"""Mem0 memory provider — the reference, cloud-neutral adapter.

Mem0 is the first provider for Zil's memory layer because it is framework- and
cloud-neutral and manages its own storage (vector/kv/graph) internally, so no
BYO substrate is required.

Scope → Mem0 key mapping:

- ``SESSION`` → ``run_id``      (short-term, one conversation/run)
- ``USER``    → ``user_id``     (long-term, per end-user)
- ``AGENT``   → ``agent_id``    (the *namespace* — a shared group key that lets
  a set of agents share one pool; "segmented knowledge")

Agents that pass the same ``namespace`` share AGENT-scope memory; combining a
``namespace`` with a ``user_id`` yields per-user memory within a group.

This module performs **no** import of ``mem0`` at module load — the SDK is
imported lazily on first client use so the registry stays usable (and tests
can mock the client) without ``mem0ai`` installed.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping, Sequence
from typing import Any

from zil.sdk.memory.config import MemoryConfig
from zil.sdk.memory.types import (
    MemoryItem,
    MemoryKeys,
    MemoryQuery,
    MemoryScope,
    Message,
    MissingKeyError,
    UnsupportedScopeError,
)

logger = logging.getLogger(__name__)

_KEY_NAME = {
    MemoryScope.SESSION: "session_id",
    MemoryScope.USER: "user_id",
    MemoryScope.AGENT: "namespace",
}


class Mem0Provider:
    """MemoryProvider backed by Mem0 (managed platform or self-hosted OSS)."""

    # Mem0 natively supports all three scopes via run_id/user_id/agent_id.
    CAPABILITIES = frozenset(MemoryScope)
    # Mem0 manages its own vector/kv/graph storage internally (both managed
    # and self-hosted modes), so it must NOT declare a BYO substrate block.
    REQUIRES_SUBSTRATE = False

    def __init__(
        self,
        config: MemoryConfig,
        *,
        client: Any | None = None,
    ) -> None:
        self._config = config
        self._client = client  # injectable for tests
        self._default_namespace = config.namespace

    @property
    def name(self) -> str:
        return "mem0"

    def supports(self, scope: MemoryScope) -> bool:
        return scope in self.CAPABILITIES

    # -- client construction --------------------------------------------

    @property
    def client(self) -> Any:
        """Lazily construct the Mem0 client on first use."""
        if self._client is not None:
            return self._client

        if self._config.is_managed:
            try:
                from mem0 import MemoryClient
            except ImportError as exc:  # pragma: no cover - env-dependent
                raise ImportError(
                    "mem0ai is required for the 'mem0' provider. "
                    "Install it with:  pip install 'zil-ai[memory]'"
                ) from exc
            api_key = os.environ.get("MEM0_API_KEY")
            kwargs: dict[str, Any] = {}
            if api_key:
                kwargs["api_key"] = api_key
            org = os.environ.get("MEM0_ORG_ID")
            project = os.environ.get("MEM0_PROJECT_ID")
            if org:
                kwargs["org_id"] = org
            if project:
                kwargs["project_id"] = project
            # A custom host points the Platform client at a self-hosted Mem0
            # server instead of the SaaS endpoint. Order: config → env.
            host = (
                self._config.host
                or os.environ.get("MEM0_API_BASE")
                or os.environ.get("MEM0_HOST")
            )
            if host:
                kwargs["host"] = host
                logger.debug("Mem0 using self-hosted server host=%s", host)
            self._client = MemoryClient(**kwargs)
        else:
            try:
                from mem0 import Memory
            except ImportError as exc:  # pragma: no cover - env-dependent
                raise ImportError(
                    "mem0ai is required for the 'mem0' provider. "
                    "Install it with:  pip install 'zil-ai[memory]'"
                ) from exc
            if self._config.config:
                self._client = Memory.from_config(self._config.config)
            else:
                self._client = Memory()
        return self._client

    # -- key mapping -----------------------------------------------------

    def _mem0_kwargs(self, scope: MemoryScope, keys: MemoryKeys) -> dict[str, str]:
        """Build Mem0 identifier kwargs from neutral keys for ``scope``."""
        namespace = keys.namespace or self._default_namespace
        primary = keys.primary_for(scope)
        if scope is MemoryScope.AGENT and not primary:
            primary = namespace
        if not primary:
            raise MissingKeyError(scope, _KEY_NAME[scope])

        kwargs: dict[str, str] = {}
        # Always pass any keys that are present so callers can combine e.g.
        # namespace + user_id for per-user-within-group memory.
        if keys.user_id:
            kwargs["user_id"] = keys.user_id
        if keys.session_id:
            kwargs["run_id"] = keys.session_id
        if namespace:
            kwargs["agent_id"] = namespace
        return kwargs

    def _require_scope(self, scope: MemoryScope) -> None:
        if not self.supports(scope):
            raise UnsupportedScopeError(
                self.name, scope, [s.value for s in self.CAPABILITIES]
            )

    # -- API -------------------------------------------------------------

    def write(
        self,
        content: str,
        *,
        scope: MemoryScope,
        keys: MemoryKeys,
        metadata: Mapping[str, Any] | None = None,
    ) -> list[str]:
        self._require_scope(scope)
        kwargs = self._mem0_kwargs(scope, keys)
        if metadata:
            kwargs["metadata"] = dict(metadata)  # type: ignore[assignment]
        result = self.client.add(content, **kwargs)
        return _extract_ids(result)

    def add_session(
        self,
        messages: Sequence[Message],
        *,
        scope: MemoryScope,
        keys: MemoryKeys,
        metadata: Mapping[str, Any] | None = None,
    ) -> list[str]:
        self._require_scope(scope)
        kwargs = self._mem0_kwargs(scope, keys)
        if metadata:
            kwargs["metadata"] = dict(metadata)  # type: ignore[assignment]
        result = self.client.add(list(messages), **kwargs)
        return _extract_ids(result)

    def retrieve(self, query: MemoryQuery) -> list[MemoryItem]:
        self._require_scope(query.scope)
        kwargs = self._mem0_kwargs(query.scope, query.keys)
        results = self.client.search(query.query, limit=query.limit, **kwargs)
        return _to_items(results, query.scope)

    def delete(
        self,
        *,
        scope: MemoryScope,
        keys: MemoryKeys,
        ids: Sequence[str] | None = None,
    ) -> int:
        self._require_scope(scope)
        if ids:
            count = 0
            for mem_id in ids:
                self.client.delete(memory_id=mem_id)
                count += 1
            return count
        kwargs = self._mem0_kwargs(scope, keys)
        self.client.delete_all(**kwargs)
        return -1  # provider does not report exact count for bulk delete

    def list_all(
        self,
        *,
        scope: MemoryScope,
        keys: MemoryKeys,
    ) -> list[MemoryItem]:
        self._require_scope(scope)
        kwargs = self._mem0_kwargs(scope, keys)
        results = self.client.get_all(**kwargs)
        return _to_items(results, scope)

    def close(self) -> None:  # pragma: no cover - trivial
        return None


# ---------------------------------------------------------------------------
# Response normalization (Mem0 managed vs OSS shapes differ)
# ---------------------------------------------------------------------------


def _records(result: Any) -> list[dict[str, Any]]:
    """Normalize a Mem0 add/search result into a list of record dicts."""
    if result is None:
        return []
    if isinstance(result, dict):
        inner = result.get("results", result.get("memories"))
        if isinstance(inner, list):
            return [r for r in inner if isinstance(r, dict)]
        return []
    if isinstance(result, list):
        return [r for r in result if isinstance(r, dict)]
    return []


def _extract_ids(result: Any) -> list[str]:
    ids: list[str] = []
    for rec in _records(result):
        mem_id = rec.get("id") or rec.get("memory_id")
        if mem_id is not None:
            ids.append(str(mem_id))
    return ids


def _to_items(result: Any, scope: MemoryScope) -> list[MemoryItem]:
    items: list[MemoryItem] = []
    for rec in _records(result):
        content = rec.get("memory") or rec.get("text") or rec.get("content") or ""
        items.append(
            MemoryItem(
                content=str(content),
                id=str(rec["id"]) if rec.get("id") is not None else None,
                scope=scope,
                score=rec.get("score"),
                metadata=rec.get("metadata") or {},
                created_at=rec.get("created_at"),
            )
        )
    return items
