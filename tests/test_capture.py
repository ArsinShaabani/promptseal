"""Tests for the in-process capture SDK (`promptseal.capture`)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from promptseal.capture import CaptureClient, CaptureError
from promptseal.record import captures_to_cases, load_captures


@pytest.fixture()
def upstream():
    hits: list[dict] = []

    class FakeUpstream(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):  # noqa: N802
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            hits.append(json.loads(body))
            resp = json.dumps(
                {"choices": [{"message": {"content": "Hi from upstream!"}}], "usage": {}}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)

    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeUpstream)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server, hits
    server.shutdown()


def _client(tmp_path, server, **kwargs):
    defaults = {
        "base_url": f"http://127.0.0.1:{server.server_address[1]}",
        "capture_path": tmp_path / "app.jsonl",
        "model": "gpt-x",
    }
    defaults.update(kwargs)
    return CaptureClient(**defaults)


def test_ask_sends_and_captures(tmp_path, upstream):
    server, hits = upstream
    client = _client(tmp_path, server, api_key="sk-test")
    reply = client.ask("hello there", system="be brief")
    assert reply == "Hi from upstream!"
    assert client.captured_count == 1
    assert len(hits) == 1
    assert hits[0]["model"] == "gpt-x"
    assert hits[0]["messages"][0] == {"role": "system", "content": "be brief"}
    assert hits[0]["messages"][1] == {"role": "user", "content": "hello there"}


def test_capture_is_redacted_and_loadable(tmp_path, upstream):
    server, _ = upstream
    client = _client(tmp_path, server)
    client.ask("email me at secret@corp.com")
    captures = load_captures(client.capture_path.parent)
    assert len(captures) == 1
    dumped = json.dumps(captures[0])
    assert "secret@corp.com" not in dumped
    assert "<EMAIL>" in captures[0]["messages"][0]["content"]


def test_sdk_captures_convert_to_cases(tmp_path, upstream):
    server, _ = upstream
    client = _client(tmp_path, server)
    client.ask("What is PromptSeal?")
    suite = captures_to_cases(client.capture_path.parent)
    assert len(suite["cases"]) == 1
    assert suite["cases"][0]["prompt"] == "What is PromptSeal?"


def test_streaming_rejected(tmp_path, upstream):
    server, _ = upstream
    client = _client(tmp_path, server)
    with pytest.raises(CaptureError):
        client.chat([{"role": "user", "content": "hi"}], stream=True)
    assert client.captured_count == 0


def test_http_error_raises(tmp_path):
    client = CaptureClient(
        base_url="http://127.0.0.1:1",
        capture_path=tmp_path / "c.jsonl",
        model="m",
        timeout_s=1,
    )
    with pytest.raises(CaptureError):
        client.ask("hi")


def test_model_required(tmp_path):
    client = CaptureClient(base_url="http://127.0.0.1:1", capture_path=tmp_path / "c.jsonl")
    with pytest.raises(CaptureError):
        client.ask("hi")