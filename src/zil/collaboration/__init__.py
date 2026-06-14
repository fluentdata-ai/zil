"""A2A multi-agent collaboration (ZIL-RFC-005).

Framework-neutral contract + discovery for calling peer agents over A2A.
"""

from zil.collaboration.auth import (
    BearerAuthenticator,
    GcpIdTokenAuthenticator,
    NoneAuthenticator,
    build_authenticator,
)
from zil.collaboration.client import (
    A2APeerClient,
    PeerArtifact,
    PeerCallResult,
    PeerStreamEvent,
    SkillNotAllowedError,
)
from zil.collaboration.contract import (
    AgentCard,
    AgentSkill,
    Authenticator,
    ContextTransferPolicy,
    PeerRef,
    PeerResolver,
    RemoteAgent,
)
from zil.collaboration.discovery import (
    HttpRegistryResolver,
    RegistryResolver,
    StaticResolver,
    build_resolver,
    interpolate_env,
)
from zil.collaboration.topology import (
    TopologyGraph,
    build_topology_graph,
    find_cycles,
    manifest_agent_name,
)

__all__ = [
    "AgentCard",
    "AgentSkill",
    "Authenticator",
    "ContextTransferPolicy",
    "PeerRef",
    "PeerResolver",
    "RemoteAgent",
    "StaticResolver",
    "RegistryResolver",
    "HttpRegistryResolver",
    "build_resolver",
    "interpolate_env",
    "build_authenticator",
    "NoneAuthenticator",
    "BearerAuthenticator",
    "GcpIdTokenAuthenticator",
    "TopologyGraph",
    "build_topology_graph",
    "find_cycles",
    "manifest_agent_name",
    "A2APeerClient",
    "PeerCallResult",
    "PeerArtifact",
    "PeerStreamEvent",
    "SkillNotAllowedError",
]
