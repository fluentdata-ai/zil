# ZIL-RFC-002b — OpenHands Framework Backend

| Field | Value |
|---|---|
| **Status** | Draft / Backlog |
| **Target component** | `zil-ai` Python SDK (`OpenHandsBackend`), `zil init` (scaffold), manifest schema, `zil deploy` (runtime integration), `zil eval` (coding-task evals) |
| **Owner** | FluentData / Zil maintainers |
| **Zil version target** | post-v0.1 |
| **License** | Apache 2.0 |
| **Depends on** | **ZIL-RFC-002a (Framework Backend Abstraction) — HARD PREREQUISITE.** This RFC implements one `FrameworkBackend`; the interface, registry, `AgentSpec`/`WiredAgent`, and the ADK refactor are defined there and assumed present. |
| **Related** | ZIL-RFC-001 (Tool Contract Enforcement) and ZIL-RFC-003 (Memory Layer) — **complementary, optional integrations (see §3)**, not prerequisites. |
| **Document purpose** | Implementation spec intended to be handed to an LLM coding agent. Be pragmatic. Prefer the smallest correct increment. |

---

## 0. How to read this document

This spec assumes RFC-002a is implemented (or implemented concurrently). It does **not** re-specify the `FrameworkBackend` interface, the registry, `AgentSpec`/`WiredAgent`, or the ADK refactor — those are RFC-002a. This document specifies **only** the OpenHands backend that plugs into that abstraction.

Section 1 orients on Zil + the assumed abstraction. Section 2 orients on OpenHands and the "why." Section 3 covers optional integrations with RFC-001/003. Sections 4–12 are design and requirements. Section 13 is acceptance criteria. Section 14 is the build plan — **Phase 0 (verification spike) first.**

When this document and the live Zil codebase disagree, the codebase wins; flag the discrepancy. **OpenHands is an external, fast-moving platform: every API, SDK entry point, runtime behavior, and configuration field referenced here MUST be verified against the pinned version before relying on it.** Where this document says "verify," treat it as a hard gate. Do not confabulate OpenHands APIs — if you cannot confirm a hook or entry point exists, stop and surface it as an open question.

> **Split note.** This RFC is the OpenHands-specific half of the original RFC-002. The framework-agnostic half (the `FrameworkBackend` abstraction + ADK refactor) is now RFC-002a and is a prerequisite below.

---

## 1. Primer: Zil + the assumed abstraction

Zil is an open-source CLI and Python SDK for validating, packaging, and deploying production AI agents. It composes with ADK (agent framework), MCP (tools), DeepEval (evals), and OpenTelemetry (tracing). The manifest is the contract; `zil pack` produces a signed, portable `.zil` archive; the SDK's `create_agent(...)` returns a wired agent.

**Assumed from RFC-002a:** a `FrameworkBackend` interface with `wire(spec) -> WiredAgent`, `run_local(agent)`, and `deploy_descriptor(agent, spec)`; a `BackendRegistry` keyed by `runtime.framework`; a framework-neutral `AgentSpec` (name, version, instructions, model, tools, mcp_servers, observability, raw_manifest); and an `AdkBackend` already implementing the interface. **This RFC adds `OpenHandsBackend` as a second registered backend.** No `create_agent` branching is added — registration is the integration point.

Four guiding principles still constrain this feature:
1. **Built on what exists** — compose with OpenHands; do not reinvent its runtime.
2. **Declarative-first** — manifest is the contract.
3. **No new runtime** — agents run in the OpenHands runtime the user controls.
4. **No new registry** — unchanged.

---

## 2. Primer + problem statement: OpenHands and the "why"

**What OpenHands is (verify against installed version).** OpenHands is an open-source, model-agnostic platform for **autonomous cloud coding agents** — agents that plan, write, and apply changes across a codebase end-to-end, rather than suggesting snippets interactively. Properties relevant here:

- **Autonomous and headless-capable**: triggered from GitHub/GitLab/Slack/CI or via API/SDK; runs tasks to completion, including in parallel at scale.
- Ships an **SDK** for embedding agents, a **CLI**, and a hosted cloud option.
- Runs agents inside a **secure, sandboxed runtime the user controls** — isolated Docker or Kubernetes, self-hosted or private cloud — with its own access control and execution auditability.
- **Model-agnostic**; integrates with CI/CD and source control natively.

**Why this belongs in Zil.** An autonomous coding agent is a *deployed artifact that acts on production code with little human-in-the-loop* — exactly the class Zil exists to make shippable. The pains Zil targets ("no manifest, no eval gate, no signed artifact, no audit; works in a demo, breaks in prod") are most acute here: an autonomous agent opening PRs against real repos needs identity, provenance, guardrails, eval-gating, and contract-level tool safety. OpenHands support lets Zil produce **governed, identifiable, eval-gated autonomous coding agents** as portable signed artifacts — a sharp, differentiated capability and the first proof that RFC-002a's abstraction is real.

**What OpenHands already provides (so Zil does NOT reinvent it).** Sandbox isolation, runtime access control, and execution-level auditability are **OpenHands'**. Zil's additive value on top is specifically: a **declarative manifest** as single source of truth; a **signed, portable `.zil` artifact** with SLSA/cosign provenance ("which exact agent config acted"); **eval-gated promotion** (incl. coding benchmarks); **per-tool contract enforcement** (via RFC-001); and **one governance model across frameworks** (ADK and OpenHands governed identically). Position OpenHands support as **complementary to** OpenHands' native runtime security, not competing with it. (Document the seam — §16.5.)

---

## 3. Optional integrations with RFC-001 and RFC-003

RFC-002b is **independently shippable**. It does not assume RFC-001 or RFC-003 are implemented.

- **With RFC-001 (contract enforcement) [optional]:** provide an OpenHands adapter binding RFC-001's `ToolCallInterceptor` to OpenHands' tool/event interception point (§9). Fenced behind a capability check; skippable; separate module.
- **With RFC-003 (memory) [optional]:** if the memory layer exists, attach the wired `MemoryProvider` to the OpenHands agent in `wire()` via OpenHands' memory model (verify it exists). Skippable.

Every reference to RFC-001/003 below is marked **[optional]** and must not block the core deliverable. Keep optional integrations in separate modules.

---

## 4. Goals and non-goals

### Goals
1. Implement `OpenHandsBackend(FrameworkBackend)` and register it for `runtime.framework: openhands`.
2. Map Zil's declarative concepts (instructions, model, tools, MCP servers, observability) onto OpenHands' SDK configuration in `wire()`.
3. Scaffold OpenHands autonomous-coding-agent projects via `zil init --framework openhands`.
4. Back `zil run` (`run_local`) and `zil deploy` (`deploy_descriptor`) for OpenHands — deploying into an OpenHands runtime the user controls.
5. Enable `zil eval` to gate OpenHands coding agents, including SWE-bench-style coding-task suites where feasible.
6. **[RFC-001 optional]** OpenHands adapter for the contract interceptor. **[RFC-003 optional]** attach memory provider.

### Non-goals
- **The framework abstraction itself** — that is RFC-002a.
- Reimplementing OpenHands' sandbox/runtime/access control (§2).
- Supporting *interactive pair-programmer* coding tools — this RFC targets **autonomous/headless** coding agents only.
- A Zil-owned runtime (principle 3); the OpenHands runtime runs on the user's infra.
- A third framework; OpenHands only (the abstraction allows more later).
- RFC-001/003 themselves — only the optional OpenHands *bindings*.

---

## 5. Architecture overview

```
        zil.create_agent(...) → registry.get("openhands") → OpenHandsBackend   ← registered per RFC-002a
                                          │
                                          ▼
                             OpenHandsBackend.wire(spec)
                       maps AgentSpec → OpenHands SDK agent config
                                          │
                                          ▼
                  runs in OpenHands sandboxed runtime (Docker/K8s, user-controlled)

   [RFC-001 optional, separate module]   ToolCallInterceptor ─bind─▶ OpenHands tool/event hook (VERIFY §9)
   [RFC-003 optional]                    MemoryProvider attached in wire() via OpenHands memory model (VERIFY)
```

Hard rules:
- `OpenHandsBackend` is the **only** module importing the OpenHands SDK.
- Optional RFC-001 interceptor binding lives in a separate module from the backend.
- No changes to `create_agent` beyond backend registration (which RFC-002a's registry already supports).

---

## 6. The OpenHands backend

Implement `OpenHandsBackend(FrameworkBackend)` in `zil/frameworks/openhands/backend.py` (only module importing the OpenHands SDK). Map each responsibility to a **verified** OpenHands SDK entry point — do not assume names.

1. **`wire(spec)`** — construct an OpenHands agent from `AgentSpec`:
   - `spec.instructions` → OpenHands agent system/instruction config.
   - `spec.model` → OpenHands model config (model-agnostic; map provider/model/params).
   - `spec.tools` + `spec.mcp_servers` → OpenHands' tool system / MCP config. **OpenHands supports MCP (verify), so prefer wiring MCP servers natively rather than re-implementing tools.**
   - `spec.observability` → OpenHands tracing/telemetry or an attached OTel exporter (verify; reuse the agent's OTel config, do not create a parallel exporter).
   - **[RFC-003 optional]** attach the wired `MemoryProvider` via OpenHands' memory model.
   - Return a `WiredAgent` whose `framework == "openhands"`.
2. **`run_local(agent)`** — back `zil run` by invoking the agent through the OpenHands SDK/CLI for a single task or interactive session (verify the local-execution entry point; see open question §16.2).
3. **`deploy_descriptor(agent, spec)`** — emit what `zil deploy` needs to stand the agent up in an OpenHands runtime: sandbox/runtime requirements (Docker/K8s), entrypoint, env vars, source-control/CI trigger wiring. **The OpenHands runtime is the deploy target; Zil does not introduce its own.**

The backend translates declarative config → OpenHands SDK calls. It must not embed coding-agent *behavior* (that's OpenHands'); it only configures and wires.

---

## 7. `zil init` — OpenHands scaffold preset

Add an `openhands` preset to `zil init` that scaffolds a working autonomous coding-agent project (mirroring the standard Zil layout). Generated `manifest.yaml` sets `runtime.framework: openhands` and pre-populates **tool contract annotations** for the typical autonomous-coding toolset (inert without RFC-001, but correct and future-proof):

```yaml
spec:
  runtime:
    framework: openhands
    language: python
  tools:
    - name: run_shell
      contract: { destructive: true, reversible: false, idempotent: false }
    - name: write_file
      contract: { destructive: true, reversible: true, idempotent: false }
    - name: read_repo
      contract: { read_only: true, sensitive: true, idempotent: true }
    - name: open_pull_request
      contract: { destructive: false, egress: true, idempotent: false }
    - name: git_push
      contract: { destructive: true, reversible: false, egress: true, idempotent: false }
```

> The `contract:` blocks follow RFC-001's schema and are scaffolded regardless of whether RFC-001 is implemented. `zil validate` should accept them either way; only RFC-001 makes them enforce at runtime.

Scaffold also includes: `identity/` (persona/instructions/guardrails for a careful autonomous coding agent), `adapters/llm.yaml`, `evals/` (with a coding-task suite — §11), `observability/config.yaml`, a `Dockerfile` for the OpenHands runtime image (verify base/image guidance), and CI trigger wiring (issue → agent → PR) where applicable.

---

## 8. Manifest schema changes

1. **`runtime.framework`** accepts `openhands` (RFC-002a makes this the backend selector; this RFC registers the backend). `zil validate` validates OpenHands-specific required fields (runtime/sandbox settings, source-control integration) when `framework: openhands`.
2. **Tool `contract` blocks** (RFC-001 schema) accepted and schema-validated by `zil validate` **independent of RFC-001**.
3. **OpenHands runtime block** (new, framework-scoped) — what `zil deploy` needs: sandbox type (docker/k8s), image, resource limits, source-control + CI trigger config. **Field names verify against OpenHands' config.**

Backward compatible: existing ADK manifests unaffected.

---

## 9. [RFC-001 optional] OpenHands interceptor adapter

**Skippable if RFC-001 is absent; fence behind a capability check; separate module.**

If RFC-001's `ToolCallInterceptor`/`InterceptorChain` exists, provide `zil/contract/adapters/openhands.py` binding the chain to OpenHands' tool-call interception point.

- **Verify the interception seam first.** OpenHands uses a tool system and an event-stream (action/observation) architecture; the correct before/after-tool hook must be confirmed against the installed version. **If no such hook exists, do not fake one — record it as a blocking open question (§16.1) and ship RFC-002b without this adapter.**
- If a hook exists, implement the same adapter contract RFC-001 defines for ADK: translate per-tool-call events into neutral `before_call`/`after_call` and honor the returned `Decision` (`ALLOW`/`BLOCK`/`REQUIRE_APPROVAL`/`MUTATE`/`REDACT`) using OpenHands' short-circuit / result-substitution mechanism.
- `REQUIRE_APPROVAL` reuses RFC-001's `ApprovalPort`; for autonomous runs the queue-based approval adapter fits (the run pauses pending approval), pairing with source-control/CI flows.

This is the second framework binding that proves RFC-001's neutral core is framework-agnostic — valuable, but optional and independent here.

---

## 10. Evaluation of coding agents (`zil eval`)

For OpenHands coding agents, add **coding-task evals** so a new version can be gated before it touches repositories:
- Eval cases defining a task + repository state + success check (tests pass, PR diff satisfies criteria) — the natural home for **SWE-bench-style** task sets.
- Where a full harness is heavy, support a lightweight subset and a pluggable runner; **integrate existing harnesses, do not vendor a whole benchmark.**
- Prefer execution-based correctness (run tests) over LLM-judge where possible.
- Gate `zil deploy`/promotion on thresholds via the existing eval-gate mechanism.

Closes a compelling loop: an autonomous coding agent must pass a coding benchmark before Zil signs and promotes it.

---

## 11. Packaging, signing, deploy

- **`zil pack`** — bundle the OpenHands agent (manifest, identity, tools/MCP config, eval results incl. coding-task results, SBOM) into a signed `.zil` with the same cosign/SLSA provenance as ADK agents. Framework-tagged via `runtime.framework`; no format change.
- **`zil push`** — unchanged (OCI).
- **`zil deploy`** — deploy into a user-controlled OpenHands runtime (Docker/K8s) using `deploy_descriptor` (§6), wiring env vars, observability, and source-control/CI triggers. Zil orchestrates deployment into OpenHands' runtime; it does not replace it.

---

## 12. File / module layout (suggested)

```
zil/
  frameworks/
    openhands/
      __init__.py
      backend.py               # OpenHandsBackend (ONLY OpenHands SDK import site); self-registers
      scaffold/                # zil init template files for the openhands preset
  contract/
    adapters/
      openhands.py             # [RFC-001 optional] interceptor binding
  ...
tests/
  frameworks/
    test_openhands_wire.py
    test_openhands_scaffold.py
    test_openhands_eval.py
    test_openhands_deploy.py
```

---

## 13. Acceptance criteria (write these as tests)

1. **Registration/dispatch:** with RFC-002a present, `runtime.framework: openhands` resolves to `OpenHandsBackend` via the registry; `adk` still resolves to `AdkBackend`; no `create_agent` branching added.
2. **Wiring:** `OpenHandsBackend.wire(spec)` produces a runnable OpenHands agent with model, instructions, tools, and MCP servers correctly mapped (assert against verified OpenHands SDK config shape).
3. **Scaffold:** `zil init --framework openhands my-agent` produces a project that `zil validate` passes and `zil run` executes on a trivial task.
4. **Validate:** `zil validate` enforces OpenHands-specific required fields and accepts/validates `contract` blocks regardless of RFC-001 presence.
5. **Eval:** a coding-task eval case runs against a sample repo and gates promotion on a threshold.
6. **Pack/deploy:** `zil pack` yields a signed, framework-tagged `.zil`; `deploy_descriptor` emits a valid OpenHands runtime descriptor.
7. **No-runtime-reinvention:** deploy delegates to the OpenHands runtime (assert the descriptor targets OpenHands' sandbox, not a Zil-owned runtime).
8. **[RFC-001 optional]** the OpenHands interceptor adapter binds the neutral chain to OpenHands' tool hook and a destructive/sensitive→egress scenario is gated. **Criteria 1–7 must pass with this skipped when RFC-001 is absent.**
9. **[RFC-003 optional]** a memory provider attaches to the OpenHands agent. **Criteria 1–7 must pass with this skipped when RFC-003 is absent.**

---

## 14. Phased implementation plan (build order)

**Phase 0 — verification spike (do first, timebox).** Confirm against the installed OpenHands version: the SDK entry point for constructing/wiring an agent; how tools and MCP servers are configured; the local run entry point; the runtime/deploy model (Docker/K8s); the telemetry integration path; **whether a before/after-tool interception hook exists** (for §9); and (if RFC-003 present) the memory interface. Output a findings note pinning exact APIs. **Do not proceed on assumptions.**

**Phase 1 — backend + minimal wiring.** `OpenHandsBackend.wire` + `run_local` for a trivial agent; self-registration into the RFC-002a registry. Criteria 1, 2, 3 (run).

**Phase 2 — manifest, scaffold, validate.** `runtime.framework: openhands` validation, OpenHands runtime block, `zil init` preset (§7) incl. scaffolded `contract` annotations, validate rules. Criteria 3 (validate), 4.

**Phase 3 — eval + pack + deploy.** Coding-task eval support (§10), framework-tagged signed `.zil`, `zil deploy` via `deploy_descriptor` (§11). Criteria 5, 6, 7.

**Phase 4 — [optional integrations].** RFC-001 OpenHands interceptor (§9); RFC-003 memory attachment. Criteria 8, 9. Both skippable.

---

## 15. Open questions (Phase 0 answers most)

1. **Tool interception hook (blocking for §9 only).** Does the installed OpenHands expose a before/after-tool-call interception point usable for RFC-001? If not, §9 defers; Phases 1–3 proceed.
2. **`zil run` semantics for an autonomous agent.** Single-task headless run vs. interactive session — which does `run_local` default to, and how is a task specified?
3. **Deploy target shape.** Long-running service, CI-triggered job, or registered agent in OpenHands Cloud? Likely more than one; pick the primary for v1.
4. **Coding-eval harness boundary.** How much SWE-bench-style harness to integrate vs. reference. Keep Zil thin.
5. **Overlap management (the governance seam).** Where Zil governance stops and OpenHands' native access control / audit begins. Document so the two are complementary, not redundant (§2).
6. **Telemetry path.** Reuse the agent's OTel config through OpenHands' tracing, or attach an exporter? Verify; do not double-emit.

---

## 16. Definition of done (core RFC-002b, excluding optional §9/§3)

- `OpenHandsBackend` merged and self-registering into the RFC-002a registry; `runtime.framework: openhands` works end to end: `init` → `validate` → `run` → `eval` → `pack` → `deploy`.
- An OpenHands autonomous coding agent can be scaffolded, validated, eval-gated on a coding task, packed into a signed `.zil`, and deployed into a user-controlled OpenHands runtime.
- Acceptance criteria 1–7 pass in CI; criteria 8–9 cleanly skipped when RFC-001/003 absent.
- Docs page under `getzil.dev/docs` for the OpenHands preset, the `runtime.framework` option, and an explicit statement of the Zil/OpenHands governance seam (§2, §15.5).
- No Zil-owned runtime introduced (principle 3 upheld; criterion 7).

---

## 17. References (verify against installed versions)

- **ZIL-RFC-002a** — Framework Backend Abstraction (HARD PREREQUISITE: interface, registry, `AgentSpec`, ADK refactor).
- OpenHands — platform docs, SDK, CLI, runtime/sandbox model, MCP support, source-control/CI integrations. **Upstream source of truth; pin versions.**
- ZIL-RFC-001 — Tool Contract Enforcement (optional interceptor binding).
- ZIL-RFC-003 — Memory Layer (optional memory attachment).
- MCP — tool protocol shared by both frameworks.
- DeepEval — eval metrics; SWE-bench-style harnesses for §10.
- OpenTelemetry — telemetry path.
- Zil docs — manifest schema, `create_agent`, `zil init/validate/eval/pack/deploy`, `.zil` archive, cosign/SLSA provenance.
