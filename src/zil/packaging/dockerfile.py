"""Dockerfile generation for Zil agent projects.

Single source of truth used by:
- ``zil init`` (project scaffolding)
- ``zil web --docker`` (local container runs)
- ``zil deploy`` (Cloud Run deployment)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

# Map well-known host dependency names to apt packages.
HOST_DEP_PACKAGES: dict[str, str] = {
    "nodejs": "nodejs npm",
    "git": "git",
    "docker": "docker.io",
    "curl": "curl",
    "jq": "jq",
    "uv": "pipx && pipx install uv",
}


def _apt_install_block(host_deps: list[str]) -> str:
    """Generate the RUN apt-get line for host dependencies."""
    if not host_deps:
        return ""
    packages = []
    for dep in host_deps:
        packages.append(HOST_DEP_PACKAGES.get(dep, dep))
    return (
        "\n# Install host dependencies for external tools\n"
        f"RUN apt-get update && apt-get install -y {' '.join(packages)} "
        "&& rm -rf /var/lib/apt/lists/*\n"
    )


def generate_dockerfile(
    *,
    name: str,
    module_dir: str | None = None,
    host_deps: list[str] | None = None,
    has_tools_dir: bool = False,
) -> str:
    """Generate a Dockerfile for a Zil agent project.

    This produces the multi-stage build Dockerfile used for both local
    ``zil web --docker`` runs and ``zil init`` scaffolding.

    Args:
        name: Agent name (used in comments only).
        module_dir: Python module directory name.  Not needed for the
            scaffolded template (uses ``COPY . .``).
        host_deps: System packages to install (e.g. ``["nodejs"]``).
        has_tools_dir: Whether a ``tools/`` directory should be expected.
    """
    apt_block = _apt_install_block(host_deps or [])

    return f"""\
# Multi-stage build for {name}
# Stage 1: dependencies
FROM python:3.12-slim AS deps
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: runtime
FROM python:3.12-slim
{apt_block}WORKDIR /app
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin/ /usr/local/bin/
COPY . .
EXPOSE 8000
CMD ["adk", "web", ".", "--port", "8000", "--host", "0.0.0.0"]
"""


def generate_deploy_dockerfile(
    *,
    module_dir: str,
    adk_version: str = "1.0.0",
    host_deps: list[str] | None = None,
    with_ui: bool = False,
    trace: bool = False,
) -> str:
    """Generate a Dockerfile for Cloud Run deployment.

    Unlike the scaffolded Dockerfile, this one is placed in a temp directory
    by ``zil deploy`` alongside an ``agents/{module_dir}/`` copy.

    Args:
        module_dir: Python module directory name.
        adk_version: Pinned google-adk version.
        host_deps: System packages to install.
        with_ui: Whether to start with ``adk web`` (True) or ``adk api_server``.
        trace: Enable ``--trace_to_cloud``.
    """
    apt_block = ""
    if host_deps:
        apt_block = _apt_install_block(host_deps)
        # For deploy, apt-get runs before USER switch
        apt_block = f"USER root\n{apt_block}USER myuser\n"

    command = "web" if with_ui else "api_server"
    trace_flag = " --trace_to_cloud" if trace else ""

    return f"""\
FROM python:3.12-slim
WORKDIR /app

# Create a non-root user
RUN adduser --disabled-password --gecos "" myuser

# Install host dependencies (external tools)
{apt_block}
# Switch to the non-root user
USER myuser
ENV PATH="/home/myuser/.local/bin:$PATH"

# Install ADK
RUN pip install google-adk=={adk_version}

# Copy agent
COPY --chown=myuser:myuser "agents/{module_dir}/" "/app/agents/{module_dir}/"

# Install agent deps
COPY --chown=myuser:myuser "agents/{module_dir}/requirements.txt" "/app/agents/{module_dir}/requirements.txt"
RUN pip install --no-cache-dir -r "/app/agents/{module_dir}/requirements.txt" 2>/dev/null || true

EXPOSE 8000

CMD adk {command} --port=8000 --host=0.0.0.0{trace_flag} "/app/agents"
"""


def read_host_deps(manifest_or_path: dict | Path) -> list[str]:
    """Extract host_dependencies from a manifest dict or file path."""
    if isinstance(manifest_or_path, Path):
        manifest_or_path = yaml.safe_load(manifest_or_path.read_text())
    tools = manifest_or_path.get("spec", {}).get("tools")
    if isinstance(tools, dict):
        return tools.get("host_dependencies", [])
    return []


def has_tools_dir(project_dir: Path) -> bool:
    """Check if the project has a tools/ directory with content."""
    td = project_dir / "tools"
    return td.is_dir() and any(td.iterdir())
