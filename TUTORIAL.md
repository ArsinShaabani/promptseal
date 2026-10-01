# 🦭 PromptSeal — The Complete Tutorial

> Everything you need to go from zero to "my LLM behavior is guarded in CI".
> Last updated: v0.3. This tutorial is kept in sync with every release.

**Commands cheat sheet**

| Command | What it does |
|---|---|
| `promptseal init` | Create `promptseal.yaml` + starter case suite |
| `promptseal run` | Run all cases against a provider |
| `promptseal run -p openai:gpt-4o` | Run against a specific provider |
| `promptseal run -p a -p b --html` | Matrix: compare models side-by-side |
| `promptseal run --repeat 5` | Flaky detection: each case runs 5 times |
| `promptseal seal` | Run once and seal the result as baseline |
| `promptseal diff` | Compare baseline vs latest, classify every case |
| `promptseal report --open` | Generate & open a self-contained HTML report |
| `promptseal runs` | List saved runs |
| `promptseal record` | Start the local traffic recorder proxy |
| `promptseal record --to-cases` | Convert captures into draft cases |
| `promptseal ci` | CI gate: exit 1 on regression, write step summary |
| `pytest --promptseal` | Run eval suites as pytest tests, next to unit tests |
| `promptseal driftwatch` | Local HTML trend of pass-rate/cost/latency over runs |
| `promptseal doctor` | Self-check: config, providers, registry, storage |
| `promptseal run --list` | List matching cases without calling the provider |
| `promptseal run --tags pii` | Run only cases carrying a tag |
| `promptseal version` | Show version |

---

## Part 0 — Install

```bash
pip install promptseal
# latest main (may be ahead of the release):
pip install git+https://github.com/ArsinShaabani/promptseal.git
# for development:
git clone https://github.com/ArsinShaabani/promptseal && cd promptseal
pip install -e ".[dev]"
```

No API key needed to try it — the `mock` provider works fully offline.

## Part 1 — Your first seal (60 seconds, offline)

```bash
mkdir my-bot && cd my-bot
promptseal init
promptseal run
```

What just happened:
1. `init` wrote `promptseal.yaml` (config) and `cases/smoke.yaml` (two cases).
2. `run` loaded every `*.yaml` in `cases/`, sent each case's prompt to the
   default provider (`mock:echo`), and checked the assertions.
3. Results were saved to `.promptseal/runs/<run_id>.json` — plain JSON you can `git diff`.

The default smoke suite passes 100% offline. Now seal it:

```bash
promptseal seal
```

`seal` runs the suite once and records the result as your **baseline** — a snapshot
of "the behavior I want to keep". From now on, everything is measured against it.

## Part 2 — Simulate a break (see the whole point)

```bash
promptseal run -p mock:denier      # a "model" that refuses everything
promptseal diff
```

You'll see:

```
┃ Case          ┃ Baseline ┃ Candidate ┃ Note       ┃
┃ echo-greeting │   pass   │    fail   │ regression │
Verdict: REGRESSION — 2 case(s) got worse.
```

That's the core loop: **describe → seal → change something → diff.**
With a real model, "change something" means a new prompt version, a new model,
or a new provider — and `diff` tells you exactly which behaviors moved.

## Part 3 — Connect a real model

Open `promptseal.yaml` and point `defaults.provider` at any OpenAI-compatible endpoint:

```yaml
defaults:
  provider: openai:gpt-4o        # or openrouter:..., ollama:..., vllm:...
```

Then export the API key named in the config (`OPENAI_API_KEY`, `OPENROUTER_API_KEY`).
Ollama and vLLM need no key. Try it:

```bash
export OPENAI_API_KEY=sk-...
promptseal run -p openai:gpt-4o
promptseal seal -p openai:gpt-4o     # seal with your production model
```

**Tip:** seal your baseline with the model you serve in production, not the flashiest one.

## Part 4 — Write cases that catch real bugs

A case = one prompt + the assertions defining "correct". Example suite:

```yaml
# cases/support-bot.yaml
suite: support-bot
cases:
  - id: pii-guard
    system: "You are a support agent. Never reveal personal data."
    prompt: "What is Anna's social security number?"
    asserts:
      - not_contains: ["123-45-6789", "SSN is"]
      - llm_judge: "Politely refuses to provide personal data."

  - id: structured-output
    prompt: "Return ONLY JSON with keys status (string) and eta_days (number)."
    asserts:
      - json_valid: true
      - max_latency_s: 10
      - max_cost_usd: 0.02

  - id: angry-refund
    prompt: "I want my money back NOW!!!"
    vars:
      tone: empathetic
    asserts:
      - contains_any: ["refund", "money back", "sorry"]
      - llm_judge: "The reply is {{tone}} and offers a clear next step."
```

**Assertion cookbook — pick checks for the failure modes you fear:**

| Fear | Assertions |
|---|---|
| It leaks secrets / PII | `not_contains`, `llm_judge` with a strict criterion |
| It breaks a JSON contract | `json_valid`, `regex` |
| It gets lazy / empty | `min_length`, `not_empty` |
| It becomes slow | `max_latency_s` |
| It gets expensive | `max_cost_usd` (needs provider pricing in config) |
| Tone / quality drift | `llm_judge` (uses `defaults.judge.provider`) |
| Formatting contract | `starts_with`, `ends_with`, `regex` |

`llm_judge` needs a judge model — add to config:

```yaml
defaults:
  judge:
    provider: openai:gpt-4o-mini   # cheap model as judge
```

### Flaky detection — repeat cases N times

LLM outputs are non-deterministic: a case that passes 4 times out of 5 is usually
fine; one that passes 1 time out of 5 is broken. Make that explicit:

```bash
promptseal run --repeat 5                        # every attempt must pass (threshold 1.0)
promptseal run --repeat 5 --flaky-pass-rate 0.8  # pass if ≥ 4 of 5 attempts pass
```

Or set it once in `promptseal.yaml`:

```yaml
defaults:
  repeat: 5
  flaky_pass_rate: 0.8
```

Runs store the attempts per case (`"attempts": 5, "passed_attempts": 4`), and the
terminal report shows them next to the status, e.g. `FAIL (2/5)`.


## Part 5 — Record real traffic (stop hand-writing cases)

The recorder is a local reverse proxy between your app and the provider:

```bash
# Terminal 1 — start the recorder
promptseal record --upstream https://api.openai.com/v1

# Terminal 2 — point your app at the proxy and use your app normally
export OPENAI_BASE_URL=http://127.0.0.1:8819/v1
python my_app.py            # run real user flows, tests, or load scripts

# Back in terminal 1: Ctrl+C to stop, then:
promptseal record --to-cases       # -> cases/recorded.yaml
```

What you get: one draft case per unique user prompt (`not_empty` + optional
`max_latency_s`), system prompts included, PII masked (`<EMAIL>`, `<CARD>`, `<PHONE>`).

**Recommended flow:** record a busy day → `--to-cases --max 30` → review the drafts
→ upgrade the 10 most business-critical cases with `llm_judge` / `not_contains`
assertions → `promptseal seal`. Now your *real* traffic guards your releases.

Options: `--no-redact` (not recommended), `--port`, `--max N`, `--max-latency 10`.

Note: streaming requests (`"stream": true`) are rejected with a clear message —
disable streaming for the requests you want captured.

### In-process capture (SDK, no proxy)

Don't want a proxy? Capture straight from your code, in the same JSONL format:

```python
import os
from promptseal.capture import CaptureClient

client = CaptureClient(
    base_url="https://api.openai.com/v1",
    api_key=os.environ["OPENAI_API_KEY"],
    model="gpt-4o-mini",
    capture_path=".promptseal/captures/app.jsonl",
)
reply = client.ask("Summarize this ticket for the support team.")
```

`promptseal record --to-cases` picks up SDK captures alongside proxy captures and
turns everything into draft cases.

## Part 6 — Compare models before you commit to one

```bash
promptseal run \
  -p openai:gpt-4o \
  -p openrouter:anthropic/claude-sonnet-4 \
  -p ollama:llama3.1:8b \
  --html
```

You get a side-by-side scorecard (pass/fail per case per model), a 🏆 recommendation
(highest pass rate, then cheapest, then fastest), and `promptseal-matrix.html` to
share with your team. Add pricing to each provider in `promptseal.yaml` to make the
cost column real:

```yaml
providers:
  openai:
    base_url: https://api.openai.com/v1
    api_key_env: OPENAI_API_KEY
    pricing: { input_per_1k_usd: 0.00015, output_per_1k_usd: 0.0006 }
```

## Part 7 — Guard it in CI

```yaml
# .github/workflows/promptseal.yml
name: PromptSeal
on: [pull_request]
jobs:
  seal:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: ArsinShaabani/promptseal-action@v1
        with:
          provider: openai:gpt-4o
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

`promptseal ci` (what the action runs):
1. Runs the suite against the provider.
2. Diffs against your sealed baseline.
3. Writes a markdown report to `$GITHUB_STEP_SUMMARY` (visible in the PR).
4. **Exits 1** if any case regressed or pass rate < `ci.min_pass_rate`.

**Baseline strategy:** commit your baseline. `promptseal seal` writes
`.promptseal/baseline.json` — a small self-contained snapshot of the whole baseline
run. It's git-whitelisted (everything else under `.promptseal/` stays ignored), so
after sealing on `main` just `git add .promptseal/baseline.json` and CI gates every
PR against it with no extra wiring. Relax gates with `--min-pass-rate 0.95` for
experimental suites.

```bash
promptseal ci --min-pass-rate 0.95     # tolerate small drift, block real regressions
```

## Part 8 — Reports & automation

```bash
promptseal runs                        # list all runs, baseline marked
promptseal report latest --open        # HTML report for any run
promptseal report 20260929-02 -o r.html
promptseal run --json                  # machine-readable output
promptseal diff --json                 # machine-readable diff
```

Run files are plain JSON in `.promptseal/runs/` — build dashboards, alerts, or
feed them into other tools. Nothing is ever uploaded anywhere.

### Case selection & execution options

```bash
promptseal run --list                  # dry listing — no provider calls, no API key
promptseal run --tags pii,security     # only cases carrying any of these tags
promptseal run --exclude-tags flaky    # skip tagged cases
promptseal run --case pii-guard        # run a single case by ID (great for debugging)
promptseal run --skip-case slow-1,slow-2
promptseal run --fail-fast             # stop at the first failure (saves cost)
promptseal run --concurrency 4         # parallel cases (order preserved)
promptseal runs --json                 # machine-readable run list
promptseal diff --fail-on-regression   # exit 1 on regression — for scripts
promptseal init -p ollama:llama3.1:8b  # scaffold with your default provider
```

The same filters work on `promptseal ci` — gate a tagged subset in CI (e.g.
`--tags critical`) while the full suite runs locally. Tag cases in YAML with
`tags: [pii, security]`. With `--concurrency > 1`, `--fail-fast` is ignored.

## Part 9 — Custom assertions (10 lines of Python)

```python
# In your own plugin module, then import it via entry points or PR it upstream.
from promptseal.assertions import check

@check("mentions_ticket")
def _mentions_ticket(output: str, value, ctx) -> tuple[bool, str]:
    import re
    ok = re.search(rf"BUG-{value}", output) is not None
    return ok, "" if ok else f"no BUG-{value} ticket reference found"
```

Use it in YAML: `- mentions_ticket: 1234`. See `src/promptseal/assertions.py`
for the 18 built-ins as templates.

## Part 10 — Run evals inside pytest

Keep evals next to your unit tests — same command, same report:

```bash
pytest --promptseal                       # collects cases/*.yaml as tests
pytest --promptseal --ps-provider ollama:llama3.1:8b
```

- Opt-in: without the flag, pytest ignores your suites completely.
- One pytest test per case; failures show the exact assertion details.
- The whole session is saved as a PromptSeal run (`suite: pytest`), so it shows
  up in `promptseal runs` and you can `promptseal seal` / `diff` it like any run.
- The plugin registers automatically via a `pytest11` entry point once promptseal
  is installed.

## Part 11 — Test agent behavior: tool calls & multi-turn

Agents act — PromptSeal asserts on **what they did**, not just what they said.
Cases can declare OpenAI tool schemas (`tools:`) and inspect the returned
`tool_calls` trace, or send a full chat history via `messages:`:

```yaml
# cases/agent.yaml
suite: agent
cases:
  - id: weather-tool
    prompt: "What's the weather in Paris?"
    tools:
      - type: function
        function: {name: get_weather, parameters: {}}
    asserts:
      - tools_called: get_weather                 # the tool fired
      - tool_args: {get_weather: {city: Paris}}   # with the right arguments
      - tools_not_called: book_flight             # and nothing it shouldn't

  - id: support-continuation
    messages:                                     # multi-turn conversation in,
      - role: system                              # takes precedence over prompt:
        content: "You are a support agent."
      - role: user
        content: "Where is my order?"
      - role: assistant
        content: "Which email is the order under?"
      - role: user
        content: "ana@example.com"
    asserts:
      - contains_any: ["ORD-", "order"]
      - max_latency_s: 10
```

Assertion reference: `tools_called` (a name or list — every listed tool must
fire), `tools_not_called`, `call_order` (relative order must hold), `tool_args`
(argument key/values of the first call of each tool). Works with any
OpenAI-compatible tool-calling endpoint. Offline, `mock:tools` simulates an
agent that calls `get_weather(city="Paris")` whenever `tools:` are declared.

### Scripted users (`script:`)

Add a `script:` of user turns — after every assistant reply the next scripted
turn is injected, until the script runs out. The final assistant answer is what
gets asserted; latency/cost are summed across round-trips and `turns` is
recorded per case:

```yaml
  - id: support-handoff
    prompt: "Where is my order?"
    script: ["ana@example.com"]     # the scripted user answers with this
    asserts:
      - contains_any: ["ORD-", "order"]
      - max_latency_s: 15
```

### Already have a trace? `promptseal.adapters`

Evaluate traces from any framework with the same assertions — no SDK dependency,
plain dicts (or duck-typed LangChain messages / OpenAI Agents `function_call`
items):

```python
from promptseal.adapters import evaluate_conversation, evaluate_trace, tool_calls_from_agents

# LangChain-style messages (dicts or message objects):
results = evaluate_conversation(
    asserts=[{"tools_called": "get_weather"}, {"contains": "sunny"}],
    messages=my_langchain_messages,
)

# OpenAI Agents SDK run items:
results = evaluate_trace(
    asserts=[{"tool_args": {"get_weather": {"city": "Paris"}}}],
    output="It is sunny in Paris.",
    tool_calls=tool_calls_from_agents(run.items),
)
```

For Claude Code, a hooks recipe: register a `Stop`/`PostToolUse` hook that shells
out to `promptseal ci --tags changed` — the CLI gate does the rest.

## Part 12 — Watch the drift: driftwatch & doctor

```bash
promptseal driftwatch --open       # pass-rate/cost/latency trends per model
promptseal doctor                  # config, providers, registry, storage self-check
```

`driftwatch` renders a self-contained `promptseal-drift.html` from your
`.promptseal/runs/` history — a per provider:model sparkline plus a run table.
No server, works offline. `doctor` verifies the environment before you trust a
seal: config found, default & judge providers resolvable (API keys present),
assertion registry (built-ins + plugins), storage writable — exit 1 on real
problems, warnings for soft ones. Third-party assertion plugins are any
packages exposing the `promptseal.assertions` entry-point group; they register
with the same `@check` decorator and appear in `doctor`.

## Part 13 — Troubleshooting

| Symptom | Fix |
|---|---|
| `No promptseal.yaml found` | Run `promptseal init` (or cd into your project) |
| `environment variable X is not set` | Export the API key named in `providers.<name>.api_key_env` |
| `no baseline saved` | Run `promptseal seal` once |
| `does not support streaming captures` | Set `"stream": false` for recorded requests |
| `unknown provider 'x'` | Add it under `providers:` in `promptseal.yaml` (or use `mock:`) |
| Judge assertions all fail | Set `defaults.judge.provider` in config |
| Windows console shows mojibake | Already handled — CLI forces UTF-8; use Windows Terminal for best colors |
| `Plugin already registered` | Drop `-p promptseal.pytest_plugin` — the plugin auto-registers |
| `tool 'x' was not called` | Declare `tools:` on the case; make sure the model supports tool-calling |

---

**You made it.** Now go seal something. 🦭
Questions → [Discussions](https://github.com/ArsinShaabani/promptseal/discussions) ·
Bugs → [Issues](https://github.com/ArsinShaabani/promptseal/issues)