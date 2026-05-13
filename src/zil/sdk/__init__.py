"""Zil SDK — read manifest + identity files and create a wired agent."""

from zil.sdk.agent import create_agent
from zil.sdk.config import AgentConfig
from zil.sdk.cost import CostTracker
from zil.sdk.guardrail_callback import GuardrailCallback
from zil.sdk.guardrails import GuardrailEngine, GuardrailResult, Violation
from zil.sdk.telemetry import setup_console_telemetry, setup_telemetry

# Module-level config singleton — populated by create_agent()
config: AgentConfig = AgentConfig()

# Module-level cost tracker singleton — populated by create_agent()
cost: CostTracker = CostTracker()

__all__ = [
    "create_agent",
    "config",
    "cost",
    "AgentConfig",
    "CostTracker",
    "GuardrailCallback",
    "GuardrailEngine",
    "GuardrailResult",
    "Violation",
    "setup_telemetry",
    "setup_console_telemetry",
]
