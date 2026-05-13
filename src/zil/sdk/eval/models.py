"""Data models for the Zil evaluation engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class CaseVerdict(StrEnum):
    """Outcome of a single eval case."""

    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"


@dataclass
class JudgeConfig:
    """LLM configuration for the evaluation judge (separate from agent LLM)."""

    provider: str = "gemini"
    model: str = "gemini-2.0-flash"
    api_key_env: str = "GOOGLE_API_KEY"


@dataclass
class ExecutionConfig:
    """Controls for eval execution (concurrency, retries, timeout)."""

    concurrency: int = 1
    retries: int = 0
    timeout: int = 60


@dataclass
class EvalEngineConfig:
    """Top-level eval engine configuration (evals/config.yaml)."""

    framework: str = "deepeval"
    judge: JudgeConfig = field(default_factory=JudgeConfig)
    metric_thresholds: dict[str, float] = field(default_factory=dict)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)


@dataclass
class EvalCase:
    """A single evaluation test case."""

    input: str
    expected_output: str | None = None
    expected_contains: list[str] = field(default_factory=list)
    expected_tool: str | None = None
    expected_action: str | None = None
    context: list[str] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)


@dataclass
class CaseGroup:
    """A named group of eval cases loaded from a single file."""

    name: str
    cases: list[EvalCase]
    weight: float = 1.0


@dataclass
class EvalSuiteConfig:
    """Parsed eval suite configuration (evals/baseline.yaml)."""

    name: str = "baseline"
    pass_threshold: float = 0.85
    metrics: list[str] = field(default_factory=list)
    groups: list[CaseGroup] = field(default_factory=list)


@dataclass
class CaseResult:
    """Result of evaluating a single case."""

    case: EvalCase
    verdict: CaseVerdict
    actual_output: str = ""
    score: float = 0.0
    metric_scores: dict[str, float] = field(default_factory=dict)
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class GroupResult:
    """Aggregated results for one case group."""

    name: str
    weight: float
    pass_rate: float
    case_results: list[CaseResult]


@dataclass
class SuiteResult:
    """Final result of running a full eval suite."""

    suite_name: str
    score: float
    passed: bool
    threshold: float
    group_results: list[GroupResult]

    @property
    def total_cases(self) -> int:
        return sum(len(g.case_results) for g in self.group_results)

    @property
    def passed_cases(self) -> int:
        return sum(
            1
            for g in self.group_results
            for c in g.case_results
            if c.verdict == CaseVerdict.PASS
        )

    @property
    def failed_cases(self) -> int:
        return self.total_cases - self.passed_cases
