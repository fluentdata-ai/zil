"""ADK framework backend — Google Agent Development Kit integration.

This module encapsulates all ADK-specific logic: model mapping, agent
construction, MCP wiring, sub-agent building, and local execution.
It is the ONLY module in the Zil SDK that imports ``google.adk``.
"""

from __future__ import annotations

import json
import logging
import re
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


def _to_node_name(name: str) -> str:
    """Normalize a fleet/peer name into a valid Python identifier for ADK.

    ADK validates agent (node) names as Python identifiers, so hyphens and
    other non-identifier characters (common in fleet names like
    'weather-agent') are replaced with underscores. A leading digit is
    prefixed with an underscore.
    """
    node = re.sub(r"\W", "_", name)
    if node and node[0].isdigit():
        node = f"_{node}"
    return node or "_peer"


def _build_remote_agents(spec: AgentSpec) -> list[Any]:
    """Wrap declared A2A collaborators as RemoteA2aAgent AgentTools (RFC-005 §7.2).

    Resolves each ``spec.context.collaborators`` peer to its Agent Card URL via
    the static resolver and exposes it to the LLM as an ``AgentTool`` over the
    A2A wire. The per-peer ``skills`` allowlist is surfaced in the tool
    description so the model delegates only matching requests. Peers whose URL
    cannot be resolved (e.g. unset env var) are skipped with a warning.
    """
    ctx = spec.context
    collaborators = getattr(ctx, "collaborators", None) if ctx else None
    if not collaborators:
        return []

    from google.adk.agents.remote_a2a_agent import RemoteA2aAgent
    from google.adk.tools.agent_tool import AgentTool

    from zil.collaboration.auth import NoneAuthenticator, build_authenticator
    from zil.collaboration.discovery import build_resolver
    from zil.collaboration.http import build_peer_http_client

    try:
        from a2a.utils.constants import AGENT_CARD_WELL_KNOWN_PATH
    except ImportError:
        AGENT_CARD_WELL_KNOWN_PATH = "/.well-known/agent-card.json"  # noqa: N806

    caller = spec.name or ""
    # build_resolver selects the discovery seam from the environment: an HTTP
    # registry of record (ZIL_FLEET_REGISTRY_URL) in production, else the
    # in-process RegistryResolver. Both handle plain ``url:`` peers and
    # ``ref: zil://fleet/<name>`` identically (RFC-005 §9).
    resolver = build_resolver()
    agent_tools: list[Any] = []
    for peer in collaborators:
        try:
            base_url = resolver.resolve_url(peer)
        except ValueError as exc:
            logger.warning("Collaborator %r skipped: %s", peer.name, exc)
            continue

        card_url = base_url.rstrip("/") + AGENT_CARD_WELL_KNOWN_PATH

        allowed = peer.skills
        if allowed:
            description = (
                f"Remote agent '{peer.name}'. Allowed skills: "
                f"{', '.join(allowed)}. Delegate matching requests by sending "
                "a natural-language message."
            )
        else:
            description = (
                f"Remote agent '{peer.name}'. Delegate matching requests by "
                "sending a natural-language message."
            )

        # Every outbound call asserts caller identity (RFC-005 §10.3) and, for
        # any mode except 'none', attaches inter-agent auth (§10.2).
        authenticator = build_authenticator(peer, base_url)
        auth_for_client = (
            None if isinstance(authenticator, NoneAuthenticator) else authenticator
        )
        httpx_client = build_peer_http_client(
            caller=caller, authenticator=auth_for_client
        )

        # ADK requires the agent (node) name to be a valid Python identifier,
        # so hyphenated fleet names like 'weather-agent' must be normalized.
        # peer.name is preserved everywhere else (identity, auth, description).
        remote = RemoteA2aAgent(
            name=_to_node_name(peer.name),
            agent_card=card_url,
            description=description,
            httpx_client=httpx_client,
        )
        agent_tools.append(AgentTool(agent=remote))
        logger.info(
            "Collaborator %r wired as RemoteA2aAgent (card=%s, skills=%s, auth=%s)",
            peer.name,
            card_url,
            allowed or "all",
            peer.auth,
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

        # Memory recall tool (RFC-003) — lets the agent fetch long-term memory.
        if spec.memory_provider is not None:
            from zil.sdk.frameworks.adk.memory_wiring import build_recall_tool

            recall_tool = build_recall_tool()
            if recall_tool is not None:
                all_tools.append(recall_tool)
                logger.info("Memory recall tool attached (provider=%s)",
                            getattr(spec.memory_provider, "name", "?"))

        # Build sub-agents from spec.sub_agent_specs and attach as AgentTool
        if spec.context and spec.context.agents:
            agent_tools = _build_sub_agents(spec, enable_mcp=True)
            all_tools = all_tools + agent_tools
            logger.info(
                "Multi-agent wiring: %d sub-agent(s) attached",
                len(agent_tools),
            )

        # Wire declared A2A collaborators as RemoteA2aAgent tools (RFC-005).
        if spec.context and getattr(spec.context, "collaborators", None):
            remote_tools = _build_remote_agents(spec)
            all_tools = all_tools + remote_tools
            logger.info(
                "A2A collaboration: %d remote agent(s) attached",
                len(remote_tools),
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

        # Stash memory provider/config for invoke() to wire a Runner.
        if spec.memory_provider is not None:
            from zil.sdk.frameworks.adk.memory_wiring import attach_memory

            attach_memory(agent, spec)

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

            # Wire a long-term memory service if configured (RFC-003).
            memory_service = None
            mem_provider = getattr(agent._agent, '_zil_memory_provider', None)
            if mem_provider is not None:
                from zil.sdk.frameworks.adk.memory_wiring import make_memory_service

                mem_config = getattr(agent._agent, '_zil_memory_config', None)
                memory_service = make_memory_service(mem_provider, mem_config)

            runner_kwargs: dict[str, Any] = {
                "agent": agent._agent,
                "app_name": app_name,
                "session_service": session_service,
            }
            if memory_service is not None:
                runner_kwargs["memory_service"] = memory_service
            runner = Runner(**runner_kwargs)

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
        total_input_tokens = 0
        total_output_tokens = 0
        total_tokens = 0

        # Cost callback (if cost tracking is enabled)
        cost_cb = getattr(agent._agent, '_zil_cost', None)

        try:
            async for event in runner.run_async(
                user_id=user_id,
                session_id=adk_sid,
                new_message=content,
            ):
                # Accumulate token usage from ADK usage_metadata
                usage_meta = getattr(event, 'usage_metadata', None)
                if usage_meta:
                    inp = getattr(usage_meta, 'prompt_token_count', 0) or 0
                    out = getattr(usage_meta, 'candidates_token_count', 0) or 0
                    tot = getattr(usage_meta, 'total_token_count', 0) or 0
                    total_input_tokens += inp
                    total_output_tokens += out
                    total_tokens += tot or (inp + out)

                    # Feed the cost tracker if present
                    if cost_cb and hasattr(cost_cb, 'record'):
                        cost_cb.record(input_tokens=inp, output_tokens=out)

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
                        is_plain_text = (
                            text
                            and not event.get_function_calls()
                            and not event.get_function_responses()
                        )
                        if is_plain_text:
                            text_parts.append(text)
                            yield SessionEvent(type="text", text=text)

        except Exception as exc:
            yield SessionEvent(type="error", text=str(exc))

        # Persist the completed turn into long-term memory (RFC-003).
        memory_service = getattr(runner, 'memory_service', None)
        if memory_service is not None and hasattr(
            memory_service, 'add_session_to_memory'
        ):
            try:
                completed = await session_service.get_session(
                    app_name=getattr(agent._agent, 'name', 'zil-agent'),
                    user_id=user_id,
                    session_id=adk_sid,
                )
                if completed is not None:
                    await memory_service.add_session_to_memory(completed)
            except Exception as exc:
                logger.warning("memory add_session_to_memory failed: %s", exc)

        done_metadata: dict[str, Any] = {
            "session_id": logical_sid,
            "app_name": getattr(agent._agent, 'name', 'zil-agent'),
        }
        if total_tokens > 0 or total_input_tokens > 0 or total_output_tokens > 0:
            done_metadata["token_usage"] = {
                "input": total_input_tokens,
                "output": total_output_tokens,
                "total": total_tokens,
            }

        yield SessionEvent(type="done", metadata=done_metadata)
