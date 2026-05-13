"""Audit check: Instruction consistency analysis.

Detects contradictions between persona.md (permissive language) and
guardrails.yaml (restrictive rules) that create social-engineering gaps.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from zil.sdk.audit import AuditFinding, AuditSection, Category, Severity

# Permissive patterns that conflict with strict guardrails
_PERMISSIVE_PATTERNS: list[tuple[str, str]] = [
    (r"\b(do|help with)\s+anything\b", "overly permissive: 'do/help with anything'"),
    (r"\bno\s+(limitations?|restrictions?|boundaries)\b", "claims no limitations"),
    (r"\balways\s+(comply|agree|say yes|help)\b", "unconditional compliance"),
    (r"\bnever\s+(refuse|reject|decline|say no)\b", "never refuse pattern"),
    (r"\b(any|all)\s+requests?\b.*\b(fulfill|handle|process)\b",
     "handles all requests without qualification"),
    (r"\byou\s+can\s+do\s+(everything|anything)\b", "claims unlimited capability"),
]

# Restrictive patterns that should be present when guardrails are strict
_BOUNDARY_PATTERNS: list[tuple[str, str]] = [
    (r"\b(cannot|can't|will not|won't|refuse|decline)\b", "refusal language"),
    (r"\b(boundar|limit|restrict|scope|only)\b", "boundary definition"),
    (r"\b(not\s+)?(designed|built|intended)\s+(to|for)\b", "scope definition"),
    (r"\b(outside|beyond)\s+(my|the)\s+(scope|capabilities?)\b", "explicit scope limit"),
]


def check_instruction_consistency(
    project_dir: Path,
    guardrails_config: dict[str, Any] | None,
) -> AuditSection:
    """Detect contradictions between persona/instructions and guardrails."""
    section = AuditSection(
        category=Category.INSTRUCTION_CONSISTENCY,
        title="Instruction Consistency",
    )

    identity_dir = project_dir / "identity"

    # Load persona and instructions
    persona_text = ""
    instructions_text = ""

    persona_path = identity_dir / "persona.md"
    if persona_path.is_file():
        persona_text = persona_path.read_text().lower()

    instructions_path = identity_dir / "instructions.md"
    if instructions_path.is_file():
        instructions_text = instructions_path.read_text().lower()

    combined_text = f"{persona_text}\n{instructions_text}"

    if not combined_text.strip():
        section.findings.append(AuditFinding(
            category=Category.INSTRUCTION_CONSISTENCY,
            severity=Severity.INFO,
            message="No identity files to analyze",
        ))
        section.score = "N/A"
        return section

    # Check for permissive language that contradicts guardrails
    has_guardrails = bool(guardrails_config)
    has_denied_topics = bool(
        guardrails_config.get("denied_topics") if guardrails_config else False
    )
    has_blocked_patterns = bool(
        guardrails_config.get("blocked_patterns") if guardrails_config else False
    )

    contradictions = 0

    for pattern, description in _PERMISSIVE_PATTERNS:
        matches = re.findall(pattern, combined_text, re.IGNORECASE)
        if matches and has_guardrails:
            contradictions += 1
            # Determine which file contains the contradiction
            source = "persona.md" if re.search(pattern, persona_text) else "instructions.md"
            section.findings.append(AuditFinding(
                category=Category.INSTRUCTION_CONSISTENCY,
                severity=Severity.WARNING,
                message=f"{source} — {description}",
                detail=(
                    f"Permissive language in {source} conflicts with "
                    f"restrictive guardrails. Attackers can exploit this "
                    f"contradiction via social engineering."
                ),
                fix=(
                    f"Remove or qualify permissive language in {source}. "
                    f"Replace with explicit scope boundaries."
                ),
            ))

    # Check if guardrails are strict but instructions lack boundaries
    if has_denied_topics or has_blocked_patterns:
        has_boundary = any(
            re.search(pattern, combined_text)
            for pattern, _ in _BOUNDARY_PATTERNS
        )
        if not has_boundary:
            contradictions += 1
            section.findings.append(AuditFinding(
                category=Category.INSTRUCTION_CONSISTENCY,
                severity=Severity.WARNING,
                message=(
                    "Guardrails enforce restrictions but instructions "
                    "lack explicit boundary language"
                ),
                detail=(
                    "The LLM receives conflicting signals: guardrails block "
                    "certain content, but the instruction text never mentions "
                    "any limits. This makes the agent easier to social-engineer."
                ),
                fix=(
                    "Add explicit scope boundaries to instructions.md "
                    "(e.g., 'I cannot help with X, Y, Z')"
                ),
            ))

    if contradictions == 0:
        section.findings.append(AuditFinding(
            category=Category.INSTRUCTION_CONSISTENCY,
            severity=Severity.PASS,
            message="No contradictions between persona and guardrails",
        ))
        section.score = "PASS"
    else:
        section.score = f"{contradictions} issue(s)"

    return section
