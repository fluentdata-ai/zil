"""Tests for the framework backend abstraction (RFC-002a).

Covers:
  - BackendRegistry: register, resolve, duplicate handling, __contains__, list
  - UnknownFrameworkError with helpful message
  - AgentSpec construction
  - StubBackend: wire, run_local, deploy_descriptor, validate, scaffold_config
  - StubBackend satisfies FrameworkBackend protocol
  - _check_framework() validation integration
  - Schema: framework enum includes openhands/stub, framework_config allowed
  - zil init --framework flag
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml
from click.testing import CliRunner

from zil.cli import cli
from zil.schema.loader import validate_project
from zil.sdk.frameworks import registry
from zil.sdk.frameworks.base import (
    AgentSpec,
    BackendRegistry,
    FrameworkBackend,
    UnknownFrameworkError,
    WiredAgent,
)
from zil.sdk.frameworks.stub.backend import StubBackend, StubWiredAgent

# ---------------------------------------------------------------------------
# BackendRegistry
# ---------------------------------------------------------------------------

class TestBackendRegistry:
    def test_register_and_get(self):
        reg = BackendRegistry()
        backend = StubBackend()
        reg.register(backend)
        assert reg.get("stub") is backend

    def test_unknown_raises(self):
        reg = BackendRegistry()
        with pytest.raises(UnknownFrameworkError, match="nope"):
            reg.get("nope")

    def test_unknown_lists_registered(self):
        reg = BackendRegistry()
        reg.register(StubBackend())
        try:
            reg.get("nope")
        except UnknownFrameworkError as e:
            assert "stub" in e.registered

    def test_duplicate_overwrites(self):
        reg = BackendRegistry()
        b1 = StubBackend()
        b2 = StubBackend()
        reg.register(b1)
        reg.register(b2)
        assert reg.get("stub") is b2

    def test_contains(self):
        reg = BackendRegistry()
        assert "stub" not in reg
        reg.register(StubBackend())
        assert "stub" in reg

    def test_len(self):
        reg = BackendRegistry()
        assert len(reg) == 0
        reg.register(StubBackend())
        assert len(reg) == 1

    def test_list_names_sorted(self):
        reg = BackendRegistry()
        # Create a mock backend with name "alpha"
        alpha = MagicMock()
        alpha.name = "alpha"
        beta = StubBackend()  # name = "stub"
        reg.register(beta)
        reg.register(alpha)
        assert reg.list_names() == ["alpha", "stub"]


# ---------------------------------------------------------------------------
# UnknownFrameworkError
# ---------------------------------------------------------------------------

class TestUnknownFrameworkError:
    def test_message_format(self):
        err = UnknownFrameworkError("foo", ["adk", "stub"])
        assert "foo" in str(err)
        assert "adk" in str(err)
        assert "stub" in str(err)

    def test_empty_registered(self):
        err = UnknownFrameworkError("bar", [])
        assert "(none)" in str(err)


# ---------------------------------------------------------------------------
# AgentSpec
# ---------------------------------------------------------------------------

class TestAgentSpec:
    def test_defaults(self):
        spec = AgentSpec(
            name="test",
            version="0.1.0",
            description="A test agent",
            instructions="Be helpful",
            model="gemini-2.0-flash",
        )
        assert spec.tool_callables == []
        assert spec.mcp_server_configs == []
        assert spec.sub_agent_specs == []
        assert spec.thinking_budget is None
        assert spec.observability is None
        assert spec.raw_manifest == {}
        assert spec.guardrail_callback is None
        assert spec.cost_callback is None
        assert spec.context is None

    def test_with_all_fields(self):
        def my_tool():
            pass

        spec = AgentSpec(
            name="full",
            version="1.0.0",
            description="Full agent",
            instructions="Do things",
            model="openai/gpt-4o",
            tool_callables=[my_tool],
            mcp_server_configs=[{"name": "s1", "command": "echo"}],
            sub_agent_specs=["sub1"],
            thinking_budget=1024,
            observability={"tracing": {}},
            raw_manifest={"spec": {}},
        )
        assert len(spec.tool_callables) == 1
        assert spec.mcp_server_configs[0]["name"] == "s1"
        assert spec.thinking_budget == 1024


# ---------------------------------------------------------------------------
# StubBackend
# ---------------------------------------------------------------------------

class TestStubBackend:
    def test_name(self):
        assert StubBackend().name == "stub"

    def test_satisfies_protocol(self):
        assert isinstance(StubBackend(), FrameworkBackend)

    def test_wire_returns_wired_agent(self):
        spec = AgentSpec(
            name="test", version="0.1", description="", instructions="", model="m"
        )
        wired = StubBackend().wire(spec)
        assert isinstance(wired, StubWiredAgent)
        assert isinstance(wired, WiredAgent)
        assert wired.framework == "stub"
        assert wired.inner is spec

    def test_run_local_noop(self):
        spec = AgentSpec(
            name="test", version="0.1", description="", instructions="", model="m"
        )
        wired = StubBackend().wire(spec)
        # Should not raise
        StubBackend().run_local(wired, mode="interactive")

    def test_deploy_descriptor(self):
        spec = AgentSpec(
            name="test", version="0.1", description="", instructions="", model="m"
        )
        wired = StubBackend().wire(spec)
        desc = StubBackend().deploy_descriptor(wired, spec)
        assert desc["framework"] == "stub"

    def test_validate_returns_empty(self):
        assert StubBackend().validate(Path("."), {}) == []

    def test_scaffold_config_returns_none(self):
        assert StubBackend().scaffold_config() is None


# ---------------------------------------------------------------------------
# Global registry
# ---------------------------------------------------------------------------

class TestGlobalRegistry:
    def test_stub_registered(self):
        assert "stub" in registry

    def test_adk_registered(self):
        # ADK should be registered if google-adk is installed
        # If not installed, it won't be — skip the test
        try:
            import google.adk  # noqa: F401
            assert "adk" in registry
        except ImportError:
            pytest.skip("google-adk not installed")


# ---------------------------------------------------------------------------
# _check_framework validation
# ---------------------------------------------------------------------------

class TestCheckFramework:
    @pytest.fixture
    def project_with_framework(self, tmp_path):
        """Create a minimal project with a given framework in the manifest."""
        def _make(framework: str, extra_runtime: dict | None = None):
            runtime = {
                "framework": framework,
                "language": "python",
                "llm": {"adapter": "adapters/llm.yaml"},
            }
            if extra_runtime:
                runtime.update(extra_runtime)

            manifest = {
                "apiVersion": "zil/v1",
                "kind": "Agent",
                "metadata": {"name": "test-agent", "version": "0.1.0"},
                "spec": {
                    "identity": "./identity",
                    "runtime": runtime,
                },
            }
            (tmp_path / "manifest.yaml").write_text(yaml.dump(manifest))
            # Create minimal required files
            (tmp_path / "identity").mkdir(exist_ok=True)
            (tmp_path / "identity" / "persona.md").write_text("persona")
            (tmp_path / "identity" / "instructions.md").write_text("instructions")
            (tmp_path / "identity" / "guardrails.yaml").write_text("{}")
            (tmp_path / "adapters").mkdir(exist_ok=True)
            (tmp_path / "adapters" / "llm.yaml").write_text(
                "provider: gemini\nmodel: gemini-2.0-flash"
            )
            return tmp_path
        return _make

    def test_known_framework_passes(self, project_with_framework):
        project = project_with_framework("adk")
        result = validate_project(project)
        fw_checks = [c for c in result.checks if "runtime.framework" in c.message]
        assert any(c.status == "pass" for c in fw_checks)

    def test_stub_framework_passes(self, project_with_framework):
        project = project_with_framework("stub")
        result = validate_project(project)
        fw_checks = [c for c in result.checks if "runtime.framework" in c.message]
        assert any(c.status == "pass" for c in fw_checks)

    def test_unknown_framework_fails_validation(self, tmp_path):
        """An unregistered framework name causes a schema fail (enum)."""
        manifest = {
            "apiVersion": "zil/v1",
            "kind": "Agent",
            "metadata": {"name": "test-agent", "version": "0.1.0"},
            "spec": {
                "identity": "./identity",
                "runtime": {
                    "framework": "totally-unknown",
                    "language": "python",
                    "llm": {"adapter": "adapters/llm.yaml"},
                },
            },
        }
        (tmp_path / "manifest.yaml").write_text(yaml.dump(manifest))
        result = validate_project(tmp_path)
        # Should fail at schema level since "totally-unknown" isn't in enum
        schema_checks = [c for c in result.checks if c.status == "fail"]
        assert len(schema_checks) > 0

    def test_framework_config_passes_schema(self, project_with_framework):
        """framework_config with arbitrary keys passes schema validation."""
        project = project_with_framework(
            "adk",
            extra_runtime={"framework_config": {"sandbox": "docker", "timeout": 300}},
        )
        result = validate_project(project)
        schema_checks = [c for c in result.checks if "schema" in c.message.lower()]
        assert any(c.status == "pass" for c in schema_checks)


# ---------------------------------------------------------------------------
# Schema: framework enum + framework_config
# ---------------------------------------------------------------------------

class TestManifestSchema:
    @pytest.fixture
    def schema(self):
        schema_path = (
            Path(__file__).parent.parent
            / "src" / "zil" / "spec" / "v1" / "manifest.schema.json"
        )
        with open(schema_path) as f:
            return json.load(f)

    def test_framework_enum_includes_openhands(self, schema):
        fw = schema["$defs"]["runtime"]["properties"]["framework"]
        assert "openhands" in fw["enum"]

    def test_framework_enum_includes_stub(self, schema):
        fw = schema["$defs"]["runtime"]["properties"]["framework"]
        assert "stub" in fw["enum"]

    def test_framework_config_defined(self, schema):
        runtime_props = schema["$defs"]["runtime"]["properties"]
        assert "framework_config" in runtime_props
        assert runtime_props["framework_config"]["type"] == "object"
        assert runtime_props["framework_config"]["additionalProperties"] is True


# ---------------------------------------------------------------------------
# zil init --framework
# ---------------------------------------------------------------------------

runner_cli = CliRunner()


class TestInitFrameworkFlag:
    def test_init_default_framework_is_adk(self, tmp_path):
        with runner_cli.isolated_filesystem(temp_dir=tmp_path):
            result = runner_cli.invoke(
                cli, ["init", "test-agent", "--non-interactive", "--skip-install"],
                catch_exceptions=False,
            )
            assert result.exit_code == 0
            manifest = yaml.safe_load((Path("test-agent") / "manifest.yaml").read_text())
            assert manifest["spec"]["runtime"]["framework"] == "adk"

    def test_init_framework_adk_explicit(self, tmp_path):
        with runner_cli.isolated_filesystem(temp_dir=tmp_path):
            result = runner_cli.invoke(
                cli,
                [
                    "init", "test-agent", "--framework", "adk",
                    "--non-interactive", "--skip-install",
                ],
                catch_exceptions=False,
            )
            assert result.exit_code == 0
            manifest = yaml.safe_load((Path("test-agent") / "manifest.yaml").read_text())
            assert manifest["spec"]["runtime"]["framework"] == "adk"

    def test_init_framework_unknown_fails(self, tmp_path):
        with runner_cli.isolated_filesystem(temp_dir=tmp_path):
            result = runner_cli.invoke(
                cli,
                [
                    "init", "test-agent", "--framework", "nope",
                    "--non-interactive", "--skip-install",
                ],
            )
            assert result.exit_code != 0
            assert "Unknown framework" in result.output

    def test_init_help_shows_framework(self):
        result = runner_cli.invoke(cli, ["init", "--help"])
        assert "--framework" in result.output


# ---------------------------------------------------------------------------
# A2A collaborators -> RemoteA2aAgent wiring (ZIL-RFC-005 Phase 1b)
# ---------------------------------------------------------------------------


class TestRemoteAgents:
    """`_build_remote_agents` wraps spec.collaborators as RemoteA2aAgent tools."""

    def _spec_with(self, collaborators):
        from types import SimpleNamespace

        # _build_remote_agents only reads ctx.collaborators.
        ctx = SimpleNamespace(collaborators=collaborators)
        return AgentSpec(
            name="caller",
            version="1.0.0",
            description="",
            instructions="",
            model="gemini-3.5-flash",
            context=ctx,
        )

    def test_no_collaborators_returns_empty(self):
        from zil.sdk.frameworks.adk.backend import _build_remote_agents

        assert _build_remote_agents(self._spec_with([])) == []

    @staticmethod
    def _close(remote):
        """Close any attached httpx client to avoid unclosed-client warnings.

        Uses a throwaway loop. ``new_event_loop()`` does not install itself as
        the current loop, so other tests relying on ``asyncio.get_event_loop()``
        are undisturbed.
        """
        import asyncio

        client = getattr(remote, "_httpx_client", None)
        if client is None:
            return
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(client.aclose())
        finally:
            loop.close()

    def test_wraps_peer_as_agent_tool(self):
        pytest.importorskip("google.adk")
        from zil.collaboration.contract import PeerRef
        from zil.sdk.frameworks.adk.backend import _build_remote_agents

        spec = self._spec_with([
            PeerRef(name="billing", url="https://billing.run.app",
                    skills=["refund"], auth="none"),
        ])
        tools = _build_remote_agents(spec)
        assert len(tools) == 1
        remote = tools[0].agent
        assert remote.name == "billing"
        # URL resolution is lazy; the card source targets the current
        # well-known path (no network call at construction time).
        assert remote._agent_card_source.endswith("/.well-known/agent-card.json")
        assert remote._agent_card_source.startswith("https://billing.run.app")
        # The per-peer skill allowlist is surfaced to the model.
        assert "refund" in remote.description
        self._close(remote)

    def test_hyphenated_peer_name_normalized_to_identifier(self):
        pytest.importorskip("google.adk")
        from zil.collaboration.contract import PeerRef
        from zil.sdk.frameworks.adk.backend import _build_remote_agents

        # ADK validates node names as Python identifiers; hyphenated fleet
        # names like 'weather-agent' must be normalized or construction fails.
        spec = self._spec_with([
            PeerRef(name="weather-agent", url="https://weather.run.app",
                    skills=["get-forecast"], auth="none"),
        ])
        remote = _build_remote_agents(spec)[0].agent
        assert remote.name == "weather_agent"
        # The original logical name is still surfaced to the model.
        assert "weather-agent" in remote.description
        self._close(remote)

    def test_unresolvable_env_url_is_skipped(self):
        pytest.importorskip("google.adk")
        from zil.collaboration.contract import PeerRef
        from zil.sdk.frameworks.adk.backend import _build_remote_agents

        spec = self._spec_with([
            PeerRef(name="billing", url="${DEFINITELY_UNSET_ENV_VAR_XYZ}"),
        ])
        assert _build_remote_agents(spec) == []

    def test_none_auth_still_attaches_identity_client(self):
        pytest.importorskip("google.adk")
        from zil.collaboration.contract import PeerRef
        from zil.collaboration.http import PeerRequestAuth
        from zil.sdk.frameworks.adk.backend import _build_remote_agents

        spec = self._spec_with([
            PeerRef(name="billing", url="https://billing.run.app", auth="none"),
        ])
        remote = _build_remote_agents(spec)[0].agent
        # 'none' still gets a client to carry the caller-identity header.
        assert remote._httpx_client is not None
        assert isinstance(remote._httpx_client.auth, PeerRequestAuth)
        # ...but no credentials authenticator is attached.
        assert remote._httpx_client.auth._authenticator is None
        self._close(remote)

    def test_bearer_auth_attaches_authenticated_client(self):
        pytest.importorskip("google.adk")
        from zil.collaboration.contract import PeerRef
        from zil.sdk.frameworks.adk.backend import _build_remote_agents

        spec = self._spec_with([
            PeerRef(name="billing", url="https://billing.run.app", auth="bearer"),
        ])
        remote = _build_remote_agents(spec)[0].agent
        # Non-'none' modes get an httpx client carrying the auth flow.
        assert remote._httpx_client is not None
        assert remote._httpx_client.auth._authenticator is not None
        self._close(remote)

    def test_caller_identity_is_the_agent_name(self):
        pytest.importorskip("google.adk")
        from zil.collaboration.contract import PeerRef
        from zil.sdk.frameworks.adk.backend import _build_remote_agents

        spec = self._spec_with([
            PeerRef(name="billing", url="https://billing.run.app", auth="none"),
        ])
        remote = _build_remote_agents(spec)[0].agent
        assert remote._httpx_client.auth._caller == spec.name
        self._close(remote)
