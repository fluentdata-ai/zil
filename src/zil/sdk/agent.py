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
    enable_telemetry: bool = True,
    enable_guardrails: bool = True,
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
        enable_telemetry: Wire up OTel tracing from observability config
            (default ``True``).  Set to ``False`` in tests or when
            managing OTel providers yourself.
        enable_guardrails: Load and enforce guardrail rules from
            ``identity/guardrails.yaml`` at runtime (default ``True``).

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

    resolved_model = model or resolve_model(ctx.llm_adapter)
    resolved_instruction = instruction or compose_instruction(
        persona=ctx.identity.persona,
        instructions=ctx.identity.instructions,
        guardrails=ctx.identity.guardrails,
    )

    resolved_name = name or ctx.name.replace("-", "_")

    agent = LlmAgent(
        model=resolved_model,
        name=resolved_name,
        description=description or ctx.description,
        instruction=resolved_instruction,
        tools=tools or [],
    )

    # Attach the guardrail callback to the agent for direct access
    # Users can call agent._zil_guardrails.check_input(text) etc.
    agent._zil_guardrails = guardrail_callback  # type: ignore[attr-defined]

    return agent
