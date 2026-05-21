"""Template rendering for zil init."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console

if TYPE_CHECKING:
    from zil.commands.init import InitConfig

console = Console()


def render_project(project_dir: Path, config: InitConfig) -> None:
    """Render all template files into the project directory."""
    from zil.templates.files import TEMPLATE_FILES

    project_dir.mkdir(parents=True)

    for path_or_fn, renderer in TEMPLATE_FILES:
        rel_path = path_or_fn(config) if callable(path_or_fn) else path_or_fn
        target = project_dir / rel_path

        # Skip conditional files
        if rel_path.startswith("evals/") and not config.include_evals:
            continue
        if rel_path.startswith("observability/") and not config.include_otel:
            continue
        if rel_path == "__multi_agent_skip__":
            continue
        if rel_path.startswith("agents/__placeholder__"):
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        content = renderer(config)
        target.write_text(content)
        console.print(f"  [green]\u2713[/green] Created {rel_path}")

    # Render extra files (multi-agent identity dirs, webhook app.py/runner.py)
    from zil.templates.files import _render_extra_files
    _render_extra_files(project_dir, config)

    # Init git only if we're not already inside a git repo
    import subprocess

    inside_git = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=project_dir,
        capture_output=True,
        text=True,
    ).returncode == 0

    if not inside_git:
        subprocess.run(["git", "init", "-q"], cwd=project_dir, check=True)
        console.print("  [green]✓[/green] Initialized git")
    else:
        console.print("  [dim]–[/dim] Skipped git init (already inside a git repo)")
