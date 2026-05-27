"""Framework backend abstraction — neutral types and registry.

This module defines the protocol, data types, and registry that allow
Zil to support multiple agent frameworks (ADK, OpenHands, etc.) without
framework-specific logic leaking into ``create_agent`` or the CLI commands.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from zil.schema.loader import CheckResult
    from zil.sdk.loader import ProjectContext
    from zil.sdk.session import SessionEvent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Neutral data types
# ---------------------------------------------------------------------------


@dataclass
class AgentSpec:
    """Framework-neutral parsed agent specification.

    Constructed by ``create_agent()`` from the ``ProjectContext`` and user
    overrides, then passed to ``FrameworkBackend.wire()`` for framework-
    specific agent construction.
    """

    name: str
    version: str
    description: str
    instructions: str
    model: str

    # Tools — separated so backends can wire MCP their own way.
    tool_callables: list[Callable[..., Any]] = field(default_factory=list)
    mcp_server_configs: list[dict[str, Any]] = field(default_factory=list)

    # Sub-agents (from spec.agents in the manifest)
    sub_agent_specs: list[Any] = field(default_factory=list)

    # Configuration
    thinking_budget: int | None = None
    observability: dict[str, Any] | None = None
    raw_manifest: dict[str, Any] = field(default_factory=dict)

    # Cross-cutting callbacks (guardrails, cost)
    guardrail_callback: Any | None = None
    cost_callback: Any | None = None

    # Escape hatch for backend-specific needs
    context: ProjectContext | None = None


@runtime_checkable
class WiredAgent(Protocol):
    """Opaque handle wrapping a fully-configured framework agent."""

    @property
    def framework(self) -> str:
        """Name of the framework backend that produced this agent."""
        ...

    @property
    def inner(self) -> Any:
        """The underlying framework-specific agent object."""
        ...


@runtime_checkable
class FrameworkBackend(Protocol):
    """Protocol for pluggable agent framework backends.

    Each backend implements framework-specific wiring, local execution,
    and deployment descriptor generation.
    """

    @property
    def name(self) -> str:
        """Registry key matching ``spec.runtime.framework`` in the manifest."""
        ...

    def wire(self, spec: AgentSpec) -> WiredAgent:
        """Construct a framework-specific agent from the neutral spec."""
        ...

    def run_local(self, agent: WiredAgent, **kwargs: Any) -> None:
        """Run the agent locally.

        Standard kwargs:
            mode: "interactive" | "web" | "headless"
            project_dir: Path to the project root
            module_name: Name of the agent module directory
            port: Port for web mode (default 8000)
            trace_mode: Enable OTLP trace export
            trace_console: Print spans to stderr
            task: Task description (for headless mode)
        """
        ...

    def deploy_descriptor(self, agent: WiredAgent, spec: AgentSpec) -> dict[str, Any]:
        """Return framework-specific deployment metadata.

        The returned dict is consumed by ``zil deploy`` to configure the
        deployment target (Cloud Run, OpenHands runtime, etc.).
        """
        ...

    def validate(self, project_dir: Path, manifest: dict[str, Any]) -> list[CheckResult]:
        """Return framework-specific validation checks.

        Called by ``zil validate`` after the backend is resolved.
        Default implementations should return an empty list.
        """
        ...

    def scaffold_config(self) -> dict[str, Any] | None:
        """Return init template overrides for ``zil init --framework``.

        Returns a dict with keys like ``module_template``, ``dockerfile``,
        ``identity_defaults``, etc. Returns ``None`` if the backend does
        not provide scaffold support.
        """
        ...

    def invoke(
        self,
        agent: WiredAgent,
        message: str,
        *,
        session_id: str | None = None,
        workspace: str | Path | None = None,
    ) -> AsyncIterator[SessionEvent]:
        """Send a message to the agent and yield response events.

        This is the core invocation method used by ``zil.Session``.
        Backends must implement this as an async generator that yields
        ``SessionEvent`` instances as the agent processes the message.

        Args:
            agent: The wired agent to invoke.
            message: User message or task description.
            session_id: Session identifier for multi-turn conversations.
            workspace: Working directory for file-operating agents.

        Yields:
            ``SessionEvent`` instances in order of production.
        """
        ...

    def close_session(self, session_id: str) -> None:
        """Release backend-specific resources for a session.

        Called by ``Session.close()`` to allow backends to clean up
        any cached state (e.g., OpenHands Conversation objects,
        persistence files).  Default implementation is a no-op.
        """
        ...


# ---------------------------------------------------------------------------
# Backend registry
# ---------------------------------------------------------------------------


class UnknownFrameworkError(ValueError):
    """Raised when a framework name is not registered."""

    def __init__(self, name: str, registered: list[str]) -> None:
        self.name = name
        self.registered = registered
        super().__init__(
            f"Unknown framework {name!r}. "
            f"Registered backends: {registered or ['(none)']}"
        )


class BackendRegistry:
    """Maps framework names to ``FrameworkBackend`` implementations."""

    def __init__(self) -> None:
        self._backends: dict[str, FrameworkBackend] = {}

    def register(self, backend: FrameworkBackend) -> None:
        """Register a backend. Last-write-wins on duplicate names."""
        if backend.name in self._backends:
            logger.info(
                "BackendRegistry: overwriting existing backend %r",
                backend.name,
            )
        self._backends[backend.name] = backend
        logger.debug("BackendRegistry: registered %r", backend.name)

    def get(self, name: str) -> FrameworkBackend:
        """Retrieve a backend by name or raise ``UnknownFrameworkError``."""
        if name not in self._backends:
            raise UnknownFrameworkError(name, self.list_names())
        return self._backends[name]

    def list_names(self) -> list[str]:
        """Return sorted list of registered backend names."""
        return sorted(self._backends.keys())

    def __contains__(self, name: str) -> bool:
        return name in self._backends

    def __len__(self) -> int:
        return len(self._backends)
