"""httpx integration for outbound peer calls (ZIL-RFC-005 §10.2/§10.3).

Kept separate from the neutral ``contract`` module because it imports ``httpx``;
the collaboration package ``__init__`` does not import this, so the neutral core
stays importable without an HTTP client. Framework adapters lazily import this
to build a client that asserts caller identity and attaches per-mode auth.
"""

from __future__ import annotations

from typing import Any

import httpx

# Caller-identity assertion seam (RFC-005 §10.3). Callers attach a verifiable
# identity header derived from the agent's identity; callee-side verification /
# per-caller authorization is specified with RFC-001 and enforced there. We set
# the seam (the header) now so the wire carries caller identity from day one.
CALLER_IDENTITY_HEADER = "X-Zil-Caller-Agent"


class PeerRequestAuth(httpx.Auth):
    """httpx auth flow attaching caller identity + per-mode auth to every call.

    The caller-identity header is always attached (when *caller* is set). Auth
    headers are pulled from *authenticator* when one is supplied; the ``none``
    auth mode passes ``authenticator=None`` (identity only, no credentials).
    """

    def __init__(self, *, caller: str = "", authenticator: Any = None) -> None:
        self._caller = caller
        self._authenticator = authenticator

    def auth_flow(self, request):  # type: ignore[override]
        if self._caller:
            request.headers[CALLER_IDENTITY_HEADER] = self._caller
        if self._authenticator is not None:
            for key, value in self._authenticator.headers().items():
                request.headers[key] = value
        yield request


def build_peer_http_client(
    *,
    caller: str = "",
    authenticator: Any = None,
) -> httpx.AsyncClient:
    """Build an httpx client that asserts caller identity and attaches auth."""
    return httpx.AsyncClient(
        auth=PeerRequestAuth(caller=caller, authenticator=authenticator)
    )
