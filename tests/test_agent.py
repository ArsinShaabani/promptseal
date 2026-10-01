"""Agent-native tests: tool-call trace assertions + multi-turn messages."""

import yaml

from promptseal.assertions import CheckContext, parse_asserts, run_asserts
from promptseal.config import AppConfig
from promptseal.models import Case
from promptseal.providers import get_provider
from promptseal.runner import load_suite_file, run_cases

TC = [
    {
        "id": "c1",
        "type": "function",
        "function": {"name": "get_weather", "arguments": '{"city": "Paris"}'},
    },
    {
        "id": "c2",
        "type": "function",
        "function": {"name": "search_flights", "arguments": '{"to": "Tokyo"}'},
    },
]


def _ctx(tool_calls=None):
    return CheckContext(tool_calls=tool_calls)


def _run_specs(specs_raw, ctx):
    return run_asserts(parse_asserts(specs_raw), "", ctx)


def test_tools_called_variants():
    assert _run_specs([{"tools_called": ["get_weather"]}], _ctx(TC))[0].passed
    assert _run_specs([{"tools_called": "get_weather"}], _ctx(TC))[0].passed
    miss = _run_specs([{"tools_called": ["book_hotel"]}], _ctx(TC))[0]
    assert not miss.passed and "book_hotel" in miss.detail
    none = _run_specs([{"tools_called": "get_weather"}], _ctx())[0]
    assert not none.passed and "none" in none.detail


def test_tools_not_called():
    assert _run_specs([{"tools_not_called": ["book_hotel"]}], _ctx(TC))[0].passed
    res = _run_specs([{"tools_not_called": "search_flights"}], _ctx(TC))[0]
    assert not res.passed and "search_flights" in res.detail


def test_call_order_subsequence():
    assert _run_specs([{"call_order": ["get_weather", "search_flights"]}], _ctx(TC))[0].passed
    res = _run_specs([{"call_order": ["search_flights", "get_weather"]}], _ctx(TC))[0]
    assert not res.passed and "call order" in res.detail


def test_tool_args_matching_and_failures():
    ok = _run_specs([{"tool_args": {"get_weather": {"city": "Paris"}}}], _ctx(TC))[0]
    assert ok.passed
    bad = _run_specs([{"tool_args": {"get_weather": {"city": "Rome"}}}], _ctx(TC))[0]
    assert not bad.passed and "Rome" in bad.detail
    missing = _run_specs([{"tool_args": {"nope": {"a": 1}}}], _ctx(TC))[0]
    assert not missing.passed and "not called" in missing.detail
    badjson = _run_specs(
        [{"tool_args": {"get_weather": {"x": 1}}}],
        _ctx([{"function": {"name": "get_weather", "arguments": "not-json"}}]),
    )[0]
    assert not badjson.passed and "valid JSON" in badjson.detail


def test_mock_tools_provider_end_to_end():
    provider = get_provider("mock:tools", AppConfig())
    case = Case(
        id="agent",
        prompt="Weather in Paris?",
        tools=[{"type": "function", "function": {"name": "get_weather", "parameters": {}}}],
        asserts=parse_asserts(
            [
                {"tools_called": "get_weather"},
                {"tool_args": {"get_weather": {"city": "Paris"}}},
                {"call_order": ["get_weather"]},
                {"tools_not_called": "book_hotel"},
            ]
        ),
    )
    run = run_cases([case], "t", provider)
    r = run.results[0]
    assert r.status == "pass"
    assert r.tool_calls and r.tool_calls[0]["function"]["name"] == "get_weather"


def test_plain_mock_has_no_tool_calls():
    provider = get_provider("mock:echo", AppConfig())
    case = Case(id="plain", prompt="hi", asserts=parse_asserts([{"tools_not_called": "get_weather"}]))
    run = run_cases([case], "t", provider)
    assert run.results[0].status == "pass"
    assert run.results[0].tool_calls is None


def test_multiturn_messages_with_vars():
    provider = get_provider("mock:echo", AppConfig())
    case = Case(
        id="chat",
        messages=[
            {"role": "system", "content": "be {{tone}}"},
            {"role": "user", "content": "hi, I'm {{name}}"},
            {"role": "assistant", "content": "hello!"},
            {"role": "user", "content": "my ticket is {{name}}-1"},
        ],
        vars={"tone": "brief", "name": "Zara"},
        asserts=parse_asserts([{"equals": "Echo: my ticket is Zara-1"}]),
    )
    run = run_cases([case], "t", provider)
    assert run.results[0].status == "pass"
    assert run.results[0].output == "Echo: my ticket is Zara-1"


def test_loader_accepts_messages_without_prompt(tmp_path):
    path = tmp_path / "s.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "suite": "s",
                "cases": [
                    {
                        "id": "m",
                        "messages": [{"role": "user", "content": "hi"}],
                        "asserts": [{"not_empty": True}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    suite = load_suite_file(path)
    assert suite.cases[0].prompt == ""
    assert suite.cases[0].messages[0]["content"] == "hi"


def test_scripted_user_simulation():
    provider = get_provider("mock:echo", AppConfig())
    case = Case(
        id="scripted",
        prompt="start",
        script=["turn one", "turn two"],
        asserts=parse_asserts([{"equals": "Echo: turn two"}]),
    )
    run = run_cases([case], "t", provider)
    r = run.results[0]
    assert r.status == "pass"
    assert r.output == "Echo: turn two"
    assert r.turns == 3


def test_scripted_multi_turn_messages():
    provider = get_provider("mock:echo", AppConfig())
    case = Case(
        id="chat-script",
        messages=[{"role": "user", "content": "q1"}],
        script=["q2"],
        asserts=parse_asserts([{"equals": "Echo: q2"}, {"max_latency_s": 1}]),
    )
    run = run_cases([case], "t", provider)
    r = run.results[0]
    assert r.status == "pass"
    assert r.turns == 2
    assert r.latency_ms == 24  # 2 x 12ms mock latency, aggregated


def test_no_script_means_no_turns_field():
    provider = get_provider("mock:echo", AppConfig())
    run = run_cases(
        [Case(id="s", prompt="x", asserts=parse_asserts([{"contains": "Echo"}]))], "t", provider
    )
    assert run.results[0].turns is None