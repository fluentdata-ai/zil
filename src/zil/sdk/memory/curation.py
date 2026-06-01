"""Curation of conversation turns before they are persisted to memory.

Framework backends hand the completed exchange to ``provider.add_session``.
Without curation, every raw turn is shipped to the provider, which then
LLM-extracts arbitrary "facts" — producing low-signal noise (e.g. "User asked
…") and letting PII through. This module applies the project's ``persist``
policy to the role-tagged message list before it reaches the provider:

- **strategy** (``MemoryConfig.persist_strategy``):
    - ``turn`` — keep the full user+assistant exchange (default);
    - ``assistant_only`` — keep only the agent's messages (its decisions /
      conclusions), dropping user chit-chat;
    - ``explicit`` — persist only lines the agent explicitly marks with
      ``persist.marker`` (default ``MEMORY:``); each marked fact is stored
      **verbatim** (``infer=False``) so the provider does not re-extract or
      explode it into noise. Nothing else is stored;
    - ``off`` — persist nothing.
- **PII** — when ``persist.exclude_pii`` is set, drop (or redact) any message
  whose content matches a PII pattern, as defense-in-depth on the write path
  (the same filter the packable seed uses).

Use ``persist_messages`` from framework wiring; it applies the policy and calls
the provider appropriately for each strategy.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from zil.sdk.memory import pii

logger = logging.getLogger(__name__)


def persist_enabled(config: Any) -> bool:
    """Whether conversation turns should be persisted at all."""
    return _strategy(config) != "off"


def _strategy(config: Any) -> str:
    return getattr(config, "persist_strategy", "turn") or "turn"


def curate_messages(
    config: Any, messages: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Apply the ``persist`` policy to a role-tagged message list.

    Returns a new list of message dicts to persist (possibly empty).
    """
    strategy = _strategy(config)
    if strategy == "off":
        return []

    out: list[dict[str, Any]] = [dict(m) for m in messages]

    if strategy == "assistant_only":
        out = [m for m in out if m.get("role") == "assistant"]

    out = _apply_pii(config, out)
    return out


def _apply_pii(
    config: Any, messages: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Drop/redact messages containing PII when ``exclude_pii`` is set."""
    if not getattr(config, "exclude_pii", False) or not messages:
        return messages
    mode = getattr(config, "persist_pii_mode", "drop")
    if mode not in ("drop", "redact"):
        mode = "drop"
    result = pii.filter_entries(messages, mode=mode)  # type: ignore[arg-type]
    if result.dropped or any("PII" in w for w in result.warnings):
        logger.info(
            "memory persist: PII policy '%s' affected %d message(s)",
            mode,
            len(result.dropped) or len(result.warnings),
        )
    return result.kept


def extract_explicit_facts(
    config: Any, messages: Sequence[Mapping[str, Any]]
) -> list[str]:
    """Return facts the agent explicitly marked with ``persist.marker``.

    Scans every message (any role) line-by-line; for each line containing the
    marker, the text *after* the marker is captured as a discrete fact.
    Duplicates are removed while preserving order. PII policy is applied.
    """
    marker = getattr(config, "persist_marker", "MEMORY:") or "MEMORY:"
    facts: list[str] = []
    for msg in messages:
        content = str(msg.get("content", ""))
        for line in content.splitlines():
            idx = line.find(marker)
            if idx == -1:
                continue
            fact = line[idx + len(marker):].strip().lstrip(":-").strip()
            if fact and fact not in facts:
                facts.append(fact)

    if not facts:
        return []
    # Reuse the PII filter on fact strings.
    entries = [{"content": f} for f in facts]
    kept = _apply_pii(config, entries)
    return [e["content"] for e in kept]


def persist_messages(
    provider: Any,
    config: Any,
    *,
    scope: Any,
    keys: Any,
    messages: Sequence[Mapping[str, Any]],
) -> None:
    """Apply the persist policy and write to ``provider`` accordingly.

    - ``off`` — no-op.
    - ``explicit`` — write each marked fact verbatim (``infer=False``).
    - otherwise — curate the message list and ``add_session``.
    """
    strategy = _strategy(config)
    if strategy == "off":
        return

    if strategy == "explicit":
        facts = extract_explicit_facts(config, messages)
        for fact in facts:
            provider.write(fact, scope=scope, keys=keys, infer=False)
        if facts:
            logger.info("memory persist: stored %d explicit fact(s)", len(facts))
        return

    curated = curate_messages(config, messages)
    if curated:
        provider.add_session(curated, scope=scope, keys=keys)
