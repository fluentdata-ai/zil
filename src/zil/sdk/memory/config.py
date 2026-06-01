"""Parsed representation of ``adapters/memory.yaml``."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from zil.sdk.memory.types import MemoryScope


@dataclass
class MemoryConfig:
    """Resolved memory configuration for a project.

    Mirrors the shape of ``adapters/memory.yaml``::

        provider: mem0
        mode: managed            # managed | self_hosted
        host: https://mem0.my-vpc.internal  # self-hosted Mem0 server (optional)
        namespace: coding        # default AGENT-scope group key
        scopes: [session, user, agent]
        retention:
          user: 90d
          session: ephemeral
        persist:
          include: [preferences, decisions]
          exclude_pii: true
        substrate: { ... }       # BYO-store only; absent for managed providers
        config: { ... }          # provider-specific (e.g. mem0 self-host stores)
        seed:                    # optional packable AGENT-scope knowledge
          file: ../memory/seed.yaml
          scopes: [agent]
    """

    provider: str
    mode: str = "managed"
    host: str | None = None
    namespace: str | None = None
    scopes: list[MemoryScope] = field(default_factory=list)
    retention: dict[str, Any] = field(default_factory=dict)
    persist: dict[str, Any] = field(default_factory=dict)
    substrate: dict[str, Any] | None = None
    config: dict[str, Any] = field(default_factory=dict)
    seed: dict[str, Any] | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_managed(self) -> bool:
        return self.mode == "managed"

    @property
    def exclude_pii(self) -> bool:
        return bool(self.persist.get("exclude_pii", False))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryConfig:
        provider = data.get("provider")
        if not provider:
            raise ValueError("adapters/memory.yaml: missing required 'provider' field")

        scopes_raw = data.get("scopes") or []
        scopes = [MemoryScope.from_str(s) for s in scopes_raw]

        return cls(
            provider=provider,
            mode=data.get("mode", "managed"),
            host=data.get("host"),
            namespace=data.get("namespace"),
            scopes=scopes,
            retention=data.get("retention") or {},
            persist=data.get("persist") or {},
            substrate=data.get("substrate"),
            config=data.get("config") or {},
            seed=data.get("seed"),
            raw=data,
        )
