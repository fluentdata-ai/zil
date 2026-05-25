"""Create an ADK agent wired from Zil manifest and identity files."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from zil.sdk.identity import compose_instruction
from zil.sdk.loader import ProjectContext, load_project

logger = logging.getLogger(__name__)

# ADK model string mapping.
# Keys match the (provider, model) values in adapters/llm.yaml.
_MODEL_MAP: dict[tuple[str, str], str] = {
    # Anthropic — ADK uses LiteLLM prefix
    ("anthropic", "claude-sonnet-4-20250514"): "anthropic/claude-sonnet-4-20250514",
    ("anthropic", "claude-3-5-sonnet-20241022"): "anthropic/claude-3-5-sonnet-20241022",
    # OpenAI
    ("openai", "gpt-4o"): "openai/gpt-4o",
    ("openai", "gpt-4o-mini"): "openai/gpt-4o-mini",
    # Vertex / Gemini — ADK native
    ("vertex-ai", "gemini-2.0-flash"): "gemini-2.0-flash",
    ("vertex-ai", "gemini-2.5-flash"): "gemini-2.5-flash-preview-05-20",
    ("vertex-ai", "gemini-2.5-pro"): "gemini-2.5-pro-preview-05-06",
    ("vertex-ai", "gemini-3.5-flash"): "gemini-3.5-flash",
    ("gemini", "gemini-3.5-flash"): "gemini-3.5-flash",
}


def resolve_model(llm_adapter: dict[str, Any]) -> str:
    """Map an LLM adapter config to an ADK-compatible model string."""
    provider = llm_adapter.get("provider", "")
    model = llm_adapter.get("model", "")

    # Exact match
    key = (provider, model)
    if key in _MODEL_MAP:
        return _MODEL_MAP[key]

    # Fall through: if provider looks like a LiteLLM prefix, combine
    if provider and model:
        if provider in ("vertex-ai", "gemini"):
            return model  # Gemini models are used directly by ADK
        return f"{provider}/{model}"

    raise ValueError(
        f"Cannot resolve model from adapter config: provider={provider!r}, model={model!r}. "
        "Check adapters/llm.yaml."
    )


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
) -> Any:
    """Create an ADK LlmAgent wired from the Zil project manifest.

    Reads ``manifest.yaml``, identity files, and adapter config from the
    project directory (auto-detected from cwd if not given), then returns
    a fully-configured ``google.adk.agents.LlmAgent``.

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

    Returns:
        A ``google.adk.agents.LlmAgent`` instance.
    """
    try:
        from google.adk.agents import LlmAgent
    except ImportError:
        raise ImportError(
            "google-adk is required to create agents. "
            "Install it with: pip install 'zil-ai[adk]'"
        ) from None

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

    resolved_model = model or resolve_model(ctx.llm_adapter)
    resolved_instruction = instruction or compose_instruction(
        persona=ctx.identity.persona,
        instructions=ctx.identity.instructions,
        guardrails=ctx.identity.guardrails,
    )

    resolved_name = name or ctx.name.replace("-", "_")

    # Auto-wire MCP toolsets from spec.tools.mcp_servers
    mcp_toolsets: list[Any] = []
    if enable_mcp and ctx.tools_config:
        mcp_servers = ctx.tools_config.get("mcp_servers", [])
        if mcp_servers:
            from zil.sdk.mcp import create_mcp_toolsets_adk

            mcp_toolsets = create_mcp_toolsets_adk(mcp_servers, project_dir=ctx.project_dir)
            logger.info(
                "MCP auto-wiring: %d server(s) connected",
                len(mcp_toolsets),
            )

    all_tools: list[Any] = list(tools or []) + mcp_toolsets

    # Build sub-agents from spec.agents and attach as AgentTool instances
    if ctx.agents:
        agent_tools = _build_sub_agents(ctx, enable_mcp=enable_mcp)
        all_tools = all_tools + agent_tools
        logger.info(
            "Multi-agent wiring: %d sub-agent(s) attached",
            len(agent_tools),
        )

    # Build generate_content_config with thinking if configured
    generate_content_config = _build_generate_content_config(
        thinking_budget=thinking_budget or ctx.thinking_budget,
    )

    agent = LlmAgent(
        model=resolved_model,
        name=resolved_name,
        description=description or ctx.description,
        instruction=resolved_instruction,
        tools=all_tools,
        generate_content_config=generate_content_config,
    )

    # Attach the guardrail callback to the agent for direct access
    # Users can call agent._zil_guardrails.check_input(text) etc.
    agent._zil_guardrails = guardrail_callback  # type: ignore[attr-defined]

    # Attach the cost callback to the agent
    # Users can call agent._zil_cost.record(input_tokens, output_tokens) etc.
    agent._zil_cost = cost_callback  # type: ignore[attr-defined]

    return agent


def _build_generate_content_config(
    thinking_budget: int | None = None,
) -> Any:
    """Build a GenerateContentConfig with optional thinking support.

    Returns a ``types.GenerateContentConfig`` suitable for passing to
    ``LlmAgent(generate_content_config=...)``.  When *thinking_budget*
    is set, the config includes a ``ThinkingConfig`` that enables
    Gemini's chain-of-thought reasoning with the given token budget.
    """
    if thinking_budget is None or thinking_budget <= 0:
        return None

    try:
        from google.genai import types
    except ImportError:
        logger.warning(
            "google-genai not installed — thinking_budget=%d ignored",
            thinking_budget,
        )
        return None

    logger.info(
        "Thinking mode enabled — budget: %d tokens",
        thinking_budget,
    )
    return types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(
            thinking_budget=thinking_budget,
        ),
    )


def _load_skills(skills_dir: Any) -> dict[str, Any]:
    """Load all skills from a directory into a name→Skill index.

    Scans *skills_dir* for subdirectories that contain a ``SKILL.md`` file,
    loads each with ``load_skill_from_dir``, and returns a ``{name: Skill}``
    mapping.  Missing or unreadable skills are skipped with a warning.
    Returns an empty dict if *skills_dir* is ``None`` or does not exist.
    """
    if skills_dir is None:
        return {}
    from pathlib import Path as _Path
    skills_path = _Path(skills_dir)
    if not skills_path.is_dir():
        logger.warning("spec.skills directory %r not found — skills unavailable", str(skills_path))
        return {}

    try:
        from google.adk.skills import load_skill_from_dir
    except ImportError:
        logger.warning(
            "google-adk skills module not available — SkillToolset disabled. "
            "Install google-adk>=1.0 to enable skills support."
        )
        return {}

    index: dict[str, Any] = {}
    for entry in sorted(skills_path.iterdir()):
        if not entry.is_dir():
            continue
        if not (entry / "SKILL.md").is_file() and not (entry / "skill.md").is_file():
            continue
        try:
            skill = load_skill_from_dir(entry)
            index[skill.name] = skill
            logger.debug("Loaded skill %r from %s", skill.name, entry)
        except Exception:
            logger.warning("Could not load skill from %s — skipped", entry, exc_info=True)

    logger.info("Skills index: %d skill(s) loaded from %s", len(index), skills_path)
    return index


def _build_sub_agents(ctx: Any, *, enable_mcp: bool = True) -> list[Any]:
    """Build sub-agent LlmAgents wrapped as AgentTool from spec.agents.

    Each sub-agent gets its own identity, model, (optionally) a filtered
    subset of MCP toolsets from the root spec.tools.mcp_servers, and
    (optionally) a SkillToolset filtered to its spec.agents[].tools.skills
    allowlist from ctx.skills_dir.
    """
    try:
        from google.adk.agents import LlmAgent
        from google.adk.tools.agent_tool import AgentTool
    except ImportError:
        raise ImportError(
            "google-adk is required for multi-agent support. "
            "Install it with: pip install 'zil-ai[adk]'"
        ) from None

    # Build a name → server config index for MCP filtering
    all_mcp_servers: list[Any] = []
    if enable_mcp and ctx.tools_config:
        all_mcp_servers = ctx.tools_config.get("mcp_servers", [])
    mcp_by_name: dict[str, Any] = {s["name"]: s for s in all_mcp_servers}

    # Load the full skills index once (empty dict if spec.skills not declared)
    skills_index: dict[str, Any] = _load_skills(getattr(ctx, "skills_dir", None))

    agent_tools: list[Any] = []
    for spec in ctx.agents:
        # Resolve model: model_env_var override → adapter model
        sub_model = resolve_model(spec.llm_adapter)
        if spec.model_env_var:
            import os
            env_override = os.environ.get(spec.model_env_var)
            if env_override:
                sub_model = env_override

        # Compose instruction from sub-agent identity
        from zil.sdk.identity import compose_instruction
        sub_instruction = compose_instruction(
            persona=spec.identity.persona,
            instructions=spec.identity.instructions,
            guardrails=spec.identity.guardrails,
        )

        # Filter MCP toolsets to those listed in spec.agents[].tools.mcp_servers
        sub_mcp_toolsets: list[Any] = []
        if enable_mcp and spec.mcp_server_names:
            from zil.sdk.mcp import create_mcp_toolsets_adk

            filtered_servers = [
                mcp_by_name[n] for n in spec.mcp_server_names if n in mcp_by_name
            ]
            if filtered_servers:
                sub_mcp_toolsets = create_mcp_toolsets_adk(
                    filtered_servers, project_dir=ctx.project_dir
                )

        # Build SkillToolset filtered to spec.agents[].tools.skills allowlist
        skill_toolset: list[Any] = []
        skill_names: list[str] = getattr(spec, "skill_names", []) or []
        if skill_names and skills_index:
            try:
                from google.adk.tools.skill_toolset import SkillToolset

                filtered_skills = [skills_index[n] for n in skill_names if n in skills_index]
                missing = [n for n in skill_names if n not in skills_index]
                if missing:
                    logger.warning(
                        "Sub-agent %r: skill(s) not found in spec.skills dir: %s",
                        spec.name,
                        missing,
                    )
                if filtered_skills:
                    skill_toolset = [SkillToolset(skills=filtered_skills)]
                    logger.info(
                        "Sub-agent %r: SkillToolset with %d skill(s): %s",
                        spec.name,
                        len(filtered_skills),
                        [s.name for s in filtered_skills],
                    )
            except ImportError:
                logger.warning(
                    "SkillToolset not available in installed google-adk version — "
                    "sub-agent %r skills skipped",
                    spec.name,
                )

        # Propagate thinking config from root to sub-agents
        sub_gen_config = _build_generate_content_config(
            thinking_budget=ctx.thinking_budget,
        )

        sub_agent = LlmAgent(
            model=sub_model,
            name=spec.name,
            description=spec.description,
            instruction=sub_instruction,
            tools=sub_mcp_toolsets + skill_toolset,
            generate_content_config=sub_gen_config,
        )

        agent_tools.append(AgentTool(agent=sub_agent))
        logger.info(
            "Sub-agent %r built (model=%s, mcp=%d server(s), skills=%d)",
            spec.name,
            sub_model,
            len(sub_mcp_toolsets),
            len(skill_toolset),
        )

    return agent_tools
