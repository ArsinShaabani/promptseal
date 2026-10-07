"""Local traffic recorder — an OpenAI-compatible reverse proxy that captures chats.

Point your app's OPENAI_BASE_URL at the recorder; every request is forwarded to the
real provider and saved as a JSONL capture. Convert captures into draft eval cases
with `promptseal record --to-cases`.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional

import httpx
import yaml

_REDACTIONS = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "<EMAIL>"),
    (re.compile(r"\b(?:\d[ -]*?){13,16}\b"), "<CARD>"),
    (re.compile(r"\b(?:\+?\d[\d\s().-]{7,}\d)\b"), "<PHONE>"),
]

_DEFAULT_PORT = 8819
_CAPTURE_OUTPUT_LIMIT = 4000


def redact(text: str) -> str:
    """Mask obvious PII (emails, card numbers, phone numbers)."""
    out = text
    for pattern, replacement in _REDACTIONS:
        out = pattern.sub(replacement, out)
    return out


def _capture_entry(
    request_body: dict[str, Any],
    response_json: Optional[dict[str, Any]],
    status: int,
    latency_ms: int,
    do_redact: bool,
) -> dict[str, Any]:
    messages = request_body.get("messages", []) or []
    cleaned_messages = []
    for msg in messages:
        msg = dict(msg)
        if do_redact and isinstance(msg.get("content"), str):
            msg["content"] = redact(msg["content"])
        cleaned_messages.append(msg)

    output = ""
    try:
        output = response_json["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        output = ""
    if do_redact and isinstance(output, str):
        output = redact(output)

    parameters = {
        k: request_body[k]
        for k in ("temperature", "max_tokens", "top_p")
        if k in request_body
    }
    return {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": request_body.get("model"),
        "messages": cleaned_messages,
        "parameters": parameters,
        "status": status,
        "output": output[:_CAPTURE_OUTPUT_LIMIT],
        "latency_ms": latency_ms,
    }


class _ProxyHandler(BaseHTTPRequestHandler):
    server_version = "PromptSealRecord/0.2"

    def log_message(self, format: str, *args) -> None:  # noqa: A002 — stdlib signature
        pass  # keep the recorder quiet; the summary is printed on shutdown

    def _send(self, status: int, body: bytes, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 — stdlib naming
        # OpenAI SDKs (and LangChain) hit /models on connect — answer locally so
        # the proxy stays transparent for discovery calls.
        path = self.path.split("?", 1)[0]
        if path.rstrip("/").endswith("/models") or "/models/" in path:
            upstream_url = self.server.upstream.rstrip("/") + "/models"  # type: ignore[attr-defined]
            try:
                resp = httpx.get(
                    upstream_url,
                    headers={"Accept": "application/json"},
                    timeout=self.server.timeout_s,  # type: ignore[attr-defined]
                )
            except httpx.HTTPError as exc:
                self._send(502, json.dumps({"error": {"message": f"upstream failed: {exc}"}}).encode())
                return
            if resp.status_code != 200:
                models = {"object": "list", "data": [{"id": "promptseal-proxy", "object": "model"}]}
                self._send(200, json.dumps(models).encode())
                return
            self._send(resp.status_code, resp.content, resp.headers.get("content-type", "application/json"))
            return
        self._send(404, json.dumps({"error": {"message": "promptseal recorder only handles /v1/chat/completions"}}).encode())

    def do_POST(self) -> None:  # noqa: N802 — stdlib naming
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length)
        try:
            request_body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            self._send(400, json.dumps({"error": {"message": "invalid JSON body"}}).encode())
            return

        if request_body.get("stream"):
            self._send(
                400,
                json.dumps(
                    {
                        "error": {
                            "message": (
                                "PromptSeal recorder does not support streaming captures. "
                                "Disable streaming for the requests you want recorded."
                            )
                        }
                    }
                ).encode(),
            )
            return

        upstream_url = self.server.upstream.rstrip("/") + self.path  # type: ignore[attr-defined]
        forward_headers = {
            k: v
            for k, v in self.headers.items()
            if k.lower() in ("authorization", "content-type", "accept")
        }
        started = time.perf_counter()
        try:
            resp = httpx.post(
                upstream_url,
                content=raw,
                headers=forward_headers,
                timeout=self.server.timeout_s,  # type: ignore[attr-defined]
            )
        except httpx.HTTPError as exc:
            self._send(502, json.dumps({"error": {"message": f"upstream failed: {exc}"}}).encode())
            return
        latency_ms = int((time.perf_counter() - started) * 1000)

        self._send(resp.status_code, resp.content, resp.headers.get("content-type", "application/json"))

        try:
            response_json = resp.json() if resp.content else None
        except ValueError:
            response_json = None
        entry = _capture_entry(
            request_body,
            response_json,
            resp.status_code,
            latency_ms,
            do_redact=self.server.redact,  # type: ignore[attr-defined]
        )
        with self.server.capture_lock:  # type: ignore[attr-defined]
            with open(self.server.capture_path, "a", encoding="utf-8") as fh:  # type: ignore[attr-defined]
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self.server.captured_count += 1  # type: ignore[attr-defined]


class RecordProxy:
    """A tiny threaded reverse proxy for OpenAI-compatible chat traffic."""

    def __init__(
        self,
        upstream: str,
        capture_path: Path,
        port: int = _DEFAULT_PORT,
        timeout_s: float = 60.0,
        redact_pii: bool = True,
    ):
        self.upstream = upstream
        self.capture_path = capture_path
        self.port = port
        self.timeout_s = timeout_s
        self.redact = redact_pii
        self.captured_count = 0
        self.capture_lock = threading.Lock()
        self._httpd: Optional[ThreadingHTTPServer] = None

    def start(self) -> "RecordProxy":
        capture_path = Path(self.capture_path)
        capture_path.parent.mkdir(parents=True, exist_ok=True)
        self._httpd = ThreadingHTTPServer(("127.0.0.1", self.port), _ProxyHandler)
        self._httpd.upstream = self.upstream  # type: ignore[attr-defined]
        self._httpd.capture_path = str(capture_path)  # type: ignore[attr-defined]
        self._httpd.timeout_s = self.timeout_s  # type: ignore[attr-defined]
        self._httpd.redact = self.redact  # type: ignore[attr-defined]
        self._httpd.capture_lock = self.capture_lock  # type: ignore[attr-defined]
        self._httpd.captured_count = self.captured_count  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        self.port = self._httpd.server_address[1]
        return self

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def shutdown(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None


# ---------------------------------------------------------------------------
# Capture -> eval cases conversion
# ---------------------------------------------------------------------------

def _slug(text: str, max_len: int = 24) -> str:
    words = re.findall(r"[a-zA-Z0-9]+", text.lower())[:3]
    slug = "-".join(words) if words else "case"
    return slug[:max_len]


def _first_of(messages: list[dict], role: str) -> Optional[str]:
    for msg in messages:
        if msg.get("role") == role and isinstance(msg.get("content"), str):
            return msg["content"]
    return None


def load_captures(capture_dir: Path) -> list[dict[str, Any]]:
    """Load all JSONL captures from a directory, newest last, skipping corrupt lines."""
    captures: list[dict[str, Any]] = []
    for path in sorted(Path(capture_dir).glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                captures.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return captures


def captures_to_cases(
    capture_dir: Path,
    suite: str = "recorded",
    max_cases: int = 50,
    max_latency_s: Optional[float] = None,
) -> dict[str, Any]:
    """Turn captured traffic into a draft eval suite (deduped by first user message)."""
    captures = load_captures(capture_dir)
    seen: set[str] = set()
    cases: list[dict[str, Any]] = []

    for cap in captures:
        messages = cap.get("messages", []) or []
        prompt = _first_of(messages, "user")
        if not prompt:
            continue
        key = hashlib.sha1(prompt.encode("utf-8")).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        if len(cases) >= max_cases:
            break

        asserts: list[dict[str, Any]] = [{"not_empty": True}]
        if max_latency_s is not None:
            asserts.append({"max_latency_s": max_latency_s})

        case: dict[str, Any] = {
            "id": f"rec-{len(cases) + 1:03d}-{_slug(prompt)}",
            "description": f"Captured from real traffic on {cap.get('ts', 'unknown')}",
            "prompt": prompt,
            "asserts": asserts,
        }
        system = _first_of(messages, "system")
        if system:
            case["system"] = system
        cases.append(case)

    return {"suite": suite, "description": "Draft cases generated from recorded traffic.", "cases": cases}


def write_cases_yaml(suite_dict: dict[str, Any], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        yaml.safe_dump(suite_dict, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8",
    )
    return out_path
