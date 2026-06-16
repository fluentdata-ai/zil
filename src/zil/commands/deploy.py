"""zil deploy — deploy the agent to Cloud Run."""

import json
import os
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click
import yaml
from rich.console import Console
from rich.prompt import Prompt

console = Console()  # Rich output (captured by CliRunner in tests)


def _resolve_module(project_dir: Path) -> str:
    """Derive the ADK module name from the manifest."""
    manifest_path = project_dir / "manifest.yaml"
    if not manifest_path.is_file():
        console.print(
            "[red]Error:[/red] manifest.yaml not found."
        )
        raise SystemExit(1)

    with open(manifest_path, encoding="utf-8") as f:
        manifest = yaml.safe_load(f)

    name = manifest.get("metadata", {}).get("name", "")
    if not name:
        console.print(
            "[red]Error:[/red] metadata.name is missing in manifest.yaml."
        )
        raise SystemExit(1)

    return name


def _resolve_module_dir(project_dir: Path, agent_name: str) -> str:
    """Get the Python module directory name (snake_case)."""
    return agent_name.replace("-", "_")


def _check_gcloud() -> bool:
    """Check if gcloud CLI is available."""
    if not shutil.which("gcloud"):
        console.print(
            "[red]Error:[/red] gcloud CLI not found. "
            "Install it: https://cloud.google.com/sdk/docs/install"
        )
        return False
    return True


def _resolve_gcp_project(project_flag: str | None) -> str | None:
    """Resolve GCP project from flag → env → gcloud config."""
    if project_flag:
        return project_flag

    env_project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if env_project:
        return env_project

    try:
        result = subprocess.run(
            ["gcloud", "config", "get-value", "project"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return None


def _resolve_gcp_region(region_flag: str | None) -> str | None:
    """Resolve GCP region from flag → env."""
    if region_flag:
        return region_flag

    env_region = os.environ.get("GOOGLE_CLOUD_REGION")
    if env_region:
        return env_region

    return None


def _run_eval_gate(project_dir: Path) -> None:
    """Run evals and block deploy on failure."""
    try:
        from zil.sdk.eval import run_eval_suite

        console.print("→ Running pre-deploy eval check...")
        result = run_eval_suite(project_dir=project_dir)
        if not result.passed:
            console.print(
                f"[red]✗[/red] Eval suite failed: "
                f"{result.score:.1%} (threshold: {result.threshold:.1%}). "
                "Deploy blocked. Use [bold]--skip-evals[/bold] to override."
            )
            raise SystemExit(1)
        console.print(
            f"[green]✓[/green] Evals passed: {result.score:.1%}"
        )
    except SystemExit:
        raise
    except Exception as e:
        console.print(
            f"[yellow]⚠ Warning:[/yellow] Could not run evals: {e}. "
            "Proceeding with deploy."
        )


def _resolve_env_vars(
    manifest: dict[str, Any],
    env_file: Path | None,
) -> dict[str, str]:
    """Resolve env var values from --env-file or interactive prompts.

    Returns a dict of {VAR_NAME: value} containing every entry from the env
    file (so platform-injected infra vars like ZIL_FLEET_REGISTRY_URL are
    forwarded) plus all declared spec.env vars resolved via defaults,
    os.environ, or interactive prompts.
    """
    env_declarations: list[dict[str, Any]] = (
        manifest.get("spec", {}).get("env") or []
    )

    # Load values from env file if provided
    file_values: dict[str, str] = {}
    if env_file:
        if not env_file.is_file():
            console.print(
                f"[red]Error:[/red] Env file not found: {env_file}"
            )
            raise SystemExit(1)
        file_values = _parse_env_file(env_file)

    # Forward every value present in the env file. Platform-injected infra vars
    # (e.g. ZIL_FLEET_REGISTRY_URL / ZIL_FLEET_REGISTRY_TOKEN for registry
    # discovery) are written to --env-file by the runtime but are intentionally
    # not declared in user manifests, so resolving only spec.env would drop
    # them. Declared-var resolution (defaults / os.environ / prompts /
    # required-checks) is layered on top below.
    resolved: dict[str, str] = dict(file_values)

    if not env_declarations:
        return resolved

    missing_required: list[str] = []

    for decl in env_declarations:
        name = decl.get("name", "")
        if not name:
            continue
        required = decl.get("required", True)
        default = decl.get("default")
        is_secret = decl.get("secret", False)
        description = decl.get("description", "")

        # Resolution order: env file → os.environ → interactive prompt
        value = file_values.get(name)

        if value is None:
            value = os.environ.get(name)

        if value is None and not env_file:
            # Interactive prompt
            prompt_text = f"  {name}"
            if description:
                prompt_text += f" ({description})"
            if default:
                prompt_text += f" [default: {default}]"

            value = Prompt.ask(
                prompt_text,
                default=default or "",
                password=is_secret,
                console=console,
            )
            if value == "":
                value = None

        # Apply default if still None
        if value is None and default:
            value = default

        if value:
            resolved[name] = value
        elif required:
            missing_required.append(name)

    if missing_required:
        console.print(
            "[red]Error:[/red] Missing required env vars: "
            + ", ".join(missing_required)
        )
        raise SystemExit(1)

    return resolved


def _parse_env_file(env_file: Path) -> dict[str, str]:
    """Parse a dotenv-style file into a dict."""
    values: dict[str, str] = {}
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        # Strip surrounding quotes
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
            val = val[1:-1]
        values[key] = val
    return values


def _deploy_with_mcp_deps(
    module_path: Path,
    project: str,
    region: str,
    service_name: str,
    trace: bool,
    with_ui: bool,
    env_vars: dict[str, str] | None,
    allow_unauthenticated: bool,
    host_deps: list[str],
    module_dir: str,
    cloud_sql_instance: str | None = None,
    runtime_deps: list[dict] | None = None,
    memory: str = "1Gi",
    cpu: str = "1",
) -> int:
    """Deploy with a custom Dockerfile that installs host dependencies."""
    import importlib.metadata
    import tempfile

    from zil.packaging.dockerfile import generate_deploy_dockerfile

    try:
        adk_version = importlib.metadata.version("google-adk")
    except importlib.metadata.PackageNotFoundError:
        adk_version = "1.0.0"

    dockerfile = generate_deploy_dockerfile(
        module_dir=module_dir,
        adk_version=adk_version,
        host_deps=host_deps,
        runtime_deps=runtime_deps or [],
        with_ui=with_ui,
        trace=trace,
    )

    # Stage everything in a temp folder
    temp_dir = tempfile.mkdtemp(prefix="zil_deploy_mcp_")
    temp_path = Path(temp_dir)

    # Write Dockerfile
    (temp_path / "Dockerfile").write_text(dockerfile)

    # Copy the module dir as agents/{module_dir}/
    agents_dir = temp_path / "agents" / module_dir
    shutil.copytree(module_path, agents_dir, symlinks=True)

    console.print(
        f"→ Deploying [bold]{service_name}[/bold] to Cloud Run "
        f"(project={project}, region={region}, with MCP host deps)..."
    )

    # Deploy via gcloud
    cmd = [
        "gcloud", "run", "deploy", service_name,
        "--source", temp_dir,
        f"--project={project}",
        f"--region={region}",
        "--port=8000",
        f"--cpu={cpu}",
        f"--memory={memory}",
        "--timeout=3600",
        "--concurrency=80",
        "--max-instances=1",
        "--session-affinity",
    ]
    if env_vars:
        env_pairs = ",".join(f"{k}={v}" for k, v in env_vars.items())
        cmd.append(f"--set-env-vars={env_pairs}")
    if allow_unauthenticated:
        cmd.append("--allow-unauthenticated")
    if cloud_sql_instance:
        cmd.append(f"--add-cloudsql-instances={cloud_sql_instance}")
        console.print(
            f"  Cloud SQL: attaching instance [bold]{cloud_sql_instance}[/bold] "
            "(detected from SESSION_DB_URI)"
        )

    result = subprocess.call(cmd)

    # Cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)
    return result


def _fetch_service_url(service_name: str, project: str, region: str) -> str | None:
    """Query Cloud Run for the live service URL."""
    try:
        out = subprocess.check_output(
            [
                "gcloud", "run", "services", "describe", service_name,
                f"--project={project}",
                f"--region={region}",
                "--format=value(status.url)",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        url = out.strip()
        return url if url else None
    except subprocess.CalledProcessError:
        return None


def _build_deploy_result(
    manifest: dict,
    service_name: str,
    project: str,
    region: str,
    cloud_sql_instance: str | None,
) -> dict[str, Any]:
    """Build a structured deploy result dict, querying gcloud for the URL."""
    url = _fetch_service_url(service_name, project, region)

    # Derive webhook / HITL endpoints from manifest service config
    service_cfg = manifest.get("spec", {}).get("runtime", {}).get("service", {})
    endpoints: dict[str, Any] = {"agent": url}

    if service_cfg:
        webhooks = service_cfg.get("webhooks", [])
        if url and webhooks:
            endpoints["webhooks"] = [
                f"{url}{wh['path']}" for wh in webhooks if wh.get("path")
            ]
        hitl = service_cfg.get("human_interaction", {})
        if hitl.get("enabled"):
            response_path = hitl.get("response_path", "/human/respond")
            endpoints["hitl_respond"] = f"{url}{response_path}" if url else response_path

    result: dict[str, Any] = {
        "service": service_name,
        "project": project,
        "region": region,
        "url": url,
        "endpoints": endpoints,
        "deployed_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if cloud_sql_instance:
        result["cloud_sql_instance"] = cloud_sql_instance
    return result


def _emit_deploy_result(result: dict[str, Any] | None, output_format: str) -> None:
    """Print deploy result in the requested format.

    JSON goes to stdout (clean for pipes/CI).
    Rich-formatted text summary goes to stderr (same as all other console output).
    """
    if not result:
        return
    if output_format == "json":
        # click.echo writes to sys.stdout directly — clean for pipes/CI
        click.echo(json.dumps(result, indent=2))
        return
    # text mode: print a human-readable summary of key endpoints
    url = result.get("url")
    endpoints = result.get("endpoints", {})
    if url:
        console.print(f"  URL: [link={url}]{url}[/link]")
    webhooks = endpoints.get("webhooks", [])
    for wh_url in webhooks:
        console.print(f"  Webhook: {wh_url}")
    hitl_url = endpoints.get("hitl_respond")
    if hitl_url:
        console.print(f"  HITL respond: {hitl_url}")
    sql = result.get("cloud_sql_instance")
    if sql:
        console.print(f"  Cloud SQL: {sql}")


def _deploy_cloud_run(
    project_dir: Path,
    agent_name: str,
    module_dir: str,
    project: str,
    region: str,
    service: str | None,
    trace: bool,
    with_ui: bool,
    env_vars: dict[str, str] | None = None,
    allow_unauthenticated: bool = False,
    memory: str = "1Gi",
    cpu: str = "1",
) -> dict[str, Any]:
    """Deploy to Cloud Run via adk deploy cloud_run."""
    service_name = service or agent_name
    module_path = project_dir / module_dir

    # ADK deploy cloud_run only copies the module dir. Copy project files
    # (manifest, identity, adapters, observability, memory) so
    # zil.create_agent() can find them — and seed memory — at runtime.
    _copied_artifacts: list[Path] = []
    _copy_targets = [
        ("manifest.yaml", None),
        ("identity", None),
        ("adapters", None),
        ("observability", None),
        ("tools", None),
        ("skills", None),
        ("memory", None),
    ]
    for name, _ in _copy_targets:
        src = project_dir / name
        dst = module_path / name
        if src.exists() and not dst.exists():
            if src.is_file():
                shutil.copy2(src, dst)
            else:
                shutil.copytree(src, dst, symlinks=True)
            _copied_artifacts.append(dst)

    # Detect if MCP host dependencies need custom Dockerfile
    manifest_path = project_dir / "manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text())
    tools_cfg = manifest.get("spec", {}).get("tools")
    host_deps: list[str] = []
    has_mcp_source = False
    if isinstance(tools_cfg, dict):
        host_deps = tools_cfg.get("host_dependencies", [])
        for srv in tools_cfg.get("mcp_servers", []):
            if srv.get("source"):
                has_mcp_source = True
    runtime_deps: list[dict] = manifest.get("spec", {}).get("runtime", {}).get("dependencies", [])

    # Resolve Cloud SQL instance from SESSION_DB_URI (used in both deploy paths)
    cloud_sql_instance: str | None = None
    session_uri = env_vars.get("SESSION_DB_URI") if env_vars else None
    if not session_uri:
        session_uri = os.environ.get("SESSION_DB_URI")
    if session_uri and "/cloudsql/" in session_uri:
        m = re.search(r"/cloudsql/([^/]+)/", session_uri)
        if m:
            cloud_sql_instance = m.group(1)

    if host_deps or has_mcp_source or runtime_deps:
        # Use custom deploy path that injects host deps into Dockerfile
        result = _deploy_with_mcp_deps(
            module_path, project, region, service_name,
            trace, with_ui, env_vars, allow_unauthenticated,
            host_deps, module_dir,
            cloud_sql_instance=cloud_sql_instance,
            runtime_deps=runtime_deps,
            memory=memory,
            cpu=cpu,
        )
    else:
        if not shutil.which("adk"):
            console.print(
                "[red]Error:[/red] adk CLI not found. "
                "Install it with: [bold]pip install 'zil-ai\\[adk]'[/bold]"
            )
            raise SystemExit(1)

        cmd = [
            "adk", "deploy", "cloud_run",
            f"--project={project}",
            f"--region={region}",
            f"--service_name={service_name}",
        ]

        if trace:
            cmd.append("--otel_to_cloud")

        if with_ui:
            cmd.append("--with_ui")

        # The agent path is the module directory
        cmd.append(str(module_path))

        # Inject extra gcloud flags via -- separator
        gcloud_args: list[str] = []
        if env_vars:
            env_pairs = ",".join(f"{k}={v}" for k, v in env_vars.items())
            gcloud_args.append(f"--set-env-vars={env_pairs}")
        if allow_unauthenticated:
            gcloud_args.append("--allow-unauthenticated")

        # Cloud SQL session wiring (cloud_sql_instance resolved above)
        if cloud_sql_instance:
            gcloud_args.append(f"--add-cloudsql-instances={cloud_sql_instance}")
            console.print(
                f"  Cloud SQL: attaching instance [bold]{cloud_sql_instance}[/bold] "
                "(detected from SESSION_DB_URI)"
            )

        if gcloud_args:
            cmd.append("--")
            cmd.extend(gcloud_args)

        console.print(
            f"→ Deploying [bold]{agent_name}[/bold] to Cloud Run "
            f"(project={project}, region={region})..."
        )

        result = subprocess.call(cmd)

    try:
        pass
    finally:
        # Clean up copied artifacts to avoid polluting the source tree
        for artifact in _copied_artifacts:
            if artifact.is_file():
                artifact.unlink()
            elif artifact.is_dir():
                shutil.rmtree(artifact)

    if result != 0:
        console.print("[red]Error:[/red] Cloud Run deployment failed.")
        raise SystemExit(1)

    console.print(
        f"\n[green]✓[/green] Deployed [bold]{service_name}[/bold] "
        f"to Cloud Run."
    )
    if trace:
        console.print(
            "  Traces: Google Cloud Console → Trace Explorer"
        )

    return _build_deploy_result(
        manifest=manifest,
        service_name=service_name,
        project=project,
        region=region,
        cloud_sql_instance=cloud_sql_instance,
    )


def _deploy_unified(
    project_dir: Path,
    agent_name: str,
    project: str,
    region: str,
    service: str | None,
    env_vars: dict[str, str] | None = None,
    allow_unauthenticated: bool = False,
    memory: str = "1Gi",
    cpu: str = "1",
) -> dict[str, Any]:
    """Deploy using the unified path: Dockerfile with ``zil serve`` entrypoint.

    This is framework-agnostic — works for ADK, OpenHands, or any backend.
    The container runs ``zil serve`` which starts the agent as a REST/A2A server.
    """
    import tempfile

    from zil.packaging.dockerfile import (
        generate_serve_dockerfile,
        read_host_deps,
        read_memory_enabled,
        read_runtime_deps,
        strip_zil_requirement,
    )

    service_name = service or agent_name
    manifest_path = project_dir / "manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text())

    framework = manifest.get("spec", {}).get("runtime", {}).get("framework", "adk")
    host_deps = read_host_deps(manifest)
    runtime_deps = read_runtime_deps(manifest)
    memory_enabled = read_memory_enabled(manifest)

    # Resolve Cloud SQL instance
    cloud_sql_instance: str | None = None
    session_uri = env_vars.get("SESSION_DB_URI") if env_vars else None
    if not session_uri:
        session_uri = os.environ.get("SESSION_DB_URI")
    if session_uri and "/cloudsql/" in session_uri:
        m = re.search(r"/cloudsql/([^/]+)/", session_uri)
        if m:
            cloud_sql_instance = m.group(1)

    # Detect editable install — bundle local source so deployed version
    # matches what was tested locally.
    from zil.commands._docker import _is_editable_install

    zil_repo_root = _is_editable_install()
    use_local_src = zil_repo_root is not None

    if use_local_src:
        console.print(
            f"  [dim]Dev mode: bundling local zil source from "
            f"[bold]{zil_repo_root}[/bold] for deploy[/dim]"
        )

    # Generate Dockerfile
    dockerfile = generate_serve_dockerfile(
        host_deps=host_deps,
        runtime_deps=runtime_deps,
        framework=framework,
        local_zil_src=use_local_src,
        memory_enabled=memory_enabled,
    )

    # Stage project in a temp dir
    temp_dir = tempfile.mkdtemp(prefix="zil_deploy_serve_")
    temp_path = Path(temp_dir)

    # Write Dockerfile
    (temp_path / "Dockerfile").write_text(dockerfile)

    # Copy entire project
    ignore = shutil.ignore_patterns(
        ".git", ".venv", "__pycache__", "*.pyc", ".ruff_cache",
        "node_modules", "*.egg-info",
    )
    shutil.copytree(project_dir, temp_path / "project", ignore=ignore, dirs_exist_ok=False)

    # Move project files to root of temp dir for simpler COPY .
    # (Dockerfile expects files at top level)
    for item in (temp_path / "project").iterdir():
        dest = temp_path / item.name
        if not dest.exists():
            shutil.move(str(item), str(dest))
    shutil.rmtree(temp_path / "project", ignore_errors=True)

    # Copy local zil source into build context if editable install
    if use_local_src and zil_repo_root:
        zil_dest = temp_path / "_zil_src"
        zil_dest.mkdir()
        shutil.copytree(
            zil_repo_root / "src", zil_dest / "src", ignore=ignore,
        )
        shutil.copy2(zil_repo_root / "pyproject.toml", zil_dest / "pyproject.toml")
        readme = zil_repo_root / "README.md"
        if readme.is_file():
            shutil.copy2(readme, zil_dest / "README.md")

    # Reconcile requirements.txt with the zil install strategy. The Dockerfile
    # always COPYs requirements.txt, so it must exist either way.
    req_path = temp_path / "requirements.txt"
    if use_local_src:
        # zil is installed from local source (with extras) by the Dockerfile.
        # Drop any PyPI ``zil-ai`` line so it can't shadow the local build or
        # miss the ``memory`` extra. Always (re)write so the file exists even
        # when the packed project ships no requirements.txt.
        existing = req_path.read_text() if req_path.exists() else ""
        req_path.write_text(strip_zil_requirement(existing))
    elif not req_path.exists():
        groups = ["serve"]
        if framework != "stub":
            groups.append(framework)
        if memory_enabled:
            groups.append("memory")
        req_path.write_text(f"zil-ai[{','.join(groups)}]\n")

    console.print(
        f"→ Deploying [bold]{service_name}[/bold] to Cloud Run "
        f"(unified mode, framework={framework})..."
    )

    # Deploy via gcloud run deploy --source
    cmd = [
        "gcloud", "run", "deploy", service_name,
        "--source", temp_dir,
        f"--project={project}",
        f"--region={region}",
        "--port=8000",
        f"--cpu={cpu}",
        f"--memory={memory}",
        "--timeout=3600",
        "--concurrency=80",
        "--max-instances=1",
        "--session-affinity",
    ]
    if env_vars:
        env_pairs = ",".join(f"{k}={v}" for k, v in env_vars.items())
        cmd.append(f"--set-env-vars={env_pairs}")
    if allow_unauthenticated:
        cmd.append("--allow-unauthenticated")
    if cloud_sql_instance:
        cmd.append(f"--add-cloudsql-instances={cloud_sql_instance}")
        console.print(
            f"  Cloud SQL: attaching instance [bold]{cloud_sql_instance}[/bold]"
        )

    result = subprocess.call(cmd)

    # Cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)

    if result != 0:
        console.print("[red]Error:[/red] Cloud Run deployment failed.")
        raise SystemExit(1)

    console.print(
        f"\n[green]✓[/green] Deployed [bold]{service_name}[/bold] "
        f"to Cloud Run (via zil serve)."
    )
    console.print("  Endpoints:")
    console.print("    GET  /health")
    console.print("    POST /invoke")
    console.print("    POST /sessions")
    console.print("    GET  /.well-known/agent.json")
    console.print("    POST /tasks/send")

    return _build_deploy_result(
        manifest=manifest,
        service_name=service_name,
        project=project,
        region=region,
        cloud_sql_instance=cloud_sql_instance,
    )


@click.command()
@click.option(
    "--project-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=".",
    help="Project directory (default: current directory).",
)
@click.option(
    "--project", "gcp_project",
    type=str, default=None,
    help="GCP project (or GOOGLE_CLOUD_PROJECT env var).",
)
@click.option(
    "--region", "gcp_region",
    type=str, default=None,
    help="GCP region (or GOOGLE_CLOUD_REGION env var).",
)
@click.option(
    "--service",
    type=str, default=None,
    help="Cloud Run service name (default: agent name).",
)
@click.option(
    "--with-ui", "with_ui",
    is_flag=True, default=False,
    help="Include ADK web UI in Cloud Run deploy.",
)
@click.option(
    "--trace",
    is_flag=True, default=False,
    help="Enable Cloud Trace telemetry.",
)
@click.option(
    "--skip-evals", "skip_evals",
    is_flag=True, default=False,
    help="Skip pre-deploy eval check.",
)
@click.option(
    "--from", "from_ref",
    type=str, default=None,
    help="Deploy from a .zil archive or OCI registry reference.",
)
@click.option(
    "--env-file", "env_file",
    type=click.Path(path_type=Path),
    default=None,
    help="Dotenv file with env var values (alternative to interactive prompts).",
)
@click.option(
    "--allow-unauthenticated", "allow_unauthenticated",
    is_flag=True, default=False,
    help="Allow unauthenticated access to the Cloud Run service.",
)
@click.option(
    "--memory",
    type=str, default="1Gi",
    help="Cloud Run memory limit (default: 1Gi). Examples: 512Mi, 1Gi, 2Gi.",
)
@click.option(
    "--cpu",
    type=str, default="1",
    help="CPU allocation (default: 1). Must satisfy memory constraints.",
)
@click.option(
    "--output", "output_format",
    type=click.Choice(["text", "json"], case_sensitive=False),
    default="text",
    help="Output format after deploy: 'text' (default) or 'json' (machine-readable).",
)
@click.option(
    "--mode",
    type=click.Choice(["auto", "serve", "legacy-adk"], case_sensitive=False),
    default="auto",
    help=(
        "Deploy mode. 'auto' (default) uses 'serve' for non-ADK frameworks "
        "and legacy ADK path for ADK agents. 'serve' forces the unified "
        "zil-serve-based deployment. 'legacy-adk' forces the ADK CLI deploy."
    ),
)
def deploy(
    project_dir: Path,
    gcp_project: str | None,
    gcp_region: str | None,
    service: str | None,
    with_ui: bool,
    trace: bool,
    skip_evals: bool,
    from_ref: str | None,
    env_file: Path | None,
    allow_unauthenticated: bool,
    memory: str,
    cpu: str,
    output_format: str,
    mode: str,
) -> None:
    """Deploy the agent to Cloud Run."""
    # If --from is specified, deploy from artifact
    if from_ref:
        result = _deploy_from_artifact(
            from_ref, gcp_project, gcp_region, service, trace, with_ui, env_file,
            allow_unauthenticated, memory=memory, cpu=cpu, mode=mode,
        )
        _emit_deploy_result(result, output_format)
        return

    project_dir = project_dir.resolve()
    agent_name = _resolve_module(project_dir)
    module_dir = _resolve_module_dir(project_dir, agent_name)

    # Validate framework is registered
    manifest_path_check = project_dir / "manifest.yaml"
    if manifest_path_check.is_file():
        _manifest = yaml.safe_load(manifest_path_check.read_text())
        framework = _manifest.get("spec", {}).get("runtime", {}).get("framework", "adk")
        from zil.sdk.frameworks import registry
        try:
            registry.get(framework)
        except Exception as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise SystemExit(1)

    # Verify module directory exists
    if not (project_dir / module_dir).is_dir():
        console.print(
            f"[red]Error:[/red] Agent module directory "
            f"'{module_dir}/' not found. Did you run [bold]zil init[/bold]?"
        )
        raise SystemExit(1)

    # Pre-deploy eval gate (warn only)
    if not skip_evals:
        _run_eval_gate(project_dir)

    # Cloud Run mode
    if not _check_gcloud():
        raise SystemExit(1)

    project = _resolve_gcp_project(gcp_project)
    if not project:
        console.print(
            "[red]Error:[/red] GCP project not specified. "
            "Use --project, set GOOGLE_CLOUD_PROJECT, or run "
            "`gcloud config set project <PROJECT_ID>`."
        )
        raise SystemExit(1)

    region = _resolve_gcp_region(gcp_region)
    if not region:
        console.print(
            "[red]Error:[/red] GCP region not specified. "
            "Use --region or set GOOGLE_CLOUD_REGION."
        )
        raise SystemExit(1)

    # Resolve env vars from manifest declarations
    manifest_path = project_dir / "manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text())
    env_vars = _resolve_env_vars(manifest, env_file)
    if env_vars:
        count = len(env_vars)
        console.print(f"[green]✓[/green] Resolved {count} env variable(s)")

    # Decide deploy path based on --mode and framework
    use_unified = False
    if mode == "serve":
        use_unified = True
    elif mode == "auto" and framework != "adk":
        use_unified = True
        console.print(
            f"  Using unified deploy (framework={framework} → zil serve entrypoint)"
        )

    if use_unified:
        deploy_result = _deploy_unified(
            project_dir, agent_name,
            project, region, service, env_vars,
            allow_unauthenticated, memory=memory, cpu=cpu,
        )
    else:
        deploy_result = _deploy_cloud_run(
            project_dir, agent_name, module_dir,
            project, region, service, trace, with_ui, env_vars,
            allow_unauthenticated, memory=memory, cpu=cpu,
        )
    _emit_deploy_result(deploy_result, output_format)


def _deploy_from_artifact(
    from_ref: str,
    gcp_project: str | None,
    gcp_region: str | None,
    service: str | None,
    trace: bool,
    with_ui: bool,
    env_file: Path | None = None,
    allow_unauthenticated: bool = False,
    memory: str = "1Gi",
    cpu: str = "1",
    mode: str = "auto",
) -> dict[str, Any]:
    """Deploy from a .zil archive or OCI registry reference."""
    import tempfile

    from zil.packaging.archive import extract_archive

    # Determine if from_ref is a local file or registry reference
    ref_path = Path(from_ref)
    if ref_path.exists() and ref_path.suffix == ".zil":
        archive_path = ref_path
        console.print(f"→ Deploying from local archive: [bold]{archive_path.name}[/bold]")
    else:
        # Pull from registry
        console.print(f"→ Pulling from registry: [bold]{from_ref}[/bold]")
        from zil.packaging.registry import pull_archive

        tmp_dir = Path(tempfile.mkdtemp(prefix="zil-pull-"))
        try:
            archive_path = pull_archive(from_ref, tmp_dir)
        except ImportError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise SystemExit(1)
        except Exception as e:
            console.print(f"[red]Error:[/red] Pull failed: {e}")
            raise SystemExit(1)
        console.print("[green]✓[/green] Pulled")

    # Extract archive to temp directory
    console.print("→ Extracting archive...")
    extract_dir = Path(tempfile.mkdtemp(prefix="zil-deploy-"))
    extract_archive(archive_path, extract_dir)
    console.print("[green]✓[/green] Extracted")

    # Resolve the project from extracted contents
    project_dir = extract_dir
    agent_name = _resolve_module(project_dir)
    module_dir = _resolve_module_dir(project_dir, agent_name)

    # Cloud Run deploy
    if not _check_gcloud():
        raise SystemExit(1)

    project = _resolve_gcp_project(gcp_project)
    if not project:
        console.print(
            "[red]Error:[/red] GCP project not specified. "
            "Use --project, set GOOGLE_CLOUD_PROJECT, or run "
            "`gcloud config set project <PROJECT_ID>`."
        )
        raise SystemExit(1)

    region = _resolve_gcp_region(gcp_region)
    if not region:
        console.print(
            "[red]Error:[/red] GCP region not specified. "
            "Use --region or set GOOGLE_CLOUD_REGION."
        )
        raise SystemExit(1)

    # Resolve env vars from manifest declarations
    manifest_path = project_dir / "manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text())
    env_vars = _resolve_env_vars(manifest, env_file)
    if env_vars:
        count = len(env_vars)
        console.print(f"[green]✓[/green] Resolved {count} env variable(s)")

    # Route to unified path based on mode and framework
    framework = manifest.get("spec", {}).get("runtime", {}).get("framework", "adk")
    use_unified = mode == "serve" or (mode == "auto" and framework != "adk")
    if use_unified:
        console.print(
            f"  Using unified deploy (framework={framework} → zil serve entrypoint)"
        )
        return _deploy_unified(
            project_dir, agent_name,
            project, region, service, env_vars,
            allow_unauthenticated, memory=memory, cpu=cpu,
        )

    return _deploy_cloud_run(
        project_dir, agent_name, module_dir,
        project, region, service, trace, with_ui, env_vars,
        allow_unauthenticated, memory=memory, cpu=cpu,
    )
