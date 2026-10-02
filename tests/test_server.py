"""Tests for the read-only local server + ci webhook alerts."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
from typer.testing import CliRunner

from promptseal import server as server_mod, storage
from promptseal.cli import app
from promptseal.models import CaseResult, Run, RunMeta, RunSummary

runner = CliRunner()


def _run(rid, rate=1.0):
    return Run(
        meta=RunMeta(
            run_id=rid,
            created_at="2026-01-01T00:00:00+00:00",
            provider="mock",
            model="m",
            suite="t",
        ),
        summary=RunSummary(
            total=1,
            passed=int(rate),
            pass_rate=rate,
            total_cost_usd=0.01,
            total_latency_ms=100,
        ),
        results=[CaseResult(case_id="a", status="pass" if rate >= 1.0 else "fail", cost_usd=0.01)],
    )


def _project(tmp_path):
    (tmp_path / "promptseal.yaml").write_text(
        "suite: t\ncases_dir: cases\ndefaults:\n  provider: mock:echo\n", encoding="utf-8"
    )
    cases = tmp_path / "cases"
    cases.mkdir(exist_ok=True)
    (cases / "t.yaml").write_text(
        "suite: t\ncases:\n  - id: ok\n    prompt: hi\n    asserts: [{contains: Echo}]\n",
        encoding="utf-8",
    )


def test_server_endpoints(tmp_path):
    r1, r2 = _run("srv-alpha"), _run("srv-beta", 0.5)
    r1.meta.created_at = "2026-01-01T00:00:00+00:00"
    r2.meta.created_at = "2026-01-02T00:00:00+00:00"
    storage.save_run(r1, tmp_path)
    storage.save_run(r2, tmp_path)
    srv = server_mod.PromptSealServer(root=tmp_path, port=0).start()
    try:
        html = httpx.get(f"{srv.base_url}/", timeout=5)
        assert html.status_code == 200 and "PromptSeal" in html.text

        runs = httpx.get(f"{srv.base_url}/api/runs", timeout=5).json()
        assert [r["run_id"] for r in runs] == ["srv-beta", "srv-alpha"]
        assert runs[0]["pass_rate"] == 0.5

        full = httpx.get(f"{srv.base_url}/api/runs/srv-alpha", timeout=5).json()
        assert full["meta"]["run_id"] == "srv-alpha"

        # Unique prefix resolves; ambiguous prefix 404s.
        prefix = httpx.get(f"{srv.base_url}/api/runs/srv-a", timeout=5).json()
        assert prefix["meta"]["run_id"] == "srv-alpha"
        ambiguous = httpx.get(f"{srv.base_url}/api/runs/srv", timeout=5)
        assert ambiguous.status_code == 404

        missing = httpx.get(f"{srv.base_url}/api/runs/ghost", timeout=5)
        assert missing.status_code == 404

        stats = httpx.get(f"{srv.base_url}/api/stats", timeout=5).json()
        assert stats[0]["case_id"] == "a"

        health = httpx.get(f"{srv.base_url}/api/health", timeout=5).json()
        assert health == {"ok": True, "runs": 2}

        unknown = httpx.get(f"{srv.base_url}/api/nope", timeout=5)
        assert unknown.status_code == 404
    finally:
        srv.shutdown()


class _Webhook(BaseHTTPRequestHandler):
    received = []

    def log_message(self, *args):
        pass

    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        type(self).received.append(json.loads(body))
        resp = b"{}"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)


def test_ci_sends_webhook_and_audits(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _project(tmp_path)
    hook = ThreadingHTTPServer(("127.0.0.1", 0), _Webhook)
    threading.Thread(target=hook.serve_forever, daemon=True).start()
    try:
        (tmp_path / "promptseal.yaml").write_text(
            "suite: t\ncases_dir: cases\n"
            "defaults:\n  provider: mock:echo\n"
            "ci:\n  alert_webhook: http://127.0.0.1:%d/hook\n" % hook.server_address[1],
            encoding="utf-8",
        )
        # First run seals the baseline (also audited), then ci posts the webhook.
        assert runner.invoke(app, ["seal"]).exit_code == 0
        result = runner.invoke(app, ["ci"])
        assert result.exit_code == 0, result.output
        assert "webhook alert sent" in result.output
        assert len(_Webhook.received) == 1
        payload = _Webhook.received[0]
        assert payload["event"] == "promptseal_ci"
        assert payload["verdict"] == "pass"
        assert payload["failed"] is False

        events = storage.read_audit()
        kinds = [e["event"] for e in events]
        assert "seal" in kinds and "ci" in kinds
    finally:
        hook.shutdown()


def test_webhook_failure_does_not_break_gate(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _project(tmp_path)
    (tmp_path / "promptseal.yaml").write_text(
        "suite: t\ncases_dir: cases\n"
        "defaults:\n  provider: mock:echo\n"
        "ci:\n  alert_webhook: http://127.0.0.1:1/hook\n",  # nothing listens here
        encoding="utf-8",
    )
    assert runner.invoke(app, ["seal"]).exit_code == 0
    result = runner.invoke(app, ["ci"])
    assert result.exit_code == 0, result.output
    assert "webhook alert failed" in result.output


def test_audit_command_lists_events(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _project(tmp_path)
    runner.invoke(app, ["seal"])
    result = runner.invoke(app, ["audit"])
    assert result.exit_code == 0, result.output
    assert "seal" in result.output