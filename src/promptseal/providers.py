"""Model providers: mock (offline demos/tests) and any OpenAI-compatible API."""

from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass
from typing import Any, Optional, Protocol

import httpx

from promptseal.config import AppConfig


class ProviderError(Exception):
    pass


def _is_retryable_status(status: int) -> bool:
    return status == 429 or 500 <= status < 600


def _request_with_retries(
    method: str,
    url: str,
    *,
    headers: Optional[dict[str, str]] = None,
    json_body: Optional[dict[str, Any]] = None,
    timeout_s: float = 60.0,
    max_retries: int = 3,
    backoff_s: float = 0.5,
    label: str = "request",
) -> httpx.Response:
    """GET/POST with exponential backoff + jitter on 429/5xx and transport errors.

    Non-retryable 4xx responses are returned immediately so the caller can turn
    them into a precise error; transport failures and retryable statuses are
    retried (total attempts = max_retries + 1).
    """
    attempts = max(0, int(max_retries)) + 1
    last_exc: Optional[Exception] = None
    resp: Optional[httpx.Response] = None
    for attempt in range(attempts):
        try:
            # follow_redirects=False: 301/302 must surface as errors (a redirect
            # would otherwise replay the request — possibly against a wrong host —
            # and httpx follows them silently by opt-in only.
            if method == "get":
                resp = httpx.get(url, headers=headers, timeout=timeout_s, follow_redirects=False)
            else:
                resp = httpx.post(
                    url, json=json_body, headers=headers, timeout=timeout_s, follow_redirects=False
                )
            last_exc = None
        except httpx.HTTPError as exc:
            resp = None
            last_exc = exc
        done = resp is not None and (
            resp.status_code < 400 or not _is_retryable_status(resp.status_code)
        )
        if done or attempt >= attempts - 1:
            break
        delay = backoff_s * (2**attempt) * (0.5 + random.random())
        if delay > 0:
            time.sleep(delay)
    if resp is not None:
        return resp
    raise ProviderError(f"{label} failed after {attempts} attempt(s): {last_exc}")


@dataclass
class Completion:
    text: str
    latency_ms: int
    cost_usd: Optional[float]
    model: str
    provider: str
    # Normalized OpenAI tool_calls (assistant message), when the model called tools.
    tool_calls: Optional[list[dict[str, Any]]] = None


class Provider(Protocol):
    name: str
    model: str

    def complete(
        self,
        system: Optional[str],
        prompt: str,
        *,
        messages: Optional[list[dict[str, Any]]] = None,
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Optional[Any] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> Completion: ...


class MockProvider:
    """Deterministic provider for demos, tests, and offline development.

    Modes:
      echo    -> "Echo: <prompt>" (or the last user message for multi-turn cases)
      upper   -> uppercase prompt
      denier  -> a polite refusal (useful to simulate failing cases)
      lorem   -> fixed filler text
      tools   -> simulates an agent: calls get_weather(city="Paris") when the
                 case declares `tools:` (empty text, tool_calls set)
    """

    MODES = ("echo", "upper", "denier", "lorem", "tools")

    def __init__(self, mode: str = "echo"):
        if mode not in self.MODES:
            raise ProviderError(f"mock mode must be one of {self.MODES}, got {mode!r}")
        self.mode = mode
        self.name = "mock"
        self.model = f"mock-{mode}"

    def complete(
        self,
        system: Optional[str] = None,
        prompt: str = "",
        *,
        messages: Optional[list[dict[str, Any]]] = None,
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Optional[Any] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> Completion:
        time.sleep(0.005)  # simulate a tiny latency so reports look real
        if messages:
            prompt = next(
                (
                    m["content"]
                    for m in reversed(messages)
                    if isinstance(m, dict)
                    and m.get("role") == "user"
                    and isinstance(m.get("content"), str)
                ),
                prompt,
            )
        text = ""
        tool_calls: Optional[list[dict[str, Any]]] = None
        if self.mode == "echo":
            text = f"Echo: {prompt}"
        elif self.mode == "upper":
            text = prompt.upper()
        elif self.mode == "denier":
            text = "I'm sorry, I cannot help with that."
        elif self.mode == "tools":
            if tools:
                tool_calls = [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": json.dumps({"city": "Paris"}),
                        },
                    }
                ]
        else:
            text = "Lorem ipsum dolor sit amet, consectetur adipiscing elit."
        return Completion(
            text=text,
            latency_ms=12,
            cost_usd=0.0,
            model=self.model,
            provider=self.name,
            tool_calls=tool_calls,
        )


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
        max_retries: int = 3,
        retry_backoff_s: float = 0.5,
    ):
        self.name = name
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.pricing = pricing or {}
        self.max_retries = max_retries
        self.retry_backoff_s = retry_backoff_s

    def _estimate_cost(self, usage: Optional[dict]) -> Optional[float]:
        if not usage or not self.pricing:
            return None
        prompt_tokens = usage.get("prompt_tokens", 0) or 0
        completion_tokens = usage.get("completion_tokens", 0) or 0
        in_price = self.pricing.get("input_per_1k_usd", 0.0)
        out_price = self.pricing.get("output_per_1k_usd", 0.0)
        return (prompt_tokens * in_price + completion_tokens * out_price) / 1000.0

    def complete(
        self,
        system: Optional[str] = None,
        prompt: str = "",
        *,
        messages: Optional[list[dict[str, Any]]] = None,
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Optional[Any] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> Completion:
        chat: list[dict[str, Any]] = (
            list(messages)
            if messages is not None
            else (
                ([{"role": "system", "content": system}] if system else [])
                + [{"role": "user", "content": prompt}]
            )
        )

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: dict[str, Any] = {"model": self.model, "messages": chat}
        if tools:
            payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        if params:
            for key, value in params.items():
                payload.setdefault(key, value)
        started = time.perf_counter()
        try:
            response = _request_with_retries(
                "post",
                f"{self.base_url}/chat/completions",
                headers=headers,
                json_body=payload,
                timeout_s=self.timeout_s,
                max_retries=self.max_retries,
                backoff_s=self.retry_backoff_s,
                label=f"{self.name}:{self.model}",
            )
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 — defensive: helpers must not leak raw errors
            raise ProviderError(f"{self.name}:{self.model} request failed: {exc}") from exc
        latency_ms = int((time.perf_counter() - started) * 1000)

        if response.status_code != 200:
            raise ProviderError(
                f"{self.name}:{self.model} returned HTTP {response.status_code}: {response.text[:300]}"
            )
        try:
            body = response.json()
            message = body["choices"][0]["message"]
            text = message.get("content") or ""
            tool_calls = message.get("tool_calls") or None
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            raise ProviderError(f"{self.name}:{self.model} returned an unexpected body: {exc}") from exc
        return Completion(
            text=text,
            latency_ms=latency_ms,
            cost_usd=self._estimate_cost(body.get("usage")),
            model=self.model,
            provider=self.name,
            tool_calls=tool_calls,
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
        max_retries=config.retry_attempts,
        retry_backoff_s=config.retry_backoff_s,
    )
