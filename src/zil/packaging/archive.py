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
    memory_binding: dict[str, Any] | None = None


# Directories and files to include in the archive (relative to project root)
_BUNDLE_DIRS = ["identity", "adapters", "evals", "observability", "skills"]
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


def _load_memory_config(project_dir: Path, manifest: dict[str, Any]):
    """Load the parsed MemoryConfig for a project, or None if not configured."""
    mem_ref = manifest.get("spec", {}).get("memory")
    if not mem_ref:
        return None, None
    candidate = project_dir / mem_ref
    if candidate.is_dir():
        candidate = candidate / "memory.yaml"
    if not candidate.is_file():
        return None, None
    try:
        from zil.sdk.memory.config import MemoryConfig

        cfg = MemoryConfig.from_dict(yaml.safe_load(candidate.read_text()) or {})
    except (yaml.YAMLError, ValueError, ImportError):
        return None, None
    return cfg, candidate


def gather_memory_seed(
    project_dir: Path,
    manifest: dict[str, Any],
    *,
    exported_entries: list[dict[str, Any]] | None = None,
    pii_mode: str = "drop",
):
    """Assemble the packable AGENT-scope seed (authored + optional live export).

    Returns ``(SeedSet | None, FilterResult | None)``. Entries are deduplicated
    by content hash and PII-filtered (default: drop offending entries). Never
    includes SESSION/USER scope. The authored ``seed.yaml`` is *never* bundled
    raw — only the filtered, normalized result ships.
    """
    from zil.sdk.memory import pii
    from zil.sdk.memory.config import MemoryConfig  # noqa: F401
    from zil.sdk.memory.seed import (
        SeedSet,
        entry_hash,
        load_seed_file,
    )

    cfg, adapter_path = _load_memory_config(project_dir, manifest)
    if cfg is None:
        if not exported_entries:
            return None, None
        namespace = None
    else:
        namespace = cfg.namespace

    entries: list[dict[str, Any]] = []

    # 1) authored seed file (resolved relative to the memory adapter)
    if cfg is not None and cfg.seed and cfg.seed.get("file") and adapter_path:
        seed_file = (adapter_path.parent / cfg.seed["file"]).resolve()
        authored = load_seed_file(seed_file)
        entries.extend(authored.entries)
        if authored.namespace:
            namespace = authored.namespace

    # 2) live-exported entries (already normalized by the caller)
    if exported_entries:
        entries.extend(exported_entries)

    if not entries:
        return None, None

    # Dedup by content hash, preserving first occurrence.
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for entry in entries:
        h = entry_hash(str(entry.get("content", "")), entry.get("metadata"))
        if h in seen:
            continue
        seen.add(h)
        deduped.append(entry)

    # PII filter (drop offending entries by default).
    result = pii.filter_entries(deduped, mode=pii_mode)  # type: ignore[arg-type]
    seed = SeedSet(entries=result.kept, namespace=namespace)
    return seed, result


def _memory_binding(project_dir: Path, manifest: dict[str, Any]) -> dict[str, Any] | None:
    """Return a sanitized memory binding summary for provenance.

    Records *configuration only* — provider, mode, scopes, namespace,
    retention, and PII policy. Never includes memory *data* or secrets
    (auth is env-referenced and resolved at runtime, not packaged).
    """
    mem_ref = manifest.get("spec", {}).get("memory")
    if not mem_ref:
        return None
    candidate = project_dir / mem_ref
    if candidate.is_dir():
        candidate = candidate / "memory.yaml"
    if not candidate.is_file():
        return None
    try:
        cfg = yaml.safe_load(candidate.read_text()) or {}
    except yaml.YAMLError:
        return None
    persist = cfg.get("persist") or {}
    return {
        "provider": cfg.get("provider"),
        "mode": cfg.get("mode", "managed"),
        "namespace": cfg.get("namespace"),
        "scopes": cfg.get("scopes") or [],
        "retention": cfg.get("retention") or {},
        "exclude_pii": bool(persist.get("exclude_pii", False)),
        "has_substrate": cfg.get("substrate") is not None,
    }


def build_archive(
    project_dir: Path,
    output_dir: Path,
    sbom: dict[str, Any] | None = None,
    eval_results: dict[str, Any] | None = None,
    env_coverage: dict[str, Any] | None = None,
    memory_seed: Any | None = None,
) -> Path:
    """Build a .zil archive from a project directory.

    If ``memory_seed`` (a ``SeedSet``) is not provided, the authored seed (if
    any) is gathered and PII-filtered automatically so direct callers still
    ship pre-seeded knowledge. Returns the path to the created archive.
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
        # Memory binding (config only — no data, no secrets) for provenance.
        memory_binding = _memory_binding(project_dir, manifest)

        # Packable memory seed (AGENT-scope knowledge; PII-filtered).
        if memory_seed is None:
            memory_seed, _ = gather_memory_seed(project_dir, manifest)
        if memory_seed is not None and len(memory_seed) > 0:
            from zil.sdk.memory.seed import SEED_ARCHIVE_PATH, dump_seed_jsonl

            _add_bytes_to_tar(tar, SEED_ARCHIVE_PATH, dump_seed_jsonl(memory_seed))
            seed_summary = {
                "digest": memory_seed.digest,
                "count": len(memory_seed),
                "scopes": ["agent"],
                "namespace": memory_seed.namespace,
                "pii_filtered": True,
            }
            memory_binding = dict(memory_binding or {})
            memory_binding["seed"] = seed_summary

        if memory_binding:
            build_meta["memory"] = memory_binding
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
        memory_binding = None
        try:
            meta_member = tar.getmember("BUILD_META.json")
            meta_file = tar.extractfile(meta_member)
            if meta_file:
                build_meta = json.loads(meta_file.read())
                created_at = build_meta.get("created_at", "")
                env_coverage = build_meta.get("env_coverage")
                memory_binding = build_meta.get("memory")
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
        memory_binding=memory_binding,
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
    import time

    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    info.mtime = int(time.time())
    tar.addfile(info, io.BytesIO(data))
