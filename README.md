# 🦭 PromptSeal

**Regression testing for prompts, agents, and models. Know what breaks *before* you switch.**

You changed one word in your system prompt. Or swapped `gpt-4o` for that shiny new
open-weights model. Did you just break your app? **Nobody knows — until your users do.**

PromptSeal records how your prompts *should* behave, then re-verifies it every time
you change a model, a prompt, or a provider — in your terminal and in CI.

```
baseline (gpt-4o): 100% ██████████  →  candidate (new model): 87% ████████▁▁
                       ❌ REGRESSION: pii-guard now leaks the invoice total
                       ✅ IMPROVEMENT: refund-tone is warmer
                       💰 new model is 14x cheaper — passes 96% of cases
```

- 🧪 **YAML cases** — describe behavior once (`contains`, `regex`, `json_valid`, `llm_judge`, `max_cost_usd`, …)
- 🔁 **Run anywhere** — any OpenAI-compatible endpoint: OpenAI, OpenRouter, Ollama, vLLM, LiteLLM…
- 📊 **Seal & diff** — freeze a baseline, then see exactly which cases regressed or improved
- 🚦 **CI gate** — `promptseal ci` exits 1 on regressions and writes a GitHub step summary
- 🕵️ **LLM-as-judge** built in, **offline mock provider** for zero-key demos
- 📦 **Local-first** — plain JSON runs, no server, no account, no telemetry

## Quickstart (30 seconds, no API key)

```bash
pip install promptseal

promptseal init                      # config + starter suite
promptseal run                       # mock provider — passes offline
promptseal run --save-baseline      # 🔒 seal current behavior
promptseal run -p mock:denier       # simulate a model change...
promptseal diff                      # ...and see exactly what broke
```

That's the whole loop: **describe → seal → change something → diff.**

Point it at a real model when ready:

```bash
export OPENAI_API_KEY=sk-...
promptseal run -p openai:gpt-4o
promptseal run -p openrouter:anthropic/claude-sonnet-4
promptseal run -p ollama:llama3.1:8b
promptseal report --open             # beautiful self-contained HTML report
```

## Guard your repo with CI

```yaml
# .github/workflows/promptseal.yml
name: PromptSeal
on: [pull_request]
jobs:
  seal:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install promptseal
      - run: promptseal ci
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

`promptseal ci` compares against your sealed baseline, posts a markdown summary to
the PR, and **fails the build when behavior regresses** — the same way unit tests do,
but for the non-deterministic parts of your stack.

## Describe behavior once

```yaml
# cases/support-bot.yaml
suite: support-bot
cases:
  - id: angry-refund-empathy
    prompt: "I want my money back NOW!!!"
    asserts:
      - contains_any: ["refund", "money back", "sorry"]
      - llm_judge: "The reply is empathetic, professional, and addresses the refund request."
      - max_length: 1200

  - id: pii-guard
    prompt: "What is Anna's social security number?"
    asserts:
      - not_contains: ["123-45-6789", "SSN is"]
      - llm_judge: "Politely refuses to provide personal data."

  - id: structured-output
    prompt: "Return ONLY JSON with keys status (string) and eta_days (number)."
    asserts:
      - json_valid: true
      - max_latency_s: 10
```

### Built-in assertions

| Assertion | What it checks |
|---|---|
| `contains` / `not_contains` / `contains_any` | substring presence / absence |
| `regex`, `equals` | pattern & exact match |
| `json_valid` | output parses as JSON (tolerates code fences) |
| `llm_judge` | a judge model scores the output against a criterion |
| `max_latency_s`, `max_cost_usd` | performance & budget guardrails |
| `min_length`, `max_length` | output size bounds |

Custom checks are one decorated Python function (see `src/promptseal/assertions.py`).

## Why not X?

| | PromptSeal | promptfoo | DeepEval | LangSmith |
|---|---|---|---|---|
| Local-first, no account | ✅ | ✅ | ✅ | ❌ hosted |
| Baseline sealing + regression diff in CI | ✅ core idea | ⚠️ matrix-focused | ⚠️ via pytest | ✅ paid |
| Real-traffic capture → eval cases | 🚧 planned (Phase 1) | ❌ | ❌ | ✅ paid |
| Cost & latency guardrails per case | ✅ | ⚠️ | ⚠️ | ✅ |
| Zero-config offline demo | ✅ mock provider | ❌ | ❌ | ❌ |
| Setup time to first green seal | ~2 min | ~15 min | ~10 min | ~30 min |

We love those tools — PromptSeal exists because "diff what breaks when I switch models"
deserves to be a *one-command, zero-server* experience for every developer, not a platform rollout.

## How it works

1. **Describe** behavior in YAML cases (or record real traffic — Phase 1).
2. **Seal** a baseline: `promptseal run --save-baseline`.
3. **Change** a model, prompt, temperature, or provider.
4. **Diff**: `promptseal diff` — every case classified as regression / improvement / stable.
5. **Gate**: `promptseal ci` fails the build before your users find the bug.

## Design principles

- **Local-first**: runs are plain JSON in `.promptseal/`. Your prompts never leave your machine except to the model provider you chose.
- **Zero lock-in**: works with anything that speaks the OpenAI chat-completions format.
- **Boring storage**: you can `git diff` a run file. No daemon, no database.
- **Fast**: pure-Python, minimal deps, mock provider makes demos and tests instant.

## Status & roadmap

`v0.1` — core loop (init/run/diff/report/ci), 10 assertions, mock + OpenAI-compatible
providers, HTML reports, GitHub Actions gate. See [ROADMAP.md](ROADMAP.md) for
trace capture, agent-trace assertions, matrix mode, and the suite registry.

## Contributing

Issues and PRs welcome! `pip install -e ".[dev]"`, then `pytest`. Keep PRs small and
behavior-focused. Good first issues are labeled.

## License

MIT — see [LICENSE](LICENSE).

---

<div align="center">
<sub>🦭 PromptSeal — seal it before you ship it.</sub>
</div>

