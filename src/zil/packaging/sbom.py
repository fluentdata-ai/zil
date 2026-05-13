"""Generate CycloneDX SBOM from project dependencies."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def generate_sbom(project_dir: Path, name: str, version: str) -> dict[str, Any]:
    """Generate a CycloneDX 1.5 SBOM from requirements.txt files.

    Scans for requirements.txt in the project root and module directory.
    Returns a CycloneDX JSON-compatible dict.
    """
    components: list[dict[str, Any]] = []
    seen: set[str] = set()

    # Look for requirements files in project root and module dir
    module_name = name.replace("-", "_")
    req_paths = [
        project_dir / "requirements.txt",
        project_dir / module_name / "requirements.txt",
    ]

    for req_path in req_paths:
        if req_path.is_file():
            deps = _parse_requirements(req_path)
            for dep_name, dep_version in deps:
                key = dep_name.lower()
                if key not in seen:
                    seen.add(key)
                    component: dict[str, Any] = {
                        "type": "library",
                        "name": dep_name,
                        "purl": f"pkg:pypi/{dep_name.lower()}",
                    }
                    if dep_version:
                        component["version"] = dep_version
                        component["purl"] += f"@{dep_version}"
                    components.append(component)

    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(UTC).isoformat(),
            "component": {
                "type": "application",
                "name": name,
                "version": version,
            },
            "tools": [{"name": "zil-ai", "vendor": "FluentData"}],
        },
        "components": components,
    }


def _parse_requirements(path: Path) -> list[tuple[str, str]]:
    """Parse a requirements.txt file into (name, version) tuples."""
    deps: list[tuple[str, str]] = []

    for line in path.read_text().splitlines():
        line = line.strip()
        # Skip comments and empty lines
        if not line or line.startswith("#") or line.startswith("-"):
            continue

        # Handle extras like zil-ai[adk]
        # Match: package[extras]==version or package>=version etc.
        match = re.match(
            r"^([a-zA-Z0-9_.-]+(?:\[[a-zA-Z0-9_,.-]+\])?)\s*([><=!~]+\s*[\d.]+)?",
            line,
        )
        if match:
            pkg_name = match.group(1).split("[")[0]  # strip extras
            version_spec = match.group(2) or ""
            # Extract just the version number
            version = re.sub(r"[><=!~\s]+", "", version_spec)
            deps.append((pkg_name, version))

    return deps
