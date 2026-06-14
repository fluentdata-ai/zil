"""Native A2A peer client (ZIL-RFC-005 §7.1).

A framework-neutral client to call a declared peer over A2A: it enforces the
per-peer skill allowlist *before* any network call (least authority), resolves
the peer's Agent Card, sends a message (non-streaming or streaming), and returns
parsed artifacts. Unlike the ADK adapter (which delegates to a black-box
``RemoteA2aAgent``), this client gives *any* backend a collaboration path and is
the natural enforcement point for ``ContextTransferPolicy`` (RFC-005 §10.4).

It builds on the protocol SDK (``a2a-sdk``) rather than the agent framework, so
it stays framework-neutral. Auth + caller-identity ride on the httpx client from
``zil.collaboration.http``; the SDK is imported lazily so importing this module
does not require ``a2a`` to be installed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from zil.collaboration.contract import PeerRef

# Current A2A well-known Agent Card path (overridable for legacy peers).
AGENT_CARD_WELL_KNOWN_PATH = "/.well-known/agent-card.json"


class SkillNotAllowedError(Exception):
    """Raised when a call targets a skill outside the peer's allowlist.

    Raised *before* any network request so a least-authority violation never
    leaves the process (RFC-005 acceptance criterion 4).
    """


@dataclass
class PeerArtifact:
    """A parsed artifact returned by a peer call."""

    name: str | None
    text: str
    raw: Any = None


@dataclass
class PeerCallResult:
    """Aggregated outcome of a (possibly streaming) peer call."""

    task_id: str | None = None
    context_id: str | None = None
    status: str | None = None
    artifacts: list[PeerArtifact] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)

    def text(self) -> str:
        """Concatenate artifact + message text (the common 'just give me the answer')."""
        parts = [a.text for a in self.artifacts if a.text]
        parts += [m for m in self.messages if m]
        return "\n".join(parts)


@dataclass
class PeerStreamEvent:
    """An incremental event yielded by :meth:`A2APeerClient.stream`."""

    kind: str  # "artifact" | "status" | "message"
    text: str = ""
    status: str | None = None
    final: bool = False


def _parts_text(parts: Any) -> str:
    """Extract and concatenate text from a list of A2A Part union models."""
    out: list[str] = []
    for part in parts or []:
        root = getattr(part, "root", part)
        text = getattr(root, "text", None)
        if text:
            out.append(text)
    return "".join(out)


def _artifact(obj: Any) -> PeerArtifact:
    return PeerArtifact(
        name=getattr(obj, "name", None),
        text=_parts_text(getattr(obj, "parts", None)),
        raw=obj,
    )


def _task_state(task: Any) -> str | None:
    status = getattr(task, "status", None)
    state = getattr(status, "state", None)
    return getattr(state, "value", state) if state is not None else None


class A2APeerClient:
    """Call a declared peer over A2A, enforcing its skill allowlist.

    Parameters
    ----------
    peer:
        The declared collaborator (carries the ``skills`` allowlist + ``url``).
    caller:
        This agent's name, asserted to the peer via the identity header.
    authenticator:
        Optional credentials authenticator (``None`` => no auth headers).
    resolver:
        Resolves ``peer`` to a base URL. Defaults to a ``StaticResolver``.
    httpx_client:
        Inject a pre-built client (e.g. an ASGI-transport client for tests).
        When provided it is *not* closed by this client; otherwise an
        identity/auth-asserting client is built per call and closed after.
    agent_card_path:
        Well-known Agent Card path on the peer.
    """

    def __init__(
        self,
        peer: PeerRef,
        *,
        caller: str = "",
        authenticator: Any = None,
        resolver: Any = None,
        httpx_client: Any = None,
        agent_card_path: str = AGENT_CARD_WELL_KNOWN_PATH,
    ) -> None:
        self._peer = peer
        self._caller = caller
        self._authenticator = authenticator
        self._resolver = resolver
        self._injected_client = httpx_client
        self._agent_card_path = agent_card_path

    # -- allowlist (pre-network) -------------------------------------------

    def _check_skill_allowed(self, skill: str) -> None:
        allow = self._peer.skills
        if allow is not None and skill not in allow:
            raise SkillNotAllowedError(
                f"skill '{skill}' is not in the allowlist {allow} for peer "
                f"'{self._peer.name}'"
            )

    # -- client / message construction -------------------------------------

    def _http_client(self) -> tuple[Any, bool]:
        """Return (client, owned). Owned clients are closed by the caller."""
        if self._injected_client is not None:
            return self._injected_client, False
        from zil.collaboration.http import build_peer_http_client

        client = build_peer_http_client(
            caller=self._caller, authenticator=self._authenticator
        )
        return client, True

    def _base_url(self) -> str:
        resolver = self._resolver
        if resolver is None:
            from zil.collaboration.discovery import build_resolver

            resolver = build_resolver()
        return resolver.resolve_url(self._peer)

    async def _build_a2a_client(self, http: Any, *, streaming: bool) -> Any:
        from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
        from a2a.types import TransportProtocol

        base_url = self._base_url()
        card_resolver = A2ACardResolver(http, base_url, self._agent_card_path)
        card = await card_resolver.get_agent_card()
        config = ClientConfig(
            httpx_client=http,
            streaming=streaming,
            supported_transports=[TransportProtocol.jsonrpc],
        )
        return ClientFactory(config).create(card)

    def _message(self, message: str, context_id: str | None, skill: str) -> Any:
        from a2a.client import create_text_message_object

        msg = create_text_message_object(content=message)
        if context_id:
            msg.context_id = context_id
        # Surface the targeted skill for peer-side routing / observability.
        msg.metadata = {**(msg.metadata or {}), "zil.skill": skill}
        return msg

    # -- public API --------------------------------------------------------

    async def call(
        self, skill: str, message: str, *, context_id: str | None = None
    ) -> PeerCallResult:
        """Send *message* targeting *skill*; aggregate and return the result.

        Raises :class:`SkillNotAllowedError` before any network call when
        *skill* is outside the peer's allowlist.
        """
        self._check_skill_allowed(skill)
        http, owned = self._http_client()
        try:
            client = await self._build_a2a_client(http, streaming=False)
            msg = self._message(message, context_id, skill)
            result = PeerCallResult()
            async for event in client.send_message(msg):
                if isinstance(event, tuple):
                    task, _update = event
                    result.task_id = getattr(task, "id", None)
                    result.context_id = getattr(task, "context_id", None)
                    result.status = _task_state(task)
                    result.artifacts = [
                        _artifact(a) for a in (getattr(task, "artifacts", None) or [])
                    ]
                else:  # a2a Message
                    text = _parts_text(getattr(event, "parts", None))
                    if text:
                        result.messages.append(text)
            return result
        finally:
            if owned:
                await http.aclose()

    async def stream(
        self, skill: str, message: str, *, context_id: str | None = None
    ):
        """Yield incremental :class:`PeerStreamEvent`s for a streaming call.

        Raises :class:`SkillNotAllowedError` before any network call when
        *skill* is outside the peer's allowlist.
        """
        self._check_skill_allowed(skill)
        http, owned = self._http_client()
        try:
            client = await self._build_a2a_client(http, streaming=True)
            msg = self._message(message, context_id, skill)
            async for event in client.send_message(msg):
                if isinstance(event, tuple):
                    task, update = event
                    if update is not None:
                        text = _parts_text(
                            getattr(getattr(update, "artifact", None), "parts", None)
                        )
                        if text:
                            yield PeerStreamEvent(kind="artifact", text=text)
                        state = _task_state(update) or getattr(
                            getattr(update, "status", None), "state", None
                        )
                        state = getattr(state, "value", state)
                        if state:
                            yield PeerStreamEvent(
                                kind="status",
                                status=state,
                                final=bool(getattr(update, "final", False)),
                            )
                    else:
                        yield PeerStreamEvent(
                            kind="status", status=_task_state(task), final=True
                        )
                else:  # a2a Message
                    text = _parts_text(getattr(event, "parts", None))
                    if text:
                        yield PeerStreamEvent(kind="message", text=text)
        finally:
            if owned:
                await http.aclose()
