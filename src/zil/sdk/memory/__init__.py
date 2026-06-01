"""Zil memory layer — framework- and provider-neutral long/short-term memory.

Public surface:

- Core types: ``MemoryScope``, ``MemoryKeys``, ``MemoryItem``, ``MemoryQuery``,
  ``MemoryProvider`` (Protocol), and the error types.
- ``MemoryConfig`` parsed from ``adapters/memory.yaml``.
- ``registry`` of provider factories (always has ``stub``; ``mem0`` when usable).
- Loaders: ``load_memory_config`` / ``build_provider`` / ``load_memory_provider``.

The neutral core (this package's ``types`` and ``substrate`` modules) imports
no provider SDK or agent framework, so it can be used and tested standalone.
"""

from __future__ import annotations

from zil.sdk.memory.config import MemoryConfig
from zil.sdk.memory.loader import (
    build_provider,
    load_memory_config,
    load_memory_provider,
    resolve_memory_ref,
)
from zil.sdk.memory.registry import (
    MemoryProviderRegistry,
    UnknownProviderError,
    registry,
)
from zil.sdk.memory.seed import (
    SEED_ARCHIVE_PATH,
    SeedError,
    SeedReport,
    SeedSet,
    load_seed_file,
    resolve_seed_path,
    seed_if_needed,
)
from zil.sdk.memory.types import (
    MemoryError,
    MemoryItem,
    MemoryKeys,
    MemoryProvider,
    MemoryQuery,
    MemoryScope,
    MissingKeyError,
    UnsupportedScopeError,
)

__all__ = [
    "SEED_ARCHIVE_PATH",
    "MemoryConfig",
    "MemoryError",
    "MemoryItem",
    "MemoryKeys",
    "MemoryProvider",
    "MemoryProviderRegistry",
    "MemoryQuery",
    "MemoryScope",
    "MissingKeyError",
    "SeedError",
    "SeedReport",
    "SeedSet",
    "UnknownProviderError",
    "UnsupportedScopeError",
    "build_provider",
    "load_memory_config",
    "load_memory_provider",
    "load_seed_file",
    "registry",
    "resolve_memory_ref",
    "resolve_seed_path",
    "seed_if_needed",
]
