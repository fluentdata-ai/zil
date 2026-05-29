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

## Working Flow

The SVT-Agent is designed to take a **loosely defined Jira ticket** and turn it
into a reviewed, implemented pull request. It doesn't just execute — it
**critiques, refines, and aligns on a spec** with the human before writing code.

```
┌─────────────┐       ┌──────────────────────┐       ┌─────────────┐
│  Human      │       │  SVT-Agent           │       │  Repo       │
│  (Jira)     │       │  (OpenHands)         │       │             │
└──────┬──────┘       └──────────┬───────────┘       └──────┬──────┘
       │                         │                          │
       │  1. Loose ticket        │                          │
       │─────────────────────────>                          │
       │                         │  2. Clone repo           │
       │                         │─────────────────────────>│
       │                         │  3. Read context bank    │
       │                         │<─────────────────────────│
       │                         │                          │
       │  4. Critique + questions│                          │
       │<─────────────────────────                          │
       │                         │                          │
       │  5. Answers/refinement  │                          │
       │─────────────────────────>                          │
       │                         │                          │
       │  6. Proposed spec       │                          │
       │<─────────────────────────                          │
       │                         │                          │
       │  7. "Approved"          │                          │
       │─────────────────────────>                          │
       │                         │  8. Commit spec + implement
       │                         │─────────────────────────>│
       │                         │  9. PR                   │
       │                         │─────────────────────────>│
```

### Phases

The agent's behavior is driven by `identity/persona.md` and
`identity/instructions.md`, which define three phases:

1. **Phase 0 — Spec Refinement** (when the ticket is loosely defined)
   - Reads the ticket, clones the repo, and loads the target repo's context bank
     (`.agents/context/`) and existing specs (`openspec/specs/`).
   - **Critiques** the ticket via a Jira comment: missing acceptance criteria,
     architectural questions, cross-package implications, edge cases.
   - Proposes a formal spec (following the repo's `spec-template.md`) and **stops**
     to wait for human approval.
   - On approval, commits the spec to `openspec/changes/<ticket>/` and proceeds.

2. **Phase 1 — Planning**
   - With clear acceptance criteria (or an approved spec), produces a detailed
     implementation plan and waits for approval.

3. **Phase 2 — Execution**
   - Implements the plan, runs tests, commits, and opens a pull request.

### Why this works

- **Session continuity:** the agent's workspace is tied to the session, so the
  repo cloned in step 2 persists across all turns — no re-cloning between the
  critique, refinement, and implementation phases.
- **Context-aware:** the agent reads the target repo's context bank before
  proposing anything, so its specs align with existing architecture and
  conventions.
- **Human-in-the-loop:** the agent stops at natural decision points (spec
  approval, plan approval) rather than running unattended end-to-end.

> **Note:** This flow assumes the target repo includes a context bank
> (`.agents/context/`) and OpenSpec specs (`openspec/`). See the
> `composable-app` repo for a reference setup.

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
