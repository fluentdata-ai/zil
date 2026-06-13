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



def _parse_json_from_output(output: str) -> dict:
    """Extract the JSON object from mixed Rich+JSON output."""
    import json
    start = output.index("{")
    return json.loads(output[start:])


class TestDeployOutputJson:
    """Tests for --output json and the structured deploy result."""

    def _deploy_with_json_output(self, tmp_path, service_cfg=None):
        """Helper: run zil deploy --output json with gcloud/adk fully mocked."""
        import yaml

        manifest = {
            "apiVersion": "zil/v1",
            "kind": "Agent",
            "metadata": {"name": "test-agent", "version": "0.1.0"},
            "spec": {
                "runtime": {
                    "framework": "adk",
                    "language": "python",
                    **({"service": service_cfg} if service_cfg else {}),
                },
                "identity": "./identity",
            },
        }
        (tmp_path / "manifest.yaml").write_text(yaml.dump(manifest))
        module_dir = tmp_path / "test_agent"
        module_dir.mkdir()
        (module_dir / "__init__.py").write_text("")

        with patch("zil.commands.deploy.subprocess.call", return_value=0), \
             patch("zil.commands.deploy.subprocess.run",
                   return_value=MagicMock(returncode=0, stdout="my-project\n", stderr="")), \
             patch("zil.commands.deploy.shutil.which", return_value="/usr/bin/gcloud"), \
             patch("zil.commands.deploy.subprocess.check_output",
                   return_value="https://test-agent-abc-uc.a.run.app\n"):
            return runner.invoke(
                cli,
                [
                    "deploy", "--skip-evals",
                    "--project-dir", str(tmp_path),
                    "--project", "my-project",
                    "--region", "us-central1",
                    "--output", "json",
                ],
                catch_exceptions=False,
            )

    def test_output_json_exit_code_zero(self, tmp_path):
        result = self._deploy_with_json_output(tmp_path)
        assert result.exit_code == 0

    def test_output_json_is_valid_json(self, tmp_path):
        result = self._deploy_with_json_output(tmp_path)
        parsed = _parse_json_from_output(result.output)
        assert isinstance(parsed, dict)

    def test_output_json_contains_service(self, tmp_path):
        result = self._deploy_with_json_output(tmp_path)
        parsed = _parse_json_from_output(result.output)
        assert parsed["service"] == "test-agent"

    def test_output_json_contains_project_and_region(self, tmp_path):
        result = self._deploy_with_json_output(tmp_path)
        parsed = _parse_json_from_output(result.output)
        assert parsed["project"] == "my-project"
        assert parsed["region"] == "us-central1"

    def test_output_json_contains_url(self, tmp_path):
        result = self._deploy_with_json_output(tmp_path)
        parsed = _parse_json_from_output(result.output)
        assert parsed["url"] == "https://test-agent-abc-uc.a.run.app"

    def test_output_json_contains_deployed_at(self, tmp_path):
        result = self._deploy_with_json_output(tmp_path)
        parsed = _parse_json_from_output(result.output)
        assert "deployed_at" in parsed
        assert parsed["deployed_at"].endswith("Z")

    def test_output_json_endpoints_contains_agent_url(self, tmp_path):
        result = self._deploy_with_json_output(tmp_path)
        parsed = _parse_json_from_output(result.output)
        assert parsed["endpoints"]["agent"] == "https://test-agent-abc-uc.a.run.app"

    def test_output_json_webhook_endpoints_present(self, tmp_path):
        result = self._deploy_with_json_output(tmp_path, service_cfg={
            "entry_point": "webhook",
            "webhooks": [{"name": "jira", "path": "/webhooks/jira"}],
        })
        parsed = _parse_json_from_output(result.output)
        assert "webhooks" in parsed["endpoints"]
        assert parsed["endpoints"]["webhooks"] == [
            "https://test-agent-abc-uc.a.run.app/webhooks/jira"
        ]

    def test_output_json_hitl_respond_present(self, tmp_path):
        result = self._deploy_with_json_output(tmp_path, service_cfg={
            "entry_point": "webhook",
            "human_interaction": {"enabled": True},
        })
        parsed = _parse_json_from_output(result.output)
        assert parsed["endpoints"]["hitl_respond"] == (
            "https://test-agent-abc-uc.a.run.app/human/respond"
        )

    def test_output_json_custom_hitl_response_path(self, tmp_path):
        result = self._deploy_with_json_output(tmp_path, service_cfg={
            "entry_point": "webhook",
            "human_interaction": {"enabled": True, "response_path": "/approvals"},
        })
        parsed = _parse_json_from_output(result.output)
        assert parsed["endpoints"]["hitl_respond"].endswith("/approvals")

    def test_output_json_no_webhooks_without_service_config(self, tmp_path):
        result = self._deploy_with_json_output(tmp_path)
        parsed = _parse_json_from_output(result.output)
        assert "webhooks" not in parsed["endpoints"]
        assert "hitl_respond" not in parsed["endpoints"]

    def test_output_json_cloud_sql_instance_present(self, tmp_path):
        import yaml

        manifest = {
            "apiVersion": "zil/v1",
            "kind": "Agent",
            "metadata": {"name": "test-agent", "version": "0.1.0"},
            "spec": {
                "runtime": {"framework": "adk", "language": "python"},
                "identity": "./identity",
                "env": [{"name": "SESSION_DB_URI", "required": False, "secret": True}],
            },
        }
        (tmp_path / "manifest.yaml").write_text(yaml.dump(manifest))
        (tmp_path / "test_agent").mkdir()
        (tmp_path / "test_agent" / "__init__.py").write_text("")

        with patch("zil.commands.deploy.subprocess.call", return_value=0), \
             patch("zil.commands.deploy.subprocess.run",
                   return_value=MagicMock(returncode=0, stdout="my-project\n", stderr="")), \
             patch("zil.commands.deploy.shutil.which", return_value="/usr/bin/gcloud"), \
             patch("zil.commands.deploy.subprocess.check_output",
                   return_value="https://test-agent-abc-uc.a.run.app\n"), \
             patch.dict("os.environ", {
                 "SESSION_DB_URI":
                     "postgresql+pg8000://user:pass@/db?unix_sock=/cloudsql/my-project:us-central1:mydb/.s.PGSQL.5432"
             }):
            result = runner.invoke(
                cli,
                [
                    "deploy", "--skip-evals",
                    "--project-dir", str(tmp_path),
                    "--project", "my-project",
                    "--region", "us-central1",
                    "--output", "json",
                ],
                catch_exceptions=False,
            )

        parsed = _parse_json_from_output(result.output)
        assert parsed["cloud_sql_instance"] == "my-project:us-central1:mydb"

    def test_output_text_no_json_in_stdout(self, tmp_path):
        result = self._deploy_with_json_output(tmp_path)
        parsed = _parse_json_from_output(result.output)
        assert parsed  # non-empty dict

    def test_output_help_shows_json_option(self):
        result = runner.invoke(cli, ["deploy", "--help"])
        assert "--output" in result.output
        assert "json" in result.output


class TestBuildDeployResult:
    """Unit tests for _build_deploy_result and _fetch_service_url."""

    def test_fetch_service_url_returns_url(self):
        from zil.commands.deploy import _fetch_service_url
        with patch("zil.commands.deploy.subprocess.check_output",
                   return_value="https://my-svc-abc-uc.a.run.app\n"):
            url = _fetch_service_url("my-svc", "proj", "us-central1")
        assert url == "https://my-svc-abc-uc.a.run.app"

    def test_fetch_service_url_returns_none_on_failure(self):
        from zil.commands.deploy import _fetch_service_url
        with patch("zil.commands.deploy.subprocess.check_output",
                   side_effect=__import__("subprocess").CalledProcessError(1, "gcloud")):
            url = _fetch_service_url("svc", "proj", "region")
        assert url is None

    def test_build_result_basic_fields(self):
        from zil.commands.deploy import _build_deploy_result
        manifest = {"spec": {"runtime": {}}}
        with patch("zil.commands.deploy._fetch_service_url",
                   return_value="https://svc.run.app"):
            r = _build_deploy_result(manifest, "svc", "proj", "us-east1", None)
        assert r["service"] == "svc"
        assert r["project"] == "proj"
        assert r["region"] == "us-east1"
        assert r["url"] == "https://svc.run.app"
        assert "cloud_sql_instance" not in r

    def test_build_result_includes_cloud_sql(self):
        from zil.commands.deploy import _build_deploy_result
        manifest = {"spec": {"runtime": {}}}
        with patch("zil.commands.deploy._fetch_service_url", return_value=None):
            r = _build_deploy_result(manifest, "svc", "proj", "r", "proj:r:db")
        assert r["cloud_sql_instance"] == "proj:r:db"

    def test_build_result_webhook_endpoints(self):
        from zil.commands.deploy import _build_deploy_result
        manifest = {"spec": {"runtime": {"service": {
            "entry_point": "webhook",
            "webhooks": [{"name": "gh", "path": "/webhooks/gh"}],
        }}}}
        with patch("zil.commands.deploy._fetch_service_url",
                   return_value="https://svc.run.app"):
            r = _build_deploy_result(manifest, "svc", "proj", "r", None)
        assert r["endpoints"]["webhooks"] == ["https://svc.run.app/webhooks/gh"]

    def test_build_result_hitl_default_path(self):
        from zil.commands.deploy import _build_deploy_result
        manifest = {"spec": {"runtime": {"service": {
            "human_interaction": {"enabled": True},
        }}}}
        with patch("zil.commands.deploy._fetch_service_url",
                   return_value="https://svc.run.app"):
            r = _build_deploy_result(manifest, "svc", "proj", "r", None)
        assert r["endpoints"]["hitl_respond"] == "https://svc.run.app/human/respond"

    def test_build_result_hitl_disabled_not_included(self):
        from zil.commands.deploy import _build_deploy_result
        manifest = {"spec": {"runtime": {"service": {
            "human_interaction": {"enabled": False},
        }}}}
        with patch("zil.commands.deploy._fetch_service_url",
                   return_value="https://svc.run.app"):
            r = _build_deploy_result(manifest, "svc", "proj", "r", None)
        assert "hitl_respond" not in r["endpoints"]

    def test_build_result_url_none_gives_path_only_for_hitl(self):
        from zil.commands.deploy import _build_deploy_result
        manifest = {"spec": {"runtime": {"service": {
            "human_interaction": {"enabled": True, "response_path": "/approvals"},
        }}}}
        with patch("zil.commands.deploy._fetch_service_url", return_value=None):
            r = _build_deploy_result(manifest, "svc", "proj", "r", None)
        assert r["endpoints"]["hitl_respond"] == "/approvals"


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
