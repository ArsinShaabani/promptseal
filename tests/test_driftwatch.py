"""Tests for the driftwatch dashboard (module + CLI)."""

from promptseal import driftwatch, storage
from promptseal.models import CaseResult, Run, RunMeta, RunSummary


def _run(rid, provider, model, rate, ts):
    return Run(
        meta=RunMeta(run_id=rid, created_at=ts, provider=provider, model=model, suite="t"),
        summary=RunSummary(
            total=2,
            passed=int(rate * 2),
            pass_rate=rate,
            total_latency_ms=100,
            total_cost_usd=0.01,
        ),
        results=[CaseResult(case_id="a", status="pass" if rate >= 1.0 else "fail")],
    )


def test_render_html_groups_by_provider():
    runs = [
        _run("r1", "openai", "gpt-4o", 1.0, "2026-01-01T00:00:00+00:00"),
        _run("r2", "openai", "gpt-4o", 0.5, "2026-01-02T00:00:00+00:00"),
        _run("r3", "mock", "mock-echo", 1.0, "2026-01-03T00:00:00+00:00"),
    ]
    html = driftwatch.render_html(runs, generated_at="now")
    assert "openai:gpt-4o" in html and "mock:mock-echo" in html
    assert "<svg" in html and "polyline" in html
    assert html.count("<svg") >= 2
    assert "driftwatch" in html


def test_sparkline_handles_single_point():
    svg = driftwatch._sparkline([1.0])
    assert "<svg" in svg and "circle" in svg and "polyline" not in svg


def test_cli_driftwatch_writes_html(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from promptseal.cli import app

    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    storage.save_run(_run("r1", "mock", "m", 1.0, "2026-01-01T00:00:00+00:00"), tmp_path)
    storage.save_run(_run("r2", "mock", "m", 0.5, "2026-01-02T00:00:00+00:00"), tmp_path)
    result = runner.invoke(app, ["driftwatch"])
    assert result.exit_code == 0, result.output
    out = tmp_path / "promptseal-drift.html"
    assert out.exists()
    assert "mock:m" in out.read_text(encoding="utf-8")


def test_cli_driftwatch_without_runs_fails(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from promptseal.cli import app

    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["driftwatch"])
    assert result.exit_code == 1
    assert "No runs" in result.output


def test_per_case_stats_percentiles():
    runs = [
        _run("r1", "openai", "gpt-4o", 1.0, "2026-01-01T00:00:00+00:00"),
        _run("r2", "mock", "m", 1.0, "2026-01-02T00:00:00+00:00"),
    ]
    runs[0].results = [CaseResult(case_id="a", status="pass", cost_usd=0.02, latency_ms=300)]
    runs[1].results = [CaseResult(case_id="a", status="pass", cost_usd=0.01, latency_ms=100)]
    stats = driftwatch.per_case_stats(runs)
    s = stats[0]
    assert s["case_id"] == "a"
    assert s["samples"] == 2
    assert s["cost_p50"] == 0.01
    assert s["cost_p95"] == 0.02
    assert s["cost_max"] == 0.02
    assert s["latency_p50"] == 100
    assert s["latency_p95"] == 300
    assert s["cheapest_provider"] == "mock:m"


def test_html_contains_stats_section(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from promptseal.cli import app

    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    runs = [
        _run("r1", "openai", "gpt-4o", 1.0, "2026-01-01T00:00:00+00:00"),
        _run("r2", "mock", "m", 1.0, "2026-01-02T00:00:00+00:00"),
    ]
    runs[0].results = [CaseResult(case_id="a", status="pass", cost_usd=0.02, latency_ms=300)]
    runs[1].results = [CaseResult(case_id="a", status="pass", cost_usd=0.01, latency_ms=100)]
    storage.save_run(runs[0], tmp_path)
    storage.save_run(runs[1], tmp_path)
    result = runner.invoke(app, ["driftwatch"])
    assert result.exit_code == 0, result.output
    html = (tmp_path / "promptseal-drift.html").read_text(encoding="utf-8")
    assert "percentiles across providers" in html
    assert "mock:m" in html