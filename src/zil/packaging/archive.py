"""Build and read .zil archives (tar.gz with fixed layout)."""

from __future__ import annotations

import json
import tarfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ArchiveMetadata:
    """Metadata extracted from a .zil archive."""

    name: str
    version: str
    description: str = ""
    framework: str = "adk"
    language: str = "python"
    created_at: str = ""
    archive_size: int = 0
    components: list[str] = field(default_factory=list)
    component_sizes: dict[str, int] = field(default_factory=dict)
    sbom_dependency_count: int = 0
    eval_score: float | None = None
    eval_threshold: float | None = None
    env_var_count: int = 0
    env_secret_count: int = 0
    env_coverage: dict[str, Any] | None = None
    cost_config: dict[str, Any] | None = None
    tools_config: dict[str, Any] | None = None


# Directories and files to include in the archive (relative to project root)
_BUNDLE_DIRS = ["identity", "adapters", "evals", "observability"]
_BUNDLE_FILES = ["manifest.yaml"]

# Default directories/files excluded when bundling tool sources.
# Override or extend via a .bundleignore file in the tool directory.
_DEFAULT_BUNDLE_EXCLUDES = {
    ".git",
    ".github",
    ".env",
    ".env.example",
    "src",
    "tests",
    "docs",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".bundleignore",
}


def _load_bundle_excludes(source_dir: Path) -> set[str]:
    """Load exclusion patterns from .bundleignore or fall back to defaults."""
    ignore_file = source_dir / ".bundleignore"
    if ignore_file.is_file():
        extras = {
            line.strip()
            for line in ignore_file.read_text().splitlines()
            if line.strip() and not line.startswith("#")
        }
        return _DEFAULT_BUNDLE_EXCLUDES | extras
    return _DEFAULT_BUNDLE_EXCLUDES


def _is_excluded(rel_path: Path, excludes: set[str]) -> bool:
    """Check if a relative path starts with an excluded top-level entry."""
    return rel_path.parts[0] in excludes if rel_path.parts else False


def build_archive(
    project_dir: Path,
    output_dir: Path,
    sbom: dict[str, Any] | None = None,
    eval_results: dict[str, Any] | None = None,
    env_coverage: dict[str, Any] | None = None,
) -> Path:
    """Build a .zil archive from a project directory.

    Returns the path to the created archive.
    """
    manifest_path = project_dir / "manifest.yaml"
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest.yaml not found in {project_dir}")

    manifest = yaml.safe_load(manifest_path.read_text())
    name = manifest["metadata"]["name"]
    version = manifest["metadata"]["version"]

    # Determine the module directory (agent code)
    module_name = name.replace("-", "_")
    module_dir = project_dir / module_name

    output_dir.mkdir(parents=True, exist_ok=True)
    archive_name = f"{name}-{version}.zil"
    archive_path = output_dir / archive_name

    with tarfile.open(archive_path, "w:gz") as tar:
        # Add manifest.yaml
        tar.add(manifest_path, arcname="manifest.yaml")

        # Add standard directories
        for dir_name in _BUNDLE_DIRS:
            dir_path = project_dir / dir_name
            if dir_path.is_dir():
                for file_path in sorted(dir_path.rglob("*")):
                    if file_path.is_file():
                        arcname = str(file_path.relative_to(project_dir))
                        tar.add(file_path, arcname=arcname)

        # Add module directory (agent code)
        if module_dir.is_dir():
            for file_path in sorted(module_dir.rglob("*")):
                if file_path.is_file() and "__pycache__" not in str(file_path):
                    arcname = str(file_path.relative_to(project_dir))
                    tar.add(file_path, arcname=arcname)

        # Add MCP server sources (tools/{name}/)
        spec = manifest.get("spec", {})
        tools_config = spec.get("tools")
        if isinstance(tools_config, dict):
            mcp_servers = tools_config.get("mcp_servers", [])
            for server in mcp_servers:
                source = server.get("source")
                if not source:
                    continue
                server_name = server["name"]
                source_path = (project_dir / source).resolve()
                if not source_path.is_dir():
                    continue
                excludes = _load_bundle_excludes(source_path)
                for file_path in sorted(source_path.rglob("*")):
                    if file_path.is_file() or file_path.is_symlink():
                        rel = file_path.relative_to(source_path)
                        if _is_excluded(rel, excludes):
                            continue
                        arcname = f"tools/{server_name}/{rel}"
                        tar.add(
                            file_path, arcname=arcname, recursive=False,
                        )

        # Add SBOM
        if sbom:
            sbom_json = json.dumps(sbom, indent=2).encode()
            _add_bytes_to_tar(tar, "SBOM.cyclonedx.json", sbom_json)

        # Add eval results
        if eval_results:
            results_json = json.dumps(eval_results, indent=2).encode()
            _add_bytes_to_tar(tar, "EVAL_RESULTS.json", results_json)

        # Add build metadata
        build_meta: dict[str, Any] = {
            "name": name,
            "version": version,
            "created_at": datetime.now(UTC).isoformat(),
            "builder": "zil-ai",
        }
        if env_coverage:
            build_meta["env_coverage"] = env_coverage
        meta_json = json.dumps(build_meta, indent=2).encode()
        _add_bytes_to_tar(tar, "BUILD_META.json", meta_json)

    return archive_path


def read_archive(archive_path: Path) -> ArchiveMetadata:
    """Read a .zil archive and extract metadata without fully extracting."""
    if not archive_path.exists():
        raise FileNotFoundError(f"Archive not found: {archive_path}")

    archive_size = archive_path.stat().st_size

    with tarfile.open(archive_path, "r:gz") as tar:
        # Extract manifest
        manifest_member = tar.getmember("manifest.yaml")
        manifest_file = tar.extractfile(manifest_member)
        if manifest_file is None:
            raise ValueError("Cannot read manifest.yaml from archive")
        manifest = yaml.safe_load(manifest_file.read())

        name = manifest["metadata"]["name"]
        version = manifest["metadata"]["version"]
        description = manifest["metadata"].get("description", "")
        framework = manifest.get("spec", {}).get("runtime", {}).get("framework", "adk")
        language = manifest.get("spec", {}).get("runtime", {}).get("language", "python")

        # Gather component info
        components: list[str] = []
        component_sizes: dict[str, int] = {}
        for member in tar.getmembers():
            if member.isfile():
                top_level = member.name.split("/")[0]
                if top_level not in components:
                    components.append(top_level)
                component_sizes[member.name] = member.size

        # Read build metadata
        created_at = ""
        env_coverage = None
        try:
            meta_member = tar.getmember("BUILD_META.json")
            meta_file = tar.extractfile(meta_member)
            if meta_file:
                build_meta = json.loads(meta_file.read())
                created_at = build_meta.get("created_at", "")
                env_coverage = build_meta.get("env_coverage")
        except KeyError:
            pass

        # Read SBOM
        sbom_dep_count = 0
        try:
            sbom_member = tar.getmember("SBOM.cyclonedx.json")
            sbom_file = tar.extractfile(sbom_member)
            if sbom_file:
                sbom = json.loads(sbom_file.read())
                sbom_dep_count = len(sbom.get("components", []))
        except KeyError:
            pass

        # Read eval results
        eval_score = None
        eval_threshold = None
        try:
            eval_member = tar.getmember("EVAL_RESULTS.json")
            eval_file = tar.extractfile(eval_member)
            if eval_file:
                eval_data = json.loads(eval_file.read())
                eval_score = eval_data.get("score")
                eval_threshold = eval_data.get("threshold")
        except KeyError:
            pass

        # Read env declarations
        env_declarations = manifest.get("spec", {}).get("env", [])
        env_var_count = len(env_declarations)
        env_secret_count = sum(1 for e in env_declarations if e.get("secret"))

        # Read cost config
        cost_config = manifest.get("spec", {}).get("cost")

        # Read tools config
        tools_ref = manifest.get("spec", {}).get("tools")
        tools_config = tools_ref if isinstance(tools_ref, dict) else None

    return ArchiveMetadata(
        name=name,
        version=version,
        description=description,
        framework=framework,
        language=language,
        created_at=created_at,
        archive_size=archive_size,
        components=components,
        component_sizes=component_sizes,
        sbom_dependency_count=sbom_dep_count,
        eval_score=eval_score,
        eval_threshold=eval_threshold,
        env_var_count=env_var_count,
        env_secret_count=env_secret_count,
        env_coverage=env_coverage,
        cost_config=cost_config,
        tools_config=tools_config,
    )


def extract_archive(archive_path: Path, target_dir: Path) -> Path:
    """Extract a .zil archive to a target directory. Returns the extraction path."""
    if not archive_path.exists():
        raise FileNotFoundError(f"Archive not found: {archive_path}")

    target_dir.mkdir(parents=True, exist_ok=True)

    with tarfile.open(archive_path, "r:gz") as tar:
        tar.extractall(path=target_dir, filter="data")

    return target_dir


def _add_bytes_to_tar(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    """Add raw bytes as a file to a tar archive."""
    import io

    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    tar.addfile(info, io.BytesIO(data))
