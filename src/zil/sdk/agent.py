"""Create an agent wired from Zil manifest and identity files.

Dispatches to the appropriate framework backend based on
``spec.runtime.framework`` in the manifest.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from zil.sdk.identity import compose_instruction
from zil.sdk.loader import ProjectContext, load_project

logger = logging.getLogger(__name__)


# Backward-compatible re-exports from the ADK backend.
# User code may import `from zil.sdk.agent import resolve_model`.
def resolve_model(llm_adapter: dict[str, Any]) -> str:
    """Map an LLM adapter config to an ADK-compatible model string."""
    from zil.sdk.frameworks.adk.backend import resolve_model as _resolve

    return _resolve(llm_adapter)


def _load_skills(skills_dir: Any) -> dict[str, Any]:
    """Backward-compat re-export."""
    from zil.sdk.frameworks.adk.backend import _load_skills as _impl

    return _impl(skills_dir)


def create_agent(
    *,
    tools: list[Callable[..., Any]] | None = None,
    project_dir: str | Path | None = None,
    name: str | None = None,
    description: str | None = None,
    model: str | None = None,
    instruction: str | None = None,
    thinking_budget: int | None = None,
    enable_telemetry: bool = True,
    enable_guardrails: bool = True,
    enable_cost_tracking: bool = True,
    enable_mcp: bool = True,
    enable_memory: bool = True,
    enable_memory_seed: bool = True,
    raw: bool = False,
) -> Any:
    """Create an agent wired from the Zil project manifest.

    Reads ``manifest.yaml``, identity files, and adapter config from the
    project directory (auto-detected from cwd if not given), then dispatches
    to the appropriate ``FrameworkBackend`` based on ``spec.runtime.framework``.

    Args:
        tools: Tool functions to attach to the agent.
        project_dir: Explicit project root (default: walk up from cwd).
        name: Override the agent name from the manifest.
        description: Override the description from the manifest.
        model: Override the model string from the adapter config.
        instruction: Override the composed instruction entirely.
        thinking_budget: Override thinking token budget from the manifest.
            Set to an integer to enable Gemini thinking mode with that
            many tokens allocated for chain-of-thought reasoning.
            ``None`` (default) falls back to ``spec.thinking_budget``
            in the manifest.
        enable_telemetry: Wire up OTel tracing from observability config
            (default ``True``).  Set to ``False`` in tests or when
            managing OTel providers yourself.
        enable_guardrails: Load and enforce guardrail rules from
            ``identity/guardrails.yaml`` at runtime (default ``True``).
        enable_cost_tracking: Track token usage and enforce budgets from
            ``spec.cost`` in the manifest (default ``True``).
        enable_mcp: Auto-connect to MCP servers declared in
            ``spec.tools.mcp_servers`` (default ``True``).  Set to ``False``
            in tests or when wiring MCP toolsets manually.
        raw: If ``True``, return the ``WiredAgent`` handle instead of the
            inner framework object.  Use this with ``zil.Session``.

    Returns:
        The underlying framework agent object (e.g. ``LlmAgent`` for ADK),
        or a ``WiredAgent`` if ``raw=True``.
    """
    from zil.sdk.frameworks import AgentSpec, registry

    if project_dir:
        dir_path = Path(project_dir)
    else:
        # Auto-detect from caller's file location (works in Cloud Run
        # where CWD ≠ the agent module directory).
        import inspect

        caller_frame = inspect.stack()[1]
        caller_file = caller_frame.filename
        dir_path = Path(caller_file).resolve().parent

    ctx: ProjectContext = load_project(dir_path)

    # Populate the module-level config singleton with env declarations
    import zil
    if ctx.env_declarations:
        # Determine module dir: use dir_path if it differs from project root,
        # otherwise derive from manifest name (e.g. "my-agent" → "my_agent/")
        module_dir = dir_path
        if module_dir == ctx.project_dir:
            candidate = ctx.project_dir / ctx.name.replace("-", "_")
            if candidate.is_dir():
                module_dir = candidate
        zil.config._initialize(
            ctx.env_declarations,
            project_dir=ctx.project_dir,
            module_dir=module_dir,
        )

    if enable_telemetry and ctx.observability:
        from zil.sdk.telemetry import setup_telemetry

        setup_telemetry(
            ctx.observability,
            agent_name=ctx.name,
            agent_version=ctx.version,
        )

    # Load guardrail engine from identity/guardrails.yaml
    guardrail_callback = None
    if enable_guardrails and ctx.identity.guardrails:
        from zil.sdk.guardrail_callback import GuardrailCallback
        from zil.sdk.guardrails import GuardrailEngine

        engine = GuardrailEngine.from_config(ctx.identity.guardrails)
        guardrail_callback = GuardrailCallback(engine)
        logger.info(
            "Guardrails active — %d rules loaded (%s input, %s output)",
            engine.rule_count,
            "✓" if engine.has_input_checks else "✗",
            "✓" if engine.has_output_checks else "✗",
        )

    # Load cost tracker from spec.cost
    cost_callback = None
    if enable_cost_tracking:
        from zil.sdk.cost_callback import CostCallback

        resolved_model_for_cost = model or resolve_model(ctx.llm_adapter)
        zil.cost._initialize(ctx.cost_config)
        cost_callback = CostCallback(
            tracker=zil.cost,
            model=resolved_model_for_cost,
        )
        if ctx.cost_config:
            logger.info(
                "Cost tracking active — session limit: %s, request limit: %s",
                ctx.cost_config.get("max_tokens_per_session", "none"),
                ctx.cost_config.get("max_tokens_per_request", "none"),
            )

    # Resolve model and instruction
    resolved_model = model or resolve_model(ctx.llm_adapter)
    resolved_instruction = instruction or compose_instruction(
        persona=ctx.identity.persona,
        instructions=ctx.identity.instructions,
        guardrails=ctx.identity.guardrails,
    )
    resolved_name = name or ctx.name.replace("-", "_")

    # Collect MCP server configs (raw dicts — backend wires them)
    mcp_server_configs: list[dict[str, Any]] = []
    if enable_mcp and ctx.tools_config:
        mcp_server_configs = ctx.tools_config.get("mcp_servers", [])

    # Build the memory provider from adapters/memory.yaml (if declared)
    memory_provider = None
    if enable_memory and ctx.memory_config is not None:
        from zil.sdk.memory.loader import build_provider

        memory_provider = build_provider(ctx.memory_config)
        logger.info(
            "Memory active — provider=%s, mode=%s, namespace=%s, scopes=%s",
            ctx.memory_config.provider,
            ctx.memory_config.mode,
            ctx.memory_config.namespace,
            [s.value for s in ctx.memory_config.scopes] or "all",
        )

        # Idempotently install bundled seed memories (RFC-003 seeding).
        seed_enabled = enable_memory_seed and os.environ.get(
            "ZIL_MEMORY_SEED", "1"
        ) != "0"
        if seed_enabled:
            from zil.sdk.memory.seed import resolve_seed_path, seed_if_needed

            seed_path = resolve_seed_path(ctx.project_dir, ctx.memory_config)
            if seed_path is not None:
                report = seed_if_needed(
                    memory_provider, ctx.memory_config, seed_path
                )
                if report.seeded:
                    logger.info("Memory seed installed — %d entries", report.seeded)
                elif report.skipped:
                    logger.info("Memory seed skipped — %s", report.reason)

    # Build the framework-neutral AgentSpec
    agent_spec = AgentSpec(
        name=resolved_name,
        version=ctx.version,
        description=description or ctx.description,
        instructions=resolved_instruction,
        model=resolved_model,
        tool_callables=list(tools or []),
        mcp_server_configs=mcp_server_configs,
        sub_agent_specs=ctx.agents,
        thinking_budget=thinking_budget or ctx.thinking_budget,
        observability=ctx.observability,
        raw_manifest=ctx.manifest,
        guardrail_callback=guardrail_callback,
        cost_callback=cost_callback,
        memory_config=ctx.memory_config,
        memory_provider=memory_provider,
        context=ctx,
    )

    # Dispatch to the appropriate framework backend
    backend = registry.get(ctx.framework)
    wired = backend.wire(agent_spec)

    # Return WiredAgent for Session API, or inner for backward compat
    if raw:
        return wired
    return wired.inner
