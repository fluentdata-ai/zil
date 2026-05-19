"""zil init — scaffold a new agent project."""

import subprocess
import sys
from pathlib import Path

import click
from rich.console import Console

console = Console()


LLM_PROVIDERS = ["gemini", "anthropic", "openai", "vertex"]
MCP_PRESETS = ["none", "filesystem", "git", "custom"]


@click.command()
@click.argument("name")
@click.option(
    "--llm",
    "llm_provider",
    type=click.Choice(LLM_PROVIDERS, case_sensitive=False),
    default=None,
    help="LLM provider (default: gemini).",
)
@click.option("--no-evals", is_flag=True, help="Skip eval suite scaffolding.")
@click.option("--no-otel", is_flag=True, help="Skip OpenTelemetry instrumentation.")
@click.option(
    "--mcp",
    "mcp_preset",
    type=click.Choice(MCP_PRESETS, case_sensitive=False),
    default=None,
    help="Include MCP server scaffolding (default: none).",
)
@click.option(
    "--non-interactive",
    is_flag=True,
    help="Use defaults for all prompts.",
)
def init(
    name: str,
    llm_provider: str | None,
    no_evals: bool,
    no_otel: bool,
    mcp_preset: str | None,
    non_interactive: bool,
) -> None:
    """Scaffold a new Zil agent project.

    Creates a working agent project with manifest, identity, adapters,
    eval suite, and deployment config.
    """
    project_dir = Path.cwd() / name

    if project_dir.exists():
        console.print(f"[red]Error:[/red] Directory '{name}' already exists.")
        raise SystemExit(1)

    # Resolve options — prompt interactively or use defaults
    llm_provider = llm_provider or _resolve(
        "LLM provider", LLM_PROVIDERS, "gemini", non_interactive
    )
    mcp_preset = mcp_preset or _resolve(
        "MCP servers", MCP_PRESETS, "none", non_interactive
    )

    include_evals = not no_evals
    include_otel = not no_otel

    config = InitConfig(
        name=name,
        framework="adk",
        language="python",
        llm_provider=llm_provider,
        eval_framework="deepeval",
        deploy_target="cloud-run",
        include_evals=include_evals,
        include_otel=include_otel,
        mcp_preset=mcp_preset if mcp_preset != "none" else None,
    )

    console.print()
    _scaffold(project_dir, config)
    console.print()

    _install_deps(project_dir, non_interactive)

    console.print()
    console.print("[green]Done![/green] Your agent is ready.")
    console.print(f"\n  cd {name}")
    console.print("  source .venv/bin/activate")
    console.print("  zil validate")
    console.print()


def _resolve(label: str, choices: list[str], default: str, non_interactive: bool) -> str:
    """Prompt the user or return the default."""
    if non_interactive:
        return default
    choice_str = " / ".join(
        f"[bold]{c}[/bold]" if c == default else c for c in choices
    )
    result = console.input(f"  ? {label} ({choice_str}): ").strip().lower()
    return result if result in choices else default


class InitConfig:
    """Holds resolved configuration for project scaffolding."""

    def __init__(
        self,
        name: str,
        framework: str,
        language: str,
        llm_provider: str,
        eval_framework: str,
        deploy_target: str,
        include_evals: bool,
        include_otel: bool,
        mcp_preset: str | None = None,
    ) -> None:
        self.name = name
        self.framework = framework
        self.language = language
        self.llm_provider = llm_provider
        self.eval_framework = eval_framework
        self.deploy_target = deploy_target
        self.include_evals = include_evals
        self.include_otel = include_otel
        self.mcp_preset = mcp_preset

    @property
    def module_name(self) -> str:
        """Agent name as a valid Python identifier (for ADK module dir)."""
        return self.name.replace("-", "_")


def _scaffold(project_dir: Path, config: InitConfig) -> None:
    """Create the project directory tree and write all template files."""
    from zil.templates import render_project

    render_project(project_dir, config)


def _install_deps(project_dir: Path, non_interactive: bool) -> None:
    """Create a venv and install requirements.txt."""
    requirements = project_dir / "requirements.txt"
    if not requirements.is_file():
        return

    if not non_interactive:
        answer = console.input(
            "  ? Install dependencies now? ([bold]yes[/bold] / no): "
        ).strip().lower()
        if answer in ("no", "n"):
            console.print("  Skipped. Run [bold]pip install -r requirements.txt[/bold] later.")
            return

    venv_dir = project_dir / ".venv"
    console.print("  Creating virtual environment...")
    subprocess.run(
        [sys.executable, "-m", "venv", str(venv_dir)],
        check=True,
        capture_output=True,
    )

    pip = venv_dir / "bin" / "pip"
    if not pip.exists():
        pip = venv_dir / "Scripts" / "pip.exe"  # Windows

    console.print("  Installing dependencies...")
    result = subprocess.run(
        [str(pip), "install", "-r", str(requirements), "--quiet"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        console.print("  [green]✓[/green] Dependencies installed.")
    else:
        console.print("  [yellow]⚠[/yellow] Dependency install failed. Run manually:")
        console.print(f"    cd {project_dir.name} && pip install -r requirements.txt")
        if result.stderr:
            console.print(f"    {result.stderr.strip()[:200]}")

