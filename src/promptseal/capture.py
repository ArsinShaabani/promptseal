"""In-process capture: an OpenAI-compatible client that records traffic as JSONL.

`CaptureClient` is a tiny sync client for OpenAI-compatible /chat/completions
endpoints that writes every request/response pair in the same JSONL format the
`promptseal record` proxy uses — so `promptseal record --to-cases` converts SDK
captures into draft eval cases exactly like proxy captures.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Optional

import httpx

from promptseal.record import _capture_entry


class CaptureError(Exception):
    pass


class CaptureClient:
    """Minimal OpenAI-compatible chat client that captures every call to a JSONL file."""

    def __init__(
        self,
        base_url: str,
        capture_path: Path | str,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        redact_pii: bool = True,
        timeout_s: float = 60.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.capture_path = Path(capture_path)
        self.api_key = api_key
        self.model = model
        self.redact_pii = redact_pii
        self.timeout_s = timeout_s
        self.captured_count = 0
        self._lock = threading.Lock()

    def chat(
        self, messages: list[dict[str, str]], model: Optional[str] = None, **params: Any
    ) -> str:
        """Send a chat-completions request, return the assistant text, capture the pair."""
        used_model = model or self.model
        if not used_model:
            raise CaptureError("no model given — pass model=... or set CaptureClient(model=...)")
        if params.get("stream"):
            raise CaptureError("SDK capture does not support streaming responses")
        body: dict[str, Any] = {"model": used_model, "messages": messages, **params}

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        started = time.perf_counter()
        try:
            resp = httpx.post(
                f"{self.base_url}/chat/completions",
                json=body,
                headers=headers,
                timeout=self.timeout_s,
            )
        except httpx.HTTPError as exc:
            raise CaptureError(f"request to {self.base_url} failed: {exc}") from exc
        latency_ms = int((time.perf_counter() - started) * 1000)

        if resp.status_code != 200:
            raise CaptureError(
                f"HTTP {resp.status_code} from {self.base_url}: {resp.text[:300]}"
            )
        try:
            response_json = resp.json()
            text = response_json["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, ValueError) as exc:
            raise CaptureError(f"unexpected response body: {exc}") from exc

        entry = _capture_entry(
            body,
            response_json,
            resp.status_code,
            latency_ms,
            do_redact=self.redact_pii,
        )
        self._append(entry)
        return text

    def ask(
        self,
        prompt: str,
        system: Optional[str] = None,
        model: Optional[str] = None,
        **params: Any,
    ) -> str:
        """Sugar for chat(): one user prompt (+ optional system prompt)."""
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return self.chat(messages, model=model, **params)

    def _append(self, entry: dict[str, Any]) -> None:
        self.capture_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with open(self.capture_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self.captured_count += 1