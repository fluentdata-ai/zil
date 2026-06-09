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


# Logical-name reference scheme for registry discovery: ``zil://fleet/<name>``.
_REF_SCHEME = "zil://fleet/"


class RegistryResolver:
    """Resolve peers declared with ``ref: zil://fleet/<name>`` (ZIL-RFC-005 §9).

    The registry maps a logical peer name to a base URL — the RFC-007 *registry
    of record*. Until that registry service exists, the mapping is supplied
    explicitly (``registry={...}``) or via the ``ZIL_FLEET_REGISTRY`` env var as
    comma-separated ``name=url`` pairs. Plain ``url:`` peers are delegated to the
    same logic as ``StaticResolver`` (with ``${ENV}`` interpolation), so one
    resolver handles a mixed fleet.
    """

    def __init__(
        self,
        registry: Mapping[str, str] | None = None,
        *,
        env: Mapping[str, str] | None = None,
        fetcher: CardFetcher | None = None,
    ) -> None:
        self._env = env if env is not None else os.environ
        self._fetcher = fetcher or _default_fetcher
        if registry is not None:
            self._registry = dict(registry)
        else:
            self._registry = _parse_registry_env(self._env.get("ZIL_FLEET_REGISTRY"))

    def resolve_url(self, ref: PeerRef) -> str:
        """Return the peer's absolute base URL (registry lookup or plain url)."""
        if ref.url and not ref.ref:
            try:
                return interpolate_env(ref.url, self._env)
            except KeyError as exc:
                raise ValueError(
                    f"collaborator '{ref.name}' url references unset env var "
                    f"${{{exc.args[0]}}}"
                ) from exc
        if not ref.ref:
            raise ValueError(
                f"collaborator '{ref.name}' has neither 'url' nor 'ref'"
            )
        if not ref.ref.startswith(_REF_SCHEME):
            raise ValueError(
                f"collaborator '{ref.name}' ref '{ref.ref}' must use the "
                f"'{_REF_SCHEME}<name>' scheme"
            )
        key = ref.ref[len(_REF_SCHEME):].strip("/")
        if not self._registry:
            raise ValueError(
                f"collaborator '{ref.name}' uses registry discovery but no "
                "registry is configured (set ZIL_FLEET_REGISTRY or inject one)"
            )
        if key not in self._registry:
            raise ValueError(
                f"collaborator '{ref.name}' ref '{ref.ref}' not found in the "
                f"registry (known: {sorted(self._registry)})"
            )
        return self._registry[key]

    def resolve(self, ref: PeerRef) -> AgentCard:
        """Resolve via the registry and fetch the peer's Agent Card."""
        url = self.resolve_url(ref)
        card = AgentCard.from_dict(self._fetcher(url))
        if not card.url:
            card.url = url
        return card


def _parse_registry_env(value: str | None) -> dict[str, str]:
    """Parse ``name=url,name2=url2`` into a mapping (empty when unset)."""
    registry: dict[str, str] = {}
    if not value:
        return registry
    for pair in value.split(","):
        pair = pair.strip()
        if not pair:
            continue
        name, sep, url = pair.partition("=")
        if sep and name.strip() and url.strip():
            registry[name.strip()] = url.strip()
    return registry
