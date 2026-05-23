# ZIL-RFC-002 — OpenHands Framework Support

| Field | Value |
|---|---|
| **Status** | Draft / Backlog |
| **Target component** | `zil-ai` Python SDK (`create_agent`, framework adapters), `zil init` (scaffold), manifest schema, `zil deploy` (runtime integration) |
| **Owner** | FluentData / Zil maintainers |
| **Zil version target** | post-v0.1 |
| **License** | Apache 2.0 |
| **Related** | ZIL-RFC-001 (Tool Contract Enforcement). **Complementary, not a prerequisite — see §3.** |
| **Document purpose** | Implementation spec intended to be handed to an LLM coding agent. Be pragmatic. Prefer the smallest correct increment. |

---

## 0. How to read this document

This spec is written so an implementer (human or LLM) with **no prior knowledge of Zil or OpenHands** can build the feature. Section 1 orients on Zil. Section 2 orients on OpenHands and states the "why." Section 3 explains the relationship to RFC-001. Sections 4–12 are the design and requirements. Section 13 is acceptance criteria. Section 14 is the phased build plan — **start there if you want to know what to write first.**

When this document and the live Zil codebase disagree, the codebase wins; flag the discrepancy. **OpenHands is an external, fast-moving platform: every API, SDK entry point, runtime behavior, and configuration field referenced here MUST be verified against the version pinned in the project before relying on it.** Where this document says "verify," treat it as a hard gate, not a suggestion. Do not confabulate OpenHands APIs — if you cannot confirm a hook or entry point exists, stop and surface it as an open question.

---

## 1. Primer: what Zil is

Zil is an open-source CLI and Python SDK for **validating, packaging, and deploying production AI agents**. It does not reinvent agent orchestration, tool protocols, evaluation, or telemetry — it **composes** with existing standards: Google ADK (the currently supported agent framework), MCP (tool protocol), DeepEval (evals), and OpenTelemetry (tracing).

Core mental model:

- **The manifest is the contract.** A declarative `manifest.yaml` describes an agent's runtime, identity, tools, evals, and observability.
- **The CLI is a thin wrapper** over that manifest: `init`, `validate`, `audit`, `eval`, `pack`, `push`, `deploy`, etc.
- **`zil pack`** produces a signed, portable `.zil` archive (manifest + agent code + tools + SBOM + eval results + cosign signature + SLSA provenance).
- **The SDK** exposes `zil.create_agent(...)`, which reads the manifest and identity files and returns a **fully wired agent**. Today it returns a wired **ADK** agent. **This RFC adds OpenHands as a second, selectable framework that `create_agent` can wire.**

Four guiding principles that constrain this feature:

1. **Built on what exists** — compose with ADK/MCP/DeepEval/OTel and (per this RFC) OpenHands; do not invent new protocols or runtimes.
2. **Declarative-first** — the manifest is the contract; code reads it.
3. **No new runtime** — agents run on infra the user already has.
4. **No new registry** — use OCI registries the user already has.

> **The current state this RFC changes:** Zil currently assumes a single framework (ADK) in `create_agent` and in the manifest's `runtime.framework` field. This RFC generalizes that into a **framework-backend abstraction** with ADK and OpenHands as two implementations.

---

## 2. Primer + problem statement: OpenHands and the "why"

**What OpenHands is (verify against installed version).** OpenHands is an open-source, model-agnostic platform for **autonomous cloud coding agents** — agents that plan, write, and apply changes across a codebase end-to-end, rather than suggesting snippets interactively. Key properties relevant to this RFC:

- It is **autonomous and headless-capable**: agents are triggered from GitHub/GitLab/Slack/CI or via API/SDK, and run tasks (fix vulnerabilities, review PRs, migrate code, triage incidents) to completion, including in parallel at scale.
- It ships an **SDK** for embedding agents into apps and workflows, a **CLI**, and a hosted cloud option.
- It runs agents inside a **secure, sandboxed runtime the user controls** — isolated Docker or Kubernetes environments, self-hosted or private cloud — with its own access control and execution auditability.
- It is **model-agnostic** and integrates with CI/CD and source-control systems natively.

**Why this belongs in Zil.** An autonomous coding agent is a *deployed artifact that acts on production code with little human-in-the-loop* — which is precisely the class of agent Zil exists to make shippable. The pains Zil already targets ("no manifest, no eval gate, no signed artifact, no audit; works in a demo, breaks in prod") are most acute here: an autonomous agent opening PRs against real repositories needs identity, provenance, guardrails, eval-gating, and contract-level tool safety. Supporting OpenHands lets Zil produce **governed, identifiable, eval-gated, contract-enforced autonomous coding agents** as portable signed artifacts — a sharp, differentiated capability.

**What OpenHands already provides (so Zil does NOT reinvent it).** OpenHands already gives you sandbox isolation, runtime access control, and execution-level auditability. **Do not duplicate these.** Zil's additive value on top of OpenHands is specifically:

1. A **declarative manifest** as the single, version-controlled source of truth for the agent's identity, tools, model, and policy.
2. A **signed, portable `.zil` artifact** with SLSA/cosign provenance answering "*which exact agent configuration acted*" — supply-chain provenance of the agent itself, distinct from a runtime audit log.
3. **Eval-gated promotion** — block a new agent version on quality thresholds (including coding-benchmark suites) before it is allowed to run against repos.
4. **Per-tool contract enforcement** (via RFC-001) at finer granularity than a coarse sandbox boundary.
5. **One governance model across frameworks** — an ADK agent and an OpenHands agent are declared, audited, packaged, and signed identically.

Position OpenHands support as **complementary to** OpenHands' native runtime security, not competing with it.

---

## 3. Relationship to ZIL-RFC-001 (read carefully)

RFC-001 specifies a **framework-neutral tool-contract enforcement layer** (a `ToolCallInterceptor` core plus per-framework adapters, starting with ADK). RFC-002 (this document) specifies **adding OpenHands as a framework backend**.

These are **complementary and independently shippable**. Neither is a prerequisite for the other, and **this RFC does not assume RFC-001 is implemented first.** Specifically:

- **If RFC-001 is not yet built:** RFC-002 is fully deliverable on its own. The OpenHands backend wires and runs OpenHands agents through Zil, scaffolds them, packages them, and deploys them. Contract enforcement simply is not present yet — same situation as ADK agents without RFC-001.
- **If RFC-001 is built first or concurrently:** RFC-002 should additionally provide an **OpenHands adapter for RFC-001's interceptor** (binding the neutral `ToolCallInterceptor` to OpenHands' tool/event interception point — see §9). This is called out below as an **optional, clearly-fenced integration**, gated behind a check for RFC-001's presence.
- **Sequencing is the maintainers' choice.** This RFC is written so the OpenHands backend lands cleanly regardless of order. Every reference to RFC-001 in the requirements below is marked **[RFC-001 integration — optional]** and must be skippable without breaking the core deliverable.

Design implication: keep the OpenHands **framework adapter** (wiring/running agents) and the OpenHands **interceptor adapter** (RFC-001 binding) in **separate modules**, so the latter can be absent or added later without touching the former.

---

## 4. Goals and non-goals

### Goals
1. Add `openhands` as a selectable value of the manifest's `runtime.framework`, alongside `adk`.
2. Generalize `zil.create_agent(...)` behind a **framework-backend interface** so it can wire and return either an ADK agent or an OpenHands agent from the same manifest/identity inputs.
3. Scaffold OpenHands agent projects via `zil init` (a new framework preset).
4. Map Zil's declarative concepts (identity/persona/instructions, tools, MCP servers, model adapter, observability) onto OpenHands' SDK configuration.
5. Package an OpenHands agent as a `.zil` archive and run/deploy it (`zil run`, `zil deploy`) into an OpenHands runtime the user controls.
6. Make `zil eval` able to gate OpenHands coding agents, including coding-benchmark-style suites (e.g. SWE-bench-style task sets) where feasible.
7. **[RFC-001 integration — optional]** Provide an OpenHands adapter that binds RFC-001's `ToolCallInterceptor` to OpenHands' tool/event interception point.

### Non-goals (explicitly out of scope)
- **Not** reimplementing OpenHands' sandbox, runtime isolation, or execution access control — those are OpenHands' and Zil composes with them (§2).
- **Not** supporting *interactive pair-programmer* coding tools (e.g. terminal TUIs driven turn-by-turn). This RFC targets **autonomous/headless** coding agents, which match Zil's ship lifecycle. Interactive tools are a different philosophy and out of scope.
- **Not** building a Zil-specific agent runtime (principle 3). The OpenHands runtime runs on the user's own Docker/K8s/cloud; Zil delegates to it.
- **Not** a third framework. ADK and OpenHands only; the abstraction should *allow* more later but this RFC ships exactly one new backend.
- **Not** RFC-001 itself. Contract-enforcement *logic* is RFC-001's scope; this RFC only optionally provides the OpenHands *binding* for it.

---

## 5. Architecture overview

Introduce a **framework-backend abstraction** that `create_agent` dispatches to based on `runtime.framework`:

```
                         zil.create_agent(manifest, identity, tools, ...)
                                          │
                                          │ reads runtime.framework
                          ┌───────────────┴────────────────┐
                          ▼                                 ▼
                 FrameworkBackend (ADK)          FrameworkBackend (OpenHands)   ← NEW
                 wires an ADK agent              wires an OpenHands agent
                 (existing behavior)             via the OpenHands SDK
                          │                                 │
                          ▼                                 ▼
                 runs on user infra              runs in OpenHands sandboxed
                 (Cloud Run, etc.)               runtime (Docker/K8s, user-controlled)

   [RFC-001 integration — optional, separate module]
        ToolCallInterceptor (neutral, from RFC-001)
                          │
                          ▼
        OpenHands interceptor adapter  ──binds to──▶  OpenHands tool/event hook (VERIFY §9)
```

Hard rules:
- The **framework-backend interface** must be the only thing `create_agent` knows about; it must not contain framework-specific branches inline. Refactor the existing ADK path into an `AdkBackend` implementing the same interface (this is a prerequisite refactor — §6).
- The OpenHands backend is the **only module allowed to import the OpenHands SDK.**
- The optional RFC-001 interceptor binding lives in a **separate module** from the backend (§3).

---

## 6. Prerequisite refactor: extract a FrameworkBackend interface

Before adding OpenHands, factor the current ADK-specific wiring out of `create_agent` into an interface. This is a small, mechanical, behavior-preserving change and is **in scope for this RFC**.

```python
from typing import Protocol, Any
from dataclasses import dataclass


@dataclass
class AgentSpec:
    """Framework-neutral, parsed from manifest + identity files."""
    name: str
    version: str
    instructions: str            # composed from identity/persona.md + instructions.md
    model: dict                  # from adapters/llm.yaml (provider, model, params)
    tools: list[Any]             # python tool callables + resolved MCP tools
    mcp_servers: list[dict]      # MCP server configs from manifest
    observability: dict          # OTel config
    raw_manifest: dict


class WiredAgent(Protocol):
    """Opaque handle the rest of Zil treats uniformly (run/deploy/pack inspect it minimally)."""
    @property
    def framework(self) -> str: ...


class FrameworkBackend(Protocol):
    name: str  # "adk" | "openhands"

    def wire(self, spec: AgentSpec) -> WiredAgent:
        """Build and return a runnable agent for this framework."""
        ...

    def run_local(self, agent: WiredAgent, **kwargs) -> None:
        """Back `zil run` for this framework."""
        ...

    def deploy_descriptor(self, agent: WiredAgent, spec: AgentSpec) -> dict:
        """Return framework-specific deploy metadata `zil deploy` needs
        (e.g. runtime image, entrypoint, sandbox requirements)."""
        ...
```

`create_agent` becomes: parse → build `AgentSpec` → select backend by `runtime.framework` → `backend.wire(spec)`. The existing ADK logic moves into `AdkBackend` unchanged. Add a backend registry keyed by name.

**Acceptance for the refactor:** existing ADK agents behave identically (criterion 1, §13).

---

## 7. The OpenHands backend

Implement `OpenHandsBackend(FrameworkBackend)` in `zil/frameworks/openhands/backend.py` (only module importing the OpenHands SDK).

Responsibilities (each must be mapped to a **verified** OpenHands SDK entry point — do not assume names):

1. **`wire(spec)`** — construct an OpenHands agent from `AgentSpec`:
   - Map `spec.instructions` → OpenHands agent system/instruction configuration.
   - Map `spec.model` → OpenHands model configuration (it is model-agnostic; map provider/model/params).
   - Map `spec.tools` and `spec.mcp_servers` → OpenHands' tool system / MCP configuration. **OpenHands supports MCP (verify), so prefer wiring MCP servers natively rather than re-implementing tools.**
   - Map `spec.observability` → OpenHands tracing/telemetry config or attach an OTel exporter (verify integration path; do not create a parallel exporter — reuse the agent's OTel config).
   - Return a `WiredAgent` whose `framework == "openhands"`.
2. **`run_local(agent)`** — back `zil run` by invoking the agent through the OpenHands SDK/CLI for a single task or interactive session (verify the SDK's local-execution entry point).
3. **`deploy_descriptor(agent, spec)`** — emit what `zil deploy` needs to stand the agent up in an OpenHands runtime: the sandbox/runtime requirements (Docker/K8s), entrypoint, env vars, source-control/CI trigger wiring. **The OpenHands runtime is the deploy target; Zil does not introduce its own.**

**Capability boundary:** the backend translates declarative config → OpenHands SDK calls. It must not embed coding-agent *behavior* (that's OpenHands'); it only configures and wires.

---

## 8. `zil init` — OpenHands scaffold preset

Add an `openhands` framework preset to `zil init` that scaffolds a working autonomous coding-agent project. Suggested generated layout (mirror the existing Zil project layout; differences noted):

```
my-coding-agent/
├── manifest.yaml              # runtime.framework: openhands
├── my_coding_agent/
│   ├── __init__.py
│   └── agent.py               # zil.create_agent(...) → OpenHands agent
├── adapters/
│   └── llm.yaml               # model-agnostic; pick provider/model
├── identity/
│   ├── persona.md             # e.g. "careful autonomous refactoring agent"
│   ├── instructions.md        # task framing, PR etiquette, repo conventions
│   └── guardrails.yaml        # behavioral guardrails (existing Zil concept)
├── tools/                     # custom tools + MCP server declarations
├── evals/
│   ├── baseline.yaml          # include a coding-task suite (see §11)
│   └── cases/
├── observability/
│   └── config.yaml
├── Dockerfile                 # OpenHands runtime image (verify base/image guidance)
└── .github/workflows/         # CI trigger wiring (issue → agent → PR), if applicable
```

The generated `manifest.yaml` should pre-populate **tool contract annotations** for the typical autonomous-coding toolset (these are inert without RFC-001, but make the manifest correct and future-proof — see §10):

```yaml
spec:
  runtime:
    framework: openhands         # NEW selectable value
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

> The `contract:` blocks follow RFC-001's schema. **They are scaffolded regardless of whether RFC-001 is implemented.** Without RFC-001 they are descriptive metadata; with RFC-001 they become enforced. `zil validate` should accept them in both cases; only RFC-001 makes them *do* anything at runtime.

---

## 9. [RFC-001 integration — optional] OpenHands interceptor adapter

**This entire section is skippable if RFC-001 is not present. Fence it behind a capability check; the §7 backend must not depend on it.**

If RFC-001's neutral `ToolCallInterceptor`/`InterceptorChain` exists, provide `zil/contract/adapters/openhands.py` that binds the chain to OpenHands' tool-call interception point.

- **Verify the interception seam first.** OpenHands uses a tool system and an event-stream (action/observation) architecture; the correct hook for "intercept before/after each tool action" must be confirmed against the installed version. **If no before/after-tool interception point exists, do not fake one — record it as a blocking open question (§16) and ship RFC-002 without this adapter.**
- If a hook exists, implement the same adapter contract RFC-001 defines for ADK: translate the framework's per-tool-call event into the neutral `before_call`/`after_call` calls, and honor the returned `Decision` (`ALLOW`/`BLOCK`/`REQUIRE_APPROVAL`/`MUTATE`/`REDACT`) using whatever short-circuit / result-substitution mechanism OpenHands provides.
- `REQUIRE_APPROVAL` servicing reuses RFC-001's `ApprovalPort`; for autonomous OpenHands runs the queue-based approval adapter is the natural fit (the run pauses pending approval), which pairs with source-control/CI trigger flows.

This adapter is the second framework binding that proves RFC-001's neutral core really is framework-agnostic — valuable, but explicitly **optional and independent** here.

---

## 10. Manifest schema changes

1. **`runtime.framework`** accepts `openhands` in addition to `adk`. `zil validate` must validate framework-specific required fields (e.g. OpenHands runtime/sandbox settings, source-control integration config) when `framework: openhands`.
2. **Tool `contract` blocks** (RFC-001 schema) are accepted and schema-validated by `zil validate` **independent of RFC-001**. Without RFC-001 they are descriptive; with it they are enforced. Validation of contradictions (e.g. `read_only` + `destructive`) should still run.
3. **OpenHands runtime block** (new, framework-scoped) — capture what `zil deploy` needs: sandbox type (docker/k8s), image, resource limits, source-control + CI trigger config. **Field names verify against OpenHands' own config.**

Backward compatibility: existing ADK manifests are unaffected; `framework` already exists and defaults remain.

---

## 11. Evaluation of coding agents (`zil eval`)

`zil eval` already runs suites and gates promotions. For OpenHands coding agents, add support for **coding-task evals** so a new agent version can be gated before it touches repositories:

- Allow eval cases that define a task + a repository state + a success check (tests pass, PR diff satisfies criteria). This is the natural place for **SWE-bench-style** task sets.
- Where a full benchmark harness is heavy, support a lightweight subset and a pluggable runner; **do not** vendor an entire benchmark — reference/integrate existing harnesses.
- Reuse DeepEval-style metrics where they apply (e.g. correctness of a produced patch via test execution rather than LLM-judge where possible).
- Gate `zil deploy`/promotion on thresholds, identical to the existing eval-gating mechanism.

This closes a compelling loop: an autonomous coding agent must pass a coding benchmark before Zil will sign and promote it.

---

## 12. Packaging, signing, deploy

- **`zil pack`** — bundle the OpenHands agent (manifest, identity, tools/MCP config, eval results incl. coding-task results, SBOM) into a signed `.zil` with the same cosign/SLSA provenance as ADK agents. The provenance answers "which exact autonomous coding agent config is this." No format change — the artifact is framework-tagged via `runtime.framework`.
- **`zil push`** — unchanged (OCI registry).
- **`zil deploy`** — deploy into an OpenHands runtime the user controls (Docker/K8s, self-hosted or cloud), using `deploy_descriptor` (§7). Wire env vars, observability, and source-control/CI triggers. **Zil orchestrates deployment into OpenHands' runtime; it does not replace that runtime.**

---

## 13. Acceptance criteria (write these as tests)

1. **ADK unaffected (refactor safety):** all existing ADK agent tests pass unchanged after the `FrameworkBackend` extraction (§6).
2. **Framework selection:** a manifest with `runtime.framework: openhands` causes `create_agent` to dispatch to `OpenHandsBackend`; `adk` still dispatches to `AdkBackend`. Unknown framework ⇒ clear validation error.
3. **Wiring:** `OpenHandsBackend.wire(spec)` produces a runnable OpenHands agent from a scaffolded manifest, with model, instructions, tools, and MCP servers correctly mapped (assert against the OpenHands SDK's expected config shape — verified, not assumed).
4. **Scaffold:** `zil init --framework openhands my-agent` produces a project that `zil validate` passes and `zil run` can execute on a trivial task.
5. **Validate:** `zil validate` enforces OpenHands-specific required fields and accepts/validates `contract` blocks regardless of RFC-001 presence.
6. **Eval:** a coding-task eval case runs against a sample repo and gates promotion on a threshold.
7. **Pack/deploy:** `zil pack` yields a signed, framework-tagged `.zil`; `deploy_descriptor` emits a valid OpenHands runtime descriptor.
8. **No-runtime-reinvention:** deploy delegates to the OpenHands runtime (assert the descriptor targets OpenHands' sandbox, not a Zil-owned runtime).
9. **[RFC-001 integration — optional]** *Only runs if RFC-001 is present:* the OpenHands interceptor adapter binds the neutral chain to OpenHands' tool hook and a destructive/sensitive→egress scenario is gated. **The full suite (criteria 1–8) must pass with this criterion skipped when RFC-001 is absent.**

---

## 14. Phased implementation plan (build order)

**Phase 0 — verification spike (do this first, timebox it).** Confirm against the installed OpenHands version: the SDK entry point for constructing/wiring an agent; how tools and MCP servers are configured; the local run entry point; the runtime/deploy model (Docker/K8s); the telemetry integration path; and **whether a before/after-tool interception hook exists** (for §9). Output: a short findings note pinning exact APIs. **Do not proceed to Phase 1 on assumptions.**

**Phase 1 — backend abstraction + minimal OpenHands wiring.** §6 refactor (extract `FrameworkBackend`, move ADK into `AdkBackend`, registry). Implement `OpenHandsBackend.wire` + `run_local` for a trivial agent. Criteria 1, 2, 3 (wiring), 4 (run).

**Phase 2 — manifest, scaffold, validate.** `runtime.framework: openhands`, OpenHands runtime block, `zil init` preset (§8) incl. scaffolded `contract` annotations, `zil validate` rules. Criteria 4 (validate), 5.

**Phase 3 — eval + pack + deploy.** Coding-task eval support (§11), `zil pack` framework-tagged signed artifact, `zil deploy` via `deploy_descriptor` into OpenHands runtime (§12). Criteria 6, 7, 8.

**Phase 4 — [RFC-001 integration — optional].** Only if/when RFC-001 exists: OpenHands interceptor adapter (§9), approval via queue adapter. Criterion 9. Skippable with no impact on Phases 1–3.

---

## 15. File / module layout (suggested)

```
zil/
  agent.py                     # create_agent: parse → AgentSpec → select backend → wire
  frameworks/
    __init__.py                # FrameworkBackend protocol + registry
    base.py                    # AgentSpec, WiredAgent, FrameworkBackend
    adk/
      __init__.py
      backend.py               # AdkBackend (existing ADK logic moved here)
    openhands/
      __init__.py
      backend.py               # OpenHandsBackend (ONLY file importing the OpenHands SDK)
      scaffold/                # zil init template files for the openhands preset
  contract/                    # (RFC-001) — present only if RFC-001 implemented
    adapters/
      openhands.py             # [RFC-001 integration — optional] interceptor binding
  ...
tests/
  frameworks/
    test_backend_registry.py
    test_adk_unchanged.py
    test_openhands_wire.py
    test_openhands_scaffold.py
    test_openhands_eval.py
    test_openhands_deploy.py
```

---

## 16. Open questions (resolve during implementation; Phase 0 should answer most)

1. **Tool interception hook (blocking for §9 only).** Does the installed OpenHands expose a before/after-tool-call interception point usable for RFC-001? If not, §9 is deferred and recorded; Phases 1–3 proceed regardless.
2. **`zil run` semantics for an autonomous agent.** Single-task headless run vs. interactive session — which does `run_local` default to, and how is a task specified?
3. **Deploy target shape.** What exactly does `zil deploy` produce/operate for OpenHands — a long-running service, a CI-triggered job, a registered agent in OpenHands Cloud? Likely supports more than one; pick the primary for v1.
4. **Coding-eval harness boundary.** How much SWE-bench-style harness does Zil integrate vs. reference? Keep Zil thin; integrate existing harnesses.
5. **Overlap management.** Where exactly does Zil governance stop and OpenHands' native access control / audit begin? Document the seam so the two are complementary, not redundant (§2).
6. **Telemetry path.** Reuse the agent's OTel config through OpenHands' tracing, or attach an exporter? Verify and pick one; do not double-emit.

---

## 17. Definition of done (core RFC-002, excluding optional §9)

- `FrameworkBackend` abstraction merged; ADK behavior unchanged (criterion 1).
- `runtime.framework: openhands` supported end to end: `init` → `validate` → `run` → `eval` → `pack` → `deploy`.
- An OpenHands autonomous coding agent can be scaffolded, validated, eval-gated on a coding task, packed into a signed `.zil`, and deployed into a user-controlled OpenHands runtime.
- Acceptance criteria 1–8 pass in CI; criterion 9 is cleanly skipped when RFC-001 is absent.
- Docs page under `getzil.dev/docs` for the OpenHands framework preset, the manifest `runtime.framework` options, and an explicit statement of the Zil/OpenHands governance seam (§2, §16.5).
- No Zil-owned runtime introduced (principle 3 upheld; criterion 8).

---

## 18. References (verify against installed versions)

- OpenHands — platform docs, SDK, CLI, runtime/sandbox model, MCP support, source-control/CI integrations. **Treat as the upstream source of truth; pin versions.**
- ZIL-RFC-001 — Tool Contract Enforcement (neutral `ToolCallInterceptor`, adapters, `ApprovalPort`). Complementary; not assumed implemented.
- Google ADK — existing framework backend (reference for the abstraction).
- MCP — tool protocol shared by both frameworks.
- DeepEval — eval metrics; coding-task / SWE-bench-style harnesses for §11.
- OpenTelemetry — telemetry path.
- Zil docs — manifest schema, `create_agent`, `zil init/validate/eval/pack/deploy`, `.zil` archive, cosign/SLSA provenance.
