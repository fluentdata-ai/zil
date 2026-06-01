"""zil audit — agent-native security audit."""

from __future__ import annotations

import json
from pathlib import Path

import click
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from zil.sdk.audit import AuditFinding, AuditResult, AuditSection, Severity

console = Console()


@click.command()
@click.option(
    "--project-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=".",
    help="Project directory to audit (default: current directory).",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"], case_sensitive=False),
    default="text",
    help="Output format (default: text).",
)
@click.option(
    "--fix",
    "show_fixes",
    is_flag=True,
    help="Show actionable fix suggestions.",
)
def audit(project_dir: Path, output_format: str, show_fixes: bool) -> None:
    """Run an agent-native security audit.

    Analyzes the project for LLM agent-specific attack surfaces:
    prompt injection resilience, output leakage, indirect injection,
    instruction quality, and context window risks.

    Exit codes: 0 = pass, 1 = critical findings, 2 = warnings only.
    """
    result = _run_audit(project_dir)

    if output_format == "json":
        _print_json(result)
    else:
        _print_text(result, show_fixes=show_fixes)

    raise SystemExit(result.exit_code)


def _run_audit(project_dir: Path) -> AuditResult:
    """Execute all audit checks and return the combined result."""
    from zil.sdk.audit.context_window import check_context_window
    from zil.sdk.audit.guardrail_coverage import check_guardrail_coverage
    from zil.sdk.audit.identity_review import check_identity_hardening
    from zil.sdk.audit.indirect_injection import check_indirect_injection
    from zil.sdk.audit.injection_probe import check_injection_resilience
    from zil.sdk.audit.instruction_consistency import check_instruction_consistency
    from zil.sdk.audit.mcp_permissions import check_mcp_permissions
    from zil.sdk.audit.memory_governance import check_memory_governance
    from zil.sdk.audit.output_leakage import check_output_leakage

    # Load project metadata
    manifest_path = project_dir / "manifest.yaml"
    project_name = "unknown"
    project_version = ""
    if manifest_path.is_file():
        try:
            manifest = yaml.safe_load(manifest_path.read_text())
            meta = manifest.get("metadata", {})
            project_name = meta.get("name", "unknown")
            project_version = meta.get("version", "")
        except Exception:
            pass

    # Load guardrails config once
    guardrails_config: dict | None = None
    guardrails_path = project_dir / "identity" / "guardrails.yaml"
    if guardrails_path.is_file():
        try:
            guardrails_config = yaml.safe_load(guardrails_path.read_text())
        except Exception:
            pass

    # Run all checks
    result = AuditResult(
        project_name=project_name,
        project_version=project_version,
    )

    result.sections.append(check_guardrail_coverage(project_dir, guardrails_config))
    result.sections.append(check_injection_resilience(guardrails_config))
    result.sections.append(check_output_leakage(project_dir, guardrails_config))
    result.sections.append(check_indirect_injection(project_dir))
    result.sections.append(check_instruction_consistency(project_dir, guardrails_config))
    result.sections.append(check_context_window(project_dir, guardrails_config))
    result.sections.append(check_identity_hardening(project_dir))
    result.sections.append(check_mcp_permissions(project_dir))
    result.sections.append(check_memory_governance(project_dir))

    return result


def _print_text(result: AuditResult, *, show_fixes: bool) -> None:
    """Render audit results as rich text."""
    # Header panel
    title = f"Project: {result.project_name}"
    if result.project_version:
        title += f"  v{result.project_version}"
    console.print()
    console.print(Panel(title, title="Zil Security Audit", border_style="blue"))
    console.print()

    # Sections
    for section in result.sections:
        _print_section(section, show_fixes=show_fixes)

    # Summary
    console.print()
    if result.critical_count == 0 and result.warning_count == 0:
        console.print("[green]All checks passed.[/green]")
    else:
        parts: list[str] = []
        if result.critical_count > 0:
            parts.append(f"[red]{result.critical_count} critical[/red]")
        if result.warning_count > 0:
            parts.append(f"[yellow]{result.warning_count} warning(s)[/yellow]")
        console.print(f"Summary: {', '.join(parts)}")
        if not show_fixes:
            console.print("[dim]Run `zil audit --fix` for remediation suggestions.[/dim]")
    console.print()


def _print_section(section: AuditSection, *, show_fixes: bool) -> None:
    """Render a single audit section."""
    # Section header with score
    score_color = "green" if section.passed else ("red" if section.has_critical else "yellow")
    header = Text()
    header.append(f"{section.title} ", style="bold")
    header.append("─" * max(1, 50 - len(section.title)))
    header.append(f" {section.score}", style=score_color)
    console.print(header)

    # Findings
    for finding in section.findings:
        _print_finding(finding, show_fixes=show_fixes)

    console.print()


def _print_finding(finding: AuditFinding, *, show_fixes: bool) -> None:
    """Render a single finding."""
    icon_map = {
        Severity.PASS: ("✓", "green"),
        Severity.INFO: ("·", "dim"),
        Severity.WARNING: ("⚠", "yellow"),
        Severity.CRITICAL: ("✗", "red"),
    }
    icon, color = icon_map.get(finding.severity, ("?", "white"))
    console.print(f"  [{color}]{icon}[/{color}] {finding.message}")

    if show_fixes and finding.fix:
        console.print(f"    [dim]→ {finding.fix}[/dim]")


def _print_json(result: AuditResult) -> None:
    """Render audit results as JSON."""
    console.print(json.dumps(result.to_dict(), indent=2), soft_wrap=True)
