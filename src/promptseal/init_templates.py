"""Starter files written by `promptseal init`."""

INIT_YAML = """\
# PromptSeal configuration
version: 1
suite: my-app
cases_dir: cases

defaults:
  # Any OpenAI-compatible provider works:
  #   openai:gpt-4o | openrouter:anthropic/claude-sonnet-4 | ollama:llama3.1:8b | vllm:model
  # Start offline with the deterministic mock provider:
  provider: mock:echo
  timeout_s: 60
  # Reliability: retries with backoff+jitter on 429/5xx, cached judge verdicts.
  retry_attempts: 3
  retry_backoff_s: 0.5
  judge_cache: true
  judge:
    # Used by llm_judge assertions. Defaults to the run provider if unset.
    # provider: openai:gpt-4o-mini
    # params: {temperature: 0}   # fixed judge params (merged into judge requests)

providers:
  openai:
    base_url: https://api.openai.com/v1
    api_key_env: OPENAI_API_KEY
  openrouter:
    base_url: https://openrouter.ai/api/v1
    api_key_env: OPENROUTER_API_KEY
  ollama:
    base_url: http://localhost:11434/v1
    api_key_env: null

ci:
  min_pass_rate: 1.0
  fail_on_regression: true
"""

INIT_CASES = """\
suite: smoke
description: Minimal smoke suite — passes with `mock:echo` so you can try PromptSeal offline.

cases:
  - id: echo-greeting
    description: The mock provider echoes the prompt back.
    prompt: "Hello from PromptSeal!"
    asserts:
      - contains: "Echo"
      - max_latency_s: 2

  - id: echo-content
    prompt: "The quick brown fox"
    asserts:
      - contains: "Echo"
      - contains_any: ["quick", "lazy"]
      - min_length: 10
"""
