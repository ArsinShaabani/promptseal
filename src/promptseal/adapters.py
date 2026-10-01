"""Framework adapters: evaluate traces from LangChain, OpenAI Agents SDK, etc.

No SDK required — the adapters work on plain message dicts (OpenAI chat format)
and duck-typed framework objects, and funnel everything into `evaluate_trace`,
which runs the exact same assertion registry a provider run would use.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from promptseal.assertions import CheckContext, JudgeFn, parse_asserts, run_asserts
from promptseal.models import AssertResult


def evaluate_trace(
    asserts: list[dict[str, Any]],
    output: str = "",
    tool_calls: Optional[list[dict[str, Any]]] = None,
    cost_usd: Optional[float] = None,
    latency_ms: int = 0,
    judge_fn: Optional[JudgeFn] = None,
) -> list[AssertResult]:
    """Run the standard assertion registry against an in-memory trace.

    The escape hatch for framework adapters and tests: bring your own output /
    tool_calls (e.g. produced by a LangChain or OpenAI Agents run) and evaluate
    them with the same checks a provider run would use.
    """
    specs = parse_asserts(asserts)
    ctx = CheckContext(
        latency_ms=latency_ms,
        cost_usd=cost_usd,
        judge_fn=judge_fn,
        tool_calls=tool_calls,
    )
    return run_asserts(specs, output, ctx)


def _norm_tool_call(name: Any, arguments: Any) -> Optional[dict[str, Any]]:
    if not name:
        return None
    if isinstance(arguments, str):
        serialized = arguments
    else:
        try:
            serialized = json.dumps(arguments or {})
        except (TypeError, ValueError):
            serialized = "{}"
    return {"type": "function", "function": {"name": str(name), "arguments": serialized}}


def tool_calls_from_langchain(messages: list[Any]) -> list[dict[str, Any]]:
    """Extract normalized OpenAI-style tool_calls from LangChain-style messages.

    Accepts plain dicts (LangChain serialization) or duck-typed message objects
    (anything with a `.tool_calls` attribute, e.g. langchain_core AIMessage).
    Supported shapes: OpenAI style ({function: {name, arguments}}) and LangChain
    style ({name, args}).
    """
    calls: list[dict[str, Any]] = []
    for msg in messages or []:
        if isinstance(msg, dict):
            raw = msg.get("tool_calls")
        elif hasattr(msg, "tool_calls"):
            raw = getattr(msg, "tool_calls", None)
        else:
            continue
        for tc in raw or []:
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function") or {}
            name = fn.get("name") or tc.get("name")
            args = fn.get("arguments") if "arguments" in fn else tc.get("args")
            normalized = _norm_tool_call(name, args)
            if normalized:
                calls.append(normalized)
    return calls


def tool_calls_from_agents(items: list[Any]) -> list[dict[str, Any]]:
    """Extract normalized tool_calls from OpenAI Agents SDK run output items.

    Accepts function_call items in dict form ({"type": "function_call",
    "name": ..., "arguments": "..."}) or duck-typed objects exposing
    `.name` / `.arguments`.
    """
    calls: list[dict[str, Any]] = []
    for item in items or []:
        if isinstance(item, dict):
            if item.get("type") not in (None, "function_call"):
                continue
            name, args = item.get("name"), item.get("arguments")
        else:
            name = getattr(item, "name", None)
            args = getattr(item, "arguments", None)
        if not name:
            continue
        normalized = _norm_tool_call(name, args)
        if normalized:
            calls.append(normalized)
    return calls


def _last_assistant_text(messages: list[Any]) -> str:
    for msg in reversed(messages or []):
        role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", None)
        if role != "assistant":
            continue
        content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", "")
        if isinstance(content, str):
            return content
    return ""


def evaluate_conversation(
    asserts: list[dict[str, Any]],
    messages: list[Any],
    judge_fn: Optional[JudgeFn] = None,
) -> list[AssertResult]:
    """Evaluate a conversation's final assistant turn and its tool calls."""
    return evaluate_trace(
        asserts,
        output=_last_assistant_text(messages),
        tool_calls=tool_calls_from_langchain(messages),
        judge_fn=judge_fn,
    )