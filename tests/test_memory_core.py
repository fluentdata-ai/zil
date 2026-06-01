"""Tests for the neutral memory core and stub provider (RFC-003).

Covers acceptance criteria:
  1. Neutral core + stub work with no provider/framework SDK installed.
  4. Validation errors when a manifest requests an unsupported scope.
  5. Validation errors for substrate mismatch (managed + substrate).
  9. delete() removes memory for a key/scope.
Plus namespace-based segmented shared memory.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from zil.schema.loader import validate_project
from zil.sdk.memory import (
    MemoryConfig,
    MemoryItem,
    MemoryKeys,
    MemoryQuery,
    MemoryScope,
    build_provider,
    registry,
)
from zil.sdk.memory.types import MissingKeyError

# ---------------------------------------------------------------------------
# Neutral core types
# ---------------------------------------------------------------------------

class TestNeutralTypes:
    def test_scope_from_str(self):
        assert MemoryScope.from_str("USER") is MemoryScope.USER
        assert MemoryScope.from_str(" agent ") is MemoryScope.AGENT
        with pytest.raises(ValueError, match="Unknown memory scope"):
            MemoryScope.from_str("galaxy")

    def test_keys_primary_for(self):
        keys = MemoryKeys(user_id="u1", session_id="s1", namespace="coding")
        assert keys.primary_for(MemoryScope.USER) == "u1"
        assert keys.primary_for(MemoryScope.SESSION) == "s1"
        assert keys.primary_for(MemoryScope.AGENT) == "coding"

    def test_item_to_dict(self):
        item = MemoryItem(content="hi", id="1", scope=MemoryScope.USER, score=0.5)
        d = item.to_dict()
        assert d["content"] == "hi"
        assert d["scope"] == "user"
        assert d["score"] == 0.5

    def test_core_imports_without_provider_sdks(self):
        # Importing the core must not require mem0/adk/openhands.
        import importlib

        for mod in ("mem0", "google.adk", "openhands"):
            # The neutral core does not import these at module load.
            assert mod not in _loaded_top_level()
        importlib.import_module("zil.sdk.memory.types")
        importlib.import_module("zil.sdk.memory.substrate")


def _loaded_top_level() -> set[str]:
    import sys

    return {name.split(".")[0] for name in sys.modules}


# ---------------------------------------------------------------------------
# Stub provider
# ---------------------------------------------------------------------------

@pytest.fixture
def stub():
    cfg = MemoryConfig.from_dict({"provider": "stub"})
    return build_provider(cfg)


class TestStubProvider:
    def test_registered(self):
        assert "stub" in registry
        assert "mem0" in registry

    def test_write_and_retrieve_user(self, stub):
        stub.write("User loves Python", scope=MemoryScope.USER, keys=MemoryKeys(user_id="u1"))
        stub.write("User uses macOS", scope=MemoryScope.USER, keys=MemoryKeys(user_id="u1"))
        res = stub.retrieve(
            MemoryQuery("python", scope=MemoryScope.USER, keys=MemoryKeys(user_id="u1"))
        )
        assert res[0].content == "User loves Python"
        assert res[0].score and res[0].score > 0

    def test_partitions_isolated_by_user(self, stub):
        stub.write("secret", scope=MemoryScope.USER, keys=MemoryKeys(user_id="u1"))
        other = stub.retrieve(
            MemoryQuery("secret", scope=MemoryScope.USER, keys=MemoryKeys(user_id="u2"))
        )
        assert other == []

    def test_add_session(self, stub):
        ids = stub.add_session(
            [
                {"role": "user", "content": "I prefer dark mode"},
                {"role": "assistant", "content": "Noted"},
                {"role": "user", "content": ""},  # skipped
            ],
            scope=MemoryScope.USER,
            keys=MemoryKeys(user_id="u1"),
        )
        assert len(ids) == 2

    def test_missing_key_raises(self, stub):
        with pytest.raises(MissingKeyError):
            stub.write("x", scope=MemoryScope.USER, keys=MemoryKeys())

    def test_delete_by_scope(self, stub):
        stub.write("a", scope=MemoryScope.USER, keys=MemoryKeys(user_id="u1"))
        stub.write("b", scope=MemoryScope.USER, keys=MemoryKeys(user_id="u1"))
        removed = stub.delete(scope=MemoryScope.USER, keys=MemoryKeys(user_id="u1"))
        assert removed == 2
        assert stub.retrieve(
            MemoryQuery("a", scope=MemoryScope.USER, keys=MemoryKeys(user_id="u1"))
        ) == []

    def test_delete_by_ids(self, stub):
        ids = stub.write("a", scope=MemoryScope.USER, keys=MemoryKeys(user_id="u1"))
        removed = stub.delete(scope=MemoryScope.USER, keys=MemoryKeys(user_id="u1"), ids=ids)
        assert removed == 1


# ---------------------------------------------------------------------------
# Segmented shared memory (namespace)
# ---------------------------------------------------------------------------

class TestSegmentation:
    def test_namespaces_isolated(self, stub):
        stub.write("Use pytest", scope=MemoryScope.AGENT, keys=MemoryKeys(namespace="coding"))
        stub.write("Q3 revenue up", scope=MemoryScope.AGENT, keys=MemoryKeys(namespace="finance"))

        coding = stub.retrieve(
            MemoryQuery("pytest", scope=MemoryScope.AGENT, keys=MemoryKeys(namespace="coding"))
        )
        finance = stub.retrieve(
            MemoryQuery("pytest", scope=MemoryScope.AGENT, keys=MemoryKeys(namespace="finance"))
        )
        assert [m.content for m in coding] == ["Use pytest"]
        assert [m.content for m in finance] == ["Q3 revenue up"]

    def test_agents_in_same_namespace_share(self, stub):
        # Two different agents writing to the same namespace share a pool.
        stub.write("shared fact", scope=MemoryScope.AGENT, keys=MemoryKeys(namespace="coding"))
        res = stub.retrieve(
            MemoryQuery("shared", scope=MemoryScope.AGENT, keys=MemoryKeys(namespace="coding"))
        )
        assert res and res[0].content == "shared fact"


# ---------------------------------------------------------------------------
# A limited provider to exercise unsupported-scope validation
# ---------------------------------------------------------------------------

class _UserOnlyProvider:
    CAPABILITIES = frozenset({MemoryScope.USER})
    REQUIRES_SUBSTRATE = False

    def __init__(self, config):
        self._config = config

    @property
    def name(self):
        return "user_only"

    def supports(self, scope):
        return scope in self.CAPABILITIES

    def write(self, *a, **k):
        return []

    def add_session(self, *a, **k):
        return []

    def retrieve(self, *a, **k):
        return []

    def delete(self, *a, **k):
        return 0

    def close(self):
        return None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_DEFAULT_ENV = [{"name": "MEM0_API_KEY", "secret": True}]


def _write_project(tmp_path: Path, memory_yaml: dict, *, env: list | None = None) -> Path:
    (tmp_path / "identity").mkdir()
    (tmp_path / "identity" / "persona.md").write_text("You are a test agent.")
    (tmp_path / "identity" / "instructions.md").write_text("Be helpful.")
    (tmp_path / "adapters").mkdir()
    (tmp_path / "adapters" / "llm.yaml").write_text(
        yaml.safe_dump({"provider": "openai", "model": "gpt-4o"})
    )
    (tmp_path / "adapters" / "memory.yaml").write_text(yaml.safe_dump(memory_yaml))
    manifest = {
        "apiVersion": "zil.dev/v1",
        "kind": "Agent",
        "metadata": {"name": "test-agent", "version": "0.1.0"},
        "spec": {
            "identity": "./identity",
            "memory": "./adapters/memory.yaml",
            "runtime": {"framework": "adk", "llm": {"adapter": "./adapters/llm.yaml"}},
            "env": _DEFAULT_ENV if env is None else env,
        },
    }
    (tmp_path / "manifest.yaml").write_text(yaml.safe_dump(manifest))
    return tmp_path


def _statuses(result, needle: str) -> list[str]:
    return [c.status for c in result.checks if needle in c.message]


class TestValidation:
    def test_valid_mem0_config_passes(self, tmp_path):
        proj = _write_project(
            tmp_path,
            {
                "provider": "mem0",
                "mode": "managed",
                "scopes": ["session", "user", "agent"],
                "namespace": "coding",
                "retention": {"user": "90d", "agent": "90d"},
                "persist": {"exclude_pii": True},
            },
        )
        result = validate_project(proj)
        assert "fail" not in _statuses(result, "memory.yaml")

    def test_unknown_provider_fails(self, tmp_path):
        proj = _write_project(tmp_path, {"provider": "nope", "scopes": ["user"]})
        result = validate_project(proj)
        assert "fail" in _statuses(result, "memory.yaml")

    def test_unsupported_scope_fails(self, tmp_path):
        registry.register("user_only", lambda cfg: _UserOnlyProvider(cfg))
        try:
            proj = _write_project(
                tmp_path, {"provider": "user_only", "scopes": ["user", "agent"]}
            )
            result = validate_project(proj)
            fails = [c.message for c in result.checks if c.status == "fail"]
            assert any("does not support" in m and "agent" in m for m in fails)
        finally:
            # Restore registry to avoid cross-test leakage.
            registry._factories.pop("user_only", None)

    def test_managed_with_substrate_fails(self, tmp_path):
        proj = _write_project(
            tmp_path,
            {
                "provider": "mem0",
                "mode": "managed",
                "scopes": ["user"],
                "substrate": {"store": "pgvector"},
            },
        )
        result = validate_project(proj)
        fails = [c.message for c in result.checks if c.status == "fail"]
        assert any("manages its own storage" in m for m in fails)

    def test_missing_pii_exclusion_warns(self, tmp_path):
        proj = _write_project(
            tmp_path,
            {
                "provider": "mem0",
                "scopes": ["user"],
                "retention": {"user": "90d"},
                "persist": {"exclude_pii": False},
            },
        )
        result = validate_project(proj)
        warns = [c.message for c in result.checks if c.status == "warn"]
        assert any("exclude_pii" in m for m in warns)

    def test_missing_api_key_warns(self, tmp_path):
        proj = _write_project(
            tmp_path,
            {"provider": "mem0", "mode": "managed", "scopes": ["user"],
             "retention": {"user": "90d"}, "persist": {"exclude_pii": True}},
            env=[],
        )
        result = validate_project(proj)
        warns = [c.message for c in result.checks if c.status == "warn"]
        assert any("MEM0_API_KEY" in m for m in warns)

    def test_self_hosted_host_passes(self, tmp_path):
        proj = _write_project(
            tmp_path,
            {"provider": "mem0", "mode": "managed", "scopes": ["agent"],
             "namespace": "coding", "retention": {"agent": "90d"},
             "persist": {"exclude_pii": True},
             "host": "https://mem0.my-vpc.internal"},
        )
        result = validate_project(proj)
        passes = [c.message for c in result.checks if c.status == "pass"]
        assert any("self-hosted Mem0 server" in m and "host=" in m for m in passes)

    def test_invalid_host_url_fails(self, tmp_path):
        proj = _write_project(
            tmp_path,
            {"provider": "mem0", "mode": "managed", "scopes": ["agent"],
             "namespace": "coding", "retention": {"agent": "90d"},
             "persist": {"exclude_pii": True},
             "host": "mem0.my-vpc.internal"},  # no scheme
        )
        result = validate_project(proj)
        fails = [c.message for c in result.checks if c.status == "fail"]
        assert any("must be an http(s) URL" in m for m in fails)

    def test_host_from_env_passes(self, tmp_path):
        proj = _write_project(
            tmp_path,
            {"provider": "mem0", "mode": "managed", "scopes": ["agent"],
             "namespace": "coding", "retention": {"agent": "90d"},
             "persist": {"exclude_pii": True}},
            env=[
                {"name": "MEM0_API_KEY", "secret": True},
                {"name": "MEM0_API_BASE"},
            ],
        )
        result = validate_project(proj)
        passes = [c.message for c in result.checks if c.status == "pass"]
        assert any("self-hosted Mem0 server (host from env)" in m for m in passes)
