"""zil serve — run the agent as a REST/A2A server.

Starts a FastAPI application that exposes the agent via:
- REST endpoints (sessions API)
- Manifest-declared webhooks
- A2A protocol endpoints (Agent Card + tasks)
- Health check
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Optional

import click
import yaml

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_otlp_endpoint(project_dir: Path, manifest: dict) -> str | None:
    """Resolve the OTLP endpoint from observability config."""
    import yaml as _yaml

    from zil.sdk.telemetry import _resolve_env_refs

    obs_ref = manifest.get("spec", {}).get("observability")
    if not obs_ref:
        return None

    obs_path = project_dir / obs_ref / "config.yaml"
    if not obs_path.is_file():
        return None

    with open(obs_path, encoding="utf-8") as f:
        obs_config = _yaml.safe_load(f) or {}

    endpoint = obs_config.get("observability", {}).get("tracing", {}).get("endpoint", "")
    if not endpoint:
        return None

    return _resolve_env_refs(endpoint) or None


# ---------------------------------------------------------------------------
# Agent loader — custom entry point or default create_agent()
# ---------------------------------------------------------------------------


def _load_agent(project_dir: Path, agent_name: str) -> Any:
    """Load the agent for ``zil serve``.

    If the project contains a custom agent module (``<name>/agent.py`` with a
    ``root_agent`` attribute), import and wrap it. Otherwise fall back to the
    standard ``create_agent(raw=True)`` path.
    """
    import importlib
    import sys

    from zil.sdk.frameworks.base import WiredAgent

    module_dir = project_dir / agent_name
    agent_file = module_dir / "agent.py"

    if agent_file.is_file():
        logger.info("Custom agent entry point found: %s", agent_file)
        # Make sure the project dir is importable
        project_str = str(project_dir)
        if project_str not in sys.path:
            sys.path.insert(0, project_str)

        module_name = f"{agent_name}.agent"
        try:
            mod = importlib.import_module(module_name)
        except Exception:
            logger.warning(
                "Failed to import %s — falling back to create_agent()",
                module_name,
                exc_info=True,
            )
            from zil.sdk.agent import create_agent
            return create_agent(project_dir=project_dir, raw=True)

        root_agent = getattr(mod, "root_agent", None)
        if root_agent is None:
            logger.warning(
                "%s has no 'root_agent' attribute — falling back to create_agent()",
                module_name,
            )
            from zil.sdk.agent import create_agent
            return create_agent(project_dir=project_dir, raw=True)

        # Wrap the raw framework agent as a WiredAgent
        if isinstance(root_agent, WiredAgent):
            return root_agent

        from zil.sdk.session import _wrap_raw_agent
        wrapped = _wrap_raw_agent(root_agent)
        logger.info("Custom root_agent loaded and wrapped from %s", module_name)
        return wrapped

    # No custom entry point — use default SDK path
    from zil.sdk.agent import create_agent
    return create_agent(project_dir=project_dir, raw=True)


# ---------------------------------------------------------------------------
# FastAPI app factory
# ---------------------------------------------------------------------------


def _create_app(
    project_dir: Path,
    *,
    enable_a2a: bool = True,
) -> Any:
    """Build the FastAPI application from the project manifest."""
    try:
        from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request, status
        from fastapi.responses import JSONResponse, StreamingResponse
        from pydantic import BaseModel
    except ImportError:
        raise ImportError(
            "FastAPI is required for 'zil serve'. "
            "Install it with:  pip install 'zil-ai[serve]'"
        ) from None

    from zil.sdk.session import Session, SessionEvent

    # ---- Load manifest ----------------------------------------------------
    manifest_path = project_dir / "manifest.yaml"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifest.yaml not found in {project_dir}")

    with open(manifest_path, encoding="utf-8") as f:
        manifest = yaml.safe_load(f)

    metadata = manifest.get("metadata", {})
    agent_name = metadata.get("name", "zil-agent")
    agent_version = metadata.get("version", "0.0.0")
    agent_description = metadata.get("description", "")

    # ---- Wire the agent ---------------------------------------------------
    wired_agent = _load_agent(project_dir, agent_name)

    # ---- Session store (in-memory) ----------------------------------------
    sessions: dict = {}
    # Active streaming tasks — keyed by session_id so they can be cancelled
    active_tasks: dict[str, asyncio.Task] = {}

    # ---- Request models ---------------------------------------------------
    class CreateSessionBody(BaseModel):
        workspace: Optional[str] = None
        session_id: Optional[str] = None

    class SendMessageBody(BaseModel):
        message: str

    class InvokeBody(BaseModel):
        message: str
        workspace: Optional[str] = None

    class A2AMessagePart(BaseModel):
        type: str = "text"
        text: str = ""

    class A2AMessage(BaseModel):
        parts: list = []

    class A2ATaskRequest(BaseModel):
        id: Optional[str] = None
        message: Optional[A2AMessage] = None

    # ---- Build FastAPI app ------------------------------------------------
    app = FastAPI(
        title=f"{agent_name} — Zil Agent Server",
        version=agent_version,
        description=agent_description,
    )

    # Store references on app state
    app.state.wired_agent = wired_agent
    app.state.project_dir = project_dir

    # ---- Health check -----------------------------------------------------
    @app.get("/health")
    async def health():
        return {"status": "ok", "agent": agent_name, "version": agent_version}

    # ---- Session endpoints ------------------------------------------------
    def _get_or_create_session(session_id: str | None = None, workspace: str | None = None) -> tuple[str, Any]:
        """Return (session_id, Session), creating one if needed."""
        sid = session_id or uuid.uuid4().hex
        if sid not in sessions:
            ws = workspace or str(project_dir)
            sessions[sid] = Session(
                wired_agent,
                workspace=ws,
                session_id=sid,
            )
            logger.info("Session created: %s", sid)
        return sid, sessions[sid]

    @app.post("/sessions", status_code=201)
    async def create_session_endpoint(body: CreateSessionBody = CreateSessionBody()):
        """Create a new session. Optionally accepts workspace and session_id in body."""
        sid, session = _get_or_create_session(body.session_id, body.workspace)
        return {"session_id": sid, "workspace": session.workspace}

    @app.post("/sessions/{session_id}/messages")
    async def send_message(session_id: str, body: SendMessageBody):
        """Send a message to an existing session and get the full response."""
        if session_id not in sessions:
            raise HTTPException(status_code=404, detail="Session not found")

        if not body.message:
            raise HTTPException(status_code=400, detail="'message' field is required")

        session = sessions[session_id]
        response = await session.send(body.message)
        return {
            "session_id": session_id,
            "text": response.text,
            "events": [
                {
                    "type": ev.type,
                    "text": ev.text,
                    "tool_name": ev.tool_name,
                    "args": ev.args,
                }
                for ev in response.events
            ],
            "token_usage": response.token_usage,
        }

    @app.get("/sessions/{session_id}/stream")
    async def stream_session(session_id: str, message: str = Query(default="")):
        """SSE stream — send a message via query param and stream events."""
        if not message:
            raise HTTPException(status_code=400, detail="'message' query param required")

        # Auto-create session on miss so the caller's ID is preserved
        _sid, session = _get_or_create_session(session_id)

        async def event_generator():
            # Register the current task so it can be cancelled
            current_task = asyncio.current_task()
            if current_task:
                active_tasks[session_id] = current_task
            try:
                async for event in session.stream(message):
                    payload: dict[str, Any] = {
                        "type": event.type,
                    }
                    if event.text is not None:
                        payload["text"] = event.text
                    if event.tool_name is not None:
                        payload["tool_name"] = event.tool_name
                    if event.args is not None:
                        payload["args"] = event.args
                    if event.result is not None:
                        payload["result"] = event.result
                    if event.metadata:
                        payload["metadata"] = event.metadata
                        # Surface token_usage at top level for SSE consumers
                        if "token_usage" in event.metadata:
                            payload["token_usage"] = event.metadata["token_usage"]
                    data = json.dumps(payload)
                    yield f"data: {data}\n\n"
            except asyncio.CancelledError:
                yield f'data: {{"type": "done", "text": "Cancelled by user"}}\n\n'
            finally:
                active_tasks.pop(session_id, None)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
        )

    @app.post("/sessions/{session_id}/cancel")
    async def cancel_session(session_id: str):
        """Cancel a running stream for this session."""
        task = active_tasks.get(session_id)
        if not task:
            return {"status": "no_active_task", "session_id": session_id}
        task.cancel()
        return {"status": "cancelled", "session_id": session_id}

    @app.delete("/sessions/{session_id}")
    async def close_session(session_id: str):
        """Close and delete a session."""
        if session_id not in sessions:
            raise HTTPException(status_code=404, detail="Session not found")

        session = sessions.pop(session_id)
        await session.close()
        return {"status": "closed", "session_id": session_id}

    # ---- Quick invoke (stateless) -----------------------------------------
    @app.post("/invoke")
    async def invoke_endpoint(body: InvokeBody):
        """Stateless invoke — creates a session, sends message, closes."""
        if not body.message:
            raise HTTPException(status_code=400, detail="'message' field is required")

        workspace = body.workspace or str(project_dir)
        session = Session(wired_agent, workspace=workspace)
        try:
            response = await session.send(body.message)
        finally:
            await session.close()

        # Build events list for response
        events_out = []
        for ev in response.events:
            events_out.append({
                "type": ev.type,
                "text": ev.text,
                "tool_name": ev.tool_name,
                "args": ev.args,
            })

        return {
            "text": response.text,
            "session_id": response.session_id,
            "token_usage": response.token_usage,
            "events": events_out,
        }

    # ---- Manifest-declared webhooks ---------------------------------------
    service_cfg = manifest.get("spec", {}).get("runtime", {}).get("service", {})
    webhooks = service_cfg.get("webhooks", [])

    for wh_cfg in webhooks:
        wh_name = wh_cfg.get("name", "")
        wh_path = wh_cfg.get("path", f"/webhooks/{wh_name}")
        sig_header = wh_cfg.get("signature_header")
        algorithm = wh_cfg.get("algorithm", "sha256")
        secret_env = wh_cfg.get("secret_env", "")

        _register_webhook(
            app,
            name=wh_name,
            path=wh_path,
            signature_header=sig_header,
            algorithm=algorithm,
            secret_env=secret_env,
            wired_agent=wired_agent,
            project_dir=project_dir,
            sessions=sessions,
        )

    # ---- A2A endpoints ---------------------------------------------------
    if enable_a2a:
        _register_a2a_endpoints(
            app, project_dir, manifest, agent_name, agent_version, agent_description
        )

    return app


def _register_webhook(
    app,
    *,
    name: str,
    path: str,
    signature_header,
    algorithm: str,
    secret_env: str,
    wired_agent,
    project_dir: Path,
    sessions: dict,
) -> None:
    """Dynamically register a webhook endpoint on the app."""
    from fastapi import BackgroundTasks, HTTPException, Request

    from zil.sdk.session import Session

    # Capture closure variables
    _name = name
    _sig_header = signature_header
    _algorithm = algorithm
    _secret_env = secret_env
    _wired_agent = wired_agent
    _project_dir = project_dir

    @app.post(path, status_code=202, name=f"webhook_{_name}")
    async def webhook_handler(request: Request, background: BackgroundTasks):
        raw = await request.body()

        # Signature verification
        if _sig_header and _secret_env:
            secret = os.environ.get(_secret_env, "")
            if secret:
                provided_sig = request.headers.get(_sig_header, "")
                if "=" in provided_sig:
                    provided_sig = provided_sig.split("=", 1)[1]
                h = hmac.new(secret.encode(), raw, getattr(hashlib, _algorithm, hashlib.sha256))
                expected = h.hexdigest()
                if not hmac.compare_digest(expected, provided_sig):
                    raise HTTPException(status_code=401, detail="Invalid signature")

        # Parse payload and dispatch
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid JSON payload")

        # Generic dispatch: send payload as message to agent
        msg = json.dumps(payload, indent=2)

        async def _dispatch():
            session = Session(_wired_agent, workspace=str(_project_dir))
            try:
                await session.send(f"Webhook '{_name}' received:\n{msg}")
            finally:
                await session.close()

        background.add_task(_dispatch)
        return {"status": "accepted", "webhook": _name}


def _load_skill_cards(project_dir: Path, manifest: dict) -> list[dict]:
    """Build A2A AgentSkill entries from the ``spec.skills`` directory.

    Each skill is a subdirectory containing a ``SKILL.md`` with YAML
    frontmatter (``name``, ``description``). Advertising the real skills on
    the Agent Card lets any A2A client introspect and select capabilities.
    Returns ``[]`` when ``spec.skills`` is absent, missing, or empty.
    """
    skills_ref = manifest.get("spec", {}).get("skills")
    if not skills_ref:
        return []
    skills_path = (project_dir / skills_ref).resolve()
    if not skills_path.is_dir():
        return []

    cards: list[dict] = []
    for entry in sorted(skills_path.iterdir()):
        if not entry.is_dir():
            continue
        skill_md = entry / "SKILL.md"
        if not skill_md.is_file():
            skill_md = entry / "skill.md"
            if not skill_md.is_file():
                continue
        name = entry.name
        description = ""
        try:
            text = skill_md.read_text(encoding="utf-8")
            if text.startswith("---"):
                fm_block = text.partition("---")[2].partition("---")[0]
                meta = yaml.safe_load(fm_block) or {}
                name = meta.get("name", name)
                description = (meta.get("description") or "").strip()
        except Exception:
            logger.warning(
                "Could not parse skill frontmatter: %s", skill_md, exc_info=True
            )
        cards.append({
            "id": entry.name,
            "name": name,
            "description": description,
        })
    return cards


def _register_a2a_endpoints(
    app,
    project_dir: Path,
    manifest: dict,
    agent_name: str,
    agent_version: str,
    agent_description: str,
) -> None:
    """Register A2A protocol endpoints (Agent Card + task management)."""
    from fastapi import HTTPException, Request
    from fastapi.responses import JSONResponse, StreamingResponse

    from zil.sdk.session import Session

    # Build Agent Card from manifest
    agent_card = {
        "name": agent_name,
        "description": agent_description,
        "url": "",
        "version": agent_version,
        "capabilities": {
            "streaming": True,
            "pushNotifications": False,
        },
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [],
    }

    # Advertise real skills from spec.skills so A2A clients can introspect
    # and select capabilities (RFC-005 §8). Falls back to [] when undeclared.
    agent_card["skills"] = _load_skill_cards(project_dir, manifest)

    # In-memory task store
    tasks: dict = {}

    @app.get("/.well-known/agent.json")
    async def agent_card_endpoint(request: Request):
        """A2A Agent Card — describes this agent's capabilities."""
        card = dict(agent_card)
        scheme = request.headers.get("x-forwarded-proto", "http")
        host = request.headers.get("host", "localhost")
        card["url"] = f"{scheme}://{host}"
        return JSONResponse(content=card)

    @app.post("/tasks/send")
    async def a2a_send_task(request: Request):
        """A2A: Send a task (non-streaming)."""
        body = await request.json()
        task_id = body.get("id", uuid.uuid4().hex)
        message_parts = body.get("message", {}).get("parts", [])
        text_parts = [p.get("text", "") for p in message_parts if p.get("type") == "text"]
        message_text = "\n".join(text_parts) if text_parts else json.dumps(body.get("message", {}))

        tasks[task_id] = {"id": task_id, "status": {"state": "working"}}

        wired = app.state.wired_agent
        project = app.state.project_dir

        session = Session(wired, workspace=str(project) if project else None)
        try:
            response = await session.send(message_text)
        finally:
            await session.close()

        artifacts = [{"parts": [{"type": "text", "text": response.text}]}]
        tasks[task_id] = {
            "id": task_id,
            "status": {"state": "completed"},
            "artifacts": artifacts,
        }
        return JSONResponse(content={"id": task_id, "result": tasks[task_id]})

    @app.post("/tasks/sendSubscribe")
    async def a2a_send_subscribe(request: Request):
        """A2A: Send a task with SSE streaming."""
        body = await request.json()
        task_id = body.get("id", uuid.uuid4().hex)
        message_parts = body.get("message", {}).get("parts", [])
        text_parts = [p.get("text", "") for p in message_parts if p.get("type") == "text"]
        message_text = "\n".join(text_parts) if text_parts else json.dumps(body.get("message", {}))

        wired = app.state.wired_agent
        project = app.state.project_dir

        session = Session(wired, workspace=str(project) if project else None)

        async def event_stream():
            yield f"data: {json.dumps({'id': task_id, 'status': {'state': 'working'}})}\n\n"
            text_parts_out = []
            try:
                async for event in session.stream(message_text):
                    if event.type == "text" and event.text:
                        text_parts_out.append(event.text)
                        yield f"data: {json.dumps({'id': task_id, 'status': {'state': 'working'}, 'artifact': {'parts': [{'type': 'text', 'text': event.text}]}})}\n\n"
                    elif event.type == "tool_call":
                        yield f"data: {json.dumps({'id': task_id, 'status': {'state': 'working', 'message': 'Calling tool: ' + str(event.tool_name)}})}\n\n"
            finally:
                await session.close()
            full_text = "".join(text_parts_out)
            yield f"data: {json.dumps({'id': task_id, 'status': {'state': 'completed'}, 'artifacts': [{'parts': [{'type': 'text', 'text': full_text}]}]})}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.get("/tasks/{task_id}")
    async def a2a_get_task(task_id: str):
        """A2A: Get task status."""
        if task_id not in tasks:
            raise HTTPException(status_code=404, detail="Task not found")
        return JSONResponse(content=tasks[task_id])


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------


@click.command()
@click.option(
    "--project-dir", "-d",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    default=".",
    help="Project root directory (default: current dir).",
)
@click.option(
    "--port", "-p",
    type=int,
    default=8000,
    help="Port to listen on (default: 8000).",
)
@click.option(
    "--host",
    type=str,
    default="0.0.0.0",
    help="Host to bind (default: 0.0.0.0).",
)
@click.option(
    "--no-a2a",
    is_flag=True,
    default=False,
    help="Disable A2A protocol endpoints.",
)
@click.option(
    "--reload",
    is_flag=True,
    default=False,
    help="Enable auto-reload for development.",
)
@click.option(
    "--docker",
    is_flag=True,
    default=False,
    help="Build and run in a Docker container.",
)
@click.option(
    "--trace", "trace_mode",
    is_flag=True,
    default=False,
    help="Enable OTLP trace export.",
)
@click.option(
    "--trace-console", "trace_console",
    is_flag=True,
    default=False,
    help="Print spans to stderr (no collector needed).",
)
def serve(
    project_dir: str, port: int, host: str, no_a2a: bool, reload: bool,
    docker: bool, trace_mode: bool, trace_console: bool,
) -> None:
    """Start the agent as a REST/A2A server.

    Exposes the agent via REST endpoints, manifest-declared webhooks,
    and optionally the A2A protocol for agent-to-agent communication.
    """
    from rich.console import Console

    console = Console()
    project_path = Path(project_dir)

    # Validate manifest exists
    if not (project_path / "manifest.yaml").is_file():
        console.print("[red]Error:[/red] manifest.yaml not found.")
        raise SystemExit(1)

    manifest = yaml.safe_load((project_path / "manifest.yaml").read_text())
    agent_name = manifest.get("metadata", {}).get("name", "agent")

    # ---- Docker mode --------------------------------------------------------
    if docker:
        from zil.commands._docker import check_docker, docker_serve

        if not check_docker():
            raise SystemExit(1)
        docker_serve(project_path, agent_name, port, trace=trace_mode)
        return

    # ---- Tracing setup (non-Docker) -----------------------------------------
    if trace_console:
        from zil.sdk.telemetry import setup_console_telemetry

        agent_version = manifest.get("metadata", {}).get("version", "")
        ok = setup_console_telemetry(agent_name=agent_name, agent_version=agent_version)
        if ok:
            console.print("[green]✓[/green] Console tracing active — spans printed to stderr.")

    if trace_mode:
        endpoint = _resolve_otlp_endpoint(project_path, manifest)
        if endpoint:
            os.environ.setdefault("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", endpoint)
            console.print(f"[green]✓[/green] Tracing active — exporting to {endpoint}")
        else:
            console.print(
                "[yellow]Warning:[/yellow] Tracing endpoint not configured. "
                "Set OTEL_EXPORTER_OTLP_TRACES_ENDPOINT in your .env file."
            )

    # ---- Start server -------------------------------------------------------
    try:
        import uvicorn
    except ImportError:
        click.echo(
            "Error: uvicorn is required for 'zil serve'. "
            "Install it with:  pip install 'zil-ai[serve]'",
            err=True,
        )
        raise SystemExit(1) from None

    console.print(f"[bold]zil serve[/bold] — starting agent server")
    console.print(f"  Project: {project_path}")
    console.print(f"  Port: {port}")
    console.print(f"  A2A: {'enabled' if not no_a2a else 'disabled'}")
    console.print()

    app = _create_app(project_path, enable_a2a=not no_a2a)

    console.print(f"  Endpoints:")
    console.print(f"    GET  /health")
    console.print(f"    POST /invoke")
    console.print(f"    POST /sessions")
    console.print(f"    POST /sessions/{{id}}/messages")
    console.print(f"    GET  /sessions/{{id}}/stream")
    if not no_a2a:
        console.print(f"    GET  /.well-known/agent.json")
        console.print(f"    POST /tasks/send")
        console.print(f"    POST /tasks/sendSubscribe")
    console.print()

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
        reload=reload,
    )
