"""Eval adapter protocol — pluggable evaluation backends."""

from __future__ import annotations

from typing import Any, Protocol

from zil.sdk.eval.models import (
    CaseResult,
    EvalCase,
    EvalEngineConfig,
)


class EvalAdapter(Protocol):
    """Protocol for evaluation framework adapters.

    Adapters translate Zil's EvalCase format into framework-specific
    objects, run evaluations, and return standardized results.
    """

    def configure(self, config: EvalEngineConfig) -> None:
        """Configure the adapter with engine settings (judge LLM, etc.)."""
        ...

    def evaluate_case(
        self,
        case: EvalCase,
        actual_output: str,
        metrics: list[str],
    ) -> CaseResult:
        """Evaluate a single case against the actual agent output.

        Args:
            case: The eval case definition.
            actual_output: The agent's response to the case input.
            metrics: List of metric names to apply (e.g., ["hallucination"]).

        Returns:
            A CaseResult with verdict, scores, and details.
        """
        ...

    def available_metrics(self) -> list[str]:
        """Return the list of metric names this adapter supports."""
        ...


def get_adapter(framework: str) -> Any:
    """Get an adapter instance by framework name."""
    if framework == "deepeval":
        from zil.sdk.eval.adapters.deepeval import DeepEvalAdapter

        return DeepEvalAdapter()

    raise ValueError(
        f"Unknown eval framework: {framework!r}. "
        "Supported frameworks: deepeval"
    )
