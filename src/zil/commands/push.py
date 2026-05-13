"""zil push — push a .zil archive to an OCI registry."""

from pathlib import Path

import click
from rich.console import Console

console = Console()


@click.command()
@click.argument(
    "archive",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--registry",
    required=True,
    help="OCI registry URL (e.g. us-docker.pkg.dev/my-project/agents).",
)
def push(archive: Path, registry: str) -> None:
    """Push a .zil archive to an OCI-compatible registry.

    Uploads the archive as an OCI artifact using oras. Supports any
    OCI-compatible registry: Artifact Registry, GHCR, ECR, Docker Hub.

    Authentication uses ambient credentials (gcloud auth, docker login,
    or ORAS environment variables).
    """
    if not archive.name.endswith(".zil"):
        console.print(
            f"[red]Error:[/red] Expected a .zil archive, got '{archive.name}'"
        )
        raise SystemExit(1)

    console.print(f"→ Pushing [bold]{archive.name}[/bold] to registry...")

    from zil.packaging.registry import push_archive

    try:
        reference = push_archive(archive, registry)
    except ImportError as e:
        console.print(f"[red]Error:[/red] {e}", highlight=False)
        raise SystemExit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] Push failed: {e}")
        raise SystemExit(1)

    console.print(f"[green]✓[/green] Pushed: [bold]{reference}[/bold]")
