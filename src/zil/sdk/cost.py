"""Zil cost tracking — token usage metering and budget enforcement."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class CostStatus(StrEnum):
    """Result of a usage recording against budget limits."""

    ALLOWED = "allowed"
    WARNED = "warned"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class UsageRecord:
    """A single LLM call's token usage."""

    input_tokens: int
    output_tokens: int
    total_tokens: int
    model: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class TokenCounts:
    """Accumulated token counts for a model or session."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    request_count: int = 0

    def add(self, record: UsageRecord) -> None:
        self.input_tokens += record.input_tokens
        self.output_tokens += record.output_tokens
        self.total_tokens += record.total_tokens
        self.request_count += 1


@dataclass
class CostResult:
    """Result of recording a usage event."""

    status: CostStatus
    total_tokens: int
    budget_remaining: int | None = None
    message: str = ""


class CostTracker:
    """Thread-safe token usage tracker with budget enforcement.

    Tracks per-request and per-session token usage. Enforces
    ``max_tokens_per_request`` and ``max_tokens_per_session`` limits
    from ``spec.cost`` in the manifest. Emits warnings when usage
    reaches ``alert_threshold_pct`` of the session budget.

    Usage::

        import zil

        root_agent = zil.create_agent(...)
        print(zil.cost.total_tokens)
        print(zil.cost.by_model)
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._lock = threading.Lock()
        self._config = config or {}
        self._initialized = False

        # Limits from spec.cost
        self._max_per_request: int | None = None
        self._max_per_session: int | None = None
        self._alert_threshold_pct: int = 80
        self._track_by_model: bool = True

        # Accumulators
        self._session = TokenCounts()
        self._by_model: dict[str, TokenCounts] = {}
        self._requests: list[UsageRecord] = []
        self._alert_fired = False

    def _initialize(self, config: dict[str, Any] | None = None) -> None:
        """Initialize the tracker with spec.cost configuration."""
        with self._lock:
            self._config = config or {}
            self._max_per_request = self._config.get("max_tokens_per_request")
            self._max_per_session = self._config.get("max_tokens_per_session")
            self._alert_threshold_pct = self._config.get("alert_threshold_pct", 80)
            self._track_by_model = self._config.get("track_by_model", True)

            # Reset accumulators
            self._session = TokenCounts()
            self._by_model = {}
            self._requests = []
            self._alert_fired = False
            self._initialized = True

    def record_usage(
        self,
        input_tokens: int,
        output_tokens: int,
        model: str = "",
    ) -> CostResult:
        """Record token usage from an LLM call.

        Returns a CostResult indicating whether the usage was allowed,
        warned (approaching budget), or blocked (exceeds budget).
        """
        total = input_tokens + output_tokens
        record = UsageRecord(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total,
            model=model,
        )

        with self._lock:
            # Check per-request limit
            if self._max_per_request and total > self._max_per_request:
                logger.warning(
                    "Cost blocked: request used %d tokens (limit: %d)",
                    total,
                    self._max_per_request,
                )
                return CostResult(
                    status=CostStatus.BLOCKED,
                    total_tokens=self._session.total_tokens,
                    budget_remaining=self._budget_remaining,
                    message=(
                        f"Request blocked: {total} tokens exceeds "
                        f"max_tokens_per_request ({self._max_per_request})"
                    ),
                )

            # Check per-session limit (pre-check)
            if self._max_per_session:
                projected = self._session.total_tokens + total
                if projected > self._max_per_session:
                    logger.warning(
                        "Cost blocked: session would reach %d tokens (limit: %d)",
                        projected,
                        self._max_per_session,
                    )
                    return CostResult(
                        status=CostStatus.BLOCKED,
                        total_tokens=self._session.total_tokens,
                        budget_remaining=self._budget_remaining,
                        message=(
                            f"Session blocked: would reach {projected} tokens "
                            f"(max_tokens_per_session: {self._max_per_session})"
                        ),
                    )

            # Record the usage
            self._session.add(record)
            self._requests.append(record)

            if self._track_by_model and model:
                if model not in self._by_model:
                    self._by_model[model] = TokenCounts()
                self._by_model[model].add(record)

            # Check alert threshold
            status = CostStatus.ALLOWED
            message = ""
            if (
                self._max_per_session
                and not self._alert_fired
                and self._session.total_tokens
                >= (self._max_per_session * self._alert_threshold_pct / 100)
            ):
                self._alert_fired = True
                status = CostStatus.WARNED
                pct = (self._session.total_tokens / self._max_per_session) * 100
                message = (
                    f"Token budget alert: {self._session.total_tokens} tokens "
                    f"used ({pct:.0f}% of {self._max_per_session} session limit)"
                )
                logger.warning(message)

            return CostResult(
                status=status,
                total_tokens=self._session.total_tokens,
                budget_remaining=self._budget_remaining,
                message=message,
            )

    @property
    def _budget_remaining(self) -> int | None:
        """Remaining session budget (None if no limit set)."""
        if self._max_per_session is None:
            return None
        return max(0, self._max_per_session - self._session.total_tokens)

    # --- Public read-only properties ---

    @property
    def total_tokens(self) -> int:
        """Total tokens used this session."""
        return self._session.total_tokens

    @property
    def total_input_tokens(self) -> int:
        """Total input tokens used this session."""
        return self._session.input_tokens

    @property
    def total_output_tokens(self) -> int:
        """Total output tokens used this session."""
        return self._session.output_tokens

    @property
    def request_count(self) -> int:
        """Number of LLM requests recorded."""
        return self._session.request_count

    @property
    def requests(self) -> list[UsageRecord]:
        """List of all usage records this session."""
        with self._lock:
            return list(self._requests)

    @property
    def by_model(self) -> dict[str, TokenCounts]:
        """Token usage breakdown by model."""
        with self._lock:
            return dict(self._by_model)

    @property
    def budget_remaining(self) -> int | None:
        """Remaining tokens in session budget (None if no limit)."""
        with self._lock:
            return self._budget_remaining

    @property
    def config(self) -> dict[str, Any]:
        """The spec.cost configuration dict."""
        return self._config

    def reset(self) -> None:
        """Reset all accumulators (keeps config)."""
        with self._lock:
            self._session = TokenCounts()
            self._by_model = {}
            self._requests = []
            self._alert_fired = False

    def __repr__(self) -> str:
        if not self._initialized:
            return "CostTracker(<not initialized>)"
        parts = [f"tokens={self._session.total_tokens}"]
        if self._max_per_session:
            parts.append(f"budget={self._max_per_session}")
        parts.append(f"requests={self._session.request_count}")
        return f"CostTracker({', '.join(parts)})"
