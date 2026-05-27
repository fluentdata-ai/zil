"""Framework-neutral agent session — invoke any Zil agent without framework imports.

Provides ``Session``, ``SessionEvent``, and ``SessionResponse`` as the public
invocation API.  Internally delegates to ``FrameworkBackend.invoke()`` so the
same application code works across ADK, OpenHands, or any future backend.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------


@dataclass
class SessionEvent:
    """A single event emitted during agent execution.

    Attributes:
        type: Event kind — "text" for LLM output tokens, "tool_call" when the
            agent invokes a tool, "tool_result" for the tool's return value,
            "error" for failures, "done" to signal completion.
        text: Human-readable text content (for "text" and "error" types).
        tool_name: Name of the tool being called (for "tool_call" type).
        args: Tool arguments (for "tool_call" type).
        result: Tool result data (for "tool_result" type).
        metadata: Backend-specific extra data (e.g., token counts, latency).
    """

    type: Literal["text", "tool_call", "tool_result", "error", "done"]
    text: str | None = None
    tool_name: str | None = None
    args: dict[str, Any] | None = None
    result: Any | None = None
    metadata: dict[str, Any] | None = None


@dataclass
class SessionResponse:
    """Aggregated result from a single ``Session.send()`` call.

    Attributes:
        text: Final concatenated text response from the agent.
        events: Full ordered list of events produced during execution.
        session_id: Unique identifier for this session.
        token_usage: Token consumption data (prompt, completion, total).
    """

    text: str
    events: list[SessionEvent] = field(default_factory=list)
    session_id: str = ""
    token_usage: dict[str, int] | None = None


# ---------------------------------------------------------------------------
# Session class
# ---------------------------------------------------------------------------


class Session:
    """Framework-neutral agent invocation handle.

    Wraps a wired agent and provides ``send()`` / ``stream()`` methods that
    delegate to the backend's ``invoke()`` implementation.

    Usage::

        import zil

        agent = zil.create_agent(project_dir=".", raw=True)
        session = zil.Session(agent)
        response = await session.send("Plan task INCA-229")
        print(response.text)

        # Multi-turn
        r2 = await session.send("Execute the plan")

        # Streaming
        async for event in session.stream("What's the status?"):
            print(event.text, end="")

        await session.close()
    """

    def __init__(
        self,
        agent: Any,
        *,
        workspace: str | Path | None = None,
        session_id: str | None = None,
    ) -> None:
        """Create a session for the given agent.

        Args:
            agent: A ``WiredAgent`` (from ``create_agent(raw=True)``) or a raw
                framework-specific agent object.  If a raw object is passed,
                the session attempts to identify and wrap it automatically.
            workspace: Working directory for agents that operate on files
                (e.g., OpenHands).  Defaults to cwd.
            session_id: Optional session identifier for resuming a conversation.
                If not provided, a new UUID is generated.
        """
        from zil.sdk.frameworks import registry
        from zil.sdk.frameworks.base import WiredAgent

        if isinstance(agent, WiredAgent):
            self._wired_agent = agent
        else:
            # Raw framework object — wrap it
            self._wired_agent = _wrap_raw_agent(agent)

        self._backend = registry.get(self._wired_agent.framework)
        self._workspace = str(Path(workspace).resolve()) if workspace else str(Path.cwd())
        self._session_id = session_id or uuid.uuid4().hex
        self._closed = False

    @property
    def session_id(self) -> str:
        """Unique identifier for this session."""
        return self._session_id

    @property
    def workspace(self) -> str:
        """Working directory for this session."""
        return self._workspace

    async def send(self, message: str) -> SessionResponse:
        """Send a message and wait for the full response.

        Args:
            message: The user message or task description.

        Returns:
            A ``SessionResponse`` with the aggregated text and event log.

        Raises:
            RuntimeError: If the session has been closed.
        """
        if self._closed:
            raise RuntimeError("Session is closed.")

        events: list[SessionEvent] = []
        text_parts: list[str] = []

        async for event in self.stream(message):
            events.append(event)
            if event.type == "text" and event.text:
                text_parts.append(event.text)

        # Extract token usage from the "done" event if present
        token_usage = None
        for ev in reversed(events):
            if ev.type == "done" and ev.metadata:
                token_usage = ev.metadata.get("token_usage")
                break

        return SessionResponse(
            text="".join(text_parts),
            events=events,
            session_id=self._session_id,
            token_usage=token_usage,
        )

    async def stream(self, message: str) -> AsyncIterator[SessionEvent]:
        """Send a message and stream response events as they arrive.

        Args:
            message: The user message or task description.

        Yields:
            ``SessionEvent`` objects in the order they are produced.

        Raises:
            RuntimeError: If the session has been closed.
        """
        if self._closed:
            raise RuntimeError("Session is closed.")

        async for event in self._backend.invoke(
            agent=self._wired_agent,
            message=message,
            session_id=self._session_id,
            workspace=self._workspace,
        ):
            yield event

    async def close(self) -> None:
        """Release resources associated with this session.

        After calling ``close()``, further ``send()`` / ``stream()`` calls
        will raise ``RuntimeError``.
        """
        self._closed = True
        if hasattr(self._backend, "close_session"):
            self._backend.close_session(self._session_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _wrap_raw_agent(agent: Any) -> Any:
    """Attempt to wrap a raw framework object as a WiredAgent."""
    # ADK LlmAgent
    try:
        from google.adk.agents import LlmAgent

        if isinstance(agent, LlmAgent):
            from zil.sdk.frameworks.adk.backend import AdkWiredAgent

            return AdkWiredAgent(_agent=agent)
    except ImportError:
        pass

    # OpenHands Agent
    try:
        from openhands.sdk import Agent

        if isinstance(agent, Agent):
            from zil.sdk.frameworks.openhands.backend import OpenHandsWiredAgent

            return OpenHandsWiredAgent(_agent=agent)
    except ImportError:
        pass

    raise TypeError(
        f"Cannot wrap agent of type {type(agent).__name__!r}. "
        "Pass a WiredAgent from create_agent(raw=True) or a recognized "
        "framework agent object (ADK LlmAgent, OpenHands Agent)."
    )
