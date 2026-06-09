"""Tests for inter-agent authentication (ZIL-RFC-005 §10.2, Phase 2)."""

import pytest

from zil.collaboration.auth import (
    BearerAuthenticator,
    GcpIdTokenAuthenticator,
    NoneAuthenticator,
    _bearer_env_candidates,
    build_authenticator,
)
from zil.collaboration.contract import PeerRef


class TestNoneAuthenticator:
    def test_headers_empty(self):
        assert NoneAuthenticator().headers() == {}
        assert NoneAuthenticator().mode == "none"


class TestBearerAuthenticator:
    def test_uses_first_set_candidate(self):
        auth = BearerAuthenticator(
            ["ZIL_A2A_TOKEN_BILLING", "ZIL_A2A_TOKEN"],
            env={"ZIL_A2A_TOKEN_BILLING": "abc", "ZIL_A2A_TOKEN": "shared"},
        )
        assert auth.headers() == {"Authorization": "Bearer abc"}

    def test_falls_back_to_shared(self):
        auth = BearerAuthenticator(
            ["ZIL_A2A_TOKEN_BILLING", "ZIL_A2A_TOKEN"],
            env={"ZIL_A2A_TOKEN": "shared"},
        )
        assert auth.headers() == {"Authorization": "Bearer shared"}

    def test_missing_token_raises(self):
        auth = BearerAuthenticator(["ZIL_A2A_TOKEN_BILLING"], env={})
        with pytest.raises(RuntimeError, match="no token found"):
            auth.headers()


class TestBearerEnvCandidates:
    def test_per_peer_then_shared(self):
        assert _bearer_env_candidates("billing-agent") == [
            "ZIL_A2A_TOKEN_BILLING_AGENT",
            "ZIL_A2A_TOKEN",
        ]


class TestGcpIdTokenAuthenticator:
    def test_mints_and_caches(self, monkeypatch):
        pytest.importorskip("google.oauth2")
        import google.oauth2.id_token as idt

        calls: list[str] = []

        def fake_fetch(request, audience):
            calls.append(audience)
            return "tok-123"

        monkeypatch.setattr(idt, "fetch_id_token", fake_fetch)

        auth = GcpIdTokenAuthenticator("https://billing.run.app")
        assert auth.headers() == {"Authorization": "Bearer tok-123"}
        # Second call is served from cache — token minted only once.
        assert auth.headers() == {"Authorization": "Bearer tok-123"}
        assert calls == ["https://billing.run.app"]


class TestBuildAuthenticator:
    def test_none(self):
        peer = PeerRef(name="p", url="u", auth="none")
        assert isinstance(build_authenticator(peer, "u"), NoneAuthenticator)

    def test_bearer(self):
        peer = PeerRef(name="billing-agent", url="u", auth="bearer")
        auth = build_authenticator(
            peer, "u", env={"ZIL_A2A_TOKEN_BILLING_AGENT": "t"}
        )
        assert isinstance(auth, BearerAuthenticator)
        assert auth.headers()["Authorization"] == "Bearer t"

    def test_gcp_is_default(self):
        # PeerRef.auth defaults to gcp-id-token.
        peer = PeerRef(name="p", url="u")
        auth = build_authenticator(peer, "https://p.run.app")
        assert isinstance(auth, GcpIdTokenAuthenticator)
        assert auth._audience == "https://p.run.app"

    def test_unknown_mode_raises(self):
        peer = PeerRef(name="p", url="u", auth="quantum")
        with pytest.raises(ValueError, match="unknown auth mode"):
            build_authenticator(peer, "u")
