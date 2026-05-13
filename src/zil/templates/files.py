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
  identity: ./identity
{evals_line}
{obs_line}
  env:
{env_vars}
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
    tools=[],  # add your tool functions here
    project_dir=Path(__file__).parent,
)
'''


# ---------------------------------------------------------------------------
# Dockerfile
# ---------------------------------------------------------------------------
@_register("Dockerfile")
def _dockerfile(c: InitConfig) -> str:
    return f"""\
# Multi-stage build for {c.name}
# Stage 1: dependencies
FROM python:3.12-slim AS deps
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: runtime
FROM python:3.12-slim
WORKDIR /app
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin/ /usr/local/bin/
COPY . .
EXPOSE 8000
CMD ["adk", "web", ".", "--port", "8000", "--host", "0.0.0.0"]
"""


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
dist/
*.egg-info/
.pytest_cache/
.ruff_cache/
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
