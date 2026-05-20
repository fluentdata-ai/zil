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
@click.option(
    "--username",
    default=None,
    help="Registry username (e.g. oauth2accesstoken for GCP).",
)
@click.option(
    "--password",
    default=None,
    help="Registry password or token (e.g. gcloud auth print-access-token).",
)
def push(archive: Path, registry: str, username: str | None, password: str | None) -> None:
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
        reference = push_archive(archive, registry, username=username, password=password)
    except ImportError as e:
        console.print(f"[red]Error:[/red] {e}", highlight=False)
        raise SystemExit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] Push failed: {e}")
        raise SystemExit(1)

    console.print(f"[green]✓[/green] Pushed: [bold]{reference}[/bold]")

    # Push cosign bundle alongside if it exists
    bundle_path = archive.with_suffix(archive.suffix + ".bundle")
    if bundle_path.exists():
        console.print("→ Pushing signature bundle...", end="  ")
        try:
            from zil.packaging.registry import push_signature

            push_signature(bundle_path, reference)
            console.print("[green]✓[/green]")
        except Exception as e:
            console.print(f"[yellow]⚠ {e}[/yellow]")
