"""End-to-end CLI tests using the offline mock provider."""

import json
import os
from pathlib import Path

from typer.testing import CliRunner

from promptseal.cli import app

runner = CliRunner()


def _in_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_version():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "promptseal" in result.output


def test_init_creates_files(tmp_path, monkeypatch):
    _in_tmp(tmp_path, monkeypatch)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output
    assert Path("promptseal.yaml").exists()
    assert Path("cases/smoke.yaml").exists()


def test_full_workflow_init_run_baseline_diff_ci(tmp_path, monkeypatch):
    _in_tmp(tmp_path, monkeypatch)
    assert runner.invoke(app, ["init"]).exit_code == 0

    # 1) Baseline run with the passing mock provider.
    result = runner.invoke(app, ["run", "--provider", "mock:echo", "--save-baseline"])
    assert result.exit_code == 0, result.output
    assert "baseline sealed" in result.output

    # 2) Candidate run with the denier mock -> cases fail -> run exits 1.
    result = runner.invoke(app, ["run", "--provider", "mock:denier"])
    assert result.exit_code == 1, result.output

    # 3) Diff baseline vs latest shows regressions.
    result = runner.invoke(app, ["diff"])
    assert result.exit_code == 0, result.output
    assert "REGRESSION" in result.output

    # 4) CI mode fails the build on regressions.
    result = runner.invoke(app, ["ci", "--provider", "mock:denier"])
    assert result.exit_code == 1, result.output

    # 5) CI mode passes when behavior matches the baseline.
    result = runner.invoke(app, ["ci", "--provider", "mock:echo"])
    assert result.exit_code == 0, result.output
    assert "Sealed" in result.output


def test_runs_command_lists_runs(tmp_path, monkeypatch):
    _in_tmp(tmp_path, monkeypatch)
    runner.invoke(app, ["init"])
    runner.invoke(app, ["run", "--provider", "mock:echo"])
    result = runner.invoke(app, ["runs"])
    assert result.exit_code == 0, result.output
    assert "mock-echo" in result.output


def test_report_command_generates_html(tmp_path, monkeypatch):
    _in_tmp(tmp_path, monkeypatch)
    runner.invoke(app, ["init"])
    runner.invoke(app, ["run", "--provider", "mock:echo"])
    result = runner.invoke(app, ["report", "latest", "--out", "r.html"])
    assert result.exit_code == 0, result.output
    content = Path("r.html").read_text(encoding="utf-8")
    assert "PromptSeal" in content
    assert "</html>" in content


def test_seal_command_sets_baseline(tmp_path, monkeypatch):
    _in_tmp(tmp_path, monkeypatch)
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["seal", "--provider", "mock:echo"])
    assert result.exit_code == 0, result.output
    assert "sealed" in result.output
    from promptseal import storage

    baseline_id = storage.load_baseline()
    assert baseline_id is not None
    assert "mock-echo" in baseline_id


def test_matrix_comparison(tmp_path, monkeypatch):
    _in_tmp(tmp_path, monkeypatch)
    runner.invoke(app, ["init"])
    result = runner.invoke(
        app, ["run", "-p", "mock:echo", "-p", "mock:denier", "--html"]
    )
    assert result.exit_code == 0, result.output
    assert "Recommended" in result.output
    assert Path("promptseal-matrix.html").exists()
    html = Path("promptseal-matrix.html").read_text(encoding="utf-8")
    assert "model comparison" in html


def test_run_json_output(tmp_path, monkeypatch):
    _in_tmp(tmp_path, monkeypatch)
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["run", "--provider", "mock:echo", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["summary"]["total"] == 2
    assert payload["meta"]["provider"] == "mock"


def test_diff_json_output(tmp_path, monkeypatch):
    _in_tmp(tmp_path, monkeypatch)
    runner.invoke(app, ["init"])
    runner.invoke(app, ["run", "--provider", "mock:echo", "--save-baseline"])
    runner.invoke(app, ["run", "--provider", "mock:denier"])
    result = runner.invoke(app, ["diff", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["verdict"] == "regression"
    assert set(payload["regressions"]) == {"echo-greeting", "echo-content"}
