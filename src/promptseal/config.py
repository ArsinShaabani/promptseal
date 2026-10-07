"""Configuration loading for promptseal.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

CONFIG_FILENAME = "promptseal.yaml"

DEFAULT_PROVIDERS: dict[str, dict[str, Any]] = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEY",
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "api_key_env": None,
    },
    "vllm": {
        "base_url": "http://localhost:8000/v1",
        "api_key_env": None,
    },
}


@dataclass
class ProviderConfig:
    name: str
    base_url: str = ""
    api_key_env: Optional[str] = None
    pricing: dict[str, float] = field(default_factory=dict)  # per-1k-token prices


@dataclass
class JudgeConfig:
    provider: Optional[str] = None  # defaults to the run provider
    params: dict[str, Any] = field(default_factory=dict)  # merged into judge requests


@dataclass
class CIConfig:
    min_pass_rate: float = 1.0
    fail_on_regression: bool = True
    # POSTed on every ci run (verdict, pass rate, regressions) — Slack/Discord/generic.
    alert_webhook: Optional[str] = None


@dataclass
class AppConfig:
    suite: str = "app"
    cases_dir: str = "cases"
    default_provider: str = "mock:echo"
    timeout_s: float = 60.0
    repeat: int = 1  # run each case N times (flaky detection)
    flaky_pass_rate: float = 1.0  # fraction of attempts that must pass, in (0, 1]
    concurrency: int = 1  # parallel case execution (1 = sequential)
    retry_attempts: int = 3  # provider retries on 429/5xx (0 = no retries)
    retry_backoff_s: float = 0.5  # base backoff seconds (exponential + jitter)
    judge_cache: bool = True  # skip judge calls when an identical output was judged
    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    judge: JudgeConfig = field(default_factory=JudgeConfig)
    ci: CIConfig = field(default_factory=CIConfig)
    config_path: Optional[Path] = None

    def provider(self, name: str) -> ProviderConfig:
        return self.providers.get(name) or ProviderConfig(name=name)


def find_config(start_dir: Optional[Path] = None) -> Optional[Path]:
    """Walk up from start_dir (or cwd) looking for promptseal.yaml."""
    current = (start_dir or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        path = candidate / CONFIG_FILENAME
        if path.exists():
            return path
    return None


def load_config(path: Optional[Path] = None) -> AppConfig:
    """Load config from promptseal.yaml, or return sensible defaults."""
    config_path = path or find_config()
    cfg = AppConfig(config_path=config_path)
    if config_path is None:
        return cfg

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    cfg.suite = raw.get("suite", cfg.suite)
    cfg.cases_dir = raw.get("cases_dir", cfg.cases_dir)

    defaults = raw.get("defaults", {}) or {}
    cfg.default_provider = defaults.get("provider", cfg.default_provider)
    cfg.timeout_s = float(defaults.get("timeout_s", cfg.timeout_s))
    cfg.repeat = int(defaults.get("repeat", cfg.repeat))
    cfg.flaky_pass_rate = float(defaults.get("flaky_pass_rate", cfg.flaky_pass_rate))
    if cfg.repeat < 1:
        raise ValueError("defaults.repeat must be >= 1")
    if not 0.0 < cfg.flaky_pass_rate <= 1.0:
        raise ValueError("defaults.flaky_pass_rate must be in (0, 1]")
    cfg.concurrency = int(defaults.get("concurrency", cfg.concurrency))
    if cfg.concurrency < 1:
        raise ValueError("defaults.concurrency must be >= 1")
    cfg.retry_attempts = int(defaults.get("retry_attempts", cfg.retry_attempts))
    if cfg.retry_attempts < 0:
        raise ValueError("defaults.retry_attempts must be >= 0")
    cfg.retry_backoff_s = float(defaults.get("retry_backoff_s", cfg.retry_backoff_s))
    if cfg.retry_backoff_s < 0:
        raise ValueError("defaults.retry_backoff_s must be >= 0")
    cfg.judge_cache = bool(defaults.get("judge_cache", cfg.judge_cache))

    providers_raw = raw.get("providers", {}) or {}
    # Deep-merge: a user block only overrides the keys it sets, so redefining
    # `openai: {api_key_env: X}` never drops the shipped base_url/pricing.
    merged = dict(DEFAULT_PROVIDERS)
    for name, pdata in (providers_raw or {}).items():
        merged[name] = {**(merged.get(name) or {}), **(pdata or {})}
    for name, pdata in merged.items():
        pdata = pdata or {}
        cfg.providers[name] = ProviderConfig(
            name=name,
            base_url=pdata.get("base_url", ""),
            api_key_env=pdata.get("api_key_env"),
            pricing=pdata.get("pricing", {}) or {},
        )

    judge_raw = raw.get("judge", {}) or {}
    _judge_params = judge_raw.get("params") or {}
    if not isinstance(_judge_params, dict):
        raise ValueError("judge.params must be a mapping of model parameters")
    cfg.judge = JudgeConfig(
        provider=judge_raw.get("provider"),
        params=dict(_judge_params),
    )

    ci_raw = raw.get("ci", {}) or {}
    cfg.ci = CIConfig(
        min_pass_rate=float(ci_raw.get("min_pass_rate", 1.0)),
        fail_on_regression=bool(ci_raw.get("fail_on_regression", True)),
        alert_webhook=ci_raw.get("alert_webhook") or None,
    )
    return cfg
