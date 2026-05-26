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

        # --- Sub-agents warning ---
        if spec.sub_agent_specs:
            logger.warning(
                "OpenHands does not support sub-agents. "
                "spec.agents entries will be ignored for framework 'openhands'."
            )

        # --- Build the Agent ---
        agent = Agent(
            llm=llm,
            tools=tools,
            mcp_config=mcp_config,
            system_prompt=system_prompt,
        )

        logger.info(
            "OpenHandsBackend.wire() — agent configured "
            "(model=%s, tools=%d, mcp_servers=%d)",
            spec.model,
            len(tools),
            len(spec.mcp_server_configs),
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
    def _build_mcp_config(
        mcp_server_configs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Transform Zil MCP server config list to OpenHands format.

        Zil format::

            [{"name": "jira", "command": "npx", "args": [...], "env": {...}}]

        OpenHands format::

            {"mcpServers": {"jira": {"command": "npx", "args": [...], "env": {...}}}}
        """
        if not mcp_server_configs:
            return {}

        servers: dict[str, Any] = {}
        for cfg in mcp_server_configs:
            name = cfg.get("name", "")
            if not name:
                continue
            server_entry: dict[str, Any] = {}
            if "command" in cfg:
                server_entry["command"] = cfg["command"]
            if "args" in cfg:
                server_entry["args"] = cfg["args"]
            if "env" in cfg:
                server_entry["env"] = cfg["env"]
            if "url" in cfg:
                server_entry["url"] = cfg["url"]
            servers[name] = server_entry

        return {"mcpServers": servers} if servers else {}

    async def invoke(
        self,
        agent: Any,
        message: str,
        *,
        session_id: str | None = None,
        workspace: str | Path | None = None,
    ) -> AsyncIterator:
        """Invoke the OpenHands agent and yield SessionEvents.

        Uses OpenHands' Conversation API to send a message and maps
        the results to framework-neutral SessionEvent instances.
        """
        from zil.sdk.session import SessionEvent

        try:
            from openhands.sdk import Conversation
        except ImportError:
            yield SessionEvent(
                type="error",
                text="openhands-sdk is required. Install with: pip install 'zil-ai[openhands]'",
            )
            return

        sid = session_id or uuid.uuid4().hex
        ws = str(workspace) if workspace else str(Path.cwd())
        oh_agent = agent._agent if hasattr(agent, "_agent") else agent

        try:
            conversation = Conversation(agent=oh_agent, workspace=ws)
            try:
                conversation.send_message(message)
                result = conversation.run()

                # Extract text from result
                response_text = ""
                if hasattr(result, "text"):
                    response_text = result.text
                elif isinstance(result, str):
                    response_text = result
                elif result is not None:
                    response_text = str(result)

                if response_text:
                    yield SessionEvent(type="text", text=response_text)
            finally:
                conversation.close()

        except Exception as exc:
            yield SessionEvent(type="error", text=str(exc))

        yield SessionEvent(
            type="done",
            metadata={"session_id": sid, "workspace": ws},
        )

    def _wire_from_project(
        self, project_dir: Path, module_name: str | None = None
    ) -> OpenHandsWiredAgent:
        """Wire an agent from the project manifest (for CLI-level invocation)."""
        from zil.sdk.agent import create_agent

        # create_agent dispatches back to OpenHandsBackend.wire() via the registry
        inner = create_agent(project_dir=project_dir)
        return OpenHandsWiredAgent(_agent=inner)
