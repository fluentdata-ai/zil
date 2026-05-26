"""zil run — run the agent interactively via the framework backend."""

import os
from pathlib import Path
from typing import Any

import click
from rich.console import Console

console = Console()


def _resolve_module(project_dir: Path) -> str:
    """Derive the agent module name from the manifest."""
    import yaml

    manifest_path = project_dir / "manifest.yaml"
    if not manifest_path.is_file():
        console.print("[red]Error:[/red] manifest.yaml not found in the current directory.")
        raise SystemExit(1)

    with open(manifest_path, encoding="utf-8") as f:
        manifest = yaml.safe_load(f)

    name = manifest.get("metadata", {}).get("name", "")
    if not name:
        console.print("[red]Error:[/red] metadata.name is missing in manifest.yaml.")
        raise SystemExit(1)

    return name.replace("-", "_")


def _load_manifest(project_dir: Path) -> dict[str, Any]:
    """Load the full manifest dict."""
    import yaml

    with open(project_dir / "manifest.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _resolve_otlp_endpoint(project_dir: Path, manifest: dict[str, Any]) -> str | None:
    """Resolve the OTLP endpoint from observability config, return the URL or None."""
    import yaml

    from zil.sdk.telemetry import _resolve_env_refs

    obs_ref = manifest.get("spec", {}).get("observability")
    if not obs_ref:
        return None

    obs_path = project_dir / obs_ref / "config.yaml"
    if not obs_path.is_file():
        return None

    with open(obs_path, encoding="utf-8") as f:
        obs_config = yaml.safe_load(f) or {}

    endpoint = obs_config.get("observability", {}).get("tracing", {}).get("endpoint", "")
    if not endpoint:
        return None

    return _resolve_env_refs(endpoint) or None


def _resolve_framework(project_dir: Path) -> str:
    """Read the runtime.framework value from the manifest."""
    manifest = _load_manifest(project_dir)
    return manifest.get("spec", {}).get("runtime", {}).get("framework", "adk")


@click.command()
@click.option(
    "--project-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=".",
    help="Project directory (default: current directory).",
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
def run(project_dir: Path, trace_mode: bool, trace_console: bool) -> None:
    """Run the agent interactively via the framework backend."""
    from zil.sdk.frameworks import registry

    project_dir = project_dir.resolve()
    module_name = _resolve_module(project_dir)
    framework = _resolve_framework(project_dir)
    backend = registry.get(framework)

    module_dir = project_dir / module_name
    if not module_dir.is_dir():
        console.print(
            f"[red]Error:[/red] Agent module directory '{module_name}/' not found. "
            "Did you run [bold]zil init[/bold]?"
        )
        raise SystemExit(1)

    # --trace-console: run in-process so our TracerProvider is active
    if trace_console:
        from zil.sdk.telemetry import setup_console_telemetry

        manifest = _load_manifest(project_dir)
        agent_name = manifest.get("metadata", {}).get("name", "")
        agent_version = manifest.get("metadata", {}).get("version", "")

        ok = setup_console_telemetry(agent_name=agent_name, agent_version=agent_version)
        if ok:
            console.print("[green]✓[/green] Console tracing active — spans printed to stderr.")

    # --trace: set OTLP env var so framework subprocess picks it up
    if trace_mode:
        manifest = _load_manifest(project_dir)
        endpoint = _resolve_otlp_endpoint(project_dir, manifest)
        if endpoint:
            os.environ.setdefault("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", endpoint)
            console.print(f"[green]✓[/green] Tracing active — exporting to {endpoint}")
        else:
            console.print(
                "[yellow]Warning:[/yellow] Tracing endpoint not configured. "
                "Set OTEL_EXPORTER_OTLP_TRACES_ENDPOINT in your .env file."
            )

    # Dispatch to backend
    backend.run_local(
        agent=None,  # Agent object not needed for CLI-level run
        mode="interactive",
        project_dir=project_dir,
        module_name=module_name,
        trace_mode=trace_mode,
        trace_console=trace_console,
    )
