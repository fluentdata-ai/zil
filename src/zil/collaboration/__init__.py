"""A2A multi-agent collaboration (ZIL-RFC-005).

Framework-neutral contract + discovery for calling peer agents over A2A.
"""

from zil.collaboration.contract import (
    AgentCard,
    AgentSkill,
    Authenticator,
    ContextTransferPolicy,
    PeerRef,
    PeerResolver,
    RemoteAgent,
)
from zil.collaboration.discovery import StaticResolver, interpolate_env

__all__ = [
    "AgentCard",
    "AgentSkill",
    "Authenticator",
    "ContextTransferPolicy",
    "PeerRef",
    "PeerResolver",
    "RemoteAgent",
    "StaticResolver",
    "interpolate_env",
]
