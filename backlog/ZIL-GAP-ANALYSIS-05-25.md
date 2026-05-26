# Zil — Implementation Gap Analysis & RFC Roadmap

| Field | Value |
|---|---|
| **Baseline spec** | Zil Framework v2.0 (seven-pillar methodology + reference architecture) |
| **Implementation reviewed** | `zil-ai` v0.1.17 (changelog 0.1.0 → 0.1.17), getzil.dev/docs |
| **Date** | 2026-05-25 |
| **Purpose** | Map what's built vs. what the spec promises; organize the remainder into candidate RFCs. |
| **Existing RFCs** | RFC-001 (tool contract enforcement), RFC-002 (OpenHands framework), RFC-003 (memory layer). This document situates them and proposes RFC-004 onward. |

---

## 1. How to read this

The spec defines **seven pillars** plus a **reference architecture** (package format + runtime conformance + adapter pattern). This document scores each pillar's implementation status against the shipped product, then converts the gaps into a prioritized RFC roadmap.

Status legend: **Built** (shipped & documented) · **Partial** (meaningful pieces shipped, material gaps remain) · **Missing** (essentially unaddressed in code).

A caveat on method: this is derived from the changelog and public docs, not the source tree. Where the changelog is ambiguous, I mark it and recommend confirming against the repo. The changelog is unusually detailed, so confidence is high for "Built" items and medium for "Missing" (absence of evidence).

---

## 2. Executive summary

Zil v0.1.17 has built a genuinely strong **single-agent build-and-ship spine**: scaffold → validate → eval-gate → pack → sign → push → deploy, with MCP tools, runtime guardrails, an agent-native security audit, OTel tracing, token-cost tracking, env management, multi-agent scaffolding, and HITL primitives. In spec terms, **Pillar 7 (Architecture & Packaging)** and **Pillar 5 (Evaluation)** are the most complete, and **Pillar 2 (Security)** has a real, differentiated head start via `zil audit` and the guardrail engine.

The gaps cluster in four areas, in rough priority order:

1. **Data & Memory (Pillar 3)** — almost entirely missing. No memory abstraction, no PII/residency/right-to-forget. This is the single biggest hole. *(RFC-003 already drafted; this analysis confirms its priority and surfaces sub-gaps it doesn't yet cover.)*
2. **Cost & multi-provider portability (Pillar 6 + reference-architecture adapter promise)** — cost *tracking* is built, but cost *governance* (enforcement, routing, multi-provider fallback) and the **embedding/vector-store adapters** the spec explicitly promises are missing. The adapter pattern is currently **LLM-only**.
3. **Runtime conformance & reliability (Pillar 4 + reference architecture)** — the spec's headline "package-spec vs runtime-spec" separation does not exist yet: there is no published runtime conformance contract, and no crash recovery / checkpointing / state durability for long-running agents.
4. **Governance & lifecycle at fleet scale (Pillar 1)** — registry-of-packages, approval workflows, risk tiering, deprecation, ownership/SLA are missing as product features (deploy targets a single Cloud Run service; there's no agent registry-of-record or approval gate).

Cross-cutting: the product is currently **GCP/Cloud-Run-and-ADK-coupled**, while the spec sells **cloud and framework portability** as the core commercial hedge. RFC-002 (OpenHands) addresses framework portability; nothing yet addresses cloud-runtime portability or the conformance contract that would make portability real.

---

## 3. Pillar-by-pillar gap analysis

### Pillar 1 — Governance & Lifecycle — **Partial (lean toward Missing)**
**Built:** signed artifacts + SLSA provenance + SBOM give the *evidentiary substrate* for governance; whole-agent versioning via `.zil`; `zil inspect --verify`.
**Missing:** agent **registry of record** (an OCI registry stores artifacts, but there's no registry *of agents* with ownership, approvals, version history as a queryable system); **multi-stakeholder approval workflow**; **risk tiering**; **deprecation/sunset policy**; **ownership & SLA registration**; human **oversight UX** (dashboards, approval queues) — only HITL *primitives* exist (`request_human_input`/`resolve_human_input`), not the operating-model layer.
**Note:** much of this pillar is arguably *product/platform* surface beyond a CLI/SDK; some may be intentionally services-layer. Worth an explicit scope decision (see RFC-007).

### Pillar 2 — Security & Adversarial Hardness — **Partial (strong start)**
**Built:** `zil audit` (injection resilience over 20 adversarial prompts/6 categories, output-leakage scan, **indirect-injection AST surface analysis**, instruction-consistency, context-window risk, identity hardening); runtime `GuardrailEngine` (injection + PII patterns, denied topics, output constraints); MCP permission audit (over-permission, risky host deps); supply chain (SBOM, cosign, SLSA).
**Missing / partial:** **least-privilege tool *enforcement*** (audit flags over-permission, but there's no runtime capability-grant enforcement — *this is exactly RFC-001*); **memory poisoning testing** (no memory layer to test — blocked on RFC-003); **A2A authentication / agent identity** (no cryptographic per-agent identity, no authenticated A2A); **repeatable red-team playbook / regression harness** (audit is point-in-time, not a managed regression suite). 
**Mapping:** RFC-001 fills the tool-enforcement gap. A2A auth and memory-poisoning testing are net-new (RFC-005, RFC-003 respectively).

### Pillar 3 — Data & Memory Protection — **Missing**
**Built:** nothing memory-specific. Guardrail PII *pattern* detection on I/O exists, which is a fragment of "PII filtering," but there is no memory subsystem at all.
**Missing:** the entire memory abstraction (episodic/semantic/procedural); memory classification & **retention**; **right-to-forget cascade**; **data residency mapping**; **cross-agent data boundaries**; document-level access control in retrieval (RAG); knowledge/semantic layer.
**Mapping:** RFC-003 (memory layer) covers the core. But RFC-003 as drafted is scoped to *provider integration + basic governance hooks* — it does **not** fully cover right-to-forget cascade, residency mapping, or cross-agent data boundaries. Those are either RFC-003 expansions or a dedicated **RFC-006 (Data Governance & Compliance)**. RAG is the deferred **RFC-004**.

### Pillar 4 — Observability & Reliability — **Partial**
**Built (observability side is solid):** OTel tracing (`zil run --trace`, OTLP export, console export), `setup_telemetry`, observability config, cost spans, guardrail spans, Grafana OTEL-LGTM stack for local. Span *types* partially realized (guardrail check, MCP tool call, cost).
**Missing (reliability side is largely absent):** **state durability / checkpointing**; **crash recovery / resumable execution**; **long-running agent patterns** (persistent goal state across days, long-horizon audit retention); **idempotency for tool calls** (spec calls out dedup keys/retry — overlaps RFC-001's idempotency contract but the *reliability* mechanism, e.g. checkpoint+resume, is separate); **production replay / shadow mode**; **semantic drift detection**. The full standardized **agent span taxonomy** (session/turn/reasoning/memory r-w/skill/HITL) is only partially emitted.
**Mapping:** reliability is a coherent net-new chunk → **RFC-008 (Reliability & Long-Running Execution)**. Drift detection + production replay sit at the Pillar 4/5 boundary → fold into RFC-009 (eval-in-production) or RFC-008.

### Pillar 5 — Evaluation & QA — **Partial (strong)**
**Built:** `zil eval` group (`run/add/record/generate`), DeepEval integration, per-metric thresholds, LLM-as-judge case synthesis, concurrency/retries, **eval gate blocks deploy**. This is one of the most mature pillars.
**Missing:** **eval-in-production** (sample 1–5% of prod traffic for continuous scoring); **staged rollout** (shadow/canary/A-B with auto-rollback); **production replay** (shared with Pillar 4); **multi-turn / planning-quality / tool-use-correctness** as first-class eval dimensions (current evals look case/metric-based; tool-use-correctness specifically connects to RFC-001 contracts and RFC-002b coding evals); **cost-per-task regression gate** (cost is tracked, but not a promotion gate).
**Mapping:** **RFC-009 (Eval-in-Production & Staged Rollout)** — the continuous/production half of evaluation.

### Pillar 6 — Cost & Resource Governance — **Partial**
**Built:** `spec.cost` token budgets (per-request/session), `zil.cost` tracker, `CostCallback` extracting usage across Gemini/OpenAI/Anthropic, alert thresholds, `zil validate`/`inspect` cost surfacing. Token *tracking* and *budget declaration* are solid.
**Missing:** **budget *enforcement*** (the changelog frames cost as tracking; enforcement/hard-cap behavior on breach — reject/degrade/escalate — appears absent or partial); **model routing by complexity**; **rate limiting** (TPM/RPM/concurrency); **multi-provider fallback** (depends on a provider-abstraction that doesn't fully exist); **cost attribution** by team/customer/tenant; **prompt compression/caching**; **dollar conversion** (explicitly deferred to an external runtime service).
**Mapping:** **RFC-010 (Cost Governance & Model Routing)**. Note hard dependency on the provider/adapter abstraction (RFC-004-adjacent).

### Pillar 7 — Architecture & Packaging — **Built (with notable exceptions)**
**Built:** declarative manifest; `.zil` signed tar archive with SBOM (CycloneDX 1.5) + provenance + cosign; OCI push via ORAS; deploy (Cloud Run) with eval gate, env injection, Cloud SQL auto-wiring; **multi-agent scaffolding** (`spec.agents`, orchestrator + sub-agents, MCP assignment); HITL primitives; runtime dependency declarations; skills convention; MCP integration & bundling. This pillar is largely realized.
**Missing / partial vs. spec:**
- **Adapter pattern is LLM-only.** Spec promises LLM **+ embedding + vector store** adapters as first-class swappable config. Embedding/vector adapters are not built. → blocks RFC-003/004/010.
- **Runtime conformance specification + cloud adapters** — the spec's central "package-spec vs runtime-spec (OCI-style)" separation **does not exist**. There is no runtime contract (load/session/turn/checkpoint/restore/HITL/observability interface), and deploy is hardwired to **Cloud Run + ADK**. **This is where AWS/Azure/neocloud support lives**, and it is two things: the **conformance contract** (designed once) and **per-platform adapters** (Cloud Run, Modal, AWS, Azure, k8s — each its own item; "support AWS" = contract + AWS adapter). Keystone gap for the portability story. → **RFC-011 (contract + Cloud Run reference) + the RFC-011 adapter series**.
- **Multi-agent *topology* governance** — scaffolding exists, but the spec's richer claims (declared topology of who-talks-to-whom, **what context can transfer**, A2A handoffs, **shared-memory boundaries**, system-level evaluation) are largely unbuilt. → **RFC-005 (Multi-Agent Topology & A2A)**.
- **Portable vector snapshots** (`data/` RAG bundles restorable into any backend) — not built; depends on vector adapter + RAG. → RFC-004.
- **Rollback / canary** as pipeline features — not evidenced. → RFC-009.

---

## 4. Cross-cutting gaps (not owned by one pillar)

### 4.1 The portability theme — three layers of the same idea

The spec's headline commercial argument is **no lock-in**: tooling-agnostic, deploy-anywhere, hedge against single-provider dependency (the "67% want to avoid single-provider dependency" / "57% spent >$1M on migrations" framing). Today the product is coupled on **three independent axes**, and portability is only real when all three are swappable. These are the same architectural move — turn a hardwired dependency into a swappable adapter behind an interface — applied at three layers:

| Layer | Coupled to today | Makes it swappable | RFC |
|---|---|---|---|
| **Framework** | ADK only | `FrameworkBackend` abstraction | **RFC-002a** |
| **Provider** (LLM/embedding/vector) | LLM adapter only; embedding/vector absent | provider adapter set | **RFC-004** |
| **Runtime** (where it executes) | Cloud Run + ADK deploy hardwired | runtime conformance **contract** (RFC-011) + per-platform **adapters** (RFC-011 series) | **RFC-011 (+ adapters)** |

Treat these as one **portability theme**, not three scattered RFCs. None alone satisfies the spec's promise: RFC-011 makes the *runtime* swappable, RFC-002a makes the *framework* swappable, RFC-004 makes *providers* swappable. **RFC-002a + RFC-011 together** are what actually deliver "deploy any framework, anywhere." All three are strategic, co-equal gaps — the earlier draft under-weighted framework portability relative to cloud portability; they are peers.

> **The runtime layer is itself two things, not one** (this is where AWS/Azure/neocloud support actually lives). RFC-011 splits into (a) the **conformance contract** — the abstract runtime interface, designed once — and (b) **per-platform runtime adapters** — Cloud Run, Modal, AWS (ECS/Fargate), Azure (Container Apps), k8s — each its own item. **"Support AWS" = the contract *plus* an AWS adapter, not one ticket.** Recommended adapter sequence: **Cloud Run** (refactor existing → known-good reference) → **Modal** (neocloud; the *second* adapter, deliberately chosen as the contract's neutrality proof because it's most architecturally different, and a differentiated capability for sandboxed agentic workloads) → **AWS / Azure / k8s** (enterprise breadth, landing on a battle-tested contract). Modal is prioritized as the neutrality-prover, **not** ahead of the hyperscalers commercially — the sequencing captures the neocloud upside while the hyperscaler/sovereign adapters carry the enterprise-portability rationale.

### 4.2 Other cross-cutting gaps

1. **Framework breadth is an *abstraction*, not a *product*.** The capability "support frameworks beyond ADK" is the `FrameworkBackend` extraction (**RFC-002a**) — foundational, small, a prerequisite for *every* future framework. It must not be conflated with the OpenHands *adapter* (**RFC-002b**), which is one specific, heavier binding and a strategic vertical bet. Build the abstraction early and unconditionally; resource specific adapters (OpenHands, later LangGraph/CrewAI) on demand. Once the abstraction exists, additional framework adapters are cheap follow-ons not worth pre-speccing.
2. **Fleet/platform vs. toolchain boundary.** Several Pillar 1 items (registry-of-record, approval workflows, oversight dashboards) may be a *platform/services* layer rather than `zil-ai` CLI/SDK features. Needs an explicit product-scope decision before speccing.

---

## 5. Proposed RFC roadmap

Existing (in flight): **RFC-001** tool contract enforcement · **RFC-002** OpenHands framework · **RFC-003** memory layer.

> **RFC-002 should be split.** It currently bundles two separable things: (a) the **`FrameworkBackend` abstraction** that makes ADK one swappable backend among many — foundational and framework-agnostic — and (b) the **OpenHands backend** itself — one specific, heavy adapter. These belong in different waves. Below they appear as **RFC-002a** (abstraction) and **RFC-002b** (OpenHands adapter, = the current RFC-002 body).

Proposed RFCs (IDs are suggestions; sequence within tiers is the recommendation):

| RFC | Title | Pillar(s) | Size | Depends on | Why this grouping |
|---|---|---|---|---|---|
| **RFC-002a** | Framework Backend Abstraction | 7 (+ enables framework breadth) | S–M | — (foundational) | Refactor `create_agent` so ADK is one backend behind a `FrameworkBackend` interface. Prerequisite for **every** non-ADK framework. Same architectural move as RFC-004. **Wave 1.** |
| **RFC-002b** | OpenHands Framework Backend | 7, 5 | L | RFC-002a | The current RFC-002 body. First *proof* the abstraction is real + the autonomous-coding-agent vertical bet. Strategic; **Wave 2.** |
| **RFC-004** | Provider Adapters (Embedding + Vector Store) **&** RAG/Knowledge Grounding | 7, 3 | M | — (adapters) / adapters→RAG | The adapter half is small and **unblocks 003/010**; do it first even if RAG defers. RAG is the larger second half. |
| **RFC-005** | Multi-Agent Topology & A2A Security | 7, 2, 1 | L | RFC-001 (identity/enforcement helps) | Turns multi-agent *scaffolding* into governed *topology*: declared context-transfer, A2A auth/identity, shared-memory boundaries, system-level eval. |
| **RFC-006** | Data Governance & Compliance | 3 | M | RFC-003 | Right-to-forget cascade, residency mapping, cross-agent data boundaries, retention SLAs. The compliance half of Pillar 3 that RFC-003 doesn't cover. |
| **RFC-007** | Agent Registry & Lifecycle Governance | 1 | L | — | Registry-of-record, approval workflows, risk tiering, ownership/SLA, deprecation. **Scope decision first** (toolchain vs platform). |
| **RFC-008** | Reliability & Long-Running Execution | 4 | L | RFC-011 (runtime contract) | Checkpointing, crash recovery, resumable execution, durable long-horizon state/audit. Pairs naturally with the runtime spec. |
| **RFC-009** | Eval-in-Production & Staged Rollout | 5, 4 | M | RFC-008 (replay needs durable capture) | Prod traffic sampling, shadow/canary/A-B, auto-rollback, drift detection, cost-per-task gate. The continuous half of evaluation. |
| **RFC-010** | Cost Governance & Model Routing | 6 | M | RFC-004 (provider abstraction) | Budget enforcement, routing by complexity, rate limiting, multi-provider fallback, attribution. Upgrades cost *tracking* → *governance*. |
| **RFC-011** | Runtime Conformance **Contract** | 7 (+ enables all) | L | — (foundational) | The package-spec/runtime-spec separation. Defines the load/session/turn/checkpoint/HITL/observability contract that makes cloud portability real. Keystone. Includes the **Cloud Run** reference adapter (refactor). |
| **RFC-011·Modal** | Runtime Adapter: Modal (neocloud) | 7 | M | RFC-011 | Second adapter, by design: neutrality proof (most different from Cloud Run) + differentiated sandboxed-agent capability (synergy with RFC-002b coding agents). |
| **RFC-011·AWS** | Runtime Adapter: AWS (ECS/Fargate) | 7 | M | RFC-011 | Primary AWS enterprise target. Follow-on, lands on the proven contract. |
| **RFC-011·Azure** | Runtime Adapter: Azure (Container Apps) | 7 | M | RFC-011 | Primary Azure enterprise target. Follow-on. |
| **RFC-011·k8s** | Runtime Adapter: Kubernetes (self-host/sovereign) | 7 | M | RFC-011 | Self-hosted / on-prem / sovereign — the residency & compliance story. High enterprise value after hyperscalers. Follow-on. |

> **The portability theme (§4.1) spans RFC-002a + RFC-004 + RFC-011.** Framework, provider, and runtime are the same swap-the-dependency move at three layers. Consider tracking them as one theme even though they ship as separate RFCs across waves.

### Suggested sequencing (three waves)

**Wave 1 — unblock and complete the in-flight work.**
The two foundational abstractions land first because they unblock the most: **RFC-002a** (framework backend) and **RFC-004** (provider/embedding/vector adapters) — the same architectural move at two layers. **RFC-003** (memory, already drafted) lands on the RFC-004 adapters; **RFC-001** (enforcement) proceeds in parallel.

**Wave 2 — make the portability story real and govern the fleet.**
**RFC-011 (the runtime conformance contract + Cloud Run reference adapter)** — the third portability layer and keystone of the commercial claim — and **RFC-007** (registry/governance) after its scope decision. **RFC-002b** (OpenHands backend) lands here as the first proof RFC-002a's abstraction is real and the coding-agent vertical bet. **RFC-005** (multi-agent/A2A) here too, since topology governance is increasingly the default architectural unit. The **Modal** adapter (RFC-011·Modal) follows immediately after the contract as its neutrality proof.

**Wave 3 — operational maturity + cloud breadth.**
Runtime adapter breadth lands here as demanded: **RFC-011·AWS → RFC-011·Azure → RFC-011·k8s** (each on the proven contract; sequence by customer demand). Plus RFC-008 (reliability/long-running — builds on the contract's checkpoint/restore) → RFC-009 (eval-in-production, needs durable capture) → RFC-010 (cost governance, needs provider abstraction) → RFC-006 (data compliance, needs memory).

> **If forced to pick the single highest-leverage next RFC after the current three:** **RFC-011 (Runtime Conformance)** — it's the third leg of portability and its absence quietly undermines the "no lock-in" argument. But the highest-leverage *small* items are the two Wave-1 abstractions: **RFC-002a** and **RFC-004**, which together unblock framework breadth, memory, RAG, and cost routing for little code.

---

## 6. What's genuinely strong already (don't re-spec)

To keep the roadmap honest, these spec areas are effectively delivered and should not absorb new RFC effort beyond maintenance: the `.zil` package format and signing/SBOM/provenance chain; the eval framework and deploy-time eval gate; the agent-native security audit and runtime guardrail engine; OTel tracing integration; token cost tracking; env declaration/drift detection; MCP integration and bundling; single-agent and basic multi-agent scaffolding; HITL primitives.

---

## 7. Open scope decisions to make before speccing

1. **Toolchain vs platform boundary (RFC-007).** Is the agent registry-of-record, approval workflow, and oversight dashboard part of `zil-ai`, or a separate FluentData platform/service? This determines whether Pillar 1 is RFC'd as code or as a services offering.
2. **How much of Pillar 1/3 governance is delivered as ISO-42001 *evidence generation* vs. *enforcement*.** The spec's ISO-42001 section frames much governance as evidence produced as a byproduct. Decide per-capability whether Zil *enforces* or merely *evidences*.
3. **Runtime conformance ambition (RFC-011) — now drafted.** Full OCI-style published spec others can implement, or a pragmatic internal interface that just decouples Zil from Cloud Run first? RFC-011 (drafted) recommends building the internal contract first and treating publication as a later additive step gated on a second adapter proving it. **Confirm this choice**, plus the cloud-adapter sequence (Cloud Run reference → Modal neutrality-proof → AWS/Azure/k8s breadth) and the Modal capability claims (verify against current docs before encoding in the adapter).
4. **RFC-003/004 split point.** Confirm the memory/RAG boundary (already drawn) and where the shared vectorization substrate lands — RFC-004 owns it, RFC-003 consumes it.
