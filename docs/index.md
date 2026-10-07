---
hide:
  - navigation
  - toc
---

# 🦭 PromptSeal

**Regression testing for prompts, agents, and models. Know what breaks *before* you switch.**

You changed one word in your system prompt. Or swapped `gpt-4o` for a new open-weights
model. Did you just break your app? **Nobody knows — until your users do.**

PromptSeal records how your prompts *should* behave, then re-verifies it every time
you change a model, a prompt, or a provider — in your terminal and in CI.

```bash
pip install promptseal

promptseal init                      # config + starter suite
promptseal run                       # mock provider — passes offline
promptseal seal                      # 🔒 seal current behavior as baseline
promptseal run -p mock:denier        # simulate a model change...
promptseal diff                      # ...and see exactly what broke
```

That's the whole loop: **describe → seal → change something → diff.**

## Highlights

- 🧪 **YAML cases** — 14 built-in assertions: `contains`, `regex`, `json_valid`,
  `llm_judge`, `max_cost_usd`, …
- 🔁 **Any OpenAI-compatible endpoint** — OpenAI, OpenRouter, Ollama, vLLM, LiteLLM…
- 📊 **Seal & diff** — regression / improvement / stable, per case
- 🚦 **CI gate** — `promptseal ci` fails the build and writes the PR summary ·
  official [GitHub Action](https://github.com/ArsinShaabani/promptseal-action)
- 🎲 **Flaky detection** — `--repeat N` with a statistical pass threshold
- 🎥 **Capture reality** — local proxy (`record`) or the in-process
  `promptseal.capture` SDK turn real traffic into cases
- 🧪 **pytest plugin** — `pytest --promptseal` runs evals next to your unit tests
- 🦭 **v0.8: reliability & trust** — retries with backoff, `params:` passthrough,
  judge cache, XSS-safe reports, [CHANGELOG](https://github.com/ArsinShaabani/promptseal/blob/main/CHANGELOG.md)
- 📦 **Local-first** — plain JSON runs, no server, no account, no telemetry

## Links

- 📦 [PyPI](https://pypi.org/project/promptseal/) — `pip install promptseal`
- 🐙 [GitHub](https://github.com/ArsinShaabani/promptseal) ·
  [promptseal-action](https://github.com/ArsinShaabani/promptseal-action)
- 📚 [Full tutorial](tutorial.md) · [آموزش فارسی](tutorial.fa.md) ·
  [Roadmap](roadmap.md)