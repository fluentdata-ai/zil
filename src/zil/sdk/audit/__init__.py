"""Zil Security Audit — agent-native security analysis.

Provides modular audit checks focused on LLM agent-specific attack surfaces:
prompt injection, output leakage, indirect injection, instruction quality,
and context window risks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Severity(StrEnum):
    """Audit finding severity levels."""

    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"
    PASS = "pass"


class Category(StrEnum):
    """Audit check categories."""

    GUARDRAIL_COVERAGE = "guardrail_coverage"
    INJECTION_RESILIENCE = "injection_resilience"
    OUTPUT_LEAKAGE = "output_leakage"
    INDIRECT_INJECTION = "indirect_injection"
    INSTRUCTION_CONSISTENCY = "instruction_consistency"
    CONTEXT_WINDOW = "context_window"
    IDENTITY_HARDENING = "identity_hardening"
    MCP_PERMISSIONS = "mcp_permissions"
    MEMORY_GOVERNANCE = "memory_governance"


@dataclass
class AuditFinding:
    """A single finding from an audit check."""

    category: Category
    severity: Severity
    message: str
    detail: str = ""
    fix: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "category": self.category.value,
            "severity": self.severity.value,
            "message": self.message,
        }
        if self.detail:
            d["detail"] = self.detail
        if self.fix:
            d["fix"] = self.fix
        return d


@dataclass
class AuditSection:
    """Results from one audit check category."""

    category: Category
    title: str
    score: str = ""  # e.g. "4/5" or "PASS"
    findings: list[AuditFinding] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(f.severity in (Severity.PASS, Severity.INFO) for f in self.findings)

    @property
    def has_critical(self) -> bool:
        return any(f.severity == Severity.CRITICAL for f in self.findings)

    @property
    def has_warning(self) -> bool:
        return any(f.severity == Severity.WARNING for f in self.findings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category.value,
            "title": self.title,
            "score": self.score,
            "passed": self.passed,
            "findings": [f.to_dict() for f in self.findings],
        }


@dataclass
class AuditResult:
    """Complete audit report."""

    project_name: str = ""
    project_version: str = ""
    sections: list[AuditSection] = field(default_factory=list)

    @property
    def critical_count(self) -> int:
        return sum(
            1
            for s in self.sections
            for f in s.findings
            if f.severity == Severity.CRITICAL
        )

    @property
    def warning_count(self) -> int:
        return sum(
            1
            for s in self.sections
            for f in s.findings
            if f.severity == Severity.WARNING
        )

    @property
    def exit_code(self) -> int:
        if self.critical_count > 0:
            return 1
        if self.warning_count > 0:
            return 2
        return 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "project": self.project_name,
            "version": self.project_version,
            "exit_code": self.exit_code,
            "critical": self.critical_count,
            "warnings": self.warning_count,
            "sections": [s.to_dict() for s in self.sections],
        }


__all__ = [
    "AuditFinding",
    "AuditResult",
    "AuditSection",
    "Category",
    "Severity",
]
