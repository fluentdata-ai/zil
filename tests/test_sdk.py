"""Tests for the zil SDK — loader, identity composer, and agent factory."""

from __future__ import annotations

import os
from pathlib import Path
from textwrap import dedent
from unittest.mock import MagicMock, patch

import pytest
import yaml

from zil.sdk.identity import compose_instruction
from zil.sdk.loader import (
    IdentityContext,
    ProjectContext,
    find_project_dir,
    load_project,
)
from zil.sdk.telemetry import _resolve_env_refs, setup_telemetry


# ---------------------------------------------------------------------------
# Fixtures — a minimal valid Zil project on disk
# ---------------------------------------------------------------------------

@pytest.fixture()
def zil_project(tmp_path: Path) -> Path:
    """Create a minimal Zil project tree and return its root."""
    manifest = {
        "apiVersion": "zil/v1",
        "kind": "Agent",
        "metadata": {
            "name": "test-agent",
            "version": "0.1.0",
            "description": "A test agent.",
        },
        "spec": {
            "runtime": {
                "framework": "adk",
                "language": "python",
                "llm": {"adapter": "./adapters/llm.yaml"},
            },
            "identity": "./identity",
        },
    }
    (tmp_path / "manifest.yaml").write_text(yaml.dump(manifest))

    # adapters/
    adapters = tmp_path / "adapters"
    adapters.mkdir()
    (adapters / "llm.yaml").write_text(
        yaml.dump({"provider": "anthropic", "model": "claude-sonnet-4-20250514"})
    )

    # identity/
    identity = tmp_path / "identity"
    identity.mkdir()
    (identity / "persona.md").write_text("# Test Agent\n\nYou are a test agent.")
    (identity / "instructions.md").write_text("# Instructions\n\n1. Be helpful.")
    (identity / "guardrails.yaml").write_text(
        yaml.dump(
            {
                "hard_blocks": [
                    {"topic": "illegal_activity", "description": "Refuse illegal requests."}
                ],
                "escalation_triggers": [
                    {
                        "condition": "user_requests_human",
                        "action": "escalate",
                        "message": "Connecting you with a human.",
                    }
                ],
                "output_constraints": {
                    "max_response_length": 2000,
                    "format": "markdown",
                    "citation_required": False,
                },
            }
        )
    )

    return tmp_path


# ---------------------------------------------------------------------------
# Loader tests
# ---------------------------------------------------------------------------

class TestFindProjectDir:
    def test_finds_root(self, zil_project: Path) -> None:
        assert find_project_dir(zil_project) == zil_project

    def test_finds_from_subdirectory(self, zil_project: Path) -> None:
        subdir = zil_project / "identity"
        assert find_project_dir(subdir) == zil_project

    def test_raises_when_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="manifest.yaml"):
            find_project_dir(tmp_path / "nonexistent")


class TestLoadProject:
    def test_loads_manifest(self, zil_project: Path) -> None:
        ctx = load_project(zil_project)
        assert ctx.name == "test-agent"
        assert ctx.version == "0.1.0"
        assert ctx.description == "A test agent."
        assert ctx.framework == "adk"

    def test_loads_identity(self, zil_project: Path) -> None:
        ctx = load_project(zil_project)
        assert ctx.identity.persona is not None
        assert "test agent" in ctx.identity.persona.lower()
        assert ctx.identity.instructions is not None
        assert "Be helpful" in ctx.identity.instructions

    def test_loads_guardrails(self, zil_project: Path) -> None:
        ctx = load_project(zil_project)
        assert ctx.identity.guardrails is not None
        assert "hard_blocks" in ctx.identity.guardrails

    def test_loads_llm_adapter(self, zil_project: Path) -> None:
        ctx = load_project(zil_project)
        assert ctx.llm_adapter["provider"] == "anthropic"
        assert "claude" in ctx.llm_adapter["model"]

    def test_missing_llm_adapter_raises(self, zil_project: Path) -> None:
        (zil_project / "adapters" / "llm.yaml").unlink()
        with pytest.raises(FileNotFoundError, match="LLM adapter"):
            load_project(zil_project)

    def test_load_from_module_subdir(self, zil_project: Path) -> None:
        """Regression: load_project should walk up when called from a module
        subdirectory that doesn't contain manifest.yaml (local dev scenario)."""
        module_dir = zil_project / "my_agent"
        module_dir.mkdir()
        ctx = load_project(module_dir)
        assert ctx.project_dir == zil_project
        assert ctx.name == "test-agent"


# ---------------------------------------------------------------------------
# Identity composition tests
# ---------------------------------------------------------------------------

class TestComposeInstruction:
    def test_combines_all_sections(self) -> None:
        result = compose_instruction(
            persona="You are a helpful bot.",
            instructions="1. Be concise.",
            guardrails={
                "hard_blocks": [{"description": "No illegal stuff."}],
                "output_constraints": {"max_response_length": 500},
            },
        )
        assert "helpful bot" in result
        assert "Be concise" in result
        assert "No illegal stuff" in result
        assert "500 characters" in result

    def test_empty_returns_default(self) -> None:
        result = compose_instruction(persona=None, instructions=None, guardrails=None)
        assert "helpful AI assistant" in result

    def test_guardrails_escalation(self) -> None:
        result = compose_instruction(
            persona=None,
            instructions=None,
            guardrails={
                "escalation_triggers": [
                    {"condition": "user_angry", "message": "Calm them down."}
                ]
            },
        )
        assert "user_angry" in result
        assert "Calm them down" in result

    def test_persona_only(self) -> None:
        result = compose_instruction(
            persona="You are a pirate.",
            instructions=None,
            guardrails=None,
        )
        assert result == "You are a pirate."


# ---------------------------------------------------------------------------
# Model resolution tests
# ---------------------------------------------------------------------------

class TestResolveModel:
    def test_anthropic_mapped(self) -> None:
        from zil.sdk.agent import resolve_model

        result = resolve_model({"provider": "anthropic", "model": "claude-sonnet-4-20250514"})
        assert result == "anthropic/claude-sonnet-4-20250514"

    def test_openai_mapped(self) -> None:
        from zil.sdk.agent import resolve_model

        result = resolve_model({"provider": "openai", "model": "gpt-4o"})
        assert result == "openai/gpt-4o"

    def test_vertex_mapped(self) -> None:
        from zil.sdk.agent import resolve_model

        result = resolve_model({"provider": "vertex-ai", "model": "gemini-2.0-flash"})
        assert result == "gemini-2.0-flash"

    def test_gemini_mapped(self) -> None:
        from zil.sdk.agent import resolve_model

        result = resolve_model({"provider": "gemini", "model": "gemini-2.0-flash"})
        assert result == "gemini-2.0-flash"

    def test_unknown_provider_falls_through(self) -> None:
        from zil.sdk.agent import resolve_model

        result = resolve_model({"provider": "mistral", "model": "mistral-large"})
        assert result == "mistral/mistral-large"

    def test_empty_raises(self) -> None:
        from zil.sdk.agent import resolve_model

        with pytest.raises(ValueError, match="Cannot resolve model"):
            resolve_model({"provider": "", "model": ""})


# ---------------------------------------------------------------------------
# create_agent integration test (mocks ADK)
# ---------------------------------------------------------------------------

class TestCreateAgent:
    def test_creates_agent_from_project(self, zil_project: Path) -> None:
        mock_agent = MagicMock(name="LlmAgent")
        mock_llm_agent_cls = MagicMock(return_value=mock_agent)

        with patch.dict("sys.modules", {"google": MagicMock(), "google.adk": MagicMock(), "google.adk.agents": MagicMock(LlmAgent=mock_llm_agent_cls)}):
            from zil.sdk.agent import create_agent

            agent = create_agent(project_dir=zil_project)

            mock_llm_agent_cls.assert_called_once()
            call_kwargs = mock_llm_agent_cls.call_args[1]
            assert call_kwargs["name"] == "test_agent"
            assert "anthropic/claude" in call_kwargs["model"]
            assert "test agent" in call_kwargs["instruction"].lower()
            assert "Be helpful" in call_kwargs["instruction"]
            assert "illegal" in call_kwargs["instruction"].lower()

    def test_raises_without_adk(self, zil_project: Path) -> None:
        with patch.dict("sys.modules", {"google.adk": None, "google.adk.agents": None}):
            # Need to reimport to pick up the patched modules
            import importlib
            import zil.sdk.agent as agent_mod
            importlib.reload(agent_mod)

            with pytest.raises(ImportError, match="google-adk"):
                agent_mod.create_agent(project_dir=zil_project)

    def test_overrides(self, zil_project: Path) -> None:
        mock_llm_agent_cls = MagicMock()

        with patch.dict("sys.modules", {"google": MagicMock(), "google.adk": MagicMock(), "google.adk.agents": MagicMock(LlmAgent=mock_llm_agent_cls)}):
            from zil.sdk.agent import create_agent

            create_agent(
                project_dir=zil_project,
                name="custom_name",
                model="openai/gpt-4o",
                instruction="Custom instruction.",
            )
            call_kwargs = mock_llm_agent_cls.call_args[1]
            assert call_kwargs["name"] == "custom_name"
            assert call_kwargs["model"] == "openai/gpt-4o"
            assert call_kwargs["instruction"] == "Custom instruction."


# ---------------------------------------------------------------------------
# Observability loader tests
# ---------------------------------------------------------------------------

@pytest.fixture()
def zil_project_with_obs(zil_project: Path) -> Path:
    """Extend base project with observability config."""
    manifest_path = zil_project / "manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text())
    manifest["spec"]["observability"] = "./observability"
    manifest_path.write_text(yaml.dump(manifest))

    obs_dir = zil_project / "observability"
    obs_dir.mkdir()
    obs_config = {
        "observability": {
            "tracing": {
                "exporter": "otlp",
                "endpoint": "${OTEL_EXPORTER_OTLP_TRACES_ENDPOINT}",
                "sample_rate": 1.0,
            },
            "resource_attributes": {
                "service.name": "test-agent",
            },
            "span_conventions": ["agent.session", "agent.turn"],
            "required_attributes": ["agent.name", "agent.version", "cost.usd"],
        }
    }
    (obs_dir / "config.yaml").write_text(yaml.dump(obs_config))
    return zil_project


class TestLoadObservability:
    def test_loads_observability_when_present(self, zil_project_with_obs: Path) -> None:
        ctx = load_project(zil_project_with_obs)
        assert ctx.observability is not None
        assert "observability" in ctx.observability
        assert ctx.observability["observability"]["tracing"]["exporter"] == "otlp"

    def test_observability_none_when_absent(self, zil_project: Path) -> None:
        ctx = load_project(zil_project)
        assert ctx.observability is None

    def test_observability_none_when_file_missing(self, zil_project: Path) -> None:
        manifest_path = zil_project / "manifest.yaml"
        manifest = yaml.safe_load(manifest_path.read_text())
        manifest["spec"]["observability"] = "./observability"
        manifest_path.write_text(yaml.dump(manifest))
        # observability dir not created
        ctx = load_project(zil_project)
        assert ctx.observability is None


# ---------------------------------------------------------------------------
# Telemetry setup tests
# ---------------------------------------------------------------------------

class TestResolveEnvRefs:
    def test_resolves_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_ENDPOINT", "http://collector:4318/v1/traces")
        assert _resolve_env_refs("${MY_ENDPOINT}") == "http://collector:4318/v1/traces"

    def test_unset_resolves_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("UNSET_VAR", raising=False)
        assert _resolve_env_refs("${UNSET_VAR}") == ""

    def test_no_placeholder_unchanged(self) -> None:
        assert _resolve_env_refs("http://localhost:4318") == "http://localhost:4318"


class TestSetupTelemetry:
    def test_returns_false_when_none(self) -> None:
        assert setup_telemetry(None) is False

    def test_returns_false_when_empty_endpoint(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", raising=False)
        obs = {"observability": {"tracing": {"endpoint": "${OTEL_EXPORTER_OTLP_TRACES_ENDPOINT}"}}}
        assert setup_telemetry(obs) is False

    def test_sets_env_vars_and_calls_adk(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "http://collector:4318/v1/traces")
        monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
        monkeypatch.delenv("OTEL_RESOURCE_ATTRIBUTES", raising=False)

        obs = {"observability": {"tracing": {"endpoint": "${OTEL_EXPORTER_OTLP_TRACES_ENDPOINT}"}}}

        mock_providers = MagicMock()
        mock_module = MagicMock(maybe_set_otel_providers=mock_providers)
        with patch.dict("sys.modules", {"google.adk.telemetry.setup": mock_module}):
            result = setup_telemetry(obs, agent_name="my-agent", agent_version="1.0.0")

        assert result is True
        assert os.environ.get("OTEL_SERVICE_NAME") == "my-agent"
        attrs = os.environ.get("OTEL_RESOURCE_ATTRIBUTES", "")
        assert "agent.name=my-agent" in attrs
        assert "agent.version=1.0.0" in attrs
        mock_providers.assert_called_once()

    def test_noop_without_observability_key(self) -> None:
        obs = {"something_else": {}}
        assert setup_telemetry(obs) is False
