"""Shared Docker helpers for containerized local runs."""

import atexit
import shutil
import subprocess
import sys
from pathlib import Path

from rich.console import Console

console = Console()

OTEL_LGTM_IMAGE = "grafana/otel-lgtm:latest"
OTEL_CONTAINER_NAME = "zil-otel-lgtm"
GRAFANA_PORT = 3000


def check_docker() -> bool:
    """Check if Docker CLI is available."""
    if not shutil.which("docker"):
        console.print(
            "[red]Error:[/red] Docker CLI not found. "
            "Install Docker: https://docs.docker.com/get-docker/"
        )
        return False
    return True


def find_env_files(project_dir: Path, module_dir: str) -> list[Path]:
    """Find env files — check module dir first, then project root.

    Returns all .env and .env.local files found (Docker supports multiple
    --env-file flags; later files override earlier ones).
    """
    candidates = [
        project_dir / module_dir / ".env",
        project_dir / ".env",
        project_dir / module_dir / ".env.local",
        project_dir / ".env.local",
    ]
    seen: set[Path] = set()
    result: list[Path] = []
    for c in candidates:
        resolved = c.resolve()
        if resolved not in seen and c.is_file():
            seen.add(resolved)
            result.append(c)
    return result


def start_otel_stack() -> str | None:
    """Start Grafana OTEL-LGTM stack (traces + metrics + logs).

    Returns container ID or None.
    """
    console.print("→ Starting observability stack (Grafana LGTM)...")

    subprocess.run(
        ["docker", "rm", "-f", OTEL_CONTAINER_NAME],
        capture_output=True,
    )

    result = subprocess.run(
        [
            "docker", "run", "-d",
            "--name", OTEL_CONTAINER_NAME,
            "-p", f"{GRAFANA_PORT}:3000",  # Grafana UI
            "-p", "4317:4317",              # OTLP gRPC
            "-p", "4318:4318",              # OTLP HTTP
            OTEL_LGTM_IMAGE,
        ],
        capture_output=True, text=True,
    )

    if result.returncode != 0:
        console.print(
            f"[yellow]⚠ Warning:[/yellow] Could not start "
            f"observability stack: {result.stderr.strip()}"
        )
        return None

    container_id = result.stdout.strip()[:12]
    console.print(
        "[green]✓[/green] Grafana LGTM running — "
        f"UI: [bold]http://localhost:{GRAFANA_PORT}[/bold]"
    )
    return container_id


def stop_otel_stack() -> None:
    """Stop and remove the OTEL-LGTM container."""
    subprocess.run(
        ["docker", "rm", "-f", OTEL_CONTAINER_NAME],
        capture_output=True,
    )


def docker_run(
    project_dir: Path,
    agent_name: str,
    module_dir: str,
    port: int,
    trace: bool,
) -> None:
    """Build and run the agent container locally with ADK web UI."""
    image_tag = f"{agent_name}:latest"

    # Build
    console.print(f"→ Building Docker image [bold]{image_tag}[/bold]...")
    build_result = subprocess.run(
        ["docker", "build", "-t", image_tag, "."],
        cwd=str(project_dir),
    )
    if build_result.returncode != 0:
        console.print("[red]Error:[/red] Docker build failed.")
        raise SystemExit(1)

    console.print(f"[green]✓[/green] Image built: {image_tag}")

    # Start observability stack if tracing
    otel_started = False
    if trace:
        container_id = start_otel_stack()
        if container_id:
            otel_started = True
            atexit.register(stop_otel_stack)

    # Build docker run command
    container_name = f"zil-{agent_name}"
    run_cmd = [
        "docker", "run", "--rm",
        "-p", f"{port}:8000",
        "--name", container_name,
    ]

    # Pass env files if available
    for env_file in find_env_files(project_dir, module_dir):
        run_cmd.extend(["--env-file", str(env_file)])

    # Set OTLP endpoint and service name for tracing.
    # Grafana LGTM accepts traces, metrics, and logs on 4318.
    if trace and otel_started:
        run_cmd.extend([
            "-e", "OTEL_EXPORTER_OTLP_ENDPOINT="
                  "http://host.docker.internal:4318",
            "-e", f"OTEL_SERVICE_NAME={agent_name}",
        ])

    run_cmd.append(image_tag)

    # Override CMD to start the ADK web server.
    # Bind to 0.0.0.0 so Docker port-forwarding can reach it.
    run_cmd.extend([
        "python", "-c",
        (
            "import sys; "
            "sys.argv = ['adk', 'web', "
            "'.', '--port', '8000', '--host', '0.0.0.0']; "
            "from google.adk.cli import main; main()"
        ),
    ])

    console.print(
        f"\n[green]✓[/green] Agent running at "
        f"[bold]http://localhost:{port}[/bold]"
    )
    if trace and otel_started:
        console.print(
            f"  Grafana: [bold]http://localhost:{GRAFANA_PORT}[/bold]"
        )
    console.print("  Press Ctrl+C to stop.\n")

    # Run agent container (blocks until Ctrl+C)
    try:
        sys.exit(subprocess.call(run_cmd))
    except KeyboardInterrupt:
        console.print("\n→ Stopping containers...")
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            capture_output=True,
        )
        if otel_started:
            stop_otel_stack()
