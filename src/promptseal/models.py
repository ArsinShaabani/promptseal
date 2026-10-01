"""Core data models for suites, cases, and runs."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from promptseal._version import __version__


class AssertSpec(BaseModel):
    """A single assertion to run against a model output."""

    type: str
    value: Any = None
    weight: float = 1.0
    extra: dict[str, Any] = Field(default_factory=dict)


class AssertResult(BaseModel):
    """Outcome of one assertion."""

    type: str
    passed: bool
    detail: str = ""


class Case(BaseModel):
    """One eval case: a prompt (or multi-turn messages) plus assertions."""

    id: str
    prompt: str = ""
    system: Optional[str] = None
    description: Optional[str] = None
    vars: dict[str, Any] = Field(default_factory=dict)
    asserts: list[AssertSpec] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    # Multi-turn input: full chat history sent as-is; takes precedence over prompt.
    messages: Optional[list[dict[str, Any]]] = None
    # Agent traces: OpenAI tool schemas forwarded to the provider.
    tools: Optional[list[dict[str, Any]]] = None
    tool_choice: Optional[Any] = None
    # Scripted-user simulation: after each assistant reply, inject the next user
    # turn from `script` and continue until the script is exhausted.
    script: Optional[list[str]] = None


class Suite(BaseModel):
    """A named group of cases loaded from one YAML file."""

    name: str
    source_file: str = ""
    description: Optional[str] = None
    cases: list[Case] = Field(default_factory=list)


class CaseResult(BaseModel):
    """Outcome of one case in a run."""

    case_id: str
    status: str  # "pass" | "fail" | "error"
    output: str = ""
    latency_ms: int = 0
    cost_usd: Optional[float] = None
    assertion_results: list[AssertResult] = Field(default_factory=list)
    error: Optional[str] = None
    # Present when the case ran with repeat > 1 (flaky detection).
    attempts: Optional[int] = None
    passed_attempts: Optional[int] = None
    # Normalized tool_calls from the assistant message (agent traces).
    tool_calls: Optional[list[dict[str, Any]]] = None
    # Provider round-trips for this case (present on scripted-user runs).
    turns: Optional[int] = None


class RunSummary(BaseModel):
    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    pass_rate: float = 0.0
    total_cost_usd: Optional[float] = None
    total_latency_ms: int = 0
    duration_s: float = 0.0
    # True when --fail-fast aborted the run at the first failing case.
    interrupted: bool = False


class RunMeta(BaseModel):
    run_id: str
    created_at: str
    provider: str
    model: str
    suite: str
    git_commit: Optional[str] = None
    promptseal_version: str = __version__
    # Flaky detection settings recorded with the run (repeat > 1 = repeated runs).
    repeat: int = 1
    flaky_pass_rate: float = 1.0


class Run(BaseModel):
    """A complete eval run: metadata, summary, and per-case results."""

    meta: RunMeta
    summary: RunSummary
    results: list[CaseResult] = Field(default_factory=list)
