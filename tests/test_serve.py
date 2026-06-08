"""Tests for zil serve — REST endpoints, webhook dispatch, and A2A."""

import json
import os
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

# We need fastapi for testing. Skip if not available.
fastapi = pytest.importorskip("fastapi")
httpx = pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from zil.commands.serve import _create_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_project(tmp_path):
    """Create a minimal stub-framework project for serve tests."""
    manifest = {
        "version": "1",
        "metadata": {
            "name": "serve-test",
            "version": "1.0.0",
            "description": "Test agent for serve",
        },
        "spec": {
            "runtime": {"framework": "stub"},
            "identity": "./identity",
        },
    }
    (tmp_path / "manifest.yaml").write_text(yaml.dump(manifest))
    (tmp_path / "identity").mkdir()
    (tmp_path / "identity" / "persona.md").write_text("You are a test agent.")
    (tmp_path / "adapters").mkdir()
    (tmp_path / "adapters" / "llm.yaml").write_text(
        "provider: gemini\nmodel: gemini-3.5-flash\n"
    )
    return tmp_path


@pytest.fixture
def stub_project_with_webhooks(tmp_path):
    """Create a stub project with webhook declarations."""
    manifest = {
        "version": "1",
        "metadata": {
            "name": "webhook-test",
            "version": "1.0.0",
            "description": "Webhook test",
        },
        "spec": {
            "runtime": {
                "framework": "stub",
                "service": {
                    "webhooks": [
                        {
                            "name": "jira",
                            "path": "/webhooks/jira",
                            "signature_header": "X-Hub-Signature",
                            "algorithm": "sha256",
                            "secret_env": "JIRA_WEBHOOK_SECRET",
                        }
                    ]
                },
            },
            "identity": "./identity",
        },
    }
    (tmp_path / "manifest.yaml").write_text(yaml.dump(manifest))
    (tmp_path / "identity").mkdir()
    (tmp_path / "identity" / "persona.md").write_text("You are a test agent.")
    (tmp_path / "adapters").mkdir()
    (tmp_path / "adapters" / "llm.yaml").write_text(
        "provider: gemini\nmodel: gemini-3.5-flash\n"
    )
    return tmp_path


@pytest.fixture
def client(stub_project):
    """TestClient for the stub project."""
    app = _create_app(stub_project)
    return TestClient(app)


@pytest.fixture
def webhook_client(stub_project_with_webhooks):
    """TestClient for the webhook project."""
    app = _create_app(stub_project_with_webhooks)
    return TestClient(app)


# ---------------------------------------------------------------------------
# TestHealth
# ---------------------------------------------------------------------------


class TestHealth:
    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["agent"] == "serve-test"
        assert data["version"] == "1.0.0"


# ---------------------------------------------------------------------------
# TestSessions
# ---------------------------------------------------------------------------


class TestSessions:
    def test_create_session(self, client):
        resp = client.post("/sessions", json={})
        assert resp.status_code == 201
        data = resp.json()
        assert "session_id" in data
        assert "workspace" in data

    def test_send_message(self, client):
        # Create session
        create_resp = client.post("/sessions", json={})
        session_id = create_resp.json()["session_id"]

        # Send message
        resp = client.post(
            f"/sessions/{session_id}/messages",
            json={"message": "Hello agent"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == session_id
        assert "Hello agent" in data["text"]
        assert len(data["events"]) >= 1

    def test_send_message_missing_field(self, client):
        create_resp = client.post("/sessions", json={})
        session_id = create_resp.json()["session_id"]

        # Pydantic requires 'message' field — this returns 422
        resp = client.post(
            f"/sessions/{session_id}/messages",
            json={},
        )
        assert resp.status_code == 422

    def test_send_message_unknown_session(self, client):
        resp = client.post(
            "/sessions/nonexistent/messages",
            json={"message": "hi"},
        )
        assert resp.status_code == 404

    def test_close_session(self, client):
        create_resp = client.post("/sessions", json={})
        session_id = create_resp.json()["session_id"]

        resp = client.delete(f"/sessions/{session_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "closed"

        # Sending after close should fail (session removed)
        resp = client.post(
            f"/sessions/{session_id}/messages",
            json={"message": "hi"},
        )
        assert resp.status_code == 404

    def test_multi_turn_session(self, client):
        create_resp = client.post("/sessions", json={})
        session_id = create_resp.json()["session_id"]

        r1 = client.post(
            f"/sessions/{session_id}/messages",
            json={"message": "first"},
        )
        r2 = client.post(
            f"/sessions/{session_id}/messages",
            json={"message": "second"},
        )
        assert "first" in r1.json()["text"]
        assert "second" in r2.json()["text"]


# ---------------------------------------------------------------------------
# TestInvoke (stateless)
# ---------------------------------------------------------------------------


class TestInvoke:
    def test_invoke_returns_response(self, client):
        resp = client.post("/invoke", json={"message": "Do something"})
        assert resp.status_code == 200
        data = resp.json()
        assert "Do something" in data["text"]
        assert "session_id" in data

    def test_invoke_empty_message(self, client):
        # Empty string passes Pydantic validation but hits our check
        resp = client.post("/invoke", json={"message": ""})
        assert resp.status_code == 400

    def test_invoke_missing_message(self, client):
        # Missing field triggers Pydantic 422
        resp = client.post("/invoke", json={})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# TestStreaming
# ---------------------------------------------------------------------------


class TestStreaming:
    def test_stream_endpoint(self, client):
        # Create session first
        create_resp = client.post("/sessions", json={})
        session_id = create_resp.json()["session_id"]

        # Stream with message query param
        resp = client.get(
            f"/sessions/{session_id}/stream",
            params={"message": "stream test"},
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        # Should contain SSE data
        assert "data:" in resp.text

    def test_stream_missing_message(self, client):
        create_resp = client.post("/sessions", json={})
        session_id = create_resp.json()["session_id"]

        resp = client.get(f"/sessions/{session_id}/stream")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# TestA2AAgentCard
# ---------------------------------------------------------------------------


class TestA2AAgentCard:
    def test_agent_card_endpoint(self, client):
        resp = client.get("/.well-known/agent.json")
        assert resp.status_code == 200
        card = resp.json()
        assert card["name"] == "serve-test"
        assert card["version"] == "1.0.0"
        assert card["capabilities"]["streaming"] is True

    def test_agent_card_url_from_host(self, client):
        resp = client.get(
            "/.well-known/agent.json",
            headers={"host": "myagent.run.app", "x-forwarded-proto": "https"},
        )
        card = resp.json()
        assert card["url"] == "https://myagent.run.app"

    def test_agent_card_no_skills_is_empty(self, client):
        """A project without spec.skills advertises an empty skills list."""
        resp = client.get("/.well-known/agent.json")
        assert resp.json()["skills"] == []

    def test_agent_card_advertises_real_skills(self, tmp_path):
        """Skills from spec.skills are advertised on the Agent Card so A2A
        clients can introspect and select capabilities (RFC-005 §8)."""
        manifest = {
            "version": "1",
            "metadata": {"name": "skilled", "version": "1.0.0", "description": ""},
            "spec": {
                "runtime": {"framework": "stub"},
                "identity": "./identity",
                "skills": "./skills",
            },
        }
        (tmp_path / "manifest.yaml").write_text(yaml.dump(manifest))
        (tmp_path / "identity").mkdir()
        (tmp_path / "identity" / "persona.md").write_text("persona")
        (tmp_path / "adapters").mkdir()
        (tmp_path / "adapters" / "llm.yaml").write_text(
            "provider: gemini\nmodel: gemini-3.5-flash\n"
        )
        skills_dir = tmp_path / "skills"
        (skills_dir / "refund").mkdir(parents=True)
        (skills_dir / "refund" / "SKILL.md").write_text(
            "---\nname: refund\ndescription: Issue a customer refund.\n---\n# refund\n"
        )
        (skills_dir / "lookup").mkdir(parents=True)
        (skills_dir / "lookup" / "SKILL.md").write_text(
            "---\nname: invoice_lookup\ndescription: Look up an invoice.\n---\n# lookup\n"
        )

        client = TestClient(_create_app(tmp_path))
        card = client.get("/.well-known/agent.json").json()
        skills = {s["id"]: s for s in card["skills"]}
        assert set(skills) == {"refund", "lookup"}
        assert skills["refund"]["name"] == "refund"
        assert skills["refund"]["description"] == "Issue a customer refund."
        assert skills["lookup"]["name"] == "invoice_lookup"


# ---------------------------------------------------------------------------
# TestA2ATasks
# ---------------------------------------------------------------------------


class TestA2ATasks:
    def test_send_task(self, client):
        resp = client.post("/tasks/send", json={
            "id": "task-001",
            "message": {
                "parts": [{"type": "text", "text": "Plan the feature"}],
            },
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "task-001"
        assert data["result"]["status"]["state"] == "completed"
        assert len(data["result"]["artifacts"]) == 1

    def test_get_task(self, client):
        # Send first
        client.post("/tasks/send", json={
            "id": "task-002",
            "message": {"parts": [{"type": "text", "text": "hi"}]},
        })
        # Retrieve
        resp = client.get("/tasks/task-002")
        assert resp.status_code == 200
        assert resp.json()["status"]["state"] == "completed"

    def test_get_unknown_task(self, client):
        resp = client.get("/tasks/unknown")
        assert resp.status_code == 404

    def test_send_subscribe_streams(self, client):
        resp = client.post("/tasks/sendSubscribe", json={
            "id": "task-003",
            "message": {"parts": [{"type": "text", "text": "stream me"}]},
        })
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        # Should contain SSE data with task status
        assert "working" in resp.text
        assert "completed" in resp.text


# ---------------------------------------------------------------------------
# TestWebhooks
# ---------------------------------------------------------------------------


class TestWebhooks:
    def test_webhook_endpoint_registered(self, webhook_client):
        """The jira webhook endpoint should be registered."""
        resp = webhook_client.post(
            "/webhooks/jira",
            content=json.dumps({"webhookEvent": "jira:issue_created", "issue": {"key": "TEST-1"}}).encode(),
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 202
        assert resp.json()["status"] == "accepted"
        assert resp.json()["webhook"] == "jira"

    def test_webhook_invalid_json(self, webhook_client):
        resp = webhook_client.post(
            "/webhooks/jira",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# TestCLI
# ---------------------------------------------------------------------------


class TestCLI:
    def test_serve_command_exists(self):
        from click.testing import CliRunner
        from zil.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["serve", "--help"])
        assert result.exit_code == 0
        assert "Start the agent as a REST/A2A server" in result.output

    def test_serve_help_shows_docker_flag(self):
        from click.testing import CliRunner
        from zil.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["serve", "--help"])
        assert "--docker" in result.output
        assert "--trace" in result.output
        assert "--trace-console" in result.output

    def test_serve_no_manifest(self, tmp_path):
        from click.testing import CliRunner
        from zil.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["serve", "--project-dir", str(tmp_path)])
        assert result.exit_code == 1

    def test_serve_docker_no_docker_cli(self, stub_project):
        """--docker should fail gracefully if Docker is not installed."""
        from click.testing import CliRunner
        from zil.cli import cli

        runner = CliRunner()
        with patch("shutil.which", return_value=None):
            result = runner.invoke(
                cli, ["serve", "--project-dir", str(stub_project), "--docker"]
            )
        assert result.exit_code == 1

    def test_serve_docker_calls_docker_serve(self, stub_project):
        """--docker should dispatch to docker_serve()."""
        from click.testing import CliRunner
        from zil.cli import cli

        runner = CliRunner()
        with patch("shutil.which", return_value="/usr/bin/docker"), \
             patch("zil.commands._docker.docker_serve") as mock_ds:
            result = runner.invoke(
                cli, ["serve", "--project-dir", str(stub_project), "--docker"]
            )
        mock_ds.assert_called_once()
        call_kwargs = mock_ds.call_args
        assert call_kwargs[0][1] == "serve-test"  # agent_name

