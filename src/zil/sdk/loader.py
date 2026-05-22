"""Locate the project root and load the manifest + referenced files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

MANIFEST_FILENAME = "manifest.yaml"


@dataclass
class AgentSpec:
    """Resolved configuration for a single sub-agent in a multi-agent hierarchy."""

    name: str
    role: str
    identity: IdentityContext
    identity_path: Path
    llm_adapter: dict[str, Any]
    model_env_var: str | None
    mcp_server_names: list[str]
    description: str
    skill_names: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.skill_names is None:
            self.skill_names = []


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
        tools_config: dict[str, Any] | None = None,
        agents: list[AgentSpec] | None = None,
        service_config: dict[str, Any] | None = None,
        skills_dir: Path | None = None,
        runtime_deps: list[dict[str, Any]] | None = None,
    ) -> None:
        self.project_dir = project_dir
        self.manifest = manifest
        self.identity = identity
        self.llm_adapter = llm_adapter
        self.observability = observability
        self.env_declarations = env_declarations or []
        self.cost_config = cost_config
        self.tools_config = tools_config
        self.agents: list[AgentSpec] = agents or []
        self.service_config = service_config
        self.skills_dir: Path | None = skills_dir
        self.runtime_deps: list[dict[str, Any]] = runtime_deps or []

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
    tools_config = _load_tools(root, manifest)
    agents = _load_agents(root, manifest, llm_adapter)
    service_config = _load_service(manifest)
    skills_dir = _load_skills_dir(root, manifest)

    env_declarations = manifest.get("spec", {}).get("env", [])
    cost_config = manifest.get("spec", {}).get("cost")
    runtime_deps = manifest.get("spec", {}).get("runtime", {}).get("dependencies", [])

    return ProjectContext(
        project_dir=root,
        manifest=manifest,
        identity=identity,
        llm_adapter=llm_adapter,
        observability=observability,
        env_declarations=env_declarations,
        cost_config=cost_config,
        tools_config=tools_config,
        agents=agents,
        service_config=service_config,
        skills_dir=skills_dir,
        runtime_deps=runtime_deps,
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
    return _load_identity_from_dir(identity_dir)


def _load_observability(root: Path, manifest: dict[str, Any]) -> dict[str, Any] | None:
    """Load observability config if referenced in the manifest."""
    obs_ref = manifest.get("spec", {}).get("observability")
    if not obs_ref:
        return None
    obs_path = (root / obs_ref / "config.yaml").resolve()
    if obs_path.is_file():
        return _load_yaml(obs_path)
    return None


def _load_tools(root: Path, manifest: dict[str, Any]) -> dict[str, Any] | None:
    """Load tools configuration (inline object or from tools/ directory)."""
    tools_ref = manifest.get("spec", {}).get("tools")
    if not tools_ref:
        return None

    # Inline object: spec.tools is a dict with mcp_servers / host_dependencies
    if isinstance(tools_ref, dict):
        return tools_ref

    # String path: resolve to a directory and look for config.yaml
    tools_dir = (root / tools_ref).resolve()
    config_path = tools_dir / "config.yaml"
    if config_path.is_file():
        return _load_yaml(config_path)

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


def _load_agents(
    root: Path,
    manifest: dict[str, Any],
    root_llm_adapter: dict[str, Any],
) -> list[AgentSpec]:
    """Load sub-agent specs from spec.agents, if present."""
    agents_raw = manifest.get("spec", {}).get("agents")
    if not agents_raw:
        return []

    result: list[AgentSpec] = []
    for raw in agents_raw:
        name = raw["name"]
        role = raw.get("role", "sub-agent")
        description = raw.get("description", f"{name} sub-agent")

        # Resolve identity
        identity_ref = raw["identity"]
        identity_dir = (root / identity_ref).resolve()
        identity = _load_identity_from_dir(identity_dir, root_llm_adapter)

        # Resolve LLM adapter — sub-agent can override root adapter
        llm_cfg = raw.get("llm") or {}
        adapter_ref = llm_cfg.get("adapter")
        if adapter_ref:
            adapter_path = (root / adapter_ref).resolve()
            llm_adapter = _load_yaml(adapter_path) if adapter_path.is_file() else root_llm_adapter
        else:
            llm_adapter = root_llm_adapter
        model_env_var: str | None = llm_cfg.get("model_env_var")

        # Resolve MCP server name references (just names — wiring happens in agent.py)
        mcp_server_names: list[str] = (raw.get("tools") or {}).get("mcp_servers") or []

        # Resolve skill name references (allowlist — SkillToolset built in agent.py)
        skill_names: list[str] = (raw.get("tools") or {}).get("skills") or []

        result.append(AgentSpec(
            name=name,
            role=role,
            identity=identity,
            identity_path=identity_dir,
            llm_adapter=llm_adapter,
            model_env_var=model_env_var,
            mcp_server_names=mcp_server_names,
            description=description,
            skill_names=skill_names,
        ))

    return result


def _load_identity_from_dir(
    identity_dir: Path,
    _llm_adapter: dict[str, Any] | None = None,
) -> IdentityContext:
    """Load identity from an arbitrary directory (shared logic for root + sub-agents)."""
    persona = _read_text(identity_dir / "persona.md")
    instructions = _read_text(identity_dir / "instructions.md")
    guardrails_path = identity_dir / "guardrails.yaml"
    guardrails = _load_yaml(guardrails_path) if guardrails_path.is_file() else None
    return IdentityContext(persona=persona, instructions=instructions, guardrails=guardrails)


def _load_skills_dir(root: Path, manifest: dict[str, Any]) -> Path | None:
    """Resolve spec.skills to an absolute path if declared, else None."""
    skills_ref = manifest.get("spec", {}).get("skills")
    if not skills_ref:
        return None
    skills_path = (root / skills_ref).resolve()
    if skills_path.is_dir():
        return skills_path
    return None


def _load_service(manifest: dict[str, Any]) -> dict[str, Any] | None:
    """Load spec.runtime.service configuration if present."""
    return (
        manifest.get("spec", {})
        .get("runtime", {})
        .get("service")
    )
