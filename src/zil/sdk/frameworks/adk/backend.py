"""ADK framework backend — Google Agent Development Kit integration.

This module encapsulates all ADK-specific logic: model mapping, agent
construction, MCP wiring, sub-agent building, and local execution.
It is the ONLY module in the Zil SDK that imports ``google.adk``.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from zil.sdk.frameworks.base import AgentSpec

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


def _build_sub_agents(
    spec: AgentSpec,
    *,
    enable_mcp: bool = True,
) -> list[Any]:
    """Build sub-agent LlmAgents wrapped as AgentTool from spec.agents.

    Each sub-agent gets its own identity, model, (optionally) a filtered
    subset of MCP toolsets from the root spec.tools.mcp_servers, and
    (optionally) a SkillToolset filtered to its spec.agents[].tools.skills
    allowlist from ctx.skills_dir.
    """
    from google.adk.agents import LlmAgent
    from google.adk.tools.agent_tool import AgentTool

    ctx = spec.context
    if ctx is None:
        return []

    # Build a name → server config index for MCP filtering
    mcp_by_name: dict[str, Any] = {
        s["name"]: s for s in spec.mcp_server_configs
    }

    # Load the full skills index once (empty dict if spec.skills not declared)
    skills_index: dict[str, Any] = _load_skills(getattr(ctx, "skills_dir", None))

    agent_tools: list[Any] = []
    for sub_spec in ctx.agents:
        # Resolve model: model_env_var override → adapter model
        sub_model = resolve_model(sub_spec.llm_adapter)
        if sub_spec.model_env_var:
            import os
            env_override = os.environ.get(sub_spec.model_env_var)
            if env_override:
                sub_model = env_override

        # Compose instruction from sub-agent identity
        from zil.sdk.identity import compose_instruction
        sub_instruction = compose_instruction(
            persona=sub_spec.identity.persona,
            instructions=sub_spec.identity.instructions,
            guardrails=sub_spec.identity.guardrails,
        )

        # Filter MCP toolsets to those listed in spec.agents[].tools.mcp_servers
        sub_mcp_toolsets: list[Any] = []
        if enable_mcp and sub_spec.mcp_server_names:
            from zil.sdk.mcp import create_mcp_toolsets_adk

            filtered_servers = [
                mcp_by_name[n] for n in sub_spec.mcp_server_names if n in mcp_by_name
            ]
            if filtered_servers:
                sub_mcp_toolsets = create_mcp_toolsets_adk(
                    filtered_servers, project_dir=ctx.project_dir
                )

        # Build SkillToolset filtered to spec.agents[].tools.skills allowlist
        skill_toolset: list[Any] = []
        skill_names: list[str] = getattr(sub_spec, "skill_names", []) or []
        if skill_names and skills_index:
            try:
                from google.adk.tools.skill_toolset import SkillToolset

                filtered_skills = [skills_index[n] for n in skill_names if n in skills_index]
                missing = [n for n in skill_names if n not in skills_index]
                if missing:
                    logger.warning(
                        "Sub-agent %r: skill(s) not found in spec.skills dir: %s",
                        sub_spec.name,
                        missing,
                    )
                if filtered_skills:
                    skill_toolset = [SkillToolset(skills=filtered_skills)]
                    logger.info(
                        "Sub-agent %r: SkillToolset with %d skill(s): %s",
                        sub_spec.name,
                        len(filtered_skills),
                        [s.name for s in filtered_skills],
                    )
            except ImportError:
                logger.warning(
                    "SkillToolset not available in installed google-adk version — "
                    "sub-agent %r skills skipped",
                    sub_spec.name,
                )

        # Propagate thinking config from root to sub-agents
        sub_gen_config = _build_generate_content_config(
            thinking_budget=spec.thinking_budget,
        )

        sub_agent = LlmAgent(
            model=sub_model,
            name=sub_spec.name,
            description=sub_spec.description,
            instruction=sub_instruction,
            tools=sub_mcp_toolsets + skill_toolset,
            generate_content_config=sub_gen_config,
        )

        agent_tools.append(AgentTool(agent=sub_agent))
        logger.info(
            "Sub-agent %r built (model=%s, mcp=%d server(s), skills=%d)",
            sub_spec.name,
            sub_model,
            len(sub_mcp_toolsets),
            len(skill_toolset),
        )

    return agent_tools


# ---------------------------------------------------------------------------
# WiredAgent wrapper
# ---------------------------------------------------------------------------


@dataclass
class AdkWiredAgent:
    """WiredAgent wrapping a google.adk.agents.LlmAgent."""

    _agent: Any

    @property
    def framework(self) -> str:
        return "adk"

    @property
    def inner(self) -> Any:
        return self._agent


# ---------------------------------------------------------------------------
# AdkBackend
# ---------------------------------------------------------------------------


class AdkBackend:
    """Framework backend for Google's Agent Development Kit (ADK)."""

    @property
    def name(self) -> str:
        return "adk"

    def wire(self, spec: AgentSpec) -> AdkWiredAgent:
        """Construct an ADK LlmAgent from the neutral AgentSpec."""
        try:
            from google.adk.agents import LlmAgent
        except ImportError:
            raise ImportError(
                "google-adk is required to create agents. "
                "Install it with: pip install 'zil-ai[adk]'"
            ) from None

        from zil.sdk.mcp import create_mcp_toolsets_adk

        # Wire MCP toolsets from raw configs
        mcp_toolsets: list[Any] = []
        if spec.mcp_server_configs:
            project_dir = spec.context.project_dir if spec.context else None
            mcp_toolsets = create_mcp_toolsets_adk(
                spec.mcp_server_configs, project_dir=project_dir
            )
            logger.info(
                "MCP auto-wiring: %d server(s) connected",
                len(mcp_toolsets),
            )

        all_tools: list[Any] = list(spec.tool_callables) + mcp_toolsets

        # Build sub-agents from spec.sub_agent_specs and attach as AgentTool
        enable_mcp = bool(spec.mcp_server_configs) or bool(spec.tool_callables)
        if spec.context and spec.context.agents:
            agent_tools = _build_sub_agents(spec, enable_mcp=True)
            all_tools = all_tools + agent_tools
            logger.info(
                "Multi-agent wiring: %d sub-agent(s) attached",
                len(agent_tools),
            )

        # Build generate_content_config with thinking if configured
        generate_content_config = _build_generate_content_config(
            thinking_budget=spec.thinking_budget,
        )

        agent = LlmAgent(
            model=spec.model,
            name=spec.name,
            description=spec.description,
            instruction=spec.instructions,
            tools=all_tools,
            generate_content_config=generate_content_config,
        )

        # Attach cross-cutting callbacks
        agent._zil_guardrails = spec.guardrail_callback  # type: ignore[attr-defined]
        agent._zil_cost = spec.cost_callback  # type: ignore[attr-defined]

        return AdkWiredAgent(_agent=agent)

    def run_local(self, agent: AdkWiredAgent | None, **kwargs: Any) -> None:
        """Run the agent locally via ADK CLI.

        Supported kwargs:
            mode: "interactive" (default) or "web"
            project_dir: Path to project root
            module_name: Agent module directory name
            port: Port for web mode (default 8000)
            trace_mode: Enable OTLP trace export
            trace_console: Print spans to stderr
        """
        import asyncio
        import shutil
        import subprocess
        import sys

        from rich.console import Console

        console = Console()
        mode = kwargs.get("mode", "interactive")
        project_dir: Path = kwargs["project_dir"]
        module_name: str = kwargs["module_name"]
        port: int = kwargs.get("port", 8000)
        trace_console: bool = kwargs.get("trace_console", False)

        if mode == "web":
            if not shutil.which("adk"):
                console.print(
                    "[red]Error:[/red] adk CLI not found. "
                    "Install it with: [bold]pip install 'zil-ai\\[adk]'[/bold]"
                )
                raise SystemExit(1)

            console.print(f"Starting ADK web UI on http://localhost:{port}")
            sys.exit(
                subprocess.call(
                    ["adk", "web", "--port", str(port)],
                    cwd=str(project_dir),
                )
            )
        elif trace_console:
            # In-process mode for console tracing
            self._run_in_process(project_dir, module_name)
        else:
            # Default: subprocess to adk run
            if not shutil.which("adk"):
                console.print(
                    "[red]Error:[/red] adk CLI not found. "
                    "Install it with: [bold]pip install 'zil-ai\\[adk]'[/bold]"
                )
                raise SystemExit(1)

            sys.exit(
                subprocess.call(
                    ["adk", "run", module_name],
                    cwd=str(project_dir),
                )
            )

    @staticmethod
    def _run_in_process(project_dir: Path, module_name: str) -> None:
        """Run the agent in-process using ADK's runner."""
        import asyncio

        from rich.console import Console

        console = Console()

        try:
            from google.adk.cli.cli import run_cli
        except ImportError:
            console.print(
                "[red]Error:[/red] google-adk is required. "
                "Install it with: [bold]pip install 'zil-ai\\[adk]'[/bold]"
            )
            raise SystemExit(1)

        asyncio.run(
            run_cli(
                agent_parent_dir=str(project_dir),
                agent_folder_name=module_name,
                input_file=None,
                saved_session_file=None,
                save_session=False,
                session_id=None,
                session_service_uri=None,
                artifact_service_uri=None,
                memory_service_uri=None,
                use_local_storage=True,
            )
        )

    def deploy_descriptor(
        self, agent: AdkWiredAgent, spec: AgentSpec
    ) -> dict[str, Any]:
        """Return ADK-specific deployment metadata for Cloud Run."""
        return {
            "framework": "adk",
            "needs_adk_cli": True,
            "deploy_fn": "cloud_run",
            "image_base": "python:3.11-slim",
            "entrypoint": "adk",
        }

    def validate(
        self, project_dir: Path, manifest: dict[str, Any]
    ) -> list[Any]:
        """ADK has no extra validation beyond what schema/loader.py does."""
        return []

    def scaffold_config(self) -> dict[str, Any] | None:
        """Return ADK init template configuration."""
        return {
            "framework": "adk",
            "module_template": "adk",
            "dockerfile_base": "python:3.11-slim",
            "agent_entry": "agent.py",
        }

    # Cache of (session_service, runner, user_id, adk_session_id) per
    # logical session so conversation history is preserved across calls.
    _session_cache: dict[str, tuple[Any, Any, str, str]] = {}

    async def invoke(
        self,
        agent: AdkWiredAgent,
        message: str,
        *,
        session_id: str | None = None,
        workspace: str | Path | None = None,
    ) -> AsyncIterator:
        """Invoke the ADK agent and yield SessionEvents.

        Uses ADK's Runner + InMemorySessionService to execute the agent
        and maps ADK events to framework-neutral SessionEvent instances.
        Persists the session service across calls so multi-turn works.
        """
        from zil.sdk.session import SessionEvent

        try:
            from google.adk.runners import Runner
            from google.adk.sessions import InMemorySessionService
            from google.genai import types
        except ImportError:
            yield SessionEvent(
                type="error",
                text="google-adk is required. Install with: pip install 'zil-ai[adk]'",
            )
            return

        logical_sid = session_id or uuid.uuid4().hex

        if logical_sid in self._session_cache:
            session_service, runner, user_id, adk_sid = self._session_cache[logical_sid]
        else:
            user_id = f"zil-session-{logical_sid}"
            app_name = getattr(agent._agent, 'name', 'zil-agent')

            session_service = InMemorySessionService()
            runner = Runner(
                agent=agent._agent,
                app_name=app_name,
                session_service=session_service,
            )

            # ADK requires the session to exist before run_async
            session = await session_service.create_session(
                app_name=app_name,
                user_id=user_id,
            )
            adk_sid = session.id
            self._session_cache[logical_sid] = (session_service, runner, user_id, adk_sid)

        content = types.Content(
            role="user",
            parts=[types.Part.from_text(text=message)],
        )

        text_parts: list[str] = []
        try:
            async for event in runner.run_async(
                user_id=user_id,
                session_id=adk_sid,
                new_message=content,
            ):
                author = getattr(event, 'author', '') or ''

                # Emit tool_call events from function_call parts
                for fn_call in event.get_function_calls():
                    tool_label = fn_call.name or 'unknown_tool'
                    yield SessionEvent(
                        type="tool_call",
                        tool_name=tool_label,
                        args=dict(fn_call.args) if fn_call.args else None,
                    )

                # Emit tool_result events from function_response parts
                for fn_resp in event.get_function_responses():
                    resp_name = fn_resp.name or ''
                    resp_data = getattr(fn_resp, 'response', None)
                    result_text = json.dumps(resp_data) if resp_data else None
                    yield SessionEvent(
                        type="tool_result",
                        tool_name=resp_name,
                        result=result_text,
                    )

                # Emit text events (from any agent in the hierarchy)
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        text = getattr(part, 'text', None)
                        if text and not event.get_function_calls() and not event.get_function_responses():
                            text_parts.append(text)
                            yield SessionEvent(type="text", text=text)

        except Exception as exc:
            yield SessionEvent(type="error", text=str(exc))

        yield SessionEvent(
            type="done",
            metadata={"session_id": logical_sid, "app_name": getattr(agent._agent, 'name', 'zil-agent')},
        )
