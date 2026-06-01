"""Tests for ADK memory wiring (RFC-003, acceptance criterion 6).

Exercises the ``ZilAdkMemoryService`` bridge directly: a Zil MemoryProvider
(the stub) is wrapped as an ADK ``BaseMemoryService`` so that
``add_session_to_memory`` persists a turn and ``search_memory`` recalls it in
a *new* session. Requires google-adk (skipped if absent).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("google.adk")

from zil.sdk.memory import MemoryConfig, build_provider  # noqa: E402


def _fake_event(author: str, text: str):
    part = SimpleNamespace(text=text)
    content = SimpleNamespace(role=author, parts=[part])
    return SimpleNamespace(author=author, content=content)


def _fake_session(user_id: str, turns: list[tuple[str, str]]):
    events = [_fake_event(a, t) for a, t in turns]
    return SimpleNamespace(user_id=user_id, app_name="app", id="sess1", events=events)


@pytest.fixture
def provider_and_service():
    from zil.sdk.frameworks.adk.memory_wiring import make_memory_service

    cfg = MemoryConfig.from_dict(
        {"provider": "stub", "scopes": ["user", "agent"], "namespace": "coding"}
    )
    provider = build_provider(cfg)
    service = make_memory_service(provider, cfg)
    return provider, service


class TestZilAdkMemoryService:
    def test_add_session_then_search_new_session(self, provider_and_service):
        provider, service = provider_and_service
        session = _fake_session(
            "u1",
            [
                ("user", "I prefer Python and pytest"),
                ("assistant", "Got it, noting your preferences"),
            ],
        )
        asyncio.run(service.add_session_to_memory(session))

        # New session, same user — recall should surface the stored memory.
        resp = asyncio.run(
            service.search_memory(app_name="app", user_id="u1", query="what language?")
        )
        texts = [
            "".join(p.text for p in m.content.parts) for m in resp.memories
        ]
        assert any("Python" in t for t in texts)

    def test_search_isolated_by_user(self, provider_and_service):
        provider, service = provider_and_service
        asyncio.run(
            service.add_session_to_memory(_fake_session("u1", [("user", "secret for u1")]))
        )
        resp = asyncio.run(
            service.search_memory(app_name="app", user_id="u2", query="secret")
        )
        assert resp.memories == []

    def test_empty_session_is_noop(self, provider_and_service):
        provider, service = provider_and_service
        asyncio.run(service.add_session_to_memory(_fake_session("u1", [])))
        resp = asyncio.run(
            service.search_memory(app_name="app", user_id="u1", query="x")
        )
        assert resp.memories == []


class TestRecallTool:
    def test_build_recall_tool(self):
        from zil.sdk.frameworks.adk.memory_wiring import build_recall_tool

        assert build_recall_tool() is not None


class TestWireAttachesMemory:
    def test_wire_attaches_provider_and_recall_tool(self):
        from zil.sdk.frameworks.adk.backend import AdkBackend
        from zil.sdk.frameworks.base import AgentSpec

        cfg = MemoryConfig.from_dict({"provider": "stub", "scopes": ["user"]})
        provider = build_provider(cfg)
        spec = AgentSpec(
            name="t",
            version="0.1.0",
            description="d",
            instructions="i",
            model="gemini-2.0-flash",
            memory_config=cfg,
            memory_provider=provider,
        )
        wired = AdkBackend().wire(spec)
        agent = wired.inner
        assert getattr(agent, "_zil_memory_provider", None) is provider
        # The recall tool should have been appended to the agent's tools.
        assert agent.tools

    def test_wire_without_memory_has_no_provider(self):
        from zil.sdk.frameworks.adk.backend import AdkBackend
        from zil.sdk.frameworks.base import AgentSpec

        spec = AgentSpec(
            name="t",
            version="0.1.0",
            description="d",
            instructions="i",
            model="gemini-2.0-flash",
        )
        wired = AdkBackend().wire(spec)
        assert getattr(wired.inner, "_zil_memory_provider", None) is None
