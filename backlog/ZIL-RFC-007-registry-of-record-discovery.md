# ZIL-RFC-007 — Registry-of-Record for A2A Discovery

| Field | Value |
|---|---|
| **Status** | Draft / Backlog |
| **Target component** | `zil-ai` discovery (`HttpRegistryResolver`, shipped), the registry **HTTP contract** (this doc), reference example (`examples/a2a-registry`), platform registry-of-record (out of tree — runtime/control-plane) |
| **Owner** | FluentData / Zil maintainers |
| **Zil version target** | post-v0.1 |
| **License** | Apache 2.0 |
| **Related** | **Extends** RFC-005 §9 (discovery & resolution). **Interfaces with** RFC-001 (agent identity / auth), RFC-011 (where peers are deployed). |
| **Document purpose** | Specify the minimal HTTP contract a registry-of-record exposes so that any conforming registry interoperates with Zil's `HttpRegistryResolver`. Keep the OSS surface infra-free; the stateful registry lives in the platform. |

---

## 1. Why

RFC-005 §9 establishes the discovery seam: a `PeerResolver` maps a `PeerRef`
(`ref: zil://fleet/<name>`) to a live `AgentCard`. RFC-005 deliberately ships
only static resolution and an in-process mapping, and defers the *auto-populated
registry of record* to this RFC, with one hard rule carried over:

> **No new registry in Zil core.** Zil ships a resolver and a contract, not a
> stateful registry service. The registry of record is a platform concern.

This RFC defines the **contract** between the resolver (OSS) and any registry
(reference example or production platform), so the two interoperate without Zil
core taking on infrastructure.

## 2. The contract

A registry is an HTTP service exposing, under a configurable base URL:

| Method & path        | Response body                                        | Notes |
|----------------------|------------------------------------------------------|-------|
| `GET /agents/{name}` | `{"name": str, "url": str, "card": object \| null}`  | Resolve one logical name. `404` if unknown. `url` is required; `card` is the peer's Agent Card if known, else `null`. |
| `GET /agents`        | `{"agents": [{"name", "url", "skills": [str]}]}`     | Enumerate discoverable agents (optional; for tooling/UX). |
| `GET /health`        | `{"status": "ok"}`                                   | Liveness. |
| `POST /agents`       | `{"name", "url"}`                                     | Registration. Optional; production registries auto-populate at deploy time and MAY omit this. |

Resolver behaviour (`zil.collaboration.discovery.HttpRegistryResolver`):

- Reads `ZIL_FLEET_REGISTRY_URL` (the base URL; `${ENV}` interpolation allowed).
- For a `ref: zil://fleet/<name>` peer, GETs `{base}/agents/{name}`, uses `url`,
  and prefers the embedded `card` (saving a round-trip). When `card` is `null`,
  falls back to fetching the peer's own `/.well-known/agent-card.json`.
- Plain `url:` peers bypass the registry entirely (mixed fleets work).
- `build_resolver(env)` selects `HttpRegistryResolver` when
  `ZIL_FLEET_REGISTRY_URL` is set, else the in-process `RegistryResolver`.

The least-authority skill allowlist (RFC-005 §10) is enforced **before** any
registry or network call, independent of how the peer is resolved.

## 3. Reference implementation

`examples/a2a-registry/registry_service.py` is a minimal, in-memory, no-auth
registry that implements §2. It is **reference only** — it demonstrates the
contract and lets the example fleet resolve peers by name. It is explicitly not
the production registry of record.

## 4. Production registry of record (out of tree — `composable-app`)

The production registry lives in the platform control-plane, not in Zil OSS.
**Decision: it lives in `zil-core` (the Next.js app that owns the agent
datastore), not in `zil-runtime`.** `zil-runtime` is a stateless Cloud Run
orchestrator with no database access; giving it direct access to the shared
Postgres would couple it to the whole app schema (a shared-database
antipattern), and a separate discovery store would add a third source of truth.
The authoritative "which agents exist + their URL" already lives in `zil-core`'s
`ZilAgent` rows (`status = ACTIVE`, `serviceUrl` populated post-deploy). Design:

- **Backed by the existing agent datastore.** The registry is a read/projection
  over `ZilAgent` (name, deployed `serviceUrl`, workspace) — not new storage.
  The endpoint returns `{name, url, card: null}`; the caller fetches the Agent
  Card itself over the authenticated A2A path, so skills need not be stored.
- **Workspace-scoped.** Resolution is tenant-isolated via the path
  (`/registry/<workspaceId>/agents/<name>`); the injected base URL carries the
  workspace, so the OSS resolver contract (`GET {base}/agents/{name}`) is
  unchanged.
- **Caller auth.** The endpoint accepts a logged-in session (UI) or a
  `ZIL_REGISTRY_TOKEN` bearer (agent→registry); the OSS resolver sends it via
  `ZIL_FLEET_REGISTRY_TOKEN`.
- **`gcp-id-token` for the A2A call itself.** Cross-agent calls authenticate
  with Cloud Run service-to-service ID tokens (RFC-005 `auth: gcp-id-token`);
  the registry only returns target URLs, IAM enforces invocation.
- **Injected at deploy.** `zil-core`'s deploy route sets `ZIL_FLEET_REGISTRY_URL`
  (and `ZIL_FLEET_REGISTRY_TOKEN`) in each deployed agent's environment so `ref:`
  peers resolve in production with zero agent code changes.
- **Freshness (future).** If `ZilAgent.serviceUrl/status` drifts from reality,
  add a Cloud Run reconciliation/liveness check in `zil-runtime` behind the same
  contract — without changing the resolver or the registry's HTTP shape.

## 5. Non-goals

- A broker/orchestrator on the call path — calls remain direct agent→peer over A2A.
- A stateful registry in Zil OSS.
- A new manifest surface — `spec.collaborators` (`ref:`) is unchanged from RFC-005.

## 6. Acceptance criteria

1. A `ref:` collaborator resolves via `HttpRegistryResolver` against any service
   implementing §2 and behaves identically to a `url:` peer. ✅ (OSS shipped)
2. The reference example resolves the `a2a-collaboration` fleet by name. ✅
3. The production registry auto-populates from the agent datastore, is
   workspace-scoped, and is injected into deployed agents. *(platform — pending)*
