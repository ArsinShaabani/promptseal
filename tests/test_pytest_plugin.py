"""Tests for the pytest plugin (pytester-based, offline via the mock provider)."""

import json
from pathlib import Path

PROMPTSEAL_YAML = """\
suite: smoke
cases_dir: cases

defaults:
  provider: {provider}
"""

SUITE_YAML = """\
suite: smoke
cases:
  - id: hello
    prompt: "Hello from PromptSeal!"
    asserts:
      - contains: "Echo"
      - max_latency_s: 2
"""


def _project(pytester, provider):
    pytester.makefile(".yaml", promptseal=PROMPTSEAL_YAML.format(provider=provider))
    cases = pytester.mkdir("cases")
    (cases / "smoke.yaml").write_text(SUITE_YAML, encoding="utf-8")


def test_collects_and_passes_and_persists_run(pytester):
    _project(pytester, "mock:echo")
    result = pytester.runpytest("--promptseal")
    result.assert_outcomes(passed=1)
    runs = list(Path(".promptseal", "runs").glob("*.json"))
    assert len(runs) == 1
    run = json.loads(runs[0].read_text(encoding="utf-8"))
    assert run["meta"]["suite"] == "pytest"
    assert run["meta"]["provider"] == "mock"
    assert run["meta"]["repeat"] == 1
    assert run["summary"]["passed"] == 1
    assert run["results"][0]["case_id"] == "hello"


def test_inert_without_flag(pytester):
    _project(pytester, "mock:echo")
    result = pytester.runpytest()
    result.assert_outcomes(passed=0)
    assert not Path(".promptseal", "runs").exists()


def test_failure_reports_assertion_details(pytester):
    _project(pytester, "mock:denier")
    result = pytester.runpytest("--promptseal")
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*expected output to contain*"])


def test_provider_override_flag(pytester):
    _project(pytester, "mock:echo")
    result = pytester.runpytest("--promptseal", "--ps-provider", "mock:denier")
    result.assert_outcomes(failed=1)

