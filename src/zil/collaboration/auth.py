"""Inter-agent authentication for A2A collaboration (ZIL-RFC-005 §10.2).

One ``Authenticator`` per ``auth`` mode attaches credentials to outbound peer
calls. The audience (resolved peer URL) is bound at construction, so
``headers()`` takes no argument and can be called per-request by the framework
adapter's HTTP layer.

Shipped modes:
  - ``gcp-id-token`` (default): mint a Google-signed ID token for the target
    Cloud Run URL (service-to-service identity). Aligns with private-by-default
    deploys.
  - ``bearer``: static token from an env var (cross-cloud / non-GCP peers).
  - ``none``: explicit opt-out (dev only; ``zil validate`` warns).

Follow-on modes (mTLS, OIDC client-credentials) implement the same shape.
"""

from __future__ import annotations

import os
import time
from collections.abc import Mapping

from zil.collaboration.contract import PeerRef

# Bearer token lookup convention (most specific first).
#   ZIL_A2A_TOKEN_<PEER_NAME>  (e.g. billing-agent -> ZIL_A2A_TOKEN_BILLING_AGENT)
#   ZIL_A2A_TOKEN              (shared fallback for all bearer peers)
_BEARER_ENV_PREFIX = "ZIL_A2A_TOKEN"

# Refresh GCP ID tokens slightly before their ~1h expiry to avoid races.
_GCP_TOKEN_TTL_SECONDS = 50 * 60


def _bearer_env_candidates(peer_name: str) -> list[str]:
    suffix = peer_name.upper().replace("-", "_")
    return [f"{_BEARER_ENV_PREFIX}_{suffix}", _BEARER_ENV_PREFIX]


class NoneAuthenticator:
    """No authentication — explicit dev-only opt-out."""

    mode = "none"

    def headers(self) -> dict[str, str]:
        return {}


class BearerAuthenticator:
    """Static bearer token read from the first set env var in *candidates*."""

    mode = "bearer"

    def __init__(
        self,
        candidates: list[str],
        *,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._candidates = candidates
        self._env = env if env is not None else os.environ

    def headers(self) -> dict[str, str]:
        for name in self._candidates:
            token = self._env.get(name)
            if token:
                return {"Authorization": f"Bearer {token}"}
        raise RuntimeError(
            "bearer auth: no token found in env var(s) "
            f"{', '.join(self._candidates)}"
        )


class GcpIdTokenAuthenticator:
    """Mint a Google-signed ID token scoped to the target URL (audience).

    Tokens are cached and refreshed shortly before expiry. Requires Google
    credentials in the environment (Cloud Run metadata server or
    ``GOOGLE_APPLICATION_CREDENTIALS``).
    """

    mode = "gcp-id-token"

    def __init__(self, audience: str) -> None:
        self._audience = audience
        self._token: str | None = None
        self._fetched_at: float = 0.0

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._get_token()}"}

    def _get_token(self) -> str:
        now = time.monotonic()
        if self._token and (now - self._fetched_at) < _GCP_TOKEN_TTL_SECONDS:
            return self._token
        self._token = self._mint_token()
        self._fetched_at = now
        return self._token

    def _mint_token(self) -> str:
        try:
            import google.auth.transport.requests
            from google.oauth2 import id_token
        except ImportError as exc:  # pragma: no cover - env-dependent
            raise RuntimeError(
                "gcp-id-token auth requires google-auth. Install it with: "
                "pip install 'zil-ai[adk]'"
            ) from exc

        request = google.auth.transport.requests.Request()
        return id_token.fetch_id_token(request, self._audience)


def build_authenticator(
    peer: PeerRef,
    target_url: str,
    *,
    env: Mapping[str, str] | None = None,
) -> object:
    """Construct the Authenticator for *peer*, bound to *target_url* audience."""
    mode = peer.auth or "gcp-id-token"
    if mode == "none":
        return NoneAuthenticator()
    if mode == "bearer":
        return BearerAuthenticator(_bearer_env_candidates(peer.name), env=env)
    if mode == "gcp-id-token":
        return GcpIdTokenAuthenticator(target_url)
    raise ValueError(f"unknown auth mode {mode!r} for collaborator {peer.name!r}")
