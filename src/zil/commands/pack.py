"""zil pack — build a .zil archive."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click
import yaml
from rich.console import Console

console = Console()


def _check_env_coverage(
    project_dir: Path,
    manifest: dict[str, Any],
) -> dict[str, Any] | None:
    """Cross-check .env/.env.local vars against spec.env declarations.

    Returns an env_coverage dict for BUILD_META, or None if no spec.env.
    Prints warnings for missing vars, raises SystemExit for undeclared usage.
    """
    from zil.sdk.config import _parse_dotenv

    declarations = manifest.get("spec", {}).get("env", [])
    if not declarations:
        return None

    declared_names = {d["name"] for d in declarations if d.get("name")}

    # Scan .env and .env.local from project root + module dir
    module_name = manifest["metadata"]["name"].replace("-", "_")
    module_dir = project_dir / module_name

    env_file_vars: dict[str, str] = {}
    search_dirs = [project_dir]
    if module_dir.is_dir() and module_dir != project_dir:
        search_dirs.append(module_dir)

    for directory in search_dirs:
        for filename in (".env", ".env.local"):
            env_path = directory / filename
            if env_path.is_file():
                env_file_vars.update(_parse_dotenv(env_path))

    env_file_keys = set(env_file_vars.keys())

    # Undeclared vars in env files → FAIL (config drift)
    undeclared = env_file_keys - declared_names
    if undeclared:
        for var in sorted(undeclared):
            console.print(
                f"  [red]✗[/red] '{var}' in .env file but not declared in spec.env"
            )
        console.print(
            "[red]Error:[/red] Env files contain undeclared variables. "
            "Add them to spec.env or remove from .env files."
        )
        raise SystemExit(1)

    # Declared vars missing from env files → WARN
    resolved_locally = declared_names & env_file_keys
    missing_locally = declared_names - env_file_keys
    for var in sorted(missing_locally):
        console.print(
            f"  [yellow]⚠[/yellow] '{var}' declared in spec.env "
            f"but not found in local .env files"
        )

    count = len(declared_names)
    resolved = len(resolved_locally)
    console.print(
        f"[green]✓[/green] {resolved}/{count} env var(s) resolved locally"
    )

    return {
        "declared": sorted(declared_names),
        "resolved_locally": sorted(resolved_locally),
        "missing_locally": sorted(missing_locally),
    }


@click.command()
@click.option(
    "--project-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=".",
    help="Project directory to package (default: current directory).",
)
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Output directory for the .zil archive (default: dist/).",
)
@click.option("--skip-evals", is_flag=True, help="Skip eval suite (warns loudly).")
@click.option("--sign", is_flag=True, help="Sign the archive with cosign after building.")
@click.option(
    "--key",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Path to cosign private key for signing (default: keyless/OIDC).",
)
def pack(
    project_dir: Path,
    output_dir: Path | None,
    skip_evals: bool,
    sign: bool,
    key: Path | None,
) -> None:
    """Build a .zil archive from a Zil agent project.

    Validates the project, runs the eval suite, generates an SBOM,
    creates a tar.gz archive, and writes it to dist/.
    """
    project_dir = project_dir.resolve()
    out = output_dir or (project_dir / "dist")

    if skip_evals:
        console.print("[bold yellow]⚠ --skip-evals: eval suite will NOT run. "
                       "Do not ship this archive to production.[/bold yellow]")

    # --- Validate ---
    console.print("→ Validating project...", end="  ")
    from zil.schema.loader import validate_project

    validation = validate_project(project_dir)
    if validation.exit_code == 1:
        console.print("[red]✗[/red]")
        for check in validation.checks:
            if check.status == "fail":
                console.print(f"  [red]✗[/red] {check.message}")
        console.print("[red]Error:[/red] Project validation failed.")
        raise SystemExit(1)
    console.print("[green]✓[/green]")

    # --- Load manifest for metadata ---
    manifest_path = project_dir / "manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text())
    name = manifest["metadata"]["name"]
    version = manifest["metadata"]["version"]

    # --- Env cross-check ---
    console.print("→ Checking env coverage...", end="  ")
    env_coverage = _check_env_coverage(project_dir, manifest)
    if env_coverage is None:
        console.print("[yellow]⚠ no spec.env declared[/yellow]")

    # --- Evals ---
    eval_results = None
    if not skip_evals:
        console.print("→ Running pre-flight evals...", end="  ")
        try:
            from zil.sdk.eval.runner import run_eval_suite

            result = run_eval_suite(project_dir)
            if result.passed:
                score_pct = f"{result.score * 100:.1f}%"
                console.print(f"[green]✓ {score_pct}[/green]")
                eval_results = {
                    "score": result.score,
                    "threshold": result.threshold,
                    "passed": True,
                }
            else:
                score_pct = f"{result.score * 100:.1f}%"
                threshold_pct = f"{result.threshold * 100:.1f}%"
                console.print(
                    f"[red]✗ {score_pct} (threshold: {threshold_pct})[/red]"
                )
                console.print(
                    "[red]Error:[/red] Eval suite failed. "
                    "Fix eval failures before packaging."
                )
                raise SystemExit(1)
        except SystemExit:
            raise
        except FileNotFoundError:
            console.print("[yellow]⚠ no eval suite found, skipping[/yellow]")
        except ImportError as e:
            console.print(f"[yellow]⚠ {e}[/yellow]")

    # --- SBOM ---
    console.print("→ Generating SBOM (CycloneDX)...", end="  ")
    from zil.packaging.sbom import generate_sbom

    sbom = generate_sbom(project_dir, name, version)
    dep_count = len(sbom.get("components", []))
    console.print(f"[green]✓[/green] {dep_count} dependencies")

    # --- Build archive ---
    console.print("→ Building archive...", end="  ")
    from zil.packaging.archive import build_archive

    archive_path = build_archive(
        project_dir=project_dir,
        output_dir=out,
        sbom=sbom,
        eval_results=eval_results,
        env_coverage=env_coverage,
    )
    size_bytes = archive_path.stat().st_size
    if size_bytes < 1024 * 1024:
        size_str = f"{size_bytes / 1024:.1f} KB"
    else:
        size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
    console.print("[green]✓[/green]")

    console.print(f"\n→ Wrote: [bold]{archive_path}[/bold] ({size_str})")

    # --- Signing ---
    if sign:
        console.print("\n→ Signing archive with cosign...", end="  ")
        from zil.packaging.signing import sign_archive

        sign_result = sign_archive(archive_path, key_path=key)
        if sign_result.signed:
            console.print("[green]✓[/green]")
            if sign_result.signature_path:
                console.print(f"  Signature: {sign_result.signature_path}")
            if sign_result.certificate_path:
                console.print(f"  Certificate: {sign_result.certificate_path}")
            if sign_result.signer_identity:
                console.print(f"  Signer: {sign_result.signer_identity}")
            console.print(f"  Type: {sign_result.signature_type}")
        else:
            console.print("[red]✗[/red]")
            console.print(f"[red]Error:[/red] {sign_result.error}")
            raise SystemExit(1)
