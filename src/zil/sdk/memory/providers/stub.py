"""In-memory stub provider — test-only, zero external dependencies.

Stores memories in a process-local dict keyed by ``(scope, partition)`` and
does naive token-overlap scoring for retrieval. Useful for exercising the
neutral core, wiring, validation, and governance without any provider SDK.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Mapping, Sequence

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

_KEY_NAME = {
    MemoryScope.SESSION: "session_id",
    MemoryScope.USER: "user_id",
    MemoryScope.AGENT: "namespace",
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


class StubMemoryProvider:
    """A trivial in-memory MemoryProvider for tests and local dev."""

    # Inherent capability: the stub can serve every scope.
    CAPABILITIES = frozenset(MemoryScope)
    REQUIRES_SUBSTRATE = False

    def __init__(self, config: MemoryConfig | None = None) -> None:
        self._config = config
        # partition key -> list of MemoryItem
        self._store: dict[tuple[str, str], list[MemoryItem]] = {}
        self._ids = itertools.count(1)

    @property
    def name(self) -> str:
        return "stub"

    def supports(self, scope: MemoryScope) -> bool:
        return scope in self.CAPABILITIES

    # -- internal helpers ------------------------------------------------

    def _partition(self, scope: MemoryScope, keys: MemoryKeys) -> tuple[str, str]:
        primary = keys.primary_for(scope)
        if not primary:
            raise MissingKeyError(scope, _KEY_NAME[scope])
        return (scope.value, primary)

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
        metadata: Mapping[str, object] | None = None,
        infer: bool | None = None,
    ) -> list[str]:
        self._require_scope(scope)
        part = self._partition(scope, keys)
        mem_id = str(next(self._ids))
        item = MemoryItem(
            content=content,
            id=mem_id,
            scope=scope,
            metadata=dict(metadata or {}),
        )
        self._store.setdefault(part, []).append(item)
        return [mem_id]

    def add_session(
        self,
        messages: Sequence[Message],
        *,
        scope: MemoryScope,
        keys: MemoryKeys,
        metadata: Mapping[str, object] | None = None,
    ) -> list[str]:
        self._require_scope(scope)
        # Naive "extraction": store each non-empty user/assistant message.
        ids: list[str] = []
        for msg in messages:
            content = str(msg.get("content", "")).strip()
            if not content:
                continue
            ids.extend(self.write(content, scope=scope, keys=keys, metadata=metadata))
        return ids

    def retrieve(self, query: MemoryQuery) -> list[MemoryItem]:
        self._require_scope(query.scope)
        part = self._partition(query.scope, query.keys)
        items = self._store.get(part, [])
        q_tokens = _tokens(query.query)
        scored: list[MemoryItem] = []
        for item in items:
            overlap = len(q_tokens & _tokens(item.content))
            score = overlap / len(q_tokens) if q_tokens else 0.0
            scored.append(
                MemoryItem(
                    content=item.content,
                    id=item.id,
                    scope=item.scope,
                    score=score,
                    metadata=dict(item.metadata),
                    created_at=item.created_at,
                )
            )
        scored.sort(key=lambda i: (i.score or 0.0), reverse=True)
        return scored[: query.limit]

    def delete(
        self,
        *,
        scope: MemoryScope,
        keys: MemoryKeys,
        ids: Sequence[str] | None = None,
    ) -> int:
        self._require_scope(scope)
        part = self._partition(scope, keys)
        items = self._store.get(part)
        if not items:
            return 0
        if ids is None:
            count = len(items)
            self._store[part] = []
            return count
        id_set = set(ids)
        keep = [i for i in items if i.id not in id_set]
        removed = len(items) - len(keep)
        self._store[part] = keep
        return removed

    def list_all(
        self,
        *,
        scope: MemoryScope,
        keys: MemoryKeys,
    ) -> list[MemoryItem]:
        self._require_scope(scope)
        part = self._partition(scope, keys)
        return [
            MemoryItem(
                content=item.content,
                id=item.id,
                scope=item.scope,
                metadata=dict(item.metadata),
                created_at=item.created_at,
            )
            for item in self._store.get(part, [])
        ]

    def close(self) -> None:  # pragma: no cover - trivial
        return None
