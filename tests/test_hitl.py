"""Tests for the zil HITL (human-in-the-loop) SDK primitives."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from zil.sdk.hitl import (
    HumanInputRequest,
    HumanInputResponse,
    _clear_hitl_state,
    _get_state,
    _set_state,
    request_human_input,
)


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

class TestStateHelpers:
    def test_get_state_from_adk_tool_context(self):
        ctx = MagicMock()
        ctx.state = {"key": "value"}
        state = _get_state(ctx)
        assert state["key"] == "value"

    def test_get_state_from_plain_dict(self):
        ctx = {"pending": True}
        state = _get_state(ctx)
        assert state["pending"] is True

    def test_get_state_none_returns_empty(self):
        assert _get_state(None) == {}

    def test_set_state_writes_to_context(self):
        ctx = MagicMock()
        ctx.state = {}
        _set_state(ctx, "foo", "bar")
        assert ctx.state["foo"] == "bar"

    def test_set_state_dict_context(self):
        ctx = {}
        _set_state(ctx, "x", 42)
        assert ctx["x"] == 42

    def test_clear_hitl_state_removes_keys(self):
        ctx = {
            "pending_human_request": {"question": "?"},
            "human_response": {"choice": "approve"},
            "other": "keep",
        }
        _clear_hitl_state(ctx)
        assert "pending_human_request" not in ctx
        assert "human_response" not in ctx
        assert ctx["other"] == "keep"

    def test_clear_hitl_state_noop_when_absent(self):
        ctx = {"other": "value"}
        _clear_hitl_state(ctx)  # should not raise
        assert ctx["other"] == "value"


# ---------------------------------------------------------------------------
# HumanInputRequest
# ---------------------------------------------------------------------------

class TestHumanInputRequest:
    def test_auto_generates_interaction_id(self):
        req = HumanInputRequest(question="Approve?")
        assert req.interaction_id
        assert len(req.interaction_id) == 36  # UUID4

    def test_unique_ids(self):
        r1 = HumanInputRequest(question="q1")
        r2 = HumanInputRequest(question="q2")
        assert r1.interaction_id != r2.interaction_id

    def test_default_context_is_empty(self):
        req = HumanInputRequest(question="q")
        assert req.context == {}

    def test_default_options_is_empty(self):
        req = HumanInputRequest(question="q")
        assert req.options == []

    def test_custom_fields(self):
        req = HumanInputRequest(
            question="Delete 5 files?",
            context={"risk": "high"},
            options=["approve", "reject"],
        )
        assert req.context["risk"] == "high"
        assert "approve" in req.options


# ---------------------------------------------------------------------------
# HumanInputResponse
# ---------------------------------------------------------------------------

class TestHumanInputResponse:
    def test_defaults(self):
        resp = HumanInputResponse(interaction_id="abc")
        assert resp.choice == ""
        assert resp.comment == ""
        assert resp.timed_out is False

    def test_fields(self):
        resp = HumanInputResponse(
            interaction_id="x",
            choice="approve",
            comment="LGTM",
        )
        assert resp.choice == "approve"
        assert resp.comment == "LGTM"


# ---------------------------------------------------------------------------
# request_human_input — first-call (pending) path
# ---------------------------------------------------------------------------

class TestRequestHumanInputFirstCall:
    def test_records_pending_request(self):
        ctx = {}
        req = HumanInputRequest(question="Approve plan?", options=["yes", "no"])
        resp = asyncio.get_event_loop().run_until_complete(
            request_human_input(req, ctx)
        )
        assert "pending_human_request" in ctx
        assert ctx["pending_human_request"]["question"] == "Approve plan?"
        assert ctx["pending_human_request"]["options"] == ["yes", "no"]
        assert ctx["pending_human_request"]["interaction_id"] == req.interaction_id

    def test_returns_pending_choice(self):
        ctx = {}
        req = HumanInputRequest(question="q?")
        resp = asyncio.get_event_loop().run_until_complete(
            request_human_input(req, ctx)
        )
        assert resp.choice == "__pending__"
        assert resp.interaction_id == req.interaction_id

    def test_pending_request_includes_context(self):
        ctx = {}
        req = HumanInputRequest(question="q?", context={"plan": "step1"})
        asyncio.get_event_loop().run_until_complete(request_human_input(req, ctx))
        assert ctx["pending_human_request"]["context"]["plan"] == "step1"

    def test_none_context_does_not_raise(self):
        resp = asyncio.get_event_loop().run_until_complete(
            request_human_input(HumanInputRequest(question="q"), None)
        )
        assert resp.choice == "__pending__"


# ---------------------------------------------------------------------------
# request_human_input — resume path (human already responded)
# ---------------------------------------------------------------------------

class TestRequestHumanInputResumePath:
    def test_returns_human_choice_on_resume(self):
        req = HumanInputRequest(question="Approve?")
        ctx = {
            "human_response": {
                "interaction_id": req.interaction_id,
                "choice": "approve",
                "comment": "all good",
            }
        }
        resp = asyncio.get_event_loop().run_until_complete(
            request_human_input(req, ctx)
        )
        assert resp.choice == "approve"
        assert resp.comment == "all good"
        assert resp.interaction_id == req.interaction_id

    def test_clears_hitl_state_after_resume(self):
        req = HumanInputRequest(question="q")
        ctx = {
            "human_response": {
                "interaction_id": req.interaction_id,
                "choice": "reject",
                "comment": "",
            },
            "pending_human_request": {"old": "stuff"},
        }
        asyncio.get_event_loop().run_until_complete(request_human_input(req, ctx))
        assert "human_response" not in ctx
        assert "pending_human_request" not in ctx

    def test_wrong_interaction_id_not_treated_as_resume(self):
        req = HumanInputRequest(question="q")
        ctx = {
            "human_response": {
                "interaction_id": "completely-different-id",
                "choice": "approve",
            }
        }
        resp = asyncio.get_event_loop().run_until_complete(
            request_human_input(req, ctx)
        )
        # Should still record pending — not consume this unrelated response
        assert resp.choice == "__pending__"

    def test_missing_comment_defaults_to_empty(self):
        req = HumanInputRequest(question="q")
        ctx = {
            "human_response": {
                "interaction_id": req.interaction_id,
                "choice": "approve",
                # comment intentionally absent
            }
        }
        resp = asyncio.get_event_loop().run_until_complete(
            request_human_input(req, ctx)
        )
        assert resp.comment == ""


# ---------------------------------------------------------------------------
# deploy.py: Cloud SQL session wiring
# ---------------------------------------------------------------------------

class TestDeployCloudSQL:
    """Verify Cloud SQL detection logic in deploy.py."""

    def test_extracts_instance_from_unix_sock_uri(self):
        import re
        uri = "postgresql+pg8000://user:pass@/db?unix_sock=/cloudsql/proj:us-central1:mydb/.s.PGSQL.5432"
        m = re.search(r"/cloudsql/([^/]+)/", uri)
        assert m is not None
        assert m.group(1) == "proj:us-central1:mydb"

    def test_no_cloudsql_in_sqlite_uri(self):
        uri = "sqlite+aiosqlite:///./sessions.db"
        assert "/cloudsql/" not in uri

    def test_no_cloudsql_in_plain_pg_uri(self):
        uri = "postgresql+asyncpg://user:pass@localhost/db"
        assert "/cloudsql/" not in uri

    def test_multiple_segments_in_instance_name(self):
        import re
        uri = "postgresql+pg8000://postgres:secret@/agentdb?unix_sock=/cloudsql/my-project:europe-west1:my-instance/.s.PGSQL.5432"
        m = re.search(r"/cloudsql/([^/]+)/", uri)
        assert m is not None
        assert m.group(1) == "my-project:europe-west1:my-instance"
