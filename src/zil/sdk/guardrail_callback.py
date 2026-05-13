"""ADK callback that enforces guardrails with optional OTel tracing.

Wraps :class:`~zil.sdk.guardrails.GuardrailEngine` as a pair of
``before_model`` / ``after_model`` callbacks compatible with
``google.adk.agents.LlmAgent``.
"""

from __future__ import annotations

import logging
from typing import Any

from zil.sdk.guardrails import GuardrailEngine, GuardrailResult

logger = logging.getLogger(__name__)

_TRACER_NAME = "zil.guardrails"


def _try_get_tracer() -> Any:
    """Return an OTel tracer if the SDK is available, else None."""
    try:
        from opentelemetry import trace

        return trace.get_tracer(_TRACER_NAME)
    except ImportError:
        return None


class GuardrailCallback:
    """ADK-compatible callback that enforces guardrails.

    Emits OTel spans (``guardrail.check.input`` / ``guardrail.check.output``)
    when a tracer is available.

    Usage::

        cb = GuardrailCallback(engine)
        agent = LlmAgent(..., before_model_callback=cb.before_model,
                               after_model_callback=cb.after_model)
    """

    def __init__(self, engine: GuardrailEngine) -> None:
        self.engine = engine
        self._tracer = _try_get_tracer()

    # ------------------------------------------------------------------
    # Callback entry points
    # ------------------------------------------------------------------

    def check_input(self, text: str) -> GuardrailResult:
        """Check user input and emit an OTel span."""
        result = self._traced_check(
            check_fn=self.engine.check_input,
            text=text,
            span_name="guardrail.check.input",
            direction="input",
        )
        if result.blocked:
            logger.warning(
                "Guardrail blocked input: %s",
                [v.description for v in result.violations],
            )
        return result

    def check_output(self, text: str) -> GuardrailResult:
        """Check agent output and emit an OTel span."""
        result = self._traced_check(
            check_fn=self.engine.check_output,
            text=text,
            span_name="guardrail.check.output",
            direction="output",
        )
        if result.blocked:
            logger.warning(
                "Guardrail blocked output: %s",
                [v.description for v in result.violations],
            )
        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _traced_check(
        self,
        *,
        check_fn: Any,
        text: str,
        span_name: str,
        direction: str,
    ) -> GuardrailResult:
        """Run a guardrail check, optionally wrapped in an OTel span."""
        if self._tracer is None:
            return check_fn(text)

        with self._tracer.start_as_current_span(span_name) as span:
            result: GuardrailResult = check_fn(text)
            span.set_attribute("guardrail.direction", direction)
            span.set_attribute("guardrail.passed", result.passed)
            span.set_attribute("guardrail.action", result.action)
            span.set_attribute("guardrail.violation_count", len(result.violations))
            if result.violations:
                rules = [v.rule for v in result.violations]
                span.set_attribute("guardrail.violated_rules", rules)
            return result
