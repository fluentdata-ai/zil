"""Template file definitions for zil init scaffolding."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from zil.commands.init import InitConfig


# Each entry: (relative_path, renderer_function)
# Renderers take an InitConfig and return file content as a string.
TEMPLATE_FILES: list[tuple[str, Callable[[InitConfig], str]]] = []


def _register(path: str):
    """Decorator to register a template renderer."""
    def decorator(fn: Callable[[InitConfig], str]):
        TEMPLATE_FILES.append((path, fn))
        return fn
    return decorator


# ---------------------------------------------------------------------------
# manifest.yaml
# ---------------------------------------------------------------------------
@_register("manifest.yaml")
def _manifest(c: InitConfig) -> str:
    evals_line = '  evals: ./evals' if c.include_evals else '  # evals: ./evals'
    obs_line = (
        '  observability: ./observability' if c.include_otel
        else '  # observability: ./observability'
    )
    env_vars = _manifest_env_vars(c)
    tools_block = _manifest_tools_block(c)
    agents_block = _manifest_agents_block(c)
    service_block = _manifest_service_block(c)
    identity_line = (
        '  identity: ./identity' if not c.agent_names
        else '  # identity: ./identity  # omitted — sub-agents carry their own identities'
    )
    return f"""\
apiVersion: zil/v1
kind: Agent
metadata:
  name: {c.name}
  version: 0.1.0
  description: A Zil agent scaffolded with zil init.
  labels:
    team: fluentdata
spec:
  runtime:
    framework: {c.framework}
    language: {c.language}
    python_version: "3.12"
    llm:
      adapter: ./adapters/llm.yaml
    embedding:
      adapter: ./adapters/embed.yaml
    resource_limits:
      max_tokens_per_request: 8192
      max_duration_seconds: 120
{service_block}{identity_line}
{agents_block}{evals_line}
{obs_line}
  # cost:
  #   max_tokens_per_request: 8192
  #   max_tokens_per_session: 500000
  #   alert_threshold_pct: 80
  #   track_by_model: true
  env:
{env_vars}
{tools_block}
"""


def _manifest_env_vars(c: InitConfig) -> str:
    """Generate the env var declarations block for the manifest template."""
    providers = {
        "gemini": ("GOOGLE_API_KEY", "Gemini API key"),
        "vertex": ("GOOGLE_APPLICATION_CREDENTIALS", "Path to GCP service account JSON"),
        "anthropic": ("ANTHROPIC_API_KEY", "Anthropic API key"),
        "openai": ("OPENAI_API_KEY", "OpenAI API key"),
    }
    env_name, env_desc = providers.get(c.llm_provider, providers["gemini"])
    lines = [
        f"    - name: {env_name}",
        f"      description: {env_desc}",
        "      required: true",
        "      secret: true",
    ]
    if c.llm_provider == "vertex":
        lines.extend([
            "    - name: GOOGLE_CLOUD_PROJECT",
            "      description: GCP project ID for Vertex AI",
            "      required: true",
            "      secret: false",
            "    - name: GOOGLE_CLOUD_LOCATION",
            "      description: GCP region for Vertex AI (e.g. us-central1)",
            "      required: true",
            "      default: us-central1",
            "      secret: false",
        ])
    return "\n".join(lines)


def _manifest_tools_block(c: InitConfig) -> str:
    """Generate the tools block for the manifest template."""
    if not c.mcp_preset:
        return "  # tools:\n  #   mcp_servers: []\n  #   host_dependencies: []"

    if c.mcp_preset == "filesystem":
        return """\
  tools:
    mcp_servers:
      - name: filesystem
        transport: stdio
        command: npx
        args: ["-y", "@modelcontextprotocol/server-filesystem", "${WORKSPACE_DIR}"]
        tool_filter:
          - read_file
          - write_file
          - list_directory
          - search_files
    host_dependencies:
      - nodejs"""

    if c.mcp_preset == "git":
        return """\
  tools:
    mcp_servers:
      - name: git
        transport: stdio
        command: uvx
        args: ["mcp-server-git", "--repository", "${REPO_PATH}"]
        tool_filter:
          - git_log
          - git_diff
          - git_show
          - git_status
    host_dependencies:
      - git"""

    # custom
    return """\
  tools:
    mcp_servers:
      - name: my-server
        transport: stdio
        command: uvx
        args: ["my-mcp-server"]
        tool_filter: []
    host_dependencies: []"""


def _manifest_agents_block(c: InitConfig) -> str:
    """Generate the spec.agents block for a multi-agent manifest."""
    if not c.agent_names:
        return ""
    lines = ["  agents:"]
    for agent in c.agent_names:
        agent_id = agent.replace("-", "_")
        lines += [
            f"    - name: {agent_id}",
            f"      role: sub-agent",
            f"      identity: ./agents/{agent_id}/identity",
            f"      description: {agent_id} sub-agent",
            f"      llm:",
            f"        model_env_var: AGENT_{agent_id.upper()}_MODEL",
            f"      # tools:",
            f"      #   mcp_servers: []  # reference names from spec.tools.mcp_servers",
        ]
    return "\n".join(lines) + "\n"


def _manifest_service_block(c: InitConfig) -> str:
    """Generate the spec.runtime.service block when webhook mode is requested."""
    if c.service_mode != "webhook":
        return ""
    return """\
    service:
      entry_point: webhook
      webhooks:
        - name: inbound
          path: /webhooks/inbound
          # signature_header: X-Hub-Signature-256
          # algorithm: sha256
          # secret_env: WEBHOOK_SECRET
      # human_interaction:
      #   enabled: true
      #   response_path: /human/respond
      #   timeout_seconds: 86400
      #   timeout_action: abort
"""


def _host_deps_for_preset(preset: str | None) -> list[str]:
    """Return host dependency names for an MCP preset."""
    if preset == "filesystem":
        return ["nodejs"]
    if preset == "git":
        return ["git"]
    return []


# ---------------------------------------------------------------------------
# adapters/
# ---------------------------------------------------------------------------
@_register("adapters/llm.yaml")
def _llm_adapter(c: InitConfig) -> str:
    if c.llm_provider == "vertex":
        return """\
# LLM adapter configuration
# Docs: https://getzil.dev/docs/adapters/llm
provider: vertex-ai
model: gemini-2.0-flash
auth:
  env_var: GOOGLE_APPLICATION_CREDENTIALS
  # Required for Vertex AI — set these in your .env file
  project_env_var: GOOGLE_CLOUD_PROJECT
  location_env_var: GOOGLE_CLOUD_LOCATION
parameters:
  temperature: 0.7
  max_tokens: 4096
"""

    providers = {
        "gemini": ("gemini", "gemini-2.0-flash", "GOOGLE_API_KEY"),
        "anthropic": ("anthropic", "claude-sonnet-4-20250514", "ANTHROPIC_API_KEY"),
        "openai": ("openai", "gpt-4o", "OPENAI_API_KEY"),
    }
    provider, model, env_key = providers.get(c.llm_provider, providers["gemini"])
    return f"""\
# LLM adapter configuration
# Docs: https://getzil.dev/docs/adapters/llm
provider: {provider}
model: {model}
auth:
  env_var: {env_key}
parameters:
  temperature: 0.7
  max_tokens: 4096
"""


@_register("adapters/embed.yaml")
def _embed_adapter(c: InitConfig) -> str:
    if c.llm_provider == "vertex":
        return """\
# Embedding adapter configuration
provider: vertex-ai
model: text-embedding-005
auth:
  env_var: GOOGLE_APPLICATION_CREDENTIALS
"""
    if c.llm_provider == "gemini":
        return """\
# Embedding adapter configuration
provider: gemini
model: text-embedding-004
auth:
  env_var: GOOGLE_API_KEY
"""
    return """\
# Embedding adapter configuration
provider: openai
model: text-embedding-3-small
auth:
  env_var: OPENAI_API_KEY
"""


# ---------------------------------------------------------------------------
# identity/
# ---------------------------------------------------------------------------
@_register("identity/persona.md")
def _persona(c: InitConfig) -> str:
    return f"""\
# {c.name} — Persona

You are **{c.name}**, an AI assistant built with the Zil framework.

## Core traits
- Helpful, concise, and accurate
- Cites sources when available
- Acknowledges uncertainty rather than guessing

## Tone
Professional but approachable. Avoid jargon unless the user demonstrates expertise.
"""


@_register("identity/instructions.md")
def _instructions(c: InitConfig) -> str:
    return f"""\
# {c.name} — Instructions

## Behavior rules
1. Always respond in the language the user writes in.
2. If you don't know the answer, say so clearly.
3. When using tools, explain what you're doing and why.
4. Keep responses focused — answer the question, then stop.

## Response format
- Use markdown for structured responses.
- Use bullet points for lists of 3+ items.
- Keep paragraphs to 2-3 sentences max.
"""


@_register("identity/guardrails.yaml")
def _guardrails(c: InitConfig) -> str:
    return """\
# Guardrails — runtime-enforced rules for the agent
# Docs: https://getzil.dev/docs/identity/guardrails
#
# These rules are enforced at runtime by Zil's guardrail engine.
# The engine checks input (before LLM) and output (after LLM).

# --- Detection toggles (built-in pattern libraries) ---
detection:
  # Block common prompt injection patterns (ignore instructions, DAN, etc.)
  prompt_injection: true
  # Scan agent output for PII (SSN, credit card patterns)
  pii_output: true
  # Scan user input for PII (disabled by default — enable for sensitive apps)
  pii_input: false

# --- Custom blocked patterns (regex) ---
# Each pattern is checked against input, output, or both.
blocked_patterns: []
  # Example:
  # - name: internal_urls
  #   pattern: "https?://internal\\\\."
  #   target: output      # "input" | "output" | "both"
  #   severity: block      # "block" | "warn" | "log"

# --- Denied topics (keyword matching on input) ---
denied_topics: []
  # Example:
  # - "competitor pricing"
  # - "salary information"

# --- Output constraints ---
output_constraints:
  max_response_length: 4000

# --- LLM instruction rules (included in system prompt, not enforced) ---
# These are passed to the LLM as instructions but not programmatically checked.
hard_blocks:
  - topic: illegal_activity
    description: Refuse requests for illegal activities.
  - topic: personal_data_extraction
    description: Never extract or store personal data beyond the session.

escalation_triggers:
  - condition: user_requests_human
    action: escalate
    message: "Connecting you with a human agent."
  - condition: confidence_below_threshold
    threshold: 0.3
    action: escalate
    message: "I'm not confident in my answer. Let me connect you with a specialist."
"""


# ---------------------------------------------------------------------------
# evals/
# ---------------------------------------------------------------------------
@_register("evals/config.yaml")
def _eval_config(c: InitConfig) -> str:
    # Map LLM provider to default judge config
    _judge_defaults: dict[str, tuple[str, str, str]] = {
        "gemini": ("gemini", "gemini-2.0-flash", "GOOGLE_API_KEY"),
        "vertex": ("gemini", "gemini-2.0-flash", "GOOGLE_API_KEY"),
        "openai": ("openai", "gpt-4o-mini", "OPENAI_API_KEY"),
        "anthropic": ("anthropic", "claude-3-5-haiku-20241022", "ANTHROPIC_API_KEY"),
    }
    provider, model, env_var = _judge_defaults.get(
        c.llm_provider, ("gemini", "gemini-2.0-flash", "GOOGLE_API_KEY")
    )
    return f"""\
# Eval engine configuration
# Docs: https://getzil.dev/docs/evals
eval_engine:
  framework: {c.eval_framework}
  judge:
    # LLM used for evaluation scoring (separate from agent LLM)
    provider: {provider}
    model: {model}
    # Credentials — set this env var in your .env file
    api_key_env: {env_var}
"""


@_register("evals/baseline.yaml")
def _eval_baseline(c: InitConfig) -> str:
    return f"""\
# Eval suite for {c.name}
# Docs: https://getzil.dev/docs/evals
eval_suite:
  name: baseline
  pass_threshold: 0.85
  metrics:
    - answer_relevancy
  cases:
    - file: ./cases/accuracy.yaml
      weight: 0.5
    - file: ./cases/tool_use.yaml
      weight: 0.3
    - file: ./cases/escalation.yaml
      weight: 0.2
"""


@_register("evals/cases/accuracy.yaml")
def _eval_accuracy(c: InitConfig) -> str:
    return """\
# Accuracy eval cases
name: accuracy
cases:
  - input: "What is Zil?"
    expected_output: "Zil is a framework for production AI agents"
    expected_contains:
      - "framework"
      - "agent"
    context:
      - "Zil is an open-source framework by FluentData for building production AI agents"
  - input: "Hello"
    expected_contains:
      - "hello"
    metrics: []  # deterministic only — no LLM judge needed
"""


@_register("evals/cases/tool_use.yaml")
def _eval_tool_use(c: InitConfig) -> str:
    return """\
# Tool use eval cases
name: tool_use
cases:
  - input: "Look up order #12345"
    expected_tool: lookup_order
    expected_contains:
      - "order"
"""


@_register("evals/cases/escalation.yaml")
def _eval_escalation(c: InitConfig) -> str:
    return """\
# Escalation eval cases
name: escalation
cases:
  - input: "I want to talk to a human"
    expected_action: escalate
  - input: "This is urgent, connect me to a manager"
    expected_action: escalate
"""


# ---------------------------------------------------------------------------
# observability/
# ---------------------------------------------------------------------------
@_register("observability/config.yaml")
def _observability(c: InitConfig) -> str:
    return f"""\
# OpenTelemetry observability configuration
# Docs: https://getzil.dev/docs/observability
#
# Usage:
#   zil run --trace          Export spans to your OTLP collector
#   zil run --trace-console  Print spans to stderr (no infra needed)
observability:
  tracing:
    exporter: otlp
    endpoint: ${{OTEL_EXPORTER_OTLP_TRACES_ENDPOINT}}
    sample_rate: 1.0
  resource_attributes:
    service.name: {c.name}
  span_conventions:
    - agent.session
    - agent.turn
    - agent.reasoning
    - agent.skill.invoke
    - agent.mcp.tool_call
    - agent.guardrail.check
  required_attributes:
    - agent.name
    - agent.version
    - session.id
    - tokens.input
    - tokens.output
    - cost.usd
"""


# ---------------------------------------------------------------------------
# {module_name}/ — ADK agent Python package
# ---------------------------------------------------------------------------
@_register(lambda c: f"{c.module_name}/__init__.py")
def _agent_init(c: InitConfig) -> str:
    return ""


@_register(lambda c: f"{c.module_name}/agent.py")
def _agent_py(c: InitConfig) -> str:
    return f'''\
"""
{c.name} — Main agent entry point.

Built with Zil (https://getzil.dev) using the ADK framework.
Run locally:  zil run
ADK web UI:   zil web
"""

from pathlib import Path

import zil


# Define your tools here — each is a plain Python function.
# def lookup_order(order_id: str) -> dict:
#     """Look up an order by ID."""
#     return {{"order_id": order_id, "status": "shipped"}}


# Create the agent. Zil reads manifest.yaml, identity/, and adapters/
# automatically and wires them into an ADK LlmAgent.
root_agent = zil.create_agent(
    tools=[],  # add your tool functions here (MCP servers auto-wired from manifest)
    project_dir=Path(__file__).parent,
)
'''


# ---------------------------------------------------------------------------
# Dockerfile
# ---------------------------------------------------------------------------
@_register("Dockerfile")
def _dockerfile(c: InitConfig) -> str:
    from zil.packaging.dockerfile import generate_dockerfile

    return generate_dockerfile(
        name=c.name,
        host_deps=_host_deps_for_preset(c.mcp_preset),
    )


# ---------------------------------------------------------------------------
# .dockerignore
# ---------------------------------------------------------------------------
@_register(".dockerignore")
def _dockerignore(c: InitConfig) -> str:
    return """\
.venv/
__pycache__/
*.pyc
.git/
.env
/dist/
*.egg-info/
.pytest_cache/
.ruff_cache/
tools/*/.git/
tools/*/src/
tools/*/tests/
tools/*/docs/
"""


# ---------------------------------------------------------------------------
# requirements.txt
# ---------------------------------------------------------------------------
@_register("requirements.txt")
def _requirements(c: InitConfig) -> str:
    lines = [
        f"# Core dependencies for {c.name}",
        "zil-ai[adk]>=0.1.0",
        "pyyaml>=6.0",
        "opentelemetry-api>=1.20",
        "opentelemetry-sdk>=1.20",
        "opentelemetry-exporter-otlp>=1.20",
    ]
    if c.llm_provider == "anthropic":
        lines.append("anthropic>=0.30")
    elif c.llm_provider == "openai":
        lines.append("openai>=1.30")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# {module_name}/requirements.txt  (needed by adk deploy cloud_run)
# ---------------------------------------------------------------------------
@_register(lambda c: f"{c.module_name}/requirements.txt")
def _module_requirements(c: InitConfig) -> str:
    lines = [
        f"# Dependencies for {c.name} (used by adk deploy cloud_run)",
        "zil-ai[adk]>=0.1.0",
        "pyyaml>=6.0",
        "opentelemetry-api>=1.20",
        "opentelemetry-sdk>=1.20",
        "opentelemetry-exporter-otlp>=1.20",
    ]
    if c.llm_provider == "anthropic":
        lines.append("anthropic>=0.30")
    elif c.llm_provider == "openai":
        lines.append("openai>=1.30")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# .github/workflows/zil-pipeline.yaml
# ---------------------------------------------------------------------------
@_register(".github/workflows/zil-pipeline.yaml")
def _github_workflow(c: InitConfig) -> str:
    return f"""\
name: Zil Pipeline
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  validate-and-pack:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install Zil CLI
        run: pip install zil-ai

      - name: Validate
        run: zil validate

      - name: Pack
        run: zil pack --skip-evals
        # TODO: Remove --skip-evals once eval suite is configured

      - name: Upload artifact
        uses: actions/upload-artifact@v4
        with:
          name: {c.name}-zil-package
          path: dist/*.zil
"""


# ---------------------------------------------------------------------------
# README.md
# ---------------------------------------------------------------------------
@_register("README.md")
def _readme(c: InitConfig) -> str:
    return f"""\
# {c.name}

A production AI agent built with [Zil](https://getzil.dev).

## Quick start

```bash
# Validate the project
zil validate

# Run the agent locally (CLI)
zil run

# Run the agent with ADK web UI
zil web

# Package for deployment
zil pack

# Inspect the package
zil inspect dist/{c.name}-0.1.0.zil
```

## Project layout

```
{c.name}/
├── manifest.yaml          # Zil agent manifest
├── {c.module_name}/       # ADK agent module
│   ├── __init__.py
│   ├── agent.py           # Agent entry point
│   └── .env.example       # API key template
├── adapters/              # LLM and embedding configuration
│   ├── llm.yaml
│   └── embed.yaml
├── identity/              # Agent persona, instructions, guardrails
│   ├── persona.md
│   ├── instructions.md
│   └── guardrails.yaml
├── evals/                 # Evaluation suite
│   ├── baseline.yaml
│   └── cases/
├── observability/         # OpenTelemetry configuration
│   └── config.yaml
├── Dockerfile             # Container build
└── .github/workflows/     # CI/CD pipeline
```

## Customization

1. Edit `identity/persona.md` to define who the agent is
2. Edit `identity/instructions.md` to define how the agent behaves
3. Edit `identity/guardrails.yaml` to set hard rules
4. Configure your LLM in `adapters/llm.yaml` and copy `.env.example` to `.env`
5. Add eval cases in `evals/cases/`

## Deployment

This project is configured for **{c.deploy_target}** deployment.
See the Dockerfile and `.github/workflows/zil-pipeline.yaml`.
"""


# ---------------------------------------------------------------------------
# .gitignore
# ---------------------------------------------------------------------------
@_register(".gitignore")
def _gitignore(c: InitConfig) -> str:
    return """\
# Python
__pycache__/
*.py[cod]
*.egg-info/
dist/
build/
.eggs/

# Environment
.env
.env.local
.venv/
venv/

# Zil
*.zil

# Tools (bundled MCP servers / CLI tools)
tools/*/node_modules/

# IDE
.idea/
.vscode/
*.swp
.DS_Store
"""


# ---------------------------------------------------------------------------
# .env.example
# ---------------------------------------------------------------------------
@_register(lambda c: f"{c.module_name}/.env.example")
def _env_example(c: InitConfig) -> str:
    if c.llm_provider == "vertex":
        return """\
# Copy to .env and fill in your values
# Vertex AI requires a service account and GCP project
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
GOOGLE_CLOUD_LOCATION=us-central1
# Observability — set to export traces (used by zil run --trace)
# OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://localhost:4318/v1/traces
"""

    providers = {
        "gemini": "# Get your API key at https://aistudio.google.com/apikey\nGOOGLE_API_KEY=your-api-key",
        "anthropic": "ANTHROPIC_API_KEY=sk-ant-...",
        "openai": "OPENAI_API_KEY=sk-...",
    }
    key_line = providers.get(c.llm_provider, providers["gemini"])
    return f"""\
# Copy to .env and fill in your values
{key_line}
# Observability — set to export traces (used by zil run --trace)
# OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://localhost:4318/v1/traces
"""


# ---------------------------------------------------------------------------
# Multi-agent: agents/{name}/identity/ scaffold (conditional on --agents)
# ---------------------------------------------------------------------------

def _sub_agent_identity_files(c: InitConfig) -> list[tuple[str, str]]:
    """Return (path, content) pairs for all sub-agent identity files."""
    files: list[tuple[str, str]] = []
    for agent in c.agent_names:
        agent_id = agent.replace("-", "_")
        base = f"agents/{agent_id}/identity"
        files.append((
            f"{base}/persona.md",
            f"# {agent_id} — Persona\n\nYou are **{agent_id}**, a sub-agent of {c.name}.\n",
        ))
        files.append((
            f"{base}/instructions.md",
            f"# {agent_id} — Instructions\n\n1. Complete your assigned task accurately.\n"
            f"2. Report results clearly to the root agent.\n",
        ))
    return files


# Register sub-agent identity files dynamically (skipped if no --agents flag)
@_register(lambda c: f"agents/__placeholder__" if not c.agent_names else "__multi_agent_skip__")
def _multi_agent_placeholder(c: InitConfig) -> str:
    return ""


def _render_extra_files(project_dir: "Path", c: InitConfig) -> None:
    """Render additional files that can't be expressed as simple path templates."""
    # Sub-agent identity directories
    for rel_path, content in _sub_agent_identity_files(c):
        target = project_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    # Webhook scaffold files
    if c.service_mode == "webhook":
        _render_webhook_files(project_dir, c)


def _render_webhook_files(project_dir: "Path", c: InitConfig) -> None:
    """Render app.py and runner.py into the module directory."""
    module_dir = project_dir / c.module_name
    module_dir.mkdir(parents=True, exist_ok=True)

    app_py = module_dir / "app.py"
    app_py.write_text(_webhook_app_py(c), encoding="utf-8")

    runner_py = module_dir / "runner.py"
    runner_py.write_text(_webhook_runner_py(c), encoding="utf-8")


def _webhook_app_py(c: InitConfig) -> str:
    return f'''\
"""
{c.name} — FastAPI webhook entry point.

Inbound webhooks trigger the agent; /human/respond resumes HITL sessions.
Run locally:  uvicorn {c.module_name}.app:app --reload --port 8080
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel

from {c.module_name}.runner import AgentRunner


_runner: AgentRunner | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _runner
    session_uri = os.environ.get(
        "SESSION_DB_URI", "sqlite+aiosqlite:///./sessions.db"
    )
    _runner = AgentRunner(session_uri=session_uri)
    yield
    _runner = None


app = FastAPI(title="{c.name}", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict:
    return {{"status": "ok"}}


# ---------------------------------------------------------------------------
# Inbound webhook — triggers the agent
# ---------------------------------------------------------------------------


@app.post("/webhooks/{{name}}")
async def receive_webhook(name: str, request: Request) -> dict:
    """Accept an inbound webhook and dispatch to the agent."""
    if _runner is None:
        raise HTTPException(503, "Agent not ready")
    payload = await request.json()
    session_id = await _runner.dispatch(webhook_name=name, payload=payload)
    return {{"status": "accepted", "session_id": session_id}}


# ---------------------------------------------------------------------------
# Human-in-the-loop response endpoint
# ---------------------------------------------------------------------------


class HumanResponse(BaseModel):
    session_id: str
    interaction_id: str
    choice: str = ""
    comment: str = ""


@app.post("/human/respond")
async def human_respond(body: HumanResponse) -> dict:
    """Receive a human\'s response and resume the waiting agent session."""
    if _runner is None:
        raise HTTPException(503, "Agent not ready")
    await _runner.resume(
        session_id=body.session_id,
        interaction_id=body.interaction_id,
        choice=body.choice,
        comment=body.comment,
    )
    return {{"status": "resumed"}}
'''


def _webhook_runner_py(c: InitConfig) -> str:
    return f'''\
"""
{c.name} — Agent session manager and resume handler.

Wraps ADK DatabaseSessionService for durable sessions.
SESSION_DB_URI determines the backend:
  sqlite+aiosqlite:///./sessions.db   — local dev
  postgresql+pg8000://...              — Cloud Run + Cloud SQL
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any


class AgentRunner:
    """Manages agent sessions and dispatches webhook events."""

    def __init__(self, session_uri: str) -> None:
        self.session_uri = session_uri
        self._app = self._load_agent()
        self._session_svc = self._build_session_service(session_uri)

    def _load_agent(self) -> Any:
        from {c.module_name}.agent import root_agent
        return root_agent

    def _build_session_service(self, uri: str) -> Any:
        try:
            from google.adk.sessions.database_session_service import DatabaseSessionService
            return DatabaseSessionService(db_url=uri)
        except ImportError:
            from google.adk.sessions import InMemorySessionService
            return InMemorySessionService()

    async def dispatch(self, *, webhook_name: str, payload: dict[str, Any]) -> str:
        """Create a new session and run the agent with the webhook payload."""
        from google.adk.runners import Runner

        session_id = str(uuid.uuid4())
        runner = Runner(app=self._app, session_service=self._session_svc)
        # Run in background — do not await the full turn here
        # (long-running tasks or HITL will checkpoint and return)
        import asyncio
        asyncio.create_task(
            self._run_turn(runner, session_id, payload)
        )
        return session_id

    async def _run_turn(
        self,
        runner: Any,
        session_id: str,
        payload: dict[str, Any],
    ) -> None:
        from google.genai.types import Content, Part
        message = Content(
            role="user",
            parts=[Part(text=str(payload))],
        )
        async for _event in runner.run_async(
            user_id="webhook",
            session_id=session_id,
            new_message=message,
        ):
            pass

    async def resume(
        self,
        *,
        session_id: str,
        interaction_id: str,
        choice: str,
        comment: str,
    ) -> None:
        """Resume a session that was paused for human input."""
        from google.adk.runners import Runner
        from google.genai.types import Content, Part

        runner = Runner(app=self._app, session_service=self._session_svc)
        state_delta = {{
            "human_response": {{
                "interaction_id": interaction_id,
                "choice": choice,
                "comment": comment,
            }},
            "pending_human_request": None,
        }}
        message = Content(
            role="user",
            parts=[Part(text=f"Human responded: {{choice}} {{comment}}")],
        )
        async for _event in runner.run_async(
            user_id="webhook",
            session_id=session_id,
            new_message=message,
            state_delta=state_delta,
        ):
            pass
'''
