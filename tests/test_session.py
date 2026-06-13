"""Tests for zil.Session, SessionEvent, SessionResponse, and backend invoke()."""

import asyncio

import pytest

import zil
from zil.sdk.frameworks.base import AgentSpec
from zil.sdk.frameworks.stub.backend import StubBackend, StubWiredAgent
from zil.sdk.session import Session, SessionEvent, SessionResponse

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stub_spec(name: str = "test-agent") -> AgentSpec:
    return AgentSpec(
        name=name,
        version="0.1.0",
        description="Test agent",
        instructions="Be helpful",
        model="stub/test-model",
    )


def _stub_wired() -> StubWiredAgent:
    return StubWiredAgent(_spec=_stub_spec())


# ---------------------------------------------------------------------------
# TestSessionEvent
# ---------------------------------------------------------------------------


class TestSessionEvent:
    """SessionEvent dataclass behavior."""

    def test_text_event(self):
        ev = SessionEvent(type="text", text="Hello")
        assert ev.type == "text"
        assert ev.text == "Hello"
        assert ev.tool_name is None
        assert ev.args is None

    def test_tool_call_event(self):
        ev = SessionEvent(type="tool_call", tool_name="search", args={"q": "test"})
        assert ev.type == "tool_call"
        assert ev.tool_name == "search"
        assert ev.args == {"q": "test"}
        assert ev.text is None

    def test_done_event_with_metadata(self):
        ev = SessionEvent(type="done", metadata={"token_usage": {"total": 15}})
        assert ev.type == "done"
        assert ev.metadata["token_usage"]["total"] == 15

    def test_error_event(self):
        ev = SessionEvent(type="error", text="something failed")
        assert ev.type == "error"
        assert ev.text == "something failed"


# ---------------------------------------------------------------------------
# TestSessionResponse
# ---------------------------------------------------------------------------


class TestSessionResponse:
    """SessionResponse dataclass behavior."""

    def test_basic_response(self):
        resp = SessionResponse(text="Hello world", session_id="abc123")
        assert resp.text == "Hello world"
        assert resp.session_id == "abc123"
        assert resp.events == []
        assert resp.token_usage is None

    def test_response_with_events(self):
        events = [
            SessionEvent(type="text", text="Hello"),
            SessionEvent(type="done"),
        ]
        resp = SessionResponse(
            text="Hello", events=events, session_id="s1",
            token_usage={"prompt": 5, "completion": 3, "total": 8}
        )
        assert len(resp.events) == 2
        assert resp.token_usage["total"] == 8


# ---------------------------------------------------------------------------
# TestSession — basic lifecycle
# ---------------------------------------------------------------------------


class TestSession:
    """Core Session class behavior using the stub backend."""

    def test_init_with_wired_agent(self):
        agent = _stub_wired()
        session = Session(agent)
        assert session.session_id  # non-empty
        assert not session._closed

    def test_init_with_custom_session_id(self):
        agent = _stub_wired()
        session = Session(agent, session_id="custom-123")
        assert session.session_id == "custom-123"

    def test_init_with_workspace(self, tmp_path):
        agent = _stub_wired()
        session = Session(agent, workspace=tmp_path)
        assert session.workspace == str(tmp_path.resolve())

    def test_close_sets_flag(self):
        agent = _stub_wired()
        session = Session(agent)
        asyncio.run(session.close())
        assert session._closed

    def test_send_after_close_raises(self):
        agent = _stub_wired()
        session = Session(agent)
        asyncio.run(session.close())
        with pytest.raises(RuntimeError, match="closed"):
            asyncio.run(session.send("hello"))


# ---------------------------------------------------------------------------
# TestSessionSend — invoke via stub backend
# ---------------------------------------------------------------------------


class TestSessionSend:
    """Session.send() using the stub backend."""

    def test_send_returns_response(self):
        agent = _stub_wired()
        session = Session(agent)
        resp = asyncio.run(session.send("Test message"))
        assert isinstance(resp, SessionResponse)
        assert "Test message" in resp.text
        assert resp.session_id == session.session_id

    def test_send_captures_events(self):
        agent = _stub_wired()
        session = Session(agent)
        resp = asyncio.run(session.send("hello"))
        # Stub yields: text event + done event
        assert len(resp.events) == 2
        assert resp.events[0].type == "text"
        assert resp.events[1].type == "done"

    def test_send_extracts_token_usage(self):
        agent = _stub_wired()
        session = Session(agent)
        resp = asyncio.run(session.send("check tokens"))
        assert resp.token_usage is not None
        assert resp.token_usage["total"] == 15

    def test_multi_turn(self):
        """Multiple sends on the same session should all work."""
        agent = _stub_wired()
        session = Session(agent)
        r1 = asyncio.run(session.send("first"))
        r2 = asyncio.run(session.send("second"))
        assert "first" in r1.text
        assert "second" in r2.text
        # Same session ID
        assert r1.session_id == r2.session_id


# ---------------------------------------------------------------------------
# TestSessionStream — async iteration
# ---------------------------------------------------------------------------


class TestSessionStream:
    """Session.stream() using the stub backend."""

    def test_stream_yields_events(self):
        agent = _stub_wired()
        session = Session(agent)

        events = []

        async def _collect():
            async for ev in session.stream("stream test"):
                events.append(ev)

        asyncio.run(_collect())
        assert len(events) == 2
        assert events[0].type == "text"
        assert events[1].type == "done"

    def test_stream_after_close_raises(self):
        agent = _stub_wired()
        session = Session(agent)
        asyncio.run(session.close())

        async def _try_stream():
            async for _ in session.stream("nope"):
                pass

        with pytest.raises(RuntimeError, match="closed"):
            asyncio.run(_try_stream())


# ---------------------------------------------------------------------------
# TestPublicAPI — exports from zil package
# ---------------------------------------------------------------------------


class TestPublicAPI:
    """Verify Session types are exported from the top-level zil package."""

    def test_session_exported(self):
        assert hasattr(zil, "Session")
        assert zil.Session is Session

    def test_session_event_exported(self):
        assert hasattr(zil, "SessionEvent")
        assert zil.SessionEvent is SessionEvent

    def test_session_response_exported(self):
        assert hasattr(zil, "SessionResponse")
        assert zil.SessionResponse is SessionResponse


# ---------------------------------------------------------------------------
# TestCreateAgentRaw — raw=True returns WiredAgent
# ---------------------------------------------------------------------------


class TestCreateAgentRaw:
    """create_agent(raw=True) returns a WiredAgent, not the inner object."""

    def test_raw_true_returns_wired(self, tmp_path):
        """Scaffold a minimal stub project and verify raw=True."""
        # Create minimal project structure
        manifest = {
            "version": "1",
            "metadata": {"name": "test-agent", "version": "0.1.0", "description": "t"},
            "spec": {
                "runtime": {"framework": "stub"},
                "identity": "./identity",
            },
        }
        import yaml
        (tmp_path / "manifest.yaml").write_text(yaml.dump(manifest))
        (tmp_path / "identity").mkdir()
        (tmp_path / "identity" / "persona.md").write_text("You are a test agent.")
        (tmp_path / "adapters").mkdir()
        (tmp_path / "adapters" / "llm.yaml").write_text(
            "provider: gemini\nmodel: gemini-3.5-flash\n"
        )

        agent = zil.create_agent(
            project_dir=tmp_path,
            raw=True,
            enable_telemetry=False,
            enable_guardrails=False,
            enable_cost_tracking=False,
            enable_mcp=False,
        )
        # Should be a StubWiredAgent, not the inner spec
        assert hasattr(agent, "framework")
        assert agent.framework == "stub"
        assert hasattr(agent, "inner")


# ---------------------------------------------------------------------------
# TestStubBackendInvoke
# ---------------------------------------------------------------------------


class TestStubBackendInvoke:
    """StubBackend.invoke() async generator."""

    def test_invoke_yields_events(self):
        backend = StubBackend()
        agent = _stub_wired()

        events = []

        async def _run():
            async for ev in backend.invoke(agent, "hello", session_id="s1"):
                events.append(ev)

        asyncio.run(_run())
        assert len(events) == 2
        assert events[0].type == "text"
        assert "[stub] Received: hello" in events[0].text
        assert events[1].type == "done"
        assert events[1].metadata["token_usage"]["total"] == 15
