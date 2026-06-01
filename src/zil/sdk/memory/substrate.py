"""Bring-your-own-store (BYO) substrate protocols.

These define the seams for providers that do *not* manage their own vector
store (the "BYO-store" case, e.g. a future Zep/pgvector adapter). They are
declared here so the validation layer can reason about substrate config and
so RFC-004 (RAG) can reuse the same abstractions.

Managed providers like Mem0 manage their own storage internally and MUST NOT
declare a substrate block — see ``loader._check`` / ``schema.loader``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class EmbeddingsAdapter(Protocol):
    """Turns text into vectors for storage/retrieval."""

    @property
    def dimensions(self) -> int:
        """Embedding vector dimensionality."""
        ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one embedding vector per input text."""
        ...


@runtime_checkable
class VectorStoreAdapter(Protocol):
    """A pluggable vector store (pgvector, Qdrant, etc.)."""

    def upsert(
        self,
        *,
        ids: Sequence[str],
        vectors: Sequence[Sequence[float]],
        payloads: Sequence[dict[str, Any]],
        namespace: str | None = None,
    ) -> None:
        """Insert or update vectors with associated payloads."""
        ...

    def query(
        self,
        *,
        vector: Sequence[float],
        limit: int,
        namespace: str | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Return nearest payloads (each including a similarity ``score``)."""
        ...

    def delete(
        self,
        *,
        ids: Sequence[str] | None = None,
        namespace: str | None = None,
    ) -> int:
        """Delete by id or clear a namespace. Returns count removed."""
        ...


@runtime_checkable
class VectorizationSubstrate(Protocol):
    """A composed embeddings + vector-store substrate for BYO providers."""

    @property
    def embeddings(self) -> EmbeddingsAdapter:
        ...

    @property
    def store(self) -> VectorStoreAdapter:
        ...
