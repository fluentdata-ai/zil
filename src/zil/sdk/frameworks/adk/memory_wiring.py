"""Bridge Zil's neutral MemoryProvider onto ADK's memory service.

ADK exposes long-term memory through ``BaseMemoryService`` (attached to the
``Runner``) plus a recall tool (``load_memory`` / ``PreloadMemoryTool``). This
module adapts a Zil ``MemoryProvider`` to that interface so any provider
(mem0, ...) gives ADK agents cross-session recall.

Scope mapping for ADK (which keys memory by ``app_name`` + ``user_id``):

- Long-term reads/writes use the USER scope when a ``user_id`` is present.
- If only AGENT scope is enabled, the namespace becomes the partition.

All ``google.adk`` imports are deferred to call time so importing this module
never hard-requires ADK.
"""

from __future__ import annotations

import logging
from typing import Any

from zil.sdk.frameworks.base import AgentSpec
from zil.sdk.memory.types import (
    MemoryItem,
    MemoryKeys,
    MemoryProvider,
    MemoryQuery,
    MemoryScope,
)

logger = logging.getLogger(__name__)


def _primary_scope(config: Any) -> MemoryScope:
    """Pick the long-term scope ADK should read/write by default."""
    scopes = getattr(config, "scopes", None) or list(MemoryScope)
    if MemoryScope.USER in scopes:
        return MemoryScope.USER
    if MemoryScope.AGENT in scopes:
        return MemoryScope.AGENT
    return MemoryScope.USER


def _keys_for(config: Any, user_id: str | None) -> MemoryKeys:
    namespace = getattr(config, "namespace", None)
    return MemoryKeys(user_id=user_id, namespace=namespace)


def make_memory_service(provider: MemoryProvider, config: Any) -> Any:
    """Build a ``BaseMemoryService`` that delegates to ``provider``."""
    from google.adk.memory.base_memory_service import (
        BaseMemoryService,
        SearchMemoryResponse,
    )
    from google.adk.memory.memory_entry import MemoryEntry
    from google.genai import types

    primary_scope = _primary_scope(config)

    class ZilAdkMemoryService(BaseMemoryService):
        """Adapts a Zil MemoryProvider to ADK's memory service contract."""

        def __init__(self) -> None:
            self._provider = provider
            self._config = config

        async def add_session_to_memory(self, session: Any) -> None:
            messages = _events_to_messages(getattr(session, "events", []) or [])
            if not messages:
                return
            keys = _keys_for(self._config, getattr(session, "user_id", None))
            try:
                self._provider.add_session(
                    messages, scope=primary_scope, keys=keys
                )
            except Exception as exc:  # pragma: no cover - provider/runtime errors
                logger.warning("memory add_session failed: %s", exc)

        async def search_memory(
            self, *, app_name: str, user_id: str, query: str
        ) -> Any:
            keys = _keys_for(self._config, user_id)
            try:
                items: list[MemoryItem] = self._provider.retrieve(
                    MemoryQuery(query=query, scope=primary_scope, keys=keys)
                )
            except Exception as exc:  # pragma: no cover - provider/runtime errors
                logger.warning("memory search failed: %s", exc)
                return SearchMemoryResponse(memories=[])

            entries = [
                MemoryEntry(
                    content=types.Content(
                        role="model",
                        parts=[types.Part.from_text(text=item.content)],
                    ),
                    author="memory",
                )
                for item in items
            ]
            return SearchMemoryResponse(memories=entries)

    return ZilAdkMemoryService()


def build_recall_tool() -> Any | None:
    """Return ADK's recall tool so the agent can fetch long-term memory."""
    try:
        from google.adk.tools import load_memory

        return load_memory
    except Exception as exc:  # pragma: no cover - version-dependent
        logger.warning("ADK load_memory tool unavailable: %s", exc)
        return None


def attach_memory(agent: Any, spec: AgentSpec) -> None:
    """Stash the provider/config on the agent for ``invoke`` to wire a Runner."""
    agent._zil_memory_provider = spec.memory_provider  # type: ignore[attr-defined]
    agent._zil_memory_config = spec.memory_config  # type: ignore[attr-defined]


def _events_to_messages(events: list[Any]) -> list[dict[str, str]]:
    """Flatten ADK session events into ``[{role, content}]`` messages."""
    messages: list[dict[str, str]] = []
    for event in events:
        content = getattr(event, "content", None)
        if content is None:
            continue
        parts = getattr(content, "parts", None) or []
        text = "".join(
            getattr(p, "text", "") or "" for p in parts
        ).strip()
        if not text:
            continue
        author = getattr(event, "author", None) or getattr(content, "role", "user")
        role = "user" if author == "user" else "assistant"
        messages.append({"role": role, "content": text})
    return messages
