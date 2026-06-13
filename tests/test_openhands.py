"""Tests for the OpenHands framework backend (RFC-002b).

Covers backend registration, wire(), MCP config transform, model resolution,
validation, scaffold templates, and deploy descriptor.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers — mock the openhands SDK so tests run without it installed
# ---------------------------------------------------------------------------

_MOCK_OH_SDK = types.ModuleType("openhands")
_MOCK_OH_SDK_SDK = types.ModuleType("openhands.sdk")

# Minimal mock classes
_MockLLM = MagicMock(name="LLM")
_MockAgent = MagicMock(name="Agent")
_MockConversation = MagicMock(name="Conversation")
_MockTool = MagicMock(name="Tool")

_MOCK_OH_SDK_SDK.LLM = _MockLLM
_MOCK_OH_SDK_SDK.Agent = _MockAgent
_MOCK_OH_SDK_SDK.Conversation = _MockConversation
_MOCK_OH_SDK_SDK.Tool = _MockTool

# Tools mocks
_MOCK_OH_TOOLS = types.ModuleType("openhands.tools")
_MOCK_OH_TOOLS_TERMINAL = types.ModuleType("openhands.tools.terminal")
_MOCK_OH_TOOLS_FILE_EDITOR = types.ModuleType("openhands.tools.file_editor")
_MOCK_OH_TOOLS_TASK_TRACKER = types.ModuleType("openhands.tools.task_tracker")

_MockTerminalTool = MagicMock()
_MockTerminalTool.name = "terminal"
_MockFileEditorTool = MagicMock()
_MockFileEditorTool.name = "file_editor"
_MockTaskTrackerTool = MagicMock()
_MockTaskTrackerTool.name = "task_tracker"

_MOCK_OH_TOOLS_TERMINAL.TerminalTool = _MockTerminalTool
_MOCK_OH_TOOLS_FILE_EDITOR.FileEditorTool = _MockFileEditorTool
_MOCK_OH_TOOLS_TASK_TRACKER.TaskTrackerTool = _MockTaskTrackerTool


def _install_oh_mocks():
    """Inject mock openhands modules into sys.modules."""
    sys.modules["openhands"] = _MOCK_OH_SDK
    sys.modules["openhands.sdk"] = _MOCK_OH_SDK_SDK
    sys.modules["openhands.tools"] = _MOCK_OH_TOOLS
    sys.modules["openhands.tools.terminal"] = _MOCK_OH_TOOLS_TERMINAL
    sys.modules["openhands.tools.file_editor"] = _MOCK_OH_TOOLS_FILE_EDITOR
    sys.modules["openhands.tools.task_tracker"] = _MOCK_OH_TOOLS_TASK_TRACKER


def _remove_oh_mocks():
    """Remove mock openhands modules from sys.modules."""
    for key in list(sys.modules):
        if key.startswith("openhands"):
            del sys.modules[key]


# ---------------------------------------------------------------------------
# Test: Registration
# ---------------------------------------------------------------------------


class TestOpenHandsRegistration:
    """Backend is registered when openhands-sdk is importable."""

    def test_openhands_in_registry(self):
        from zil.sdk.frameworks import registry

        assert "openhands" in registry

    def test_backend_name(self):
        from zil.sdk.frameworks import registry

        backend = registry.get("openhands")
        assert backend.name == "openhands"

    def test_satisfies_protocol(self):
        from zil.sdk.frameworks.base import FrameworkBackend
        from zil.sdk.frameworks.openhands.backend import OpenHandsBackend

        assert isinstance(OpenHandsBackend(), FrameworkBackend)


# ---------------------------------------------------------------------------
# Test: Model resolution
# ---------------------------------------------------------------------------


class TestOpenHandsModelResolution:
    """resolve_model_openhands maps Zil adapter configs to LiteLLM strings."""

    def test_anthropic_passthrough(self):
        from zil.sdk.frameworks.openhands.backend import resolve_model_openhands

        result = resolve_model_openhands(
            {"provider": "anthropic", "model": "claude-sonnet-4-20250514"}
        )
        assert result == "anthropic/claude-sonnet-4-20250514"

    def test_openai_passthrough(self):
        from zil.sdk.frameworks.openhands.backend import resolve_model_openhands

        result = resolve_model_openhands(
            {"provider": "openai", "model": "gpt-4o"}
        )
        assert result == "openai/gpt-4o"

    def test_gemini_gets_prefix(self):
        from zil.sdk.frameworks.openhands.backend import resolve_model_openhands

        result = resolve_model_openhands(
            {"provider": "gemini", "model": "gemini-2.0-flash"}
        )
        assert result == "gemini/gemini-2.0-flash"

    def test_vertex_gets_gemini_prefix(self):
        from zil.sdk.frameworks.openhands.backend import resolve_model_openhands

        result = resolve_model_openhands(
            {"provider": "vertex-ai", "model": "gemini-3.5-flash"}
        )
        assert result == "gemini/gemini-3.5-flash"

    def test_unknown_gemini_model_still_prefixed(self):
        from zil.sdk.frameworks.openhands.backend import resolve_model_openhands

        result = resolve_model_openhands(
            {"provider": "gemini", "model": "gemini-99.0-ultra"}
        )
        assert result == "gemini/gemini-99.0-ultra"

    def test_empty_raises(self):
        from zil.sdk.frameworks.openhands.backend import resolve_model_openhands

        with pytest.raises(ValueError, match="Cannot resolve model"):
            resolve_model_openhands({"provider": "", "model": ""})


# ---------------------------------------------------------------------------
# Test: MCP config transform
# ---------------------------------------------------------------------------


class TestOpenHandsMCPConfig:
    """_build_mcp_config transforms Zil format to OpenHands format."""

    def test_empty_input(self):
        from zil.sdk.frameworks.openhands.backend import OpenHandsBackend

        result = OpenHandsBackend._build_mcp_config([])
        assert result == {}

    def test_single_server(self):
        from zil.sdk.frameworks.openhands.backend import OpenHandsBackend

        result = OpenHandsBackend._build_mcp_config([
            {"name": "jira", "command": "npx", "args": ["-y", "jira-mcp"]}
        ])
        assert result == {
            "mcpServers": {
                "jira": {"command": "npx", "args": ["-y", "jira-mcp"]}
            }
        }

    def test_multiple_servers(self):
        from zil.sdk.frameworks.openhands.backend import OpenHandsBackend

        result = OpenHandsBackend._build_mcp_config([
            {"name": "jira", "command": "npx", "args": ["-y", "jira-mcp"]},
            {"name": "fs", "command": "npx", "args": ["-y", "@mcp/fs"], "env": {"ROOT": "/tmp"}},
        ])
        assert "jira" in result["mcpServers"]
        assert "fs" in result["mcpServers"]
        assert result["mcpServers"]["fs"]["env"] == {"ROOT": "/tmp"}

    def test_url_server(self):
        from zil.sdk.frameworks.openhands.backend import OpenHandsBackend

        result = OpenHandsBackend._build_mcp_config([
            {"name": "remote", "url": "https://mcp.example.com"}
        ])
        assert result["mcpServers"]["remote"]["url"] == "https://mcp.example.com"

    def test_missing_name_skipped(self):
        from zil.sdk.frameworks.openhands.backend import OpenHandsBackend

        result = OpenHandsBackend._build_mcp_config([
            {"command": "npx", "args": ["something"]}
        ])
        assert result == {}


# ---------------------------------------------------------------------------
# Test: wire()
# ---------------------------------------------------------------------------


class TestOpenHandsWire:
    """wire() constructs an OpenHands Agent via the SDK."""

    def setup_method(self):
        _install_oh_mocks()
        # Reset the mock Agent to track calls
        _MockAgent.reset_mock()
        _MockLLM.reset_mock()
        _MockTool.reset_mock()

    def teardown_method(self):
        _remove_oh_mocks()

    def test_wire_returns_wired_agent(self):
        from zil.sdk.frameworks.base import AgentSpec
        from zil.sdk.frameworks.openhands.backend import OpenHandsBackend

        spec = AgentSpec(
            name="test-agent",
            version="0.1.0",
            description="Test",
            instructions="You are a test agent.",
            model="anthropic/claude-sonnet-4-20250514",
        )
        backend = OpenHandsBackend()
        wired = backend.wire(spec)

        assert wired.framework == "openhands"
        assert wired.inner is not None

    def test_wire_passes_system_prompt(self):
        from zil.sdk.frameworks.base import AgentSpec
        from zil.sdk.frameworks.openhands.backend import OpenHandsBackend

        spec = AgentSpec(
            name="test-agent",
            version="0.1.0",
            description="Test",
            instructions="Custom instruction text.",
            model="openai/gpt-4o",
        )
        backend = OpenHandsBackend()
        backend.wire(spec)

        # Agent was called with system_prompt
        _MockAgent.assert_called_once()
        call_kwargs = _MockAgent.call_args
        assert call_kwargs.kwargs.get("system_prompt") == "Custom instruction text."

    def test_wire_builds_mcp_config(self):
        from zil.sdk.frameworks.base import AgentSpec
        from zil.sdk.frameworks.openhands.backend import OpenHandsBackend

        spec = AgentSpec(
            name="test-agent",
            version="0.1.0",
            description="Test",
            instructions="Test.",
            model="openai/gpt-4o",
            mcp_server_configs=[
                {"name": "jira", "command": "npx", "args": ["-y", "jira-mcp"]}
            ],
        )
        backend = OpenHandsBackend()
        backend.wire(spec)

        call_kwargs = _MockAgent.call_args.kwargs
        expected_mcp = {
            "mcpServers": {
                "jira": {"command": "npx", "args": ["-y", "jira-mcp"]}
            }
        }
        assert call_kwargs["mcp_config"] == expected_mcp


# ---------------------------------------------------------------------------
# Test: validate()
# ---------------------------------------------------------------------------


class TestOpenHandsValidate:
    """OpenHandsBackend.validate() checks framework-specific fields."""

    def test_warns_missing_llm_api_key(self, tmp_path):
        from zil.sdk.frameworks.openhands.backend import OpenHandsBackend

        manifest = {
            "spec": {
                "runtime": {"framework": "openhands"},
                "env": [{"name": "OTHER_VAR", "required": True}],
            }
        }
        checks = OpenHandsBackend().validate(tmp_path, manifest)
        assert any("LLM_API_KEY" in c.message and c.status == "warn" for c in checks)

    def test_passes_with_llm_api_key(self, tmp_path):
        from zil.sdk.frameworks.openhands.backend import OpenHandsBackend

        manifest = {
            "spec": {
                "runtime": {"framework": "openhands"},
                "env": [{"name": "LLM_API_KEY", "required": True, "secret": True}],
            }
        }
        checks = OpenHandsBackend().validate(tmp_path, manifest)
        assert any("LLM_API_KEY" in c.message and c.status == "pass" for c in checks)

    def test_warns_sub_agents(self, tmp_path):
        from zil.sdk.frameworks.openhands.backend import OpenHandsBackend

        manifest = {
            "spec": {
                "runtime": {"framework": "openhands"},
                "env": [{"name": "LLM_API_KEY"}],
                "agents": [
                    {"name": "sub1", "role": "coder"},
                    {"name": "sub2", "role": "reviewer"},
                ],
            }
        }
        checks = OpenHandsBackend().validate(tmp_path, manifest)
        assert any("sub-agent" in c.message and c.status == "warn" for c in checks)

    def test_no_agents_no_warning(self, tmp_path):
        from zil.sdk.frameworks.openhands.backend import OpenHandsBackend

        manifest = {
            "spec": {
                "runtime": {"framework": "openhands"},
                "env": [{"name": "LLM_API_KEY"}],
            }
        }
        checks = OpenHandsBackend().validate(tmp_path, manifest)
        assert not any("sub-agent" in c.message for c in checks)


# ---------------------------------------------------------------------------
# Test: deploy_descriptor()
# ---------------------------------------------------------------------------


class TestOpenHandsDeployDescriptor:
    """deploy_descriptor() returns correct metadata."""

    def test_descriptor_shape(self):
        from zil.sdk.frameworks.base import AgentSpec
        from zil.sdk.frameworks.openhands.backend import OpenHandsBackend

        spec = AgentSpec(
            name="my-coding-agent",
            version="0.1.0",
            description="Test",
            instructions="Test.",
            model="anthropic/claude-sonnet-4-20250514",
        )
        desc = OpenHandsBackend().deploy_descriptor(None, spec)

        assert desc["framework"] == "openhands"
        assert desc["needs_docker"] is True
        assert "openhands-sdk" in desc["pip_packages"]
        assert "zil-ai[openhands]" in desc["pip_packages"]
        assert desc["entrypoint"] == "python -m my_coding_agent.agent"

    def test_descriptor_env_vars(self):
        from zil.sdk.frameworks.base import AgentSpec
        from zil.sdk.frameworks.openhands.backend import OpenHandsBackend

        spec = AgentSpec(
            name="test-agent",
            version="0.1.0",
            description="Test",
            instructions="Test.",
            model="openai/gpt-4o",
        )
        desc = OpenHandsBackend().deploy_descriptor(None, spec)
        assert "LLM_API_KEY" in desc["env_vars"]
        assert desc["env_vars"]["LLM_MODEL"] == "openai/gpt-4o"


# ---------------------------------------------------------------------------
# Test: scaffold_config()
# ---------------------------------------------------------------------------


class TestOpenHandsScaffoldConfig:
    """scaffold_config() returns OpenHands template overrides."""

    def test_returns_dict(self):
        from zil.sdk.frameworks.openhands.backend import OpenHandsBackend

        config = OpenHandsBackend().scaffold_config()
        assert isinstance(config, dict)
        assert config["pip_extra"] == "openhands"

    def test_default_tools(self):
        from zil.sdk.frameworks.openhands.backend import OpenHandsBackend

        config = OpenHandsBackend().scaffold_config()
        assert "terminal" in config["default_tools"]
        assert "file_editor" in config["default_tools"]


# ---------------------------------------------------------------------------
# Test: zil init --framework openhands (scaffold templates)
# ---------------------------------------------------------------------------


class TestOpenHandsInitScaffold:
    """zil init --framework openhands produces correct project files."""

    def _make_config(self, name="oh-agent", framework="openhands", llm_provider="anthropic"):
        from zil.commands.init import InitConfig

        return InitConfig(
            name=name,
            framework=framework,
            language="python",
            llm_provider=llm_provider,
            eval_framework="deepeval",
            deploy_target="cloud-run",
            include_evals=False,
            include_otel=False,
        )

    def test_manifest_has_framework_openhands(self):
        from zil.templates.files import _manifest

        c = self._make_config()
        content = _manifest(c)
        assert "framework: openhands" in content

    def test_manifest_env_has_llm_api_key(self):
        from zil.templates.files import _manifest_env_vars

        c = self._make_config()
        content = _manifest_env_vars(c)
        assert "LLM_API_KEY" in content
        # Should NOT have provider-specific keys
        assert "ANTHROPIC_API_KEY" not in content

    def test_agent_py_mentions_openhands(self):
        from zil.templates.files import _agent_py

        c = self._make_config()
        content = _agent_py(c)
        assert "OpenHands" in content
        assert "zil.create_agent" in content

    def test_agent_py_adk_unchanged(self):
        from zil.templates.files import _agent_py

        c = self._make_config(framework="adk")
        content = _agent_py(c)
        assert "ADK" in content
        assert "OpenHands" not in content

    def test_requirements_uses_openhands_extra(self):
        from zil.templates.files import _requirements

        c = self._make_config()
        content = _requirements(c)
        assert "zil-ai[openhands]" in content
        assert "zil-ai[adk]" not in content

    def test_requirements_adk_unchanged(self):
        from zil.templates.files import _requirements

        c = self._make_config(framework="adk")
        content = _requirements(c)
        assert "zil-ai[adk]" in content
        assert "zil-ai[openhands]" not in content

    def test_module_requirements_uses_openhands_extra(self):
        from zil.templates.files import _module_requirements

        c = self._make_config()
        content = _module_requirements(c)
        assert "zil-ai[openhands]" in content

    def test_persona_mentions_coding_agent(self):
        from zil.templates.files import _persona

        c = self._make_config()
        content = _persona(c)
        assert "autonomous coding agent" in content
        assert "OpenHands" in content

    def test_persona_adk_unchanged(self):
        from zil.templates.files import _persona

        c = self._make_config(framework="adk")
        content = _persona(c)
        assert "autonomous coding agent" not in content

    def test_instructions_coding_focused(self):
        from zil.templates.files import _instructions

        c = self._make_config()
        content = _instructions(c)
        assert "Write tests" in content
        assert "destructive shell commands" in content

    def test_instructions_adk_unchanged(self):
        from zil.templates.files import _instructions

        c = self._make_config(framework="adk")
        content = _instructions(c)
        assert "destructive shell commands" not in content


# ---------------------------------------------------------------------------
# Test: CLI flag (zil init --framework openhands)
# ---------------------------------------------------------------------------


class TestOpenHandsInitCLI:
    """zil init --framework openhands works end-to-end."""

    def test_init_openhands_creates_project(self, tmp_path):
        from click.testing import CliRunner

        from zil.cli import cli

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli,
                [
                    "init", "my-oh-agent", "--framework", "openhands",
                    "--non-interactive", "--skip-install",
                ],
                catch_exceptions=False,
            )
            assert result.exit_code == 0
            project = Path("my-oh-agent")
            assert project.exists()
            assert (project / "manifest.yaml").exists()

            # Verify manifest content
            manifest_text = (project / "manifest.yaml").read_text()
            assert "framework: openhands" in manifest_text
            assert "LLM_API_KEY" in manifest_text

    def test_init_openhands_agent_py(self, tmp_path):
        from click.testing import CliRunner

        from zil.cli import cli

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli,
                [
                    "init", "my-oh-agent", "--framework", "openhands",
                    "--non-interactive", "--skip-install",
                ],
                catch_exceptions=False,
            )
            assert result.exit_code == 0
            agent_py = Path("my-oh-agent") / "my_oh_agent" / "agent.py"
            assert agent_py.exists()
            content = agent_py.read_text()
            assert "OpenHands" in content

    def test_init_openhands_requirements(self, tmp_path):
        from click.testing import CliRunner

        from zil.cli import cli

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli,
                [
                    "init", "my-oh-agent", "--framework", "openhands",
                    "--non-interactive", "--skip-install",
                ],
                catch_exceptions=False,
            )
            assert result.exit_code == 0
            reqs = (Path("my-oh-agent") / "requirements.txt").read_text()
            assert "zil-ai[openhands]" in reqs


# ---------------------------------------------------------------------------
# Test: Schema — openhands is accepted in manifest.schema.json
# ---------------------------------------------------------------------------


class TestOpenHandsSchema:
    """The manifest schema accepts framework: openhands."""

    def test_schema_accepts_openhands_framework(self):
        schema_path = (
            Path(__file__).resolve().parent.parent
            / "src"
            / "zil"
            / "spec"
            / "v1"
            / "manifest.schema.json"
        )
        schema = json.loads(schema_path.read_text())

        # runtime is a $ref to $defs/runtime
        runtime_def = schema["$defs"]["runtime"]
        framework_enum = runtime_def["properties"]["framework"]["enum"]
        assert "openhands" in framework_enum

    def test_schema_has_framework_config(self):
        schema_path = (
            Path(__file__).resolve().parent.parent
            / "src"
            / "zil"
            / "spec"
            / "v1"
            / "manifest.schema.json"
        )
        schema = json.loads(schema_path.read_text())

        runtime_def = schema["$defs"]["runtime"]
        assert "framework_config" in runtime_def["properties"]


# ---------------------------------------------------------------------------
# Test: _check_framework integration with OpenHands
# ---------------------------------------------------------------------------


class TestOpenHandsCheckFramework:
    """_check_framework dispatches to OpenHandsBackend.validate()."""

    def test_check_framework_openhands_pass(self, tmp_path):
        from zil.schema.loader import ValidationResult, _check_framework

        manifest = {
            "spec": {
                "runtime": {"framework": "openhands"},
                "env": [{"name": "LLM_API_KEY", "required": True}],
            }
        }
        result = ValidationResult()
        _check_framework(tmp_path, manifest, result)

        # Should have a pass for framework registered + pass for LLM_API_KEY
        statuses = [c.status for c in result.checks]
        assert "pass" in statuses
        assert "fail" not in statuses

    def test_check_framework_openhands_warns_no_key(self, tmp_path):
        from zil.schema.loader import ValidationResult, _check_framework

        manifest = {
            "spec": {
                "runtime": {"framework": "openhands"},
                "env": [],
            }
        }
        result = ValidationResult()
        _check_framework(tmp_path, manifest, result)

        statuses = [c.status for c in result.checks]
        assert "warn" in statuses
