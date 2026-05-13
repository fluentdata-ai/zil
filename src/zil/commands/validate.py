"""zil validate — validate a Zil project against the spec."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import click
from rich.console import Console

if TYPE_CHECKING:
    from zil.schema.loader import ValidationResult

console = Console()


@click.command()
@click.option(
    "--project-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=".",
    help="Project directory to validate (default: current directory).",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"], case_sensitive=False),
    default="text",
    help="Output format (default: text).",
)
def validate(project_dir: Path, output_format: str) -> None:
    """Validate a Zil agent project against the manifest schema.

    Checks manifest.yaml against the spec, resolves referenced files,
    and validates sub-schemas (identity, adapters, evals, observability).

    Exit codes: 0 = valid, 1 = invalid, 2 = warnings only.
    """
    from zil.schema.loader import validate_project

    result = validate_project(project_dir)

    if output_format == "json":
        _print_json(result)
    else:
        _print_text(result)

    raise SystemExit(result.exit_code)


def _print_text(result: ValidationResult) -> None:
    """Render validation results as rich text."""
    for check in result.checks:
        icon = {"pass": "✓", "fail": "✗", "warn": "⚠"}[check.status]
        color = {"pass": "green", "fail": "red", "warn": "yellow"}[check.status]
        console.print(f"[{color}]{icon}[/{color}] {check.message}")

    console.print()
    if result.exit_code == 0:
        w = result.warning_count
        summary = f"All checks passed ({w} warning{'s' if w != 1 else ''})"
        console.print(f"[green]{summary}[/green]")
    else:
        console.print(f"[red]Validation failed: {result.error_count} error(s)[/red]")


def _print_json(result: ValidationResult) -> None:
    """Render validation results as JSON."""
    import json

    console.print(json.dumps(result.to_dict(), indent=2), soft_wrap=True)

