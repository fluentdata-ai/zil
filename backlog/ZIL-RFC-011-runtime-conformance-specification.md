# ZIL-RFC-011 — Runtime Conformance Specification

| Field | Value |
|---|---|
| **Status** | Draft / Backlog |
| **Target component** | `zil-ai` runtime contract (new), runtime adapters (new), `zil deploy`, `zil run`; interfaces with `FrameworkBackend` (RFC-002a) |
| **Owner** | FluentData / Zil maintainers |
| **Zil version target** | post-v0.1 |
| **License** | Apache 2.0 |
| **Related** | **Keystone of the portability theme** (gap analysis §4.1) with RFC-002a (framework layer) and RFC-004 (provider layer). **Enables RFC-008** (reliability/long-running — builds on checkpoint/restore). **Consumes** `FrameworkBackend.deploy_descriptor` from RFC-002a. No hard dependency on RFC-001/003. |
| **Document purpose** | Implementation spec intended to be handed to an LLM coding agent. Be pragmatic. Prefer the smallest correct increment. This is an **XL** effort; the contract/adapter split (§3) is what makes it shippable in slices. |

---

## 0. How to read this document

This spec is written so an implementer (human or LLM) with **no prior knowledge of Zil** can build the feature. Section 1 orients on Zil. Section 2 is the "why." **Section 3 is the central structural decision — read it first: this RFC splits into a runtime *contract* and per-platform *adapters*, which are different work in different waves.** Sections 4–11 are design and requirements. Section 12 is acceptance criteria. Section 13 is the build plan.

When this document and the live Zil codebase disagree, the codebase wins; flag the discrepancy. **Cloud platforms (Cloud Run, Modal, ECS/Fargate, Azure Container Apps, k8s) are external and moving: every API, primitive, limit, and pricing/isolation claim referenced here MUST be verified against current docs before relying on it.** Where this document says "verify," treat it as a hard gate. Do not confabulate platform APIs.

> **Scope decision required before Phase 1 (§11.1).** Is this a *published, OCI-style conformance spec* others can implement against (a standards play), or a *pragmatic internal interface* that just decouples Zil from Cloud Run first (a refactor)? The two have very different sizes. This document is written to support **either**, by building the internal interface first and leaving "publish it as a spec" as a later, additive step. Make the call explicitly.

---

## 1. Primer: what Zil is

Zil is an open-source CLI and Python SDK for validating, packaging, and deploying production AI agents. It composes with ADK (and, per RFC-002a/002b, other frameworks), MCP, DeepEval, and OpenTelemetry. The manifest is the contract; `zil pack` produces a signed, portable `.zil` archive; `zil deploy` stands the agent up; the SDK's `create_agent` returns a wired agent.

**The current state this RFC changes:** `zil deploy` is **hardwired to Google Cloud Run** (with ADK). There is no abstraction for "where an agent runs." The framework spec's headline promise — *deploy anywhere: GCP, AWS, Azure, sovereign/self-hosted; no lock-in* — is therefore unmet at the implementation level. The spec's own "package-spec vs runtime-spec (OCI-style)" separation, which is supposed to make portability real, **does not exist in code.**

Four guiding principles:
1. **Built on what exists** — target existing platforms; do not build a Zil cloud.
2. **Declarative-first** — the manifest declares runtime requirements; adapters satisfy them.
3. **No new runtime** — Zil does not host execution; it conforms agents to platforms the user already has. *(This RFC defines the conformance contract that makes "no new runtime" honest across clouds.)*
4. **No new registry** — unchanged.

---

## 2. Problem statement (the "why")

Portability is the spec's central commercial argument: enterprises want to avoid single-provider dependency and have spent heavily on migrations. Today Zil contradicts that argument — it runs agents in exactly one place. Adding AWS/Azure/etc. by branching inside `zil deploy` would reproduce, at the runtime layer, the same hardwiring problem RFC-002a fixed at the framework layer.

The correct move is the same one applied at the other two portability layers: **define an abstract contract, then implement swappable adapters.** RFC-002a made the *framework* swappable; RFC-004 makes *providers* swappable; **RFC-011 makes the *runtime* swappable.** Together they deliver "any framework, any provider, anywhere." RFC-011 is the keystone because cloud portability is the most-cited enterprise requirement and the one Zil currently fails outright.

There is a second payoff: a runtime contract that includes **checkpoint/restore** is the foundation RFC-008 (reliability, crash recovery, long-running agents) builds on. Defining it well here unblocks that whole pillar.

---

## 3. The central split: conformance contract vs. runtime adapters

This RFC is **two separable deliverables.** Conflating them is why it looks like an undifferentiated XL blob; splitting them is what makes it shippable.

**(A) The Runtime Conformance Contract** — the abstract interface every runtime must satisfy: agent lifecycle (load → init → session → turn → checkpoint/restore → teardown), HITL servicing, observability emission, and the requirements the manifest can declare (sandbox needs, resources, networking, state durability). This is design-heavy, platform-agnostic, done **once.**

**(B) Runtime Adapters** — concrete implementations of the contract per platform: Cloud Run, Modal, ECS/Fargate, Azure Container Apps, k8s. Each is its own item, its own effort, its own verification spike. "Support AWS" = the contract **plus** an AWS adapter — not a single ticket.

> **Implication for the roadmap:** the gap analysis lists RFC-011 as one XL row. It should be read as **RFC-011 (the contract) + a set of adapter items.** This document specifies the contract in full and specifies the **first two adapters** (Cloud Run, Modal) concretely; later adapters (AWS/Azure/k8s) are sketched as follow-on items that land on the proven contract.

### 3.1 Seam with RFC-002a (framework backend)

Clean division of responsibility:
- **`FrameworkBackend.deploy_descriptor(agent, spec)` (RFC-002a)** answers **"what does this agent need to run"** — image/entrypoint, sandbox requirement, env, resource hints. Framework-specific, platform-agnostic.
- **`RuntimeAdapter` (this RFC)** answers **"how do I run that on platform X"** — translating the descriptor + the conformance contract into a deployed, running agent on a specific cloud. Platform-specific, framework-agnostic.

`zil deploy` becomes: `descriptor = framework_backend.deploy_descriptor(...)` → `runtime_adapter.deploy(descriptor, contract_requirements)`. Neither side knows the other's internals.

---

## 4. Goals and non-goals

### Goals
1. Define the **Runtime Conformance Contract** (§5): the abstract lifecycle + capability interface a runtime must satisfy, and the manifest `runtime` requirements it can declare.
2. Define the **`RuntimeAdapter`** interface + registry (§6), keyed by target platform.
3. Refactor the existing **Cloud Run** deploy into the first `RuntimeAdapter` — behavior-preserving, the known-good reference (§7.1).
4. Implement a **Modal** adapter as the second target (§7.2) — chosen deliberately as the neutrality proof (§8) and a differentiated capability for agentic/sandboxed workloads.
5. Sketch **AWS / Azure / k8s** adapters as follow-on items landing on the proven contract (§7.3).
6. Add a **conformance test kit** any adapter must pass (§9), so "conformant" is verifiable, not asserted.
7. Route `zil deploy`/`zil run` through the adapter registry (§10).

### Non-goals
- **Building a Zil-hosted runtime / control plane.** Adapters target the user's platforms (principle 3).
- **Reliability mechanisms** (crash recovery, resumable execution, durable long-horizon state) — RFC-011 defines the **checkpoint/restore *interface*** the contract exposes; the *mechanisms and policies* that use it are **RFC-008.**
- **Framework wiring** (RFC-002a) and **provider adapters** (RFC-004) — sibling RFCs, not this one.
- **Every platform at once.** Contract + Cloud Run + Modal here; AWS/Azure/k8s follow on the proven contract.
- **A published external standard, in v1.** Build the internal contract first; publishing it OCI-style is an explicit later step gated on the §11.1 decision.

---

## 5. The Runtime Conformance Contract

Define a platform-agnostic contract with three parts: the **agent lifecycle interface**, the **capability requirements** the manifest can declare, and the **observability/HITL obligations**. Reference signatures; adjust to house style but preserve semantics.

### 5.1 Lifecycle interface

```python
from typing import Protocol, Any, Optional
from dataclasses import dataclass, field


@dataclass
class RuntimeRequirements:
    """Declared in manifest `runtime`; what the agent needs from any runtime."""
    sandbox: Optional[str] = None        # None | "container" | "isolated" (untrusted-code isolation)
    cpu: Optional[str] = None
    memory: Optional[str] = None
    gpu: Optional[str] = None            # e.g. "A100" — many platforms can't satisfy; adapter must error clearly
    networking: dict = field(default_factory=dict)   # egress rules, ingress, ports
    state_durability: str = "ephemeral"  # "ephemeral" | "session" | "durable" (needs checkpoint support)
    concurrency: Optional[int] = None
    timeout_s: Optional[int] = None      # long-running agents need high/no timeout — key portability differentiator


@dataclass
class DeployDescriptor:
    """Produced by FrameworkBackend.deploy_descriptor (RFC-002a). What to run."""
    image: Optional[str]
    entrypoint: list[str]
    env: dict
    framework: str
    requirements: RuntimeRequirements


@dataclass
class Checkpoint:
    """Opaque, adapter-serializable agent execution state. RFC-008 builds policy on this."""
    session_id: str
    blob: bytes
    metadata: dict = field(default_factory=dict)


class ConformantRuntime(Protocol):
    """The lifecycle every runtime adapter must implement."""
    def load(self, descriptor: DeployDescriptor) -> None: ...          # provision/prepare
    def start_session(self, session_id: str, ctx: dict) -> None: ...
    def run_turn(self, session_id: str, input: Any) -> Any: ...        # one agent turn
    def checkpoint(self, session_id: str) -> Optional[Checkpoint]: ... # None if unsupported (capability-reported)
    def restore(self, checkpoint: Checkpoint) -> None: ...
    def end_session(self, session_id: str) -> None: ...
    def teardown(self) -> None: ...
```

> **Checkpoint/restore is the seam for RFC-008.** Adapters that can't support durable state report it (so `state_durability: durable` against a non-supporting adapter is a clear validation error, not a silent failure). RFC-011 defines the interface; RFC-008 defines recovery/resume policy.

### 5.2 RuntimeAdapter (deploy-side) interface

```python
class RuntimeAdapter(Protocol):
    name: str  # "cloudrun" | "modal" | "ecs" | "aca" | "k8s"

    def supports(self, req: RuntimeRequirements) -> list[str]:
        """Return a list of unmet requirements ([] = fully supported).
        e.g. a GPU or durable-state requirement an adapter can't meet."""
        ...

    def deploy(self, descriptor: DeployDescriptor) -> dict:
        """Provision and launch on this platform; return a deploy handle/record."""
        ...

    def status(self, handle: dict) -> dict: ...
    def teardown(self, handle: dict) -> None: ...
```

### 5.3 Manifest `runtime` additions

```yaml
spec:
  runtime:
    framework: adk            # (RFC-002a — what wires the agent)
    target: cloudrun          # NEW — which RuntimeAdapter deploys it: cloudrun | modal | ecs | aca | k8s
    requirements:             # NEW — RuntimeRequirements (declarative, adapter-checked)
      sandbox: isolated       # e.g. autonomous coding agents executing untrusted code
      state_durability: durable
      timeout_s: 0            # 0 = long-running / no hard timeout
      gpu: null
      concurrency: 100
```

`zil validate` must: confirm `target` is a registered adapter; call `adapter.supports(requirements)` and **fail with the explicit unmet-requirement list** if non-empty (e.g. "target `cloudrun` cannot satisfy `state_durability: durable`"); and validate framework×target combinations the framework backend declares unsupported.

---

## 6. Adapter registry

Mirror RFC-002a's backend registry: a `RuntimeRegistry` mapping `runtime.target` → `RuntimeAdapter`, adapters self-register, unknown target → clear error listing registered adapters. The neutral contract + registry import no platform SDKs; each adapter is the **only** module importing its platform SDK.

---

## 7. The adapters

### 7.1 Cloud Run — the reference adapter (refactor, do first)
Move the existing `zil deploy` Cloud Run logic into `CloudRunAdapter(RuntimeAdapter)` behavior-preservingly. This is the **known-good reference**: building the contract against an existing working target means the abstraction is a refactor with a checkable result (criterion 1), not a greenfield guess. Cloud Run characteristics to encode in `supports()`: request-timeout ceilings (long-running limits), no native durable agent state (so `state_durability: durable` → unmet unless paired with external state), container sandbox. **Verify current Cloud Run limits.**

### 7.2 Modal — the second adapter (neutrality proof + differentiation)
Implement `ModalAdapter(RuntimeAdapter)`. Chosen deliberately (rationale §8). Modal is a serverless, code-defined compute platform whose primitives map unusually well onto agentic workloads — particularly **sandboxed execution of agent-generated code**, which is the RFC-002b autonomous-coding-agent case. Capability notes to verify in Phase 0 (these come from Modal's own materials — treat as directional, confirm against current docs):
- gVisor-isolated **Sandboxes** for running untrusted/agent-generated code (maps to `sandbox: isolated`).
- Fast cold starts via memory/filesystem snapshotting; high concurrency (claimed 50k+ sessions) — fits bursty agent traffic.
- On-demand GPU (relevant if agents do local inference/fine-tuning).
- **Snapshotting primitives** (memory/filesystem/directory) — candidate substrate for the contract's `checkpoint`/`restore` (verify whether they can serialize the agent's execution state, not just container state).
- Enterprise posture is stronger than typical neoclouds: **SOC 2 Type II**, HIPAA-capable via BAA on enterprise plans — softens the "neoclouds aren't enterprise-ready" objection (verify current status).
- Code-first SDK (Python/TS/Go), no YAML — the Modal adapter defines compute in code, which is a different deploy model from Cloud Run's container-push and is exactly why it stress-tests the contract (§8).

### 7.3 AWS / Azure / k8s — follow-on adapters (sketch only)
Land on the **proven** contract after Cloud Run + Modal. Each is its own item with its own Phase-0 spike:
- **`EcsAdapter` (AWS ECS/Fargate)** — the primary AWS enterprise target; container-task model close to Cloud Run.
- **`AcaAdapter` (Azure Container Apps)** — the primary Azure enterprise target.
- **`K8sAdapter`** — self-hosted / sovereign / on-prem; the compliance-and-residency story the spec leans on. Arguably the highest enterprise value after the hyperscalers because it covers "deploy in our own cluster."

Sequence among these by customer demand; the contract makes them additive.

---

## 8. Why Modal is the *second* adapter (and not first, and not skipped)

Recorded so the sequencing isn't second-guessed:

- **Not first.** The first adapter must be the existing Cloud Run target, so the contract is validated as a refactor against known-good behavior rather than designed in the abstract.
- **Second, deliberately.** The second adapter's job is to prove the contract is genuinely platform-neutral and not secretly Cloud-Run-shaped. The best neutrality test is the adapter **most architecturally different** from the reference. Modal (code-defined serverless + gVisor sandboxes + snapshot-based state) is far more different from Cloud Run than ECS/Fargate is (ECS is Cloud-Run-like enough that it might pass while the contract is still leaky). So Modal does double duty: it **hardens the contract** before the enterprise adapters that must be rock-solid, **and** it delivers a differentiated capability (best-in-class sandboxed execution for autonomous coding agents — the RFC-002b synergy).
- **Why not over the hyperscalers.** Leading with a neocloud would cut against the very reason the contract exists: enterprises are mostly on AWS/Azure/GCP, and the compliance/residency/procurement story is more mature there. Modal-second captures the neocloud upside *without* sacrificing the enterprise-portability rationale, because the neocloud work directly de-risks the hyperscaler adapters that follow.

Net sequencing: **contract (Cloud Run reference) → Modal (neutrality proof + differentiation) → AWS/Azure/k8s (enterprise breadth, on a battle-tested contract).**

---

## 9. Conformance test kit

"Conformant" must be testable. Provide a shared `tests/runtime/conformance/` suite parametrized over adapters: full lifecycle (load→session→turn→teardown); checkpoint/restore round-trip **where the adapter reports support**, and a clean "unsupported" signal where it doesn't; `supports()` correctly reporting unmet requirements (GPU, durable state, long timeout); HITL servicing; observability emission. A new adapter is "done" when it passes the kit. This is what turns the spec from prose into an enforceable contract.

---

## 10. CLI wiring

- `zil deploy`: `descriptor = framework_backend.deploy_descriptor(agent, spec)` → `adapter = runtime_registry.get(runtime.target)` → `adapter.supports(req)` (fail clearly if unmet) → `adapter.deploy(descriptor)`.
- `zil run`: may use a local/dev adapter or the targeted adapter's local mode where available.
- `zil validate`: target registered + requirements satisfiable + framework×target allowed.
- **Backward compatibility:** absent `runtime.target` defaults to `cloudrun`, so existing manifests deploy exactly as today.

---

## 11. Phased implementation plan

### 11.1 Scope decision (do before Phase 1)
Decide: **published OCI-style conformance spec** (standards play — others implement adapters) vs **pragmatic internal interface** (decouple Zil from Cloud Run first). Recommendation: build the internal contract now; treat publishing as a later additive milestone once 2+ adapters prove it. Don't pay the standards-authoring cost before the contract has survived a second adapter.

### 11.2 Phases
**Phase 0 — verification spikes (timebox).** Cloud Run current limits (timeout, state); **Modal** primitives (Sandboxes, snapshot→checkpoint feasibility, concurrency, GPU, SOC2/HIPAA status, SDK deploy model). Output a findings note pinning APIs. **Do not design `checkpoint`/`restore` against assumed Modal snapshot semantics — confirm them.**

**Phase 1 — contract + registry + Cloud Run reference.** `RuntimeRequirements`/`DeployDescriptor`/`Checkpoint`/`ConformantRuntime`/`RuntimeAdapter`, `RuntimeRegistry`, manifest `runtime.target`/`requirements`, `zil validate` checks, refactor Cloud Run into `CloudRunAdapter`, seam with RFC-002a's `deploy_descriptor`. Conformance kit v1. Criteria 1, 2, 3, 6.

**Phase 2 — Modal adapter (neutrality proof).** `ModalAdapter` passing the conformance kit; checkpoint/restore via Modal snapshots **if Phase 0 confirms feasibility** (else report unsupported). Harden the contract based on what Modal exposes that Cloud Run didn't. Criteria 4, 5, 7.

**Phase 3 — follow-on adapters (as demanded).** ECS/Fargate, Azure Container Apps, k8s — each a spike + adapter + kit pass. Criterion 8 (per adapter).

**Phase 4 — [optional] publish the spec.** Only if §11.1 chose the standards play: document the contract as an external conformance spec with the kit as the compliance suite.

---

## 12. Acceptance criteria (write these as tests)

1. **Cloud Run unaffected (refactor safety):** existing deploys behave identically after extraction into `CloudRunAdapter`; absent `runtime.target` defaults to `cloudrun`.
2. **Contract neutrality:** contract + registry + a stub adapter pass with no platform SDK installed.
3. **Dispatch/validation:** `runtime.target` resolves to the right adapter; unknown target → clear error; unmet requirement (e.g. `state_durability: durable` on an adapter that can't) → explicit validation failure naming the unmet item.
4. **Modal deploy:** a Zil agent deploys and runs on Modal via `ModalAdapter` (assert against verified Modal SDK behavior).
5. **Neutrality proof:** the same agent manifest (changing only `runtime.target`) deploys to both Cloud Run and Modal and passes the conformance kit on both.
6. **Conformance kit:** the kit runs against an adapter and gives pass/fail per lifecycle obligation; checkpoint/restore round-trips where supported and signals cleanly where not.
7. **Seam with RFC-002a:** `zil deploy` consumes `FrameworkBackend.deploy_descriptor` output and the runtime adapter consumes it without either side knowing the other's internals.
8. **Follow-on adapter (per platform, when built):** ECS/ACA/k8s adapter passes the conformance kit.
9. **No Zil runtime:** assert deploys target the user's platform; no Zil-hosted execution introduced.

---

## 13. Definition of done (contract + Cloud Run + Modal)

- Runtime conformance contract + `RuntimeAdapter` interface + registry merged; neutral core tests pass with no platform SDK.
- Cloud Run logic relocated into `CloudRunAdapter`; existing deploys identical (criterion 1).
- `ModalAdapter` deploys/runs a real agent and passes the conformance kit; the same manifest deploys to both Cloud Run and Modal by changing only `runtime.target` (criterion 5).
- `zil validate`/`deploy`/`run` route through the registry; requirement-satisfiability checked with explicit errors.
- Conformance kit exists and gates adapter "done."
- Checkpoint/restore interface defined (whether or not Modal implements it), ready for RFC-008.
- §11.1 scope decision recorded.
- Docs page under `getzil.dev/docs`: `runtime.target`/`requirements`, the contract, supported platforms, and the Cloud Run / Modal guides; explicit note that AWS/Azure/k8s are follow-on adapters on the same contract.

---

## 14. File / module layout (suggested)

```
zil/
  runtime/
    __init__.py
    contract.py          # RuntimeRequirements, DeployDescriptor, Checkpoint, ConformantRuntime, RuntimeAdapter
    registry.py          # RuntimeRegistry (target → adapter)
    adapters/
      __init__.py
      cloudrun.py        # CloudRunAdapter (existing logic moved; ONLY GCP-deploy import site)
      modal.py           # ModalAdapter (ONLY Modal SDK import site)
      stub.py            # test-only
      # ecs.py / aca.py / k8s.py  → follow-on (§7.3)
  ...
tests/
  runtime/
    conformance/         # parametrized kit every adapter must pass
    test_contract_neutral.py
    test_cloudrun_unchanged.py
    test_modal_adapter.py
    test_validation_requirements.py
```

---

## 15. Open questions (Phase 0 / scope decision answer most)

1. **Published spec vs internal interface** (§11.1) — the big one; answer before Phase 1.
2. **Checkpoint granularity** — can Modal snapshots (or any adapter) serialize *agent execution state* meaningfully, or only container/process state? Determines how much of RFC-008 is achievable per platform.
3. **`zil run` local story** — a dedicated local dev adapter, or each adapter's local mode? Pick one.
4. **Framework×target matrix** — which combinations are unsupported (e.g. does an OpenHands agent require a sandbox-capable target, ruling out some adapters)? Have framework backends declare constraints the validator enforces.
5. **State externalization** — for adapters without native durable state (Cloud Run), is "durable" satisfiable via an external store the adapter wires (e.g. the RFC-003 memory/state backend), or simply reported unsupported? Decide the boundary with RFC-008/003.
6. **Modal claims** — confirm cold-start/snapshot/concurrency/compliance specifics against current Modal docs before encoding them in `supports()` or checkpoint design.

---

## 16. References (verify against current docs/versions)

- **ZIL-RFC-002a** — Framework Backend Abstraction (`deploy_descriptor` seam, §3.1).
- **ZIL-RFC-008** — Reliability & Long-Running Execution (consumes checkpoint/restore; recovery policy).
- ZIL-RFC-004 — Provider adapters (sibling portability layer); ZIL-RFC-003 — memory/state (state-externalization boundary, §15.5).
- Google Cloud Run — current request/timeout limits, container model, state characteristics.
- Modal — Sandboxes (gVisor isolation), cold-start/snapshot primitives, concurrency, GPU, SDK deploy model, SOC 2 / HIPAA status. **Vendor materials are directional; verify.**
- AWS ECS/Fargate, Azure Container Apps, Kubernetes — follow-on adapter targets.
- OpenTelemetry — observability obligation in the contract.
- Zil docs — manifest schema, `zil deploy/run/validate`, `.zil` archive.
