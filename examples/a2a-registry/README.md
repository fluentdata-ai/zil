# a2a-registry

A **reference registry-of-record** for A2A discovery, demonstrating the
*registry mode* of [ZIL-RFC-005 §9](../../backlog/ZIL-RFC-005-multi-agent-topology-and-a2a.md).

In [`a2a-collaboration`](../a2a-collaboration) the caller resolves its peer from
a hard-coded URL (`url: ${WEATHER_AGENT_URL}`). That works, but in a real fleet
you don't want every caller to know every peer's address. Instead, peers are
declared by **logical name** and a registry maps name → deployed URL:

```
                      ┌─────────────────────────┐
   ref: zil://fleet/weather-agent               │ registry service          │
trip-planner ──resolve(name)──▶ GET /agents/weather-agent ──▶ url + Agent Card│
     │                          └─────────────────────────┘
     └────────────── A2A (JSON-RPC) ──────────────▶ weather-agent (the resolved URL)
```

The caller still talks **directly** to the peer over A2A — the registry is only
consulted to discover *where* the peer lives. There is no broker on the call path.

> **This is a reference example, not a production service.** It keeps the fleet
> map in memory (seeded from `agents.json`), with no auth, persistence, or
> multi-tenancy. The production registry-of-record (workspace-scoped, datastore
> backed, GCP ID-token auth) belongs in the platform runtime (RFC-007). What's
> reusable here is the **HTTP contract** below, which `HttpRegistryResolver`
> speaks.

## The contract

`HttpRegistryResolver` (in `zil.collaboration.discovery`) resolves a
`ref: zil://fleet/<name>` peer by calling a registry base URL:

| Method & path          | Returns                                             |
| ---------------------- | --------------------------------------------------- |
| `GET /agents`          | `{"agents": [{"name", "url", "skills"}]}`           |
| `GET /agents/{name}`   | `{"name", "url", "card"}` — `card` may be `null`    |
| `POST /agents`         | register/replace `{"name", "url"}` (demo only)      |
| `GET /health`          | `{"status": "ok"}`                                  |

The resolver reads `url` (required) and, if present, the embedded `card` (to
skip a second round-trip). When `card` is `null` it falls back to fetching the
peer's own `/.well-known/agent-card.json`.

## Quick start

Three shells from the repo root.

### 1. Start the weather-agent (callee)

```bash
cd examples/a2a-collaboration/weather-agent
zil serve --port 8001
```

### 2. Start the registry (seeded with `weather-agent → http://localhost:8001`)

```bash
pip install "zil-ai[serve]"
python examples/a2a-registry/registry_service.py --port 8500

# Verify resolution:
curl -s http://localhost:8500/agents/weather-agent | jq '{url, skills: .card.skills[].id}'
```

### 3. Call the peer by name (no URL in the code)

```bash
ZIL_FLEET_REGISTRY_URL=http://localhost:8500 \
    python examples/a2a-registry/call_peer_via_registry.py
```

```
resolved : http://localhost:8001
status   : completed
forecast : [illustrative] Lisbon ...
blocked (as expected): skill 'delete-data' is not in the allowlist ['get-forecast'] for peer 'weather-agent'
```

## Registry mode in a manifest

To make an agent (e.g. the trip-planner) discover peers via the registry,
declare the collaborator with `ref` instead of `url`:

```yaml
spec:
  collaborators:
    - name: weather-agent
      ref: zil://fleet/weather-agent   # logical name resolved by the registry
      skills: [get-forecast]
      auth: gcp-id-token               # use real auth in production
```

Then point the agent at the registry and run it — `build_resolver()` picks
`HttpRegistryResolver` automatically when `ZIL_FLEET_REGISTRY_URL` is set:

```bash
export ZIL_FLEET_REGISTRY_URL=http://localhost:8500
zil run    # the ADK adapter wires the peer as a tool, resolved by name
```

In production the platform injects `ZIL_FLEET_REGISTRY_URL` into each deployed
agent's environment, so `ref:` peers resolve against the workspace registry with
no changes to agent code.

## Learn more

- [Multi-agent topology & A2A (RFC-005)](../../backlog/ZIL-RFC-005-multi-agent-topology-and-a2a.md)
- [`a2a-collaboration` example](../a2a-collaboration) — the URL-based baseline
