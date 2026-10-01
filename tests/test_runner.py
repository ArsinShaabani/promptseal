"""Runner tests using the deterministic mock provider."""

import yaml

from promptseal.config import AppConfig
from promptseal.runner import run_cases
from promptseal.models import Case
from promptseal.providers import Completion, get_provider


def _case(cid, prompt, asserts):
    return Case(id=cid, prompt=prompt, asserts=asserts)


def _specs(raw):
    from promptseal.assertions import parse_asserts

    return parse_asserts(raw)


def test_run_cases_mixed_results():
    provider = get_provider("mock:echo", AppConfig())
    cases = [
        _case("ok", "hello", _specs([{"contains": "Echo"}])),
        _case("bad", "hello", _specs([{"contains": "NEVER"}])),
    ]
    run = run_cases(cases, suite_name="t", provider=provider)
    assert run.summary.total == 2
    assert run.summary.passed == 1
    assert run.summary.failed == 1
    assert run.summary.pass_rate == 0.5
    assert run.meta.provider == "mock"
    assert run.meta.suite == "t"
    statuses = {r.case_id: r.status for r in run.results}
    assert statuses == {"ok": "pass", "bad": "fail"}


def test_run_cases_provider_error_is_recorded():
    from promptseal.providers import OpenAICompatProvider

    provider = OpenAICompatProvider(name="broken", model="m", base_url="http://127.0.0.1:1", timeout_s=1)
    run = run_cases([_case("c1", "hi", _specs([{"contains": "x"}]))], "t", provider)
    assert run.results[0].status == "error"
    assert run.summary.errors == 1


def test_vars_rendering():
    provider = get_provider("mock:echo", AppConfig())
    case = Case(id="v", prompt="name is {{name}}", asserts=_specs([{"contains": "Zara"}]))
    case = case.model_copy(update={"vars": {"name": "Zara"}})
    run = run_cases([case], "t", provider)
    assert "Zara" in run.results[0].output


def test_load_suites_from_dir(tmp_path):
    cases_file = tmp_path / "cases" / "s.yaml"
    cases_file.parent.mkdir()
    cases_file.write_text(
        yaml.safe_dump(
            {
                "suite": "demo",
                "cases": [
                    {"id": "a", "prompt": "p", "asserts": [{"contains": "Echo"}]},
                ],
            }
        ),
        encoding="utf-8",
    )
    from promptseal.runner import load_suites

    suites = load_suites(cases_file.parent)
    assert len(suites) == 1
    assert suites[0].name == "demo"
    assert suites[0].cases[0].id == "a"


def test_execute_matrix(tmp_path):
    from promptseal.runner import execute_matrix

    cases_file = tmp_path / "cases" / "s.yaml"
    cases_file.parent.mkdir()
    cases_file.write_text(
        yaml.safe_dump(
            {
                "suite": "demo",
                "cases": [
                    {"id": "a", "prompt": "p", "asserts": [{"contains": "Echo"}]},
                ],
            }
        ),
        encoding="utf-8",
    )
    config = AppConfig()
    config.cases_dir = str(cases_file.parent)
    runs = execute_matrix(config, ["mock:echo", "mock:denier"], cases_dir=cases_file.parent, root=tmp_path)
    assert len(runs) == 2
    assert runs[0].summary.pass_rate == 1.0
    assert runs[1].summary.pass_rate == 0.0
    # both runs persisted
    from promptseal import storage

    assert len(storage.list_runs(tmp_path)) == 2


class _FlakyProvider:
    """Cycles through canned outputs; satisfies the Provider protocol."""

    name = "flaky"
    model = "flaky-1"

    def __init__(self, outputs):
        self.outputs = outputs
        self.calls = 0

    def complete(self, system, prompt):
        text = self.outputs[self.calls % len(self.outputs)]
        self.calls += 1
        return Completion(
            text=text, latency_ms=10, cost_usd=0.0, model=self.model, provider=self.name
        )


def test_repeat_aggregates_attempts():
    provider = _FlakyProvider(["Echo: ok", "nope", "Echo: ok", "nope"])
    cases = [_case("c", "hello", _specs([{"contains": "Echo"}]))]
    run = run_cases(cases, "t", provider, repeat=4, flaky_pass_rate=0.5)
    r = run.results[0]
    assert r.attempts == 4
    assert r.passed_attempts == 2
    assert r.status == "pass"
    assert run.meta.repeat == 4
    assert run.meta.flaky_pass_rate == 0.5


def test_repeat_fails_below_threshold():
    provider = _FlakyProvider(["Echo: ok", "nope", "nope"])
    cases = [_case("c", "hello", _specs([{"contains": "Echo"}]))]
    run = run_cases(cases, "t", provider, repeat=3, flaky_pass_rate=0.8)
    r = run.results[0]
    assert r.passed_attempts == 1
    assert r.attempts == 3
    assert r.status == "fail"
    # The representative attempt is a failing one, so details explain the failure:
    assert not r.assertion_results[0].passed


def test_repeat_all_errors_status_error():
    from promptseal.providers import OpenAICompatProvider

    provider = OpenAICompatProvider(
        name="broken", model="m", base_url="http://127.0.0.1:1", timeout_s=1
    )
    cases = [_case("c", "hi", _specs([{"contains": "x"}]))]
    run = run_cases(cases, "t", provider, repeat=2)
    r = run.results[0]
    assert r.status == "error"
    assert r.attempts == 2
    assert r.passed_attempts == 0


def test_single_attempt_has_no_attempt_fields():
    provider = get_provider("mock:echo", AppConfig())
    run = run_cases([_case("c", "hi", _specs([{"contains": "Echo"}]))], "t", provider)
    assert run.results[0].attempts is None
    assert run.results[0].passed_attempts is None
    assert run.meta.repeat == 1
