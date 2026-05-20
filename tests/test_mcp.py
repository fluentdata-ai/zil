"""Tests for MCP server integration (v0.1.13).

Covers: manifest schema validation, SDK loader, env ref resolution,
validation checks, audit checks, init scaffolding, and inspect display.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import jsonschema
import pytest
import yaml
from click.testing import CliRunner

from zil.cli import cli
from zil.schema.loader import load_schema, validate_project
from zil.sdk.mcp import _resolve_env_refs, _resolve_env_refs_in_list

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_manifest(**spec_overrides) -> dict:
    """Return a valid base manifest with optional spec overrides."""
    spec = {
        "runtime": {
            "framework": "adk",
            "language": "python",
            "llm": {"adapter": "./adapters/llm.yaml"},
        },
        "identity": "./identity",
        **spec_overrides,
    }
    return {
        "apiVersion": "zil/v1",
        "kind": "Agent",
        "metadata": {"name": "test-agent", "version": "1.0.0"},
        "spec": spec,
    }


def _write_project(tmp_path: Path, manifest: dict, *, create_identity: bool = True) -> Path:
    """Write a minimal project structure and return the project dir."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "manifest.yaml").write_text(yaml.dump(manifest))

    if create_identity:
        identity = project_dir / "identity"
        identity.mkdir()
        (identity / "persona.md").write_text("# Persona")
        (identity / "instructions.md").write_text("# Instructions")
        (identity / "guardrails.yaml").write_text(yaml.dump({"detection": {"prompt_injection": True}}))

    adapters = project_dir / "adapters"
    adapters.mkdir()
    (adapters / "llm.yaml").write_text(yaml.dump({"provider": "gemini", "model": "gemini-2.0-flash"}))
    (adapters / "embed.yaml").write_text(yaml.dump({"provider": "gemini", "model": "text-embedding-004"}))

    return project_dir


# ===========================================================================
# 1. Schema validation
# ===========================================================================

class TestSchemaTools:
    """spec.tools schema validation."""

    def test_inline_tools_object_valid(self):
        schema = load_schema()
        manifest = _base_manifest(tools={
            "mcp_servers": [
                {"name": "git", "transport": "stdio", "command": "uvx", "args": ["mcp-server-git"]},
            ],
            "host_dependencies": ["git"],
        })
        jsonschema.validate(instance=manifest, schema=schema)

    def test_tools_string_path_valid(self):
        schema = load_schema()
        manifest = _base_manifest(tools="./tools")
        jsonschema.validate(instance=manifest, schema=schema)

    def test_mcp_server_sse_valid(self):
        schema = load_schema()
        manifest = _base_manifest(tools={
            "mcp_servers": [
                {"name": "postgres", "transport": "sse", "url": "http://localhost:3000/mcp"},
            ],
        })
        jsonschema.validate(instance=manifest, schema=schema)

    def test_mcp_server_with_all_fields(self):
        schema = load_schema()
        manifest = _base_manifest(tools={
            "mcp_servers": [{
                "name": "filesystem",
                "transport": "stdio",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                "env": {"WORKSPACE": "/tmp"},
                "tool_filter": ["read_file", "list_directory"],
                "timeout": 15,
            }],
        })
        jsonschema.validate(instance=manifest, schema=schema)

    def test_mcp_server_invalid_name_rejected(self):
        schema = load_schema()
        manifest = _base_manifest(tools={
            "mcp_servers": [
                {"name": "INVALID", "transport": "stdio"},
            ],
        })
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=manifest, schema=schema)

    def test_mcp_server_invalid_transport_rejected(self):
        schema = load_schema()
        manifest = _base_manifest(tools={
            "mcp_servers": [
                {"name": "test", "transport": "websocket"},
            ],
        })
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=manifest, schema=schema)

    def test_mcp_server_missing_transport_rejected(self):
        schema = load_schema()
        manifest = _base_manifest(tools={
            "mcp_servers": [
                {"name": "test"},
            ],
        })
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=manifest, schema=schema)

    def test_tools_empty_object_valid(self):
        schema = load_schema()
        manifest = _base_manifest(tools={})
        jsonschema.validate(instance=manifest, schema=schema)


# ===========================================================================
# 2. SDK loader — tools_config
# ===========================================================================

class TestLoaderTools:
    """ProjectContext.tools_config loading."""

    def test_inline_tools_loaded(self, tmp_path):
        from zil.sdk.loader import load_project

        manifest = _base_manifest(tools={
            "mcp_servers": [{"name": "git", "transport": "stdio", "command": "uvx"}],
        })
        project_dir = _write_project(tmp_path, manifest)
        ctx = load_project(project_dir)

        assert ctx.tools_config is not None
        assert len(ctx.tools_config["mcp_servers"]) == 1
        assert ctx.tools_config["mcp_servers"][0]["name"] == "git"

    def test_no_tools_returns_none(self, tmp_path):
        from zil.sdk.loader import load_project

        manifest = _base_manifest()
        project_dir = _write_project(tmp_path, manifest)
        ctx = load_project(project_dir)

        assert ctx.tools_config is None

    def test_tools_path_loads_config_yaml(self, tmp_path):
        from zil.sdk.loader import load_project

        manifest = _base_manifest(tools="./tools")
        project_dir = _write_project(tmp_path, manifest)

        tools_dir = project_dir / "tools"
        tools_dir.mkdir()
        (tools_dir / "config.yaml").write_text(yaml.dump({
            "mcp_servers": [{"name": "fs", "transport": "stdio", "command": "npx"}],
            "host_dependencies": ["nodejs"],
        }))

        ctx = load_project(project_dir)
        assert ctx.tools_config is not None
        assert ctx.tools_config["host_dependencies"] == ["nodejs"]

    def test_tools_path_missing_config_returns_none(self, tmp_path):
        from zil.sdk.loader import load_project

        manifest = _base_manifest(tools="./tools")
        project_dir = _write_project(tmp_path, manifest)
        # Don't create the tools directory

        ctx = load_project(project_dir)
        assert ctx.tools_config is None


# ===========================================================================
# 3. MCP adapter — env ref resolution
# ===========================================================================

class TestEnvRefResolution:
    """Environment variable reference resolution in MCP config."""

    def test_resolve_simple_var(self):
        with patch.dict(os.environ, {"MY_VAR": "/workspace"}):
            assert _resolve_env_refs("${MY_VAR}") == "/workspace"

    def test_resolve_multiple_vars(self):
        with patch.dict(os.environ, {"A": "x", "B": "y"}):
            assert _resolve_env_refs("${A}/${B}") == "x/y"

    def test_unset_var_left_as_is(self):
        env = {k: v for k, v in os.environ.items() if k != "NONEXISTENT_VAR_123"}
        with patch.dict(os.environ, env, clear=True):
            assert _resolve_env_refs("${NONEXISTENT_VAR_123}") == "${NONEXISTENT_VAR_123}"

    def test_resolve_in_list(self):
        with patch.dict(os.environ, {"REPO": "/repo"}):
            result = _resolve_env_refs_in_list(["--repo", "${REPO}"])
            assert result == ["--repo", "/repo"]

    def test_no_vars_passes_through(self):
        assert _resolve_env_refs("no vars here") == "no vars here"


# ===========================================================================
# 4. Validation — _check_tools
# ===========================================================================

class TestValidateTools:
    """zil validate checks for tools/MCP config."""

    def test_validate_with_tools_passes(self, tmp_path):
        manifest = _base_manifest(tools={
            "mcp_servers": [
                {"name": "git", "transport": "stdio", "command": "uvx",
                 "tool_filter": ["git_log"]},
            ],
            "host_dependencies": ["git"],
        })
        project_dir = _write_project(tmp_path, manifest)
        result = validate_project(project_dir)
        tool_checks = [c for c in result.checks if "spec.tools" in c.message or "MCP" in c.message]
        assert any(c.status == "pass" for c in tool_checks)

    def test_validate_warns_no_tool_filter(self, tmp_path):
        manifest = _base_manifest(tools={
            "mcp_servers": [
                {"name": "git", "transport": "stdio", "command": "uvx"},
            ],
        })
        project_dir = _write_project(tmp_path, manifest)
        result = validate_project(project_dir)
        tool_checks = [c for c in result.checks if "tool_filter" in c.message]
        assert any(c.status == "warn" for c in tool_checks)

    def test_validate_fails_stdio_no_command(self, tmp_path):
        manifest = _base_manifest(tools={
            "mcp_servers": [
                {"name": "bad", "transport": "stdio"},
            ],
        })
        project_dir = _write_project(tmp_path, manifest)
        result = validate_project(project_dir)
        fail_checks = [c for c in result.checks if "no command" in c.message]
        assert any(c.status == "fail" for c in fail_checks)

    def test_validate_fails_sse_no_url(self, tmp_path):
        manifest = _base_manifest(tools={
            "mcp_servers": [
                {"name": "bad", "transport": "sse"},
            ],
        })
        project_dir = _write_project(tmp_path, manifest)
        result = validate_project(project_dir)
        fail_checks = [c for c in result.checks if "no url" in c.message]
        assert any(c.status == "fail" for c in fail_checks)

    def test_validate_warns_missing_host_deps(self, tmp_path):
        manifest = _base_manifest(tools={
            "mcp_servers": [
                {"name": "fs", "transport": "stdio", "command": "npx",
                 "tool_filter": ["read_file"]},
            ],
        })
        project_dir = _write_project(tmp_path, manifest)
        result = validate_project(project_dir)
        dep_warns = [c for c in result.checks if "host_dependencies" in c.message]
        assert any(c.status == "warn" for c in dep_warns)

    def test_validate_warns_undeclared_env_ref(self, tmp_path):
        manifest = _base_manifest(tools={
            "mcp_servers": [
                {"name": "git", "transport": "stdio", "command": "uvx",
                 "args": ["--repo", "${REPO_PATH}"], "tool_filter": ["git_log"]},
            ],
        })
        project_dir = _write_project(tmp_path, manifest)
        result = validate_project(project_dir)
        env_warns = [c for c in result.checks if "REPO_PATH" in c.message]
        assert len(env_warns) > 0

    def test_validate_no_env_warn_when_declared(self, tmp_path):
        manifest = _base_manifest(
            tools={
                "mcp_servers": [
                    {"name": "git", "transport": "stdio", "command": "uvx",
                     "args": ["--repo", "${REPO_PATH}"], "tool_filter": ["git_log"]},
                ],
            },
            env=[{"name": "REPO_PATH", "description": "Repo path", "required": True}],
        )
        project_dir = _write_project(tmp_path, manifest)
        result = validate_project(project_dir)
        env_warns = [c for c in result.checks if "REPO_PATH" in c.message and "not declared" in c.message]
        assert len(env_warns) == 0


# ===========================================================================
# 5. Audit — MCP permissions
# ===========================================================================

class TestAuditMcpPermissions:
    """zil audit MCP permission checks."""

    def test_audit_no_mcp_passes(self, tmp_path):
        from zil.sdk.audit.mcp_permissions import check_mcp_permissions

        manifest = _base_manifest()
        project_dir = _write_project(tmp_path, manifest)
        section = check_mcp_permissions(project_dir)
        assert section.passed

    def test_audit_warns_no_tool_filter(self, tmp_path):
        from zil.sdk.audit.mcp_permissions import check_mcp_permissions

        manifest = _base_manifest(tools={
            "mcp_servers": [
                {"name": "git", "transport": "stdio", "command": "uvx"},
            ],
        })
        project_dir = _write_project(tmp_path, manifest)
        section = check_mcp_permissions(project_dir)
        assert section.has_warning
        warning_msgs = [f.message for f in section.findings if f.severity.value == "warning"]
        assert any("all tools" in m for m in warning_msgs)

    def test_audit_passes_with_tool_filter(self, tmp_path):
        from zil.sdk.audit.mcp_permissions import check_mcp_permissions

        manifest = _base_manifest(tools={
            "mcp_servers": [
                {"name": "git", "transport": "stdio", "command": "uvx",
                 "tool_filter": ["git_log"]},
            ],
        })
        project_dir = _write_project(tmp_path, manifest)
        section = check_mcp_permissions(project_dir)
        assert section.passed

    def test_audit_warns_risky_host_dep(self, tmp_path):
        from zil.sdk.audit.mcp_permissions import check_mcp_permissions

        manifest = _base_manifest(tools={
            "mcp_servers": [],
            "host_dependencies": ["docker", "git"],
        })
        project_dir = _write_project(tmp_path, manifest)
        section = check_mcp_permissions(project_dir)
        warning_msgs = [f.message for f in section.findings if f.severity.value == "warning"]
        assert any("docker" in m for m in warning_msgs)
        # git should pass
        pass_msgs = [f.message for f in section.findings if f.severity.value == "pass"]
        assert any("git" in m for m in pass_msgs)

    def test_audit_warns_long_timeout(self, tmp_path):
        from zil.sdk.audit.mcp_permissions import check_mcp_permissions

        manifest = _base_manifest(tools={
            "mcp_servers": [
                {"name": "slow", "transport": "stdio", "command": "uvx",
                 "tool_filter": ["something"], "timeout": 120},
            ],
        })
        project_dir = _write_project(tmp_path, manifest)
        section = check_mcp_permissions(project_dir)
        warning_msgs = [f.message for f in section.findings if f.severity.value == "warning"]
        assert any("timeout" in m.lower() for m in warning_msgs)


# ===========================================================================
# 6. Init scaffolding
# ===========================================================================

class TestInitMcp:
    """zil init --mcp scaffolding."""

    def test_init_with_git_preset(self, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli, ["init", "git-agent", "--non-interactive", "--mcp", "git"],
                catch_exceptions=False,
            )
            assert result.exit_code == 0
            manifest_text = (Path("git-agent") / "manifest.yaml").read_text()
            assert "mcp_servers" in manifest_text
            assert "git" in manifest_text
            assert "host_dependencies" in manifest_text

    def test_init_with_filesystem_preset(self, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli, ["init", "fs-agent", "--non-interactive", "--mcp", "filesystem"],
                catch_exceptions=False,
            )
            assert result.exit_code == 0
            manifest_text = (Path("fs-agent") / "manifest.yaml").read_text()
            assert "filesystem" in manifest_text
            assert "nodejs" in manifest_text

    def test_init_without_mcp_has_commented_tools(self, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli, ["init", "no-mcp-agent", "--non-interactive"],
                catch_exceptions=False,
            )
            assert result.exit_code == 0
            manifest_text = (Path("no-mcp-agent") / "manifest.yaml").read_text()
            assert "# tools:" in manifest_text

    def test_init_git_dockerfile_has_apt_install(self, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(
                cli, ["init", "git-docker-agent", "--non-interactive", "--mcp", "git"],
                catch_exceptions=False,
            )
            dockerfile = (Path("git-docker-agent") / "Dockerfile").read_text()
            assert "apt-get install" in dockerfile
            assert "git" in dockerfile

    def test_init_no_mcp_dockerfile_no_apt(self, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(
                cli, ["init", "plain-agent", "--non-interactive"],
                catch_exceptions=False,
            )
            dockerfile = (Path("plain-agent") / "Dockerfile").read_text()
            assert "apt-get install" not in dockerfile


# ---------------------------------------------------------------------------
# entry_point schema
# ---------------------------------------------------------------------------

class TestEntryPointSchema:
    """Tests for entry_point field in mcpServer schema."""

    def test_schema_accepts_entry_point(self):
        """entry_point is valid in the schema."""
        schema = load_schema()
        manifest = _base_manifest(tools={
            "mcp_servers": [{
                "name": "myserver",
                "transport": "stdio",
                "command": "node",
                "args": ["./tools/myserver/dist/index.js"],
                "source": "./tools/myserver",
                "entry_point": "dist/index.js",
            }],
        })
        jsonschema.validate(instance=manifest, schema=schema)

    def test_schema_accepts_source_without_entry_point(self):
        """source alone is valid (entry_point is optional)."""
        schema = load_schema()
        manifest = _base_manifest(tools={
            "mcp_servers": [{
                "name": "myserver",
                "transport": "stdio",
                "command": "node",
                "args": ["./tools/myserver/dist/index.js"],
                "source": "./tools/myserver",
            }],
        })
        jsonschema.validate(instance=manifest, schema=schema)


# ---------------------------------------------------------------------------
# .bundleignore
# ---------------------------------------------------------------------------

class TestBundleignore:
    """Tests for _load_bundle_excludes and _is_excluded."""

    def test_default_excludes(self):
        from zil.packaging.archive import _load_bundle_excludes
        excludes = _load_bundle_excludes(Path("/nonexistent"))
        assert ".git" in excludes
        assert "src" in excludes
        assert "tests" in excludes
        assert ".env" in excludes

    def test_bundleignore_extends_defaults(self, tmp_path):
        from zil.packaging.archive import _load_bundle_excludes
        (tmp_path / ".bundleignore").write_text("custom_dir\nmy_cache\n")
        excludes = _load_bundle_excludes(tmp_path)
        assert ".git" in excludes  # default
        assert "custom_dir" in excludes  # extra
        assert "my_cache" in excludes  # extra

    def test_bundleignore_ignores_comments(self, tmp_path):
        from zil.packaging.archive import _load_bundle_excludes
        (tmp_path / ".bundleignore").write_text("# comment\nfoo\n\n")
        excludes = _load_bundle_excludes(tmp_path)
        assert "# comment" not in excludes
        assert "foo" in excludes

    def test_is_excluded(self):
        from zil.packaging.archive import _is_excluded
        excludes = {".git", "src"}
        assert _is_excluded(Path(".git/config"), excludes) is True
        assert _is_excluded(Path("src/main.ts"), excludes) is True
        assert _is_excluded(Path("dist/index.js"), excludes) is False
        assert _is_excluded(Path("package.json"), excludes) is False


# ---------------------------------------------------------------------------
# Dockerfile generator
# ---------------------------------------------------------------------------

class TestDockerfileGenerator:
    """Tests for packaging/dockerfile.py."""

    def test_generate_dockerfile_no_deps(self):
        from zil.packaging.dockerfile import generate_dockerfile
        result = generate_dockerfile(name="myagent")
        assert "FROM python:3.12-slim AS deps" in result
        assert "apt-get" not in result
        assert "EXPOSE 8000" in result

    def test_generate_dockerfile_with_nodejs(self):
        from zil.packaging.dockerfile import generate_dockerfile
        result = generate_dockerfile(name="myagent", host_deps=["nodejs"])
        assert "apt-get" in result
        assert "nodejs npm" in result

    def test_generate_deploy_dockerfile(self):
        from zil.packaging.dockerfile import generate_deploy_dockerfile
        result = generate_deploy_dockerfile(
            module_dir="myagent",
            adk_version="1.2.3",
            host_deps=["nodejs"],
            with_ui=True,
            trace=True,
        )
        assert "google-adk==1.2.3" in result
        assert "nodejs npm" in result
        assert "adk web" in result
        assert "--trace_to_cloud" in result

    def test_generate_deploy_dockerfile_api_server(self):
        from zil.packaging.dockerfile import generate_deploy_dockerfile
        result = generate_deploy_dockerfile(module_dir="myagent")
        assert "adk api_server" in result
        assert "--trace_to_cloud" not in result


# ---------------------------------------------------------------------------
# Validation: source and entry_point paths
# ---------------------------------------------------------------------------

class TestSourceEntryPointValidation:
    """Tests for source/entry_point validation in _check_tools."""

    def test_validate_warns_source_outside_tools(self, tmp_path):
        """Warn when source is not under tools/ convention."""
        # Setup: source exists but outside tools/
        ext_source = tmp_path / "external_server"
        ext_source.mkdir()
        (ext_source / "dist").mkdir()
        (ext_source / "dist" / "index.js").write_text("//")

        (tmp_path / "identity").mkdir()
        (tmp_path / "identity" / "persona.md").write_text("x")
        (tmp_path / "adapters").mkdir()
        (tmp_path / "adapters" / "llm.yaml").write_text("provider: gemini\nmodel: gemini-2.0-flash")

        manifest = _base_manifest(tools={
            "mcp_servers": [{
                "name": "ext",
                "transport": "stdio",
                "command": "node",
                "args": ["./external_server/dist/index.js"],
                "source": "./external_server",
                "entry_point": "dist/index.js",
                "tool_filter": ["foo"],
            }],
            "host_dependencies": ["nodejs"],
        })
        (tmp_path / "manifest.yaml").write_text(yaml.dump(manifest))
        result = validate_project(tmp_path)
        msgs = [c.message for c in result.checks]
        assert any("outside tools/" in m for m in msgs)

    def test_validate_fails_source_not_found(self, tmp_path):
        """Fail when source directory doesn't exist."""
        (tmp_path / "identity").mkdir()
        (tmp_path / "identity" / "persona.md").write_text("x")
        (tmp_path / "adapters").mkdir()
        (tmp_path / "adapters" / "llm.yaml").write_text("provider: gemini\nmodel: gemini-2.0-flash")

        manifest = _base_manifest(tools={
            "mcp_servers": [{
                "name": "missing",
                "transport": "stdio",
                "command": "node",
                "args": ["./tools/missing/dist/index.js"],
                "source": "./tools/missing",
                "tool_filter": ["foo"],
            }],
            "host_dependencies": ["nodejs"],
        })
        (tmp_path / "manifest.yaml").write_text(yaml.dump(manifest))
        result = validate_project(tmp_path)
        msgs = [c.message for c in result.checks]
        assert any("directory not found" in m for m in msgs)

    def test_validate_warns_entry_point_without_source(self, tmp_path):
        """Warn when entry_point is specified without source."""
        (tmp_path / "identity").mkdir()
        (tmp_path / "identity" / "persona.md").write_text("x")
        (tmp_path / "adapters").mkdir()
        (tmp_path / "adapters" / "llm.yaml").write_text("provider: gemini\nmodel: gemini-2.0-flash")

        manifest = _base_manifest(tools={
            "mcp_servers": [{
                "name": "orphan",
                "transport": "stdio",
                "command": "node",
                "args": ["./dist/index.js"],
                "entry_point": "dist/index.js",
                "tool_filter": ["foo"],
            }],
            "host_dependencies": ["nodejs"],
        })
        (tmp_path / "manifest.yaml").write_text(yaml.dump(manifest))
        result = validate_project(tmp_path)
        msgs = [c.message for c in result.checks]
        assert any("entry_point without source" in m for m in msgs)
