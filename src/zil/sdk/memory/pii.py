"""Heuristic PII detection for packable memory (RFC-003 follow-up).

Best-effort, regex-based detection used to keep personal data out of packed
memory seeds. It is intentionally conservative for the *packing* path: when PII
is detected the default action is to **drop** the entry (and warn), since
AGENT-scope knowledge shipped with an agent should describe behavior, not
people.

This is not a compliance-grade scrubber; it catches common, high-signal
patterns (email, phone, SSN, credit card, IP address).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

FilterMode = Literal["drop", "redact", "warn"]

_REDACTION = "[REDACTED]"

# High-signal PII patterns. Keys are category labels surfaced in warnings.
_PATTERNS: dict[str, re.Pattern[str]] = {
    "email": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    "phone": re.compile(
        r"(?<!\d)(?:\+?\d{1,3}[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)"
    ),
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "credit_card": re.compile(r"\b(?:\d[ -]?){13,16}\b"),
    "ip_address": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
}


def scan(text: str) -> list[str]:
    """Return the sorted list of PII categories detected in ``text``."""
    if not text:
        return []
    found = {label for label, pattern in _PATTERNS.items() if pattern.search(text)}
    return sorted(found)


def redact(text: str) -> str:
    """Replace every PII match in ``text`` with a redaction marker."""
    out = text
    for pattern in _PATTERNS.values():
        out = pattern.sub(_REDACTION, out)
    return out


@dataclass
class FilterResult:
    """Outcome of filtering a batch of seed entries."""

    kept: list[dict[str, Any]] = field(default_factory=list)
    dropped: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def pii_detected(self) -> bool:
        return bool(self.dropped) or any("PII" in w for w in self.warnings)


def filter_entries(
    entries: Iterable[Mapping[str, Any]],
    *,
    mode: FilterMode = "drop",
) -> FilterResult:
    """Apply PII policy to seed ``entries`` (each a dict with ``content``).

    - ``drop``   — exclude entries containing PII (default for packing).
    - ``redact`` — keep entries but replace PII spans with a marker.
    - ``warn``   — keep entries unchanged, only collect warnings.
    """
    result = FilterResult()
    for raw in entries:
        entry = dict(raw)
        content = str(entry.get("content", ""))
        categories = scan(content)
        if not categories:
            result.kept.append(entry)
            continue

        cats = ", ".join(categories)
        if mode == "drop":
            result.dropped.append(entry)
            result.warnings.append(
                f"Dropped seed entry containing PII ({cats}): "
                f"{content[:60]!r}"
            )
        elif mode == "redact":
            entry["content"] = redact(content)
            result.kept.append(entry)
            result.warnings.append(
                f"Redacted PII ({cats}) in seed entry: {content[:60]!r}"
            )
        else:  # warn
            result.kept.append(entry)
            result.warnings.append(
                f"Seed entry contains PII ({cats}): {content[:60]!r}"
            )
    return result
