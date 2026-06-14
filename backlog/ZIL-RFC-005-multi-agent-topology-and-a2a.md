# ZIL-RFC-005 — Multi-Agent Topology & A2A Collaboration

| Field | Value |
|---|---|
| **Status** | Draft / Backlog |
| **Target component** | `zil-ai` collaboration contract (new), A2A **client** (new), `spec.collaborators` manifest block (new), `zil serve` Agent Card (extend), `FrameworkBackend` tool-wiring (RFC-002a seam), `zil validate` |
| **Owner** | FluentData / Zil maintainers |
| **Zil version target** | post-v0.1 |
| **License** | Apache 2.0 |
| **Related** | Pillars 7 (architecture), 2 (security), 1 (governance). **Consumes** the A2A *server* already shipped in `zil serve`. **Depends on** RFC-002a (framework backend / tool-wiring seam). **Interfaces with** RFC-001 (agent identity / least-privilege), RFC-003 (cross-agent memory boundaries), RFC-006 (data governance), RFC-007 (registry-of-record for discovery), RFC-011 (where peers are deployed). |
| **Document purpose** | Implementation spec intended to be handed to an LLM coding agent. Prefer the smallest correct increment. The contract/adapter/discovery split (§3) makes it shippable in slices. |

---

## 0. How to read this document

Section 1 orients on what Zil ships today for agent-to-agent communication. Section 2 is the "why." **Section 3 is the central structural decision — read it first: this RFC separates a platform-neutral collaboration *contract* from per-framework client *adapters* and a *discovery* mechanism.** Sections 4–11 are design and requirements. Section 12 is the conformance kit. Section 13 is the build plan. Section 14 is acceptance criteria.

When this document and the live Zil codebase disagree, **the codebase wins; flag the discrepancy.** The A2A wire protocol and every framework SDK (ADK `RemoteA2aAgent`, the `a2a` package, the Agent Card schema) are **external and moving**: every endpoint shape, card field, and SDK signature referenced here **MUST be verified against current sources before relying on it.** Where this document says "verify," treat it as a hard gate. **Do not confabulate protocol fields or SDK APIs.**

> **Scope decision (settled).** This RFC is the **full** "Multi-Agent Topology & A2A Security" surface from the gap analysis: client + discovery **and** inter-agent auth/identity **and** declared topology governance. The §13 phasing keeps it shippable: the client/discovery core lands first; auth and topology governance follow on the proven contract.

---

## 1. Primer: what Zil ships today

Zil is an open-source CLI and Python SDK for validating, packaging, and deploying production AI agents. The manifest is the contract; `zil pack` produces a signed `.zil` archive; `zil serve` runs the agent as a REST/A2A server; `zil deploy` stands it up; the SDK's `create_agent` returns a wired agent.

**Already shipped — the A2A *server* half.** `zil serve` registers the server side of A2A in `_register_a2a_endpoints` (`src/zil/commands/serve.py`):
- `GET /.well-known/agent.json` — an **Agent Card** (name, version, capabilities, skills).
- `POST /tasks/send`, `POST /tasks/sendSubscribe` — accept a task, run it through a `Session`, return artifacts (the latter via SSE).
- `GET /tasks/{task_id}` — task status.

So every deployed Zil agent is **addressable and consumable** by an A2A client.

**Already shipped — in-process multi-agent.** `spec.agents` is compiled into framework sub-agents wrapped as tools: the ADK backend's `_build_sub_agents` wraps each sub-agent's `LlmAgent` as an `AgentTool` (`src/zil/sdk/frameworks/adk/backend.py`). This is collaboration **within a single deployment** (one container, one process), validated by `_check_agents` in `src/zil/schema/loader.py`.

**The gap this RFC closes.** For *independently deployed* agents:
1. **No A2A client.** Nothing fetches a peer's Agent Card and calls its `/tasks/send`. An agent cannot consume another agent.
2. **No discovery / resolution.** No way to map a peer *name* → deployed *URL* + card.
3. **Agent Card `skills` is a placeholder.** `_register_a2a_endpoints` advertises a single synthetic `"default"` skill instead of the manifest's real skills, so a caller cannot meaningfully introspect or select capabilities.
4. **No inter-agent auth / identity.** Cross-agent calls have no agent identity and no authentication path (Cloud Run deploys are private unless `--allow-unauthenticated` is passed in `src/zil/commands/deploy.py`).

Four guiding principles:
1. **Built on what exists** — reuse the A2A protocol and the shipped server; do not invent a private RPC.
2. **Declarative-first** — collaborators and the allowed topology are declared in the manifest; the runtime enforces them.
3. **Framework-neutral contract, framework-specific adapters** — the same architectural move as RFC-002a (framework) and RFC-011 (runtime).
4. **Least authority** — an agent may only call the peers and skills its manifest declares.

---

## 2. Problem statement (the "why")

The framework spec sells multi-agent systems in which independently deployed agents collaborate — *"deploy Zil agents on my runtime and have them leverage each other."* Today that is **false for distributed agents**: each `zil serve` is an island that advertises itself but cannot reach anyone else. The only working collaboration is the **monolithic** `spec.agents` path (one deployment, sub-agents as in-process tools), which does not scale to independently owned, separately deployed, separately versioned agents.

Adding ad-hoc HTTP calls inside agent code would reproduce, at the collaboration layer, the same hardwiring problems RFC-002a/RFC-011 fixed elsewhere: no declared topology, no discovery, no auth, no governance, no portability.

The correct move is the same one applied at the other layers: **define a neutral contract, then implement adapters** — here, a collaboration contract plus per-framework client adapters and a discovery mechanism. This turns multi-agent *scaffolding* into governed *topology*: declared who-talks-to-whom, what context may transfer, authenticated agent identity, and explicit shared-memory boundaries. That is precisely the gap analysis's **"Multi-Agent Topology & A2A Security."**

There is a second payoff: a declared collaboration topology is the substrate **system-level evaluation** (RFC-009) and **fleet governance** (RFC-007) need — you cannot evaluate or govern a topology that exists only implicitly in agent code.

---

## 3. The central split: contract vs. client adapters vs. discovery

This RFC is **three separable deliverables.** Conflating them is what makes it look like one XL blob; splitting them is what makes it shippable.

**(A) The Collaboration Contract.** A platform-neutral description of a **peer reference** (name, address/ref, allowed skills, auth mode, context-transfer policy), the **Agent Card** shape a Zil caller relies on, and the neutral **`RemoteAgent` tool interface** the LLM sees. Design-heavy, framework-agnostic, done **once.**

**(B) Client Adapters.** Per-framework realizations of "call a peer as a tool." The ADK adapter can wrap a peer as `google.adk.agents.RemoteA2aAgent` / `AgentTool`; other backends implement the same contract over the A2A wire. Framework-specific, protocol-neutral above the wire. Each is its own effort with its own verification spike.

**(C) Discovery & Resolution.** How a peer *name* resolves to a concrete URL + card: **static** (manifest URL / env) in Phase 1; an **optional registry** lookup later (RFC-007 seam). The resolver is the only component that knows *where* peers live.

> **Roadmap implication.** "Support distributed collaboration" = the contract **plus** at least one client adapter **plus** a resolver — not a single ticket. This document specifies the contract in full and the **ADK adapter + static discovery** concretely; other framework adapters and registry discovery are follow-on items that land on the proven contract.

### 3.1 Seam with RFC-002a (framework backend)

`FrameworkBackend.wire(spec)` already assembles tools (callables, MCP toolsets, skills, sub-agents) onto a `WiredAgent` (`src/zil/sdk/frameworks/base.py`). This RFC adds **remote-agent tools** as one more tool source the backend wires.

Clean division of responsibility:
- **The collaboration contract (this RFC)** answers **"which peers, which skills, authenticated how, what context may transfer."** Framework-agnostic.
- **`FrameworkBackend` (RFC-002a)** answers **"how do I expose that as a callable tool in framework X."** Framework-specific.

`wire()` becomes: existing tool sources **+** `remote_agent_tools = build_remote_agent_tools(spec.collaborators, resolver, authenticator)`. Neither side knows the other's internals.

---

## 4. Goals and non-goals

### Goals
1. Define the **collaboration contract** (§5): `PeerRef`, the relied-upon Agent Card shape, the neutral `RemoteAgent` tool interface, and `ContextTransferPolicy`.
2. Add a **`spec.collaborators`** manifest block (§6) declaring allowed peers, per-peer skill allowlists, auth mode, and context-transfer rules.
3. Implement an **A2A client** (§7): fetch a peer card, expose its skills as tools, call `/tasks/send` (+ streaming via `/tasks/sendSubscribe`), return artifacts as tool results.
4. Wire remote-agent tools through **`FrameworkBackend`** (§7.2); ship the **ADK adapter** first.
5. **Populate the Agent Card `skills`** from the manifest (§8) so callers can introspect and select.
6. Define **discovery/resolution** (§9): static (Phase 1) + registry hook (later).
7. Define **topology governance & A2A security** (§10): peers-allowlist as the declared topology, per-skill least authority, pluggable inter-agent auth (GCP ID-token default), agent identity (RFC-001 tie-in), context-transfer enforcement, shared-memory boundary note (RFC-003).
8. Add **`zil validate`** checks (§11) and a **mock-peer conformance kit** (§12).

### Non-goals
- **A Zil-hosted message bus / orchestrator / broker.** Calls go agent→agent over A2A; no central runtime is introduced.
- **Replacing in-process `spec.agents`.** Sub-agents stay; this adds the *distributed* path alongside them.
- **Deep cross-agent data-boundary *policy*.** The contract exposes the context-transfer *interface*; retention/residency/right-to-forget policy is RFC-003/RFC-006.
- **Fleet-governance UX** (approval queues, ownership/SLA dashboards) — RFC-007.
- **System-level multi-agent evaluation** — consumes this topology but is RFC-009.
- **Every framework adapter at once.** Contract + ADK adapter + static discovery here; other backends and registry discovery follow on the proven contract.

---

## 5. The collaboration contract

A platform-neutral contract with four parts: the **peer reference**, the **Agent Card** shape relied upon, the **`RemoteAgent` tool interface**, and the **context-transfer policy**. Reference signatures; adjust to house style but preserve semantics. The neutral core imports **no** framework SDK and **no** HTTP client beyond the thin A2A client (§7.1).

```python
from typing import Protocol, Any, Optional
from dataclasses import dataclass, field


@dataclass
class AgentSkill:
    """A capability advertised on an Agent Card (subset Zil relies on)."""
    id: str
    name: str
    description: str = ""
    input_modes: list[str] = field(default_factory=lambda: ["text/plain"])
    output_modes: list[str] = field(default_factory=lambda: ["text/plain"])


@dataclass
class AgentCard:
    """The /.well-known/agent.json shape Zil consumes. VERIFY against the
    current A2A spec before pinning fields; treat unknown fields as opaque."""
    name: str
    description: str
    url: str
    version: str
    capabilities: dict          # e.g. {"streaming": bool, "pushNotifications": bool}
    skills: list[AgentSkill] = field(default_factory=list)


@dataclass
class ContextTransferPolicy:
    """What may cross the boundary on a peer call. Enforced by the client;
    deep policy (PII/residency/retention) is RFC-003/006."""
    send: str = "message_only"     # "message_only" | "session_summary" | "none"
    receive: str = "artifacts"     # "artifacts" | "artifacts_and_state"
    redact: list[str] = field(default_factory=list)  # field/pattern names to strip outbound


@dataclass
class PeerRef:
    """A declared collaborator. Resolves to an AgentCard via the resolver."""
    name: str                              # logical name used by the caller LLM
    url: Optional[str] = None              # explicit address (Phase 1 static)
    ref: Optional[str] = None              # registry reference (Phase 4 discovery)
    skills: Optional[list[str]] = None     # allowlist of peer skill ids (None = all advertised)
    auth: str = "gcp-id-token"             # auth mode key (§10); pluggable
    context_transfer: ContextTransferPolicy = field(default_factory=ContextTransferPolicy)


class PeerResolver(Protocol):
    """Maps a PeerRef -> live AgentCard (the only 'where peers live' knower)."""
    def resolve(self, ref: PeerRef) -> AgentCard: ...


class Authenticator(Protocol):
    """Produces auth headers for an outbound peer call. One impl per auth mode."""
    mode: str  # "gcp-id-token" | "bearer" | "mtls" | "none" ...
    def headers(self, target: AgentCard) -> dict[str, str]: ...


class RemoteAgent(Protocol):
    """Neutral interface a framework adapter exposes to its LLM as a tool."""
    name: str
    card: AgentCard
    def list_skills(self) -> list[AgentSkill]: ...
    async def send(self, skill_id: str, message: str,
                   *, stream: bool = False) -> Any: ...   # returns artifact(s)
```

> **Backward compatibility.** A manifest with no `spec.collaborators` wires exactly as today. The contract is additive.

---

## 6. Manifest: `spec.collaborators`

A new top-level block under `spec`. Mirrors how `spec.agents` is its own block, keeping *peers* (independent, networked, governed) distinct from *tools* and from in-process *sub-agents*.

```yaml
spec:
  collaborators:
    - name: billing-agent              # logical handle the caller LLM uses
      url: https://billing-agent-xyz.run.app   # Phase 1: explicit address
      # ref: zil://fleet/billing-agent          # Phase 4: registry reference (alt to url)
      skills: [refund, invoice_lookup] # allowlist of peer skill ids (omit = all advertised)
      auth: gcp-id-token               # §10 auth mode; default gcp-id-token
      context_transfer:
        send: message_only             # message_only | session_summary | none
        receive: artifacts             # artifacts | artifacts_and_state
        redact: [SSN, internal_notes]  # outbound fields/patterns to strip
    - name: research-agent
      url: https://research-agent-xyz.run.app
      auth: bearer
```

Notes:
- **`url` xor `ref`** — exactly one. `url` is static (Phase 1); `ref` is registry discovery (Phase 4).
- **`skills` is the least-authority allowlist.** Calls to a non-listed skill are rejected client-side before any network call.
- **The set of `collaborators` is the declared topology** — who this agent may talk to. §10 governs it.
- Schema and validation hook into `src/zil/schema/loader.py` alongside `_check_agents` (new `_check_collaborators`).

---

## 7. A2A client + framework adapters

### 7.1 The A2A client (framework-neutral)

A thin async client — the **only** module that speaks the A2A wire on the caller side. Responsibilities:
1. **Fetch & cache** the peer `AgentCard` from `GET {url}/.well-known/agent.json` (TTL-cached; refresh on call failure).
2. **Filter** advertised skills to the `PeerRef.skills` allowlist.
3. **Apply** the `Authenticator.headers(card)` to every request.
4. **Apply** `ContextTransferPolicy` outbound (redact / choose payload).
5. **Call** `POST {url}/tasks/send` (non-stream) or `POST {url}/tasks/sendSubscribe` (SSE), parse `artifacts[].parts[].text`, and return the result.
6. **Map errors** (401/403 → auth error; 404 → unknown task/skill; timeout → clear surfaced error).

This client is the mirror of the server already in `_register_a2a_endpoints`; its request/response shapes **must** match that server (and be verified against the current A2A spec).

### 7.2 Framework adapters

Each `FrameworkBackend` turns `PeerRef`s into framework-native tools via a shared helper `build_remote_agent_tools(collaborators, resolver, authenticator) -> list[tool]`, called inside `wire()`.

- **ADK adapter (first).** Prefer the SDK primitive: wrap each peer as `google.adk.agents.RemoteA2aAgent` (sourced from its `/.well-known/agent.json`) and expose it via `AgentTool`, reusing the existing sub-agent → `AgentTool` pattern in `_build_sub_agents`. If the SDK primitive cannot honor the per-skill allowlist / context-transfer policy, fall back to wrapping the §7.1 client as a plain function tool. **Verify `RemoteA2aAgent` signature and behavior before relying on it.**
- **Other backends (follow-on).** Implement the `RemoteAgent` interface over the §7.1 client and expose it as that framework's tool type.

Each adapter is "done" when it passes the §12 conformance kit.

---

## 8. Agent Card population (server side)

Today `_register_a2a_endpoints` emits a placeholder single `"default"` skill. To make agents introspectable by callers, populate `skills` from the manifest:
- Derive `AgentSkill` entries from `spec.skills` (id, name, description, input/output modes).
- Keep `capabilities.streaming = True` (the server supports `sendSubscribe`).
- Continue resolving `url` from forwarded host/proto (unchanged).

This is a small, self-contained change that unblocks meaningful discovery — a caller selects a peer skill by its advertised `id`.

---

## 9. Discovery & resolution

A `PeerResolver` maps `PeerRef → AgentCard`. Implementations, sequenced:

- **`StaticResolver` (Phase 1).** Resolve from `PeerRef.url` (with env-var interpolation, e.g. `${BILLING_AGENT_URL}`), then fetch the card. Covers the common case (you know your peers' URLs) with zero new infrastructure.
- **`RegistryResolver` (Phase 4).** Resolve `PeerRef.ref` (e.g. `zil://fleet/billing-agent`) via an in-process `name → url` mapping (injected or `ZIL_FLEET_REGISTRY`). Good for tests and small static fleets.
- **`HttpRegistryResolver` (Phase 4, shipped).** Resolve `PeerRef.ref` against a remote *registry of record* over HTTP — `GET {ZIL_FLEET_REGISTRY_URL}/agents/<name>` → URL + (optional) card. This is the production seam; the registry-of-record itself is **RFC-007** (do not build a bespoke registry in core — principle: no new registry). See `examples/a2a-registry` for the contract + a reference service.

`build_resolver(env)` selects `HttpRegistryResolver` when `ZIL_FLEET_REGISTRY_URL` is set, else `RegistryResolver`. The resolver is the single seam that knows *where* peers live, so swapping static → registry changes nothing else.

---

## 10. Topology governance & A2A security

### 10.1 Declared topology
The `collaborators` list **is** the allowed topology for this agent: it may call exactly those peers, and (per `skills`) exactly those capabilities. There is no implicit reachability. `zil validate` can render/check the fleet topology graph (who-talks-to-whom) from manifests and flag issues (e.g. cycles, references to undeclared peers).

### 10.2 Inter-agent authentication (pluggable)
An `Authenticator` per `auth` mode attaches credentials to outbound calls. Ship:
- **`gcp-id-token` (default).** Mint a Google-signed ID token for the target Cloud Run URL (service-to-service identity); the callee's Cloud Run validates it. Aligns with private-by-default deploys (`--allow-unauthenticated` is opt-in).
- **`bearer`.** Static token from an env var (cross-cloud / non-GCP peers).
- **`none`.** Explicit opt-out (dev only; `zil validate` warns).

Follow-on modes (mTLS, OIDC client-credentials) implement the same `Authenticator` protocol.

### 10.3 Agent identity (RFC-001 tie-in)
A peer call should carry a verifiable caller identity, not just transport auth. Define the seam now: callers attach an identity assertion (header) derived from the agent's RFC-001 identity; the **callee-side enforcement** (verify caller identity, apply per-caller authorization) is specified with RFC-001 and noted here as the integration point.

### 10.4 Context-transfer enforcement
The client enforces `ContextTransferPolicy` on every call: choose the outbound payload (`message_only` | `session_summary` | `none`), apply `redact` patterns before sending, and constrain what is ingested from the response (`artifacts` vs `artifacts_and_state`). **Deep data-classification/residency/right-to-forget policy is RFC-003/RFC-006**; this RFC provides the enforcement *point*, not the full policy engine.

### 10.5 Shared-memory boundaries
Cross-agent memory sharing is **off by default** — a peer call transfers only what `context_transfer` permits, never the caller's memory namespace. Any shared/seeded namespace coordination is deferred to RFC-003's memory-scope model; record the boundary explicitly so it is a deliberate decision, not a silent leak.

---

## 11. CLI / validation wiring

- **`zil validate`** (`src/zil/schema/loader.py`, new `_check_collaborators`):
  - each collaborator has exactly one of `url`/`ref`; env-var URLs resolvable (or warn if unset at validate time);
  - `auth` is a registered mode; `auth: none` warns;
  - declared `skills` exist on the peer's advertised card **(optional online check** behind a flag; offline by default to keep validate hermetic);
  - topology sanity: no reference to an undeclared/unknown peer; flag cycles.
- **`zil serve` / SDK `create_agent`** — `wire()` builds remote-agent tools from `spec.collaborators` via the resolver + authenticator; existing tool sources unchanged.
- **Backward compatibility** — absent `spec.collaborators` ⇒ identical behavior to today.

---

## 12. Conformance test kit

"Collaboration works" must be testable without live peers. Provide `tests/collaboration/` with a **mock peer A2A server** (a `zil serve` app or a FastAPI stub exposing `/.well-known/agent.json`, `/tasks/send`, `/tasks/sendSubscribe`) and a suite parametrized over adapters:
- card fetch + skill discovery; allowlist filtering (non-listed skill rejected pre-network);
- `send` non-stream and stream round-trips; artifact parsing;
- `Authenticator.headers` attached to every request (assert header present per mode);
- `ContextTransferPolicy` applied (redaction strips fields; `none` sends no message body);
- `zil validate` errors on unknown peer / unknown skill / missing url+ref / bad auth mode;
- caller identity header present (when RFC-001 identity available).

A framework client adapter is "done" when it passes the kit.

---

## 13. Phased implementation plan

**Phase 0 — verification spikes (timebox). ✅ DONE — see `ZIL-RFC-005-PHASE0-FINDINGS.md`.** Pinned the current Agent Card / `AgentSkill` schema (camelCase; `AgentSkill.tags` required), the JSON-RPC method set (`message/send`, `message/stream`, `tasks/get`), the current well-known path (`/.well-known/agent-card.json`), and `RemoteA2aAgent(agent_card=AgentCard|url|path)` as the viable client primitive. **Toolchain version (corrected in Phase 1b):** `google-adk` 1.32 pins **`a2a-sdk>=0.3.4,<0.4`** (its `RemoteA2aAgent` imports `a2a.client.ClientEvent`, absent in `a2a-sdk` 1.x), so the build standardizes on **`a2a-sdk` 0.3.x**; the pydantic conformance model is `a2a.types.AgentCard`. All Phase 0 conclusions hold on 0.3.x.

**Phase 1a — server conformance. ✅ DONE.** `zil serve` now emits a conformant Agent Card (`protocolVersion: "0.3.0"`, `preferredTransport: "JSONRPC"`, `additionalInterfaces`), serves `/.well-known/agent-card.json` (legacy `agent.json` kept as a deprecated alias), and exposes JSON-RPC `POST /a2a` (`message/send`, `message/stream`, `tasks/get`). The served card is validated against `a2a.types.AgentCard` in tests.

**Phase 1b — collaboration contract + client. ✅ DONE (contract + native client + ADK adapter).** Added the framework-neutral contract (`zil.collaboration.contract`: `PeerRef`, `AgentCard`, `ContextTransferPolicy`, resolver/authenticator/remote-agent protocols), `StaticResolver` (`${ENV}` interpolation), `spec.collaborators` manifest schema + loader (`ProjectContext.collaborators`) + `validate` checks, and the ADK adapter wiring declared peers as `RemoteA2aAgent` `AgentTool`s in `wire()`. **Native client (§7.1) now landed:** `zil.collaboration.client.A2APeerClient` (`call` + `stream`) is built on the protocol SDK (`a2a-sdk`: `A2ACardResolver` + `ClientFactory`/`Client`), so *any* backend (not just ADK) can call peers. It enforces the per-peer `skills` allowlist **before any network request** (`SkillNotAllowedError`) — closing the prior 'advisory-only' gap — and returns parsed artifacts (`PeerCallResult`/`PeerArtifact`). A **conformance kit** (`tests/test_collaboration_client.py`) drives the real `a2a-sdk` client against zil's *own* server (`_create_app`) in-process via an httpx ASGI transport: true JSON-RPC round-trip (`message/send`) + streaming (`message/stream`), no sockets. Criteria 1–5, 9 met. *(Inter-agent auth landed in Phase 2; `ContextTransferPolicy` enforcement tracked under Phase 3.)*

> **Phase 0 outcome — re-sequencing.** The shipped `zil serve` A2A server is **legacy/non-conformant** (old well-known path; REST `tasks/send`/`tasks/sendSubscribe` instead of JSON-RPC `message/send`/`message/stream`; card missing `protocolVersion`/`preferredTransport`; skills missing `tags`). Since interoperability is the priority, **server conformance is now a prerequisite for the client** and is split out as **Phase 1a**, ahead of the contract/client work (**Phase 1b**). Decisions taken: transport = **JSONRPC** (spec default, what `RemoteA2aAgent` expects); legacy REST + `/.well-known/agent.json` kept as **deprecated aliases** for a back-compat window; protocol advertised as `0.3.0`.

**Phase 1a — A2A server conformance (interop foundation).** Bring `zil serve` to the current A2A spec: serve `/.well-known/agent-card.json` (keep `/.well-known/agent.json` as a deprecated alias); add a **JSON-RPC** endpoint exposing `message/send`, `message/stream`, `tasks/get` (keep legacy REST `tasks/*` as deprecated aliases); add `protocolVersion`/`preferredTransport` to the card; emit `AgentSkill.tags` (done). This is what makes a Zil agent callable by *any* A2A client (Zil or third-party) and is the precondition for the ADK `RemoteA2aAgent` path.

**Phase 1b — contract + `spec.collaborators` + client + ADK adapter + static discovery.** The `PeerRef`/`AgentCard`/`RemoteAgent`/`ContextTransferPolicy` contract, `spec.collaborators` schema + `_check_collaborators`, the §7.1 client, `StaticResolver`, the ADK adapter (via `RemoteA2aAgent`), `wire()` seam, conformance kit v1. (Agent Card skill population §8 already shipped.) Criteria 1–5, 9.

**Phase 2 — A2A security (auth). ✅ DONE.** Shipped `zil.collaboration.auth` with `NoneAuthenticator`, `BearerAuthenticator` (env-var token via `ZIL_A2A_TOKEN_<PEER>` → `ZIL_A2A_TOKEN`), and `GcpIdTokenAuthenticator` (audience-scoped Google ID token, cached/refreshed; aligns with private-by-default Cloud Run) plus a `build_authenticator(peer, target_url)` factory. The ADK adapter binds the authenticator to each peer and attaches an `httpx.Auth` flow on the `RemoteA2aAgent` HTTP client for every mode except `none` (which uses ADK's default client). Validate-time auth-mode checks (`none` warns) already landed in `_check_collaborators`. **Divergence (codebase-wins):** `Authenticator.headers()` takes no argument — audience is bound at construction (what httpx has at request time). Criteria 6. **Deferred to follow-on:** mint-on-async-loop optimization for `gcp-id-token` (currently mints synchronously inside the auth flow).

**Phase 3 — topology governance + context-transfer enforcement. 🟡 PARTIAL (3a + 3c done; 3b unblocked on native client, not yet wired).**
- **3a — topology governance. ✅ DONE.** `zil validate` now fails on a topology self-reference (an agent listing itself as a collaborator) in `_check_collaborators`. Added framework-neutral fleet primitives `zil.collaboration.topology.build_topology_graph(manifests)` + `find_cycles(graph)` (DFS; detects self-loops and multi-node cycles, ignores external/unknown peers, reports each cycle once). Fleet-wide cycle checks need *all* manifests, whose source is the RFC-007 registry — the primitives are ready for that caller but not invoked by single-manifest `validate`.
- **3c — agent-identity seam. ✅ DONE.** Every outbound peer call now carries a caller-identity header `X-Zil-Caller-Agent: <agent_name>` via `zil.collaboration.http.PeerRequestAuth` (an `httpx.Auth` flow that injects identity always and auth headers when a credentials authenticator is present). The ADK adapter now *always* attaches this client (even for `auth: none`, identity-only). **Callee-side verification / per-caller authorization is specified with RFC-001** and is the documented integration point.
- **3b — context-transfer enforcement. ⏸ STILL DEFERRED on the ADK path; now UNBLOCKED on the native client.** The native `A2APeerClient` (Phase 1b) constructs the outbound A2A message itself, so it is the clean enforcement point for `redact`/`send`/`receive` (no wire-rewrite hack). ADK-path enforcement remains deferred (`RemoteA2aAgent` builds the message internally). The policy is parsed (`PeerRef.context_transfer`) and validated; wiring it into `A2APeerClient._message` is the next step. Criterion 7 (context transfer) remains open; Criterion 8 (topology validation) is met for self-reference + fleet cycles.

**Phase 4 — registry discovery. ✅ DONE (resolver; registry-of-record gated on RFC-007).** `zil.collaboration.discovery.RegistryResolver` resolves `ref: zil://fleet/<name>` against a registry mapping (injected, or `ZIL_FLEET_REGISTRY=name=url,...`), validates the scheme, and raises clear errors when the registry is unconfigured or the ref is unknown. It is a superset of `StaticResolver` (also handles plain `url:` peers with `${ENV}`), so it is now the **default resolver** in both the ADK adapter and `A2APeerClient` — `ref:` peers work end-to-end today. The remaining RFC-007 dependency is only the *registry service of record* that would populate the mapping automatically. **Discoverability also gained:** `zil validate --online` fetches each peer's Agent Card and fails on declared skills the peer does not advertise (warns on fetch failure); and a new `zil topology` command scans a directory tree of manifests, renders the declared graph, and exits non-zero on cycles (using the Phase 3a primitives). Criterion 10 met.

---

## 14. Acceptance criteria (write these as tests)

1. **Backward compat:** a manifest with no `spec.collaborators` wires and serves identically to today.
2. **Client round-trip:** against the (in-process) peer, an agent fetches the card, calls a skill via JSON-RPC `message/send`, and receives parsed artifacts. ✅ (`A2APeerClient.call`)
3. **Streaming:** `message/stream` round-trip yields incremental events and a final status. ✅ (`A2APeerClient.stream`)
4. **Least authority:** a call to a skill not in the `skills` allowlist is rejected **before** any network request, with a clear error. ✅ (`SkillNotAllowedError`)
5. **ADK adapter:** a peer declared in `spec.collaborators` appears as a callable tool to an ADK agent and successfully invokes the mock peer.
6. **Auth:** every outbound call carries credentials for the declared `auth` mode (assert per mode); `auth: none` warns at validate.
7. **Context transfer:** `redact` strips named fields outbound; `send: none` transmits no message body; `receive: artifacts` ingests only artifacts.
8. **Topology validation:** `zil validate` fails on a collaborator with neither/both `url`/`ref`, an unknown auth mode, or (`--online`) a skill the peer does not advertise; `zil topology` flags cycles across a fleet of manifests. ✅
9. **No Zil runtime:** assert calls go directly agent→peer over A2A; no central broker/service is introduced.
10. **Registry discovery:** a `ref:` collaborator resolves via `RegistryResolver` and behaves identically to a `url:` peer. ✅ (registry mapping / `ZIL_FLEET_REGISTRY`; RFC-007 only supplies the auto-populated registry of record)

---

## 15. Definition of done (contract + ADK adapter + static discovery + auth)

- Collaboration contract (`PeerRef`/`AgentCard`/`RemoteAgent`/`ContextTransferPolicy`/`PeerResolver`/`Authenticator`) merged; neutral core tests pass with no framework SDK installed.
- `spec.collaborators` schema + `_check_collaborators` validation merged.
- A2A client + `StaticResolver` + ADK adapter wired through `FrameworkBackend.wire`; a peer is callable as a tool and passes the conformance kit.
- Agent Card advertises real `spec.skills`.
- `gcp-id-token` + `bearer` + `none` authenticators; private-by-default call path.
- Context-transfer enforcement + topology validation implemented.
- Agent-identity assertion seam defined (whether or not RFC-001 callee enforcement ships).
- Conformance kit exists and gates adapter "done."
- Docs page under `getzil.dev/docs`: `spec.collaborators`, the contract, the ADK guide, auth modes, and an explicit note that other framework adapters + registry discovery are follow-on on the same contract.

---

## 16. File / module layout (suggested)

```
zil/
  collaboration/
    __init__.py
    contract.py        # PeerRef, AgentCard, AgentSkill, ContextTransferPolicy,
                       #   RemoteAgent, PeerResolver, Authenticator (no SDK imports)
    client.py          # A2A client — ONLY caller-side wire module
    discovery.py       # StaticResolver (+ RegistryResolver, Phase 4)
    auth.py            # gcp-id-token / bearer / none authenticators
    wiring.py          # build_remote_agent_tools(collaborators, resolver, authenticator)
  sdk/frameworks/
    adk/backend.py     # ADK adapter: peers -> RemoteA2aAgent/AgentTool (wire() seam)
  commands/
    serve.py           # Agent Card skills populated from spec.skills (§8)
  schema/
    loader.py          # _check_collaborators (§11)
tests/
  collaboration/
    conftest.py        # mock peer A2A server fixture
    test_contract_neutral.py
    test_client_roundtrip.py
    test_skill_allowlist.py
    test_auth_modes.py
    test_context_transfer.py
    test_validation_collaborators.py
    test_adk_remote_agent.py
```

---

## 17. Open questions (Phase 0 / scope decisions)

1. **Auth breadth** — beyond `gcp-id-token`/`bearer`, which of mTLS / OIDC client-credentials are needed for first customers? Interface is pluggable; pick the default + the first follow-on.
2. **Discovery** — extend RFC-007's registry for `ref:` resolution, or ship a lightweight name→URL map sooner? Decide the boundary with RFC-007.
3. **Context-transfer depth** — how much policy lives here vs RFC-003/RFC-006? This RFC owns the enforcement point; confirm the policy-engine boundary.
4. **Streaming to the caller LLM** — surface `sendSubscribe` increments to the calling agent's stream, or collapse to the final artifact? Pick one default.
5. **Card field pinning** — which Agent Card fields does Zil depend on vs treat as opaque? Pin only what's verified against the current A2A spec.
6. **Identity assertion format** — what does the caller-identity header carry (JWT? signed claim?), and where is callee-side enforcement specified (here vs RFC-001)?

---

## 18. References (verify against current docs/versions)

- **ZIL-RFC-002a** — Framework Backend Abstraction (`wire()` / `WiredAgent` tool-wiring seam, §3.1).
- **ZIL-RFC-001** — Tool Contract Enforcement (agent identity / least-privilege; §10.3).
- **ZIL-RFC-003 / RFC-006** — Memory layer / Data Governance (context-transfer & shared-memory boundaries, §10.4–10.5).
- **ZIL-RFC-007** — Agent Registry & Lifecycle Governance (registry discovery, §9).
- **ZIL-RFC-011** — Runtime Conformance (where peers are deployed; private-by-default call path).
- **ZIL-GAP-ANALYSIS-05-25** — §4.2 / Pillar 7 / roadmap: RFC-005 = "Multi-Agent Topology & A2A Security."
- Zil source — `src/zil/commands/serve.py` (A2A server + Agent Card), `src/zil/sdk/frameworks/adk/backend.py` (`_build_sub_agents`/`AgentTool`), `src/zil/schema/loader.py` (`_check_agents`), `src/zil/commands/deploy.py` (`--allow-unauthenticated`).
- **A2A protocol** — Agent Card schema, `tasks/send` / `tasks/sendSubscribe` shapes. **Verify; do not confabulate.**
- **Google ADK** — `google.adk.agents.RemoteA2aAgent`, `google.adk.tools.agent_tool.AgentTool`. **Verify signatures.**
- Google Cloud Run — service-to-service ID-token authentication.
```
