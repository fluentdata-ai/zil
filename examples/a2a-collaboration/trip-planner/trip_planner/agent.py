"""
trip-planner — A2A caller entry point.

Peers declared under ``spec.collaborators`` are wired automatically by
``zil.create_agent()``: the ADK adapter turns each peer into a callable tool
(backed by A2A ``RemoteA2aAgent``), with the ``skills`` allowlist, the declared
``auth`` mode, and the ``X-Zil-Caller-Agent`` identity header applied. The LLM
decides when to call the ``weather`` peer based on the instructions.

Requires the weather-agent to be reachable at ``$WEATHER_AGENT_URL``
(see the example README for how to start it with ``zil serve``).
"""

from pathlib import Path

import zil

root_agent = zil.create_agent(
    project_dir=Path(__file__).parent.parent,
    enable_guardrails=True,
    enable_cost_tracking=True,
    enable_telemetry=False,
)
