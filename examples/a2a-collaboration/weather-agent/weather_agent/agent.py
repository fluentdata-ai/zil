"""
weather-agent — A2A callee/peer entry point.

A weather specialist that is invoked by the trip-planner over A2A. Its
`get-forecast` skill is advertised on the Agent Card served at
``/.well-known/agent-card.json`` by ``zil serve``.

The ``get_forecast`` tool below is a deterministic stand-in for a real weather
API so the example runs offline.
"""

from pathlib import Path

import zil


def get_forecast(location: str, date: str = "today") -> str:
    """Return an illustrative weather forecast for a location.

    Replace this with a real weather API call in production.
    """
    return (
        f"[illustrative] {location} on {date}: partly cloudy, 22°C, light breeze. "
        "Advice: a light jacket is plenty; no umbrella needed."
    )


root_agent = zil.create_agent(
    project_dir=Path(__file__).parent.parent,
    tools=[get_forecast],
    enable_guardrails=True,
    enable_cost_tracking=True,
    enable_telemetry=False,
)
