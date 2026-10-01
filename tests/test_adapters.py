"""Tests for framework adapters (offline, plain-dict and duck-typed inputs)."""

import json

from promptseal.adapters import (
    evaluate_conversation,
    evaluate_trace,
    tool_calls_from_agents,
    tool_calls_from_langchain,
)


class _AIMessage:
    """Duck-typed langchain_core AIMessage."""

    def __init__(self, content, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


def test_evaluate_trace_text_asserts():
    assert evaluate_trace([{"contains": "ok"}], output="it's OK")[0].passed
    res = evaluate_trace([{"min_length": 100}], output="short")
    assert not res[0].passed


def test_evaluate_trace_tool_asserts():
    tc = [{"type": "function", "function": {"name": "get_weather", "arguments": '{"city": "Paris"}'}}]
    res = evaluate_trace(
        [
            {"tools_called": "get_weather"},
            {"tool_args": {"get_weather": {"city": "Paris"}}},
            {"contains": "sunny"},
        ],
        output="It is sunny in Paris.",
        tool_calls=tc,
        cost_usd=0.001,
        latency_ms=120,
    )
    assert all(r.passed for r in res)


def test_langchain_dict_shapes():
    messages = [
        {"role": "user", "content": "weather?"},
        {
            "role": "assistant",
            "content": "calling tool",
            "tool_calls": [{"name": "get_weather", "args": {"city": "Paris"}}],
        },
    ]
    calls = tool_calls_from_langchain(messages)
    assert calls[0]["function"]["name"] == "get_weather"
    assert json.loads(calls[0]["function"]["arguments"]) == {"city": "Paris"}
    res = evaluate_conversation(
        [{"tools_called": "get_weather"}, {"contains": "calling"}], messages
    )
    assert all(r.passed for r in res)


def test_langchain_object_shape():
    msg = _AIMessage("hi", [{"name": "search", "args": {"q": "x"}}])
    calls = tool_calls_from_langchain([msg])
    assert calls[0]["function"]["name"] == "search"
    assert json.loads(calls[0]["function"]["arguments"]) == {"q": "x"}


def test_langchain_openai_style_dict():
    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": "f", "arguments": '{"a": 1}'}}],
        }
    ]
    calls = tool_calls_from_langchain(messages)
    assert calls[0]["function"]["name"] == "f"
    assert json.loads(calls[0]["function"]["arguments"]) == {"a": 1}


def test_agents_dict_and_object_items():
    items = [
        {"type": "function_call", "name": "get_weather", "arguments": '{"city": "Paris"}'},
        {"type": "message", "content": "done"},
    ]
    calls = tool_calls_from_agents(items)
    assert [c["function"]["name"] for c in calls] == ["get_weather"]

    class _Item:
        name = "search"
        arguments = '{"q": "z"}'

    calls = tool_calls_from_agents([_Item()])
    assert calls[0]["function"]["name"] == "search"
    assert json.loads(calls[0]["function"]["arguments"]) == {"q": "z"}


def test_agents_trace_end_to_end():
    calls = tool_calls_from_agents(
        [{"type": "function_call", "name": "get_weather", "arguments": '{"city": "Paris"}'}]
    )
    res = evaluate_trace(
        [
            {"tools_called": "get_weather"},
            {"tool_args": {"get_weather": {"city": "Paris"}}},
            {"tools_not_called": "book_flight"},
        ],
        output="It is sunny in Paris.",
        tool_calls=calls,
    )
    assert all(r.passed for r in res)


def test_last_assistant_text_prefers_final_turn():
    messages = [
        {"role": "assistant", "content": "first"},
        {"role": "user", "content": "more"},
        {"role": "assistant", "content": "final answer"},
    ]
    res = evaluate_conversation([{"equals": "final answer"}], messages)
    assert res[0].passed