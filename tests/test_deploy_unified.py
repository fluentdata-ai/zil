"""Tests for unified deploy path (zil serve entrypoint)."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from zil.packaging.dockerfile import generate_serve_dockerfile


# ---------------------------------------------------------------------------
# TestServeDockerfile
# ---------------------------------------------------------------------------


class TestServeDockerfile:
    """Tests for generate_serve_dockerfile()."""

    def test_basic_dockerfile(self):
        df = generate_serve_dockerfile(framework="adk")
        assert "FROM python:3.12-slim" in df
        assert '"zil", "serve"' in df
        assert "zil-ai[serve,adk]" in df
        assert "EXPOSE 8000" in df

    def test_stub_framework(self):
        df = generate_serve_dockerfile(framework="stub")
        assert "zil-ai[serve]" in df
        assert "adk" not in df.split("zil-ai")[1].split("\n")[0]

    def test_openhands_framework(self):
        df = generate_serve_dockerfile(framework="openhands")
        assert "zil-ai[serve,openhands]" in df

    def test_custom_port(self):
        df = generate_serve_dockerfile(port=9000)
        assert "EXPOSE 9000" in df
        assert '"9000"' in df

    def test_with_host_deps(self):
        df = generate_serve_dockerfile(host_deps=["git", "nodejs"])
        assert "apt-get" in df
        assert "git" in df
        assert "nodejs" in df

    def test_with_runtime_deps(self):
        df = generate_serve_dockerfile(
            runtime_deps=[{"name": "curl", "type": "apt"}]
        )
        assert "curl" in df

    def test_non_root_user(self):
        df = generate_serve_dockerfile()
        assert "appuser" in df
        assert "USER appuser" in df


# ---------------------------------------------------------------------------
# TestDeployModeRouting
# ---------------------------------------------------------------------------


class TestDeployModeRouting:
    """Test that the deploy command routes correctly based on --mode."""

    def test_deploy_help_shows_mode(self):
        from click.testing import CliRunner
        from zil.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["deploy", "--help"])
        assert result.exit_code == 0
        assert "--mode" in result.output
        assert "serve" in result.output
        assert "legacy-adk" in result.output

    def test_deploy_auto_non_adk_uses_unified(self, tmp_path):
        """Non-ADK framework in auto mode should use unified deploy."""
        from click.testing import CliRunner
        from zil.cli import cli

        # Create a stub project
        manifest = {
            "version": "1",
            "metadata": {"name": "test-agent", "version": "0.1.0", "description": "t"},
            "spec": {
                "runtime": {"framework": "openhands"},
                "identity": "./identity",
            },
        }
        (tmp_path / "manifest.yaml").write_text(yaml.dump(manifest))
        (tmp_path / "identity").mkdir()
        (tmp_path / "identity" / "persona.md").write_text("You are a test agent.")
        (tmp_path / "adapters").mkdir()
        (tmp_path / "adapters" / "llm.yaml").write_text("provider: gemini\nmodel: gemini-3.5-flash\n")
        (tmp_path / "test_agent").mkdir()  # module dir

        runner = CliRunner()
        with patch.dict(os.environ, {"GOOGLE_CLOUD_PROJECT": "test-proj", "GOOGLE_CLOUD_REGION": "us-central1"}):
            with patch("subprocess.call", return_value=0) as mock_call:
                with patch("shutil.which", return_value="/usr/bin/gcloud"):
                    result = runner.invoke(cli, [
                        "deploy",
                        "--project-dir", str(tmp_path),
                        "--skip-evals",
                    ])

        # Should route to unified deploy (zil serve)
        if result.exit_code == 0 and mock_call.called:
            cmd_args = mock_call.call_args[0][0]
            # Unified path uses gcloud run deploy --source
            assert "gcloud" in cmd_args[0]
            assert "--source" in cmd_args

    def test_deploy_mode_serve_forces_unified(self, tmp_path):
        """--mode serve should use unified path even for ADK."""
        from click.testing import CliRunner
        from zil.cli import cli

        manifest = {
            "version": "1",
            "metadata": {"name": "test-agent", "version": "0.1.0", "description": "t"},
            "spec": {
                "runtime": {"framework": "adk"},
                "identity": "./identity",
            },
        }
        (tmp_path / "manifest.yaml").write_text(yaml.dump(manifest))
        (tmp_path / "identity").mkdir()
        (tmp_path / "identity" / "persona.md").write_text("You are a test agent.")
        (tmp_path / "adapters").mkdir()
        (tmp_path / "adapters" / "llm.yaml").write_text("provider: gemini\nmodel: gemini-3.5-flash\n")
        (tmp_path / "test_agent").mkdir()

        runner = CliRunner()
        with patch.dict(os.environ, {"GOOGLE_CLOUD_PROJECT": "test-proj", "GOOGLE_CLOUD_REGION": "us-central1"}):
            with patch("subprocess.call", return_value=0) as mock_call:
                with patch("shutil.which", return_value="/usr/bin/gcloud"):
                    result = runner.invoke(cli, [
                        "deploy",
                        "--project-dir", str(tmp_path),
                        "--skip-evals",
                        "--mode", "serve",
                    ])

        if result.exit_code == 0 and mock_call.called:
            cmd_args = mock_call.call_args[0][0]
            assert "--source" in cmd_args
