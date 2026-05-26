"""Framework backend registry and exports.

This package provides the ``FrameworkBackend`` abstraction, the global
``registry``, and the built-in backends (ADK, OpenHands, Stub).
"""

from zil.sdk.frameworks.base import (
    AgentSpec,
    BackendRegistry,
    FrameworkBackend,
    UnknownFrameworkError,
    WiredAgent,
)
from zil.sdk.frameworks.stub.backend import StubBackend

# Module-level singleton registry
registry = BackendRegistry()

# Always register the stub backend (test-only, no external deps)
registry.register(StubBackend())

# Lazy-register AdkBackend only if google-adk is installed
try:
    from zil.sdk.frameworks.adk.backend import AdkBackend

    registry.register(AdkBackend())
except ImportError:
    pass

# Lazy-register OpenHandsBackend only if openhands-sdk is installed
try:
    from zil.sdk.frameworks.openhands.backend import OpenHandsBackend

    registry.register(OpenHandsBackend())
except ImportError:
    pass

__all__ = [
    "AgentSpec",
    "BackendRegistry",
    "FrameworkBackend",
    "UnknownFrameworkError",
    "WiredAgent",
    "registry",
]
