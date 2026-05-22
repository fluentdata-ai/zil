"""Tests for spec.runtime.dependencies — Dockerfile generation and validation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def base_manifest() -> dict:
    return {
        "apiVersion": "zil/v1",
        "kind": "Agent",
        "metadata": {"name": "test-agent", "version": "0.1.0"},
        "spec": {
            "runtime": {
                "framework": "adk",
                "language": "python",
                "llm": {"adapter": "./adapters/llm.yaml"},
            },
            "identity": "./identity",
        },
    }


@pytest.fixture()
def zil_project(tmp_path: Path, base_manifest: dict) -> Path:
    """Minimal Zil project with adapters and identity."""
    (tmp_path / "manifest.yaml").write_text(yaml.dump(base_manifest))
    adapters = tmp_path / "adapters"
    adapters.mkdir()
    (adapters / "llm.yaml").write_text(
        yaml.dump({"provider": "gemini", "model": "gemini-2.0-flash"})
    )
    identity = tmp_path / "identity"
    identity.mkdir()
    (identity / "persona.md").write_text("# Agent\n")
    (identity / "instructions.md").write_text("# Instructions\n")
    return tmp_path


# ---------------------------------------------------------------------------
# _runtime_deps_block — unit tests
# ---------------------------------------------------------------------------


class TestRuntimeDepsBlock:
    def _block(self, deps: list[dict]) -> str:
        from zil.packaging.dockerfile import _runtime_deps_block
        return _runtime_deps_block(deps)

    def test_empty_returns_empty_string(self) -> None:
        assert self._block([]) == ""

    def test_apt_type(self) -> None:
        block = self._block([{"name": "git", "type": "apt"}])
        assert "apt-get install" in block
        assert "git" in block
        assert "# Runtime dependencies" in block

    def test_apt_nodesource_installs_nodejs(self) -> None:
        block = self._block([{"name": "nodejs", "type": "apt-nodesource", "version": "20"}])
        assert "nodesource.com/setup_20.x" in block
        assert "nodejs" in block
        assert "curl" in block  # pulled in automatically

    def test_apt_nodesource_defaults_to_20(self) -> None:
        block = self._block([{"name": "nodejs", "type": "apt-nodesource"}])
        assert "setup_20.x" in block

    def test_apt_gh_installs_gh_cli(self) -> None:
        block = self._block([{"name": "gh", "type": "apt-gh"}])
        assert "cli.github.com" in block
        assert "gh" in block
        assert "curl" in block  # pulled in automatically

    def test_pip_type_no_version(self) -> None:
        block = self._block([{"name": "uv", "type": "pip"}])
        assert "pip install --no-cache-dir uv" in block
        assert "uv==" not in block

    def test_pip_type_with_version(self) -> None:
        block = self._block([{"name": "uv", "type": "pip", "version": "0.5.1"}])
        assert "uv==0.5.1" in block

    def test_npm_global_type(self) -> None:
        block = self._block([{"name": "pnpm", "type": "npm-global"}])
        assert "npm install -g pnpm" in block

    def test_npm_global_with_version(self) -> None:
        block = self._block([{"name": "pnpm", "type": "npm-global", "version": "9"}])
        assert "pnpm@9" in block

    def test_npm_global_multiple_batched(self) -> None:
        block = self._block([
            {"name": "pnpm", "type": "npm-global"},
            {"name": "turbo", "type": "npm-global"},
        ])
        assert "npm install -g" in block
        assert "pnpm" in block
        assert "turbo" in block
        assert block.count("npm install -g") == 1  # batched into one RUN

    def test_ordering_apt_before_npm_global(self) -> None:
        block = self._block([
            {"name": "pnpm", "type": "npm-global"},
            {"name": "nodejs", "type": "apt-nodesource", "version": "20"},
        ])
        nodesource_pos = block.index("nodesource.com")
        npm_pos = block.index("npm install -g")
        assert nodesource_pos < npm_pos  # Node must be installed before npm -g

    def test_curl_deduped_when_both_nodesource_and_gh(self) -> None:
        block = self._block([
            {"name": "nodejs", "type": "apt-nodesource", "version": "20"},
            {"name": "gh", "type": "apt-gh"},
        ])
        # curl, ca-certificates, gnupg should appear only once in the base apt block
        assert block.count("curl ca-certificates gnupg") == 1

    def test_full_svt_deps(self) -> None:
        deps = [
            {"name": "git", "type": "apt"},
            {"name": "nodejs", "type": "apt-nodesource", "version": "20"},
            {"name": "pnpm", "type": "npm-global"},
            {"name": "turbo", "type": "npm-global"},
            {"name": "gh", "type": "apt-gh"},
            {"name": "uv", "type": "pip"},
        ]
        block = self._block(deps)
        assert "git" in block
        assert "nodesource.com/setup_20.x" in block
        assert "cli.github.com" in block
        assert "pip install --no-cache-dir uv" in block
        assert "npm install -g pnpm turbo" in block


# ---------------------------------------------------------------------------
# generate_dockerfile — integration with runtime_deps
# ---------------------------------------------------------------------------


class TestGenerateDockerfile:
    def test_no_deps_produces_minimal_dockerfile(self) -> None:
        from zil.packaging.dockerfile import generate_dockerfile

        df = generate_dockerfile(name="test-agent")
        assert "FROM python:3.12-slim" in df
        assert "COPY requirements.txt" in df
        assert "EXPOSE 8000" in df
        assert "Runtime dependencies" not in df

    def test_runtime_deps_injected_before_requirements(self) -> None:
        from zil.packaging.dockerfile import generate_dockerfile

        deps = [{"name": "git", "type": "apt"}]
        df = generate_dockerfile(name="test-agent", runtime_deps=deps)
        rt_pos = df.index("Runtime dependencies")
        req_pos = df.index("COPY requirements.txt")
        assert rt_pos < req_pos  # deps installed before Python packages

    def test_host_deps_and_runtime_deps_combined(self) -> None:
        from zil.packaging.dockerfile import generate_dockerfile

        df = generate_dockerfile(
            name="test-agent",
            host_deps=["jq"],
            runtime_deps=[{"name": "git", "type": "apt"}],
        )
        assert "jq" in df
        assert "git" in df

    def test_dockerfile_is_valid_syntax(self) -> None:
        from zil.packaging.dockerfile import generate_dockerfile

        deps = [
            {"name": "git", "type": "apt"},
            {"name": "nodejs", "type": "apt-nodesource", "version": "20"},
            {"name": "pnpm", "type": "npm-global"},
            {"name": "gh", "type": "apt-gh"},
            {"name": "uv", "type": "pip"},
        ]
        df = generate_dockerfile(name="test-agent", runtime_deps=deps)
        lines = df.splitlines()
        assert lines[0].startswith("# ")  # comment
        assert any(line.startswith("FROM ") for line in lines)
        assert any(line.startswith("WORKDIR ") for line in lines)
        assert any(line.startswith("CMD ") for line in lines)


# ---------------------------------------------------------------------------
# read_runtime_deps — manifest parsing helper
# ---------------------------------------------------------------------------


class TestReadRuntimeDeps:
    def test_returns_empty_when_no_dependencies(self, base_manifest: dict) -> None:
        from zil.packaging.dockerfile import read_runtime_deps

        assert read_runtime_deps(base_manifest) == []

    def test_reads_dependencies_from_dict(self, base_manifest: dict) -> None:
        from zil.packaging.dockerfile import read_runtime_deps

        base_manifest["spec"]["runtime"]["dependencies"] = [
            {"name": "git", "type": "apt"},
            {"name": "nodejs", "type": "apt-nodesource", "version": "20"},
        ]
        deps = read_runtime_deps(base_manifest)
        assert len(deps) == 2
        assert deps[0] == {"name": "git", "type": "apt"}
        assert deps[1]["version"] == "20"

    def test_reads_from_path(self, tmp_path: Path, base_manifest: dict) -> None:
        from zil.packaging.dockerfile import read_runtime_deps

        base_manifest["spec"]["runtime"]["dependencies"] = [
            {"name": "uv", "type": "pip"},
        ]
        manifest_path = tmp_path / "manifest.yaml"
        manifest_path.write_text(yaml.dump(base_manifest))
        deps = read_runtime_deps(manifest_path)
        assert len(deps) == 1
        assert deps[0]["name"] == "uv"


# ---------------------------------------------------------------------------
# ProjectContext.runtime_deps — loader integration
# ---------------------------------------------------------------------------


class TestProjectContextRuntimeDeps:
    def test_runtime_deps_empty_by_default(self, zil_project: Path) -> None:
        from zil.sdk.loader import load_project

        ctx = load_project(zil_project)
        assert ctx.runtime_deps == []

    def test_runtime_deps_loaded_from_manifest(self, zil_project: Path) -> None:
        from zil.sdk.loader import load_project

        manifest_path = zil_project / "manifest.yaml"
        manifest = yaml.safe_load(manifest_path.read_text())
        manifest["spec"]["runtime"]["dependencies"] = [
            {"name": "git", "type": "apt"},
            {"name": "nodejs", "type": "apt-nodesource", "version": "20"},
            {"name": "pnpm", "type": "npm-global"},
        ]
        manifest_path.write_text(yaml.dump(manifest))

        ctx = load_project(zil_project)
        assert len(ctx.runtime_deps) == 3
        names = [d["name"] for d in ctx.runtime_deps]
        assert "git" in names
        assert "nodejs" in names
        assert "pnpm" in names

    def test_runtime_deps_types_preserved(self, zil_project: Path) -> None:
        from zil.sdk.loader import load_project

        manifest_path = zil_project / "manifest.yaml"
        manifest = yaml.safe_load(manifest_path.read_text())
        manifest["spec"]["runtime"]["dependencies"] = [
            {"name": "uv", "type": "pip", "version": "0.5.0"},
        ]
        manifest_path.write_text(yaml.dump(manifest))

        ctx = load_project(zil_project)
        assert ctx.runtime_deps[0]["type"] == "pip"
        assert ctx.runtime_deps[0]["version"] == "0.5.0"


# ---------------------------------------------------------------------------
# _check_runtime_deps — schema validation
# ---------------------------------------------------------------------------


class TestCheckRuntimeDeps:
    def _validate(self, project_dir: Path) -> object:
        from zil.schema.loader import validate_project
        return validate_project(project_dir)

    def test_no_deps_produces_no_runtime_check(self, zil_project: Path) -> None:
        result = self._validate(zil_project)
        messages = [c.message for c in result.checks]
        assert not any("runtime.dependencies" in m for m in messages)

    def test_valid_deps_produces_pass(self, zil_project: Path) -> None:
        manifest_path = zil_project / "manifest.yaml"
        manifest = yaml.safe_load(manifest_path.read_text())
        manifest["spec"]["runtime"]["dependencies"] = [
            {"name": "git", "type": "apt"},
            {"name": "nodejs", "type": "apt-nodesource", "version": "20"},
        ]
        manifest_path.write_text(yaml.dump(manifest))

        result = self._validate(zil_project)
        passes = [c for c in result.checks if c.status == "pass" and "runtime.dependencies" in c.message]
        assert len(passes) == 1
        assert "git" in passes[0].message
        assert "nodejs" in passes[0].message

    def test_unknown_type_produces_warn(self, zil_project: Path) -> None:
        manifest_path = zil_project / "manifest.yaml"
        manifest = yaml.safe_load(manifest_path.read_text())
        manifest["spec"]["runtime"]["dependencies"] = [
            {"name": "mytool", "type": "brew"},  # invalid type
        ]
        manifest_path.write_text(yaml.dump(manifest))

        result = self._validate(zil_project)
        warns = [c for c in result.checks if c.status == "warn" and "unknown type" in c.message]
        assert len(warns) == 1
        assert "brew" in warns[0].message

    def test_npm_global_without_nodejs_produces_warn(self, zil_project: Path) -> None:
        manifest_path = zil_project / "manifest.yaml"
        manifest = yaml.safe_load(manifest_path.read_text())
        manifest["spec"]["runtime"]["dependencies"] = [
            {"name": "pnpm", "type": "npm-global"},  # no apt-nodesource
        ]
        manifest_path.write_text(yaml.dump(manifest))

        result = self._validate(zil_project)
        warns = [c for c in result.checks if c.status == "warn" and "apt-nodesource" in c.message]
        assert len(warns) == 1

    def test_npm_global_with_nodejs_no_warn(self, zil_project: Path) -> None:
        manifest_path = zil_project / "manifest.yaml"
        manifest = yaml.safe_load(manifest_path.read_text())
        manifest["spec"]["runtime"]["dependencies"] = [
            {"name": "nodejs", "type": "apt-nodesource", "version": "20"},
            {"name": "pnpm", "type": "npm-global"},
        ]
        manifest_path.write_text(yaml.dump(manifest))

        result = self._validate(zil_project)
        apt_warns = [
            c for c in result.checks
            if c.status == "warn" and "apt-nodesource" in c.message
        ]
        assert len(apt_warns) == 0
