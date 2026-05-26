# SVT Agent — OpenHands Backend

This is the SVT coding agent using the OpenHands framework backend,
served via `zil serve`. **No app.py needed.**

## Architecture

```
┌───────────────────────────────────────────┐
│  External (Jira webhooks, A2A clients)    │
├───────────────────────────────────────────┤
│  zil serve                                │
│  ├── POST /webhooks/jira (auto-wired)     │
│  ├── POST /tasks/send (A2A)              │
│  ├── POST /invoke (REST)                 │
│  └── GET /.well-known/agent.json         │
├───────────────────────────────────────────┤
│  zil.Session                              │
│  └── OpenHands Conversation API          │
├───────────────────────────────────────────┤
│  OpenHands Agent (shell, files, browser)  │
└───────────────────────────────────────────┘
```

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- An LLM API key (Anthropic by default — see `adapters/llm.yaml`)

## Setup

```bash
# Create a virtual environment and install dependencies
uv venv
source .venv/bin/activate
uv pip install 'zil-ai[serve,openhands]'

# Or, if developing from the local zil repo:
# uv pip install -e '/path/to/zil[serve,openhands]'
```

## Run locally

```bash
# Set env vars
export LLM_API_KEY=your-key-here

# Start the agent server
zil serve --project-dir .
```

## Invoke via REST

```bash
# Stateless invoke
curl -X POST http://localhost:8000/invoke \
  -H "Content-Type: application/json" \
  -d '{"message": "Work on ticket PROJ-123"}'

# A2A protocol
curl http://localhost:8000/.well-known/agent.json
```

## Deploy to Cloud Run

```bash
zil deploy --project-dir . --project my-gcp-project --region us-central1
```

This automatically uses the unified deploy path (`zil serve` as entrypoint)
since the framework is `openhands` (non-ADK).

## Comparison with ADK SVT

| Aspect | ADK SVT | OpenHands SVT |
|--------|---------|---------------|
| Agent code | `agent.py` + `runner.py` + `app.py` | **None** (just manifest + identity) |
| Framework imports | `google.adk.*` | **None** |
| Web server | Custom FastAPI app | `zil serve` (automatic) |
| Webhooks | Manual wiring | Manifest-declared |
| Deploy | `adk deploy cloud_run` | `gcloud run deploy --source` |
