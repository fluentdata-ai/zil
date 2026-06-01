"""Tests for persist-time curation (strategy + PII enforcement).

Covers the framework-neutral ``curate_messages`` policy and its wiring into
the OpenHands persist path.
"""

from __future__ import annotations

from typing import Any

from zil.sdk.memory import MemoryConfig, MemoryScope
from zil.sdk.memory.curation import (
    curate_messages,
    extract_explicit_facts,
    persist_enabled,
    persist_messages,
)


def _cfg(**persist: Any) -> MemoryConfig:
    return MemoryConfig.from_dict(
        {"provider": "stub", "scopes": ["agent"], "namespace": "coding",
         "persist": persist}
    )


_EXCHANGE = [
    {"role": "user", "content": "who is working on INCA-247?"},
    {"role": "assistant", "content": "Alvaro Castillo is working on INCA-247."},
]


class TestConfigProperties:
    def test_defaults(self):
        cfg = _cfg()
        assert cfg.persist_strategy == "turn"
        assert cfg.persist_pii_mode == "drop"

    def test_parses_values(self):
        cfg = _cfg(strategy="ASSISTANT_ONLY", pii_mode="REDACT")
        assert cfg.persist_strategy == "assistant_only"
        assert cfg.persist_pii_mode == "redact"


class TestStrategy:
    def test_turn_keeps_all(self):
        out = curate_messages(_cfg(strategy="turn"), _EXCHANGE)
        assert len(out) == 2

    def test_assistant_only_drops_user(self):
        out = curate_messages(_cfg(strategy="assistant_only"), _EXCHANGE)
        assert [m["role"] for m in out] == ["assistant"]

    def test_off_returns_empty(self):
        assert curate_messages(_cfg(strategy="off"), _EXCHANGE) == []
        assert persist_enabled(_cfg(strategy="off")) is False
        assert persist_enabled(_cfg()) is True

    def test_unknown_strategy_treated_as_turn(self):
        # Provider/loader validate; curation should not crash on a bad value.
        out = curate_messages(_cfg(strategy="bogus"), _EXCHANGE)
        assert len(out) == 2


class TestPII:
    def test_drop_removes_pii_message(self):
        msgs = [
            {"role": "assistant", "content": "Use ruff for linting."},
            {"role": "assistant", "content": "Email me at a@b.com."},
        ]
        out = curate_messages(_cfg(exclude_pii=True), msgs)
        assert len(out) == 1
        assert "a@b.com" not in out[0]["content"]

    def test_redact_keeps_but_masks(self):
        msgs = [{"role": "assistant", "content": "ping 10.0.0.1 now"}]
        out = curate_messages(_cfg(exclude_pii=True, pii_mode="redact"), msgs)
        assert len(out) == 1
        assert "[REDACTED]" in out[0]["content"]

    def test_names_not_treated_as_pii(self):
        # Heuristic does not detect personal names.
        out = curate_messages(_cfg(exclude_pii=True), _EXCHANGE)
        assert any("Alvaro Castillo" in m["content"] for m in out)

    def test_pii_disabled_keeps_everything(self):
        msgs = [{"role": "assistant", "content": "Email a@b.com"}]
        out = curate_messages(_cfg(exclude_pii=False), msgs)
        assert len(out) == 1

    def test_strategy_and_pii_combined(self):
        msgs = [
            {"role": "user", "content": "my ssn is 123-45-6789"},
            {"role": "assistant", "content": "Noted; I will not store it."},
            {"role": "assistant", "content": "Reach me at a@b.com"},
        ]
        out = curate_messages(
            _cfg(strategy="assistant_only", exclude_pii=True), msgs
        )
        # user dropped by strategy; PII assistant msg dropped; one clean left.
        assert len(out) == 1
        assert out[0]["content"] == "Noted; I will not store it."


class _CapturingProvider:
    def __init__(self) -> None:
        self.sessions: list[list[dict]] = []
        self.writes: list[tuple[str, Any]] = []  # (content, infer)

    def add_session(self, messages, *, scope, keys, **kw):  # noqa: ANN001
        self.sessions.append(list(messages))
        return ["m1"]

    def write(self, content, *, scope, keys, infer=None, **kw):  # noqa: ANN001
        self.writes.append((content, infer))
        return ["w1"]


class TestExplicit:
    def test_extracts_marked_facts(self):
        cfg = _cfg(strategy="explicit", marker="MEMORY:")
        msgs = [
            {"role": "user", "content": "I want to own INCA-225"},
            {"role": "assistant", "content": (
                "Understood.\nMEMORY: Jesus is the sole owner of INCA-225.\n"
                "Let me proceed."
            )},
        ]
        assert extract_explicit_facts(cfg, msgs) == [
            "Jesus is the sole owner of INCA-225."
        ]

    def test_no_marker_extracts_nothing(self):
        cfg = _cfg(strategy="explicit")
        assert extract_explicit_facts(cfg, _EXCHANGE) == []

    def test_multiple_and_dedup(self):
        cfg = _cfg(strategy="explicit")
        msgs = [{"role": "assistant", "content": (
            "MEMORY: Fact A\nMEMORY: Fact B\nMEMORY: Fact A"
        )}]
        assert extract_explicit_facts(cfg, msgs) == ["Fact A", "Fact B"]

    def test_custom_marker(self):
        cfg = _cfg(strategy="explicit", marker="[remember]")
        msgs = [{"role": "user", "content": "[remember] deploy on Fridays only"}]
        assert extract_explicit_facts(cfg, msgs) == ["deploy on Fridays only"]

    def test_pii_dropped_from_facts(self):
        cfg = _cfg(strategy="explicit", exclude_pii=True)
        msgs = [{"role": "assistant", "content": (
            "MEMORY: ping me at a@b.com\nMEMORY: prefer squash merges"
        )}]
        assert extract_explicit_facts(cfg, msgs) == ["prefer squash merges"]

    def test_persist_messages_writes_verbatim(self):
        provider = _CapturingProvider()
        cfg = _cfg(strategy="explicit")
        msgs = [{"role": "assistant", "content": "MEMORY: own INCA-225"}]
        persist_messages(
            provider, cfg, scope=MemoryScope.AGENT, keys=None, messages=msgs
        )
        assert provider.writes == [("own INCA-225", False)]
        assert provider.sessions == []

    def test_persist_messages_explicit_no_marker_writes_nothing(self):
        provider = _CapturingProvider()
        persist_messages(
            provider, _cfg(strategy="explicit"),
            scope=MemoryScope.AGENT, keys=None, messages=_EXCHANGE,
        )
        assert provider.writes == []
        assert provider.sessions == []

    def test_seen_dedups_across_calls(self):
        # Simulates ADK re-sending the full session each turn.
        provider = _CapturingProvider()
        cfg = _cfg(strategy="explicit")
        seen: set[str] = set()
        turn1 = [{"role": "assistant", "content": "MEMORY: own INCA-225"}]
        turn2 = [
            {"role": "assistant", "content": "MEMORY: own INCA-225"},
            {"role": "assistant", "content": "MEMORY: prefer squash merges"},
        ]
        persist_messages(provider, cfg, scope=MemoryScope.AGENT, keys=None,
                         messages=turn1, seen=seen)
        persist_messages(provider, cfg, scope=MemoryScope.AGENT, keys=None,
                         messages=turn2, seen=seen)
        # "own INCA-225" written once; only the new fact added on turn 2.
        assert [c for c, _ in provider.writes] == [
            "own INCA-225", "prefer squash merges"
        ]
        assert seen == {"own INCA-225", "prefer squash merges"}

    def test_without_seen_rewrites(self):
        provider = _CapturingProvider()
        cfg = _cfg(strategy="explicit")
        msgs = [{"role": "assistant", "content": "MEMORY: own INCA-225"}]
        persist_messages(provider, cfg, scope=MemoryScope.AGENT, keys=None,
                         messages=msgs)
        persist_messages(provider, cfg, scope=MemoryScope.AGENT, keys=None,
                         messages=msgs)
        assert len(provider.writes) == 2  # no dedup without a seen set


class TestOpenHandsWiring:
    def test_persist_turn_applies_assistant_only(self):
        from zil.sdk.frameworks.openhands.memory_wiring import persist_turn

        provider = _CapturingProvider()
        persist_turn(
            provider,
            _cfg(strategy="assistant_only"),
            user_message="who is on INCA-247?",
            agent_messages=["Alvaro is on it."],
            user_id=None,
        )
        assert len(provider.sessions) == 1
        assert [m["role"] for m in provider.sessions[0]] == ["assistant"]

    def test_persist_turn_explicit_writes_marked_fact(self):
        from zil.sdk.frameworks.openhands.memory_wiring import persist_turn

        provider = _CapturingProvider()
        persist_turn(
            provider,
            _cfg(strategy="explicit"),
            user_message="I want to be the sole owner of INCA-225",
            agent_messages=[
                "Got it.\nMEMORY: Jesus is the sole owner of INCA-225."
            ],
            user_id=None,
        )
        assert provider.writes == [
            ("Jesus is the sole owner of INCA-225.", False)
        ]
        assert provider.sessions == []

    def test_persist_turn_off_writes_nothing(self):
        from zil.sdk.frameworks.openhands.memory_wiring import persist_turn

        provider = _CapturingProvider()
        persist_turn(
            provider,
            _cfg(strategy="off"),
            user_message="hi",
            agent_messages=["hello"],
            user_id=None,
        )
        assert provider.sessions == []

    def test_scope_is_agent_namespace(self):
        # Sanity: curation does not disturb scope/keys selection.
        from zil.sdk.frameworks.openhands.memory_wiring import scope_and_keys

        scope, keys = scope_and_keys(_cfg(), user_id=None)
        assert scope is MemoryScope.AGENT
        assert keys.namespace == "coding"
