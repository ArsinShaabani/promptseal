"""Suite loading and run execution."""

from __future__ import annotations

import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from promptseal._version import __version__
from promptseal.assertions import CheckContext, JudgeFn, parse_asserts, run_asserts
from promptseal.config import AppConfig
from promptseal.models import Case, CaseResult, Run, RunMeta, RunSummary, Suite
from promptseal.providers import Provider, ProviderError, get_provider
from promptseal import storage


def load_suite_file(path: Path) -> Suite:
    """Load a single suite YAML file."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw_cases = raw.get("cases") or []
    cases: list[Case] = []
    for i, rc in enumerate(raw_cases):
        if not isinstance(rc, dict) or "id" not in rc or ("prompt" not in rc and "messages" not in rc):
            raise ValueError(
                f"{path.name}: case #{i + 1} must be a mapping with 'id' and 'prompt' or 'messages'"
            )
        cases.append(
            Case(
                id=str(rc["id"]),
                prompt=str(rc.get("prompt") or ""),
                system=rc.get("system"),
                description=rc.get("description"),
                vars=rc.get("vars", {}) or {},
                asserts=parse_asserts(rc.get("asserts") or []),
                tags=rc.get("tags", []) or [],
                messages=rc.get("messages"),
                tools=rc.get("tools"),
                tool_choice=rc.get("tool_choice"),
            )
        )
    return Suite(
        name=str(raw.get("suite") or path.stem),
        source_file=str(path),
        description=raw.get("description"),
        cases=cases,
    )


def load_suites(cases_dir: Path) -> list[Suite]:
    """Load every *.yaml / *.yml file in cases_dir as a suite."""
    if not cases_dir.exists():
        raise FileNotFoundError(f"cases directory not found: {cases_dir}")
    files = sorted([*cases_dir.glob("*.yaml"), *cases_dir.glob("*.yml")])
    if not files:
        raise FileNotFoundError(f"no suite files (*.yaml) found in {cases_dir}")
    return [load_suite_file(path) for path in files]


def _render(text: str, variables: dict) -> str:
    for key, value in variables.items():
        text = text.replace("{{" + str(key) + "}}", str(value))
    return text


def _git_commit() -> Optional[str]:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if out.returncode == 0:
            return out.stdout.strip() or None
    except Exception:  # noqa: BLE001
        pass
    return None


def _judge_fn(judge_provider: Provider) -> JudgeFn:
    def judge(system: str, user: str) -> str:
        return judge_provider.complete(system, user).text

    return judge


def _run_case_once(case: Case, provider: Provider, judge_fn: Optional[JudgeFn]) -> CaseResult:
    """One attempt of a single case."""
    try:
        if case.messages is not None:
            chat = []
            for m in case.messages:
                if not isinstance(m, dict):
                    continue
                item = dict(m)
                if isinstance(item.get("content"), str):
                    item["content"] = _render(item["content"], case.vars)
                chat.append(item)
            completion = provider.complete(
                messages=chat, tools=case.tools, tool_choice=case.tool_choice
            )
        else:
            system = _render(case.system, case.vars) if case.system else None
            completion = provider.complete(
                system,
                _render(case.prompt, case.vars),
                tools=case.tools,
                tool_choice=case.tool_choice,
            )
    except ProviderError as exc:
        return CaseResult(case_id=case.id, status="error", error=str(exc))

    ctx = CheckContext(
        latency_ms=completion.latency_ms,
        cost_usd=completion.cost_usd,
        judge_fn=judge_fn,
        tool_calls=completion.tool_calls,
    )
    assertion_results = run_asserts(case.asserts, completion.text, ctx)
    failed = [a for a in assertion_results if not a.passed]
    status = "fail" if failed else "pass"
    return CaseResult(
        case_id=case.id,
        status=status,
        output=completion.text,
        latency_ms=completion.latency_ms,
        cost_usd=completion.cost_usd,
        assertion_results=assertion_results,
        tool_calls=completion.tool_calls,
    )


def _aggregate_attempts(
    case: Case, attempts: list[CaseResult], flaky_pass_rate: float
) -> CaseResult:
    """Combine repeat > 1 attempts of one case into a single result (flaky detection).

    The case passes when at least `flaky_pass_rate` of its attempts passed. The
    representative attempt (whose output/details are kept) is the first failing
    attempt, or the first passing one when nothing failed.
    """
    passed = sum(1 for a in attempts if a.status == "pass")
    ratio_ok = (passed / len(attempts)) >= flaky_pass_rate - 1e-9
    if ratio_ok:
        status = "pass"
        representative = next((a for a in attempts if a.status == "pass"), attempts[-1])
    else:
        representative = next((a for a in attempts if a.status != "pass"), attempts[-1])
        status = representative.status
    costs = [a.cost_usd for a in attempts if a.cost_usd is not None]
    return CaseResult(
        case_id=case.id,
        status=status,
        output=representative.output,
        latency_ms=round(sum(a.latency_ms for a in attempts) / len(attempts)),
        cost_usd=(sum(costs) / len(costs)) if costs else None,
        assertion_results=representative.assertion_results,
        error=representative.error,
        attempts=len(attempts),
        passed_attempts=passed,
    )


def run_cases(
    cases: list[Case],
    suite_name: str,
    provider: Provider,
    judge_fn: Optional[JudgeFn] = None,
    repeat: int = 1,
    flaky_pass_rate: float = 1.0,
) -> Run:
    """Execute cases sequentially against one provider and return a Run.

    With repeat > 1 every case runs N times (flaky detection): it passes only
    when at least `flaky_pass_rate` of the attempts pass.
    """
    repeat = max(1, int(repeat))
    started = time.perf_counter()
    results: list[CaseResult] = []
    for case in cases:
        attempts = [_run_case_once(case, provider, judge_fn) for _ in range(repeat)]
        if repeat == 1:
            results.append(attempts[0])
        else:
            results.append(_aggregate_attempts(case, attempts, flaky_pass_rate))

    total = len(results)
    passed = sum(1 for r in results if r.status == "pass")
    errors = sum(1 for r in results if r.status == "error")
    failed = sum(1 for r in results if r.status == "fail")
    costs = [r.cost_usd for r in results if r.cost_usd is not None]

    run_id = (
        f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-"
        f"{provider.name}-{provider.model}".replace("/", "-").replace(":", "-")
    )
    return Run(
        meta=RunMeta(
            run_id=run_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            provider=provider.name,
            model=provider.model,
            suite=suite_name,
            git_commit=_git_commit(),
            promptseal_version=__version__,
            repeat=repeat,
            flaky_pass_rate=flaky_pass_rate,
        ),
        summary=RunSummary(
            total=total,
            passed=passed,
            failed=failed,
            errors=errors,
            pass_rate=(passed / total) if total else 0.0,
            total_cost_usd=sum(costs) if costs else None,
            total_latency_ms=sum(r.latency_ms for r in results),
            duration_s=round(time.perf_counter() - started, 3),
        ),
        results=results,
    )


def execute(
    config: AppConfig,
    provider_spec: Optional[str] = None,
    cases_dir: Optional[Path] = None,
    root: Optional[Path] = None,
    repeat: Optional[int] = None,
    flaky_pass_rate: Optional[float] = None,
) -> Run:
    """Full pipeline: load suites -> build providers -> run -> persist."""
    root = root or Path.cwd()
    cases_path = cases_dir or (root / config.cases_dir)
    suites = load_suites(cases_path)

    spec = provider_spec or config.default_provider
    provider = get_provider(spec, config)

    needs_judge = any(
        a.type == "llm_judge" for s in suites for c in s.cases for a in c.asserts
    )
    judge_fn = None
    if needs_judge:
        judge_spec = config.judge.provider or spec
        judge_fn = _judge_fn(get_provider(judge_spec, config))

    cases = [c for s in suites for c in s.cases]
    if not cases:
        raise ValueError(f"no cases found in {cases_path}")

    rep = config.repeat if repeat is None else repeat
    rate = config.flaky_pass_rate if flaky_pass_rate is None else flaky_pass_rate
    run = run_cases(
        cases,
        suite_name=config.suite,
        provider=provider,
        judge_fn=judge_fn,
        repeat=rep,
        flaky_pass_rate=rate,
    )
    run.meta.run_id = storage.unique_run_id(run.meta.run_id, root)
    storage.save_run(run, root)
    return run


def execute_matrix(
    config: AppConfig,
    provider_specs: list[str],
    cases_dir: Optional[Path] = None,
    root: Optional[Path] = None,
    repeat: Optional[int] = None,
    flaky_pass_rate: Optional[float] = None,
) -> list[Run]:
    """Run the suite against several providers; returns runs in the given order."""
    return [
        execute(
            config,
            provider_spec=spec,
            cases_dir=cases_dir,
            root=root,
            repeat=repeat,
            flaky_pass_rate=flaky_pass_rate,
        )
        for spec in provider_specs
    ]
