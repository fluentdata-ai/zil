# ZIL-RFC-003 — Memory Layer Integration

| Field | Value |
|---|---|
| **Status** | Draft / Backlog |
| **Target component** | `zil-ai` Python SDK (`create_agent`, memory adapters, shared substrate adapter), manifest schema, `zil validate` / `zil audit` / `zil pack` |
| **Owner** | FluentData / Zil maintainers |
| **Zil version target** | post-v0.1 |
| **License** | Apache 2.0 |
| **Related** | ZIL-RFC-001 (Tool Contract Enforcement), ZIL-RFC-002a (Framework Backend Abstraction), and ZIL-RFC-002b (OpenHands Framework Backend). **Complementary, not prerequisites — see §3.** RAG / knowledge grounding is **explicitly out of scope — see §4 and §12.** |
| **Document purpose** | Implementation spec intended to be handed to an LLM coding agent. Be pragmatic. Prefer the smallest correct increment. |

---

## 0. How to read this document

This spec is written so an implementer (human or LLM) with **no prior knowledge of Zil** can build the feature. Section 1 orients on Zil. Section 2 is the "why" and the scope distinction that defines this feature. Section 3 is the relationship to RFC-001/002. Section 4 is goals/non-goals (read the non-goals carefully — the RAG boundary is load-bearing). Sections 5–12 are design and requirements. Section 13 is acceptance criteria. Section 14 is the phased build plan — **start there if you want to know what to write first.**

When this document and the live Zil codebase disagree, the codebase wins; flag the discrepancy. **Memory providers are external, fast-moving, and fragmented: every provider SDK entry point, interface, and configuration field referenced here MUST be verified against the version pinned in the project before relying on it.** Where this document says "verify," treat it as a hard gate. Do not confabulate provider APIs — if you cannot confirm a method exists, stop and surface it as an open question.

---

## 1. Primer: what Zil is

Zil is an open-source CLI and Python SDK for **validating, packaging, and deploying production AI agents**. It does not reinvent agent orchestration, tool protocols, evaluation, or telemetry — it **composes** with existing standards: Google ADK (and, per RFC-002a/002b, other frameworks such as OpenHands) as agent frameworks, MCP (tool protocol), DeepEval (evals), OpenTelemetry (tracing).

Core mental model:

- **The manifest is the contract.** A declarative `manifest.yaml` describes an agent's runtime, identity, adapters, tools, evals, and observability.
- **The CLI is a thin wrapper** over the manifest: `init`, `validate`, `audit`, `eval`, `pack`, `push`, `deploy`.
- **`zil pack`** produces a signed, portable `.zil` archive (manifest + agent code + tools + SBOM + eval results + cosign signature + SLSA provenance).
- **The SDK** exposes `zil.create_agent(...)`, which reads the manifest and identity files and returns a fully wired agent.
- **Adapters** are how Zil composes with external systems declaratively. The existing `adapters/llm.yaml` configures the model provider. **This RFC adds memory the same way — as declarative adapters, not a Zil-built subsystem.**

Four guiding principles that constrain this feature:

1. **Built on what exists** — compose with existing memory providers; **do not build a memory store or a vector database.**
2. **Declarative-first** — memory configuration lives in the manifest; code reads it.
3. **No new runtime** — memory data lives in the provider the user chose; Zil does not host it.
4. **No new registry** — unchanged here.

---

## 2. Problem statement and the defining scope distinction (the "why")

### 2.1 Why memory belongs in Zil

Zil's actual driver is **completeness and portability of the agent's declared contract**: the `.zil` should be a self-describing, reproducible artifact. Today, memory is the biggest hole in that completeness — it is delegated to the framework's native session model (e.g. ADK Sessions), which makes it an **undeclared, framework-coupled dependency.** That breaks the "complete, portable artifact" promise.

Two forces make this urgent rather than cosmetic:

1. **Multi-framework portability (the strongest driver).** Native session/memory models do not port across frameworks. ADK has its own model (Session service + a `BaseMemoryService`/Vertex AI Memory Bank wrapper); OpenHands (RFC-002b) has its own. To honor "one governance model across frameworks" and a portable artifact, memory must be abstracted at the **Zil layer**, not delegated per-framework.
2. **Governance.** Long-term memory is a security and data-governance surface: it introduces **memory poisoning** (false data persisted then later retrieved as fact) and **prompt-injection-via-memory**, and it is a sensitive-data and exfiltration vector (what an agent *remembers* it may later *emit* — directly connected to RFC-001's sensitive→egress concern). What is persisted, where, retention, and PII are exactly what `zil audit` and the contract layer should govern.

> **Framing note for implementers:** memory is an **extension of Zil's completeness driver**, not a new product pillar. Build it as a declarative adapter mirroring the LLM adapter — nothing more architecturally novel than that.

### 2.2 The scope distinction that defines this RFC

Three concepts are routinely conflated. This RFC depends on keeping them apart:

- **Vectorization** = embeddings + a vector/graph store + similarity search. This is a **substrate**, not a feature.
- **Agent memory (THIS RFC)** = what the agent accumulates from its own interactions (user preferences, derived facts, conversation history, procedural learnings). **Read-write by the agent at runtime. Experiential. Often per-user and privacy-sensitive.**
- **RAG / knowledge grounding (NOT this RFC)** = grounding generation on an externally-authored, read-mostly knowledge corpus (docs, codebase, KB). Different write semantics (separate ingestion pipeline), different governance (corpus provenance/freshness/access), different providers.

Vectorization is a shared dependency that **both** memory and RAG sit on. RAG and memory are **distinct consumers** of it. Therefore: this RFC implements **agent memory**, factors **vectorization as a shared substrate adapter** (so a future RAG RFC reuses it), and explicitly excludes RAG (§4, §12).

### 2.3 Short-term vs long-term memory

Within agent memory there are two sub-concerns, and the abstraction must represent both:

- **Short-term / session memory** — working context within a single conversation/session (event history, current task state). Framework-native today (e.g. ADK Session).
- **Long-term memory** — information persisted and retrieved **across** sessions and (optionally) across users (preferences, learned facts).

This RFC abstracts both, but they are different operations on the interface (§7).

---

## 3. Relationship to RFC-001 and RFC-002a/002b (read carefully)

These three RFCs are **complementary and independently shippable.** This RFC **does not assume RFC-001, RFC-002a, or RFC-002b are implemented first.**

- **Standalone:** memory integration is fully deliverable for the current ADK-only Zil. It wires a declared memory provider into the ADK-wired agent.
- **With RFC-002a (framework backend abstraction):** if the `FrameworkBackend` abstraction exists, memory wiring is performed *per backend* (each `FrameworkBackend` attaches a wired memory provider to its agent). If RFC-002a is not present, only the ADK path is wired. **Design the memory wiring so a second framework can attach later without rework**, but do not require it. OpenHands-specific memory attachment is RFC-002b.
- **With RFC-001 (contract enforcement):** memory operations are themselves tool-like and are a sensitive→egress surface. **[RFC-001 integration — optional]** memory read/write can be governed by the contract layer (e.g. flag a memory-write that persists sensitive data, or a memory-read whose result later flows to an egress tool). Fence this behind a check for RFC-001's presence; it must be skippable.

Every reference to RFC-001/002 below is marked **[RFC-00X integration — optional]** and must not block the core deliverable. Keep optional integrations in separate modules.

---

## 4. Goals and non-goals

### Goals
1. A neutral **`MemoryProvider`** interface (mirrors the LLM adapter / `FrameworkBackend` pattern), covering short-term and long-term memory operations.
2. A **shared vectorization substrate adapter** (embeddings + vector/graph store) that memory consumes when using a bring-your-own-store provider, and that a future RAG RFC can reuse.
3. Declarative configuration in the manifest (`adapters/memory.yaml` + a `spec.memory` reference), validated by `zil validate`.
4. Reference provider adapters: **Vertex AI Memory Bank** (first, lowest-friction), **Mem0** (neutrality-proving default), and **Zep/Graphiti** (advanced/optional).
5. `create_agent` wires the configured memory provider into the active framework.
6. Governance: `zil audit` memory findings (PII, retention, poisoning/injection surface, egress of remembered data); `zil pack` records the memory **configuration/binding** in the artifact and provenance — **never the memory data itself.**
7. **[RFC-001 integration — optional]** govern memory read/write through the contract layer.

### Non-goals (explicitly out of scope — these define the feature)
- **RAG / knowledge grounding / document corpora.** Externally-authored, read-mostly knowledge bases are a separate concern with different write semantics, governance, and providers. **Deferred to a future RFC (provisionally RFC-004).** Note that retrieval is frequently delivered *as a tool* (e.g. an MCP `search_knowledge_base` tool), which Zil's existing tools/MCP layer already supports — so RAG is partly covered there and does not belong here.
- **Building a memory store or a vector database.** Zil composes with providers; it does not host data (principles 1 and 3).
- **Owning the vector layer for managed providers.** Managed memory providers (Mem0 cloud, Zep Cloud, Vertex Memory Bank) manage their own embeddings/storage internally. Zil must **not** assume it always owns the substrate (§6.2).
- **Memory algorithms / consolidation logic.** How memories are extracted, scored, summarized, or consolidated is the provider's job, not Zil's.
- **Letta as a memory provider.** Letta is a full agent *framework/runtime*, not a memory layer; if relevant it is a candidate **framework backend** (RFC-002a/002b-style), not a memory adapter. Do not wire it here.

---

## 5. Architecture overview

```
                    zil.create_agent(manifest, identity, tools, ...)
                                       │
                                       │ reads spec.memory → adapters/memory.yaml
                                       ▼
                            MemoryProvider (selected adapter)
                ┌──────────────┬───────────────┬──────────────────┐
                ▼              ▼               ▼                  ▼
        VertexMemoryBank     Mem0          Zep/Graphiti     (future providers)
        (managed: owns       (managed or   (self-host:
         substrate)          self-host)     needs Neo4j)
                │ (bring-your-own-store providers only)
                ▼
        VectorizationSubstrate (shared adapter)         ◀── reusable by a future RAG RFC
        embeddings adapter + vector/graph store adapter

   create_agent attaches the wired MemoryProvider to the active framework:
       ADK  → map onto BaseMemoryService / Session service (VERIFY)
       OpenHands (RFC-002b) → map onto its memory model (VERIFY)

   [RFC-001 integration — optional, separate module]
       memory read/write decisions routed through the ToolCallInterceptor
```

Hard rules:
- The neutral `MemoryProvider` interface and the substrate adapter must have **zero provider-SDK imports**; only each provider adapter imports its own SDK.
- Provider adapters live in separate modules; the substrate adapter is independent of any specific memory provider.
- Framework wiring (attaching memory to ADK vs OpenHands) lives behind the framework boundary, not inline in `create_agent`.

---

## 6. Neutral core — types and interfaces

Reference signatures; adjust to house style but preserve semantics.

### 6.1 MemoryProvider

```python
from typing import Protocol, Optional, Any
from dataclasses import dataclass, field
from enum import Enum


class MemoryScope(Enum):
    SESSION = "session"     # short-term, single conversation
    USER = "user"           # long-term, across sessions for one user
    AGENT = "agent"         # long-term, shared across users for one agent
    # providers may not support all scopes — capability-report via supports()


@dataclass
class MemoryItem:
    content: Any
    scope: MemoryScope
    keys: dict = field(default_factory=dict)     # user_id / session_id / agent_id as applicable
    metadata: dict = field(default_factory=dict) # timestamps, source, provenance (provider-defined)


@dataclass
class MemoryQuery:
    text: Optional[str] = None                   # similarity query (None = non-semantic retrieval)
    scope: MemoryScope = MemoryScope.USER
    keys: dict = field(default_factory=dict)
    limit: int = 10


class MemoryProvider(Protocol):
    name: str  # "vertex_memorybank" | "mem0" | "zep" | ...

    def supports(self, scope: MemoryScope) -> bool:
        """Capability report — not all providers support all scopes."""
        ...

    def write(self, item: MemoryItem) -> None:
        """Persist a memory. For session scope this may be a no-op if the
        framework owns session state (see §8)."""
        ...

    def retrieve(self, query: MemoryQuery) -> list[MemoryItem]:
        """Retrieve memories (similarity or scoped fetch)."""
        ...

    def add_session(self, session_id: str, keys: dict) -> None:
        """Hand a completed session to the provider for long-term memory
        generation, where the provider supports it (e.g. Memory Bank's
        add_session_to_memory). No-op if unsupported."""
        ...

    def delete(self, keys: dict, scope: MemoryScope) -> None:
        """Deletion for retention / right-to-erasure. Required for governance."""
        ...
```

> Note: memory-generation *logic* (what to extract from a session) is the provider's responsibility. Zil's interface only triggers it (`add_session`) and reads/writes/deletes — it does not implement consolidation.

### 6.2 Vectorization substrate (shared adapter)

Only used by **bring-your-own-store** providers. Managed providers ignore it.

```python
class EmbeddingsAdapter(Protocol):
    name: str
    def embed(self, texts: list[str]) -> list[list[float]]: ...

class VectorStoreAdapter(Protocol):
    name: str  # "pgvector" | "qdrant" | "weaviate" | ...
    def upsert(self, ids: list[str], vectors: list[list[float]], payloads: list[dict]) -> None: ...
    def query(self, vector: list[float], top_k: int, filter: dict | None = None) -> list[dict]: ...

@dataclass
class VectorizationSubstrate:
    embeddings: EmbeddingsAdapter
    store: VectorStoreAdapter
```

**Critical design rule:** the `MemoryProvider` for a managed provider must treat the substrate as **provider-internal** and not require a `VectorizationSubstrate`. Only providers that expose bring-your-own-store accept one. Do not assume Zil owns the vector layer (§4 non-goal). This same `VectorizationSubstrate` is the reuse point for a future RAG RFC.

---

## 7. Reference provider adapters

Each adapter is the only module importing its provider SDK. **Verify all SDK entry points against pinned versions.**

### 7.1 `vertex_memorybank` — integrate first
- Lowest-friction step from the current ADK Sessions baseline. ADK exposes Memory Bank via a `BaseMemoryService` implementation (`VertexAiMemoryBankService`) and short-term context via the Session service. (Verify exact class/method names against the installed ADK + Vertex versions.)
- Map `MemoryProvider.add_session` → Memory Bank's session→memory generation; `retrieve` → its similarity/scoped retrieval; `write`/`delete` → its corresponding APIs.
- Managed substrate (provider-internal) — no `VectorizationSubstrate`.
- GCP-coupled — proves the pattern but **must not be the only provider** (cloud-neutrality).

### 7.2 `mem0` — neutrality-proving default
- Open-source, framework- and cloud-agnostic, broad adoption — the adapter that proves the abstraction is genuinely neutral across ADK *and* OpenHands and across clouds.
- Map scopes onto Mem0's user/session/agent memory model (verify).
- Supports managed and self-host; substrate may be provider-internal or BYO depending on deployment (verify).

### 7.3 `zep` — advanced / optional
- Temporal knowledge graph (Graphiti); strong for temporal/relational accuracy. Graphiti is self-hostable (Apache-2.0) but **requires Neo4j** — real operational weight; document it.
- Ship after Vertex + Mem0 prove the interface.

> Selection rationale, recorded so the backlog is unambiguous: **Vertex (low friction) + Mem0 (neutrality)** justify the abstraction; **Zep** is a power option; **Letta is excluded** as a memory provider (§4).

---

## 8. Framework wiring

`create_agent` selects the memory provider from the manifest, instantiates the adapter, and attaches it to the active framework:

- **ADK:** wire the provider onto ADK's memory mechanism — a `MemoryService` for long-term and the Session service for short-term — and register the appropriate memory tool(s) so the agent can recall during inference. ADK does **not** auto-orchestrate session→memory generation in all cases; where it doesn't, attach the trigger via the framework's callback mechanism (e.g. an after-agent/after-session callback calling `add_session`). **Verify ADK's current memory-service interface and whether memory generation is runner-orchestrated or callback-driven.**
- **OpenHands (RFC-002b) [optional]:** if the `FrameworkBackend` abstraction (RFC-002a) exists and the OpenHands backend is present, map the provider onto OpenHands' memory model. **Verify OpenHands' memory interface; if absent or different, document and limit to ADK.**

**Short-term scope handling:** if a framework already owns session state well (ADK Session), the provider's `write(SESSION)` may be a no-op and Zil simply uses the native session — the `MemoryProvider` abstraction still *represents* it for portability, but does not duplicate storage. Make this explicit so behavior is identical to today for ADK session memory.

---

## 9. Manifest schema additions

Add an `adapters/memory.yaml` (parallel to `adapters/llm.yaml`) and a `spec.memory` reference. Backward compatible: absence ⇒ current behavior (framework-native sessions only).

```yaml
# adapters/memory.yaml
provider: mem0                 # vertex_memorybank | mem0 | zep
mode: managed                  # managed | self_hosted
scopes: [session, user]        # which scopes this agent uses
retention:
  user: 90d                    # governance: retention policy per scope
  session: ephemeral
persist:                       # what is allowed into long-term memory
  include: [preferences, decisions]
  exclude_pii: true            # governance signal for zil audit
substrate:                     # ONLY for bring-your-own-store providers; omit for managed
  embeddings: { adapter: vertex_embeddings, model: text-embedding-005 }
  store: { adapter: pgvector, dsn_env: MEMORY_DB_DSN }
```

```yaml
# manifest.yaml (excerpt)
spec:
  memory: ./adapters/memory.yaml
```

`zil validate` must: confirm the provider is known; validate scope support against the adapter's `supports()`; require `substrate` to be **absent** for managed providers and **present** for BYO-store providers; validate retention/persist fields; and surface contradictions (e.g. `exclude_pii: false` with a `user` scope) as warnings.

---

## 10. Governance: audit and packaging

### 10.1 `zil audit` — memory findings
Add a memory-audit category emitting findings for: long-term memory holding PII while `exclude_pii` is false; missing/empty retention policy on a long-term scope; **memory poisoning / injection surface** (memory written from untrusted input and later retrieved as fact); and **[RFC-001 integration — optional]** remembered data that can flow to an egress tool (sensitive→egress via memory). These are findings, not hard blocks, consistent with audit's existing posture.

### 10.2 `zil pack` — what is and isn't packaged
- **Package:** the memory **configuration and binding** (provider, mode, scopes, retention, substrate config, **no secrets** — env-referenced) into the manifest and SLSA/cosign provenance. The artifact answers "*which memory backend, what scope, what retention, what PII policy*."
- **Never package:** the memory **data** itself. Memory lives in the provider for privacy and portability; the `.zil` is config-only. State this explicitly in code and docs.

---

## 11. [RFC-001 integration — optional] Contract-governed memory

**Skippable if RFC-001 is absent; fence behind a capability check; keep in a separate module.**

If RFC-001's `ToolCallInterceptor` exists, route memory `write`/`retrieve` through it so the contract layer can: gate a `write` that would persist sensitive data; taint `retrieve` results as sensitive-origin for the sensitive→egress dataflow check; and require approval for memory deletion in regulated contexts. This makes memory a first-class participant in the same enforcement pipeline as tools — but it is an enhancement, not a dependency.

---

## 12. RAG boundary (explicit, so it is not re-litigated)

RAG / knowledge grounding is **out of scope** and deferred to a future RFC (provisionally **RFC-004**). The reasons, recorded:

- Different write semantics (read-mostly corpus + separate ingestion vs. read-write experiential memory).
- Different governance (corpus provenance/freshness/access vs. PII/retention/poisoning).
- Different providers (vector DBs + embedding models + managed retrieval like Vertex AI Search vs. memory providers).
- Much of RAG is already served by Zil's **tools/MCP layer** (retrieval-as-a-tool), lowering the need for a dedicated subsystem.

The **only** shared element is the **`VectorizationSubstrate`** (§6.2), which this RFC factors out specifically so RFC-004 can reuse it without duplicating embedding/store configuration. Do not add corpus ingestion, document loaders, or knowledge-base concepts to the memory interface.

---

## 13. Acceptance criteria (write these as tests)

The neutral core (`MemoryProvider`, substrate) test-suite must run **without importing any provider SDK or agent framework** (use stub adapters).

1. **Interface neutrality:** core types + a stub `MemoryProvider` pass tests with no provider/framework dependency installed.
2. **Vertex adapter:** `write`/`retrieve`/`add_session`/`delete` map to verified Memory Bank entry points; managed substrate (no `VectorizationSubstrate` required).
3. **Mem0 adapter:** same operations across `session`/`user` scopes; works without GCP (proves cloud-neutrality).
4. **Scope capability:** requesting an unsupported scope yields a clear validation error via `supports()`.
5. **Substrate rule:** managed provider with a `substrate` block ⇒ validation error; BYO-store provider without one ⇒ validation error.
6. **ADK wiring:** an ADK agent retrieves a previously written long-term memory in a new session; short-term session behavior is unchanged vs. today (no duplicate storage).
7. **Audit:** PII-in-long-term-memory with `exclude_pii: false`, and a missing retention policy, each produce a finding.
8. **Pack:** `.zil` contains memory config/binding and provenance but **no memory data and no secrets** (assert data/secret absence explicitly).
9. **Deletion:** `delete` removes memory for a key/scope (retention / erasure path).
10. **[RFC-002b integration — optional]** memory attaches to an OpenHands backend when present; criteria 1–9 pass with this skipped.
11. **[RFC-001 integration — optional]** a memory write of sensitive data is gated by the interceptor; criteria 1–9 pass with this skipped.

---

## 14. Phased implementation plan (build order)

**Phase 0 — verification spike (do first, timebox).** Confirm against pinned versions: ADK's current memory-service interface and whether session→memory generation is runner-orchestrated or callback-driven; Vertex AI Memory Bank's class/methods; Mem0's scope model and SDK; (if RFC-002b present) OpenHands' memory interface. Output a findings note pinning exact APIs. **Do not build on assumptions.**

**Phase 1 — neutral core + Vertex adapter (ADK).** `MemoryProvider`, `MemoryScope`, `MemoryItem`/`MemoryQuery`, stub adapter, `vertex_memorybank` adapter, ADK wiring, `adapters/memory.yaml` + `spec.memory`, `zil validate`. Criteria 1, 2, 4, 5, 6.

**Phase 2 — Mem0 + governance.** `mem0` adapter (proves neutrality), `zil audit` memory findings, `zil pack` config-only packaging, `delete`/retention. Criteria 3, 7, 8, 9.

**Phase 3 — substrate + Zep (optional power path).** Factor/finish the `VectorizationSubstrate` for BYO-store, add `zep`/Graphiti (document Neo4j requirement). Hardens the substrate that RFC-004 will reuse.

**Phase 4 — [optional integrations].** RFC-002b OpenHands memory wiring; RFC-001 contract-governed memory. Criteria 10, 11. Both skippable.

---

## 15. File / module layout (suggested)

```
zil/
  memory/
    __init__.py
    types.py            # MemoryProvider, MemoryScope, MemoryItem, MemoryQuery
    registry.py         # provider registry keyed by name
    substrate.py        # EmbeddingsAdapter, VectorStoreAdapter, VectorizationSubstrate
    loader.py           # adapters/memory.yaml → provider + (optional) substrate
    providers/
      __init__.py
      vertex_memorybank.py   # ONLY file importing Vertex/ADK Memory Bank SDK
      mem0.py                # ONLY file importing Mem0 SDK
      zep.py                 # ONLY file importing Zep/Graphiti SDK
      stub.py                # test-only
  frameworks/                # (RFC-002a) — memory attachment per backend
    adk/memory_wiring.py
    openhands/memory_wiring.py   # [RFC-002b integration — optional]
  contract/
    adapters/memory_governance.py  # [RFC-001 integration — optional]
  ...
tests/
  memory/
    test_core_neutral.py
    test_vertex_adapter.py
    test_mem0_adapter.py
    test_validation_rules.py
    test_adk_wiring.py
    test_audit_findings.py
    test_pack_config_only.py
```

---

## 16. Open questions (resolve during implementation; Phase 0 answers most)

1. **ADK memory-generation trigger.** Runner-orchestrated vs. callback-driven `add_session` — confirm and standardize the wiring.
2. **Scope model normalization.** Providers model scope differently (user/session/agent/namespace). Confirm a clean mapping for each adapter; document where a provider can't express a scope.
3. **Short-term ownership.** When the framework owns session state well, does the provider abstraction stay a thin pass-through, or does Zil ever take over session storage? Default: pass-through (no duplication).
4. **Substrate exposure.** Which reference providers actually expose BYO-store vs. force managed substrate? Determines how much of §6.2 is exercised in v1.
5. **Erasure semantics.** Right-to-erasure / retention enforcement — does Zil trigger provider deletion, or only declare policy? v1: trigger `delete`; document provider support gaps.
6. **Telemetry.** Emit memory read/write/generate events via the agent's existing OTel config; do not create a separate exporter. Confirm the path.

---

## 17. Definition of done (core RFC-003, excluding optional integrations)

- Neutral `MemoryProvider` + substrate merged; core tests pass with no provider/framework installed.
- `vertex_memorybank` and `mem0` adapters working; an ADK agent recalls long-term memory across sessions; short-term session behavior unchanged.
- `adapters/memory.yaml` + `spec.memory` parsed and validated (incl. managed-vs-BYO substrate rule).
- `zil audit` emits memory findings; `zil pack` records memory config/binding + provenance with **no memory data and no secrets**.
- Acceptance criteria 1–9 pass in CI; criteria 10–11 cleanly skipped when RFC-001/002 absent.
- Docs page under `getzil.dev/docs` for the memory adapter, scopes, governance, **and an explicit RAG-is-out-of-scope boundary note (§12).**
- No Zil-owned memory store or vector DB introduced (principles upheld).

---

## 18. References (verify against installed versions)

- Google ADK — `BaseMemoryService`, Session service, memory tools, callbacks; whether memory generation is runner- or callback-driven.
- Vertex AI Agent Engine Memory Bank — session→memory generation, retrieval, scopes; ADK `VertexAiMemoryBankService` wrapper.
- Mem0 — memory model, scopes, self-host vs managed, SDK.
- Zep / Graphiti — temporal knowledge graph, Neo4j requirement, self-host (Apache-2.0).
- ZIL-RFC-001 (contract enforcement), ZIL-RFC-002a (framework backend abstraction), ZIL-RFC-002b (OpenHands framework) — complementary, not assumed implemented.
- MCP — relevant to RAG-as-a-tool (the out-of-scope boundary, §12).
- OpenTelemetry — telemetry path.
- Zil docs — manifest schema, `adapters/llm.yaml` (the pattern this RFC mirrors), `create_agent`, `zil validate/audit/pack`, `.zil` archive, cosign/SLSA provenance.
