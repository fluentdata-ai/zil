"""Framework-neutral A2A collaboration contract (ZIL-RFC-005 §5).

Platform-agnostic types describing a declared peer agent (``PeerRef``), the
Agent Card a caller relies on (``AgentCard``/``AgentSkill``), what context may
cross the boundary (``ContextTransferPolicy``), and the resolver / authenticator
/ remote-agent interfaces. This module imports no framework SDK and no HTTP
client, so the neutral core is testable in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class AgentSkill:
    """A capability advertised on a peer's Agent Card (subset Zil relies on)."""

    id: str
    name: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    input_modes: list[str] = field(default_factory=lambda: ["text/plain"])
    output_modes: list[str] = field(default_factory=lambda: ["text/plain"])


@dataclass
class AgentCard:
    """The ``/.well-known/agent-card.json`` shape a Zil caller consumes."""

    name: str
    description: str
    url: str
    version: str
    capabilities: dict = field(default_factory=dict)
    skills: list[AgentSkill] = field(default_factory=list)
    protocol_version: str = "0.3.0"
    preferred_transport: str = "JSONRPC"

    @classmethod
    def from_dict(cls, data: dict) -> AgentCard:
        """Parse a raw Agent Card dict (camelCase or snake_case keys)."""
        skills = [
            AgentSkill(
                id=s.get("id", ""),
                name=s.get("name", s.get("id", "")),
                description=s.get("description", ""),
                tags=list(s.get("tags", []) or []),
                input_modes=list(
                    s.get("inputModes", s.get("input_modes", [])) or ["text/plain"]
                ),
                output_modes=list(
                    s.get("outputModes", s.get("output_modes", [])) or ["text/plain"]
                ),
            )
            for s in (data.get("skills") or [])
        ]
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            url=data.get("url", ""),
            version=data.get("version", ""),
            capabilities=dict(data.get("capabilities") or {}),
            skills=skills,
            protocol_version=data.get(
                "protocolVersion", data.get("protocol_version", "0.3.0")
            ),
            preferred_transport=data.get(
                "preferredTransport", data.get("preferred_transport", "JSONRPC")
            ),
        )

    def skill_ids(self) -> list[str]:
        return [s.id for s in self.skills]


@dataclass
class ContextTransferPolicy:
    """What may cross the boundary on a peer call (enforcement is RFC-005 P3)."""

    send: str = "message_only"  # "message_only" | "session_summary" | "none"
    receive: str = "artifacts"  # "artifacts" | "artifacts_and_state"
    redact: list[str] = field(default_factory=list)


@dataclass
class PeerRef:
    """A declared collaborator. Resolves to an AgentCard via a PeerResolver."""

    name: str
    url: str | None = None
    ref: str | None = None
    skills: list[str] | None = None  # allowlist of peer skill ids (None = all)
    auth: str = "gcp-id-token"
    context_transfer: ContextTransferPolicy = field(
        default_factory=ContextTransferPolicy
    )


@runtime_checkable
class PeerResolver(Protocol):
    """Maps a PeerRef to a live AgentCard (the only 'where peers live' knower)."""

    def resolve(self, ref: PeerRef) -> AgentCard: ...


@runtime_checkable
class Authenticator(Protocol):
    """Produces auth headers for an outbound peer call (one impl per auth mode)."""

    mode: str

    def headers(self, target: AgentCard) -> dict[str, str]: ...


@runtime_checkable
class RemoteAgent(Protocol):
    """Neutral interface a framework adapter exposes to its LLM as a tool."""

    name: str
    card: AgentCard

    def list_skills(self) -> list[AgentSkill]: ...

    async def send(
        self, skill_id: str, message: str, *, stream: bool = False
    ) -> Any: ...
