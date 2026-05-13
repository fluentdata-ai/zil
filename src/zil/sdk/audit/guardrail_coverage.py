"""Audit check: Guardrail coverage scoring.

Verifies guardrails.yaml exists and has runtime-enforceable rules,
scores coverage across 5 dimensions.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from zil.sdk.audit import AuditFinding, AuditSection, Category, Severity


def check_guardrail_coverage(
    project_dir: Path,
    guardrails_config: dict[str, Any] | None,
) -> AuditSection:
    """Score guardrail coverage across 5 dimensions."""
    section = AuditSection(
        category=Category.GUARDRAIL_COVERAGE,
        title="Guardrail Coverage",
    )

    if guardrails_config is None:
        guardrails_path = project_dir / "identity" / "guardrails.yaml"
        if guardrails_path.is_file():
            try:
                guardrails_config = yaml.safe_load(guardrails_path.read_text())
            except Exception:
                pass

    if not guardrails_config or not isinstance(guardrails_config, dict):
        section.findings.append(AuditFinding(
            category=Category.GUARDRAIL_COVERAGE,
            severity=Severity.CRITICAL,
            message="No guardrails.yaml found or file is empty",
            fix="Run `zil init` to scaffold a guardrails.yaml with default protections",
        ))
        section.score = "0/5"
        return section

    detection = guardrails_config.get("detection", {})
    passed = 0
    total = 5

    # 1. Prompt injection detection
    if detection.get("prompt_injection", True):
        section.findings.append(AuditFinding(
            category=Category.GUARDRAIL_COVERAGE,
            severity=Severity.PASS,
            message="Prompt injection detection enabled",
        ))
        passed += 1
    else:
        section.findings.append(AuditFinding(
            category=Category.GUARDRAIL_COVERAGE,
            severity=Severity.CRITICAL,
            message="Prompt injection detection disabled",
            fix="Set `detection.prompt_injection: true` in guardrails.yaml",
        ))

    # 2. PII output detection
    if detection.get("pii_output", True):
        section.findings.append(AuditFinding(
            category=Category.GUARDRAIL_COVERAGE,
            severity=Severity.PASS,
            message="PII output detection enabled",
        ))
        passed += 1
    else:
        section.findings.append(AuditFinding(
            category=Category.GUARDRAIL_COVERAGE,
            severity=Severity.WARNING,
            message="PII output detection disabled",
            fix="Set `detection.pii_output: true` in guardrails.yaml",
        ))

    # 3. PII input detection
    if detection.get("pii_input", False):
        section.findings.append(AuditFinding(
            category=Category.GUARDRAIL_COVERAGE,
            severity=Severity.PASS,
            message="PII input detection enabled",
        ))
        passed += 1
    else:
        section.findings.append(AuditFinding(
            category=Category.GUARDRAIL_COVERAGE,
            severity=Severity.INFO,
            message="PII input detection disabled (optional — enable for sensitive apps)",
            fix="Set `detection.pii_input: true` for applications handling PII",
        ))
        # Count as partial pass (it's optional)
        passed += 0.5

    # 4. Output constraints
    constraints = guardrails_config.get("output_constraints", {})
    max_len = constraints.get("max_response_length")
    if max_len:
        section.findings.append(AuditFinding(
            category=Category.GUARDRAIL_COVERAGE,
            severity=Severity.PASS,
            message=f"Output constraints: max {max_len} chars",
        ))
        passed += 1
    else:
        section.findings.append(AuditFinding(
            category=Category.GUARDRAIL_COVERAGE,
            severity=Severity.WARNING,
            message="No output length constraint configured",
            fix="Add `output_constraints.max_response_length` to guardrails.yaml",
        ))

    # 5. Denied topics
    denied_topics = guardrails_config.get("denied_topics", [])
    if denied_topics:
        section.findings.append(AuditFinding(
            category=Category.GUARDRAIL_COVERAGE,
            severity=Severity.PASS,
            message=f"Denied topics: {len(denied_topics)} configured",
        ))
        passed += 1
    else:
        section.findings.append(AuditFinding(
            category=Category.GUARDRAIL_COVERAGE,
            severity=Severity.WARNING,
            message="Denied topics: none configured",
            fix="Add project-specific denied_topics to guardrails.yaml",
        ))

    section.score = f"{int(passed)}/{total}"
    return section
