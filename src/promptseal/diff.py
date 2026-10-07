"""Compare two runs and classify every case: regression, improvement, or stable."""

from __future__ import annotations

from dataclasses import dataclass, field

from promptseal.models import CaseResult, Run


@dataclass
class DiffReport:
    baseline_run_id: str
    candidate_run_id: str
    baseline_pass_rate: float
    candidate_pass_rate: float
    regressions: list[tuple[str, CaseResult, CaseResult]] = field(default_factory=list)
    improvements: list[tuple[str, CaseResult, CaseResult]] = field(default_factory=list)
    stable_pass: list[str] = field(default_factory=list)
    stable_fail: list[str] = field(default_factory=list)
    new_cases: list[str] = field(default_factory=list)
    missing_cases: list[str] = field(default_factory=list)
    verdict: str = "pass"  # "pass" | "regression"

    @property
    def has_regressions(self) -> bool:
        return len(self.regressions) > 0


def diff_runs(baseline: Run, candidate: Run, only_ids=None) -> DiffReport:
    """Compare baseline vs candidate. With only_ids, ignore every other case id.

    Used by filtered CI runs (--tags/--case/...): baseline-only cases disappear
    from missing_cases instead of showing up as noise next to the real verdict.
    """
    base_results = {r.case_id: r for r in baseline.results}
    cand_results = {r.case_id: r for r in candidate.results}
    if only_ids is not None:
        base_results = {k: v for k, v in base_results.items() if k in only_ids}
        cand_results = {k: v for k, v in cand_results.items() if k in only_ids}

    report = DiffReport(
        baseline_run_id=baseline.meta.run_id,
        candidate_run_id=candidate.meta.run_id,
        baseline_pass_rate=baseline.summary.pass_rate,
        candidate_pass_rate=candidate.summary.pass_rate,
    )

    for case_id, cand in cand_results.items():
        base = base_results.get(case_id)
        if base is None:
            report.new_cases.append(case_id)
            continue
        if base.status == "pass" and cand.status != "pass":
            report.regressions.append((case_id, base, cand))
        elif base.status != "pass" and cand.status == "pass":
            report.improvements.append((case_id, base, cand))
        elif base.status == "pass" and cand.status == "pass":
            report.stable_pass.append(case_id)
        else:
            report.stable_fail.append(case_id)

    for case_id in base_results:
        if case_id not in cand_results:
            report.missing_cases.append(case_id)

    no_regressions = not report.regressions
    rate_ok = candidate.summary.pass_rate >= baseline.summary.pass_rate - 1e-9
    report.verdict = "pass" if (no_regressions and rate_ok) else "regression"
    return report
