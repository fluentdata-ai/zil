"""Locate the project root and load the manifest + referenced files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

MANIFEST_FILENAME = "manifest.yaml"


class ProjectContext:
    """Resolved project context from manifest.yaml and referenced files."""

    def __init__(
        self,
        project_dir: Path,
        manifest: dict[str, Any],
        identity: IdentityContext,
        llm_adapter: dict[str, Any],
        observability: dict[str, Any] | None = None,
        env_declarations: list[dict[str, Any]] | None = None,
        cost_config: dict[str, Any] | None = None,
    ) -> None:
        self.project_dir = project_dir
        self.manifest = manifest
        self.identity = identity
        self.llm_adapter = llm_adapter
        self.observability = observability
        self.env_declarations = env_declarations or []
        self.cost_config = cost_config

    @property
    def name(self) -> str:
        return self.manifest["metadata"]["name"]

    @property
    def version(self) -> str:
        return self.manifest["metadata"]["version"]

    @property
    def description(self) -> str:
        return self.manifest["metadata"].get("description", "")

    @property
    def framework(self) -> str:
        return self.manifest["spec"]["runtime"]["framework"]


class IdentityContext:
    """Resolved identity files (persona, instructions, guardrails)."""

    def __init__(
        self,
        persona: str | None,
        instructions: str | None,
        guardrails: dict[str, Any] | None,
    ) -> None:
        self.persona = persona
        self.instructions = instructions
        self.guardrails = guardrails


def find_project_dir(start: Path | None = None) -> Path:
    """Walk up from *start* (default: cwd) looking for manifest.yaml."""
    current = (start or Path.cwd()).resolve()
    for directory in [current, *current.parents]:
        if (directory / MANIFEST_FILENAME).is_file():
            return directory
    raise FileNotFoundError(
        f"Could not find {MANIFEST_FILENAME} in {current} or any parent directory. "
        "Are you inside a Zil project?"
    )


def load_project(project_dir: Path | None = None) -> ProjectContext:
    """Load the full project context from *project_dir* (or auto-detect)."""
    if project_dir:
        candidate = project_dir.resolve()
        if (candidate / MANIFEST_FILENAME).is_file():
            root = candidate
        else:
            root = find_project_dir(start=candidate)
    else:
        root = find_project_dir()
    manifest = _load_yaml(root / MANIFEST_FILENAME)

    identity = _load_identity(root, manifest)
    llm_adapter = _load_llm_adapter(root, manifest)
    observability = _load_observability(root, manifest)

    env_declarations = manifest.get("spec", {}).get("env", [])
    cost_config = manifest.get("spec", {}).get("cost")

    return ProjectContext(
        project_dir=root,
        manifest=manifest,
        identity=identity,
        llm_adapter=llm_adapter,
        observability=observability,
        env_declarations=env_declarations,
        cost_config=cost_config,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_yaml(path: Path) -> dict[str, Any]:
    """Read and parse a YAML file."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _read_text(path: Path) -> str | None:
    """Read a text file if it exists, else return None."""
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return None


def _load_identity(root: Path, manifest: dict[str, Any]) -> IdentityContext:
    """Load persona, instructions, and guardrails from the identity directory."""
    identity_path = manifest.get("spec", {}).get("identity", "./identity")
    identity_dir = (root / identity_path).resolve()

    persona = _read_text(identity_dir / "persona.md")
    instructions = _read_text(identity_dir / "instructions.md")

    guardrails_path = identity_dir / "guardrails.yaml"
    guardrails = _load_yaml(guardrails_path) if guardrails_path.is_file() else None

    return IdentityContext(
        persona=persona,
        instructions=instructions,
        guardrails=guardrails,
    )


def _load_observability(root: Path, manifest: dict[str, Any]) -> dict[str, Any] | None:
    """Load observability config if referenced in the manifest."""
    obs_ref = manifest.get("spec", {}).get("observability")
    if not obs_ref:
        return None
    obs_path = (root / obs_ref / "config.yaml").resolve()
    if obs_path.is_file():
        return _load_yaml(obs_path)
    return None


def _load_llm_adapter(root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """Load the LLM adapter configuration."""
    adapter_path = (
        manifest.get("spec", {})
        .get("runtime", {})
        .get("llm", {})
        .get("adapter", "./adapters/llm.yaml")
    )
    full_path = (root / adapter_path).resolve()
    if not full_path.is_file():
        raise FileNotFoundError(
            f"LLM adapter config not found at {full_path}. "
            "Check spec.runtime.llm.adapter in manifest.yaml."
        )
    return _load_yaml(full_path)
