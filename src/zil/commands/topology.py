"""zil topology — render the declared A2A collaboration graph and flag cycles.

Scans a directory tree for agent ``manifest.yaml`` files, builds the declared
topology (who lists whom in ``spec.collaborators``), prints the edges, and
reports any cycles (ZIL-RFC-005 §10.1). Useful for a monorepo / fleet of agents
before a registry of record (RFC-007) exists.

Exit codes: 0 = acyclic, 1 = cycle(s) detected.
"""

from __future__ import annotations

import json as _json
from pathlib import Path

import click
import yaml
from rich.console import Console

console = Console()


def _load_manifests(root_dir: Path) -> list[dict]:
    """Load every ``manifest.yaml`` under *root_dir* (skipping unreadable ones)."""
    manifests: list[dict] = []
    for path in sorted(root_dir.rglob("manifest.yaml")):
        try:
            data = yaml.safe_load(path.read_text())
        except (yaml.YAMLError, OSError):
            continue
        if isinstance(data, dict):
            manifests.append(data)
    return manifests


@click.command()
@click.option(
    "--dir",
    "root_dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=".",
    help="Directory to scan for manifests (default: current directory).",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"], case_sensitive=False),
    default="text",
    help="Output format (default: text).",
)
def topology(root_dir: Path, output_format: str) -> None:
    """Render the declared A2A topology across manifests and flag cycles."""
    from zil.collaboration.topology import build_topology_graph, find_cycles

    manifests = _load_manifests(root_dir)
    graph = build_topology_graph(manifests)
    cycles = find_cycles(graph)

    if output_format == "json":
        console.print_json(
            _json.dumps({"graph": graph, "cycles": cycles})
        )
        raise SystemExit(1 if cycles else 0)

    if not graph:
        console.print("[yellow]No agent manifests with a name found.[/yellow]")
        raise SystemExit(0)

    console.print("[bold]Declared A2A topology[/bold]")
    for agent in sorted(graph):
        peers = graph[agent]
        if peers:
            for peer in peers:
                known = "" if peer in graph else " [dim](external)[/dim]"
                console.print(f"  {agent} [dim]→[/dim] {peer}{known}")
        else:
            console.print(f"  {agent} [dim](no collaborators)[/dim]")

    console.print()
    if cycles:
        console.print(f"[red]✗ {len(cycles)} cycle(s) detected:[/red]")
        for cycle in cycles:
            console.print("  [red]" + " → ".join([*cycle, cycle[0]]) + "[/red]")
        raise SystemExit(1)

    console.print("[green]✓ No cycles detected[/green]")
    raise SystemExit(0)
