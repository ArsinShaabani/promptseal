"""promptseal server — optional, read-only local web UI over a run history.

Stdlib only (no extra dependencies): serves the driftwatch dashboard and a small
JSON API from `.promptseal/runs/`. Binds to 127.0.0.1 only — your data never
leaves the machine, and there are no write endpoints: seals happen through git,
so RBAC is exactly your git provider's permission model.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from promptseal import driftwatch, storage


class _Handler(BaseHTTPRequestHandler):
    server_version = "PromptSealServer/0.1"

    def log_message(self, format: str, *args) -> None:  # noqa: A002 — stdlib signature
        pass  # keep the server quiet; the CLI banner is the UX

    def _send(self, status: int, body: bytes, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 — stdlib naming
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        root: Path = self.server.runs_root  # type: ignore[attr-defined]
        runs = storage.list_runs(root)

        if path in ("/", "/dashboard"):
            html = driftwatch.render_html(runs, generated_at="promptseal server (live)")
            self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/api/runs":
            payload = [
                {
                    "run_id": r.meta.run_id,
                    "created_at": r.meta.created_at,
                    "provider": r.meta.provider,
                    "model": r.meta.model,
                    "suite": r.meta.suite,
                    "pass_rate": r.summary.pass_rate,
                    "total": r.summary.total,
                    "total_latency_ms": r.summary.total_latency_ms,
                    "total_cost_usd": r.summary.total_cost_usd,
                }
                for r in runs
            ]
            self._send(200, json.dumps(payload, indent=2).encode("utf-8"))
        elif path.startswith("/api/runs/"):
            run_id = path.rsplit("/", 1)[-1]
            run_path = storage.runs_dir(root) / f"{run_id}.json"
            if run_path.exists():
                self._send(200, run_path.read_bytes())
                return
            matches = [r for r in runs if r.meta.run_id.startswith(run_id)]
            if len(matches) == 1:
                exact = storage.runs_dir(root) / f"{matches[0].meta.run_id}.json"
                self._send(200, exact.read_bytes())
                return
            self._send(404, json.dumps({"error": f"run not found: {run_id}"}).encode())
        elif path == "/api/stats":
            self._send(200, json.dumps(driftwatch.per_case_stats(runs), indent=2).encode("utf-8"))
        elif path == "/api/health":
            self._send(200, json.dumps({"ok": True, "runs": len(runs)}).encode("utf-8"))
        else:
            self._send(404, json.dumps({"error": "not found"}).encode())


class PromptSealServer:
    """Tiny threaded read-only server over one project's `.promptseal/` store."""

    def __init__(self, root: Optional[Path] = None, port: int = 8800):
        self.root = Path(root) if root else Path.cwd()
        self.port = port
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> "PromptSealServer":
        self._httpd = ThreadingHTTPServer(("127.0.0.1", self.port), _Handler)
        self._httpd.runs_root = self.root  # type: ignore[attr-defined]
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