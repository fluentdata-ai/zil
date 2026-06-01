"""Framework- and provider-neutral memory types.

This module defines the core abstractions for Zil's memory layer. It has
**zero** imports of any provider SDK (mem0, vertex, zep) or agent framework
(google-adk, openhands) so it can be imported and exercised standalone.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class MemoryScope(StrEnum):
    """Where a memory lives and how broadly it is shared.

    The scope determines the primary partition key used by the underlying
    provider:

    - ``SESSION``: short-term, scoped to a single conversation/run.
    - ``USER``: long-term, scoped to one end-user.
    - ``AGENT``: long-term, scoped to a named *namespace* shared by a group
      of agents ("segmented knowledge"). Maps to a shared partition so that
      e.g. all coding agents share one pool while financial agents use a
      different one.
    """

    SESSION = "session"
    USER = "user"
    AGENT = "agent"

    @classmethod
    def from_str(cls, value: str) -> MemoryScope:
        try:
            return cls(value.strip().lower())
        except ValueError as exc:
            valid = ", ".join(s.value for s in cls)
            raise ValueError(
                f"Unknown memory scope {value!r}. Valid scopes: {valid}."
            ) from exc


@dataclass(frozen=True)
class MemoryKeys:
    """Partition keys identifying *which* memory a read/write targets.

    Providers translate these onto their native key model. For Mem0:
    ``user_id`` → ``user_id``, ``session_id`` → ``run_id``,
    ``namespace`` → ``agent_id`` (the segmented group key).
    """

    user_id: str | None = None
    session_id: str | None = None
    namespace: str | None = None

    def primary_for(self, scope: MemoryScope) -> str | None:
        """Return the key value that *must* be present for ``scope``."""
        if scope is MemoryScope.SESSION:
            return self.session_id
        if scope is MemoryScope.USER:
            return self.user_id
        if scope is MemoryScope.AGENT:
            return self.namespace
        return None


@dataclass
class MemoryItem:
    """A single stored memory returned from a provider."""

    content: str
    id: str | None = None
    scope: MemoryScope | None = None
    score: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"content": self.content}
        if self.id is not None:
            d["id"] = self.id
        if self.scope is not None:
            d["scope"] = self.scope.value
        if self.score is not None:
            d["score"] = self.score
        if self.metadata:
            d["metadata"] = self.metadata
        if self.created_at is not None:
            d["created_at"] = self.created_at
        return d


@dataclass
class MemoryQuery:
    """A semantic retrieval request against a scope/partition."""

    query: str
    scope: MemoryScope
    keys: MemoryKeys
    limit: int = 5


# Message lists for session ingestion: ``[{"role": "user", "content": "..."}]``
Message = Mapping[str, Any]


@runtime_checkable
class MemoryProvider(Protocol):
    """Protocol implemented by every memory backend (stub, mem0, ...).

    Implementations must not require network/cloud access at import time;
    heavy SDK imports should be lazy (inside methods or ``__init__``).
    """

    @property
    def name(self) -> str:
        """Registry key matching ``provider`` in ``adapters/memory.yaml``."""
        ...

    def supports(self, scope: MemoryScope) -> bool:
        """Whether this provider can serve the given scope."""
        ...

    def write(
        self,
        content: str,
        *,
        scope: MemoryScope,
        keys: MemoryKeys,
        metadata: Mapping[str, Any] | None = None,
    ) -> list[str]:
        """Persist a single memory string. Returns created memory id(s)."""
        ...

    def add_session(
        self,
        messages: Sequence[Message],
        *,
        scope: MemoryScope,
        keys: MemoryKeys,
        metadata: Mapping[str, Any] | None = None,
    ) -> list[str]:
        """Ingest a conversation; the provider extracts/derives memories."""
        ...

    def retrieve(self, query: MemoryQuery) -> list[MemoryItem]:
        """Semantic search within a scope/partition."""
        ...

    def delete(
        self,
        *,
        scope: MemoryScope,
        keys: MemoryKeys,
        ids: Sequence[str] | None = None,
    ) -> int:
        """Delete memories by id, or all in a scope/partition. Returns count."""
        ...

    def list_all(
        self,
        *,
        scope: MemoryScope,
        keys: MemoryKeys,
    ) -> list[MemoryItem]:
        """List every memory in a scope/partition (no semantic ranking).

        Used for memory export (``zil pack --export-memory``) and idempotent
        seeding. Providers that cannot enumerate memories may omit this method;
        callers must guard with ``hasattr(provider, "list_all")``.
        """
        ...

    def close(self) -> None:
        """Release provider resources (optional; default no-op)."""
        ...


class MemoryError(Exception):
    """Base class for memory-layer errors."""


class UnsupportedScopeError(MemoryError):
    """Raised when a provider is asked to serve a scope it does not support."""

    def __init__(self, provider: str, scope: MemoryScope, supported: list[str]) -> None:
        self.provider = provider
        self.scope = scope
        self.supported = supported
        super().__init__(
            f"Provider {provider!r} does not support scope {scope.value!r}. "
            f"Supported: {supported or ['(none)']}"
        )


class MissingKeyError(MemoryError):
    """Raised when the required partition key for a scope is absent."""

    def __init__(self, scope: MemoryScope, key_name: str) -> None:
        self.scope = scope
        self.key_name = key_name
        super().__init__(
            f"Scope {scope.value!r} requires '{key_name}' to be set in MemoryKeys."
        )
