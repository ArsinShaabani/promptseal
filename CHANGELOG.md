# 🦭 PromptSeal — Changelog

All notable changes, newest first. Follows [Keep a Changelog](https://keepachangelog.com/)
conventions loosely; versions are [SemVer](https://semver.org/)-ish.

## [Unreleased]

## [0.8.0] — Reliability & trust release

Fixes every finding of the v0.7.0 technical audit:

### Fixed
- HTML reports are XSS-safe: Jinja templates now render with `autoescape=True`
  (model outputs and assertion details can no longer inject markup).
- Webhook alerts are honest: non-2xx responses raise via `raise_for_status()`,
  so a wrong hook URL reports failure instead of printing "sent".
- The traffic recorder answers `GET /v1/models` (mock list or upstream
  passthrough), so OpenAI SDKs and LangChain can connect through the proxy.
- Provider blocks in `promptseal.yaml` deep-merge over the shipped defaults —
  redefining only `api_key_env` no longer drops `base_url`/pricing.
- Filtered CI runs (`--tags/--case/...`) diff only executed cases: baseline-only
  ids no longer pollute `missing_cases`.
- `runs` ordering is deterministic: sorts by `(created_at, run_id)`.
- `driftwatch` renders an empty-history page instead of crashing.
- Empty judge answers return a clean failure instead of `IndexError`.

### Added
- Retries: exponential backoff + jitter on 429/5xx and transport errors
  (`defaults.retry_attempts`, `defaults.retry_backoff_s`).
- Case-level `params:` (temperature, max_tokens, ...) passed straight to the
  model; `judge.params` for the judge calls.
- Judge-answer cache (`.promptseal/judge-cache.json`, exact-match, persisted):
  reruns skip paid judge calls; disable with `defaults.judge_cache: false`.
- New GitHub Action input `version:` — pin an exact release, and the PR-comment
  step now runs on `always()` so it also fires when the gate fails.
- pytest plugin: judge errors become per-case errors, and its judge verdicts
  use the same answer cache.

## [0.7.0] — Teams & scale (Phase 3 begins)

- `extends:` suite inheritance for monorepos (child overrides by case id,
  chains, cycle errors; extended bases never double-load).
- `$PROMPTSEAL_HOME` relocates the whole `.promptseal` store (shared baselines).
- `promptseal audit` + append-only `audit.log` for every seal/diff/ci.
- `promptseal server`: read-only local dashboard + JSON API
  (`/api/runs`, `/api/runs/<id>`, `/api/stats`, `/api/health`), localhost-only.
- `ci.alert_webhook`: POST a JSON verdict to Slack/Discord/generic hooks.
- Run-id collision fix: same-second runs get `-2/-3/...` suffixes.
- Docs site (mkdocs-material) auto-deployed to GitHub Pages.

## [0.6.0] — Agent-Native complete (Phase 2 complete)

- Agent tool-call assertions: `tools_called`, `tools_not_called`, `call_order`,
  `tool_args` (offline via `mock:tools`).
- Multi-turn `messages:` cases + scripted-user simulation (`script:`).
- `promptseal.adapters`: evaluate LangChain/OpenAI-Agents traces without SDKs.
- `promptseal driftwatch`: per-case cost/latency percentiles + cheapest provider.
- `promptseal doctor`: config/provider/registry/storage self-check.

## [0.5.0] — Filters & control

- `--tags/--exclude-tags/--case/--skip-case` filters on `run` and `ci`,
  `--list` dry listing, `--fail-fast`, `--concurrency N`,
  `diff --fail-on-regression`, `runs --json`, `init -p/--suite`,
  global `--version`.

## [0.4.0] — Agent-native begins

- 4 agent tool-call assertions + multi-turn `messages:` cases
  (`mock:tools` simulation); `promptseal driftwatch` trend dashboard;
  `promptseal doctor` self-check; assertion plugins via entry points;
  run-id collision fix.

## [0.3.0] — Hardening & ecosystem hooks

- Committed self-contained baselines (`baseline.json` embeds the run,
  git-whitelisted).
- Flaky detection: `run --repeat N` + `flaky_pass_rate`.
- `promptseal.capture` in-process SDK.
- pytest plugin (`pytest --promptseal`).
- mkdocs-material docs site.

## [0.2.0] — Matrix, recorder, action

- Multi-model matrix comparison (`run -p a -p b`), `seal` command, `--json` output.
- `promptseal record`: local traffic-capture proxy with PII redaction.
- Official GitHub Action.
- Hero demo GIF; bilingual docs (EN/FA).

## [0.1.0] — Core loop

- `init` / `run` / `seal` / `diff` / `report` / `runs` / `ci`,
  10 built-in assertions, mock + OpenAI-compatible providers,
  baseline sealing, CI gate with GitHub step summaries.