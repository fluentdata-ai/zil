"""Audit check: Context window stuffing risk.

Measures combined system prompt size (persona + instructions + guardrails-as-text)
and warns if it's large enough for adversarial context stuffing attacks.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from zil.sdk.audit import AuditFinding, AuditSection, Category, Severity

# Approximate tokens-per-char ratio (conservative estimate)
_CHARS_PER_TOKEN = 4

# Default context window sizes by model family
_CONTEXT_WINDOWS: dict[str, int] = {
    "gemini": 1_000_000,   # Gemini 2.0 Flash
    "anthropic": 200_000,  # Claude 3.5
    "openai": 128_000,     # GPT-4o
    "vertex": 1_000_000,   # Gemini via Vertex
}

# Threshold: warn if system prompt uses more than this % of context
_WARN_THRESHOLD_PCT = 15.0
_CRITICAL_THRESHOLD_PCT = 30.0


def _estimate_tokens(text_or_chars: str | int) -> int:
    """Estimate token count from text string or character count."""
    chars = text_or_chars if isinstance(text_or_chars, int) else len(text_or_chars)
    return chars // _CHARS_PER_TOKEN


def _detect_model_context(project_dir: Path) -> int:
    """Try to detect context window size from adapter config."""
    import yaml

    adapter_path = project_dir / "adapters" / "llm.yaml"
    if not adapter_path.is_file():
        return 128_000  # Conservative default

    try:
        config = yaml.safe_load(adapter_path.read_text())
        provider = config.get("provider", "").lower()
        return _CONTEXT_WINDOWS.get(provider, 128_000)
    except Exception:
        return 128_000


def check_context_window(
    project_dir: Path,
    guardrails_config: dict[str, Any] | None,
) -> AuditSection:
    """Measure system prompt size and assess context stuffing risk."""
    section = AuditSection(
        category=Category.CONTEXT_WINDOW,
        title="Context Window Risk",
    )

    identity_dir = project_dir / "identity"

    # Collect all text that goes into the system prompt
    components: dict[str, str] = {}

    persona_path = identity_dir / "persona.md"
    if persona_path.is_file():
        components["persona.md"] = persona_path.read_text()

    instructions_path = identity_dir / "instructions.md"
    if instructions_path.is_file():
        components["instructions.md"] = instructions_path.read_text()

    # Guardrails get converted to text instructions too
    if guardrails_config:
        # Estimate the guardrails-as-instruction text
        guardrails_text = _estimate_guardrails_text(guardrails_config)
        if guardrails_text:
            components["guardrails (as instruction)"] = guardrails_text

    if not components:
        section.findings.append(AuditFinding(
            category=Category.CONTEXT_WINDOW,
            severity=Severity.INFO,
            message="No system prompt components found",
        ))
        section.score = "N/A"
        return section

    # Calculate totals
    total_chars = sum(len(text) for text in components.values())
    total_tokens = total_chars // _CHARS_PER_TOKEN
    context_window = _detect_model_context(project_dir)
    pct_used = (total_tokens / context_window) * 100

    # Report
    if pct_used >= _CRITICAL_THRESHOLD_PCT:
        section.findings.append(AuditFinding(
            category=Category.CONTEXT_WINDOW,
            severity=Severity.CRITICAL,
            message=(
                f"System prompt: ~{total_tokens:,} tokens "
                f"({pct_used:.1f}% of {context_window:,} context)"
            ),
            detail=(
                "A large system prompt is vulnerable to context stuffing: "
                "attackers can pad their messages to push critical instructions "
                "out of the model's attention window."
            ),
            fix=(
                "Reduce system prompt size. Move verbose instructions to "
                "retrieval-based context or compress persona/instructions text."
            ),
        ))
        section.score = "CRITICAL"
    elif pct_used >= _WARN_THRESHOLD_PCT:
        section.findings.append(AuditFinding(
            category=Category.CONTEXT_WINDOW,
            severity=Severity.WARNING,
            message=(
                f"System prompt: ~{total_tokens:,} tokens "
                f"({pct_used:.1f}% of {context_window:,} context)"
            ),
            detail=(
                "System prompt is moderately large. Consider whether all "
                "content is necessary in every request."
            ),
            fix="Consider splitting rarely-needed instructions into retrieval context.",
        ))
        section.score = "WARN"
    else:
        section.findings.append(AuditFinding(
            category=Category.CONTEXT_WINDOW,
            severity=Severity.PASS,
            message=(
                f"System prompt: ~{total_tokens:,} tokens "
                f"({pct_used:.1f}% of {context_window:,} context)"
            ),
        ))
        section.score = "PASS"

    # Per-component breakdown (info level)
    for name, text in components.items():
        tokens = _estimate_tokens(len(text))
        section.findings.append(AuditFinding(
            category=Category.CONTEXT_WINDOW,
            severity=Severity.INFO,
            message=f"  {name}: ~{tokens:,} tokens",
        ))

    return section


def _estimate_guardrails_text(config: dict[str, Any]) -> str:
    """Estimate the text that guardrails.yaml produces in the instruction."""
    parts: list[str] = []

    # hard_blocks
    for block in config.get("hard_blocks", []):
        desc = block.get("description", "")
        if desc:
            parts.append(f"- {desc}")

    # escalation_triggers
    for trigger in config.get("escalation_triggers", []):
        msg = trigger.get("message", "")
        condition = trigger.get("condition", "")
        if msg or condition:
            parts.append(f"- When {condition}: {msg}")

    # output_constraints
    constraints = config.get("output_constraints", {})
    if constraints:
        for k, v in constraints.items():
            parts.append(f"- {k}: {v}")

    return "\n".join(parts)
