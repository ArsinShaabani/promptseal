"""Tests for baseline persistence: embedded snapshot + legacy formats."""

from promptseal import storage
from promptseal.models import CaseResult, Run, RunMeta, RunSummary


def _run(rid: str = "r1") -> Run:
    return Run(
        meta=RunMeta(
            run_id=rid,
            created_at="2026-01-01T00:00:00+00:00",
            provider="mock",
            model="m",
            suite="t",
        ),
        summary=RunSummary(total=1, passed=1, pass_rate=1.0),
        results=[CaseResult(case_id="a", status="pass")],
    )


def test_baseline_embeds_full_run_and_resolves_without_runs_dir(tmp_path):
    run = _run("r1")
    storage.save_baseline("r1", root=tmp_path, run=run)
    # No runs dir at all — the embedded snapshot must be enough (CI flow):
    assert not (tmp_path / ".promptseal" / "runs").exists()
    resolved, path = storage.resolve_run("baseline", root=tmp_path)
    assert resolved.meta.run_id == "r1"
    assert path.name == "baseline.json"


def test_baseline_legacy_run_id_with_run_file(tmp_path):
    run = _run("legacy-1")
    storage.save_run(run, tmp_path)
    storage.save_baseline("legacy-1", root=tmp_path)  # old format: run_id only
    resolved, path = storage.resolve_run("baseline", root=tmp_path)
    assert resolved.meta.run_id == "legacy-1"
    assert path.name == "legacy-1.json"


def test_baseline_legacy_missing_run_file_raises(tmp_path):
    storage.save_baseline("ghost", root=tmp_path)
    try:
        storage.resolve_run("baseline", root=tmp_path)
    except FileNotFoundError as exc:
        assert "re-seal" in str(exc)
    else:
        raise AssertionError("expected FileNotFoundError")


def test_no_baseline_raises(tmp_path):
    try:
        storage.resolve_run("baseline", root=tmp_path)
    except FileNotFoundError as exc:
        assert "no baseline" in str(exc)
    else:
        raise AssertionError("expected FileNotFoundError")


def test_corrupt_baseline_json_is_tolerated(tmp_path):
    (tmp_path / ".promptseal").mkdir()
    (tmp_path / ".promptseal" / "baseline.json").write_text("{not json", encoding="utf-8")
    assert storage.load_baseline(tmp_path) is None
    assert storage.load_baseline_run(tmp_path) is None