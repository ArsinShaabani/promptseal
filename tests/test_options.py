"""Tests for the v0.5 options: filters, fail-fast, concurrency, --list, JSON outputs, init flags."""

import json

from typer.testing import CliRunner

from promptseal.cli import app
from promptseal.models import Case
from promptseal.runner import CaseFilter

runner = CliRunner()

SUITE = """\
suite: opts
cases:
  - id: c-pii
    prompt: "x"
    tags: [pii, security]
    asserts:
      - contains: "Echo"
  - id: c-tone
    prompt: "x"
    tags: [tone]
    asserts:
      - contains: "Echo"
  - id: c-plain
    prompt: "x"
    asserts:
      - contains: "Echo"
"""


def _project(tmp_path, provider="mock:echo"):
    (tmp_path / "promptseal.yaml").write_text(
        f"suite: opts\ncases_dir: cases\ndefaults:\n  provider: {provider}\n",
        encoding="utf-8",
    )
    (tmp_path / "cases").mkdir()
    (tmp_path / "cases" / "opts.yaml").write_text(SUITE, encoding="utf-8")


def test_case_filter_matching():
    f = CaseFilter.parse(tags="pii,security")
    assert f.matches(Case(id="a", tags=["pii"]))
    assert not f.matches(Case(id="b", tags=["tone"]))
    f2 = CaseFilter.parse(only="a,b", skip="b")
    assert f2.matches(Case(id="a"))
    assert not f2.matches(Case(id="b"))
    assert not f2.matches(Case(id="c"))
    assert CaseFilter.parse().matches(Case(id="anything"))


def _ids(result):
    return [r["case_id"] for r in json.loads(result.output)["results"]]


def test_run_tags_filter(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _project(tmp_path)
    result = runner.invoke(app, ["run", "--tags", "pii", "--json"])
    assert result.exit_code == 0, result.output
    assert _ids(result) == ["c-pii"]


def test_run_exclude_tags(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _project(tmp_path)
    result = runner.invoke(app, ["run", "--exclude-tags", "security,tone", "--json"])
    assert result.exit_code == 0, result.output
    assert _ids(result) == ["c-plain"]


def test_run_case_and_skip_case(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _project(tmp_path)
    result = runner.invoke(app, ["run", "--case", "c-tone,c-plain", "--json"])
    assert result.exit_code == 0, result.output
    assert _ids(result) == ["c-tone", "c-plain"]
    result = runner.invoke(app, ["run", "--skip-case", "c-tone", "--json"])
    assert result.exit_code == 0, result.output
    assert _ids(result) == ["c-pii", "c-plain"]


def test_run_no_match_fails(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _project(tmp_path)
    result = runner.invoke(app, ["run", "--tags", "nonexistent"])
    assert result.exit_code == 1
    assert "no cases match" in result.output


def test_run_list_makes_no_provider_call(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _project(tmp_path, provider="openai:gpt-4o")  # would need an API key if executed
    result = runner.invoke(app, ["run", "--list"])
    assert result.exit_code == 0, result.output
    assert "c-pii" in result.output and "3" in result.output
    assert not (tmp_path / ".promptseal" / "runs").exists()


def test_run_list_respects_filters(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _project(tmp_path)
    result = runner.invoke(app, ["run", "--list", "--tags", "tone"])
    assert result.exit_code == 0, result.output
    assert "c-tone" in result.output


def test_fail_fast_stops_early(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _project(tmp_path, provider="mock:denier")
    result = runner.invoke(app, ["run", "--fail-fast", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["summary"]["interrupted"] is True
    assert payload["summary"]["total"] == 1


def test_concurrency_preserves_order(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _project(tmp_path)
    result = runner.invoke(app, ["run", "--concurrency", "3", "--json"])
    assert result.exit_code == 0, result.output
    assert _ids(result) == ["c-pii", "c-tone", "c-plain"]


def test_diff_fail_on_regression(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _project(tmp_path)
    assert runner.invoke(app, ["seal"]).exit_code == 0
    runner.invoke(app, ["run", "-p", "mock:denier"])
    ok = runner.invoke(app, ["diff"])
    assert ok.exit_code == 0
    fail = runner.invoke(app, ["diff", "--fail-on-regression"])
    assert fail.exit_code == 1


def test_runs_json_marks_baseline(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _project(tmp_path)
    runner.invoke(app, ["run", "--save-baseline"])
    result = runner.invoke(app, ["runs", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data[0]["is_baseline"] is True
    assert data[0]["suite"] == "opts"


def test_init_provider_and_suite(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app, ["init", "--provider", "ollama:llama3.1:8b", "--suite", "mybot"]
    )
    assert result.exit_code == 0, result.output
    text = (tmp_path / "promptseal.yaml").read_text(encoding="utf-8")
    assert "provider: ollama:llama3.1:8b" in text
    assert "suite: mybot" in text


def test_init_rejects_provider_without_model(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init", "--provider", "nope"])
    assert result.exit_code != 0


def test_app_version_flag():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "promptseal" in result.output