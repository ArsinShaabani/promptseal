"""Unit tests for built-in assertions."""

import pytest

from promptseal.assertions import CheckContext, parse_asserts, run_asserts


def run(specs_raw, output, **ctx_kwargs):
    specs = parse_asserts(specs_raw)
    return run_asserts(specs, output, CheckContext(**ctx_kwargs))


def test_contains_shorthand():
    results = run([{"contains": "hello"}], "say Hello World")
    assert results[0].passed


def test_contains_failure_detail():
    results = run([{"contains": "goodbye"}], "say hello")
    assert not results[0].passed
    assert "goodbye" in results[0].detail


def test_not_contains_string_and_list():
    assert run([{"not_contains": "secret"}], "all clear")[0].passed
    results = run([{"not_contains": ["pin", "ssn"]}], "my ssn is 123")
    assert not results[0].passed
    assert "ssn" in results[0].detail


def test_contains_any():
    assert run([{"contains_any": ["sorry", "apologize"]}], "I apologize deeply")[0].passed
    assert not run([{"contains_any": ["sorry", "apologize"]}], "nope")[0].passed


def test_regex():
    assert run([{"regex": r"order[- ]?\d+"}], "your order-1234 shipped")[0].passed
    assert not run([{"regex": r"order[- ]?\d+"}], "no id here")[0].passed


def test_equals_strips():
    assert run([{"equals": " hi "}], "hi")[0].passed


def test_json_valid_with_code_fence():
    out = "```json\n{\"a\": 1}\n```"
    assert run([{"json_valid": True}], out)[0].passed
    assert not run([{"json_valid": True}], "not json")[0].passed


def test_latency_and_cost_checks():
    ctx_latency = run([{"max_latency_s": 1}], "x", latency_ms=500)
    assert ctx_latency[0].passed
    ctx_slow = run([{"max_latency_s": 1}], "x", latency_ms=2500)
    assert not ctx_slow[0].passed
    # cost unknown -> skipped (pass)
    assert run([{"max_cost_usd": 0.01}], "x")[0].passed
    over = run([{"max_cost_usd": 0.01}], "x", cost_usd=0.5)
    assert not over[0].passed


def test_length_checks():
    assert run([{"min_length": 3}], "hello")[0].passed
    assert not run([{"min_length": 10}], "hi")[0].passed
    assert run([{"max_length": 5}], "hi")[0].passed
    assert not run([{"max_length": 5}], "way too long")[0].passed


def test_not_empty():
    assert run([{"not_empty": True}], "  content  ")[0].passed
    result = run([{"not_empty": True}], "   ")
    assert not result[0].passed
    assert "empty" in result[0].detail


def test_starts_with_and_ends_with():
    assert run([{"starts_with": "hello"}], "Hello there")[0].passed
    assert not run([{"starts_with": "bye"}], "Hello there")[0].passed
    assert run([{"ends_with": "!"}], "Nice job!")[0].passed
    assert not run([{"ends_with": "?"}], "Nice job!")[0].passed


def test_llm_judge_requires_judge():
    results = run([{"llm_judge": "be nice"}], "output")
    assert not results[0].passed
    assert "judge" in results[0].detail


def test_llm_judge_with_stub_judge():
    ctx = CheckContext(judge_fn=lambda system, user: "PASS\nIt is polite.")
    specs = parse_asserts([{"llm_judge": "response is polite"}])
    results = run_asserts(specs, "Thank you so much!", ctx)
    assert results[0].passed

    ctx_fail = CheckContext(judge_fn=lambda system, user: "FAIL\nRude.")
    results_fail = run_asserts(specs, "Whatever.", ctx_fail)
    assert not results_fail[0].passed


def test_explicit_type_form():
    results = run([{"type": "contains", "value": "ok"}], "it's OK")
    assert results[0].passed


def test_unknown_type_raises():
    with pytest.raises(ValueError):
        parse_asserts([{"type": "telepathy", "value": "x"}])


def test_unknown_shorthand_raises():
    with pytest.raises(ValueError):
        parse_asserts([{"vibes": "good"}])
