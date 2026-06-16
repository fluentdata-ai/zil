"""Tests for spec.env declarations, deploy env resolution, and AgentConfig."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from zil.commands.deploy import _parse_env_file, _resolve_env_vars
from zil.schema.loader import validate_project
from zil.sdk.config import AgentConfig, MissingConfigError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MINIMAL_MANIFEST = {
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


def _make_project(tmp_path: Path, manifest_extra: dict | None = None) -> Path:
    """Create a minimal valid project directory for testing."""
    manifest = {**MINIMAL_MANIFEST}
    if manifest_extra:
        manifest["spec"] = {**manifest["spec"], **manifest_extra}
    (tmp_path / "manifest.yaml").write_text(yaml.dump(manifest))
    (tmp_path / "identity").mkdir()
    (tmp_path / "identity" / "persona.md").write_text("# Test persona")
    (tmp_path / "identity" / "instructions.md").write_text("# Test instructions")
    (tmp_path / "identity" / "guardrails.yaml").write_text("hard_blocks: []")
    (tmp_path / "adapters").mkdir()
    (tmp_path / "adapters" / "llm.yaml").write_text(
        "provider: gemini\nmodel: gemini-2.0-flash\nauth:\n  env_var: GOOGLE_API_KEY\n"
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------

class TestSchemaValidation:
    """Tests for spec.env schema validation."""

    def test_valid_env_declarations(self, tmp_path: Path) -> None:
        """Valid spec.env passes schema validation (no errors)."""
        env = [
            {"name": "GOOGLE_API_KEY", "description": "API key", "required": True, "secret": True},
            {"name": "OTEL_ENDPOINT", "required": False, "default": "http://localhost:4318"},
        ]
        project_dir = _make_project(tmp_path, {"env": env})
        result = validate_project(project_dir)
        assert result.exit_code != 1, [c.message for c in result.checks if c.status == "fail"]

    def test_env_missing_warns(self, tmp_path: Path) -> None:
        """No spec.env produces a warning."""
        project_dir = _make_project(tmp_path)
        result = validate_project(project_dir)
        messages = [c.message for c in result.checks if c.status == "warn"]
        assert any("spec.env" in m and "not declared" in m for m in messages)

    def test_env_count_reported(self, tmp_path: Path) -> None:
        """Validation reports the number of declared env vars."""
        env = [
            {"name": "VAR_ONE", "secret": True},
            {"name": "VAR_TWO", "secret": False},
            {"name": "VAR_THREE", "secret": True},
        ]
        project_dir = _make_project(tmp_path, {"env": env})
        result = validate_project(project_dir)
        messages = [c.message for c in result.checks if c.status == "pass"]
        assert any("3 variable(s) declared (2 secret)" in m for m in messages)

    def test_adapter_env_var_cross_reference_warns(self, tmp_path: Path) -> None:
        """Warn when adapter references an env_var not in spec.env."""
        env = [{"name": "SOMETHING_ELSE", "secret": False}]
        project_dir = _make_project(tmp_path, {"env": env})
        result = validate_project(project_dir)
        messages = [c.message for c in result.checks if c.status == "warn"]
        assert any("GOOGLE_API_KEY" in m and "not declared" in m for m in messages)

    def test_adapter_env_var_declared_no_warn(self, tmp_path: Path) -> None:
        """No warning when adapter env_var IS declared in spec.env."""
        env = [{"name": "GOOGLE_API_KEY", "secret": True}]
        project_dir = _make_project(tmp_path, {"env": env})
        result = validate_project(project_dir)
        messages = [c.message for c in result.checks if c.status == "warn"]
        assert not any("GOOGLE_API_KEY" in m for m in messages)


# ---------------------------------------------------------------------------
# Deploy env resolution tests
# ---------------------------------------------------------------------------

class TestEnvResolution:
    """Tests for _resolve_env_vars and _parse_env_file."""

    def test_parse_env_file_basic(self, tmp_path: Path) -> None:
        """Parse simple key=value env file."""
        env_file = tmp_path / ".env"
        env_file.write_text("KEY1=value1\nKEY2=value2\n")
        result = _parse_env_file(env_file)
        assert result == {"KEY1": "value1", "KEY2": "value2"}

    def test_parse_env_file_with_quotes(self, tmp_path: Path) -> None:
        """Strips surrounding quotes from values."""
        env_file = tmp_path / ".env"
        env_file.write_text('KEY1="quoted value"\nKEY2=\'single\'\n')
        result = _parse_env_file(env_file)
        assert result == {"KEY1": "quoted value", "KEY2": "single"}

    def test_parse_env_file_ignores_comments(self, tmp_path: Path) -> None:
        """Skips comment lines and blank lines."""
        env_file = tmp_path / ".env"
        env_file.write_text("# comment\n\nKEY=val\n")
        result = _parse_env_file(env_file)
        assert result == {"KEY": "val"}

    def test_resolve_from_file(self, tmp_path: Path) -> None:
        """Resolves env vars from a provided env file."""
        env_file = tmp_path / ".env.prod"
        env_file.write_text("API_KEY=sk-123\nDB_URL=postgres://...\n")
        manifest = {
            "spec": {
                "env": [
                    {"name": "API_KEY", "required": True, "secret": True},
                    {"name": "DB_URL", "required": True},
                ]
            }
        }
        result = _resolve_env_vars(manifest, env_file)
        assert result == {"API_KEY": "sk-123", "DB_URL": "postgres://..."}

    def test_resolve_missing_required_raises(self, tmp_path: Path) -> None:
        """SystemExit when required var is missing from env file."""
        env_file = tmp_path / ".env"
        env_file.write_text("OTHER=something\n")
        manifest = {
            "spec": {
                "env": [
                    {"name": "REQUIRED_VAR", "required": True},
                ]
            }
        }
        with pytest.raises(SystemExit):
            _resolve_env_vars(manifest, env_file)

    def test_resolve_optional_missing_ok(self, tmp_path: Path) -> None:
        """Optional vars that are missing don't cause failure."""
        env_file = tmp_path / ".env"
        env_file.write_text("API_KEY=val\n")
        manifest = {
            "spec": {
                "env": [
                    {"name": "API_KEY", "required": True},
                    {"name": "OPTIONAL", "required": False},
                ]
            }
        }
        result = _resolve_env_vars(manifest, env_file)
        assert result == {"API_KEY": "val"}

    def test_resolve_default_applied(self, tmp_path: Path) -> None:
        """Default values applied when var not in env file."""
        env_file = tmp_path / ".env"
        env_file.write_text("")
        manifest = {
            "spec": {
                "env": [
                    {"name": "ENDPOINT", "required": False, "default": "http://localhost:4318"},
                ]
            }
        }
        result = _resolve_env_vars(manifest, env_file)
        assert result == {"ENDPOINT": "http://localhost:4318"}

    def test_resolve_no_declarations(self) -> None:
        """No env declarations returns empty dict."""
        manifest = {"spec": {}}
        result = _resolve_env_vars(manifest, None)
        assert result == {}

    def test_resolve_forwards_undeclared_infra_vars(self, tmp_path: Path) -> None:
        """Platform-injected vars not in spec.env are forwarded from the file.

        Registry discovery relies on the runtime writing ZIL_FLEET_REGISTRY_URL
        (+ token) to --env-file; these are intentionally not declared in user
        manifests, so they must still reach the deployed container.
        """
        env_file = tmp_path / ".env.deploy"
        env_file.write_text(
            "GOOGLE_API_KEY=sk-123\n"
            "ZIL_FLEET_REGISTRY_URL=https://example.com/api/registry/ws-1\n"
            "ZIL_FLEET_REGISTRY_TOKEN=secret-token\n"
        )
        manifest = {
            "spec": {
                "env": [
                    {"name": "GOOGLE_API_KEY", "required": True, "secret": True},
                ]
            }
        }
        result = _resolve_env_vars(manifest, env_file)
        assert result == {
            "GOOGLE_API_KEY": "sk-123",
            "ZIL_FLEET_REGISTRY_URL": "https://example.com/api/registry/ws-1",
            "ZIL_FLEET_REGISTRY_TOKEN": "secret-token",
        }

    def test_resolve_forwards_infra_vars_with_no_declarations(
        self, tmp_path: Path
    ) -> None:
        """Env-file vars are forwarded even when the manifest declares no env."""
        env_file = tmp_path / ".env.deploy"
        env_file.write_text("ZIL_FLEET_REGISTRY_URL=https://example.com/r\n")
        result = _resolve_env_vars({"spec": {}}, env_file)
        assert result == {"ZIL_FLEET_REGISTRY_URL": "https://example.com/r"}

    def test_resolve_file_not_found(self, tmp_path: Path) -> None:
        """SystemExit when env file path doesn't exist."""
        manifest = {"spec": {"env": [{"name": "X", "required": True}]}}
        with pytest.raises(SystemExit):
            _resolve_env_vars(manifest, tmp_path / "nonexistent.env")


# ---------------------------------------------------------------------------
# AgentConfig tests
# ---------------------------------------------------------------------------

class TestAgentConfig:
    """Tests for the AgentConfig runtime config object."""

    def test_getitem(self) -> None:
        """Access a resolved value via []."""
        config = AgentConfig()
        with patch.dict(os.environ, {"MY_KEY": "my_value"}):
            config._initialize([{"name": "MY_KEY", "required": True}])
        assert config["MY_KEY"] == "my_value"

    def test_getitem_missing_raises(self) -> None:
        """Accessing an undeclared var raises KeyError."""
        config = AgentConfig()
        config._initialize([{"name": "EXISTS", "required": False, "default": "x"}])
        with pytest.raises(KeyError, match="not declared"):
            config["UNDECLARED"]

    def test_get_with_default(self) -> None:
        """get() returns fallback for missing optional vars."""
        config = AgentConfig()
        config._initialize([{"name": "OPT", "required": False}])
        assert config.get("OPT", "fallback") == "fallback"

    def test_missing_required_raises_on_init(self) -> None:
        """MissingConfigError raised during _initialize for missing required vars."""
        config = AgentConfig()
        with patch.dict(os.environ, {}, clear=True):
            # Remove the var from env if it exists
            os.environ.pop("REQUIRED_VAR", None)
            with pytest.raises(MissingConfigError, match="REQUIRED_VAR"):
                config._initialize([
                    {"name": "REQUIRED_VAR", "required": True, "description": "test var"},
                ])

    def test_default_applied(self) -> None:
        """Default value used when env var is not set."""
        config = AgentConfig()
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("WITH_DEFAULT", None)
            config._initialize([
                {"name": "WITH_DEFAULT", "required": False, "default": "default_val"},
            ])
        assert config["WITH_DEFAULT"] == "default_val"

    def test_env_overrides_default(self) -> None:
        """Env var takes precedence over default."""
        config = AgentConfig()
        with patch.dict(os.environ, {"MY_VAR": "from_env"}):
            config._initialize([
                {"name": "MY_VAR", "required": True, "default": "from_default"},
            ])
        assert config["MY_VAR"] == "from_env"

    def test_is_secret(self) -> None:
        """is_secret() returns True for vars marked secret."""
        config = AgentConfig()
        with patch.dict(os.environ, {"SECRET": "hidden", "PLAIN": "visible"}):
            config._initialize([
                {"name": "SECRET", "required": True, "secret": True},
                {"name": "PLAIN", "required": True, "secret": False},
            ])
        assert config.is_secret("SECRET") is True
        assert config.is_secret("PLAIN") is False

    def test_contains(self) -> None:
        """in operator works for checking presence."""
        config = AgentConfig()
        with patch.dict(os.environ, {"PRESENT": "yes"}):
            config._initialize([{"name": "PRESENT", "required": True}])
        assert "PRESENT" in config
        assert "ABSENT" not in config

    def test_len_and_iter(self) -> None:
        """len() and iteration work correctly."""
        config = AgentConfig()
        with patch.dict(os.environ, {"A": "1", "B": "2"}):
            config._initialize([
                {"name": "A", "required": True},
                {"name": "B", "required": True},
            ])
        assert len(config) == 2
        assert set(config) == {"A", "B"}

    def test_repr_redacts_secrets(self) -> None:
        """repr() masks secret values."""
        config = AgentConfig()
        with patch.dict(os.environ, {"KEY": "sk-123", "PLAIN": "visible"}):
            config._initialize([
                {"name": "KEY", "required": True, "secret": True},
                {"name": "PLAIN", "required": True, "secret": False},
            ])
        r = repr(config)
        assert "sk-123" not in r
        assert "***" in r
        assert "visible" in r

    def test_not_initialized_raises(self) -> None:
        """Accessing config before initialization raises RuntimeError."""
        config = AgentConfig()
        with pytest.raises(RuntimeError, match="not initialized"):
            config["ANYTHING"]

    def test_loads_env_local_from_module_dir(self, tmp_path: Path) -> None:
        """_initialize loads .env.local from module_dir into os.environ."""
        module_dir = tmp_path / "my_agent"
        module_dir.mkdir()
        (module_dir / ".env.local").write_text("TEST_FROM_DOTENV=dotenv_value\n")

        config = AgentConfig()
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("TEST_FROM_DOTENV", None)
            config._initialize(
                [{"name": "TEST_FROM_DOTENV", "required": True}],
                module_dir=module_dir,
            )
        assert config["TEST_FROM_DOTENV"] == "dotenv_value"
        # Clean up
        os.environ.pop("TEST_FROM_DOTENV", None)

    def test_loads_env_from_project_dir(self, tmp_path: Path) -> None:
        """_initialize loads .env from project_dir."""
        (tmp_path / ".env").write_text("PROJ_VAR=from_project\n")

        config = AgentConfig()
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("PROJ_VAR", None)
            config._initialize(
                [{"name": "PROJ_VAR", "required": True}],
                project_dir=tmp_path,
            )
        assert config["PROJ_VAR"] == "from_project"
        os.environ.pop("PROJ_VAR", None)

    def test_existing_env_not_overridden(self, tmp_path: Path) -> None:
        """Real os.environ values take precedence over .env.local."""
        (tmp_path / ".env.local").write_text("MY_EXISTING=from_file\n")

        config = AgentConfig()
        with patch.dict(os.environ, {"MY_EXISTING": "from_real_env"}):
            config._initialize(
                [{"name": "MY_EXISTING", "required": True}],
                module_dir=tmp_path,
            )
        assert config["MY_EXISTING"] == "from_real_env"

    def test_module_dir_env_overrides_project_dir(self, tmp_path: Path) -> None:
        """Module dir .env.local fills in after project dir .env.local."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        module_dir = project_dir / "my_agent"
        module_dir.mkdir()
        (project_dir / ".env.local").write_text("SHARED=from_project\nPROJ_ONLY=proj\n")
        (module_dir / ".env.local").write_text("SHARED=from_module\nMOD_ONLY=mod\n")

        config = AgentConfig()
        with patch.dict(os.environ, {}, clear=True):
            for k in ("SHARED", "PROJ_ONLY", "MOD_ONLY"):
                os.environ.pop(k, None)
            config._initialize(
                [
                    {"name": "SHARED", "required": True},
                    {"name": "PROJ_ONLY", "required": True},
                    {"name": "MOD_ONLY", "required": True},
                ],
                project_dir=project_dir,
                module_dir=module_dir,
            )
        # Project loads first, so SHARED comes from project (never overridden)
        assert config["SHARED"] == "from_project"
        assert config["PROJ_ONLY"] == "proj"
        assert config["MOD_ONLY"] == "mod"
        for k in ("SHARED", "PROJ_ONLY", "MOD_ONLY"):
            os.environ.pop(k, None)
