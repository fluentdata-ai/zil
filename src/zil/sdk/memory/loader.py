"""Load ``adapters/memory.yaml`` into a provider instance."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from zil.sdk.memory.config import MemoryConfig
from zil.sdk.memory.registry import registry
from zil.sdk.memory.types import MemoryProvider

logger = logging.getLogger(__name__)

DEFAULT_MEMORY_ADAPTER = "./adapters/memory.yaml"


def resolve_memory_ref(manifest: dict[str, Any]) -> str | None:
    """Return the ``spec.memory`` path, or ``None`` if memory is not enabled."""
    return manifest.get("spec", {}).get("memory")


def load_memory_config(
    project_dir: Path, manifest: dict[str, Any]
) -> MemoryConfig | None:
    """Parse the memory adapter referenced by ``spec.memory``.

    Returns ``None`` when the manifest does not declare memory.
    """
    ref = resolve_memory_ref(manifest)
    if not ref:
        return None

    # ``spec.memory`` may point directly at a YAML file or at a directory
    # containing ``memory.yaml``.
    candidate = (project_dir / ref).resolve()
    if candidate.is_dir():
        candidate = candidate / "memory.yaml"
    if not candidate.is_file():
        raise FileNotFoundError(
            f"Memory adapter config not found at {candidate}. "
            "Check spec.memory in manifest.yaml."
        )

    with open(candidate, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return MemoryConfig.from_dict(data)


def build_provider(config: MemoryConfig) -> MemoryProvider:
    """Instantiate the memory provider named in ``config``."""
    return registry.create(config)


def load_memory_provider(
    project_dir: Path, manifest: dict[str, Any]
) -> tuple[MemoryConfig, MemoryProvider] | None:
    """Convenience: load config and build the provider in one call."""
    config = load_memory_config(project_dir, manifest)
    if config is None:
        return None
    return config, build_provider(config)
