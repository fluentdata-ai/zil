"""
hello-agent — Main agent entry point.

This is a minimal Zil reference agent that demonstrates:
- Identity composition (persona + instructions + guardrails)
- Runtime guardrail engine (prompt injection detection, PII scanning)
- OpenTelemetry tracing (optional)
"""

from pathlib import Path

import zil


def get_greeting() -> str:
    """Return a greeting message. This is an example tool."""
    return "Hello from the Zil reference agent!"


root_agent = zil.create_agent(
    project_dir=Path(__file__).parent.parent,
    tools=[get_greeting],
    enable_guardrails=True,
    enable_telemetry=False,
)
