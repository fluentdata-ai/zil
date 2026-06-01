"""Tests for OpenHands memory wiring helpers (RFC-003, criterion 10).

These exercise the Zil-layer recall/persist helpers directly (no live LLM and
no openhands-sdk required), plus that ``wire`` carries the provider onto the
wired-agent wrapper.
"""

from __future__ import annotations

import pytest

from zil.sdk.frameworks.openhands.memory_wiring import (
    inject_memories,
    persist_turn,
    retrieve_memories,
    scope_and_keys,
)
from zil.sdk.memory import MemoryConfig, build_provider
from zil.sdk.memory.types import MemoryScope


def _provider(**cfg):
    return build_provider(MemoryConfig.from_dict({"provider": "stub", **cfg}))


class TestScopeAndKeys:
    def test_namespace_uses_agent_scope(self):
        cfg = MemoryConfig.from_dict(
            {"provider": "stub", "scopes": ["agent", "user"], "namespace": "coding"}
        )
        scope, keys = scope_and_keys(cfg, user_id=None)
        assert scope is MemoryScope.AGENT
        assert keys.namespace == "coding"

    def test_no_namespace_uses_user_scope(self):
        cfg = MemoryConfig.from_dict({"provider": "stub", "scopes": ["user"]})
        scope, keys = scope_and_keys(cfg, user_id="u1")
        assert scope is MemoryScope.USER
        assert keys.user_id == "u1"


class TestInject:
    def test_inject_empty_returns_original(self):
        assert inject_memories("hello", []) == "hello"

    def test_inject_prepends_bullets(self):
        out = inject_memories("do X", ["likes Python", "uses macOS"])
        assert "likes Python" in out
        assert out.endswith("do X")


class TestRecallPersistRoundTrip:
    def test_persist_then_retrieve(self):
        cfg = MemoryConfig.from_dict(
            {"provider": "stub", "scopes": ["agent"], "namespace": "coding"}
        )
        provider = build_provider(cfg)
        persist_turn(
            provider,
            cfg,
            user_message="Always use pytest for tests",
            agent_messages=["Understood, I'll use pytest"],
            user_id=None,
        )
        recalled = retrieve_memories(provider, cfg, query="what test tool?", user_id=None)
        assert any("pytest" in r for r in recalled)

    def test_segmented_namespaces_isolated(self):
        coding = MemoryConfig.from_dict(
            {"provider": "stub", "scopes": ["agent"], "namespace": "coding"}
        )
        finance = MemoryConfig.from_dict(
            {"provider": "stub", "scopes": ["agent"], "namespace": "finance"}
        )
        # Shared underlying provider store would still isolate by namespace key.
        provider = build_provider(coding)
        persist_turn(provider, coding, user_message="use pytest",
                     agent_messages=[], user_id=None)
        # Finance config points at a different namespace → no cross-read.
        recalled = retrieve_memories(provider, finance, query="pytest", user_id=None)
        assert recalled == []


class TestWireCarriesMemory:
    def test_wire_sets_memory_on_wrapper(self):
        pytest.importorskip("openhands.sdk")
        from zil.sdk.frameworks.base import AgentSpec
        from zil.sdk.frameworks.openhands.backend import OpenHandsBackend

        cfg = MemoryConfig.from_dict(
            {"provider": "stub", "scopes": ["agent"], "namespace": "coding"}
        )
        provider = build_provider(cfg)
        spec = AgentSpec(
            name="t",
            version="0.1.0",
            description="d",
            instructions="i",
            model="anthropic/claude-sonnet-4-20250514",
            memory_config=cfg,
            memory_provider=provider,
        )
        wired = OpenHandsBackend().wire(spec)
        assert wired.memory_provider is provider
        assert wired.memory_config is cfg
