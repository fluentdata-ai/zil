"""Registry mapping provider names to factory callables.

Mirrors ``zil.sdk.frameworks.BackendRegistry``: a module-level singleton
``registry`` always has the test-only ``stub`` provider; real providers
(mem0, ...) are lazy-registered only when their SDK is importable.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from zil.sdk.memory.config import MemoryConfig
from zil.sdk.memory.types import MemoryProvider

logger = logging.getLogger(__name__)

# A factory takes the parsed config and returns a ready provider instance.
ProviderFactory = Callable[[MemoryConfig], MemoryProvider]


class UnknownProviderError(ValueError):
    """Raised when a memory provider name is not registered."""

    def __init__(self, name: str, registered: list[str]) -> None:
        self.name = name
        self.registered = registered
        super().__init__(
            f"Unknown memory provider {name!r}. "
            f"Registered providers: {registered or ['(none)']}"
        )


class MemoryProviderRegistry:
    """Maps provider names to factory callables."""

    def __init__(self) -> None:
        self._factories: dict[str, ProviderFactory] = {}

    def register(self, name: str, factory: ProviderFactory) -> None:
        """Register a provider factory. Last-write-wins on duplicate names."""
        if name in self._factories:
            logger.info("MemoryProviderRegistry: overwriting provider %r", name)
        self._factories[name] = factory
        logger.debug("MemoryProviderRegistry: registered %r", name)

    def create(self, config: MemoryConfig) -> MemoryProvider:
        """Instantiate the provider named in ``config``."""
        if config.provider not in self._factories:
            raise UnknownProviderError(config.provider, self.list_names())
        return self._factories[config.provider](config)

    def list_names(self) -> list[str]:
        return sorted(self._factories.keys())

    def __contains__(self, name: str) -> bool:
        return name in self._factories

    def __len__(self) -> int:
        return len(self._factories)


# Module-level singleton
registry = MemoryProviderRegistry()


def _register_builtins() -> None:
    """Register the always-available stub and lazy-register real providers."""
    from zil.sdk.memory.providers.stub import StubMemoryProvider

    registry.register("stub", lambda cfg: StubMemoryProvider(cfg))

    # Mem0 is registered unconditionally but its SDK import is deferred to
    # provider construction, so the registry stays usable without mem0ai.
    try:
        from zil.sdk.memory.providers.mem0 import Mem0Provider

        registry.register("mem0", lambda cfg: Mem0Provider(cfg))
    except ImportError:  # pragma: no cover - defensive; module has no hard import
        logger.debug("mem0 provider module not importable; skipping registration")


_register_builtins()
