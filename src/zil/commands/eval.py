"""zil eval — evaluation subcommands (run, add, record, generate)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from zil.sdk.eval.models import CaseVerdict, SuiteResult

console = Console()


@click.group()
def eval() -> None:
    """Agent evaluation — run suites, add cases, record sessions, generate tests."""


@eval.command()
@click.option(
    "--project-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=".",
    help="Project directory (default: current directory).",
)
@click.option(
    "--suite",
    default="baseline",
    help="Suite to run (default: baseline).",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    help="Show per-case details.",
)
@click.option(
    "--json-output", "json_out",
    is_flag=True,
    help="Output results as JSON (for CI).",
)
@click.option(
    "--threshold",
    type=float,
    default=None,
    help="Override pass threshold.",
)
def run(
    project_dir: Path,
    suite: str,
    verbose: bool,
    json_out: bool,
    threshold: float | None,
) -> None:
    """Run the evaluation suite against the agent."""
    from zil.sdk.eval.runner import run_eval_suite

    project_dir = project_dir.resolve()

    # Load .env files from project and module directories
    _load_env(project_dir)

    if not json_out:
        console.print(f"→ Running eval suite [bold]{suite}[/bold]...\n")

    try:
        result = run_eval_suite(
            project_dir,
            suite_name=suite,
            threshold_override=threshold,
        )
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)
    except ImportError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)

    if json_out:
        _print_json(result)
    else:
        _print_rich(result, verbose)

    if not result.passed:
        raise SystemExit(1)


def _print_rich(result: SuiteResult, verbose: bool) -> None:
    """Print results using Rich formatting."""
    # Summary table
    table = Table(title=f"Eval Suite: {result.suite_name}")
    table.add_column("Group", style="cyan")
    table.add_column("Pass Rate", justify="right")
    table.add_column("Weight", justify="right")
    table.add_column("Cases", justify="right")

    for group in result.group_results:
        passed = sum(
            1 for c in group.case_results if c.verdict == CaseVerdict.PASS
        )
        total = len(group.case_results)
        rate_pct = f"{group.pass_rate * 100:.1f}%"
        rate_style = "green" if group.pass_rate >= result.threshold else "red"
        table.add_row(
            group.name,
            f"[{rate_style}]{rate_pct}[/{rate_style}]",
            f"{group.weight:.2f}",
            f"{passed}/{total}",
        )

    console.print(table)
    console.print()

    # Verbose: per-case details
    if verbose:
        for group in result.group_results:
            console.print(f"[bold]{group.name}[/bold]")
            for cr in group.case_results:
                icon = "✓" if cr.verdict == CaseVerdict.PASS else "✗"
                color = "green" if cr.verdict == CaseVerdict.PASS else "red"
                input_preview = (
                    cr.case.input[:60] + "..."
                    if len(cr.case.input) > 60
                    else cr.case.input
                )
                console.print(f"  [{color}]{icon}[/{color}] {input_preview}")
                if cr.error:
                    console.print(f"    [dim]Error: {cr.error}[/dim]")
                if cr.metric_scores:
                    scores_str = ", ".join(
                        f"{k}: {v:.2f}" for k, v in cr.metric_scores.items()
                    )
                    console.print(f"    [dim]{scores_str}[/dim]")
            console.print()

    # Final verdict
    score_pct = f"{result.score * 100:.1f}%"
    threshold_pct = f"{result.threshold * 100:.1f}%"

    if result.passed:
        console.print(
            f"[green]✓ Suite passed:[/green] {score_pct} "
            f"(threshold: {threshold_pct})"
        )
    else:
        console.print(
            f"[red]✗ Suite failed:[/red] {score_pct} "
            f"(threshold: {threshold_pct})"
        )

    console.print(
        f"  {result.passed_cases} passed, "
        f"{result.failed_cases} failed, "
        f"{result.total_cases} total"
    )


def _print_json(result: SuiteResult) -> None:
    """Print results as JSON for CI consumption."""
    output = {
        "suite": result.suite_name,
        "score": round(result.score, 4),
        "passed": result.passed,
        "threshold": result.threshold,
        "total_cases": result.total_cases,
        "passed_cases": result.passed_cases,
        "failed_cases": result.failed_cases,
        "groups": [
            {
                "name": g.name,
                "pass_rate": round(g.pass_rate, 4),
                "weight": g.weight,
                "cases": [
                    {
                        "input": cr.case.input,
                        "verdict": cr.verdict.value,
                        "score": round(cr.score, 4),
                        "actual_output": cr.actual_output[:200],
                        "error": cr.error,
                        "metric_scores": {
                            k: round(v, 4)
                            for k, v in cr.metric_scores.items()
                        },
                    }
                    for cr in g.case_results
                ],
            }
            for g in result.group_results
        ],
    }
    click.echo(json.dumps(output, indent=2))


# ---------------------------------------------------------------------------
# zil eval add
# ---------------------------------------------------------------------------

@eval.command()
@click.option(
    "--project-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=".",
    help="Project directory (default: current directory).",
)
@click.option(
    "--group",
    default="accuracy",
    help="Target case group name (default: accuracy).",
)
@click.option(
    "--suite",
    default="baseline",
    help="Suite to register the group in (default: baseline).",
)
def add(project_dir: Path, group: str, suite: str) -> None:
    """Interactively create eval cases by chatting with the agent."""
    from zil.sdk.eval.models import EvalCase
    from zil.sdk.eval.runner import _build_default_agent_fn
    from zil.sdk.eval.writer import append_case_to_group, register_group_in_suite

    project_dir = project_dir.resolve()
    _load_env(project_dir)

    evals_dir = project_dir / "evals"
    group_file = f"cases/{group}.yaml"

    try:
        invoke = _build_default_agent_fn(project_dir)
    except ImportError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)

    console.print(
        f"[bold]Interactive case builder[/bold] → group [cyan]{group}[/cyan]\n"
        "Type a message to send to the agent. Ctrl+C to stop.\n"
    )

    count = 0
    while True:
        try:
            user_input = click.prompt("You", type=str)
        except (click.Abort, EOFError, KeyboardInterrupt):
            break

        console.print("[dim]Running agent...[/dim]")
        try:
            response = invoke(user_input)
        except Exception as e:
            console.print(f"[red]Agent error:[/red] {e}")
            continue

        console.print(f"\n[bold green]Agent:[/bold green] {response}\n")

        should_pass = click.confirm("Should this response pass?", default=True)

        keywords_str = click.prompt(
            "Expected keywords (comma-separated, or empty)",
            default="",
            show_default=False,
        )
        keywords = [k.strip() for k in keywords_str.split(",") if k.strip()]

        metrics_str = click.prompt(
            "Metrics (comma-separated, e.g. answer_relevancy, or empty for deterministic-only)",
            default="",
            show_default=False,
        )
        metrics = [m.strip() for m in metrics_str.split(",") if m.strip()]

        case = EvalCase(
            input=user_input,
            expected_output=response if should_pass else None,
            expected_contains=keywords,
            metrics=metrics,
        )

        append_case_to_group(evals_dir, group_file, group, case)
        register_group_in_suite(evals_dir, suite, group_file)
        count += 1
        console.print(f"[green]✓ Case saved[/green] ({count} total)\n")

        if not click.confirm("Add another?", default=True):
            break

    console.print(f"\n[bold]{count} case(s)[/bold] saved to [cyan]{group_file}[/cyan]")


# ---------------------------------------------------------------------------
# zil eval record
# ---------------------------------------------------------------------------

@eval.command()
@click.option(
    "--project-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=".",
    help="Project directory (default: current directory).",
)
@click.option("--group", default="recorded", help="Target case group name (default: recorded).")
@click.option("--suite", default="baseline", help="Suite to register the group in.")
@click.option("--auto-accept", is_flag=True, help="Save all turns without per-turn confirmation.")
def record(project_dir: Path, group: str, suite: str, auto_accept: bool) -> None:
    """Record a chat session with the agent and convert turns into eval cases."""
    from zil.sdk.eval.models import EvalCase
    from zil.sdk.eval.runner import _build_default_agent_fn
    from zil.sdk.eval.writer import append_case_to_group, register_group_in_suite

    project_dir = project_dir.resolve()
    _load_env(project_dir)

    evals_dir = project_dir / "evals"
    group_file = f"cases/{group}.yaml"

    try:
        invoke = _build_default_agent_fn(project_dir)
    except ImportError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)

    console.print(
        "[bold]Recording session[/bold] — chat with your agent.\n"
        "Type [cyan]/done[/cyan] or press Ctrl+D to finish.\n"
    )

    transcript: list[tuple[str, str]] = []
    while True:
        try:
            user_input = click.prompt("You", type=str)
        except (click.Abort, EOFError, KeyboardInterrupt):
            break
        if user_input.strip().lower() == "/done":
            break

        console.print("[dim]Running agent...[/dim]")
        try:
            response = invoke(user_input)
        except Exception as e:
            console.print(f"[red]Agent error:[/red] {e}")
            continue

        console.print(f"[bold green]Agent:[/bold green] {response}\n")
        transcript.append((user_input, response))

    if not transcript:
        console.print("[yellow]No turns recorded.[/yellow]")
        return

    console.print(f"\n[bold]Recorded {len(transcript)} turn(s).[/bold] Reviewing...\n")

    saved = 0
    for i, (user_msg, agent_resp) in enumerate(transcript):
        console.print(f"  [bold]{i + 1}.[/bold] You: {user_msg}")
        preview = agent_resp[:120] + "..." if len(agent_resp) > 120 else agent_resp
        console.print(f"     Agent: {preview}")

        include = auto_accept or click.confirm("     Include as eval case?", default=True)
        if not include:
            console.print()
            continue

        # Extract keywords from the response for expected_contains
        keywords = _extract_keywords(agent_resp)
        if keywords and not auto_accept:
            console.print(f"     [dim]Auto-detected keywords: {', '.join(keywords)}[/dim]")
            edit_kw = click.prompt(
                "     Edit keywords (comma-separated, or Enter to keep)",
                default=", ".join(keywords),
                show_default=False,
            )
            keywords = [k.strip() for k in edit_kw.split(",") if k.strip()]

        case = EvalCase(
            input=user_msg,
            expected_output=agent_resp,
            expected_contains=keywords,
        )
        append_case_to_group(evals_dir, group_file, group, case)
        saved += 1
        console.print()

    if saved > 0:
        register_group_in_suite(evals_dir, suite, group_file)
    console.print(f"[green]✓ {saved} case(s)[/green] saved to [cyan]{group_file}[/cyan]")


def _extract_keywords(text: str, max_keywords: int = 3) -> list[str]:
    """Extract meaningful keywords from agent response text."""
    import re

    # Remove markdown formatting
    clean = re.sub(r"[*_`#\[\]()]", "", text)
    # Split into words, filter short/common words
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "can", "shall", "to", "of", "in", "for",
        "on", "with", "at", "by", "from", "as", "into", "through", "during",
        "before", "after", "above", "below", "between", "and", "but", "or",
        "not", "no", "nor", "so", "yet", "both", "either", "neither", "each",
        "every", "all", "any", "few", "more", "most", "other", "some", "such",
        "than", "too", "very", "just", "about", "also", "then", "that", "this",
        "it", "its", "i", "you", "we", "they", "he", "she", "my", "your",
        "our", "their", "me", "him", "her", "us", "them", "if", "when",
        "where", "how", "what", "which", "who", "whom", "why",
    }
    words = re.findall(r"\b[a-zA-Z]{3,}\b", clean.lower())
    # Count frequency, skip stop words
    freq: dict[str, int] = {}
    for w in words:
        if w not in stop_words:
            freq[w] = freq.get(w, 0) + 1
    # Return top N by frequency
    sorted_words = sorted(freq.items(), key=lambda x: (-x[1], x[0]))
    return [w for w, _ in sorted_words[:max_keywords]]


# ---------------------------------------------------------------------------
# zil eval generate
# ---------------------------------------------------------------------------

@eval.command()
@click.option(
    "--project-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=".",
    help="Project directory (default: current directory).",
)
@click.option("--count", "-n", default=10, help="Number of cases to generate (default: 10).")
@click.option("--group", default="generated", help="Target case group name (default: generated).")
@click.option("--suite", default="baseline", help="Suite to register the group in.")
@click.option(
    "--category", default=None,
    help="Focus area (e.g. accuracy, guardrails, edge-cases).",
)
@click.option("--no-review", is_flag=True, help="Save all generated cases without review.")
def generate(
    project_dir: Path,
    count: int,
    group: str,
    suite: str,
    category: str | None,
    no_review: bool,
) -> None:
    """Use the judge LLM to synthesize eval cases from agent identity."""
    from zil.sdk.eval.generator import generate_cases
    from zil.sdk.eval.loader import load_eval_engine_config
    from zil.sdk.eval.writer import append_case_to_group, register_group_in_suite

    project_dir = project_dir.resolve()
    _load_env(project_dir)

    engine_config = load_eval_engine_config(project_dir)
    evals_dir = project_dir / "evals"
    group_file = f"cases/{group}.yaml"

    console.print(
        f"[bold]Generating {count} eval cases[/bold] "
        f"using [cyan]{engine_config.judge.provider}/{engine_config.judge.model}[/cyan]...\n"
    )

    try:
        cases = generate_cases(
            project_dir, engine_config, count=count, category=category,
        )
    except Exception as e:
        console.print(f"[red]Error generating cases:[/red] {e}")
        raise SystemExit(1)

    if not cases:
        console.print("[yellow]No cases generated.[/yellow]")
        return

    console.print(f"[green]Generated {len(cases)} cases:[/green]\n")

    accepted: list[int] = []
    for i, case in enumerate(cases):
        console.print(f"  [bold]{i + 1}.[/bold] {case.input}")
        if case.expected_contains:
            console.print(f"     [dim]expects: {', '.join(case.expected_contains)}[/dim]")
        if case.metrics:
            console.print(f"     [dim]metrics: {', '.join(case.metrics)}[/dim]")

        if no_review:
            accepted.append(i)
        else:
            if click.confirm("     Accept this case?", default=True):
                accepted.append(i)
        console.print()

    if not accepted:
        console.print("[yellow]No cases accepted.[/yellow]")
        return

    for i in accepted:
        append_case_to_group(evals_dir, group_file, group, cases[i])

    register_group_in_suite(evals_dir, suite, group_file)
    console.print(
        f"[green]✓ {len(accepted)} case(s)[/green] saved to [cyan]{group_file}[/cyan]"
    )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _load_env(project_dir: Path) -> None:
    """Load .env files from the project directory tree."""
    # Check project root .env
    env_file = project_dir / ".env"
    if env_file.is_file():
        _parse_env_file(env_file)

    # Check module subdirectories (e.g., qbo_revrec/.env)
    for child in project_dir.iterdir():
        if child.is_dir() and (child / ".env").is_file():
            _parse_env_file(child / ".env")


def _parse_env_file(path: Path) -> None:
    """Parse a .env file and set variables that aren't already set."""
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)
