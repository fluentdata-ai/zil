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


def _a2a_agent_card_cls():
    """Return the a2a-sdk pydantic AgentCard model, or skip if unavailable.

    The pydantic model lives at ``a2a.types`` in a2a-sdk 0.3.x (what google-adk
    pins) and at ``a2a.compat.v0_3.types`` in 1.x — try both.
    """
    import importlib

    for path in ("a2a.types", "a2a.compat.v0_3.types"):
        try:
            module = importlib.import_module(path)
        except ImportError:
            continue
        cls = getattr(module, "AgentCard", None)
        if cls is not None and hasattr(cls, "model_validate"):
            return cls
    pytest.skip("a2a-sdk pydantic AgentCard model not available")


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
        # Current well-known path per A2A v0.3 (a2a-sdk 1.0.x).
        resp = client.get("/.well-known/agent-card.json")
        assert resp.status_code == 200
        card = resp.json()
        assert card["name"] == "serve-test"
        assert card["version"] == "1.0.0"
        assert card["capabilities"]["streaming"] is True

    def test_agent_card_is_a2a_conformant(self, client):
        """Card advertises protocol version + preferred transport (A2A v0.3)."""
        card = client.get("/.well-known/agent-card.json").json()
        assert card["protocolVersion"] == "0.3.0"
        assert card["preferredTransport"] == "JSONRPC"

    def test_agent_card_legacy_path_is_aliased(self, client):
        """The pre-0.3 well-known path still resolves (deprecated alias)."""
        legacy = client.get("/.well-known/agent.json")
        assert legacy.status_code == 200
        assert legacy.json()["name"] == "serve-test"

    def test_agent_card_validates_against_a2a_sdk(self, client):
        """The served card validates against the real A2A pydantic model
        (a2a-sdk) — conformance enforced by the spec types, not just shapes."""
        agent_card_cls = _a2a_agent_card_cls()
        card = client.get("/.well-known/agent-card.json").json()
        # Raises pydantic.ValidationError if the card is non-conformant.
        agent_card_cls.model_validate(card)

    def test_agent_card_url_is_jsonrpc_endpoint(self, client):
        resp = client.get(
            "/.well-known/agent-card.json",
            headers={"host": "myagent.run.app", "x-forwarded-proto": "https"},
        )
        card = resp.json()
        # For JSONRPC transport the card url is the JSON-RPC endpoint.
        assert card["url"] == "https://myagent.run.app/a2a"
        assert card["additionalInterfaces"] == [
            {"url": "https://myagent.run.app/a2a", "transport": "JSONRPC"}
        ]

    def test_agent_card_no_skills_is_empty(self, client):
        """A project without spec.skills advertises an empty skills list."""
        resp = client.get("/.well-known/agent-card.json")
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
        card = client.get("/.well-known/agent-card.json").json()
        skills = {s["id"]: s for s in card["skills"]}
        assert set(skills) == {"refund", "lookup"}
        assert skills["refund"]["name"] == "refund"
        assert skills["refund"]["description"] == "Issue a customer refund."
        assert skills["lookup"]["name"] == "invoice_lookup"
        # AgentSkill.tags is required by the current A2A spec (a2a-sdk 0.3.x)
        assert skills["refund"]["tags"] == []
        assert skills["lookup"]["tags"] == []
        # Strict: the skilled card validates against the real A2A model.
        _a2a_agent_card_cls().model_validate(card)


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
# TestA2AJsonRpc (current A2A spec transport)
# ---------------------------------------------------------------------------


class TestA2AJsonRpc:
    def _rpc(self, client, method, params, rpc_id=1):
        return client.post(
            "/a2a",
            json={"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params},
        )

    def test_message_send_returns_task(self, client):
        resp = self._rpc(
            client,
            "message/send",
            {"message": {"role": "user", "kind": "message",
                         "parts": [{"kind": "text", "text": "Plan the feature"}]}},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["jsonrpc"] == "2.0"
        assert body["id"] == 1
        result = body["result"]
        assert result["kind"] == "task"
        assert result["status"]["state"] == "completed"
        assert result["artifacts"][0]["parts"][0]["kind"] == "text"

    def test_message_send_then_tasks_get(self, client):
        send = self._rpc(
            client,
            "message/send",
            {"message": {"parts": [{"kind": "text", "text": "hi"}]}},
        ).json()
        task_id = send["result"]["id"]
        got = self._rpc(client, "tasks/get", {"id": task_id}, rpc_id=2).json()
        assert got["id"] == 2
        assert got["result"]["id"] == task_id
        assert got["result"]["status"]["state"] == "completed"

    def test_tasks_get_unknown_is_rpc_error(self, client):
        body = self._rpc(client, "tasks/get", {"id": "nope"}).json()
        assert body["error"]["code"] == -32001

    def test_unknown_method_is_rpc_error(self, client):
        body = self._rpc(client, "does/not/exist", {}).json()
        assert body["error"]["code"] == -32601

    def test_invalid_request_envelope(self, client):
        resp = client.post("/a2a", json={"method": "message/send"})  # no jsonrpc
        assert resp.json()["error"]["code"] == -32600

    def test_message_stream_sse(self, client):
        resp = self._rpc(
            client,
            "message/stream",
            {"message": {"parts": [{"kind": "text", "text": "stream me"}]}},
        )
        assert "text/event-stream" in resp.headers["content-type"]
        assert "status-update" in resp.text
        assert '"final": true' in resp.text

    def test_legacy_text_part_type_still_parsed(self, client):
        """Inbound parts using the legacy `type` key are still read."""
        body = self._rpc(
            client,
            "message/send",
            {"message": {"parts": [{"type": "text", "text": "legacy part"}]}},
        ).json()
        assert body["result"]["status"]["state"] == "completed"


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

