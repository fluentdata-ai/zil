"""Tests for A2A collaboration foundation (ZIL-RFC-005 Phase 1b).

Covers the framework-neutral contract, static discovery/resolution,
spec.collaborators loading, and `zil validate` checks.
"""

from pathlib import Path

import pytest
import yaml

from zil.collaboration.contract import (
    AgentCard,
    AgentSkill,
    ContextTransferPolicy,
    PeerRef,
)
from zil.collaboration.discovery import (
    HttpRegistryResolver,
    RegistryResolver,
    StaticResolver,
    build_resolver,
    interpolate_env,
)
from zil.schema.loader import (
    ValidationResult,
    _check_collaborator_skills_online,
    _check_collaborators,
)
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


class TestRegistryResolver:
    def test_resolves_ref_via_injected_registry(self):
        r = RegistryResolver(registry={"billing": "https://billing.run.app"})
        ref = PeerRef(name="b", ref="zil://fleet/billing")
        assert r.resolve_url(ref) == "https://billing.run.app"

    def test_resolves_ref_from_env(self):
        r = RegistryResolver(
            env={"ZIL_FLEET_REGISTRY": "billing=https://b,invoices=https://i"}
        )
        ref = PeerRef(name="i", ref="zil://fleet/invoices")
        assert r.resolve_url(ref) == "https://i"

    def test_plain_url_peer_is_delegated(self):
        r = RegistryResolver(registry={}, env={"U": "https://x"})
        assert r.resolve_url(PeerRef(name="p", url="${U}")) == "https://x"

    def test_unconfigured_registry_raises(self):
        r = RegistryResolver(registry={})
        ref = PeerRef(name="b", ref="zil://fleet/billing")
        with pytest.raises(ValueError, match="no .*registry is configured"):
            r.resolve_url(ref)

    def test_unknown_ref_raises(self):
        r = RegistryResolver(registry={"billing": "https://b"})
        ref = PeerRef(name="x", ref="zil://fleet/unknown")
        with pytest.raises(ValueError, match="not found in the registry"):
            r.resolve_url(ref)

    def test_bad_scheme_raises(self):
        r = RegistryResolver(registry={"billing": "https://b"})
        ref = PeerRef(name="x", ref="http://billing")
        with pytest.raises(ValueError, match="must use the"):
            r.resolve_url(ref)

    def test_resolve_fetches_card(self):
        captured = {}

        def fake_fetch(url):
            captured["url"] = url
            return {"name": "billing", "url": "", "version": "1",
                    "skills": [{"id": "refund", "name": "Refund", "tags": []}]}

        r = RegistryResolver(
            registry={"billing": "https://billing"}, fetcher=fake_fetch
        )
        card = r.resolve(PeerRef(name="b", ref="zil://fleet/billing"))
        assert captured["url"] == "https://billing"
        assert card.skill_ids() == ["refund"]
        assert card.url == "https://billing"


# ---------------------------------------------------------------------------
# Discovery — HttpRegistryResolver (remote registry of record, RFC-007)
# ---------------------------------------------------------------------------


class TestHttpRegistryResolver:
    def test_resolve_url_calls_registry_endpoint(self):
        captured = {}

        def fake_registry(resolve_url):
            captured["url"] = resolve_url
            return {"name": "billing", "url": "https://billing.run.app"}

        r = HttpRegistryResolver(
            "https://registry.example/api/v1/registry",
            registry_fetcher=fake_registry,
        )
        url = r.resolve_url(PeerRef(name="b", ref="zil://fleet/billing"))
        assert url == "https://billing.run.app"
        assert captured["url"] == (
            "https://registry.example/api/v1/registry/agents/billing"
        )

    def test_registry_url_from_env_is_interpolated(self):
        r = HttpRegistryResolver(
            env={"ZIL_FLEET_REGISTRY_URL": "https://reg/${STAGE}", "STAGE": "prod"},
            registry_fetcher=lambda u: {"url": u},
        )
        # The interpolated registry base is used to build the resolve URL.
        url = r.resolve_url(PeerRef(name="b", ref="zil://fleet/x"))
        assert url == "https://reg/prod/agents/x"

    def test_resolve_prefers_embedded_card(self):
        def fake_registry(_url):
            return {
                "url": "https://billing.run.app",
                "card": {"name": "billing", "url": "", "version": "1",
                         "skills": [{"id": "refund", "name": "Refund", "tags": []}]},
            }

        def card_fetcher(_url):  # pragma: no cover — must not be called
            raise AssertionError("should not fetch well-known card when embedded")

        r = HttpRegistryResolver(
            "https://reg", registry_fetcher=fake_registry, card_fetcher=card_fetcher
        )
        card = r.resolve(PeerRef(name="b", ref="zil://fleet/billing"))
        assert card.skill_ids() == ["refund"]
        assert card.url == "https://billing.run.app"

    def test_resolve_falls_back_to_well_known_card(self):
        def fake_registry(_url):
            return {"url": "https://billing.run.app"}

        def card_fetcher(url):
            assert url == "https://billing.run.app"
            return {"name": "billing", "url": url, "version": "1",
                    "skills": [{"id": "lookup", "name": "Lookup", "tags": []}]}

        r = HttpRegistryResolver(
            "https://reg", registry_fetcher=fake_registry, card_fetcher=card_fetcher
        )
        card = r.resolve(PeerRef(name="b", ref="zil://fleet/billing"))
        assert card.skill_ids() == ["lookup"]

    def test_plain_url_peer_is_delegated(self):
        r = HttpRegistryResolver(
            "https://reg",
            env={"U": "https://x.run.app"},
            registry_fetcher=lambda u: {"url": "unused"},
        )
        assert r.resolve_url(PeerRef(name="p", url="${U}")) == "https://x.run.app"

    def test_no_registry_configured_raises(self):
        r = HttpRegistryResolver(registry_fetcher=lambda u: {"url": "x"}, env={})
        with pytest.raises(ValueError, match="no .*registry is configured"):
            r.resolve_url(PeerRef(name="b", ref="zil://fleet/billing"))

    def test_bad_scheme_raises(self):
        r = HttpRegistryResolver("https://reg", registry_fetcher=lambda u: {"url": "x"})
        with pytest.raises(ValueError, match="must use the"):
            r.resolve_url(PeerRef(name="b", ref="http://billing"))

    def test_unknown_ref_raises(self):
        r = HttpRegistryResolver("https://reg", registry_fetcher=lambda u: {})
        with pytest.raises(ValueError, match="not found in the registry"):
            r.resolve_url(PeerRef(name="b", ref="zil://fleet/missing"))

    def test_default_fetcher_attaches_bearer_token(self, monkeypatch):
        captured = {}

        def fake_get(url, headers=None, timeout=None):
            captured["headers"] = headers

            class _Resp:
                def raise_for_status(self):
                    pass

                def json(self):
                    return {"url": "https://billing.run.app"}

            return _Resp()

        import httpx

        monkeypatch.setattr(httpx, "get", fake_get)
        r = HttpRegistryResolver(
            "https://reg",
            env={"ZIL_FLEET_REGISTRY_URL": "https://reg", "ZIL_FLEET_REGISTRY_TOKEN": "secret"},
        )
        r.resolve_url(PeerRef(name="b", ref="zil://fleet/billing"))
        assert captured["headers"]["Authorization"] == "Bearer secret"

    def test_default_fetcher_no_token_no_auth_header(self, monkeypatch):
        captured = {}

        def fake_get(url, headers=None, timeout=None):
            captured["headers"] = headers

            class _Resp:
                def raise_for_status(self):
                    pass

                def json(self):
                    return {"url": "https://billing.run.app"}

            return _Resp()

        import httpx

        monkeypatch.setattr(httpx, "get", fake_get)
        r = HttpRegistryResolver("https://reg", env={})
        r.resolve_url(PeerRef(name="b", ref="zil://fleet/billing"))
        assert "Authorization" not in captured["headers"]


class TestBuildResolver:
    def test_http_resolver_when_url_set(self):
        r = build_resolver(env={"ZIL_FLEET_REGISTRY_URL": "https://reg"})
        assert isinstance(r, HttpRegistryResolver)

    def test_registry_resolver_otherwise(self):
        r = build_resolver(env={})
        assert isinstance(r, RegistryResolver)


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

    def test_self_reference_fails(self):
        # An agent listing itself is a topology self-cycle (RFC-005 §10.1).
        manifest = {
            "metadata": {"name": "orchestrator"},
            "spec": {"collaborators": [{"name": "orchestrator", "url": "u"}]},
        }
        result = ValidationResult()
        _check_collaborators(manifest, result)
        statuses = [(c.status, c.message) for c in result.checks]
        assert any(
            s == "fail" and "self-reference" in m for s, m in statuses
        )

    def test_non_self_reference_has_no_self_fail(self):
        manifest = {
            "metadata": {"name": "orchestrator"},
            "spec": {"collaborators": [{"name": "billing", "url": "u"}]},
        }
        result = ValidationResult()
        _check_collaborators(manifest, result)
        assert not any(
            "self-reference" in c.message for c in result.checks
        )


class _FakeResolver:
    """Resolver returning a card with a fixed skill set, or raising on fetch."""

    def __init__(self, skills=None, *, error=None):
        self._skills = skills or []
        self._error = error

    def resolve(self, ref):
        if self._error is not None:
            raise self._error
        return AgentCard(
            name=ref.name, description="", url="https://peer", version="1",
            skills=[AgentSkill(id=s, name=s) for s in self._skills],
        )


class TestOnlineSkillValidation:
    def _run(self, collaborators, resolver):
        manifest = {"spec": {"collaborators": collaborators}}
        result = ValidationResult()
        _check_collaborator_skills_online(manifest, result, resolver=resolver)
        return [(c.status, c.message) for c in result.checks]

    def test_advertised_skill_passes(self):
        statuses = self._run(
            [{"name": "billing", "url": "u", "skills": ["refund"]}],
            _FakeResolver(skills=["refund", "lookup"]),
        )
        assert any(s == "pass" and "online skill check OK" in m for s, m in statuses)

    def test_unadvertised_skill_fails(self):
        statuses = self._run(
            [{"name": "billing", "url": "u", "skills": ["delete"]}],
            _FakeResolver(skills=["refund"]),
        )
        assert any(s == "fail" and "not " in m and "advertised" in m
                   for s, m in statuses)

    def test_fetch_failure_warns(self):
        statuses = self._run(
            [{"name": "billing", "url": "u", "skills": ["refund"]}],
            _FakeResolver(error=RuntimeError("down")),
        )
        assert any(s == "warn" and "could not fetch" in m for s, m in statuses)

    def test_no_declared_skills_is_skipped(self):
        statuses = self._run(
            [{"name": "billing", "url": "u"}],
            _FakeResolver(skills=["refund"]),
        )
        assert statuses == []
