"""zil web — start the web UI for the agent via the framework backend."""

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
    """Start the web UI for the agent via the framework backend.

    .. deprecated::
        Use ``zil serve`` instead. ``zil web`` will be removed in a future release.
    """
    import os

    console.print(
        "[yellow]⚠ Deprecation:[/yellow] 'zil web' is deprecated. "
        "Use [bold]zil serve[/bold] instead (with --docker for containerized runs)."
    )

    from zil.commands.run import (
        _load_manifest,
        _resolve_framework,
        _resolve_module,
        _resolve_otlp_endpoint,
    )
    from zil.sdk.frameworks import registry

    project_dir = project_dir.resolve()
    module_name = _resolve_module(project_dir)
    framework = _resolve_framework(project_dir)
    backend = registry.get(framework)

    # Docker mode: build and run in container
    if docker_mode:
        from zil.commands._docker import check_docker, docker_run

        if not check_docker():
            raise SystemExit(1)
        docker_run(project_dir, module_name.replace("_", "-"), module_name, port, trace_mode)
        return

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

    # Dispatch to backend with web mode
    backend.run_local(
        agent=None,
        mode="web",
        project_dir=project_dir,
        module_name=module_name,
        port=port,
        trace_mode=trace_mode,
        trace_console=trace_console,
    )
