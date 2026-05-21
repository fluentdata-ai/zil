"""Human-in-the-loop (HITL) primitives for Zil agents.

Provides a framework-neutral API for agents to pause execution and request
human input.  The mechanism works as follows:

1. The agent tool calls ``request_human_input()``.
2. The call records a ``pending_human_request`` in the session state
   (ADK ``ToolContext.state``) and sends a notification via the configured
   channel (Jira comment, Slack, etc.).
3. The call returns immediately — the agent turn ends cleanly.
4. The human responds via the ``/human/respond`` webhook endpoint, which
   injects a ``state_delta`` and calls ``runner.run_async()`` to resume.

This design is framework-neutral: the API is identical whether the
underlying runtime is ADK, LangGraph, or the future Zil Runtime.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class HumanInputRequest:
    """A request for human input from an agent tool.

    Args:
        question: The question or prompt to present to the human.
        context: Optional structured context (e.g. plan details, risk level).
        options: Optional list of valid response choices
            (e.g. ["approve", "reject", "modify"]).
        interaction_id: Auto-generated UUID for correlating request/response.
    """

    question: str
    context: dict[str, Any] = field(default_factory=dict)
    options: list[str] = field(default_factory=list)
    interaction_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class HumanInputResponse:
    """The human's response to a HITL request.

    Args:
        interaction_id: Matches the ``HumanInputRequest.interaction_id``.
        choice: The human's chosen option (or free-text if no options).
        comment: Optional free-text comment.
        timed_out: True if no response was received within ``timeout_seconds``.
    """

    interaction_id: str
    choice: str = ""
    comment: str = ""
    timed_out: bool = False


# ---------------------------------------------------------------------------
# Core primitive
# ---------------------------------------------------------------------------


async def request_human_input(
    request: HumanInputRequest,
    tool_context: Any,
) -> HumanInputResponse:
    """Request human input from within an agent tool.

    Records the pending request in session state and dispatches a notification.
    Returns a ``HumanInputResponse`` — either with the human's answer (if
    already available in ``tool_context.state``) or as a signal to the runtime
    that the agent turn should end and wait for the ``/human/respond`` webhook.

    In ADK, this works by writing to ``tool_context.state``.  The ADK runner
    persists this state change atomically before ending the turn, so the
    session remains durable even if the container scales to zero.

    Args:
        request: The HITL request to send to the human.
        tool_context: The framework's tool context object (ADK ``ToolContext``
            or equivalent).  Used to read/write session state.

    Returns:
        ``HumanInputResponse`` — check ``response.timed_out`` and
        ``response.choice`` in the calling tool.
    """
    state = _get_state(tool_context)

    # If the human has already responded (resume path), consume and return
    human_resp = state.get("human_response")
    if (
        human_resp
        and isinstance(human_resp, dict)
        and human_resp.get("interaction_id") == request.interaction_id
    ):
        _clear_hitl_state(tool_context)
        return HumanInputResponse(
            interaction_id=request.interaction_id,
            choice=human_resp.get("choice", ""),
            comment=human_resp.get("comment", ""),
        )

    # First-call path: record the pending request
    _set_state(tool_context, "pending_human_request", {
        "interaction_id": request.interaction_id,
        "question": request.question,
        "context": request.context,
        "options": request.options,
    })

    # Dispatch notification (best-effort — failure is logged, not raised)
    try:
        await _dispatch_notification(request, tool_context)
    except Exception as exc:
        logger.warning(
            "HITL notification dispatch failed for interaction %s: %s",
            request.interaction_id,
            exc,
        )

    logger.info(
        "HITL: pending human request recorded (id=%s, question=%r)",
        request.interaction_id,
        request.question[:80],
    )

    # Return a placeholder — the agent turn will end; the webhook resumes it
    return HumanInputResponse(
        interaction_id=request.interaction_id,
        choice="__pending__",
    )


# ---------------------------------------------------------------------------
# Session state helpers (ADK + generic dict-like fallback)
# ---------------------------------------------------------------------------


def _get_state(tool_context: Any) -> dict[str, Any]:
    """Extract the mutable state dict from the tool context."""
    if tool_context is None:
        return {}
    # ADK ToolContext exposes .state as a dict-like object
    state = getattr(tool_context, "state", None)
    if state is not None:
        return state  # type: ignore[return-value]
    # Fallback: plain dict passed directly (useful in tests)
    if isinstance(tool_context, dict):
        return tool_context
    return {}


def _set_state(tool_context: Any, key: str, value: Any) -> None:
    """Write a key into the tool context state."""
    state = _get_state(tool_context)
    try:
        state[key] = value
    except (TypeError, AttributeError):
        logger.debug("HITL: could not write key %r to state (read-only or None)", key)


def _clear_hitl_state(tool_context: Any) -> None:
    """Remove HITL state keys after a successful response."""
    state = _get_state(tool_context)
    for key in ("pending_human_request", "human_response"):
        try:
            state.pop(key, None)
        except (TypeError, AttributeError):
            pass


# ---------------------------------------------------------------------------
# Notification dispatch (pluggable per channel)
# ---------------------------------------------------------------------------


async def _dispatch_notification(
    request: HumanInputRequest,
    tool_context: Any,
) -> None:
    """Send a notification to the human via the configured channel.

    The channel is read from the session state key ``hitl_channel``
    (injected by the webhook runner from the manifest's
    ``spec.runtime.service.human_interaction.notify`` config).
    """
    state = _get_state(tool_context)
    channel_cfg: dict[str, Any] = state.get("hitl_channel") or {}
    channel = channel_cfg.get("channel", "log")

    if channel == "log":
        logger.info(
            "HITL [log channel] — question: %s | options: %s | id: %s",
            request.question,
            request.options or "free-text",
            request.interaction_id,
        )
    else:
        # Future channels (jira_comment, slack, http_callback) plug in here.
        # Each channel is an async function that reads the necessary env vars
        # and sends the notification.
        logger.info(
            "HITL channel %r not yet implemented — falling back to log channel",
            channel,
        )
        logger.info(
            "HITL — question: %s | options: %s | id: %s",
            request.question,
            request.options or "free-text",
            request.interaction_id,
        )
