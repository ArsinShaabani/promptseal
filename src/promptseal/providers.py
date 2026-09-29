"""Model providers: mock (offline demos/tests) and any OpenAI-compatible API."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Optional, Protocol

import httpx

from promptseal.config import AppConfig


class ProviderError(Exception):
    pass


@dataclass
class Completion:
    text: str
    latency_ms: int
    cost_usd: Optional[float]
    model: str
    provider: str


class Provider(Protocol):
    name: str
    model: str

    def complete(self, system: Optional[str], prompt: str) -> Completion: ...


class MockProvider:
    """Deterministic provider for demos, tests, and offline development.

    Modes:
      echo    -> "Echo: <prompt>"
      upper   -> uppercase prompt
      denier  -> a polite refusal (useful to simulate failing cases)
      lorem   -> fixed filler text
    """

    MODES = ("echo", "upper", "denier", "lorem")

    def __init__(self, mode: str = "echo"):
        if mode not in self.MODES:
            raise ProviderError(f"mock mode must be one of {self.MODES}, got {mode!r}")
        self.mode = mode
        self.name = "mock"
        self.model = f"mock-{mode}"

    def complete(self, system: Optional[str], prompt: str) -> Completion:
        time.sleep(0.005)  # simulate a tiny latency so reports look real
        if self.mode == "echo":
            text = f"Echo: {prompt}"
        elif self.mode == "upper":
            text = prompt.upper()
        elif self.mode == "denier":
            text = "I'm sorry, I cannot help with that."
        else:
            text = "Lorem ipsum dolor sit amet, consectetur adipiscing elit."
        return Completion(text=text, latency_ms=12, cost_usd=0.0, model=self.model, provider=self.name)


class OpenAICompatProvider:
    """Talks to any OpenAI-compatible /chat/completions endpoint.

    Works with OpenAI, OpenRouter, Ollama, vLLM, LiteLLM, Groq, Together, and more.
    """

    def __init__(
        self,
        name: str,
        model: str,
        base_url: str,
        api_key: Optional[str] = None,
        timeout_s: float = 60.0,
        pricing: Optional[dict[str, float]] = None,
    ):
        self.name = name
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.pricing = pricing or {}

    def _estimate_cost(self, usage: Optional[dict]) -> Optional[float]:
        if not usage or not self.pricing:
            return None
        prompt_tokens = usage.get("prompt_tokens", 0) or 0
        completion_tokens = usage.get("completion_tokens", 0) or 0
        in_price = self.pricing.get("input_per_1k_usd", 0.0)
        out_price = self.pricing.get("output_per_1k_usd", 0.0)
        return (prompt_tokens * in_price + completion_tokens * out_price) / 1000.0

    def complete(self, system: Optional[str], prompt: str) -> Completion:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {"model": self.model, "messages": messages}
        started = time.perf_counter()
        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=self.timeout_s,
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.name}:{self.model} request failed: {exc}") from exc
        latency_ms = int((time.perf_counter() - started) * 1000)

        if response.status_code != 200:
            raise ProviderError(
                f"{self.name}:{self.model} returned HTTP {response.status_code}: {response.text[:300]}"
            )
        try:
            body = response.json()
            text = body["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, ValueError) as exc:
            raise ProviderError(f"{self.name}:{self.model} returned an unexpected body: {exc}") from exc
        return Completion(
            text=text,
            latency_ms=latency_ms,
            cost_usd=self._estimate_cost(body.get("usage")),
            model=self.model,
            provider=self.name,
        )


def get_provider(spec: str, config: AppConfig) -> Provider:
    """Build a provider from a spec like 'openai:gpt-4o', 'ollama:llama3.1:8b', or 'mock:echo'."""
    if ":" not in spec:
        raise ProviderError(f"provider spec must look like 'name:model', got {spec!r}")
    name, model = spec.split(":", 1)

    if name == "mock":
        return MockProvider(mode=model or "echo")

    pconf = config.providers.get(name)
    if pconf is None:
        raise ProviderError(
            f"unknown provider {name!r}. Known: {sorted(config.providers)} or 'mock'. "
            f"Add it to promptseal.yaml under providers:."
        )
    api_key = os.environ.get(pconf.api_key_env) if pconf.api_key_env else None
    if pconf.api_key_env and not api_key:
        raise ProviderError(
            f"environment variable {pconf.api_key_env} is not set (required for provider {name!r})"
        )
    return OpenAICompatProvider(
        name=name,
        model=model,
        base_url=pconf.base_url,
        api_key=api_key,
        timeout_s=config.timeout_s,
        pricing=pconf.pricing,
    )
