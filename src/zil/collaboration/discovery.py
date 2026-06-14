"""Peer discovery / resolution for A2A collaboration (ZIL-RFC-005 §9).

``StaticResolver`` resolves a ``PeerRef.url`` (with ``${ENV}`` interpolation) to
a live ``AgentCard``. Card fetching uses ``httpx`` when available but is
injectable, so resolution is fully unit-testable offline.

Registry-backed discovery (``ref: zil://fleet/<name>``) has two flavours:

- ``RegistryResolver`` — an explicit/in-process ``name → url`` mapping (injected
  or via ``ZIL_FLEET_REGISTRY``). Useful for tests and small static fleets.
- ``HttpRegistryResolver`` — resolves against a remote *registry of record*
  (RFC-007) over HTTP: ``GET {registry}/agents/{name}`` returns the peer's URL
  and, optionally, its Agent Card. This is the production seam — point an agent
  at ``ZIL_FLEET_REGISTRY_URL`` and ``ref:`` peers resolve with no code changes.

``build_resolver`` selects the right implementation from the environment.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping

from zil.collaboration.contract import AgentCard, PeerRef

_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

# A fetcher maps an absolute base URL to a raw Agent Card dict.
CardFetcher = Callable[[str], dict]

# A registry fetcher maps a registry resolve URL to a raw registry entry dict
# (``{"name": ..., "url": ..., "card": {...}?}``).
RegistryFetcher = Callable[[str], dict]


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


def _fleet_ref_name(ref: PeerRef) -> str:
    """Validate a ``zil://fleet/<name>`` ref and return ``<name>``."""
    if not ref.ref:
        raise ValueError(f"collaborator '{ref.name}' has neither 'url' nor 'ref'")
    if not ref.ref.startswith(_REF_SCHEME):
        raise ValueError(
            f"collaborator '{ref.name}' ref '{ref.ref}' must use the "
            f"'{_REF_SCHEME}<name>' scheme"
        )
    return ref.ref[len(_REF_SCHEME):].strip("/")


def _default_registry_fetcher(
    resolve_url: str, headers: Mapping[str, str] | None = None
) -> dict:
    """GET a registry resolve URL and return the raw entry dict."""
    import httpx  # lazy: only needed when actually resolving over the network

    resp = httpx.get(resolve_url, headers=dict(headers or {}), timeout=10.0)
    resp.raise_for_status()
    return resp.json()


class HttpRegistryResolver:
    """Resolve ``ref: zil://fleet/<name>`` against a remote registry (RFC-007).

    The registry is a small HTTP service (the *registry of record*) exposing
    ``GET {registry}/agents/{name}`` → ``{"name", "url", "card"?}``. This is the
    production discovery seam: deployed agents are pointed at the platform
    registry via ``ZIL_FLEET_REGISTRY_URL`` and resolve peers with no code
    changes. Plain ``url:`` peers are delegated to static logic (with ``${ENV}``
    interpolation), so one resolver handles a mixed fleet.

    Both the registry fetch and the per-peer Agent Card fetch are injectable, so
    resolution is fully unit-testable offline. When ``ZIL_FLEET_REGISTRY_TOKEN``
    is set, the default fetcher attaches it as a bearer token so a protected
    registry of record can authenticate the caller.
    """

    def __init__(
        self,
        registry_url: str | None = None,
        *,
        env: Mapping[str, str] | None = None,
        registry_fetcher: RegistryFetcher | None = None,
        card_fetcher: CardFetcher | None = None,
    ) -> None:
        self._env = env if env is not None else os.environ
        raw = registry_url or self._env.get("ZIL_FLEET_REGISTRY_URL")
        self._registry_url = (
            interpolate_env(raw, self._env).rstrip("/") if raw else None
        )
        if registry_fetcher is not None:
            self._registry_fetcher = registry_fetcher
        else:
            token = self._env.get("ZIL_FLEET_REGISTRY_TOKEN")
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            self._registry_fetcher = lambda url: _default_registry_fetcher(url, headers)
        self._card_fetcher = card_fetcher or _default_fetcher

    def _lookup(self, ref: PeerRef) -> dict:
        """Resolve a ``ref:`` peer to its raw registry entry dict."""
        name = _fleet_ref_name(ref)
        if not self._registry_url:
            raise ValueError(
                f"collaborator '{ref.name}' uses registry discovery but no "
                "registry is configured (set ZIL_FLEET_REGISTRY_URL or inject one)"
            )
        resolve_url = f"{self._registry_url}/agents/{name}"
        entry = self._registry_fetcher(resolve_url)
        if not entry or not entry.get("url"):
            raise ValueError(
                f"collaborator '{ref.name}' ref '{ref.ref}' not found in the "
                f"registry at {self._registry_url}"
            )
        return entry

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
        return self._lookup(ref)["url"]

    def resolve(self, ref: PeerRef) -> AgentCard:
        """Resolve via the registry and return the peer's Agent Card.

        Prefers a card embedded in the registry entry (one round-trip); falls
        back to fetching the peer's well-known card when absent.
        """
        if ref.url and not ref.ref:
            url = self.resolve_url(ref)
            card = AgentCard.from_dict(self._card_fetcher(url))
            if not card.url:
                card.url = url
            return card
        entry = self._lookup(ref)
        url = entry["url"]
        raw_card = entry.get("card")
        card = AgentCard.from_dict(raw_card) if raw_card else AgentCard.from_dict(
            self._card_fetcher(url)
        )
        if not card.url:
            card.url = url
        return card


def build_resolver(env: Mapping[str, str] | None = None):
    """Select a resolver from the environment (RFC-005 §9 single seam).

    Returns :class:`HttpRegistryResolver` when ``ZIL_FLEET_REGISTRY_URL`` is set
    (production registry of record), otherwise :class:`RegistryResolver` (which
    handles plain ``url:`` peers and the ``ZIL_FLEET_REGISTRY`` in-process
    mapping). Either way ``ref: zil://fleet/<name>`` resolves identically.
    """
    resolved_env = env if env is not None else os.environ
    if resolved_env.get("ZIL_FLEET_REGISTRY_URL"):
        return HttpRegistryResolver(env=resolved_env)
    return RegistryResolver(env=resolved_env)
