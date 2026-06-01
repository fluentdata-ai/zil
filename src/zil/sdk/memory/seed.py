"""Packable memory seeds (RFC-003 follow-up).

A *seed* is a curated set of AGENT-scope memories that ships inside the ``.zil``
archive so an agent deploys already knowing "what it is supposed to do". Seeds
come from two sources:

- an **authored** file committed to the repo (``memory/seed.yaml``), and/or
- a **live export** snapshot taken at pack time (``zil pack --export-memory``).

At runtime the bundled seed is installed into the provider **once**, idempotently:
a per-namespace marker keyed by the seed *digest* short-circuits re-seeding, and
per-item content hashes avoid duplicating individual entries when the seed grows.

Only the AGENT scope is supported — SESSION/USER are never packed.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from zil.sdk.memory.config import MemoryConfig
from zil.sdk.memory.types import MemoryKeys, MemoryProvider, MemoryScope

logger = logging.getLogger(__name__)

SEED_ARCHIVE_PATH = "memory/seed.jsonl"
_MARKER_CONTENT = "[zil seed marker]"
_META_HASH = "zil_seed_hash"
_META_DIGEST = "zil_seed_digest"
_META_MARKER = "zil_seed_marker"


class SeedError(ValueError):
    """Raised when a seed file is malformed."""


@dataclass
class SeedSet:
    """A normalized collection of AGENT-scope seed memories."""

    entries: list[dict[str, Any]] = field(default_factory=list)
    namespace: str | None = None
    version: int = 1

    @property
    def digest(self) -> str:
        return compute_digest(self.entries)

    def __len__(self) -> int:
        return len(self.entries)


@dataclass
class SeedReport:
    """Outcome of an idempotent seeding run."""

    seeded: int = 0
    skipped: bool = False
    reason: str = ""


# ---------------------------------------------------------------------------
# Hashing / normalization
# ---------------------------------------------------------------------------


def _canonical(metadata: dict[str, Any] | None) -> str:
    return json.dumps(metadata or {}, sort_keys=True, separators=(",", ":"))


def entry_hash(content: str, metadata: dict[str, Any] | None = None) -> str:
    """Stable content+metadata hash used for per-item dedup."""
    payload = content.strip() + "\u241f" + _canonical(_strip_seed_meta(metadata))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_digest(entries: list[dict[str, Any]]) -> str:
    """Digest over the whole seed set (order-independent)."""
    hashes = sorted(
        entry_hash(str(e.get("content", "")), e.get("metadata")) for e in entries
    )
    return hashlib.sha256("".join(hashes).encode("utf-8")).hexdigest()[:16]


def _strip_seed_meta(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Remove Zil's internal seed bookkeeping keys from metadata."""
    if not metadata:
        return {}
    return {
        k: v
        for k, v in metadata.items()
        if k not in (_META_HASH, _META_DIGEST, _META_MARKER)
    }


def normalize_entries(raw_entries: list[Any]) -> list[dict[str, Any]]:
    """Coerce raw seed records into ``[{content, metadata}]`` form."""
    entries: list[dict[str, Any]] = []
    for raw in raw_entries:
        if isinstance(raw, str):
            content, metadata = raw, {}
        elif isinstance(raw, dict):
            content = str(raw.get("content", "")).strip()
            metadata = _strip_seed_meta(raw.get("metadata") or {})
        else:
            raise SeedError(f"Invalid seed entry (must be str or mapping): {raw!r}")
        if not content:
            raise SeedError("Seed entry has empty 'content'")
        entry: dict[str, Any] = {"content": content}
        if metadata:
            entry["metadata"] = metadata
        entries.append(entry)
    return entries


# ---------------------------------------------------------------------------
# Authored seed file (YAML or JSONL)
# ---------------------------------------------------------------------------


def load_seed_file(path: Path) -> SeedSet:
    """Load and validate an authored seed file (``.yaml``/``.yml``/``.jsonl``)."""
    if not path.is_file():
        raise SeedError(f"Seed file not found: {path}")

    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        raw_entries = [json.loads(line) for line in text.splitlines() if line.strip()]
        return SeedSet(entries=normalize_entries(raw_entries))

    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise SeedError(f"Seed file {path.name} must be a mapping at the top level")

    version = int(data.get("version", 1))
    namespace = data.get("namespace")
    memories = data.get("memories")
    if memories is None:
        raise SeedError(f"Seed file {path.name} missing required 'memories' list")
    if not isinstance(memories, list):
        raise SeedError(f"Seed file {path.name}: 'memories' must be a list")

    # Seeds are AGENT-scope only.
    scopes = data.get("scopes", ["agent"])
    bad = [s for s in scopes if str(s).lower() != "agent"]
    if bad:
        raise SeedError(
            f"Seed file {path.name}: only the 'agent' scope is packable (got {scopes})"
        )

    return SeedSet(
        entries=normalize_entries(memories),
        namespace=namespace,
        version=version,
    )


# ---------------------------------------------------------------------------
# Archive (JSONL) round-trip
# ---------------------------------------------------------------------------


def dump_seed_jsonl(seed: SeedSet) -> bytes:
    """Serialize a seed set to the archive's JSONL form."""
    lines: list[str] = []
    for entry in seed.entries:
        record = {
            "content": entry["content"],
            "metadata": entry.get("metadata", {}),
            "hash": entry_hash(entry["content"], entry.get("metadata")),
        }
        lines.append(json.dumps(record, sort_keys=True))
    return ("\n".join(lines) + "\n").encode("utf-8") if lines else b""


def read_seed_jsonl(text: str) -> SeedSet:
    """Parse the archive's JSONL form back into a seed set."""
    raw = [json.loads(line) for line in text.splitlines() if line.strip()]
    return SeedSet(entries=normalize_entries(raw))


# ---------------------------------------------------------------------------
# Idempotent runtime seeding
# ---------------------------------------------------------------------------


def resolve_seed_path(project_dir: Path, config: MemoryConfig) -> Path | None:
    """Locate the bundled seed: archive JSONL first, then the authored file."""
    bundled = project_dir / SEED_ARCHIVE_PATH
    if bundled.is_file():
        return bundled
    seed_cfg = config.seed or {}
    rel = seed_cfg.get("file")
    if rel:
        # ``file`` is relative to the memory adapter; callers pass project_dir as
        # the resolution root, so accept both project- and adapter-relative refs.
        candidate = (project_dir / rel).resolve()
        if candidate.is_file():
            return candidate
    return None


def _load_any_seed(path: Path) -> SeedSet:
    if path.name.endswith(SEED_ARCHIVE_PATH.split("/")[-1]) and path.suffix == ".jsonl":
        return read_seed_jsonl(path.read_text(encoding="utf-8"))
    return load_seed_file(path)


def seed_if_needed(
    provider: MemoryProvider,
    config: MemoryConfig,
    seed_path: Path,
) -> SeedReport:
    """Install bundled seed memories into ``provider`` exactly once.

    Idempotency: a marker memory tagged with the seed ``digest`` short-circuits
    re-seeding; otherwise only entries whose content hash is not already present
    are written. Requires ``provider.list_all`` — without it we skip (to avoid
    silently duplicating data on every restart).
    """
    seed = _load_any_seed(seed_path)
    if not seed.entries:
        return SeedReport(skipped=True, reason="empty seed")

    # Defense-in-depth: drop any PII before it reaches the provider. The pack
    # path already filters, but authored seeds deployed from source may not
    # have been through it.
    from zil.sdk.memory import pii

    filtered = pii.filter_entries(seed.entries, mode="drop")
    if filtered.dropped:
        logger.warning(
            "Memory seed: dropped %d entr(y/ies) containing PII before seeding",
            len(filtered.dropped),
        )
    seed = SeedSet(entries=filtered.kept, namespace=seed.namespace, version=seed.version)
    if not seed.entries:
        return SeedReport(skipped=True, reason="all entries dropped by PII filter")

    namespace = seed.namespace or config.namespace
    if not namespace:
        return SeedReport(skipped=True, reason="no namespace for AGENT-scope seed")

    keys = MemoryKeys(namespace=namespace)
    scope = MemoryScope.AGENT

    if not hasattr(provider, "list_all"):
        logger.warning(
            "memory provider %r cannot list memories; skipping seeding to avoid "
            "duplicates", getattr(provider, "name", "?"),
        )
        return SeedReport(skipped=True, reason="provider lacks list_all")

    digest = seed.digest
    try:
        existing = provider.list_all(scope=scope, keys=keys)
    except Exception as exc:  # pragma: no cover - provider/runtime errors
        logger.warning("seed list_all failed: %s", exc)
        return SeedReport(skipped=True, reason=f"list_all error: {exc}")

    existing_hashes = {
        str(item.metadata.get(_META_HASH))
        for item in existing
        if item.metadata.get(_META_HASH)
    }
    marker_digests = {
        str(item.metadata.get(_META_DIGEST))
        for item in existing
        if item.metadata.get(_META_MARKER)
    }
    if digest in marker_digests:
        return SeedReport(skipped=True, reason="already seeded")

    seeded = 0
    for entry in seed.entries:
        h = entry_hash(entry["content"], entry.get("metadata"))
        if h in existing_hashes:
            continue
        metadata = dict(entry.get("metadata") or {})
        metadata[_META_HASH] = h
        metadata[_META_DIGEST] = digest
        provider.write(entry["content"], scope=scope, keys=keys, metadata=metadata)
        seeded += 1

    # Write the marker so subsequent boots short-circuit.
    provider.write(
        _MARKER_CONTENT,
        scope=scope,
        keys=keys,
        metadata={_META_MARKER: True, _META_DIGEST: digest},
    )
    logger.info(
        "Memory seeded — namespace=%s, new_entries=%d, digest=%s",
        namespace, seeded, digest,
    )
    return SeedReport(seeded=seeded)
