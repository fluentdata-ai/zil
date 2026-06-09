"""Peer discovery / resolution for A2A collaboration (ZIL-RFC-005 §9).

``StaticResolver`` resolves a ``PeerRef.url`` (with ``${ENV}`` interpolation) to
a live ``AgentCard``. Card fetching uses ``httpx`` when available but is
injectable, so resolution is fully unit-testable offline. Registry-backed
discovery (``ref:``) is a later phase (RFC-007) and intentionally absent here.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping

from zil.collaboration.contract import AgentCard, PeerRef

_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

# A fetcher maps an absolute base URL to a raw Agent Card dict.
CardFetcher = Callable[[str], dict]


def interpolate_env(value: str, env: Mapping[str, str]) -> str:
    """Replace ``${VAR}`` in *value*; raise ``KeyError`` if a var is unset."""

    def _sub(match: re.Match[str]) -> str:
        var = match.group(1)
        if var not in env:
            raise KeyError(var)
        return env[var]

    return _ENV_RE.sub(_sub, value)


def _default_fetcher(base_url: str) -> dict:
    """Fetch the Agent Card from the current well-known path over HTTP."""
    import httpx  # lazy: only needed when actually fetching over the network

    well_known = base_url.rstrip("/") + "/.well-known/agent-card.json"
    resp = httpx.get(well_known, timeout=10.0)
    resp.raise_for_status()
    return resp.json()


class StaticResolver:
    """Resolve peers from explicit URLs declared in the manifest."""

    def __init__(
        self,
        env: Mapping[str, str] | None = None,
        fetcher: CardFetcher | None = None,
    ) -> None:
        self._env = env if env is not None else os.environ
        self._fetcher = fetcher or _default_fetcher

    def resolve_url(self, ref: PeerRef) -> str:
        """Return the peer's absolute base URL with ``${ENV}`` interpolated."""
        if ref.ref and not ref.url:
            raise ValueError(
                f"collaborator '{ref.name}' uses 'ref' (registry discovery) "
                "which StaticResolver does not support"
            )
        if not ref.url:
            raise ValueError(
                f"collaborator '{ref.name}' has no 'url' (StaticResolver requires url)"
            )
        try:
            return interpolate_env(ref.url, self._env)
        except KeyError as exc:
            raise ValueError(
                f"collaborator '{ref.name}' url references unset env var "
                f"${{{exc.args[0]}}}"
            ) from exc

    def resolve(self, ref: PeerRef) -> AgentCard:
        """Resolve the URL and fetch the peer's Agent Card."""
        url = self.resolve_url(ref)
        card = AgentCard.from_dict(self._fetcher(url))
        if not card.url:
            card.url = url
        return card
