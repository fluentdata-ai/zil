"""Tests for multi-agent schema, loader, validation, and init scaffolding."""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

import pytest
import yaml

from zil.schema.loader import validate_project
from zil.sdk.loader import load_project, AgentSpec


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _base_manifest(extras: dict | None = None) -> dict:
    """Return a minimal valid manifest dict."""
    m = {
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
    if extras:
        m["spec"].update(extras)
    return m


def _write_project(tmp_path: Path, manifest: dict) -> Path:
    """Write a minimal project tree to tmp_path and return it."""
    (tmp_path / "manifest.yaml").write_text(yaml.dump(manifest))
    adapters = tmp_path / "adapters"
    adapters.mkdir()
    (adapters / "llm.yaml").write_text(
        yaml.dump({"provider": "anthropic", "model": "claude-sonnet-4-20250514"})
    )
    identity = tmp_path / "identity"
    identity.mkdir()
    (identity / "persona.md").write_text("# Agent\n\nYou are a test agent.")
    (identity / "instructions.md").write_text("# Instructions\n\n1. Be helpful.")
    (identity / "guardrails.yaml").write_text(
        yaml.dump({
            "detection": {"prompt_injection": True, "pii_output": True},
            "output_constraints": {"max_response_length": 2000},
        })
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Schema validation: spec.agents
# ---------------------------------------------------------------------------

class TestAgentsSchema:
    def test_valid_agents_block(self, tmp_path):
        """spec.agents with valid sub-agents passes schema."""
        m = _base_manifest()
        m["spec"]["agents"] = [
            {"name": "vta", "identity": "./agents/vta/identity", "role": "sub-agent"},
            {"name": "vtd", "identity": "./agents/vtd/identity"},
        ]
        proj = _write_project(tmp_path, m)

        # Create sub-agent identity dirs to satisfy _check_agents
        for name in ("vta", "vtd"):
            d = proj / "agents" / name / "identity"
            d.mkdir(parents=True)
            (d / "instructions.md").write_text(f"# {name} instructions")

        result = validate_project(proj)
        errors = [c.message for c in result.checks if c.status == "fail"]
        assert not errors, f"Unexpected errors: {errors}"

    def test_agents_requires_identity_field(self, tmp_path):
        """spec.agents entry without identity fails schema validation."""
        m = _base_manifest()
        m["spec"]["agents"] = [{"name": "vta"}]  # missing identity
        proj = _write_project(tmp_path, m)

        result = validate_project(proj)
        # Should fail either on JSON schema or _check_agents
        all_messages = " ".join(c.message for c in result.checks)
        assert "schema" in all_messages.lower() or "identity" in all_messages.lower()

    def test_missing_identity_dir_flagged(self, tmp_path):
        """_check_agents warns when sub-agent identity directory does not exist."""
        m = _base_manifest()
        m["spec"]["agents"] = [
            {"name": "vta", "identity": "./agents/vta/identity"},
        ]
        proj = _write_project(tmp_path, m)
        # Do NOT create the identity dir

        result = validate_project(proj)
        fail_msgs = [c.message for c in result.checks if c.status == "fail"]
        assert any("vta" in msg and "identity" in msg for msg in fail_msgs)

    def test_unknown_mcp_server_name_warns(self, tmp_path):
        """Sub-agent referencing an undeclared MCP server name generates a warning."""
        m = _base_manifest()
        m["spec"]["agents"] = [
            {
                "name": "vta",
                "identity": "./agents/vta/identity",
                "tools": {"mcp_servers": ["nonexistent-server"]},
            }
        ]
        proj = _write_project(tmp_path, m)
        d = proj / "agents" / "vta" / "identity"
        d.mkdir(parents=True)
        (d / "instructions.md").write_text("instructions")

        result = validate_project(proj)
        warn_msgs = [c.message for c in result.checks if c.status == "warn"]
        assert any("nonexistent-server" in msg for msg in warn_msgs)

    def test_model_env_var_not_in_spec_env_warns(self, tmp_path):
        """model_env_var that isn't in spec.env generates a warning."""
        m = _base_manifest()
        m["spec"]["agents"] = [
            {
                "name": "vta",
                "identity": "./agents/vta/identity",
                "llm": {"model_env_var": "UNDECLARED_MODEL_VAR"},
            }
        ]
        proj = _write_project(tmp_path, m)
        d = proj / "agents" / "vta" / "identity"
        d.mkdir(parents=True)
        (d / "instructions.md").write_text("instructions")

        result = validate_project(proj)
        warn_msgs = [c.message for c in result.checks if c.status == "warn"]
        assert any("UNDECLARED_MODEL_VAR" in msg for msg in warn_msgs)

    def test_agents_count_in_pass_message(self, tmp_path):
        """Pass message includes sub-agent count and names."""
        m = _base_manifest()
        m["spec"]["agents"] = [
            {"name": "vta", "identity": "./agents/vta/identity"},
            {"name": "vtd", "identity": "./agents/vtd/identity"},
        ]
        proj = _write_project(tmp_path, m)
        for name in ("vta", "vtd"):
            d = proj / "agents" / name / "identity"
            d.mkdir(parents=True)
            (d / "instructions.md").write_text("instructions")

        result = validate_project(proj)
        pass_msgs = " ".join(c.message for c in result.checks if c.status == "pass")
        assert "2 sub-agent" in pass_msgs
        assert "vta" in pass_msgs
        assert "vtd" in pass_msgs


# ---------------------------------------------------------------------------
# Schema validation: spec.runtime.service
# ---------------------------------------------------------------------------

class TestServiceSchema:
    def _proj_with_service(self, tmp_path, service_cfg, extra_env=None) -> Path:
        m = _base_manifest()
        m["spec"]["runtime"]["service"] = service_cfg
        if extra_env:
            m["spec"]["env"] = extra_env
        return _write_project(tmp_path, m)

    def test_webhook_entry_point_passes(self, tmp_path):
        proj = self._proj_with_service(
            tmp_path,
            {"entry_point": "webhook", "webhooks": [{"name": "jira", "path": "/webhooks/jira"}]},
        )
        result = validate_project(proj)
        pass_msgs = " ".join(c.message for c in result.checks if c.status == "pass")
        assert "entry_point=webhook" in pass_msgs
        assert "jira" in pass_msgs

    def test_webhook_secret_env_not_declared_warns(self, tmp_path):
        proj = self._proj_with_service(
            tmp_path,
            {
                "entry_point": "webhook",
                "webhooks": [
                    {"name": "gh", "path": "/wh/gh", "secret_env": "GITHUB_SECRET"}
                ],
            },
        )
        result = validate_project(proj)
        warn_msgs = [c.message for c in result.checks if c.status == "warn"]
        assert any("GITHUB_SECRET" in msg for msg in warn_msgs)

    def test_hitl_without_session_uri_warns(self, tmp_path):
        proj = self._proj_with_service(
            tmp_path,
            {"entry_point": "webhook", "human_interaction": {"enabled": True}},
        )
        result = validate_project(proj)
        warn_msgs = [c.message for c in result.checks if c.status == "warn"]
        assert any("SESSION_DB_URI" in msg for msg in warn_msgs)

    def test_hitl_with_session_uri_no_warning(self, tmp_path):
        proj = self._proj_with_service(
            tmp_path,
            {"entry_point": "webhook", "human_interaction": {"enabled": True}},
            extra_env=[{"name": "SESSION_DB_URI", "required": False, "secret": True}],
        )
        result = validate_project(proj)
        warn_msgs = [c.message for c in result.checks if c.status == "warn"]
        assert not any("SESSION_DB_URI" in msg for msg in warn_msgs)

    def test_jira_comment_channel_requires_issue_key_env(self, tmp_path):
        proj = self._proj_with_service(
            tmp_path,
            {
                "entry_point": "webhook",
                "human_interaction": {
                    "enabled": True,
                    "notify": {"channel": "jira_comment"},
                },
            },
            extra_env=[{"name": "SESSION_DB_URI", "required": False, "secret": True}],
        )
        result = validate_project(proj)
        fail_msgs = [c.message for c in result.checks if c.status == "fail"]
        assert any("issue_key_env" in msg for msg in fail_msgs)

    def test_jira_comment_with_issue_key_env_passes(self, tmp_path):
        proj = self._proj_with_service(
            tmp_path,
            {
                "entry_point": "webhook",
                "human_interaction": {
                    "enabled": True,
                    "notify": {"channel": "jira_comment", "issue_key_env": "JIRA_ISSUE"},
                },
            },
            extra_env=[
                {"name": "SESSION_DB_URI", "required": False, "secret": True},
                {"name": "JIRA_ISSUE", "required": True},
            ],
        )
        result = validate_project(proj)
        fail_msgs = [c.message for c in result.checks if c.status == "fail"]
        assert not any("issue_key_env" in msg for msg in fail_msgs)

    def test_hitl_pass_message_includes_timeout(self, tmp_path):
        proj = self._proj_with_service(
            tmp_path,
            {
                "entry_point": "webhook",
                "human_interaction": {
                    "enabled": True,
                    "timeout_seconds": 3600,
                    "timeout_action": "proceed",
                },
            },
            extra_env=[{"name": "SESSION_DB_URI", "required": False, "secret": True}],
        )
        result = validate_project(proj)
        pass_msgs = " ".join(c.message for c in result.checks if c.status == "pass")
        assert "3600" in pass_msgs
        assert "proceed" in pass_msgs


# ---------------------------------------------------------------------------
# Loader: AgentSpec + service_config
# ---------------------------------------------------------------------------

class TestLoader:
    def _multi_agent_project(self, tmp_path: Path) -> Path:
        m = {
            "apiVersion": "zil/v1",
            "kind": "Agent",
            "metadata": {"name": "team-agent", "version": "0.1.0"},
            "spec": {
                "runtime": {
                    "framework": "adk",
                    "language": "python",
                    "llm": {"adapter": "./adapters/llm.yaml"},
                },
                "identity": "./identity",
                "agents": [
                    {
                        "name": "vta",
                        "role": "sub-agent",
                        "identity": "./agents/vta/identity",
                        "description": "VTA agent",
                        "llm": {"model_env_var": "AGENT_VTA_MODEL"},
                        "tools": {"mcp_servers": ["jira"]},
                    },
                    {
                        "name": "vtd",
                        "role": "sub-agent",
                        "identity": "./agents/vtd/identity",
                    },
                ],
            },
        }
        (tmp_path / "manifest.yaml").write_text(yaml.dump(m))
        adapters = tmp_path / "adapters"
        adapters.mkdir()
        (adapters / "llm.yaml").write_text(
            yaml.dump({"provider": "anthropic", "model": "claude-sonnet-4-20250514"})
        )
        # Root identity
        id_dir = tmp_path / "identity"
        id_dir.mkdir()
        (id_dir / "persona.md").write_text("persona")
        (id_dir / "instructions.md").write_text("instructions")

        # Sub-agent identity dirs
        for name in ("vta", "vtd"):
            d = tmp_path / "agents" / name / "identity"
            d.mkdir(parents=True)
            (d / "persona.md").write_text(f"# {name} persona")
            (d / "instructions.md").write_text(f"# {name} instructions")
        return tmp_path

    def test_agents_loaded(self, tmp_path):
        proj = self._multi_agent_project(tmp_path)
        ctx = load_project(proj)
        assert len(ctx.agents) == 2

    def test_agent_names(self, tmp_path):
        proj = self._multi_agent_project(tmp_path)
        ctx = load_project(proj)
        names = [a.name for a in ctx.agents]
        assert names == ["vta", "vtd"]

    def test_agent_roles(self, tmp_path):
        proj = self._multi_agent_project(tmp_path)
        ctx = load_project(proj)
        assert all(a.role == "sub-agent" for a in ctx.agents)

    def test_agent_model_env_var(self, tmp_path):
        proj = self._multi_agent_project(tmp_path)
        ctx = load_project(proj)
        vta = next(a for a in ctx.agents if a.name == "vta")
        assert vta.model_env_var == "AGENT_VTA_MODEL"

    def test_agent_no_model_env_var(self, tmp_path):
        proj = self._multi_agent_project(tmp_path)
        ctx = load_project(proj)
        vtd = next(a for a in ctx.agents if a.name == "vtd")
        assert vtd.model_env_var is None

    def test_agent_mcp_server_names(self, tmp_path):
        proj = self._multi_agent_project(tmp_path)
        ctx = load_project(proj)
        vta = next(a for a in ctx.agents if a.name == "vta")
        assert vta.mcp_server_names == ["jira"]

    def test_agent_identity_loaded(self, tmp_path):
        proj = self._multi_agent_project(tmp_path)
        ctx = load_project(proj)
        vta = next(a for a in ctx.agents if a.name == "vta")
        assert "vta persona" in (vta.identity.persona or "")
        assert "vta instructions" in (vta.identity.instructions or "")

    def test_agent_inherits_root_llm_adapter(self, tmp_path):
        proj = self._multi_agent_project(tmp_path)
        ctx = load_project(proj)
        vtd = next(a for a in ctx.agents if a.name == "vtd")
        assert vtd.llm_adapter["model"] == "claude-sonnet-4-20250514"

    def test_service_config_loaded(self, tmp_path):
        m = {
            "apiVersion": "zil/v1",
            "kind": "Agent",
            "metadata": {"name": "svc-agent", "version": "0.1.0"},
            "spec": {
                "runtime": {
                    "framework": "adk",
                    "language": "python",
                    "llm": {"adapter": "./adapters/llm.yaml"},
                    "service": {
                        "entry_point": "webhook",
                        "webhooks": [{"name": "jira", "path": "/webhooks/jira"}],
                    },
                },
                "identity": "./identity",
            },
        }
        (tmp_path / "manifest.yaml").write_text(yaml.dump(m))
        adapters = tmp_path / "adapters"
        adapters.mkdir()
        (adapters / "llm.yaml").write_text(
            yaml.dump({"provider": "anthropic", "model": "claude-sonnet-4-20250514"})
        )
        id_dir = tmp_path / "identity"
        id_dir.mkdir()
        (id_dir / "persona.md").write_text("persona")
        (id_dir / "instructions.md").write_text("instructions")

        ctx = load_project(tmp_path)
        assert ctx.service_config is not None
        assert ctx.service_config["entry_point"] == "webhook"
        assert ctx.service_config["webhooks"][0]["name"] == "jira"

    def test_no_agents_empty_list(self, tmp_path):
        m = _base_manifest()
        proj = _write_project(tmp_path, m)
        ctx = load_project(proj)
        assert ctx.agents == []

    def test_no_service_config_is_none(self, tmp_path):
        m = _base_manifest()
        proj = _write_project(tmp_path, m)
        ctx = load_project(proj)
        assert ctx.service_config is None


# ---------------------------------------------------------------------------
# Schema JSON file: new $defs present
# ---------------------------------------------------------------------------

class TestSchemaDefinitions:
    def _load_schema(self) -> dict:
        from zil.schema.loader import load_schema
        return load_schema()

    def test_agent_spec_def_present(self):
        schema = self._load_schema()
        assert "agentSpec" in schema["$defs"]

    def test_agent_llm_def_present(self):
        schema = self._load_schema()
        assert "agentLlm" in schema["$defs"]

    def test_agent_tools_def_present(self):
        schema = self._load_schema()
        assert "agentTools" in schema["$defs"]

    def test_service_config_def_present(self):
        schema = self._load_schema()
        assert "serviceConfig" in schema["$defs"]

    def test_webhook_source_def_present(self):
        schema = self._load_schema()
        assert "webhookSource" in schema["$defs"]

    def test_human_interaction_def_present(self):
        schema = self._load_schema()
        assert "humanInteraction" in schema["$defs"]

    def test_spec_agents_array_type(self):
        schema = self._load_schema()
        agents_prop = schema["properties"]["spec"]["properties"]["agents"]
        assert agents_prop["type"] == "array"

    def test_runtime_service_ref(self):
        schema = self._load_schema()
        runtime_props = schema["$defs"]["runtime"]["properties"]
        assert "service" in runtime_props

    def test_agent_spec_required_fields(self):
        schema = self._load_schema()
        required = schema["$defs"]["agentSpec"]["required"]
        assert "name" in required
        assert "identity" in required

    def test_spec_identity_not_required(self):
        """spec.identity is no longer in 'required' list (can be omitted with spec.agents)."""
        schema = self._load_schema()
        spec_required = schema["properties"]["spec"]["required"]
        assert "identity" not in spec_required


# ---------------------------------------------------------------------------
# init scaffolding: --agents and --service
# ---------------------------------------------------------------------------

class TestInitScaffolding:
    def _make_config(self, agent_names=None, service_mode=None):
        from zil.commands.init import InitConfig
        return InitConfig(
            name="team-agent",
            framework="adk",
            language="python",
            llm_provider="gemini",
            eval_framework="deepeval",
            deploy_target="cloud-run",
            include_evals=False,
            include_otel=False,
            mcp_preset=None,
            agent_names=agent_names or [],
            service_mode=service_mode,
        )

    def test_manifest_contains_agents_block(self):
        from zil.templates.files import _manifest
        config = self._make_config(agent_names=["vta", "vtd"])
        content = _manifest(config)
        assert "agents:" in content
        assert "name: vta" in content
        assert "name: vtd" in content

    def test_manifest_no_agents_no_block(self):
        from zil.templates.files import _manifest
        config = self._make_config()
        content = _manifest(config)
        assert "agents:" not in content

    def test_manifest_contains_service_block(self):
        from zil.templates.files import _manifest
        config = self._make_config(service_mode="webhook")
        content = _manifest(config)
        assert "service:" in content
        assert "entry_point: webhook" in content

    def test_manifest_no_service_no_block(self):
        from zil.templates.files import _manifest
        config = self._make_config()
        content = _manifest(config)
        assert "entry_point:" not in content

    def test_sub_agent_identity_files_created(self, tmp_path):
        from zil.templates.files import _render_extra_files
        config = self._make_config(agent_names=["vta", "vtd"])
        _render_extra_files(tmp_path, config)
        assert (tmp_path / "agents" / "vta" / "identity" / "persona.md").is_file()
        assert (tmp_path / "agents" / "vtd" / "identity" / "instructions.md").is_file()

    def test_no_extra_files_without_agents(self, tmp_path):
        from zil.templates.files import _render_extra_files
        config = self._make_config()
        _render_extra_files(tmp_path, config)
        assert not (tmp_path / "agents").exists()

    def test_webhook_scaffold_creates_app_py(self, tmp_path):
        from zil.templates.files import _render_extra_files
        config = self._make_config(service_mode="webhook")
        (tmp_path / config.module_name).mkdir()
        _render_extra_files(tmp_path, config)
        assert (tmp_path / config.module_name / "app.py").is_file()

    def test_webhook_scaffold_creates_runner_py(self, tmp_path):
        from zil.templates.files import _render_extra_files
        config = self._make_config(service_mode="webhook")
        (tmp_path / config.module_name).mkdir()
        _render_extra_files(tmp_path, config)
        assert (tmp_path / config.module_name / "runner.py").is_file()

    def test_app_py_contains_health_endpoint(self, tmp_path):
        from zil.templates.files import _webhook_app_py
        config = self._make_config(service_mode="webhook")
        content = _webhook_app_py(config)
        assert "/health" in content

    def test_app_py_contains_human_respond_endpoint(self, tmp_path):
        from zil.templates.files import _webhook_app_py
        config = self._make_config(service_mode="webhook")
        content = _webhook_app_py(config)
        assert "/human/respond" in content

    def test_runner_py_contains_session_db_uri(self, tmp_path):
        from zil.templates.files import _webhook_runner_py
        config = self._make_config(service_mode="webhook")
        content = _webhook_runner_py(config)
        assert "SESSION_DB_URI" in content
        assert "sqlite+aiosqlite" in content

    def test_runner_py_contains_state_delta(self, tmp_path):
        from zil.templates.files import _webhook_runner_py
        config = self._make_config(service_mode="webhook")
        content = _webhook_runner_py(config)
        assert "state_delta" in content
