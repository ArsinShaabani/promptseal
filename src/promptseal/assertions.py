"""Assertion registry and built-in checks."""

from __future__ import annotations

import json as jsonlib
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from promptseal.models import AssertResult, AssertSpec

# A judge function takes (criterion, output) and returns the judge model's text.
JudgeFn = Callable[[str, str], str]

_SHORTHAND_KEYS = {
    "contains",
    "not_contains",
    "contains_any",
    "regex",
    "equals",
    "json_valid",
    "max_latency_s",
    "max_cost_usd",
    "min_length",
    "max_length",
    "llm_judge",
    "not_empty",
    "starts_with",
    "ends_with",
    "tools_called",
    "tools_not_called",
    "call_order",
    "tool_args",
}


@dataclass
class CheckContext:
    latency_ms: int = 0
    cost_usd: Optional[float] = None
    judge_fn: Optional[JudgeFn] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    # Normalized tool_calls from the assistant message (agent traces).
    tool_calls: Optional[list[dict[str, Any]]] = None


_REGISTRY: dict[str, Callable[[str, Any, CheckContext], tuple[bool, str]]] = {}


def check(name: str):
    """Register a check function: fn(output, value, ctx) -> (passed, detail)."""

    def decorator(fn):
        _REGISTRY[name] = fn
        return fn

    return decorator


_PLUGIN_GROUP = "promptseal.assertions"
_loaded_plugins: list[str] = []


def load_plugins() -> list[str]:
    """Import assertion plugin packages (entry-point group `promptseal.assertions`).

    A plugin is any installed package whose module imports promptseal and uses the
    `@check` decorator. Idempotent and best-effort: a broken plugin is skipped,
    never fatal. Returns the discovered plugin names.
    """
    global _loaded_plugins
    if _loaded_plugins:
        return list(_loaded_plugins)
    import importlib.metadata

    names: list[str] = []
    try:
        eps = importlib.metadata.entry_points()
        group = (
            eps.select(group=_PLUGIN_GROUP)
            if hasattr(eps, "select")
            else eps.get(_PLUGIN_GROUP, [])
        )
    except Exception:  # noqa: BLE001 — discovery must never crash the CLI
        return []
    for ep in group:
        try:
            ep.load()
            names.append(ep.name)
        except Exception:  # noqa: BLE001 — skip broken plugins
            continue
    _loaded_plugins = names
    return list(names)


@check("contains")
def _contains(output: str, value: Any, ctx: CheckContext) -> tuple[bool, str]:
    ok = str(value).lower() in output.lower()
    return ok, "" if ok else f"expected output to contain {value!r}"


@check("not_contains")
def _not_contains(output: str, value: Any, ctx: CheckContext) -> tuple[bool, str]:
    needles = value if isinstance(value, list) else [value]
    hits = [n for n in needles if str(n).lower() in output.lower()]
    return not hits, "" if not hits else f"forbidden text found: {hits}"


@check("contains_any")
def _contains_any(output: str, value: Any, ctx: CheckContext) -> tuple[bool, str]:
    needles = value if isinstance(value, list) else [value]
    hits = [n for n in needles if str(n).lower() in output.lower()]
    return bool(hits), "" if hits else f"none of {needles} were found"


@check("regex")
def _regex(output: str, value: Any, ctx: CheckContext) -> tuple[bool, str]:
    ok = re.search(str(value), output) is not None
    return ok, "" if ok else f"pattern {value!r} did not match"


@check("equals")
def _equals(output: str, value: Any, ctx: CheckContext) -> tuple[bool, str]:
    ok = output.strip() == str(value).strip()
    return ok, "" if ok else f"expected exactly {value!r}"


@check("not_empty")
def _not_empty(output: str, value: Any, ctx: CheckContext) -> tuple[bool, str]:
    ok = output.strip() != ""
    return ok, "" if ok else "output is empty"


@check("starts_with")
def _starts_with(output: str, value: Any, ctx: CheckContext) -> tuple[bool, str]:
    ok = output.strip().lower().startswith(str(value).strip().lower())
    return ok, "" if ok else f"output does not start with {value!r}"


@check("ends_with")
def _ends_with(output: str, value: Any, ctx: CheckContext) -> tuple[bool, str]:
    ok = output.strip().lower().endswith(str(value).strip().lower())
    return ok, "" if ok else f"output does not end with {value!r}"


@check("json_valid")
def _json_valid(output: str, value: Any, ctx: CheckContext) -> tuple[bool, str]:
    stripped = output.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:]
    try:
        jsonlib.loads(stripped.strip())
        return True, ""
    except jsonlib.JSONDecodeError as exc:
        return False, f"output is not valid JSON: {exc}"


@check("max_latency_s")
def _max_latency(output: str, value: Any, ctx: CheckContext) -> tuple[bool, str]:
    limit_ms = float(value) * 1000
    ok = ctx.latency_ms <= limit_ms
    return ok, "" if ok else f"took {ctx.latency_ms}ms (limit {limit_ms:.0f}ms)"


@check("max_cost_usd")
def _max_cost(output: str, value: Any, ctx: CheckContext) -> tuple[bool, str]:
    if ctx.cost_usd is None:
        return True, "cost unknown for this provider — skipped"
    ok = ctx.cost_usd <= float(value)
    return ok, "" if ok else f"cost ${ctx.cost_usd:.4f} exceeded ${float(value):.4f}"


@check("min_length")
def _min_length(output: str, value: Any, ctx: CheckContext) -> tuple[bool, str]:
    ok = len(output) >= int(value)
    return ok, "" if ok else f"output too short ({len(output)} < {int(value)})"


@check("max_length")
def _max_length(output: str, value: Any, ctx: CheckContext) -> tuple[bool, str]:
    ok = len(output) <= int(value)
    return ok, "" if ok else f"output too long ({len(output)} > {int(value)})"


_JUDGE_SYSTEM = (
    "You are a strict QA judge for LLM outputs. "
    "Answer with exactly PASS or FAIL on the first line, then a short reason."
)


@check("llm_judge")
def _llm_judge(output: str, value: Any, ctx: CheckContext) -> tuple[bool, str]:
    if ctx.judge_fn is None:
        return False, "no judge provider configured (set defaults.judge.provider)"
    user = (
        f"Criterion: {value}\n\nAssistant output:\n{output}\n\n"
        "Does the output satisfy the criterion?"
    )
    try:
        answer = ctx.judge_fn(_JUDGE_SYSTEM, user)
    except Exception as exc:  # noqa: BLE001 — judge failures are assertion failures
        return False, f"judge call failed: {exc}"
    first_line = answer.strip().splitlines()[0].strip().upper()
    if first_line.startswith("PASS"):
        return True, answer.strip()
    if first_line.startswith("FAIL"):
        return False, answer.strip()
    return False, f"judge gave an unclear answer: {answer.strip()[:200]}"


def _tool_names(ctx: CheckContext) -> list[str]:
    names: list[str] = []
    for tc in ctx.tool_calls or []:
        fn = tc.get("function") if isinstance(tc, dict) else None
        name = fn.get("name") if isinstance(fn, dict) else None
        if name:
            names.append(str(name))
    return names


@check("tools_called")
def _tools_called(output: str, value: Any, ctx: CheckContext) -> tuple[bool, str]:
    """Every listed tool must have been called (value: str or list of names)."""
    required = [value] if isinstance(value, str) else list(value or [])
    names = _tool_names(ctx)
    missing = [t for t in required if t not in names]
    ok = bool(required) and not missing
    return ok, "" if ok else f"required tools not called: {missing} (called: {names or 'none'})"


@check("tools_not_called")
def _tools_not_called(output: str, value: Any, ctx: CheckContext) -> tuple[bool, str]:
    """None of the listed tools may appear in the trace."""
    forbidden = [value] if isinstance(value, str) else list(value or [])
    names = _tool_names(ctx)
    hits = [t for t in forbidden if t in names]
    return not hits, "" if not hits else f"forbidden tool calls found: {hits}"


@check("call_order")
def _call_order(output: str, value: Any, ctx: CheckContext) -> tuple[bool, str]:
    """The listed tools must appear in this relative order within the trace."""
    expected = [str(v) for v in (value if isinstance(value, list) else [value])]
    names = _tool_names(ctx)
    pos = 0
    for name in names:
        if pos < len(expected) and name == expected[pos]:
            pos += 1
    ok = pos == len(expected)
    return ok, "" if ok else f"expected call order {expected}, got trace {names or 'none'}"


@check("tool_args")
def _tool_args(output: str, value: Any, ctx: CheckContext) -> tuple[bool, str]:
    """First call of each named tool must have these argument key/values.

    Value shape: {tool_name: {arg: expected_value}} — provided keys are compared,
    extra arguments are allowed.
    """
    expected_map = value if isinstance(value, dict) else {}
    if not expected_map:
        return False, "tool_args expects a mapping like {tool_name: {arg: expected}}"
    calls_by_name: dict[str, dict] = {}
    for tc in ctx.tool_calls or []:
        fn = tc.get("function") if isinstance(tc, dict) else None
        if isinstance(fn, dict) and fn.get("name"):
            calls_by_name.setdefault(str(fn["name"]), tc)
    problems: list[str] = []
    for tool, expected_args in expected_map.items():
        tc = calls_by_name.get(str(tool))
        if tc is None:
            problems.append(f"tool {tool!r} was not called")
            continue
        raw = ((tc.get("function") or {}).get("arguments")) or "{}"
        try:
            args = jsonlib.loads(raw) if isinstance(raw, str) else dict(raw)
        except (ValueError, TypeError):
            problems.append(f"tool {tool!r}: arguments are not valid JSON: {raw!r}")
            continue
        if not isinstance(args, dict):
            problems.append(f"tool {tool!r}: arguments must be a JSON object")
            continue
        for key, want in (expected_args or {}).items():
            got = args.get(key)
            if got != want:
                problems.append(f"tool {tool!r}: arg {key!r} = {got!r}, expected {want!r}")
    ok = not problems
    return ok, "" if ok else "; ".join(problems)


def parse_asserts(raw_asserts: list[dict[str, Any]]) -> list[AssertSpec]:
    """Accept shorthand ({contains: 'x'}) and explicit ({type: contains, value: 'x'}) forms."""
    specs: list[AssertSpec] = []
    for raw in raw_asserts or []:
        if not isinstance(raw, dict):
            raise ValueError(f"assertion must be a mapping, got: {raw!r}")
        if "type" in raw:
            spec = AssertSpec(
                type=raw["type"],
                value=raw.get("value"),
                weight=float(raw.get("weight", 1.0)),
                extra={k: v for k, v in raw.items() if k not in ("type", "value", "weight")},
            )
            if spec.type not in _REGISTRY:
                raise ValueError(f"unknown assertion type: {spec.type!r}")
            specs.append(spec)
            continue
        unknown = set(raw) - _SHORTHAND_KEYS
        if unknown:
            raise ValueError(
                f"unknown assertion key(s) {unknown}; known: {sorted(_SHORTHAND_KEYS)}"
            )
        for key, value in raw.items():
            specs.append(AssertSpec(type=key, value=value))
    return specs


def run_asserts(specs: list[AssertSpec], output: str, ctx: CheckContext) -> list[AssertResult]:
    results: list[AssertResult] = []
    for spec in specs:
        fn = _REGISTRY[spec.type]
        try:
            passed, detail = fn(output, spec.value, ctx)
        except Exception as exc:  # noqa: BLE001 — a broken check must not kill the run
            passed, detail = False, f"check raised: {exc}"
        results.append(AssertResult(type=spec.type, passed=bool(passed), detail=detail))
    return results


def available_checks() -> list[str]:
    return sorted(_REGISTRY)

