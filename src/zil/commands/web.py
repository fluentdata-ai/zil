"""zil web — start the ADK web UI for the agent."""

import shutil
import subprocess
import sys
from pathlib import Path

import click
from rich.console import Console

console = Console()


@click.command()
@click.option(
    "--project-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=".",
    help="Project directory (default: current directory).",
)
@click.option(
    "--port",
    type=int,
    default=8000,
    help="Port for the web UI (default: 8000).",
)
@click.option(
    "--trace", "trace_mode",
    is_flag=True, default=False,
    help="Enable OTLP trace export.",
)
@click.option(
    "--trace-console", "trace_console",
    is_flag=True, default=False,
    help="Print spans to stderr (no collector needed).",
)
@click.option(
    "--docker", "docker_mode",
    is_flag=True, default=False,
    help="Build and run in a Docker container.",
)
def web(
    project_dir: Path, port: int, trace_mode: bool,
    trace_console: bool, docker_mode: bool,
) -> None:
    """Start the ADK web UI for the agent (wraps adk web)."""
    import os

    from zil.commands.run import _load_manifest, _resolve_module, _resolve_otlp_endpoint

    project_dir = project_dir.resolve()
    module_name = _resolve_module(project_dir)

    # Docker mode: build and run in container
    if docker_mode:
        from zil.commands._docker import check_docker, docker_run

        if not check_docker():
            raise SystemExit(1)
        docker_run(project_dir, module_name.replace("_", "-"), module_name, port, trace_mode)
        return

    if not shutil.which("adk"):
        console.print(
            "[red]Error:[/red] adk CLI not found. "
            "Install it with: [bold]pip install 'zil-ai\\[adk]'[/bold]"
        )
        raise SystemExit(1)

    module_dir = project_dir / module_name
    if not module_dir.is_dir():
        console.print(
            f"[red]Error:[/red] Agent module directory '{module_name}/' not found. "
            "Did you run [bold]zil init[/bold]?"
        )
        raise SystemExit(1)

    if trace_mode or trace_console:
        manifest = _load_manifest(project_dir)
        endpoint = _resolve_otlp_endpoint(project_dir, manifest)
        if endpoint:
            os.environ.setdefault("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", endpoint)
            console.print(f"[green]✓[/green] Tracing active — exporting to {endpoint}")
        elif trace_console:
            console.print(
                "[yellow]Note:[/yellow] --trace-console with `zil web` exports to OTLP. "
                "Use `zil run --trace-console` for stderr output."
            )
        else:
            console.print(
                "[yellow]Warning:[/yellow] Tracing endpoint not configured. "
                "Set OTEL_EXPORTER_OTLP_TRACES_ENDPOINT in your .env file."
            )

    console.print(f"Starting ADK web UI on http://localhost:{port}")
    sys.exit(
        subprocess.call(
            ["adk", "web", "--port", str(port)],
            cwd=str(project_dir),
        )
    )
