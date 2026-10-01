"""Tests for the `promptseal doctor` self-check command."""

from typer.testing import CliRunner

from promptseal.cli import app

runner = CliRunner()


def test_doctor_passes_in_initialized_project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["init"]).exit_code == 0
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "All checks passed" in result.output
    assert "assertion registry" in result.output
    assert "checks registered" in result.output


def test_doctor_warns_but_passes_without_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "defaults in use" in result.output


def test_doctor_fails_on_unresolvable_provider(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "promptseal.yaml").write_text(
        "defaults:\n  provider: openai:gpt-4o\n", encoding="utf-8"
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "OPENAI_API_KEY" in result.output