"""zil inspect — inspect a .zil archive."""

from __future__ import annotations

import json
import tarfile
from pathlib import Path

import click
from rich.console import Console

console = Console()


@click.command()
@click.argument("archive", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--show",
    default=None,
    help="Print a specific file from the archive (e.g. manifest.yaml, identity/persona.md).",
)
@click.option("--json", "output_json", is_flag=True, help="Machine-readable JSON output.")
def inspect(archive: Path, show: str | None, output_json: bool) -> None:
    """Inspect a .zil archive without extracting it.

    Displays the manifest summary, SBOM overview, eval results,
    and component listing.
    """
    if not archive.name.endswith(".zil"):
        console.print(f"[red]Error:[/red] Expected a .zil archive, got '{archive.name}'")
        raise SystemExit(1)

    from zil.packaging.archive import read_archive

    try:
        meta = read_archive(archive)
    except Exception as e:
        console.print(f"[red]Error:[/red] Could not read archive: {e}")
        raise SystemExit(1)

    # --show: print a specific file's contents
    if show:
        _show_file(archive, show)
        return

    # --json: machine-readable output
    if output_json:
        _print_json(meta)
        return

    # Default: rich summary
    _print_summary(archive, meta)


def _print_summary(archive: Path, meta) -> None:
    """Print a rich summary of the archive."""
    from rich.table import Table

    console.print()
    console.print(f"[bold]Zil Package:[/bold] {meta.name}")
    console.print(f"  Version:     {meta.version}")
    if meta.description:
        console.print(f"  Description: {meta.description}")
    console.print(f"  Framework:   {meta.framework} ({meta.language})")
    if meta.created_at:
        console.print(f"  Created:     {meta.created_at}")
    console.print(f"  Size:        {_format_size(meta.archive_size)}")
    console.print()

    # SBOM
    if meta.sbom_dependency_count > 0:
        console.print(f"  SBOM:        {meta.sbom_dependency_count} dependencies")

    # Eval results
    if meta.eval_score is not None:
        score_pct = f"{meta.eval_score * 100:.1f}%"
        threshold = meta.eval_threshold or 0
        status = "[green]passed[/green]" if meta.eval_score >= threshold else "[red]failed[/red]"
        console.print(f"  Evals:       {score_pct} ({status})")

    # Env vars
    if meta.env_var_count > 0:
        secret_info = f", {meta.env_secret_count} secret" if meta.env_secret_count else ""
        console.print(f"  Env vars:    {meta.env_var_count} declared{secret_info}")
        if meta.env_coverage:
            resolved = len(meta.env_coverage.get("resolved_locally", []))
            declared = len(meta.env_coverage.get("declared", []))
            missing = len(meta.env_coverage.get("missing_locally", []))
            missing_info = f" ({missing} missing at pack time)" if missing else ""
            console.print(f"  Env coverage: {resolved}/{declared} resolved locally{missing_info}")

    console.print()

    # Component table
    table = Table(title="Components", show_header=True, header_style="bold")
    table.add_column("Component", style="cyan")
    table.add_column("Files", justify="right")
    table.add_column("Size", justify="right")

    # Group by top-level directory
    groups: dict[str, list[tuple[str, int]]] = {}
    for file_path, size in meta.component_sizes.items():
        top = file_path.split("/")[0]
        if top not in groups:
            groups[top] = []
        groups[top].append((file_path, size))

    for component, files in sorted(groups.items()):
        total_size = sum(s for _, s in files)
        size_str = _format_size(total_size)
        # Distinguish files from directories
        if "/" in files[0][0] or len(files) > 1:
            table.add_row(f"{component}/", str(len(files)), size_str)
        else:
            table.add_row(component, "1", size_str)

    console.print(table)
    console.print()


def _print_json(meta) -> None:
    """Print JSON output."""
    import dataclasses

    data = dataclasses.asdict(meta)
    console.print(json.dumps(data, indent=2))


def _show_file(archive: Path, file_path: str) -> None:
    """Extract and print a specific file from the archive."""
    try:
        with tarfile.open(archive, "r:gz") as tar:
            member = tar.getmember(file_path)
            f = tar.extractfile(member)
            if f is None:
                console.print(f"[red]Error:[/red] Cannot read '{file_path}' (directory?)")
                raise SystemExit(1)
            console.print(f.read().decode())
    except KeyError:
        console.print(f"[red]Error:[/red] '{file_path}' not found in archive")
        # List available files
        with tarfile.open(archive, "r:gz") as tar:
            names = [m.name for m in tar.getmembers() if m.isfile()]
        console.print("\nAvailable files:")
        for name in sorted(names):
            console.print(f"  {name}")
        raise SystemExit(1)


def _format_size(size_bytes: int) -> str:
    """Format bytes as human-readable."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
