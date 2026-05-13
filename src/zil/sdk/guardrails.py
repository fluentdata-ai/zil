"""Runtime guardrail enforcement engine.

Loads structured guardrail rules from ``identity/guardrails.yaml`` and
enforces them at runtime via ``check_input()`` / ``check_output()``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Violation:
    """A single guardrail violation."""

    rule: str
    description: str
    severity: str = "block"  # "block" | "warn" | "log"
    matched_text: str = ""


@dataclass
class GuardrailResult:
    """Outcome of a guardrail check."""

    passed: bool
    violations: list[Violation] = field(default_factory=list)
    action: str = "allow"  # "allow" | "block" | "warn"

    @property
    def blocked(self) -> bool:
        return self.action == "block"

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "action": self.action,
            "violations": [
                {
                    "rule": v.rule,
                    "description": v.description,
                    "severity": v.severity,
                    "matched_text": v.matched_text,
                }
                for v in self.violations
            ],
        }


# ---------------------------------------------------------------------------
# Built-in pattern libraries
# ---------------------------------------------------------------------------

# Common prompt injection signatures
_INJECTION_PATTERNS: list[tuple[str, str]] = [
    (r"ignore\s+(all\s+)?(previous|prior|above|the\s+above)\s+(instructions?|prompts?|rules?|context)",
     "Prompt injection: ignore previous instructions"),
    (r"(you\s+are|act\s+as|pretend\s+(to\s+be|you[\u2019']re))\s+(now\s+)?(a\s+)?DAN",
     "Prompt injection: DAN jailbreak attempt"),
    (r"(system\s*prompt|system\s*message)\s*[:=]",
     "Prompt injection: system prompt override attempt"),
    (r"<\s*/?\s*(system|SYSTEM)\s*>",
     "Prompt injection: XML system tag injection"),
    (r"\[INST\]|\[/INST\]|\[SYS\]|\[/SYS\]",
     "Prompt injection: instruction tag injection"),
    (r"(?:do\s+)?(?:not|don[\u2019']t)\s+follow\s+(?:your|the|any)\s+(?:rules?|guidelines?|guardrails?|instructions?)",
     "Prompt injection: rule override attempt"),
    (r"reveal\s+(?:your|the)\s+(?:system\s+)?(?:prompt|instructions?|rules?)",
     "Prompt injection: system prompt extraction"),
    (r"(?:forget|disregard|override)\s+(?:all\s+)?(?:your\s+|the\s+|any\s+)?(?:previous\s+)?(?:instructions?|rules?|constraints?|prompts?)",
     "Prompt injection: instruction override"),
    (r"(?:what|print|show|tell|repeat)\s+(?:are\s+)?(?:your|the)\s+(?:system\s+)?(?:instructions?|rules?|prompt)",
     "Prompt injection: instruction extraction via question"),
    (r"(?:new\s+task|new\s+instruction|instead\s+(?:say|do|tell))",
     "Prompt injection: task override attempt"),
]

# Common PII patterns
_PII_PATTERNS: list[tuple[str, str]] = [
    (r"\b\d{3}-\d{2}-\d{4}\b", "PII: Social Security Number pattern"),
    (r"\b\d{16}\b|\b\d{4}[\s-]\d{4}[\s-]\d{4}[\s-]\d{4}\b",
     "PII: Credit card number pattern"),
]


def _compile_patterns(
    patterns: list[tuple[str, str]],
) -> list[tuple[re.Pattern[str], str]]:
    compiled: list[tuple[re.Pattern[str], str]] = []
    for pattern, desc in patterns:
        try:
            compiled.append((re.compile(pattern, re.IGNORECASE), desc))
        except re.error:
            logger.warning("Invalid regex pattern: %s", pattern)
    return compiled


# Pre-compiled built-in patterns
_COMPILED_INJECTION = _compile_patterns(_INJECTION_PATTERNS)
_COMPILED_PII = _compile_patterns(_PII_PATTERNS)


# ---------------------------------------------------------------------------
# GuardrailEngine
# ---------------------------------------------------------------------------

class GuardrailEngine:
    """Loads guardrail rules and enforces them on input/output text.

    Typical usage::

        engine = GuardrailEngine.from_config(guardrails_dict)
        result = engine.check_input(user_message)
        if result.blocked:
            return "I can't help with that."
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._input_patterns: list[tuple[re.Pattern[str], str, str]] = []
        self._output_patterns: list[tuple[re.Pattern[str], str, str]] = []
        self._denied_topics: list[str] = []
        self._max_output_length: int | None = None
        self._injection_detection: bool = True
        self._pii_detection_input: bool = False
        self._pii_detection_output: bool = True

        if config:
            self._load(config)

    @classmethod
    def from_config(cls, config: dict[str, Any] | None) -> GuardrailEngine:
        """Create an engine from a parsed guardrails.yaml dictionary."""
        return cls(config)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_input(self, text: str) -> GuardrailResult:
        """Validate user input before it reaches the LLM."""
        violations: list[Violation] = []

        # 1. Injection detection (built-in)
        if self._injection_detection:
            violations.extend(self._check_injection(text))

        # 2. PII detection on input
        if self._pii_detection_input:
            violations.extend(self._check_pii(text, direction="input"))

        # 3. Custom blocked patterns for input
        for pattern, name, severity in self._input_patterns:
            match = pattern.search(text)
            if match:
                violations.append(Violation(
                    rule=name,
                    description=f"Input matched blocked pattern: {name}",
                    severity=severity,
                    matched_text=match.group(0)[:100],
                ))

        # 4. Denied topics (keyword-based)
        violations.extend(self._check_denied_topics(text))

        return self._build_result(violations)

    def check_output(self, text: str) -> GuardrailResult:
        """Validate agent output before returning to the user."""
        violations: list[Violation] = []

        # 1. PII detection on output
        if self._pii_detection_output:
            violations.extend(self._check_pii(text, direction="output"))

        # 2. Custom blocked patterns for output
        for pattern, name, severity in self._output_patterns:
            match = pattern.search(text)
            if match:
                violations.append(Violation(
                    rule=name,
                    description=f"Output matched blocked pattern: {name}",
                    severity=severity,
                    matched_text=match.group(0)[:100],
                ))

        # 3. Max output length
        if self._max_output_length and len(text) > self._max_output_length:
            violations.append(Violation(
                rule="max_output_length",
                description=(
                    f"Output exceeds max length: {len(text)} > "
                    f"{self._max_output_length}"
                ),
                severity="warn",
            ))

        return self._build_result(violations)

    @property
    def rule_count(self) -> int:
        """Total number of active rules."""
        count = len(self._input_patterns) + len(self._output_patterns)
        count += len(self._denied_topics)
        if self._injection_detection:
            count += len(_COMPILED_INJECTION)
        if self._pii_detection_input or self._pii_detection_output:
            count += len(_COMPILED_PII)
        if self._max_output_length:
            count += 1
        return count

    @property
    def has_input_checks(self) -> bool:
        return bool(
            self._injection_detection
            or self._pii_detection_input
            or self._input_patterns
            or self._denied_topics
        )

    @property
    def has_output_checks(self) -> bool:
        return bool(
            self._pii_detection_output
            or self._output_patterns
            or self._max_output_length
        )

    def summary(self) -> dict[str, Any]:
        """Return a summary of the engine configuration for reporting."""
        return {
            "rule_count": self.rule_count,
            "has_input_checks": self.has_input_checks,
            "has_output_checks": self.has_output_checks,
            "injection_detection": self._injection_detection,
            "pii_detection_input": self._pii_detection_input,
            "pii_detection_output": self._pii_detection_output,
            "denied_topics": len(self._denied_topics),
            "input_patterns": len(self._input_patterns),
            "output_patterns": len(self._output_patterns),
            "max_output_length": self._max_output_length,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load(self, config: dict[str, Any]) -> None:
        """Parse guardrails.yaml config into internal state."""
        # Blocked patterns
        for bp in config.get("blocked_patterns", []):
            name = bp.get("name", "custom_pattern")
            pattern_str = bp.get("pattern", "")
            target = bp.get("target", "both")  # "input" | "output" | "both"
            severity = bp.get("severity", "block")
            if not pattern_str:
                continue
            try:
                compiled = re.compile(pattern_str, re.IGNORECASE)
            except re.error:
                logger.warning("Invalid blocked_patterns regex: %s", pattern_str)
                continue
            entry = (compiled, name, severity)
            if target in ("input", "both"):
                self._input_patterns.append(entry)
            if target in ("output", "both"):
                self._output_patterns.append(entry)

        # Denied topics
        self._denied_topics = [
            t.lower() for t in config.get("denied_topics", [])
        ]

        # Output constraints
        constraints = config.get("output_constraints", {})
        max_len = constraints.get("max_response_length")
        if max_len is not None:
            self._max_output_length = int(max_len)

        # Detection toggles
        detection = config.get("detection", {})
        self._injection_detection = detection.get(
            "prompt_injection", True
        )
        self._pii_detection_input = detection.get(
            "pii_input", False
        )
        self._pii_detection_output = detection.get(
            "pii_output", True
        )

        # Custom PII patterns (extend built-in)
        custom_pii = detection.get("pii_patterns", [])
        if custom_pii:
            extra = _compile_patterns(
                [(p.get("pattern", ""), p.get("name", "custom_pii"))
                 for p in custom_pii if p.get("pattern")]
            )
            # We store compiled PII separately as class-level, but custom ones
            # go into output patterns for simplicity
            for compiled, name in extra:
                entry = (compiled, name, "block")
                if self._pii_detection_input:
                    self._input_patterns.append(entry)
                if self._pii_detection_output:
                    self._output_patterns.append(entry)

    def _check_injection(self, text: str) -> list[Violation]:
        violations: list[Violation] = []
        for pattern, desc in _COMPILED_INJECTION:
            match = pattern.search(text)
            if match:
                violations.append(Violation(
                    rule="prompt_injection",
                    description=desc,
                    severity="block",
                    matched_text=match.group(0)[:100],
                ))
        return violations

    def _check_pii(self, text: str, *, direction: str) -> list[Violation]:
        violations: list[Violation] = []
        for pattern, desc in _COMPILED_PII:
            match = pattern.search(text)
            if match:
                violations.append(Violation(
                    rule="pii_detection",
                    description=f"{desc} ({direction})",
                    severity="block",
                    matched_text=match.group(0)[:100],
                ))
        return violations

    def _check_denied_topics(self, text: str) -> list[Violation]:
        violations: list[Violation] = []
        text_lower = text.lower()
        for topic in self._denied_topics:
            if topic in text_lower:
                violations.append(Violation(
                    rule="denied_topic",
                    description=f"Input contains denied topic: {topic}",
                    severity="block",
                    matched_text=topic,
                ))
        return violations

    @staticmethod
    def _build_result(violations: list[Violation]) -> GuardrailResult:
        if not violations:
            return GuardrailResult(passed=True, action="allow")

        # Determine highest-severity action
        severities = {v.severity for v in violations}
        if "block" in severities:
            action = "block"
        elif "warn" in severities:
            action = "warn"
        else:
            action = "log"

        return GuardrailResult(
            passed="block" not in severities,
            violations=violations,
            action=action,
        )
