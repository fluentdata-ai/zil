"""OpenHands framework backend — autonomous coding agent integration.

This module encapsulates all OpenHands-specific logic: LLM configuration,
agent construction, MCP wiring, local execution, and deployment descriptor.
It is the ONLY module in the Zil SDK that imports ``openhands.sdk``.
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from zil.sdk.frameworks.base import AgentSpec

logger = logging.getLogger(__name__)

# Live Conversation objects keyed by session_id for multi-turn support.
# Each entry is (conversation, queue_holder) where queue_holder is a
# single-element list so the callback always writes to the current queue.
_conversations: dict[str, tuple[Any, list]] = {}

# ---------------------------------------------------------------------------
# Model resolution
# ---------------------------------------------------------------------------

# OpenHands uses LiteLLM model strings directly.  For most providers the
# Zil adapter config already produces the right format (``provider/model``).
# Gemini/Vertex need a small adjustment — LiteLLM expects ``gemini/...``
# rather than the bare model name ADK uses.
_GEMINI_MODEL_MAP: dict[str, str] = {
    "gemini-2.0-flash": "gemini/gemini-2.0-flash",
    "gemini-2.5-flash": "gemini/gemini-2.5-flash-preview-05-20",
    "gemini-2.5-pro": "gemini/gemini-2.5-pro-preview-05-06",
    "gemini-3.5-flash": "gemini/gemini-3.5-flash",
}


def resolve_model_openhands(llm_adapter: dict[str, Any]) -> str:
    """Map a Zil LLM adapter config to an OpenHands/LiteLLM model string."""
    provider = llm_adapter.get("provider", "")
    model = llm_adapter.get("model", "")

    # Gemini / Vertex — needs ``gemini/`` prefix for LiteLLM
    if provider in ("vertex-ai", "gemini"):
        if model in _GEMINI_MODEL_MAP:
            return _GEMINI_MODEL_MAP[model]
        return f"gemini/{model}"

    # All other providers: LiteLLM uses ``provider/model`` directly
    if provider and model:
        return f"{provider}/{model}"

    raise ValueError(
        f"Cannot resolve model from adapter config: provider={provider!r}, model={model!r}. "
        "Check adapters/llm.yaml."
    )


# ---------------------------------------------------------------------------
# WiredAgent wrapper
# ---------------------------------------------------------------------------


@dataclass
class OpenHandsWiredAgent:
    """Wraps a fully-configured OpenHands ``Agent`` instance."""

    _agent: Any  # openhands.sdk.Agent (typed as Any to avoid import at module level)

    @property
    def framework(self) -> str:
        return "openhands"

    @property
    def inner(self) -> Any:
        return self._agent


# ---------------------------------------------------------------------------
# Backend implementation
# ---------------------------------------------------------------------------


class OpenHandsBackend:
    """Framework backend for OpenHands autonomous coding agents."""

    @property
    def name(self) -> str:
        return "openhands"

    # ---- wire --------------------------------------------------------

    def wire(self, spec: AgentSpec) -> OpenHandsWiredAgent:
        """Construct an OpenHands ``Agent`` from the neutral ``AgentSpec``."""
        try:
            from openhands.sdk import LLM, Agent, Tool
        except ImportError:
            raise ImportError(
                "openhands-sdk is required for the 'openhands' framework. "
                "Install it with:  pip install 'zil-ai[openhands]'"
            ) from None

        # --- LLM ---
        llm = LLM(
            model=spec.model,
            api_key=os.environ.get("LLM_API_KEY"),
            base_url=os.environ.get("LLM_BASE_URL"),
        )

        # --- MCP config ---
        mcp_config = self._build_mcp_config(spec.mcp_server_configs)

        # --- Tools ---
        tools: list[Any] = []
        # Include OpenHands built-in tools by default
        try:
            from openhands.tools.file_editor import FileEditorTool
            from openhands.tools.terminal import TerminalTool

            tools.append(Tool(name=TerminalTool.name))
            tools.append(Tool(name=FileEditorTool.name))
        except ImportError:
            logger.warning(
                "openhands-tools not installed — built-in tools unavailable. "
                "Install with:  pip install openhands-tools"
            )

        # --- System prompt (from identity/) ---
        system_prompt = spec.instructions if spec.instructions else None

        # --- Skills (from spec.skills directory) ---
        agent_context = None
        skills_dir = getattr(spec.context, "skills_dir", None) if spec.context else None
        if skills_dir and Path(skills_dir).is_dir():
            oh_skills = self._load_skills_from_dir(Path(skills_dir))
            if oh_skills:
                try:
                    from openhands.sdk.context import AgentContext
                    agent_context = AgentContext(skills=oh_skills)
                    logger.info("Loaded %d skill(s) into AgentContext", len(oh_skills))
                except ImportError:
                    logger.warning("Could not import AgentContext — skills unavailable")

        # --- Sub-agents warning ---
        if spec.sub_agent_specs:
            logger.warning(
                "OpenHands does not support sub-agents. "
                "spec.agents entries will be ignored for framework 'openhands'."
            )

        # --- Build the Agent ---
        agent_kwargs: dict[str, Any] = {
            "llm": llm,
            "tools": tools,
            "mcp_config": mcp_config,
            "system_prompt": system_prompt,
        }
        if agent_context is not None:
            agent_kwargs["agent_context"] = agent_context

        agent = Agent(**agent_kwargs)

        logger.info(
            "OpenHandsBackend.wire() — agent configured "
            "(model=%s, tools=%d, mcp_servers=%d, skills=%d)",
            spec.model,
            len(tools),
            len(spec.mcp_server_configs),
            len(oh_skills) if skills_dir and Path(skills_dir).is_dir() else 0,
        )

        return OpenHandsWiredAgent(_agent=agent)

    # ---- run_local ---------------------------------------------------

    def run_local(self, agent: Any, **kwargs: Any) -> None:
        """Run the agent locally via the OpenHands Conversation API.

        Supported kwargs:
            mode: "interactive" | "headless" (default "interactive")
            project_dir: Path to the project root (workspace)
            task: Task description for headless mode
            module_name: Agent module directory name
        """
        try:
            from openhands.sdk import Conversation
        except ImportError:
            raise ImportError(
                "openhands-sdk is required to run OpenHands agents locally. "
                "Install it with:  pip install 'zil-ai[openhands]'"
            ) from None

        from rich.console import Console

        console = Console()

        mode = kwargs.get("mode", "interactive")
        project_dir = kwargs.get("project_dir", Path.cwd())
        task = kwargs.get("task")

        # If called from CLI (agent=None), we need to wire the agent first
        if agent is None:
            agent = self._wire_from_project(project_dir, kwargs.get("module_name"))

        oh_agent = agent._agent if hasattr(agent, "_agent") else agent

        workspace = str(project_dir)

        if mode == "interactive":
            # Interactive loop — prompt for tasks
            console.print(
                "[bold]OpenHands interactive mode[/bold] "
                f"(workspace: {project_dir})"
            )
            console.print("Type a task, or 'quit' to exit.\n")

            while True:
                try:
                    task_input = console.input("[bold cyan]task>[/bold cyan] ").strip()
                except (EOFError, KeyboardInterrupt):
                    break

                if task_input.lower() in ("quit", "exit", "q"):
                    break
                if not task_input:
                    continue

                conversation = Conversation(agent=oh_agent, workspace=workspace)
                try:
                    conversation.send_message(task_input)
                    conversation.run()
                finally:
                    conversation.close()

        elif mode == "headless":
            if not task:
                console.print(
                    "[red]Error:[/red] --task is required for headless mode."
                )
                raise SystemExit(1)

            conversation = Conversation(agent=oh_agent, workspace=workspace)
            try:
                conversation.send_message(task)
                conversation.run()
            finally:
                conversation.close()

        elif mode == "web":
            console.print(
                "[yellow]Warning:[/yellow] OpenHands web mode is not yet "
                "supported via Zil. Use the OpenHands CLI or Cloud UI instead."
            )
            raise SystemExit(1)

        else:
            console.print(f"[red]Error:[/red] Unknown mode {mode!r}")
            raise SystemExit(1)

    # ---- deploy_descriptor -------------------------------------------

    def deploy_descriptor(
        self, agent: Any, spec: AgentSpec
    ) -> dict[str, Any]:
        """Return deployment metadata for an OpenHands agent."""
        module_name = spec.name.replace("-", "_")
        return {
            "framework": "openhands",
            "needs_docker": True,
            "image_base": "python:3.12-slim",
            "pip_packages": ["openhands-sdk", "openhands-tools", "zil-ai[openhands]"],
            "entrypoint": f"python -m {module_name}.agent",
            "env_vars": {
                "LLM_API_KEY": "${LLM_API_KEY}",
                "LLM_MODEL": spec.model,
            },
        }

    # ---- validate ----------------------------------------------------

    def validate(
        self, project_dir: Path, manifest: dict[str, Any]
    ) -> list[Any]:
        """Return OpenHands-specific validation checks."""
        from zil.schema.loader import CheckResult

        checks: list[Any] = []

        # Check LLM_API_KEY is declared in spec.env
        env_decls = manifest.get("spec", {}).get("env", [])
        env_names = {e.get("name", "") for e in env_decls if isinstance(e, dict)}

        if "LLM_API_KEY" not in env_names:
            checks.append(
                CheckResult(
                    "warn",
                    "openhands — LLM_API_KEY not declared in spec.env "
                    "(required by most OpenHands LLM providers)",
                )
            )
        else:
            checks.append(
                CheckResult("pass", "openhands — LLM_API_KEY declared in spec.env")
            )

        # Warn if sub-agents are declared (not supported by OpenHands)
        agents = manifest.get("spec", {}).get("agents", [])
        if agents:
            checks.append(
                CheckResult(
                    "warn",
                    f"openhands — {len(agents)} sub-agent(s) declared but "
                    "OpenHands does not support sub-agents; they will be ignored",
                )
            )

        return checks

    # ---- scaffold_config ---------------------------------------------

    def scaffold_config(self) -> dict[str, Any] | None:
        """Return template overrides for ``zil init --framework openhands``."""
        return {
            "pip_extra": "openhands",
            "default_tools": ["terminal", "file_editor"],
            "identity_persona": (
                "You are a careful, methodical autonomous coding agent.\n"
                "You plan before acting, write clean code, and verify your work."
            ),
            "identity_instructions": (
                "1. Read and understand the task thoroughly before writing code.\n"
                "2. Break complex tasks into small, testable steps.\n"
                "3. Write tests alongside implementation when appropriate.\n"
                "4. Verify your changes compile/run before declaring done.\n"
                "5. Use git to commit logical, atomic changes.\n"
                "6. Never modify files outside the designated workspace."
            ),
        }

    # ---- helpers -----------------------------------------------------

    @staticmethod
    def _load_skills_from_dir(skills_dir: Path) -> list[Any]:
        """Load SKILL.md files from a directory into OpenHands Skill objects.

        Scans skills_dir for subdirectories containing a SKILL.md file,
        parses frontmatter (name, description) and content, and returns
        a list of ``openhands.sdk.skills.Skill`` instances suitable for
        ``AgentContext.skills``.
        """
        try:
            from openhands.sdk.skills import Skill
        except ImportError:
            logger.warning("Cannot import openhands.sdk.skills.Skill — skills unavailable")
            return []

        skills: list[Any] = []
        for subdir in sorted(skills_dir.iterdir()):
            skill_md = subdir / "SKILL.md"
            if not skill_md.is_file():
                continue
            try:
                import frontmatter as fm
                post = fm.load(str(skill_md))
                name = post.metadata.get("name", subdir.name)
                description = post.metadata.get("description", "")
                content = post.content

                skill = Skill(
                    name=name,
                    content=content,
                    description=description.strip() if description else None,
                    source=str(skill_md),
                    is_agentskills_format=True,
                )
                skills.append(skill)
                logger.info("[skill] loaded: %s", name)
            except Exception as exc:
                logger.warning("[skill] failed to load %s: %s", subdir.name, exc)

        return skills

    @staticmethod
    def _build_mcp_config(
        mcp_server_configs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Transform Zil MCP server config list to OpenHands format.

        Zil format::

            [{"name": "jira", "command": "npx", "args": [...], "env": {...}}]

        OpenHands format::

            {"mcpServers": {"jira": {"command": "npx", "args": [...], "env": {...}}}}

        Resolves ``${VAR}`` env-var placeholders in command, args, env,
        and url values (matching what the ADK backend does via ``mcp.py``).
        """
        import re

        env_re = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

        def _resolve(value: str) -> str:
            return env_re.sub(
                lambda m: os.environ.get(m.group(1), m.group(0)), value
            )

        if not mcp_server_configs:
            return {}

        servers: dict[str, Any] = {}
        for cfg in mcp_server_configs:
            name = cfg.get("name", "")
            if not name:
                continue
            server_entry: dict[str, Any] = {}
            if "command" in cfg:
                server_entry["command"] = _resolve(cfg["command"])
            if "args" in cfg:
                server_entry["args"] = [_resolve(a) for a in cfg["args"]]
            if "env" in cfg:
                server_entry["env"] = {k: _resolve(v) for k, v in cfg["env"].items()}
            if "url" in cfg:
                server_entry["url"] = _resolve(cfg["url"])
            servers[name] = server_entry

        return {"mcpServers": servers} if servers else {}

    @staticmethod
    def _extract_message_text(event: Any) -> str:
        """Extract plain text from an OpenHands MessageEvent."""
        if not hasattr(event, "llm_message") or not event.llm_message:
            return ""
        msg = event.llm_message
        content = getattr(msg, "content", None)
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                getattr(part, "text", "") for part in content
                if getattr(part, "text", "")
            )
        return ""

    async def invoke(
        self,
        agent: Any,
        message: str,
        *,
        session_id: str | None = None,
        workspace: str | Path | None = None,
    ) -> AsyncIterator:
        """Invoke the OpenHands agent and yield SessionEvents.

        Uses OpenHands' Conversation API with **callbacks** and an
        ``asyncio.Queue`` so that events are streamed in real time
        (tool calls, observations, agent messages) as they happen
        during execution.
        """
        import asyncio

        from zil.sdk.session import SessionEvent

        try:
            from openhands.sdk import Conversation
            from openhands.sdk.event import (
                ActionEvent,
                AgentErrorEvent,
                MessageEvent,
                ObservationEvent,
            )
        except ImportError:
            yield SessionEvent(
                type="error",
                text="openhands-sdk is required. Install with: uv pip install 'zil-ai[openhands]'",
            )
            return

        sid = session_id or uuid.uuid4().hex
        oh_agent = agent._agent if hasattr(agent, "_agent") else agent

        # Create an isolated per-invocation workspace so the agent cannot
        # browse the host filesystem.  Falls back to explicit workspace if set.
        workspace_root = os.environ.get(
            "AGENT_WORKSPACE_ROOT", "/tmp/zil-workspaces"
        )
        ws_dir = Path(workspace_root) / sid
        ws_dir.mkdir(parents=True, exist_ok=True)
        ws = str(ws_dir)
        logger.info("[workspace] %s", ws)

        # Use a queue so callbacks push events in real-time while arun() runs.
        # The queue_holder is a mutable single-element list so the callback
        # (which is bound at conversation creation) always writes to the
        # CURRENT invocation's queue even when the conversation is reused.
        queue: asyncio.Queue[SessionEvent | None] = asyncio.Queue()

        # Check if we already have a conversation (and its queue_holder)
        entry = _conversations.get(sid)
        if entry is not None:
            queue_holder = entry[1]
        else:
            queue_holder = [queue]  # new holder for new conversation

        # Point the holder at this invocation's queue
        queue_holder[0] = queue

        def _on_event(event: Any) -> None:
            """Callback invoked by OpenHands for each event during execution."""
            q = queue_holder[0]  # always the current queue
            if isinstance(event, MessageEvent) and event.source == "agent":
                text = OpenHandsBackend._extract_message_text(event)
                if text:
                    logger.info("[agent] %s", text[:200])
                    q.put_nowait(SessionEvent(type="text", text=text))

            elif isinstance(event, ActionEvent):
                tool = getattr(event, "tool_name", "") or ""
                thought_parts = getattr(event, "thought", [])
                thought_text = ""
                if thought_parts:
                    thought_text = " ".join(
                        getattr(p, "text", "") for p in thought_parts
                        if getattr(p, "text", "")
                    )
                if thought_text:
                    logger.info("[thinking] %s", thought_text[:200])
                    q.put_nowait(SessionEvent(
                        type="text",
                        text=thought_text,
                        metadata={"kind": "reasoning"},
                    ))
                if tool:
                    logger.info("[tool_call] %s", tool)
                    q.put_nowait(SessionEvent(
                        type="tool_call",
                        tool_name=tool,
                        args={"tool_call_id": getattr(event, "tool_call_id", "")},
                    ))

            elif isinstance(event, ObservationEvent):
                obs = getattr(event, "observation", None)
                obs_text = str(obs)[:2000] if obs else ""
                tool = getattr(event, "tool_name", "") or ""
                if obs_text:
                    logger.info("[tool_result] %s → %s", tool, obs_text[:120])
                    q.put_nowait(SessionEvent(
                        type="tool_result",
                        text=obs_text,
                        tool_name=tool,
                    ))

            elif isinstance(event, AgentErrorEvent):
                err = getattr(event, "error", str(event))
                logger.error("[agent_error] %s", err)
                q.put_nowait(SessionEvent(type="error", text=str(err)))

        async def _run_agent():
            """Run the agent in a task, then signal completion via sentinel."""
            try:
                # Reuse an existing conversation for multi-turn, or create one
                existing = _conversations.get(sid)
                if existing is None:
                    persist_root = os.environ.get(
                        "AGENT_PERSIST_ROOT", "/tmp/zil-conversations"
                    )
                    persist_dir = str(Path(persist_root) / sid)
                    # OpenHands expects conversation_id as uuid.UUID
                    try:
                        conv_id = uuid.UUID(sid)
                    except ValueError:
                        conv_id = uuid.uuid5(uuid.NAMESPACE_DNS, sid)
                    conversation = Conversation(
                        agent=oh_agent,
                        workspace=ws,
                        persistence_dir=persist_dir,
                        conversation_id=conv_id,
                        visualizer=None,
                        callbacks=[_on_event],
                        delete_on_close=False,
                    )
                    _conversations[sid] = (conversation, queue_holder)
                    logger.info("[conversation] new %s", sid)
                else:
                    conversation = existing[0]
                    logger.info("[conversation] reusing %s", sid)

                conversation.send_message(message)
                await conversation.arun()
            except Exception as exc:
                logger.error("[invoke error] %s", exc)
                await queue.put(SessionEvent(type="error", text=str(exc)))
            finally:
                await queue.put(None)  # sentinel — signals end of events

        # Start the agent execution as a background task
        task = asyncio.create_task(_run_agent())

        # Yield events from the queue as they arrive in real-time
        while True:
            event = await queue.get()
            if event is None:
                break
            yield event

        # Ensure the task is done (handles exceptions)
        await task

        yield SessionEvent(
            type="done",
            metadata={"session_id": sid, "workspace": ws},
        )

    def close_session(self, session_id: str) -> None:
        """Release the cached Conversation for this session."""
        entry = _conversations.pop(session_id, None)
        if entry is not None:
            conv = entry[0]
            try:
                conv.close()
                logger.info("[conversation] closed %s", session_id)
            except Exception as exc:
                logger.warning("[conversation] close error for %s: %s", session_id, exc)

    def _wire_from_project(
        self, project_dir: Path, module_name: str | None = None
    ) -> OpenHandsWiredAgent:
        """Wire an agent from the project manifest (for CLI-level invocation)."""
        from zil.sdk.agent import create_agent

        # create_agent dispatches back to OpenHandsBackend.wire() via the registry
        inner = create_agent(project_dir=project_dir)
        return OpenHandsWiredAgent(_agent=inner)
