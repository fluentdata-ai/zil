"""Tests for the native A2A peer client + conformance kit (RFC-005 §7.1, §12).

Unit tests cover the pre-network allowlist gate and artifact parsing. The
conformance kit drives the real ``a2a-sdk`` client against zil's *own* A2A
server (built by ``zil.commands.serve._create_app``) in-process via an httpx
ASGI transport — a true round-trip over the JSON-RPC wire with no sockets.
"""

import asyncio
from types import SimpleNamespace

import pytest
import yaml

from zil.collaboration.client import (
    A2APeerClient,
    PeerArtifact,
    SkillNotAllowedError,
    _artifact,
    _parts_text,
    _task_state,
)
from zil.collaboration.contract import PeerRef


def _run(coro):
    """Run *coro* on a throwaway loop without touching global asyncio state."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Pre-network allowlist enforcement (acceptance criterion 4)
# ---------------------------------------------------------------------------


class TestAllowlistEnforcement:
    def test_disallowed_skill_raises_before_network(self):
        # A sentinel client that would explode if any network path touched it.
        sentinel = object()
        peer = PeerRef(name="billing", url="http://peer", skills=["refund"])
        client = A2APeerClient(peer, httpx_client=sentinel)
        with pytest.raises(SkillNotAllowedError, match="not in the allowlist"):
            _run(client.call("delete_everything", "go"))

    def test_allowed_skill_passes_gate(self):
        peer = PeerRef(name="billing", url="http://peer", skills=["refund"])
        client = A2APeerClient(peer)
        # Gate only — does not raise for an allowlisted skill.
        client._check_skill_allowed("refund")

    def test_none_allowlist_permits_any_skill(self):
        peer = PeerRef(name="billing", url="http://peer", skills=None)
        client = A2APeerClient(peer)
        client._check_skill_allowed("anything")


# ---------------------------------------------------------------------------
# Artifact / text parsing helpers
# ---------------------------------------------------------------------------


class TestParsing:
    def test_parts_text_concatenates_text_parts(self):
        parts = [
            SimpleNamespace(root=SimpleNamespace(text="Hello ")),
            SimpleNamespace(root=SimpleNamespace(text="world")),
            SimpleNamespace(root=SimpleNamespace(text=None)),  # non-text ignored
        ]
        assert _parts_text(parts) == "Hello world"

    def test_parts_text_empty(self):
        assert _parts_text(None) == ""

    def test_artifact_parsing(self):
        obj = SimpleNamespace(
            name="summary",
            parts=[SimpleNamespace(root=SimpleNamespace(text="done"))],
        )
        art = _artifact(obj)
        assert isinstance(art, PeerArtifact)
        assert art.name == "summary"
        assert art.text == "done"

    def test_task_state_reads_enum_value(self):
        task = SimpleNamespace(
            status=SimpleNamespace(state=SimpleNamespace(value="completed"))
        )
        assert _task_state(task) == "completed"

    def test_task_state_none(self):
        assert _task_state(SimpleNamespace(status=None)) is None


# ---------------------------------------------------------------------------
# Conformance kit — native client <-> zil's own A2A server (in-process)
# ---------------------------------------------------------------------------


@pytest.fixture
def peer_app(tmp_path):
    """Build a zil A2A server app for a minimal stub-framework agent."""
    pytest.importorskip("fastapi")
    pytest.importorskip("a2a")
    from zil.commands.serve import _create_app

    manifest = {
        "version": "1",
        "metadata": {"name": "peer-agent", "version": "1.0.0",
                     "description": "Conformance peer"},
        "spec": {"runtime": {"framework": "stub"}, "identity": "./identity"},
    }
    (tmp_path / "manifest.yaml").write_text(yaml.dump(manifest))
    (tmp_path / "identity").mkdir()
    (tmp_path / "identity" / "persona.md").write_text("You are a peer.")
    (tmp_path / "adapters").mkdir()
    (tmp_path / "adapters" / "llm.yaml").write_text(
        "provider: gemini\nmodel: gemini-3.5-flash\n"
    )
    return _create_app(tmp_path)


def _asgi_client(app):
    import httpx

    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://peer"
    )


class TestConformanceRoundTrip:
    def test_message_send_round_trip(self, peer_app):
        """Criterion 2: fetch card, call a skill, receive parsed artifacts."""
        peer = PeerRef(name="peer", url="http://peer")

        async def run():
            async with _asgi_client(peer_app) as http:
                client = A2APeerClient(peer, caller="orchestrator", httpx_client=http)
                return await client.call("chat", "hello peer")

        result = _run(run())
        assert result.status == "completed"
        assert result.task_id
        # The stub agent echoes/answers — we just require non-empty artifact text.
        assert result.text()

    def test_streaming_yields_increments_then_final(self, peer_app):
        """Criterion 3: streaming yields incremental events and a final status."""
        peer = PeerRef(name="peer", url="http://peer")

        async def run():
            events = []
            async with _asgi_client(peer_app) as http:
                client = A2APeerClient(peer, caller="orchestrator", httpx_client=http)
                async for ev in client.stream("chat", "stream please"):
                    events.append(ev)
            return events

        events = _run(run())
        # At least one terminal status event with final=True.
        assert any(e.kind == "status" and e.final for e in events)
