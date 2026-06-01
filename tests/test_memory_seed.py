"""Tests for packable memory seeds (RFC-003 follow-up).

Covers:
  - PII filter (scan/redact/drop/warn).
  - seed file load + normalization + digest determinism + scope validation.
  - provider list_all (stub).
  - idempotent runtime seeding (seed once; no-op on repeat; incremental).
  - pack integration: authored seed bundled, PII dropped, BUILD_META.seed.
  - validation + audit for seeds.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from zil.packaging.archive import build_archive, gather_memory_seed, read_archive
from zil.sdk.memory import (
    MemoryConfig,
    MemoryKeys,
    MemoryScope,
    build_provider,
    pii,
)
from zil.sdk.memory.seed import (
    SEED_ARCHIVE_PATH,
    SeedError,
    compute_digest,
    dump_seed_jsonl,
    entry_hash,
    load_seed_file,
    read_seed_jsonl,
    seed_if_needed,
)

# ---------------------------------------------------------------------------
# PII filter
# ---------------------------------------------------------------------------

class TestPII:
    def test_scan_detects_categories(self):
        assert "email" in pii.scan("contact me at a@b.com")
        assert "ssn" in pii.scan("ssn 123-45-6789")
        assert pii.scan("just behavioral knowledge") == []

    def test_redact(self):
        out = pii.redact("email a@b.com now")
        assert "a@b.com" not in out
        assert "[REDACTED]" in out

    def test_filter_drop(self):
        res = pii.filter_entries(
            [{"content": "use pytest"}, {"content": "email a@b.com"}], mode="drop"
        )
        assert len(res.kept) == 1
        assert len(res.dropped) == 1
        assert res.pii_detected

    def test_filter_redact_keeps_all(self):
        res = pii.filter_entries([{"content": "ping 10.0.0.1"}], mode="redact")
        assert len(res.kept) == 1
        assert "[REDACTED]" in res.kept[0]["content"]

    def test_filter_warn_keeps_unchanged(self):
        res = pii.filter_entries([{"content": "email a@b.com"}], mode="warn")
        assert res.kept[0]["content"] == "email a@b.com"
        assert res.warnings


# ---------------------------------------------------------------------------
# Seed file format
# ---------------------------------------------------------------------------

def _write_seed(tmp_path: Path, data: dict, name: str = "seed.yaml") -> Path:
    p = tmp_path / name
    p.write_text(yaml.safe_dump(data))
    return p


class TestSeedFile:
    def test_load_basic(self, tmp_path):
        path = _write_seed(
            tmp_path,
            {"version": 1, "namespace": "coding", "memories": [
                "Always run pytest",
                {"content": "Use ruff", "metadata": {"topic": "tooling"}},
            ]},
        )
        seed = load_seed_file(path)
        assert len(seed) == 2
        assert seed.namespace == "coding"
        assert seed.entries[1]["metadata"]["topic"] == "tooling"

    def test_missing_memories_fails(self, tmp_path):
        path = _write_seed(tmp_path, {"version": 1})
        with pytest.raises(SeedError, match="memories"):
            load_seed_file(path)

    def test_non_agent_scope_fails(self, tmp_path):
        path = _write_seed(
            tmp_path, {"memories": ["x"], "scopes": ["user"]}
        )
        with pytest.raises(SeedError, match="agent"):
            load_seed_file(path)

    def test_empty_content_fails(self, tmp_path):
        path = _write_seed(tmp_path, {"memories": [{"content": "  "}]})
        with pytest.raises(SeedError, match="empty"):
            load_seed_file(path)

    def test_digest_is_order_independent(self):
        a = [{"content": "one"}, {"content": "two"}]
        b = [{"content": "two"}, {"content": "one"}]
        assert compute_digest(a) == compute_digest(b)

    def test_jsonl_roundtrip(self):
        from zil.sdk.memory.seed import SeedSet

        seed = SeedSet(entries=[{"content": "a"}, {"content": "b"}])
        data = dump_seed_jsonl(seed)
        back = read_seed_jsonl(data.decode())
        assert [e["content"] for e in back.entries] == ["a", "b"]

    def test_entry_hash_ignores_seed_meta(self):
        h1 = entry_hash("x", {"topic": "t"})
        h2 = entry_hash("x", {"topic": "t", "zil_seed_hash": "abc"})
        assert h1 == h2


# ---------------------------------------------------------------------------
# Provider list_all
# ---------------------------------------------------------------------------

class TestListAll:
    def test_stub_list_all(self):
        provider = build_provider(MemoryConfig.from_dict({"provider": "stub"}))
        keys = MemoryKeys(namespace="coding")
        provider.write("a", scope=MemoryScope.AGENT, keys=keys)
        provider.write("b", scope=MemoryScope.AGENT, keys=keys)
        items = provider.list_all(scope=MemoryScope.AGENT, keys=keys)
        assert {i.content for i in items} == {"a", "b"}

    def test_stub_list_all_isolated_by_namespace(self):
        provider = build_provider(MemoryConfig.from_dict({"provider": "stub"}))
        provider.write("a", scope=MemoryScope.AGENT, keys=MemoryKeys(namespace="x"))
        items = provider.list_all(scope=MemoryScope.AGENT, keys=MemoryKeys(namespace="y"))
        assert items == []


# ---------------------------------------------------------------------------
# Idempotent runtime seeding
# ---------------------------------------------------------------------------

class TestSeedIfNeeded:
    def _cfg(self):
        return MemoryConfig.from_dict(
            {"provider": "stub", "scopes": ["agent"], "namespace": "coding"}
        )

    def test_seeds_once(self, tmp_path):
        provider = build_provider(self._cfg())
        seed = _write_seed(
            tmp_path, {"namespace": "coding", "memories": ["use pytest", "use ruff"]}
        )
        report = seed_if_needed(provider, self._cfg(), seed)
        assert report.seeded == 2
        items = provider.list_all(
            scope=MemoryScope.AGENT, keys=MemoryKeys(namespace="coding")
        )
        # 2 entries + 1 marker
        assert len(items) == 3

    def test_second_call_is_noop(self, tmp_path):
        provider = build_provider(self._cfg())
        seed = _write_seed(tmp_path, {"namespace": "coding", "memories": ["use pytest"]})
        seed_if_needed(provider, self._cfg(), seed)
        report2 = seed_if_needed(provider, self._cfg(), seed)
        assert report2.skipped
        assert report2.reason == "already seeded"

    def test_grown_seed_adds_only_new(self, tmp_path):
        provider = build_provider(self._cfg())
        seed1 = _write_seed(tmp_path, {"namespace": "coding", "memories": ["a"]}, "s1.yaml")
        seed_if_needed(provider, self._cfg(), seed1)
        seed2 = _write_seed(
            tmp_path, {"namespace": "coding", "memories": ["a", "b"]}, "s2.yaml"
        )
        report = seed_if_needed(provider, self._cfg(), seed2)
        # Only "b" is new (digest changed → not skipped; "a" already present).
        assert report.seeded == 1

    def test_pii_dropped_before_seeding(self, tmp_path):
        provider = build_provider(self._cfg())
        seed = _write_seed(
            tmp_path,
            {"namespace": "coding", "memories": ["use pytest", "email a@b.com"]},
        )
        report = seed_if_needed(provider, self._cfg(), seed)
        assert report.seeded == 1  # PII entry dropped

    def test_no_namespace_skips(self, tmp_path):
        cfg = MemoryConfig.from_dict({"provider": "stub", "scopes": ["agent"]})
        provider = build_provider(cfg)
        seed = _write_seed(tmp_path, {"memories": ["x"]})  # no namespace anywhere
        report = seed_if_needed(provider, cfg, seed)
        assert report.skipped


# ---------------------------------------------------------------------------
# Pack integration
# ---------------------------------------------------------------------------

def _project_with_seed(tmp_path: Path, memories: list, *, namespace="coding") -> Path:
    (tmp_path / "identity").mkdir()
    (tmp_path / "identity" / "persona.md").write_text("You are a test agent.")
    (tmp_path / "adapters").mkdir()
    (tmp_path / "adapters" / "llm.yaml").write_text(
        yaml.safe_dump({"provider": "openai", "model": "gpt-4o"})
    )
    (tmp_path / "adapters" / "memory.yaml").write_text(
        yaml.safe_dump({
            "provider": "mem0", "mode": "managed", "scopes": ["agent"],
            "namespace": namespace, "retention": {"agent": "90d"},
            "persist": {"exclude_pii": True},
            "seed": {"file": "../memory/seed.yaml"},
        })
    )
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "seed.yaml").write_text(
        yaml.safe_dump({"namespace": namespace, "memories": memories})
    )
    manifest = {
        "apiVersion": "zil.dev/v1",
        "kind": "Agent",
        "metadata": {"name": "seed-agent", "version": "0.1.0"},
        "spec": {
            "identity": "./identity",
            "memory": "./adapters/memory.yaml",
            "runtime": {"framework": "adk", "llm": {"adapter": "./adapters/llm.yaml"}},
            "env": [{"name": "MEM0_API_KEY", "secret": True}],
        },
    }
    (tmp_path / "manifest.yaml").write_text(yaml.safe_dump(manifest))
    return tmp_path


class TestPackSeed:
    def test_gather_filters_pii(self, tmp_path):
        proj = _project_with_seed(tmp_path, ["use pytest", "email a@b.com"])
        manifest = yaml.safe_load((proj / "manifest.yaml").read_text())
        seed, result = gather_memory_seed(proj, manifest)
        assert len(seed) == 1
        assert result.dropped

    def test_archive_bundles_seed_and_meta(self, tmp_path):
        proj = _project_with_seed(tmp_path, ["use pytest", "use ruff"])
        archive = build_archive(proj, proj / "dist")
        meta = read_archive(archive)
        assert meta.memory_binding is not None
        seed_meta = meta.memory_binding.get("seed")
        assert seed_meta is not None
        assert seed_meta["count"] == 2
        assert seed_meta["scopes"] == ["agent"]
        assert seed_meta["namespace"] == "coding"
        assert seed_meta["pii_filtered"] is True

    def test_archive_contains_seed_jsonl(self, tmp_path):
        import tarfile

        proj = _project_with_seed(tmp_path, ["use pytest"])
        archive = build_archive(proj, proj / "dist")
        with tarfile.open(archive, "r:gz") as tar:
            names = tar.getnames()
            assert SEED_ARCHIVE_PATH in names
            # raw authored seed.yaml must NOT be bundled (PII-bypass risk)
            assert "memory/seed.yaml" not in names

    def test_pii_only_seed_not_bundled(self, tmp_path):
        import tarfile

        proj = _project_with_seed(tmp_path, ["email a@b.com"])
        archive = build_archive(proj, proj / "dist")
        with tarfile.open(archive, "r:gz") as tar:
            assert SEED_ARCHIVE_PATH not in tar.getnames()

    def test_gather_merges_and_dedups_exported(self, tmp_path):
        proj = _project_with_seed(tmp_path, ["use pytest"])
        manifest = yaml.safe_load((proj / "manifest.yaml").read_text())
        exported = [
            {"content": "use pytest", "metadata": {}},  # dup of authored
            {"content": "deploy on fridays", "metadata": {}},  # new
        ]
        seed, _ = gather_memory_seed(proj, manifest, exported_entries=exported)
        contents = {e["content"] for e in seed.entries}
        assert contents == {"use pytest", "deploy on fridays"}


# ---------------------------------------------------------------------------
# Validation + audit
# ---------------------------------------------------------------------------

class TestSeedValidation:
    def test_valid_seed_passes(self, tmp_path):
        from zil.schema.loader import validate_project

        proj = _project_with_seed(tmp_path, ["use pytest"])
        result = validate_project(proj)
        msgs = [c.message for c in result.checks if "memory seed OK" in c.message]
        assert msgs
        assert "fail" not in [c.status for c in result.checks if "seed" in c.message]

    def test_missing_seed_file_fails(self, tmp_path):
        from zil.schema.loader import validate_project

        proj = _project_with_seed(tmp_path, ["use pytest"])
        (proj / "memory" / "seed.yaml").unlink()
        result = validate_project(proj)
        fails = [c.message for c in result.checks if c.status == "fail"]
        assert any("seed.file not found" in m for m in fails)


class TestSeedAudit:
    def test_clean_seed_passes(self, tmp_path):
        from zil.sdk.audit.memory_governance import check_memory_governance

        proj = _project_with_seed(tmp_path, ["use pytest", "use ruff"])
        section = check_memory_governance(proj)
        msgs = [f.message for f in section.findings]
        assert any("Memory seed clean" in m for m in msgs)

    def test_pii_seed_warns(self, tmp_path):
        from zil.sdk.audit import Severity
        from zil.sdk.audit.memory_governance import check_memory_governance

        proj = _project_with_seed(tmp_path, ["use pytest", "ssn 123-45-6789"])
        section = check_memory_governance(proj)
        warns = [f.message for f in section.findings if f.severity == Severity.WARNING]
        assert any("seed contains PII" in m for m in warns)
