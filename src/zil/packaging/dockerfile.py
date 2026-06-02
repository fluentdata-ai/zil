"""Dockerfile generation for Zil agent projects.

Single source of truth used by:
- ``zil init`` (project scaffolding)
- ``zil web --docker`` (local container runs)
- ``zil deploy`` (Cloud Run deployment)
"""

from __future__ import annotations

from pathlib import Path

import yaml

# Map well-known host dependency names to apt packages (legacy, for host_dependencies list).
HOST_DEP_PACKAGES: dict[str, str] = {
    "nodejs": "nodejs npm",
    "git": "git",
    "docker": "docker.io",
    "curl": "curl",
    "jq": "jq",
    "uv": "pipx && pipx install uv",
}


def _apt_install_block(host_deps: list[str]) -> str:
    """Generate the RUN apt-get line for host dependencies (legacy path)."""
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


def _runtime_deps_block(deps: list[dict]) -> str:
    """Generate ordered Dockerfile RUN stanzas for spec.runtime.dependencies.

    Installation order: apt → apt-nodesource → apt-gh → pip → npm-global
    (npm-global must come after nodejs is installed).
    """
    if not deps:
        return ""

    apt_pkgs: list[str] = []
    nodesource_version: str | None = None
    install_gh: bool = False
    pip_pkgs: list[str] = []
    npm_global_pkgs: list[str] = []

    for dep in deps:
        name = dep.get("name", "")
        dep_type = dep.get("type", "apt")
        version = dep.get("version", "")

        if dep_type == "apt":
            apt_pkgs.append(name)

        elif dep_type == "apt-nodesource":
            nodesource_version = version or "20"

        elif dep_type == "apt-gh":
            install_gh = True

        elif dep_type == "pip":
            pkg = f"{name}=={version}" if version else name
            pip_pkgs.append(pkg)

        elif dep_type == "npm-global":
            pkg = f"{name}@{version}" if version else name
            npm_global_pkgs.append(pkg)

    lines: list[str] = []
    lines.append("\n# Runtime dependencies (from spec.runtime.dependencies)")

    # Base apt packages + curl/gnupg needed for repo setups
    base_apt = list(apt_pkgs)
    if nodesource_version or install_gh:
        base_apt.extend(["curl", "ca-certificates", "gnupg"])
    if base_apt:
        deduped = list(dict.fromkeys(base_apt))  # preserve order, deduplicate
        lines.append(
            f"RUN apt-get update && apt-get install -y --no-install-recommends "
            f"{' '.join(deduped)} && rm -rf /var/lib/apt/lists/*"
        )

    # Node.js via NodeSource
    if nodesource_version:
        lines.append(
            f"RUN curl -fsSL https://deb.nodesource.com/setup_{nodesource_version}.x | bash - "
            f"&& apt-get install -y --no-install-recommends nodejs "
            f"&& rm -rf /var/lib/apt/lists/*"
        )

    # GitHub CLI via official apt repo
    if install_gh:
        lines.append(
            "RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg "
            "| dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \\\n"
            "    && echo \"deb [arch=$(dpkg --print-architecture) "
            "signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] "
            "https://cli.github.com/packages stable main\" "
            "> /etc/apt/sources.list.d/github-cli.list \\\n"
            "    && apt-get update && apt-get install -y --no-install-recommends gh "
            "&& rm -rf /var/lib/apt/lists/*"
        )

    # pip installs
    if pip_pkgs:
        lines.append(
            f"RUN pip install --no-cache-dir {' '.join(pip_pkgs)}"
        )

    # npm global installs (require nodejs to already be present)
    if npm_global_pkgs:
        lines.append(
            f"RUN npm install -g {' '.join(npm_global_pkgs)}"
        )

    return "\n".join(lines) + "\n"


def generate_dockerfile(
    *,
    name: str,
    module_dir: str | None = None,
    host_deps: list[str] | None = None,
    runtime_deps: list[dict] | None = None,
    has_tools_dir: bool = False,
) -> str:
    """Generate a Dockerfile for a Zil agent project.

    This produces the multi-stage build Dockerfile used for both local
    ``zil web --docker`` runs and ``zil init`` scaffolding.

    Args:
        name: Agent name (used in comments only).
        module_dir: Python module directory name.  Not needed for the
            scaffolded template (uses ``COPY . .``).
        host_deps: Legacy system packages from spec.tools.host_dependencies.
        runtime_deps: Structured deps from spec.runtime.dependencies.
        has_tools_dir: Whether a ``tools/`` directory should be expected.
    """
    apt_block = _apt_install_block(host_deps or [])
    rt_block = _runtime_deps_block(runtime_deps or [])

    return f"""\
# Multi-stage build for {name}
FROM python:3.12-slim
WORKDIR /app
{apt_block}{rt_block}
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["adk", "web", ".", "--port", "8000", "--host", "0.0.0.0"]
"""


def generate_deploy_dockerfile(
    *,
    module_dir: str,
    adk_version: str = "1.0.0",
    host_deps: list[str] | None = None,
    runtime_deps: list[dict] | None = None,
    with_ui: bool = False,
    trace: bool = False,
) -> str:
    """Generate a Dockerfile for Cloud Run deployment.

    Unlike the scaffolded Dockerfile, this one is placed in a temp directory
    by ``zil deploy`` alongside an ``agents/{module_dir}/`` copy.

    Args:
        module_dir: Python module directory name.
        adk_version: Pinned google-adk version.
        host_deps: Legacy system packages from spec.tools.host_dependencies.
        runtime_deps: Structured deps from spec.runtime.dependencies.
        with_ui: Whether to start with ``adk web`` (True) or ``adk api_server``.
        trace: Enable ``--trace_to_cloud``.
    """
    # Build dependency blocks (apt-get before USER switch; pip/npm after)
    legacy_apt = _apt_install_block(host_deps or [])
    rt_block = _runtime_deps_block(runtime_deps or [])

    # Wrap system-level installs to run as root, then restore myuser
    pre_user_block = ""
    if legacy_apt or rt_block:
        pre_user_block = f"USER root\n{legacy_apt}{rt_block}USER myuser\n"
    apt_block = pre_user_block  # kept for template variable below

    command = "web" if with_ui else "api_server"  # noqa: E501
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
COPY --chown=myuser:myuser \
  "agents/{module_dir}/requirements.txt" "/app/agents/{module_dir}/requirements.txt"
RUN pip install --no-cache-dir -r "/app/agents/{module_dir}/requirements.txt" 2>/dev/null || true

EXPOSE 8000

CMD adk {command} --port=8000 --host=0.0.0.0{trace_flag} "/app/agents"
"""


def generate_serve_dockerfile(
    *,
    host_deps: list[str] | None = None,
    runtime_deps: list[dict] | None = None,
    framework: str = "adk",
    port: int = 8000,
    local_zil_src: bool = False,
    memory_enabled: bool = False,
) -> str:
    """Generate a Dockerfile for unified deploy using ``zil serve`` as entrypoint.

    This is the framework-agnostic deploy path. The container installs
    the project, then starts ``zil serve`` which handles REST, webhooks,
    and A2A endpoints regardless of framework backend.

    Args:
        host_deps: Legacy system packages from spec.tools.host_dependencies.
        runtime_deps: Structured deps from spec.runtime.dependencies.
        framework: Framework backend name (for optional dep group).
        port: Port to expose (default 8000).
        local_zil_src: If True, install zil from a local ``_zil_src/``
            directory copied into the build context (for development).
            If False, install from PyPI (production default).
        memory_enabled: If True, add the ``memory`` extra so the long-term
            memory provider deps (e.g. ``mem0ai``) are installed.
    """
    apt_block = _apt_install_block(host_deps or [])
    rt_block = _runtime_deps_block(runtime_deps or [])

    # Determine zil extras. ``memory`` is added when the manifest enables a
    # long-term memory adapter so ``mem0ai`` lands in the image.
    extras = ["serve"]
    if framework != "stub":
        extras.append(framework)
    if memory_enabled:
        extras.append("memory")
    extras_suffix = "[" + ",".join(extras) + "]"
    if local_zil_src:
        zil_install = (
            f"# Install zil from local source (dev mode)\n"
            f"COPY _zil_src/ /app/_zil_src/\n"
            f"RUN uv pip install --system --no-cache '/app/_zil_src{extras_suffix}'"
        )
    else:
        zil_install = (
            f"# Install zil with serve + framework extras\n"
            f"RUN uv pip install --system --no-cache zil-ai{extras_suffix}"
        )

    return f"""\
FROM python:3.12-slim
WORKDIR /app

# Create a non-root user
RUN adduser --disabled-password --gecos "" appuser
{apt_block}{rt_block}
# Install uv/uvx for fast dependency resolution and tool running
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY --from=ghcr.io/astral-sh/uv:latest /uvx /usr/local/bin/uvx

# Install project dependencies (as root so we can write to site-packages)
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

{zil_install}

# Switch to non-root user
USER appuser
ENV PATH="/home/appuser/.local/bin:$PATH"

# Copy project files
COPY --chown=appuser:appuser . .

EXPOSE {port}

CMD ["zil", "serve", "--port", "{port}", "--host", "0.0.0.0"]
"""


def read_host_deps(manifest_or_path: dict | Path) -> list[str]:
    """Extract host_dependencies from a manifest dict or file path."""
    if isinstance(manifest_or_path, Path):
        manifest_or_path = yaml.safe_load(manifest_or_path.read_text())
    tools = manifest_or_path.get("spec", {}).get("tools")
    if isinstance(tools, dict):
        return tools.get("host_dependencies", [])
    return []


def read_runtime_deps(manifest_or_path: dict | Path) -> list[dict]:
    """Extract spec.runtime.dependencies from a manifest dict or file path."""
    if isinstance(manifest_or_path, Path):
        manifest_or_path = yaml.safe_load(manifest_or_path.read_text())
    return manifest_or_path.get("spec", {}).get("runtime", {}).get("dependencies", [])


def read_memory_enabled(manifest_or_path: dict | Path) -> bool:
    """Return True if the manifest declares a long-term memory adapter.

    A truthy ``spec.memory`` (path to an adapter file) means the image needs
    the ``memory`` extra so ``mem0ai`` is installed. ``spec.runtime.memory`` is
    accepted as a fallback for older manifests.
    """
    if isinstance(manifest_or_path, Path):
        manifest_or_path = yaml.safe_load(manifest_or_path.read_text())
    spec = manifest_or_path.get("spec", {})
    return bool(spec.get("memory") or spec.get("runtime", {}).get("memory"))


def strip_zil_requirement(requirements_text: str) -> str:
    """Drop any ``zil-ai`` requirement line.

    Used in dev mode: zil is installed from the local source copied into the
    build context, so a PyPI ``zil-ai`` line in ``requirements.txt`` would both
    pull a stale build and miss locally-available extras (e.g. ``memory``).
    """
    kept = [
        line
        for line in requirements_text.splitlines()
        if not line.strip().lower().startswith(("zil-ai", "zil_ai", "zil["))
    ]
    return "\n".join(kept).strip() + ("\n" if kept else "")


def has_tools_dir(project_dir: Path) -> bool:
    """Check if the project has a tools/ directory with content."""
    td = project_dir / "tools"
    return td.is_dir() and any(td.iterdir())
