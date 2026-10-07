"""Tests for retry/backoff, judge cache, params passthrough, deep-merged config."""

import json

from promptseal.config import ProviderConfig, load_config
from promptseal.judge import JudgeCache, cache_key


def test_judge_cache_serves_identical_calls(tmp_path):
    answers = []

    def judge(system, user):
        answers.append(user)
        return "PASS\nlooks good"

    cache = JudgeCache("mock:echo", root=tmp_path)
    first = cache.wrap(judge)
    assert first("sys", "user") == "PASS\nlooks good"
    assert first("sys", "user") == "PASS\nlooks good"
    assert len(answers) == 1
    assert cache.hits == 1 and cache.misses == 1
    cache.persist()
    stored = json.loads((tmp_path / ".promptseal" / "judge-cache.json").read_text(encoding="utf-8"))
    assert stored[cache_key("user", "mock:echo")] == "PASS\nlooks good"

    # A fresh cache object reloads the persisted answers.
    cache2 = JudgeCache("mock:echo", root=tmp_path)
    assert cache2.wrap(judge)("sys", "user") == "PASS\nlooks good"
    assert len(answers) == 1

    # Disabled cache never reads nor persists.
    cache3 = JudgeCache("mock:echo", root=tmp_path / "elsewhere", enabled=False)
    assert cache3.wrap(judge)("sys", "other") == "PASS\nlooks good"
    assert len(answers) == 2
    cache3.persist()
    assert not (tmp_path / "elsewhere" / ".promptseal" / "judge-cache.json").exists()


def test_retry_configuration_defaults_and_overrides(tmp_path):
    def write(text):
        path = tmp_path / "promptseal.yaml"
        path.write_text(text, encoding="utf-8")
        return path

    cfg = load_config(write("suite: t\n"))
    assert cfg.retry_attempts == 3
    assert cfg.retry_backoff_s == 0.5
    assert cfg.judge_cache is True
    cfg = load_config(write("defaults:\n  retry_attempts: 0\n  retry_backoff_s: 0\n  judge_cache: false\n"))
    assert (cfg.retry_attempts, cfg.retry_backoff_s, cfg.judge_cache) == (0, 0.0, False)


def test_real_openai_tool_calls_payload():
    """A faithful OpenAI chat-completions body flows through parsing + asserts."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from promptseal.assertions import parse_asserts
    from promptseal.config import AppConfig
    from promptseal.models import Case
    from promptseal.providers import get_provider
    from promptseal.runner import run_cases

    seen = []

    class FakeOpenAI(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):  # noqa: N802
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            seen.append(json.loads(body))
            resp = json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call_abc",
                                        "type": "function",
                                        "function": {
                                            "name": "get_weather",
                                            "arguments": '{"city": "Paris"}',
                                        },
                                    }
                                ],
                            }
                        }
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)

    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOpenAI)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        cfg = AppConfig()
        cfg.providers["local"] = ProviderConfig(
            name="local",
            base_url=f"http://127.0.0.1:{server.server_address[1]}/v1",
            pricing={"input_per_1k_usd": 1.0, "output_per_1k_usd": 2.0},
        )
        case = Case(
            id="agent",
            prompt="weather?",
            tools=[{"type": "function", "function": {"name": "get_weather"}}],
            params={"temperature": 0.0},
            asserts=parse_asserts(
                [
                    {"tools_called": "get_weather"},
                    {"tool_args": {"get_weather": {"city": "Paris"}}},
                    {"max_cost_usd": 1.0},
                ]
            ),
        )
        run = run_cases([case], "t", get_provider("local:stub-model", cfg))
        result = run.results[0]
        assert result.status == "pass"
        assert result.tool_calls[0]["id"] == "call_abc"
        # temperature from the case really reached the wire payload:
        assert seen[0]["messages"][-1]["content"] == "weather?"
        assert seen[0]["temperature"] == 0.0
        # pricing flowed through usage into a real cost:
        assert result.cost_usd == (10 * 1.0 + 5 * 2.0) / 1000.0
    finally:
        server.shutdown()


def test_retry_then_success():
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from promptseal.assertions import parse_asserts
    from promptseal.config import AppConfig
    from promptseal.models import Case
    from promptseal.providers import OpenAICompatProvider, get_provider
    from promptseal.runner import run_cases

    hits = []

    class Flaky(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):  # noqa: N802
            hits.append(1)
            n = len(hits)
            code = 429 if n == 1 else (500 if n == 2 else 200)
            if code == 200:
                body = {"choices": [{"message": {"role": "assistant", "content": "hello"}}]}
            else:
                body = {"error": {"message": "busy"}}
            resp = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Flaky)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        cfg = AppConfig()
        cfg.providers["f"] = ProviderConfig(
            name="f", base_url=f"http://127.0.0.1:{server.server_address[1]}/v1"
        )
        provider = get_provider("f:m", cfg)
        assert isinstance(provider, OpenAICompatProvider)
        provider.max_retries = 5
        provider.retry_backoff_s = 0.0
        run = run_cases(
            [Case(id="r", prompt="hi", asserts=parse_asserts([{"contains": "hello"}]))],
            "t",
            provider,
        )
        assert run.results[0].status == "pass", run.results[0].error
        # 429 retries, 500 retries, then 200:
        assert len(hits) == 3
    finally:
        server.shutdown()


def test_redirect_surfaces_as_error_without_retry():
    """Non-retryable statuses fail immediately — no redirect replay, no retry storm."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from promptseal.assertions import parse_asserts
    from promptseal.config import AppConfig
    from promptseal.models import Case
    from promptseal.providers import OpenAICompatProvider, get_provider
    from promptseal.runner import run_cases

    hits = []

    class Redirector(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):  # noqa: N802
            hits.append(1)
            resp = json.dumps({"error": {"message": "redirect"}}).encode()
            self.send_response(301)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Redirector)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        cfg = AppConfig()
        cfg.providers["f"] = ProviderConfig(
            name="f", base_url=f"http://127.0.0.1:{server.server_address[1]}/v1"
        )
        provider = get_provider("f:m", cfg)
        assert isinstance(provider, OpenAICompatProvider)
        provider.max_retries = 5
        provider.retry_backoff_s = 0.0
        run = run_cases(
            [Case(id="r", prompt="hi", asserts=parse_asserts([{"contains": "x"}]))],
            "t",
            provider,
        )
        assert run.results[0].status == "error"
        assert "HTTP 301" in (run.results[0].error or "")
        assert len(hits) == 1  # surfaced, never replayed or retried
    finally:
        server.shutdown()


def test_non_retryable_400_never_retries():
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from promptseal.assertions import parse_asserts
    from promptseal.config import AppConfig
    from promptseal.models import Case
    from promptseal.providers import OpenAICompatProvider, get_provider
    from promptseal.runner import run_cases

    hits = []

    class BadRequest(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):  # noqa: N802
            hits.append(1)
            resp = json.dumps({"error": {"message": "bad request"}}).encode()
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)

    server = ThreadingHTTPServer(("127.0.0.1", 0), BadRequest)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        cfg = AppConfig()
        cfg.providers["f"] = ProviderConfig(
            name="f", base_url=f"http://127.0.0.1:{server.server_address[1]}/v1"
        )
        provider = get_provider("f:m", cfg)
        assert isinstance(provider, OpenAICompatProvider)
        provider.max_retries = 5
        provider.retry_backoff_s = 0.0
        run = run_cases(
            [Case(id="r", prompt="hi", asserts=parse_asserts([{"contains": "x"}]))],
            "t",
            provider,
        )
        assert run.results[0].status == "error"
        assert "HTTP 400" in (run.results[0].error or "")
        assert len(hits) == 1  # no retries wasted on client errors
    finally:
        server.shutdown()


def test_retry_gives_up_on_persistent_500():
    from promptseal.config import AppConfig
    from promptseal.models import Case
    from promptseal.providers import OpenAICompatProvider, get_provider
    from promptseal.runner import run_cases
    from promptseal.assertions import parse_asserts

    cfg = AppConfig()
    cfg.providers["dead"] = ProviderConfig(name="dead", base_url="http://127.0.0.1:1")
    provider = get_provider("dead:m", cfg)
    assert isinstance(provider, OpenAICompatProvider)
    provider.max_retries = 0
    run = run_cases(
        [Case(id="r", prompt="hi", asserts=parse_asserts([{"contains": "x"}]))],
        "t",
        provider,
    )
    assert run.results[0].status == "error"


def test_scoped_diff_hides_filtered_baseline_cases():
    from promptseal.diff import diff_runs
    from promptseal.models import CaseResult, Run, RunMeta, RunSummary

    def _run(rid, pairs):
        results = [CaseResult(case_id=cid, status=st) for cid, st in pairs]
        total = len(pairs)
        passed = sum(1 for _, st in pairs if st == "pass")
        return Run(
            meta=RunMeta(
                run_id=rid,
                created_at="2026-01-01T00:00:00+00:00",
                provider="mock",
                model="m",
                suite="t",
            ),
            summary=RunSummary(total=total, passed=passed, pass_rate=passed / total if total else 0.0),
            results=results,
        )

    base = _run("base", [("a", "pass"), ("b", "pass")])
    cand = _run("cand", [("a", "pass")])
    full = diff_runs(base, cand)
    assert full.missing_cases == ["b"]
    scoped = diff_runs(base, cand, only_ids={"a"})
    assert scoped.missing_cases == []
    assert scoped.verdict == "pass"


def test_provider_block_deep_merges_defaults(tmp_path):
    path = tmp_path / "promptseal.yaml"
    path.write_text("providers:\n  openai:\n    api_key_env: MY_KEY\n", encoding="utf-8")
    cfg = load_config(path)
    assert cfg.providers["openai"].api_key_env == "MY_KEY"
    assert cfg.providers["openai"].base_url == "https://api.openai.com/v1"