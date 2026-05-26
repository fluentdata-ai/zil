"""Stub framework backend — test-only, no external dependencies.

The StubBackend proves that the FrameworkBackend abstraction works without
any real agent framework installed. It is always registered in the global
registry and can be selected with ``runtime.framework: stub``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from zil.sdk.frameworks.base import AgentSpec

logger = logging.getLogger(__name__)


@dataclass
class StubWiredAgent:
    """A trivial WiredAgent that stores the AgentSpec."""

    _spec: AgentSpec

    @property
    def framework(self) -> str:
        return "stub"

    @property
    def inner(self) -> Any:
        return self._spec


class StubBackend:
    """Test-only framework backend with no external dependencies."""

    @property
    def name(self) -> str:
        return "stub"

    def wire(self, spec: AgentSpec) -> StubWiredAgent:
        """Return a StubWiredAgent wrapping the spec."""
        logger.info("StubBackend.wire() called for agent %r", spec.name)
        return StubWiredAgent(_spec=spec)

    def run_local(self, agent: StubWiredAgent, **kwargs: Any) -> None:
        """No-op local run — logs the call."""
        mode = kwargs.get("mode", "interactive")
        logger.info(
            "StubBackend.run_local() called (mode=%s, agent=%r)",
            mode,
            agent._spec.name,
        )

    def deploy_descriptor(
        self, agent: StubWiredAgent, spec: AgentSpec
    ) -> dict[str, Any]:
        """Return a minimal deployment descriptor."""
        return {
            "framework": "stub",
            "image": "none",
            "entrypoint": "none",
        }

    def validate(
        self, project_dir: Path, manifest: dict[str, Any]
    ) -> list[Any]:
        """No framework-specific validation for the stub."""
        return []

    def scaffold_config(self) -> dict[str, Any] | None:
        """Stub does not provide scaffold templates."""
        return None
