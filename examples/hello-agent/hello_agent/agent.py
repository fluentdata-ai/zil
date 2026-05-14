"""
hello-agent — Main agent entry point.

This is a minimal Zil reference agent that demonstrates:
- Identity composition (persona + instructions + guardrails)
- Runtime guardrail engine (prompt injection detection, PII scanning)
- Token-based cost tracking with budget enforcement
- OpenTelemetry tracing (optional)
"""

from pathlib import Path

import zil


def get_greeting() -> str:
    """Return a greeting message. This is an example tool."""
    return "Hello from the Zil reference agent!"


def get_usage() -> str:
    """Return current token usage for this session."""
    remaining = zil.cost.budget_remaining
    budget_info = f", {remaining} tokens remaining" if remaining is not None else ""
    by_model = ", ".join(
        f"{m}: {c.total_tokens}" for m, c in zil.cost.by_model.items()
    )
    model_info = f" ({by_model})" if by_model else ""
    return (
        f"Session: {zil.cost.total_tokens} tokens across "
        f"{zil.cost.request_count} requests{budget_info}{model_info}"
    )


root_agent = zil.create_agent(
    project_dir=Path(__file__).parent.parent,
    tools=[get_greeting, get_usage],
    enable_guardrails=True,
    enable_cost_tracking=True,
    enable_telemetry=False,
)
