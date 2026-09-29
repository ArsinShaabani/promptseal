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
    """One eval case: a prompt plus the assertions that define 'correct'."""

    id: str
    prompt: str
    system: Optional[str] = None
    description: Optional[str] = None
    vars: dict[str, Any] = Field(default_factory=dict)
    asserts: list[AssertSpec] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


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


class RunSummary(BaseModel):
    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    pass_rate: float = 0.0
    total_cost_usd: Optional[float] = None
    total_latency_ms: int = 0
    duration_s: float = 0.0


class RunMeta(BaseModel):
    run_id: str
    created_at: str
    provider: str
    model: str
    suite: str
    git_commit: Optional[str] = None
    promptseal_version: str = __version__


class Run(BaseModel):
    """A complete eval run: metadata, summary, and per-case results."""

    meta: RunMeta
    summary: RunSummary
    results: list[CaseResult] = Field(default_factory=list)
