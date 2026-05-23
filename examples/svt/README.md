# SVT — Software Velocity Team

A multi-agent system built with [Zil](https://getzil.dev) that takes a Jira
task, produces an implementation plan, executes it, and opens a pull request —
all autonomously.

## Architecture

SVT uses a three-agent hierarchy:

```
┌─────────────────────────────────────────────┐
│  VTL — Virtual Team Lead (root agent)       │
│  Receives Jira tasks, delegates to:         │
│                                             │
│  ┌───────────────┐  ┌───────────────────┐   │
│  │  VTA           │  │  VTD              │   │
│  │  Architect     │  │  Developer        │   │
│  │  Plans tasks   │  │  Executes plans   │   │
│  │  (read-only)   │  │  (write + PR)     │   │
│  └───────────────┘  └───────────────────┘   │
└─────────────────────────────────────────────┘
```

- **VTL** (Virtual Team Lead) — orchestrator. Receives a Jira issue key,
  dispatches VTA to plan, presents the plan for review, then dispatches VTD
  to execute. Has no code tools — only delegates.
- **VTA** (Virtual Team Architect) — reads the Jira task, explores the repo
  with `grep_files` and `read_file`, and writes a structured plan to
  `<KEY>-plan.md`. Strict 5 tool-call budget.
- **VTD** (Virtual Team Developer) — reads the approved plan, implements it
  step-by-step with `write_file` and `run_shell_command`, runs tests, and
  opens a PR via the `fd-submit-changes` skill.

## Features

- **Two-phase interactive flow** — plan → review → execute. The user can
  request corrections before implementation begins.
- **Jira integration** — via MCP (Model Context Protocol) for real-time
  issue queries, and a REST API fallback for prompt context.
- **Sandboxed workspace** — each task gets an isolated `git clone`. File
  tools enforce path traversal protection via `ContextVar`.
- **Shell allowlist** — only permitted binaries can run; dangerous flags
  (`--force`, `rm -rf`) are blocked.
- **Skills** — reusable procedure documents (SKILL.md) guide the agents
  through repo exploration, testing, formatting, and PR submission.
- **Webhook endpoint** — receives Jira webhooks with HMAC signature
  verification for production use.
- **Cloud Run ready** — includes a Dockerfile with runtime dependencies
  (git, Node.js, pnpm, gh CLI).

## Quick start

### 1. Install Zil

```bash
pip install 'zil-ai[adk]'
```

### 2. Configure environment

```bash
cd examples/svt
cp svt/.env.example svt/.env
# Edit svt/.env with your API keys and configuration
```

Required variables:
- `GOOGLE_API_KEY` — Gemini API key
- `GITHUB_REPO_URL` — target repository URL
- `GITHUB_TOKEN` — GitHub PAT with repo access
- `JIRA_BASE_URL` — Jira instance URL (e.g. `https://your-org.atlassian.net`)
- `JIRA_API_TOKEN` — Atlassian API token
- `JIRA_USER_EMAIL` — your Jira email

### 3. Run locally

```bash
# Validate the project
zil validate

# Run with ADK web UI
zil web

# Run with Docker (includes all runtime deps)
zil web --docker
```

### 4. Use the agent

In the ADK web UI, type:

```
work on PROJ-123
```

The agent will:
1. Clone your repo
2. Run VTA to explore the codebase and produce a plan
3. Present the plan for your review

When satisfied, type `go!` to trigger VTD execution.

## Deploy to Cloud Run

```bash
# Build and push the image
zil pack
zil push dist/svt-0.1.0.zil --registry=REGION-docker.pkg.dev/PROJECT/REPO/svt:0.1.0

# Deploy (2Gi recommended for MCP + SkillToolset)
zil deploy \
  --from=REGION-docker.pkg.dev/PROJECT/REPO/svt:0.1.0 \
  --project=PROJECT --region=REGION \
  --service=svt --memory=2Gi \
  --env-file=svt/.env \
  --with-ui --skip-evals --allow-unauthenticated
```

## Project layout

```
svt/
├── manifest.yaml              # Zil agent manifest (models, tools, MCP, skills)
├── requirements.txt           # Top-level Python deps
├── Dockerfile                 # Container with runtime deps (git, node, gh, etc.)
├── identity/                  # VTL (root agent) persona + instructions
│   ├── persona.md
│   ├── instructions.md
│   └── guardrails.yaml
├── agents/                    # Sub-agent identities
│   ├── vta/identity/          # VTA persona + planning instructions
│   └── vtd/identity/          # VTD persona + execution instructions
├── svt/                       # Python module (ADK entry point)
│   ├── agent.py               # Builds VTL + injects tools into sub-agents
│   ├── app.py                 # FastAPI webhook server (Jira + debug)
│   ├── runner.py              # Workspace-per-task orchestrator
│   ├── tools/                 # Inline tools (filesystem, shell, task)
│   │   ├── filesystem.py      # Sandboxed read/write/grep with ContextVar
│   │   ├── shell.py           # Allowlisted shell execution
│   │   └── task.py            # Two-phase plan/execute tools
│   ├── requirements.txt       # Module-level deps (used by adk deploy)
│   └── .env.example           # Template for environment variables
├── skills/                    # Reusable agent skills (SKILL.md)
│   ├── fd-explore-repo/
│   ├── fd-read-jira-task/
│   ├── fd-submit-changes/
│   ├── fd-run-tests/
│   └── fd-format-code/
├── adapters/                  # LLM and embedding configuration
├── evals/                     # Evaluation suite (deepeval)
└── observability/             # OpenTelemetry configuration
```

## Key design decisions

### Tool injection via `agent.py`

Zil's `create_agent()` handles manifest parsing, model selection, MCP wiring,
and SkillToolset loading. The `agent.py` module adds inline Python tools
(filesystem, shell) post-hoc by walking the sub-agent tree:

```python
vtl = zil.create_agent(project_dir=_PROJECT_DIR, enable_mcp=True)
# VTA gets read-only tools; VTD gets the full suite
_inject_sub_agent_tools(vtl)
```

This separation keeps the manifest declarative while allowing Python-level
tool customization.

### Workspace isolation

Each task gets a fresh `git clone` under `/tmp/workspaces/`. A `ContextVar`
ensures that `read_file`, `write_file`, and `run_shell_command` are always
scoped to the active workspace — preventing cross-task contamination.

### Reference clone optimization

The first repo clone is stored as a bare reference. Subsequent clones use
`git clone --reference`, reducing clone time from ~10s to <1s.

## Model recommendations

- **Gemini 3.5 Flash** — best balance of speed, cost, and function call
  reliability. Recommended for all three agents.
- **Gemini 2.5 Pro** — stronger reasoning for VTA if plans need more depth.
- Model overrides via env vars: `AGENT_VTL_MODEL`, `AGENT_VTA_MODEL`,
  `AGENT_VTD_MODEL`.

## License

Apache-2.0
