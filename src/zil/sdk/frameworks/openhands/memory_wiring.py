"""Long-term memory wiring for the OpenHands backend (RFC-003).

OpenHands has no pluggable long-term *memory service* (its Context Condenser
manages only short-term/working context, and is a serialized pydantic
discriminated-union model whose subclassing would break persistence of saved
conversations). So Zil wires long-term memory at the SDK boundary instead:

- **recall**: before sending a turn, retrieve relevant memories and inject
  them as a context preamble (``inject_memories``);
- **persist**: after the turn completes, write the exchange back via
  ``provider.add_session`` (``persist_turn``).

Short-term context remains owned by OpenHands (native condenser +
``persistence_dir``), so ``SESSION`` scope is a pass-through here.

Default keying for OpenHands (a typically single-user coding agent): prefer the
AGENT scope keyed by ``namespace`` ("segmented knowledge" — e.g. all coding
agents share a pool); fall back to USER scope when no namespace is set.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from zil.sdk.memory.types import (
    MemoryKeys,
    MemoryProvider,
    MemoryQuery,
    MemoryScope,
)

logger = logging.getLogger(__name__)


def scope_and_keys(config: Any, *, user_id: str | None) -> tuple[MemoryScope, MemoryKeys]:
    """Pick the long-term scope/keys OpenHands should use."""
    scopes = getattr(config, "scopes", None) or list(MemoryScope)
    namespace = getattr(config, "namespace", None)
    if MemoryScope.AGENT in scopes and namespace:
        return MemoryScope.AGENT, MemoryKeys(namespace=namespace, user_id=user_id)
    return MemoryScope.USER, MemoryKeys(user_id=user_id, namespace=namespace)


def retrieve_memories(
    provider: MemoryProvider,
    config: Any,
    *,
    query: str,
    user_id: str | None,
    limit: int = 5,
) -> list[str]:
    """Return memory contents relevant to ``query`` (best-effort)."""
    scope, keys = scope_and_keys(config, user_id=user_id)
    try:
        items = provider.retrieve(
            MemoryQuery(query=query, scope=scope, keys=keys, limit=limit)
        )
    except Exception as exc:  # pragma: no cover - provider/runtime errors
        logger.warning("openhands memory retrieve failed: %s", exc)
        return []
    return [i.content for i in items if i.content]


def inject_memories(message: str, memories: Sequence[str]) -> str:
    """Prepend retrieved memories to the user message as a context preamble."""
    if not memories:
        return message
    bullets = "\n".join(f"- {m}" for m in memories)
    preamble = (
        "Relevant long-term memory (use if helpful; ignore if not):\n"
        f"{bullets}\n\n"
    )
    return preamble + message


def persist_turn(
    provider: MemoryProvider,
    config: Any,
    *,
    user_message: str,
    agent_messages: Sequence[str],
    user_id: str | None,
) -> None:
    """Write the completed exchange into long-term memory (best-effort)."""
    from zil.sdk.memory.curation import persist_messages

    scope, keys = scope_and_keys(config, user_id=user_id)
    messages: list[dict[str, str]] = [{"role": "user", "content": user_message}]
    messages.extend(
        {"role": "assistant", "content": m} for m in agent_messages if m
    )
    # Apply the project's persist policy (strategy + PII) before writing.
    try:
        persist_messages(provider, config, scope=scope, keys=keys, messages=messages)
    except Exception as exc:  # pragma: no cover - provider/runtime errors
        logger.warning("openhands memory persist failed: %s", exc)
