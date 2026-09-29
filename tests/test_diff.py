"""Diff logic tests."""

from promptseal.diff import diff_runs
from promptseal.models import CaseResult, Run, RunMeta, RunSummary


def _run(rid, statuses):
    results = [CaseResult(case_id=cid, status=st) for cid, st in statuses]
    total = len(statuses)
    passed = sum(1 for _, st in statuses if st == "pass")
    return Run(
        meta=RunMeta(
            run_id=rid,
            created_at="2026-01-01T00:00:00+00:00",
            provider="mock",
            model="m",
            suite="t",
        ),
        summary=RunSummary(
            total=total,
            passed=passed,
            failed=total - passed,
            pass_rate=passed / total if total else 0.0,
        ),
        results=results,
    )


def test_regression_detection():
    base = _run("base", [("a", "pass"), ("b", "pass"), ("c", "fail")])
    cand = _run("cand", [("a", "pass"), ("b", "fail"), ("c", "fail")])
    diff = diff_runs(base, cand)
    assert [cid for cid, _, _ in diff.regressions] == ["b"]
    assert diff.verdict == "regression"


def test_improvement_detection():
    base = _run("base", [("a", "fail")])
    cand = _run("cand", [("a", "pass")])
    diff = diff_runs(base, cand)
    assert [cid for cid, _, _ in diff.improvements] == ["a"]
    assert diff.verdict == "pass"


def test_new_and_missing_cases():
    base = _run("base", [("a", "pass"), ("gone", "pass")])
    cand = _run("cand", [("a", "pass"), ("fresh", "pass")])
    diff = diff_runs(base, cand)
    assert diff.new_cases == ["fresh"]
    assert diff.missing_cases == ["gone"]
    assert diff.verdict == "pass"


def test_stable_fail_is_not_regression():
    base = _run("base", [("a", "fail")])
    cand = _run("cand", [("a", "fail")])
    diff = diff_runs(base, cand)
    assert not diff.regressions
    assert diff.stable_fail == ["a"]
    assert diff.verdict == "pass"


def test_pass_rate_drop_without_status_regression():
    # Same statuses, but candidate has a new failing case -> overall rate drops.
    base = _run("base", [("a", "pass")])
    cand = _run("cand", [("a", "pass"), ("b", "fail")])
    diff = diff_runs(base, cand)
    assert diff.new_cases == ["b"]
    assert diff.verdict == "regression"
