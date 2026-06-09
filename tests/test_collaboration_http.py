"""Tests for the outbound peer httpx integration (RFC-005 §10.2/§10.3)."""

import asyncio

import httpx

from zil.collaboration.auth import BearerAuthenticator, NoneAuthenticator
from zil.collaboration.http import (
    CALLER_IDENTITY_HEADER,
    PeerRequestAuth,
    build_peer_http_client,
)


def _aclose(client: httpx.AsyncClient) -> None:
    """Close an AsyncClient on a throwaway loop without touching global state.

    ``new_event_loop()`` does not install itself as the current loop, so this
    leaves ``asyncio.get_event_loop()`` for other tests undisturbed.
    """
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(client.aclose())
    finally:
        loop.close()


def _run_flow(auth: PeerRequestAuth) -> httpx.Request:
    request = httpx.Request("POST", "https://peer.run.app/a2a")
    list(auth.auth_flow(request))
    return request


class TestPeerRequestAuth:
    def test_injects_caller_identity_header(self):
        request = _run_flow(PeerRequestAuth(caller="orchestrator"))
        assert request.headers[CALLER_IDENTITY_HEADER] == "orchestrator"
        # No authenticator -> no credentials attached.
        assert "Authorization" not in request.headers

    def test_no_caller_means_no_identity_header(self):
        request = _run_flow(PeerRequestAuth(caller=""))
        assert CALLER_IDENTITY_HEADER not in request.headers

    def test_none_authenticator_adds_no_auth_header(self):
        request = _run_flow(
            PeerRequestAuth(caller="o", authenticator=NoneAuthenticator())
        )
        assert request.headers[CALLER_IDENTITY_HEADER] == "o"
        assert "Authorization" not in request.headers

    def test_attaches_auth_and_identity_together(self):
        auth = PeerRequestAuth(
            caller="orchestrator",
            authenticator=BearerAuthenticator(["TOK"], env={"TOK": "abc"}),
        )
        request = _run_flow(auth)
        assert request.headers[CALLER_IDENTITY_HEADER] == "orchestrator"
        assert request.headers["Authorization"] == "Bearer abc"


class TestBuildPeerHttpClient:
    def test_returns_async_client_with_auth_flow(self):
        client = build_peer_http_client(caller="o")
        try:
            assert isinstance(client, httpx.AsyncClient)
            assert isinstance(client.auth, PeerRequestAuth)
        finally:
            _aclose(client)
