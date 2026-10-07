"""Suite loading and run execution."""

from __future__ import annotations

import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Optional

import yaml

from promptseal import judge as judge_mod
from promptseal._version import __version__
from promptseal.assertions import CheckContext, JudgeFn, parse_asserts, run_asserts
from promptseal.config import AppConfig
from promptseal.models import Case, CaseResult, Run, RunMeta, RunSummary, Suite
from promptseal.providers import Provider, ProviderError, get_provider
from promptseal import storage


@dataclass
class CaseFilter:
    """Tag/ID based case selection (CLI: --tags / --exclude-tags / --case / --skip-case)."""

    tags: frozenset = frozenset()
    exclude_tags: frozenset = frozenset()
    only: frozenset = frozenset()
    skip: frozenset = frozenset()

    def matches(self, case: Case) -> bool:
        case_tags = set(case.tags)
        if self.only and case.id not in self.only:
            return False
        if case.id in self.skip:
            return False
        if self.tags and not (case_tags & self.tags):
            return False
        if self.exclude_tags and (case_tags & self.exclude_tags):
            return False
        return True

    @staticmethod
    def parse(tags=None, exclude_tags=None, only=None, skip=None) -> "CaseFilter":
        """Build a filter from comma-separated strings, lists, or None values."""

        def split(value) -> frozenset:
            if not value:
                return frozenset()
            items = value if isinstance(value, (list, tuple, set)) else str(value).split(",")
            return frozenset(str(v).strip() for v in items if str(v).strip())

        return CaseFilter(
            tags=split(tags),
            exclude_tags=split(exclude_tags),
            only=split(only),
            skip=split(skip),
        )


def load_suite_file(path: Path, _seen: Optional[frozenset] = None) -> Suite:
    """Load a suite YAML file, resolving `extends:` inheritance chains.

    `extends: base.yaml` (relative to this file) inherits the parent's suite
    name/description and cases; a child case with the same id overrides the
    parent's. Chains are supported; cycles raise ValueError.
    """
    _seen = _seen if _seen is not None else frozenset()
    key = str(path.resolve())
    if key in _seen:
        raise ValueError(f"extends cycle detected at: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cases: list[Case] = []
    raw_cases = raw.get("cases") or []
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
                script=rc.get("script"),
                params=rc.get("params"),
            )
        )
    name = raw.get("suite")
    description = raw.get("description")
    parent_ref = raw.get("extends")
    if parent_ref:
        parent_path = (path.parent / str(parent_ref)).resolve()
        if not parent_path.exists():
            raise FileNotFoundError(f"extends target not found: {parent_path}")
        parent = load_suite_file(parent_path, _seen | {key})
        child_ids = {c.id for c in cases}
        cases = [c for c in parent.cases if c.id not in child_ids] + cases
        name = name or parent.name
        description = description or parent.description
    return Suite(
        name=str(name or path.stem),
        source_file=str(path),
        description=description,
        cases=cases,
    )


def load_suites(cases_dir: Path) -> list[Suite]:
    """Load every *.yaml / *.yml file in cases_dir as a suite.

    A file that another file in the same directory extends is not loaded as a
    standalone suite — it is already merged into its child(ren).
    """
    if not cases_dir.exists():
        raise FileNotFoundError(f"cases directory not found: {cases_dir}")
    files = sorted([*cases_dir.glob("*.yaml"), *cases_dir.glob("*.yml")])
    if not files:
        raise FileNotFoundError(f"no suite files (*.yaml) found in {cases_dir}")

    raws: dict[Path, dict] = {}
    for f in files:
        try:
            raws[f] = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            raws[f] = {}  # let load_suite_file raise the real error later

    extended: set[Path] = set()
    for f, raw in raws.items():
        ref = raw.get("extends")
        if ref:
            extended.add((f.parent / str(ref)).resolve())

    return [
        load_suite_file(f)
        for f in files
        if f.resolve() not in extended
    ]


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


def _judge_fn(judge_provider: Provider, judge_params=None) -> JudgeFn:
    def judge(system: str, user: str) -> str:
        return judge_provider.complete(system, user, params=judge_params).text

    return judge


def _run_case_once(case: Case, provider: Provider, judge_fn: Optional[JudgeFn]) -> CaseResult:
    """One attempt of a single case (scripted-user runs loop until the script ends)."""
    script = [(_render(t, case.vars) if isinstance(t, str) else str(t)) for t in (case.script or [])]

    if case.messages is not None:
        chat = []
        for m in case.messages:
            if not isinstance(m, dict):
                continue
            item = dict(m)
            if isinstance(item.get("content"), str):
                item["content"] = _render(item["content"], case.vars)
            chat.append(item)
    else:
        chat = []
        if case.system:
            chat.append({"role": "system", "content": _render(case.system, case.vars)})
        chat.append({"role": "user", "content": _render(case.prompt, case.vars)})

    try:
        outputs: list[str] = []
        costs: list[float] = []
        latency_ms = 0
        tool_calls: Optional[list[dict[str, Any]]] = None
        for round_no in range(1 + len(script)):
            completion = provider.complete(
                messages=chat,
                tools=case.tools,
                tool_choice=case.tool_choice,
                params=case.params,
            )
            latency_ms += completion.latency_ms
            if completion.cost_usd is not None:
                costs.append(completion.cost_usd)
            outputs.append(completion.text)
            tool_calls = completion.tool_calls
            chat.append({"role": "assistant", "content": completion.text})
            if round_no < len(script):
                chat.append({"role": "user", "content": script[round_no]})
    except ProviderError as exc:
        return CaseResult(case_id=case.id, status="error", error=str(exc))

    ctx = CheckContext(
        latency_ms=latency_ms,
        cost_usd=(sum(costs) if costs else None),
        judge_fn=judge_fn,
        tool_calls=tool_calls,
    )
    output = outputs[-1]
    assertion_results = run_asserts(case.asserts, output, ctx)
    failed = [a for a in assertion_results if not a.passed]
    status = "fail" if failed else "pass"
    return CaseResult(
        case_id=case.id,
        status=status,
        output=output,
        latency_ms=latency_ms,
        cost_usd=(sum(costs) if costs else None),
        assertion_results=assertion_results,
        tool_calls=tool_calls,
        turns=(1 + len(script)) if script else None,
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
    fail_fast: bool = False,
    concurrency: int = 1,
) -> Run:
    """Execute cases against one provider and return a Run.

    With repeat > 1 every case runs N times (flaky detection): it passes only
    when at least `flaky_pass_rate` of the attempts pass. With concurrency > 1
    cases run in parallel threads (input order preserved; fail-fast ignored).
    With fail_fast the run stops at the first failing case (sequential mode).
    """
    repeat = max(1, int(repeat))
    concurrency = max(1, int(concurrency or 1))
    started = time.perf_counter()
    results: list[CaseResult] = []
    interrupted = False

    def _execute_case(case: Case) -> CaseResult:
        attempts = [_run_case_once(case, provider, judge_fn) for _ in range(repeat)]
        if repeat == 1:
            return attempts[0]
        return _aggregate_attempts(case, attempts, flaky_pass_rate)

    if concurrency > 1:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            results = list(pool.map(_execute_case, cases))
    else:
        for case in cases:
            result = _execute_case(case)
            results.append(result)
            if fail_fast and result.status != "pass":
                interrupted = True
                break

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
            interrupted=interrupted,
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
    case_filter: Optional[CaseFilter] = None,
    fail_fast: bool = False,
    concurrency: Optional[int] = None,
) -> Run:
    """Full pipeline: load suites -> filter cases -> build providers -> run -> persist."""
    root = root or Path.cwd()
    cases_path = cases_dir or (root / config.cases_dir)
    suites = load_suites(cases_path)

    spec = provider_spec or config.default_provider
    provider = get_provider(spec, config)

    needs_judge = any(
        a.type == "llm_judge" for s in suites for c in s.cases for a in c.asserts
    )
    judge_fn = None
    cache = None
    if needs_judge:
        judge_spec = config.judge.provider or spec
        judge_provider = get_provider(judge_spec, config)
        cache_id = judge_spec + "::" + json.dumps(config.judge.params or {}, sort_keys=True)
        cache = judge_mod.JudgeCache(cache_id, root=root, enabled=config.judge_cache)
        judge_fn = cache.wrap(_judge_fn(judge_provider, config.judge.params or None))

    cases = [c for s in suites for c in s.cases]
    if not cases:
        raise ValueError(f"no cases found in {cases_path}")
    if case_filter is not None:
        cases = [c for c in cases if case_filter.matches(c)]
        if not cases:
            raise ValueError("no cases match the given filters")

    rep = config.repeat if repeat is None else repeat
    rate = config.flaky_pass_rate if flaky_pass_rate is None else flaky_pass_rate
    conc = config.concurrency if concurrency is None else concurrency
    run = run_cases(
        cases,
        suite_name=config.suite,
        provider=provider,
        judge_fn=judge_fn,
        repeat=rep,
        flaky_pass_rate=rate,
        fail_fast=fail_fast,
        concurrency=conc,
    )
    if cache is not None:
        cache.persist()
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
    case_filter: Optional[CaseFilter] = None,
    fail_fast: bool = False,
    concurrency: Optional[int] = None,
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
            case_filter=case_filter,
            fail_fast=fail_fast,
            concurrency=concurrency,
        )
        for spec in provider_specs
    ]
