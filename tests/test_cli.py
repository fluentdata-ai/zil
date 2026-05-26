"""Tests for the Zil CLI."""

import json
from pathlib import Path

from click.testing import CliRunner

from zil.cli import cli


runner = CliRunner()


class TestCLIBasics:
    """Basic CLI smoke tests."""

    def test_help(self):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Zil" in result.output
        assert "init" in result.output
        assert "validate" in result.output
        assert "pack" in result.output
        assert "inspect" in result.output

    def test_version(self):
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "0.1." in result.output

    def test_init_help(self):
        result = runner.invoke(cli, ["init", "--help"])
        assert result.exit_code == 0
        assert "Scaffold" in result.output

    def test_validate_help(self):
        result = runner.invoke(cli, ["validate", "--help"])
        assert result.exit_code == 0
        assert "Validate" in result.output

    def test_pack_help(self):
        result = runner.invoke(cli, ["pack", "--help"])
        assert result.exit_code == 0

    def test_inspect_help(self):
        result = runner.invoke(cli, ["inspect", "--help"])
        assert result.exit_code == 0

    def test_run_help(self):
        result = runner.invoke(cli, ["run", "--help"])
        assert result.exit_code == 0
        assert "Run the agent" in result.output

    def test_web_help(self):
        result = runner.invoke(cli, ["web", "--help"])
        assert result.exit_code == 0
        assert "web UI" in result.output


class TestInit:
    """Tests for zil init."""

    def test_init_creates_project(self, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["init", "my-agent", "--non-interactive", "--skip-install"], catch_exceptions=False)
            assert result.exit_code == 0
            project = Path("my-agent")
            assert project.exists()
            assert (project / "manifest.yaml").exists()
            assert (project / "identity" / "persona.md").exists()
            assert (project / "identity" / "instructions.md").exists()
            assert (project / "identity" / "guardrails.yaml").exists()
            assert (project / "adapters" / "llm.yaml").exists()
            assert (project / "adapters" / "embed.yaml").exists()
            assert (project / "my_agent" / "__init__.py").exists()
            assert (project / "my_agent" / "agent.py").exists()
            assert (project / "my_agent" / ".env.example").exists()
            assert (project / "README.md").exists()
            assert (project / ".gitignore").exists()

    def test_init_duplicate_fails(self, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["init", "dup-agent", "--non-interactive", "--skip-install"], catch_exceptions=False)
            result = runner.invoke(cli, ["init", "dup-agent", "--non-interactive", "--skip-install"])
            assert result.exit_code == 1


class TestValidate:
    """Tests for zil validate."""

    def test_validate_missing_manifest(self, tmp_path):
        result = runner.invoke(cli, ["validate", "--project-dir", str(tmp_path)])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_validate_scaffolded_project(self, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["init", "val-agent", "--non-interactive", "--skip-install"], catch_exceptions=False)
            result = runner.invoke(cli, ["validate", "--project-dir", "val-agent"])
            # Should pass (exit 0) or warn (exit 2), but not fail
            assert result.exit_code in (0, 2)

    def test_validate_json_output(self, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["init", "json-agent", "--non-interactive", "--skip-install"], catch_exceptions=False)
            result = runner.invoke(cli, ["validate", "--project-dir", "json-agent", "--format=json"])
            parsed = json.loads(result.output)
            assert "valid" in parsed
            assert "checks" in parsed


class TestSchema:
    """Tests for the manifest JSON Schema."""

    def test_schema_loads(self):
        from zil.schema.loader import load_schema
        schema = load_schema()
        assert schema["title"] == "Zil Agent Manifest"
        assert "properties" in schema

    def test_valid_manifest_passes(self):
        import jsonschema
        from zil.schema.loader import load_schema

        schema = load_schema()
        manifest = {
            "apiVersion": "zil/v1",
            "kind": "Agent",
            "metadata": {"name": "test-agent", "version": "1.0.0"},
            "spec": {
                "runtime": {
                    "framework": "adk",
                    "language": "python",
                    "llm": {"adapter": "./adapters/llm.yaml"},
                },
                "identity": "./identity",
            },
        }
        jsonschema.validate(instance=manifest, schema=schema)

    def test_invalid_manifest_fails(self):
        import jsonschema
        import pytest
        from zil.schema.loader import load_schema

        schema = load_schema()
        bad_manifest = {"apiVersion": "zil/v1", "kind": "Agent"}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=bad_manifest, schema=schema)

    def test_invalid_name_fails(self):
        import jsonschema
        import pytest
        from zil.schema.loader import load_schema

        schema = load_schema()
        manifest = {
            "apiVersion": "zil/v1",
            "kind": "Agent",
            "metadata": {"name": "INVALID NAME!", "version": "1.0.0"},
            "spec": {
                "runtime": {
                    "framework": "adk",
                    "language": "python",
                    "llm": {"adapter": "./adapters/llm.yaml"},
                },
                "identity": "./identity",
            },
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=manifest, schema=schema)
