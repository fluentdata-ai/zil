# a2a-collaboration

Two Zil agents communicating over **A2A** (Agent-to-Agent), demonstrating
multi-agent topology from [ZIL-RFC-005](../../backlog/ZIL-RFC-005-multi-agent-topology-and-a2a.md).

- **`weather-agent/`** — the **callee/peer**. A weather specialist that advertises
  a `get-forecast` skill on its A2A Agent Card and is served by `zil serve`.
- **`trip-planner/`** — the **caller**. A planning agent that declares the weather
  agent in `spec.collaborators` and delegates weather questions to it over A2A.

```
trip-planner  ──A2A (JSON-RPC message/send)──▶  weather-agent
   caller                                          callee
   spec.collaborators:                          spec.skills:
     - name: weather-agent                         get-forecast  (advertised on Agent Card)
       skills: [get-forecast]
```

There is **no central broker** — the caller talks directly to the peer over A2A.

## What this demonstrates

- **`spec.collaborators`** — declaring a peer agent the caller may invoke.
- **Agent Card discovery** — the peer advertises real `spec.skills` at
  `/.well-known/agent-card.json`; the caller fetches and introspects it.
- **Least authority** — the `skills: [get-forecast]` allowlist is enforced
  *before* any network request; calling any other skill raises `SkillNotAllowedError`.
- **Context transfer policy** — `context_transfer` controls what crosses the
  trust boundary (`send: message_only`, `receive: artifacts`, `redact: [user_email]`).
- **Inter-agent auth** — `auth: none` for local dev; `bearer` / `gcp-id-token`
  for production (see below).
- **Two call paths** — automatic tool-wiring via the **ADK adapter**
  (`trip-planner`), and the **framework-neutral** `A2APeerClient` (`call_peer.py`).

## Quick start

### 1. Start the weather-agent (callee)

```bash
cd examples/a2a-collaboration/weather-agent
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt
cp weather_agent/.env.example weather_agent/.env   # add your GOOGLE_API_KEY

# Serve over A2A on port 8001. The Agent Card is at
# http://localhost:8001/.well-known/agent-card.json
zil serve --port 8001
```

Confirm the skill is advertised:

```bash
curl -s http://localhost:8001/.well-known/agent-card.json | jq '.skills[].id'
# "get-forecast"
```

### 2a. Call it directly with the native client (no framework needed)

```bash
# From the repo root, in another shell:
WEATHER_AGENT_URL=http://localhost:8001 \
    python examples/a2a-collaboration/call_peer.py
```

Expected output (forecast text is illustrative offline):

```
status   : completed
task_id  : <uuid>
forecast :
[illustrative] Lisbon ...
blocked (as expected): skill 'delete-data' is not in the allowlist ['get-forecast'] for peer 'weather-agent'
```

### 2b. Or run the trip-planner (ADK adapter auto-wires the peer as a tool)

```bash
cd examples/a2a-collaboration/trip-planner
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt
cp trip_planner/.env.example trip_planner/.env      # add GOOGLE_API_KEY
export WEATHER_AGENT_URL=http://localhost:8001

zil run     # then ask: "Plan a weekend trip to Lisbon — what should I pack?"
```

The trip-planner's LLM calls the `weather-agent` peer's `get-forecast` skill over
A2A and folds the forecast into its packing advice.

## Validate

```bash
# Offline structural validation (both agents)
zil validate --project-dir examples/a2a-collaboration/weather-agent
zil validate --project-dir examples/a2a-collaboration/trip-planner

# Online skill validation — with the weather-agent running, verify that the
# trip-planner's declared `get-forecast` skill is actually advertised by the peer:
WEATHER_AGENT_URL=http://localhost:8001 \
    zil validate --project-dir examples/a2a-collaboration/trip-planner --online
```

> The trip-planner uses `auth: none` for the local quickstart, which emits a
> validate **warning** (exit code 2) by design — unauthenticated inter-agent
> calls are flagged. This is expected for local development.

## Inspect the topology

```bash
zil topology --dir examples/a2a-collaboration
```

Renders the declared graph (`trip-planner → weather-agent`) and exits non-zero
if any cycles are detected.

## Production auth

Replace `auth: none` in `trip-planner/manifest.yaml` with one of:

- **`bearer`** — token from `ZIL_A2A_TOKEN_WEATHER_AGENT` (falls back to `ZIL_A2A_TOKEN`).
- **`gcp-id-token`** — audience-scoped Google ID token; pairs with a
  private-by-default Cloud Run deployment of the weather-agent.

## Learn more

- [Multi-agent topology & A2A (RFC-005)](../../backlog/ZIL-RFC-005-multi-agent-topology-and-a2a.md)
- [Documentation](https://getzil.dev/docs)
