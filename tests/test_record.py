"""Tests for the traffic recorder and capture-to-cases conversion."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import yaml

from promptseal.record import (
    RecordProxy,
    captures_to_cases,
    redact,
    write_cases_yaml,
)


def test_redact_masks_pii():
    text = "contact me at jane.doe@example.com or 4111 1111 1111 1111 or +1 (555) 123-4567"
    out = redact(text)
    assert "jane.doe@example.com" not in out
    assert "4111" not in out
    assert "<EMAIL>" in out
    assert "<CARD>" in out


def test_proxy_captures_and_forwards(tmp_path):
    upstream_hits = []

    class FakeUpstream(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):  # noqa: N802
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            upstream_hits.append(json.loads(body))
            resp = json.dumps(
                {"choices": [{"message": {"content": "Hello from upstream!"}}], "usage": {}}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), FakeUpstream)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()

    capture_path = tmp_path / "captures" / "capture-test.jsonl"
    proxy = RecordProxy(
        upstream=f"http://127.0.0.1:{upstream.server_address[1]}",
        capture_path=capture_path,
        port=0,
        timeout_s=5,
    ).start()
    try:
        resp = httpx.post(
            f"{proxy.base_url}/v1/chat/completions",
            json={
                "model": "gpt-x",
                "messages": [
                    {"role": "user", "content": "email me at secret@corp.com please"}
                ],
            },
            timeout=5,
        )
        assert resp.status_code == 200
        assert resp.json()["choices"][0]["message"]["content"] == "Hello from upstream!"
        assert len(upstream_hits) == 1
    finally:
        proxy.shutdown()
        upstream.shutdown()

    lines = capture_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["model"] == "gpt-x"
    assert entry["output"] == "Hello from upstream!"
    assert entry["latency_ms"] >= 0
    assert "secret@corp.com" not in json.dumps(entry)  # redacted
    assert "<EMAIL>" in entry["messages"][0]["content"]


def test_proxy_blocks_streaming(tmp_path):
    capture_path = tmp_path / "captures" / "s.jsonl"
    proxy = RecordProxy(
        upstream="http://127.0.0.1:1", capture_path=capture_path, port=0, timeout_s=5
    ).start()
    try:
        resp = httpx.post(
            f"{proxy.base_url}/v1/chat/completions",
            json={"model": "m", "messages": [{"role": "user", "content": "hi"}], "stream": True},
            timeout=5,
        )
        assert resp.status_code == 400
        assert "streaming" in resp.json()["error"]["message"].lower()
    finally:
        proxy.shutdown()


def test_captures_to_cases_dedupes(tmp_path):
    capture_path = tmp_path / "cap.jsonl"
    entry1 = {
        "ts": "2026-09-29T00:00:00+00:00",
        "model": "gpt-4o",
        "messages": [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "What is PromptSeal?"},
        ],
        "status": 200,
        "output": "A regression testing tool.",
        "latency_ms": 100,
    }
    entry2 = dict(entry1, messages=[{"role": "user", "content": "Different question"}])
    entry3 = dict(entry1)  # duplicate of entry1 -> must be dropped
    capture_path.write_text(
        "\n".join(json.dumps(e) for e in (entry1, entry2, entry3)), encoding="utf-8"
    )
    suite = captures_to_cases(tmp_path, suite="my-suite", max_latency_s=5)
    assert suite["suite"] == "my-suite"
    assert len(suite["cases"]) == 2
    first = suite["cases"][0]
    assert first["prompt"] == "What is PromptSeal?"
    assert first["system"] == "You are helpful."
    assert first["id"].startswith("rec-001-")
    assert {"not_empty": True} in first["asserts"]
    assert {"max_latency_s": 5} in first["asserts"]


def test_write_cases_yaml_roundtrip(tmp_path):
    suite = captures_to_cases(
        tmp_path, suite="rt",
    )
    assert suite["cases"] == []
    suite["cases"].append({"id": "rec-001-x", "prompt": "hi", "asserts": [{"not_empty": True}]})
    out = write_cases_yaml(suite, tmp_path / "cases" / "recorded.yaml")
    loaded = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert loaded["suite"] == "rt"
    assert loaded["cases"][0]["prompt"] == "hi"