"""pytest plugin: run PromptSeal eval suites next to your unit tests.

Opt-in — enable with `pytest --promptseal`. Every suite YAML in your cases dir
becomes pytest test items (one per case), and the whole session is persisted as
a single PromptSeal run in `.promptseal/runs/`, so `promptseal seal` / `diff` /
`ci` keep working exactly as before.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from promptseal import assertions
from promptseal import judge as judge_mod
from promptseal import storage
from promptseal._version import __version__
from promptseal.config import AppConfig, find_config, load_config
from promptseal.models import Case, CaseResult, Run, RunMeta, RunSummary
from promptseal.providers import Provider, ProviderError, get_provider
from promptseal.runner import _git_commit, _judge_fn, _run_case_once, load_suite_file


class PromptSealFailure(AssertionError):
    """Raised when an eval case fails inside pytest."""


def pytest_addoption(parser) -> None:
    group = parser.getgroup("promptseal")
    group.addoption(
        "--promptseal",
        action="store_true",
        default=False,
        help="Collect PromptSeal eval suites (*.yaml in your cases dir) as tests.",
    )
    group.addoption(
        "--ps-provider",
        default=None,
        help="Provider spec override for PromptSeal cases, e.g. openai:gpt-4o.",
    )


def pytest_configure(config) -> None:
    config.addinivalue_line("markers", "promptseal: PromptSeal eval case")
    if getattr(config.option, "promptseal", False):
        assertions.load_plugins()
        cfg: AppConfig = load_config(find_config())
        spec = config.option.ps_provider or cfg.default_provider
        try:
            provider = get_provider(spec, cfg)
        except ProviderError as exc:
            raise pytest.UsageError(f"promptseal: {exc}") from exc
        config._ps_config = cfg
        config._ps_provider = provider
        config._ps_judge = None
        config._ps_results = []


def pytest_collect_file(file_path: Path, parent):
    if not getattr(parent.config.option, "promptseal", False):
        return None
    if file_path.suffix.lower() not in (".yaml", ".yml"):
        return None
    try:
        suite = load_suite_file(file_path)
    except Exception:
        return None  # not a PromptSeal suite — leave it to other collectors
    if not suite.cases:
        return None
    return PromptSealFile.from_parent(parent, path=file_path)


class PromptSealFile(pytest.File):
    def collect(self):
        suite = load_suite_file(self.path)
        for case in suite.cases:
            yield PromptSealItem.from_parent(self, name=case.id, case=case)


class PromptSealItem(pytest.Item):
    def __init__(self, *, case: Case, **kwargs):
        super().__init__(**kwargs)
        self.case = case
        self.add_marker("promptseal")

    def runtest(self) -> None:
        config = self.config
        provider: Provider = config._ps_provider
        judge_fn = config._ps_judge
        if judge_fn is None and any(a.type == "llm_judge" for a in self.case.asserts):
            judge_spec = config._ps_config.judge.provider or f"{provider.name}:{provider.model}"
            try:
                judge_provider = get_provider(judge_spec, config._ps_config)
            except ProviderError as exc:
                result = CaseResult(case_id=self.case.id, status="error", error=str(exc))
                config._ps_results.append(result)
                raise PromptSealFailure(f"[promptseal] case '{self.case.id}' judge setup failed: {exc}")
            cache = getattr(config, "_ps_judge_cache", None)
            if cache is None:
                cache_id = judge_spec + "::" + json.dumps(config._ps_config.judge.params or {}, sort_keys=True)
                cache = judge_mod.JudgeCache(cache_id, root=Path.cwd(), enabled=config._ps_config.judge_cache)
                config._ps_judge_cache = cache
            judge_fn = cache.wrap(
                _judge_fn(judge_provider, config._ps_config.judge.params or None)
            )
            config._ps_judge = judge_fn
        try:
            result = _run_case_once(self.case, provider, judge_fn)
        except ProviderError as exc:
            result = CaseResult(case_id=self.case.id, status="error", error=str(exc))
        config._ps_results.append(result)
        if result.status == "pass":
            return
        if result.status == "error":
            raise PromptSealFailure(f"[promptseal] case '{self.case.id}' errored: {result.error}")
        details = "\n".join(
            f"  ✘ {a.type}: {a.detail}" for a in result.assertion_results if not a.passed
        )
        raise PromptSealFailure(
            f"[promptseal] case '{self.case.id}' failed\n"
            f"  output: {result.output[:500]!r}\n{details}"
        )

    def repr_failure(self, excinfo, style=None):
        if isinstance(excinfo.value, PromptSealFailure):
            return str(excinfo.value)
        return super().repr_failure(excinfo, style)

    def reportinfo(self):
        return self.path, 0, f"[promptseal] {self.case.id}"


def pytest_sessionfinish(session, exitstatus) -> None:
    config = getattr(session, "config", None)
    if config is None or not getattr(config.option, "promptseal", False):
        return
    _persist_run(config)


def _persist_run(config) -> None:
    """Save the whole pytest session as one PromptSeal run (best-effort)."""
    results: list[CaseResult] = getattr(config, "_ps_results", None) or []
    if not results:
        return
    cache = getattr(config, "_ps_judge_cache", None)
    if cache is not None:
        cache.persist()
    provider: Provider = config._ps_provider
    total = len(results)
    passed = sum(1 for r in results if r.status == "pass")
    errors = sum(1 for r in results if r.status == "error")
    costs = [r.cost_usd for r in results if r.cost_usd is not None]
    run_id = (
        f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-pytest-"
        f"{provider.name}-{provider.model}".replace("/", "-").replace(":", "-")
    )
    run_id = storage.unique_run_id(run_id)
    run = Run(
        meta=RunMeta(
            run_id=run_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            provider=provider.name,
            model=provider.model,
            suite="pytest",
            git_commit=_git_commit(),
            promptseal_version=__version__,
        ),
        summary=RunSummary(
            total=total,
            passed=passed,
            failed=total - passed - errors,
            errors=errors,
            pass_rate=(passed / total) if total else 0.0,
            total_cost_usd=sum(costs) if costs else None,
            total_latency_ms=sum(r.latency_ms for r in results),
        ),
        results=results,
    )
    try:
        storage.save_run(run)
    except Exception:  # noqa: BLE001 — persistence must never break the test session
        pass