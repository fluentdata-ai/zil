"""Tests for the zil deploy command and zil web --docker."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml
from click.testing import CliRunner

from zil.cli import cli

runner = CliRunner()


def _scaffold_project(tmp_path: Path) -> Path:
    """Create a minimal Zil project for deploy tests."""
    manifest = {
        "apiVersion": "zil/v1",
        "kind": "Agent",
        "metadata": {"name": "test-agent", "version": "0.1.0"},
        "spec": {
            "runtime": {
                "framework": "adk",
                "language": "python",
            },
            "identity": "./identity",
        },
    }
    (tmp_path / "manifest.yaml").write_text(yaml.dump(manifest))
    module_dir = tmp_path / "test_agent"
    module_dir.mkdir()
    (module_dir / "__init__.py").write_text("")
    (module_dir / "agent.py").write_text("# stub")
    (tmp_path / "Dockerfile").write_text("FROM python:3.12-slim\n")
    (module_dir / ".env").write_text("GOOGLE_API_KEY=test\n")
    return tmp_path


class TestDeployHelp:
    def test_help_output(self):
        result = runner.invoke(cli, ["deploy", "--help"])
        assert result.exit_code == 0
        assert "--project" in result.output
        assert "--region" in result.output
        assert "--trace" in result.output
        assert "--local" not in result.output


class TestDeployCloudRun:
    @patch("zil.commands.deploy.subprocess.call", return_value=0)
    @patch("zil.commands.deploy.shutil.which", return_value="/usr/bin/gcloud")
    def test_cloud_run_requires_project(self, mock_which, mock_call, tmp_path):
        project = _scaffold_project(tmp_path)
        with patch.dict(
            "os.environ",
            {"GOOGLE_CLOUD_PROJECT": "", "GOOGLE_CLOUD_REGION": ""},
            clear=False,
        ):
            with patch("zil.commands.deploy.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=1, stdout="", stderr=""
                )
                result = runner.invoke(
                    cli,
                    [
                        "deploy", "--skip-evals",
                        "--project-dir", str(project),
                    ],
                )
        assert result.exit_code == 1
        assert "GCP project" in result.output

    @patch("zil.commands.deploy.subprocess.call", return_value=0)
    @patch("zil.commands.deploy.subprocess.run")
    @patch("zil.commands.deploy.shutil.which", return_value="/usr/bin/gcloud")
    def test_cloud_run_deploys_with_flags(
        self, mock_which, mock_run, mock_call, tmp_path
    ):
        project = _scaffold_project(tmp_path)
        mock_run.return_value = MagicMock(
            returncode=0, stdout="my-project\n", stderr=""
        )

        result = runner.invoke(
            cli,
            [
                "deploy", "--skip-evals",
                "--project-dir", str(project),
                "--project", "my-project",
                "--region", "us-central1",
            ],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        call_args = mock_call.call_args[0][0]
        assert "adk" in call_args
        assert "deploy" in call_args
        assert "cloud_run" in call_args
        assert "--project=my-project" in call_args
        assert "--region=us-central1" in call_args

    @patch("zil.commands.deploy.subprocess.call", return_value=0)
    @patch("zil.commands.deploy.subprocess.run")
    @patch("zil.commands.deploy.shutil.which", return_value="/usr/bin/gcloud")
    def test_cloud_run_with_trace_passes_otel_flag(
        self, mock_which, mock_run, mock_call, tmp_path
    ):
        project = _scaffold_project(tmp_path)
        mock_run.return_value = MagicMock(
            returncode=0, stdout="", stderr=""
        )

        result = runner.invoke(
            cli,
            [
                "deploy", "--skip-evals", "--trace",
                "--project-dir", str(project),
                "--project", "my-project",
                "--region", "us-east1",
            ],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        call_args = mock_call.call_args[0][0]
        assert "--otel_to_cloud" in call_args

    @patch("zil.commands.deploy.subprocess.call", return_value=0)
    @patch("zil.commands.deploy.subprocess.run")
    @patch("zil.commands.deploy.shutil.which", return_value="/usr/bin/gcloud")
    def test_cloud_run_with_ui_flag(
        self, mock_which, mock_run, mock_call, tmp_path
    ):
        project = _scaffold_project(tmp_path)
        mock_run.return_value = MagicMock(
            returncode=0, stdout="", stderr=""
        )

        result = runner.invoke(
            cli,
            [
                "deploy", "--skip-evals", "--with-ui",
                "--project-dir", str(project),
                "--project", "p", "--region", "r",
            ],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        call_args = mock_call.call_args[0][0]
        assert "--with_ui" in call_args


class TestWebDockerMode:
    @patch("zil.commands._docker.subprocess.run")
    @patch("zil.commands._docker.subprocess.call", return_value=0)
    @patch("zil.commands._docker.shutil.which", return_value="/usr/bin/docker")
    def test_docker_builds_and_runs(
        self, mock_which, mock_call, mock_run, tmp_path
    ):
        project = _scaffold_project(tmp_path)
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        result = runner.invoke(
            cli,
            [
                "web", "--docker",
                "--project-dir", str(project),
            ],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        build_calls = [
            c for c in mock_run.call_args_list
            if "build" in str(c)
        ]
        assert len(build_calls) >= 1

    @patch("zil.commands._docker.subprocess.run")
    @patch("zil.commands._docker.subprocess.call", return_value=0)
    @patch("zil.commands._docker.shutil.which", return_value="/usr/bin/docker")
    def test_docker_with_trace_starts_otel_stack(
        self, mock_which, mock_call, mock_run, tmp_path
    ):
        project = _scaffold_project(tmp_path)

        def side_effect(*args, **kwargs):
            m = MagicMock()
            m.returncode = 0
            m.stdout = "abc123container"
            m.stderr = ""
            return m

        mock_run.side_effect = side_effect

        result = runner.invoke(
            cli,
            [
                "web", "--docker", "--trace",
                "--project-dir", str(project),
            ],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert "Grafana LGTM" in result.output

    @patch("zil.commands._docker.shutil.which", return_value=None)
    def test_docker_fails_without_docker(self, mock_which, tmp_path):
        project = _scaffold_project(tmp_path)
        result = runner.invoke(
            cli,
            [
                "web", "--docker",
                "--project-dir", str(project),
            ],
        )
        assert result.exit_code == 1
        assert "Docker" in result.output

    def test_web_help_shows_docker_flag(self):
        result = runner.invoke(cli, ["web", "--help"])
        assert "--docker" in result.output


class TestResolveGcpProject:
    def test_flag_takes_precedence(self):
        from zil.commands.deploy import _resolve_gcp_project

        assert _resolve_gcp_project("my-flag-project") == "my-flag-project"

    def test_env_var_fallback(self):
        from zil.commands.deploy import _resolve_gcp_project

        with patch.dict("os.environ", {"GOOGLE_CLOUD_PROJECT": "env-proj"}):
            assert _resolve_gcp_project(None) == "env-proj"

    @patch("zil.commands.deploy.subprocess.run")
    def test_gcloud_config_fallback(self, mock_run):
        from zil.commands.deploy import _resolve_gcp_project

        mock_run.return_value = MagicMock(
            returncode=0, stdout="gcloud-proj\n", stderr=""
        )
        with patch.dict(
            "os.environ", {"GOOGLE_CLOUD_PROJECT": ""}, clear=False
        ):
            assert _resolve_gcp_project(None) == "gcloud-proj"


class TestResolveGcpRegion:
    def test_flag_takes_precedence(self):
        from zil.commands.deploy import _resolve_gcp_region

        assert _resolve_gcp_region("us-west1") == "us-west1"

    def test_env_var_fallback(self):
        from zil.commands.deploy import _resolve_gcp_region

        with patch.dict("os.environ", {"GOOGLE_CLOUD_REGION": "eu-west1"}):
            assert _resolve_gcp_region(None) == "eu-west1"

    def test_returns_none_when_unavailable(self):
        from zil.commands.deploy import _resolve_gcp_region

        with patch.dict(
            "os.environ", {"GOOGLE_CLOUD_REGION": ""}, clear=False
        ):
            assert _resolve_gcp_region(None) is None


class TestEvalGate:
    @patch("zil.commands.deploy.subprocess.run")
    @patch("zil.commands.deploy.subprocess.call", return_value=0)
    @patch("zil.commands.deploy.shutil.which", return_value="/usr/bin/gcloud")
    def test_eval_failure_blocks_deploy(
        self, mock_which, mock_call, mock_run, tmp_path
    ):
        project = _scaffold_project(tmp_path)
        mock_run.return_value = MagicMock(
            returncode=0, stdout="my-proj\n", stderr=""
        )

        mock_eval_result = MagicMock()
        mock_eval_result.passed = False
        mock_eval_result.score = 0.5
        mock_eval_result.threshold = 0.85

        with patch(
            "zil.sdk.eval.run_eval_suite", return_value=mock_eval_result
        ):
            result = runner.invoke(
                cli,
                [
                    "deploy",
                    "--project-dir", str(project),
                    "--project", "my-proj",
                    "--region", "us-central1",
                ],
            )

        assert result.exit_code == 1
        assert "blocked" in result.output.lower()
        assert "50.0%" in result.output
        # adk deploy should NOT have been called
        mock_call.assert_not_called()

    @patch("zil.commands.deploy.subprocess.run")
    @patch("zil.commands.deploy.subprocess.call", return_value=0)
    @patch("zil.commands.deploy.shutil.which", return_value="/usr/bin/gcloud")
    def test_skip_evals_bypasses_gate(
        self, mock_which, mock_call, mock_run, tmp_path
    ):
        project = _scaffold_project(tmp_path)
        mock_run.return_value = MagicMock(
            returncode=0, stdout="my-proj\n", stderr=""
        )

        result = runner.invoke(
            cli,
            [
                "deploy", "--skip-evals",
                "--project-dir", str(project),
                "--project", "my-proj",
                "--region", "us-central1",
            ],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert "eval" not in result.output.lower()
