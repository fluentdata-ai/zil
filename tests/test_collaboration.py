"""Tests for A2A collaboration foundation (ZIL-RFC-005 Phase 1b).

Covers the framework-neutral contract, static discovery/resolution,
spec.collaborators loading, and `zil validate` checks.
"""

from pathlib import Path

import pytest
import yaml

from zil.collaboration.contract import (
    AgentCard,
    ContextTransferPolicy,
    PeerRef,
)
from zil.collaboration.discovery import StaticResolver, interpolate_env
from zil.schema.loader import ValidationResult, _check_collaborators
from zil.sdk.loader import load_project

# ---------------------------------------------------------------------------
# Contract — AgentCard.from_dict
# ---------------------------------------------------------------------------


class TestAgentCardFromDict:
    def test_parses_camelcase_card(self):
        card = AgentCard.from_dict({
            "name": "billing",
            "description": "Handles billing",
            "url": "https://billing/a2a",
            "version": "1.2.0",
            "protocolVersion": "0.3.0",
            "preferredTransport": "JSONRPC",
            "capabilities": {"streaming": True},
            "skills": [
                {"id": "refund", "name": "Refund", "description": "Issue refund",
                 "tags": ["billing"], "inputModes": ["text/plain"]},
            ],
        })
        assert card.name == "billing"
        assert card.protocol_version == "0.3.0"
        assert card.preferred_transport == "JSONRPC"
        assert card.skill_ids() == ["refund"]
        assert card.skills[0].tags == ["billing"]
        assert card.skills[0].input_modes == ["text/plain"]

    def test_defaults_when_minimal(self):
        card = AgentCard.from_dict({"name": "x", "url": "u", "version": "1"})
        assert card.protocol_version == "0.3.0"
        assert card.preferred_transport == "JSONRPC"
        assert card.skills == []


# ---------------------------------------------------------------------------
# Discovery — env interpolation + StaticResolver
# ---------------------------------------------------------------------------


class TestInterpolateEnv:
    def test_replaces_vars(self):
        assert interpolate_env("${A}/x", {"A": "http://h"}) == "http://h/x"

    def test_no_vars_passthrough(self):
        assert interpolate_env("http://h/x", {}) == "http://h/x"

    def test_missing_var_raises(self):
        with pytest.raises(KeyError):
            interpolate_env("${MISSING}", {})


class TestStaticResolver:
    def test_resolve_url_plain(self):
        r = StaticResolver(env={})
        assert r.resolve_url(PeerRef(name="p", url="https://h")) == "https://h"

    def test_resolve_url_interpolates(self):
        r = StaticResolver(env={"BILLING_URL": "https://billing"})
        ref = PeerRef(name="p", url="${BILLING_URL}")
        assert r.resolve_url(ref) == "https://billing"

    def test_resolve_url_missing_url_raises(self):
        r = StaticResolver(env={})
        with pytest.raises(ValueError, match="no 'url'"):
            r.resolve_url(PeerRef(name="p"))

    def test_resolve_url_unset_env_raises(self):
        r = StaticResolver(env={})
        with pytest.raises(ValueError, match="unset env var"):
            r.resolve_url(PeerRef(name="p", url="${NOPE}"))

    def test_resolve_url_ref_unsupported(self):
        r = StaticResolver(env={})
        with pytest.raises(ValueError, match="registry discovery"):
            r.resolve_url(PeerRef(name="p", ref="zil://fleet/p"))

    def test_resolve_fetches_card_via_injected_fetcher(self):
        captured = {}

        def fake_fetch(url):
            captured["url"] = url
            return {
                "name": "billing", "description": "d", "url": "",
                "version": "1", "skills": [{"id": "refund", "name": "Refund",
                                            "tags": []}],
            }

        r = StaticResolver(env={"U": "https://billing"}, fetcher=fake_fetch)
        card = r.resolve(PeerRef(name="p", url="${U}"))
        assert captured["url"] == "https://billing"
        assert card.skill_ids() == ["refund"]
        # Card url backfilled from the resolved url when card omits it.
        assert card.url == "https://billing"


# ---------------------------------------------------------------------------
# Loader — spec.collaborators -> ProjectContext.collaborators
# ---------------------------------------------------------------------------


def _write_collab_project(tmp_path: Path, collaborators: list[dict]) -> Path:
    manifest = {
        "version": "1",
        "metadata": {"name": "caller", "version": "1.0.0"},
        "spec": {
            "runtime": {"framework": "stub", "llm": {"adapter": "./adapters/llm.yaml"}},
            "identity": "./identity",
            "collaborators": collaborators,
        },
    }
    (tmp_path / "manifest.yaml").write_text(yaml.dump(manifest))
    (tmp_path / "identity").mkdir()
    (tmp_path / "identity" / "persona.md").write_text("persona")
    (tmp_path / "adapters").mkdir()
    (tmp_path / "adapters" / "llm.yaml").write_text(
        "provider: gemini\nmodel: gemini-3.5-flash\n"
    )
    return tmp_path


class TestLoadCollaborators:
    def test_loads_peer_refs(self, tmp_path):
        proj = _write_collab_project(tmp_path, [
            {"name": "billing", "url": "https://billing",
             "skills": ["refund"], "auth": "bearer",
             "context_transfer": {"send": "none", "redact": ["SSN"]}},
        ])
        ctx = load_project(proj)
        assert len(ctx.collaborators) == 1
        peer = ctx.collaborators[0]
        assert isinstance(peer, PeerRef)
        assert peer.name == "billing"
        assert peer.url == "https://billing"
        assert peer.skills == ["refund"]
        assert peer.auth == "bearer"
        assert isinstance(peer.context_transfer, ContextTransferPolicy)
        assert peer.context_transfer.send == "none"
        assert peer.context_transfer.redact == ["SSN"]

    def test_no_collaborators_is_empty(self, tmp_path):
        manifest = {
            "version": "1",
            "metadata": {"name": "caller", "version": "1.0.0"},
            "spec": {
                "runtime": {"framework": "stub",
                            "llm": {"adapter": "./adapters/llm.yaml"}},
                "identity": "./identity",
            },
        }
        (tmp_path / "manifest.yaml").write_text(yaml.dump(manifest))
        (tmp_path / "identity").mkdir()
        (tmp_path / "identity" / "persona.md").write_text("persona")
        (tmp_path / "adapters").mkdir()
        (tmp_path / "adapters" / "llm.yaml").write_text("provider: gemini\nmodel: m\n")
        ctx = load_project(tmp_path)
        assert ctx.collaborators == []


# ---------------------------------------------------------------------------
# Validation — _check_collaborators
# ---------------------------------------------------------------------------


def _statuses(collaborators: list[dict]) -> list[tuple[str, str]]:
    manifest = {"spec": {"collaborators": collaborators}}
    result = ValidationResult()
    _check_collaborators(manifest, result)
    return [(c.status, c.message) for c in result.checks]


class TestCheckCollaborators:
    def test_valid_passes(self):
        result = ValidationResult()
        _check_collaborators(
            {"spec": {"collaborators": [{"name": "b", "url": "https://b"}]}}, result
        )
        assert result.error_count == 0
        assert any(c.status == "pass" for c in result.checks)

    def test_absent_is_noop(self):
        result = ValidationResult()
        _check_collaborators({"spec": {}}, result)
        assert result.checks == []

    def test_both_url_and_ref_fails(self):
        statuses = _statuses([{"name": "b", "url": "u", "ref": "r"}])
        assert any(s == "fail" and "exactly one" in m for s, m in statuses)

    def test_neither_url_nor_ref_fails(self):
        statuses = _statuses([{"name": "b"}])
        assert any(s == "fail" and "exactly one" in m for s, m in statuses)

    def test_unknown_auth_fails(self):
        statuses = _statuses([{"name": "b", "url": "u", "auth": "magic"}])
        assert any(s == "fail" and "unknown mode" in m for s, m in statuses)

    def test_auth_none_warns(self):
        statuses = _statuses([{"name": "b", "url": "u", "auth": "none"}])
        assert any(s == "warn" and "disables" in m for s, m in statuses)

    def test_duplicate_names_fail(self):
        statuses = _statuses([
            {"name": "b", "url": "u1"},
            {"name": "b", "url": "u2"},
        ])
        assert any(s == "fail" and "duplicate" in m for s, m in statuses)
