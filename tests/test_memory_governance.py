"""Tests for memory governance (RFC-003, acceptance criteria 7 & 8).

Covers:
  7. `zil audit` surfaces PII, retention, and poisoning findings.
  8. `zil pack` records memory binding (config only) with no data/secrets.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from zil.packaging.archive import build_archive, read_archive
from zil.sdk.audit import Category, Severity
from zil.sdk.audit.memory_governance import check_memory_governance


def _project(tmp_path: Path, memory_yaml: dict | None) -> Path:
    (tmp_path / "identity").mkdir()
    (tmp_path / "identity" / "persona.md").write_text("You are a test agent.")
    (tmp_path / "adapters").mkdir()
    (tmp_path / "adapters" / "llm.yaml").write_text(
        yaml.safe_dump({"provider": "openai", "model": "gpt-4o"})
    )
    spec = {
        "identity": "./identity",
        "runtime": {"framework": "adk", "llm": {"adapter": "./adapters/llm.yaml"}},
        "env": [{"name": "MEM0_API_KEY", "secret": True}],
    }
    if memory_yaml is not None:
        (tmp_path / "adapters" / "memory.yaml").write_text(yaml.safe_dump(memory_yaml))
        spec["memory"] = "./adapters/memory.yaml"
    manifest = {
        "apiVersion": "zil.dev/v1",
        "kind": "Agent",
        "metadata": {"name": "mem-agent", "version": "0.1.0"},
        "spec": spec,
    }
    (tmp_path / "manifest.yaml").write_text(yaml.safe_dump(manifest))
    return tmp_path


def _messages(section, severity):
    return [f.message for f in section.findings if f.severity == severity]


class TestAuditFindings:
    def test_no_memory_passes(self, tmp_path):
        section = check_memory_governance(_project(tmp_path, None))
        assert section.category is Category.MEMORY_GOVERNANCE
        assert section.passed

    def test_pii_without_exclusion_warns(self, tmp_path):
        proj = _project(
            tmp_path,
            {"provider": "mem0", "scopes": ["user"], "retention": {"user": "90d"},
             "persist": {"exclude_pii": False}},
        )
        section = check_memory_governance(proj)
        warns = _messages(section, Severity.WARNING)
        assert any("exclude_pii" in m for m in warns)

    def test_missing_retention_warns(self, tmp_path):
        proj = _project(
            tmp_path,
            {"provider": "mem0", "scopes": ["user"], "persist": {"exclude_pii": True}},
        )
        section = check_memory_governance(proj)
        warns = _messages(section, Severity.WARNING)
        assert any("retention" in m.lower() for m in warns)

    def test_shared_namespace_poisoning_warning(self, tmp_path):
        proj = _project(
            tmp_path,
            {"provider": "mem0", "scopes": ["agent"], "namespace": "coding",
             "retention": {"agent": "90d"}, "persist": {"exclude_pii": True}},
        )
        section = check_memory_governance(proj)
        warns = _messages(section, Severity.WARNING)
        assert any("poisoning" in m.lower() or "injection" in m.lower() for m in warns)

    def test_clean_config_minimal_warnings(self, tmp_path):
        proj = _project(
            tmp_path,
            {"provider": "mem0", "scopes": ["user"], "retention": {"user": "90d"},
             "persist": {"exclude_pii": True}},
        )
        section = check_memory_governance(proj)
        # No PII or retention warnings for a well-formed user-scope config.
        warns = _messages(section, Severity.WARNING)
        assert not any("exclude_pii" in m or "retention" in m.lower() for m in warns)


class TestPackConfigOnly:
    def test_binding_recorded_no_secrets_no_data(self, tmp_path):
        proj = _project(
            tmp_path,
            {"provider": "mem0", "mode": "managed", "scopes": ["user", "agent"],
             "namespace": "coding", "retention": {"user": "90d", "agent": "90d"},
             "persist": {"exclude_pii": True}},
        )
        out = tmp_path / "dist"
        archive = build_archive(proj, out)
        meta = read_archive(archive)

        assert meta.memory_binding is not None
        binding = meta.memory_binding
        assert binding["provider"] == "mem0"
        assert binding["namespace"] == "coding"
        assert binding["exclude_pii"] is True
        assert binding["has_substrate"] is False

        # The binding must not carry secrets or raw memory data.
        serialized = str(binding).lower()
        assert "api_key" not in serialized
        assert "secret" not in serialized

    def test_no_memory_binding_when_absent(self, tmp_path):
        proj = _project(tmp_path, None)
        out = tmp_path / "dist"
        archive = build_archive(proj, out)
        meta = read_archive(archive)
        assert meta.memory_binding is None
