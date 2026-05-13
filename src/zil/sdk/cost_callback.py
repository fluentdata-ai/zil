"""ADK callback that records LLM token usage with optional OTel tracing.

Intercepts LLM responses, extracts token usage metadata, and feeds it
to the :class:`~zil.sdk.cost.CostTracker`.
"""

from __future__ import annotations

import logging
from typing import Any

from zil.sdk.cost import CostResult, CostStatus, CostTracker

logger = logging.getLogger(__name__)

_TRACER_NAME = "zil.cost"


def _try_get_tracer() -> Any:
    """Return an OTel tracer if the SDK is available, else None."""
    try:
        from opentelemetry import trace

        return trace.get_tracer(_TRACER_NAME)
    except ImportError:
        return None


class CostCallback:
    """ADK-compatible callback that tracks token usage.

    Designed to be called after each LLM response. Extracts
    ``usage_metadata`` from the response and records it in the
    ``CostTracker``. Emits OTel span attributes when available.

    Usage::

        cb = CostCallback(tracker, model="gemini-2.0-flash")
        # After an LLM call, extract usage and record:
        cb.record(input_tokens=150, output_tokens=350)
    """

    def __init__(self, tracker: CostTracker, *, model: str = "") -> None:
        self.tracker = tracker
        self.model = model
        self._tracer = _try_get_tracer()

    def record(
        self,
        input_tokens: int,
        output_tokens: int,
        model: str | None = None,
    ) -> CostResult:
        """Record token usage from an LLM response.

        Args:
            input_tokens: Number of input/prompt tokens.
            output_tokens: Number of output/completion tokens.
            model: Model name override (defaults to callback's model).

        Returns:
            CostResult with status and budget info.
        """
        resolved_model = model or self.model
        result = self.tracker.record_usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=resolved_model,
        )

        # Emit OTel span
        if self._tracer is not None:
            self._emit_span(input_tokens, output_tokens, resolved_model, result)

        if result.status == CostStatus.BLOCKED:
            logger.warning("Cost tracking: %s", result.message)
        elif result.status == CostStatus.WARNED:
            logger.warning("Cost tracking: %s", result.message)

        return result

    def record_from_response(self, response: Any) -> CostResult | None:
        """Extract usage metadata from an ADK/LLM response and record it.

        Supports response objects with a ``usage_metadata`` attribute
        (Gemini responses) or a ``usage`` attribute (OpenAI/Anthropic).

        Returns None if no usage data could be extracted.
        """
        input_tokens = 0
        output_tokens = 0

        # Gemini-style: response.usage_metadata
        usage_meta = getattr(response, "usage_metadata", None)
        if usage_meta:
            input_tokens = getattr(usage_meta, "prompt_token_count", 0) or 0
            output_tokens = getattr(usage_meta, "candidates_token_count", 0) or 0
            return self.record(input_tokens, output_tokens)

        # OpenAI/Anthropic-style: response.usage
        usage = getattr(response, "usage", None)
        if usage:
            input_tokens = getattr(usage, "prompt_tokens", 0) or 0
            output_tokens = getattr(usage, "completion_tokens", 0) or 0
            return self.record(input_tokens, output_tokens)

        return None

    def _emit_span(
        self,
        input_tokens: int,
        output_tokens: int,
        model: str,
        result: CostResult,
    ) -> None:
        """Emit an OTel span with usage attributes."""
        with self._tracer.start_as_current_span("llm.usage") as span:
            span.set_attribute("llm.usage.input_tokens", input_tokens)
            span.set_attribute("llm.usage.output_tokens", output_tokens)
            span.set_attribute("llm.usage.total_tokens", input_tokens + output_tokens)
            span.set_attribute("llm.usage.model", model)
            span.set_attribute("llm.usage.status", result.status.value)
            if result.budget_remaining is not None:
                span.set_attribute("llm.usage.budget_remaining", result.budget_remaining)
