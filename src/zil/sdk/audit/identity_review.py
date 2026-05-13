"""Audit check: Identity hardening review.

Checks persona.md and instructions.md for anti-patterns such as vague
boundaries, missing refusal patterns, and overly permissive language.
"""

from __future__ import annotations

import re
from pathlib import Path

from zil.sdk.audit import AuditFinding, AuditSection, Category, Severity

# Patterns indicating good security posture in identity files
_POSITIVE_PATTERNS: dict[str, list[tuple[str, str]]] = {
    "Refusal boundaries": [
        (r"\b(cannot|can't|will not|won't|must not|refuse|decline)\b",
         "refusal language present"),
    ],
    "Scope definition": [
        (r"\b(only|specifically|exclusively)\b.*\b(help|assist|handle)\b",
         "explicit scope constraint"),
        (r"\b(designed|built|created)\s+(to|for)\b",
         "purpose statement"),
    ],
    "Response format": [
        (r"\b(format|structure|template|markdown|bullet)\b",
         "response format defined"),
    ],
}

# Anti-patterns that weaken security
_ANTI_PATTERNS: list[tuple[str, str, str]] = [
    (r"\byou\s+are\s+(a\s+)?helpful\s+assistant\b",
     "Generic 'helpful assistant' persona",
     "Define a specific role with explicit boundaries instead of generic assistant"),
    (r"\b(do|try)\s+your\s+best\b",
     "'Try your best' without constraints",
     "Add explicit boundaries for what 'best' means in your context"),
    (r"\bfollow\s+(the\s+)?user['']?s?\s+(instructions?|requests?)\b",
     "Blanket instruction-following directive",
     "Qualify with 'within the scope of...' or 'unless it conflicts with...'"),
]


def check_identity_hardening(project_dir: Path) -> AuditSection:
    """Review identity files for security anti-patterns."""
    section = AuditSection(
        category=Category.IDENTITY_HARDENING,
        title="Identity Hardening",
    )

    identity_dir = project_dir / "identity"
    files_to_check: dict[str, str] = {}

    persona_path = identity_dir / "persona.md"
    if persona_path.is_file():
        files_to_check["persona.md"] = persona_path.read_text()

    instructions_path = identity_dir / "instructions.md"
    if instructions_path.is_file():
        files_to_check["instructions.md"] = instructions_path.read_text()

    if not files_to_check:
        section.findings.append(AuditFinding(
            category=Category.IDENTITY_HARDENING,
            severity=Severity.CRITICAL,
            message="No identity files found (persona.md, instructions.md)",
            fix="Run `zil init` to scaffold identity files with security defaults",
        ))
        section.score = "CRITICAL"
        return section

    issues = 0

    # Check for positive patterns (should be present)
    combined_text = "\n".join(files_to_check.values()).lower()

    for check_name, patterns in _POSITIVE_PATTERNS.items():
        found = False
        for pattern, _ in patterns:
            if re.search(pattern, combined_text, re.IGNORECASE):
                found = True
                break

        if found:
            section.findings.append(AuditFinding(
                category=Category.IDENTITY_HARDENING,
                severity=Severity.PASS,
                message=f"{check_name} — present",
            ))
        else:
            issues += 1
            # Determine which file should contain this
            target = "instructions.md" if check_name != "Response format" else "instructions.md"
            section.findings.append(AuditFinding(
                category=Category.IDENTITY_HARDENING,
                severity=Severity.WARNING,
                message=f"{check_name} — not found in identity files",
                fix=f"Add explicit {check_name.lower()} to {target}",
            ))

    # Check for anti-patterns (should NOT be present)
    for pattern, description, fix in _ANTI_PATTERNS:
        for filename, content in files_to_check.items():
            if re.search(pattern, content, re.IGNORECASE):
                issues += 1
                section.findings.append(AuditFinding(
                    category=Category.IDENTITY_HARDENING,
                    severity=Severity.WARNING,
                    message=f"{filename} — {description}",
                    fix=fix,
                ))

    if issues == 0:
        section.score = "PASS"
    else:
        section.score = f"{issues} issue(s)"

    return section
