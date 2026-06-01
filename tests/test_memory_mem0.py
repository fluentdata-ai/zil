"""Tests for the Mem0 provider adapter (RFC-003, acceptance criterion 3).

Mem0's SDK is not required: a fake client is injected so these run without
``mem0ai`` installed and without any cloud/GCP access. Verifies scope→key
mapping (run_id/user_id/agent_id), response normalization, and delete.
"""

from __future__ import annotations

from typing import Any

from zil.sdk.memory import MemoryConfig, MemoryKeys, MemoryQuery, MemoryScope
from zil.sdk.memory.providers.mem0 import Mem0Provider


class FakeMem0Client:
    """Records calls and returns Mem0-shaped responses."""

    def __init__(self) -> None:
        self.add_calls: list[tuple[Any, dict]] = []
        self.search_calls: list[tuple[str, dict]] = []
        self.delete_calls: list[str] = []
        self.delete_all_calls: list[dict] = []

    def add(self, messages: Any, **kwargs: Any) -> dict:
        self.add_calls.append((messages, kwargs))
        return {"results": [{"id": "m1", "memory": "stored", "event": "ADD"}]}

    def search(self, query: str, **kwargs: Any) -> dict:
        self.search_calls.append((query, kwargs))
        return {
            "results": [
                {"id": "m1", "memory": "User likes Python", "score": 0.9,
                 "metadata": {"k": "v"}},
                {"id": "m2", "memory": "User uses macOS", "score": 0.4},
            ]
        }

    def delete(self, memory_id: str) -> None:
        self.delete_calls.append(memory_id)

    def delete_all(self, **kwargs: Any) -> None:
        self.delete_all_calls.append(kwargs)


def _provider(client: FakeMem0Client, **cfg_extra: Any) -> Mem0Provider:
    cfg = MemoryConfig.from_dict({"provider": "mem0", **cfg_extra})
    return Mem0Provider(cfg, client=client)


class TestScopeMapping:
    def test_user_scope_maps_user_id(self):
        c = FakeMem0Client()
        p = _provider(c)
        p.write("fact", scope=MemoryScope.USER, keys=MemoryKeys(user_id="u1"))
        _, kwargs = c.add_calls[0]
        assert kwargs["user_id"] == "u1"
        assert "run_id" not in kwargs

    def test_session_scope_maps_run_id(self):
        c = FakeMem0Client()
        p = _provider(c)
        p.write("fact", scope=MemoryScope.SESSION, keys=MemoryKeys(session_id="s1"))
        _, kwargs = c.add_calls[0]
        assert kwargs["run_id"] == "s1"

    def test_agent_scope_maps_namespace_to_agent_id(self):
        c = FakeMem0Client()
        p = _provider(c)
        p.write("fact", scope=MemoryScope.AGENT, keys=MemoryKeys(namespace="coding"))
        _, kwargs = c.add_calls[0]
        assert kwargs["agent_id"] == "coding"

    def test_default_namespace_used_for_agent_scope(self):
        c = FakeMem0Client()
        p = _provider(c, namespace="coding")
        p.write("fact", scope=MemoryScope.AGENT, keys=MemoryKeys())
        _, kwargs = c.add_calls[0]
        assert kwargs["agent_id"] == "coding"

    def test_namespace_plus_user_combines(self):
        c = FakeMem0Client()
        p = _provider(c)
        p.write(
            "fact",
            scope=MemoryScope.USER,
            keys=MemoryKeys(user_id="u1", namespace="coding"),
        )
        _, kwargs = c.add_calls[0]
        assert kwargs["user_id"] == "u1"
        assert kwargs["agent_id"] == "coding"


class TestOperations:
    def test_write_returns_ids(self):
        c = FakeMem0Client()
        p = _provider(c)
        ids = p.write("fact", scope=MemoryScope.USER, keys=MemoryKeys(user_id="u1"))
        assert ids == ["m1"]

    def test_add_session_passes_message_list(self):
        c = FakeMem0Client()
        p = _provider(c)
        msgs = [{"role": "user", "content": "hi"}]
        p.add_session(msgs, scope=MemoryScope.USER, keys=MemoryKeys(user_id="u1"))
        sent, _ = c.add_calls[0]
        assert sent == msgs

    def test_retrieve_normalizes_results(self):
        c = FakeMem0Client()
        p = _provider(c)
        items = p.retrieve(
            MemoryQuery("python", scope=MemoryScope.USER, keys=MemoryKeys(user_id="u1"))
        )
        assert [i.content for i in items] == ["User likes Python", "User uses macOS"]
        assert items[0].id == "m1"
        assert items[0].score == 0.9
        assert items[0].scope is MemoryScope.USER

    def test_retrieve_passes_limit(self):
        c = FakeMem0Client()
        p = _provider(c)
        p.retrieve(
            MemoryQuery("x", scope=MemoryScope.USER, keys=MemoryKeys(user_id="u1"), limit=3)
        )
        _, kwargs = c.search_calls[0]
        assert kwargs["limit"] == 3

    def test_delete_by_ids(self):
        c = FakeMem0Client()
        p = _provider(c)
        n = p.delete(scope=MemoryScope.USER, keys=MemoryKeys(user_id="u1"), ids=["m1", "m2"])
        assert n == 2
        assert c.delete_calls == ["m1", "m2"]

    def test_delete_all_in_scope(self):
        c = FakeMem0Client()
        p = _provider(c)
        p.delete(scope=MemoryScope.USER, keys=MemoryKeys(user_id="u1"))
        assert c.delete_all_calls[0]["user_id"] == "u1"


class TestList:
    def test_normalizes_plain_list_response(self):
        c = FakeMem0Client()
        # Managed platform sometimes returns a bare list.
        c.search = lambda q, **k: [{"id": "x", "memory": "hi", "score": 0.1}]  # type: ignore
        p = _provider(c)
        items = p.retrieve(
            MemoryQuery("hi", scope=MemoryScope.USER, keys=MemoryKeys(user_id="u1"))
        )
        assert items[0].content == "hi"

    def test_capabilities_all_scopes(self):
        c = FakeMem0Client()
        p = _provider(c)
        for scope in MemoryScope:
            assert p.supports(scope)
