# ZIL-RFC-001 — Tool Contract Enforcement (SDK Interception Layer)

| Field | Value |
|---|---|
| **Status** | Draft / Backlog |
| **Target component** | `zil-ai` Python SDK (primary), `zil audit` + `.zil` archive (integration) |
| **Owner** | FluentData / Zil maintainers |
| **Zil version target** | post-v0.1 |
| **License** | Apache 2.0 |
| **Document purpose** | Implementation spec intended to be handed to an LLM coding agent. Be pragmatic. Prefer the smallest correct increment. |

---

## 0. How to read this document

This spec is written so an implementer (human or LLM) with **no prior knowledge of Zil** can build the feature. Section 1 is orientation. Sections 2–4 are the "why" and the standards landscape. Sections 5–13 are the actual design and requirements. Section 14 is acceptance criteria. Section 15 is the phased build plan — **start there if you want to know what to write first.**

When this document and the live Zil codebase disagree, the codebase wins; flag the discrepancy. When this document references external specs (MCP, ADK), **verify against the currently installed version** — those specs move, and the version pinned in `pyproject.toml` is the source of truth.

---

## 1. Primer: what Zil is

Zil is an open-source CLI and Python SDK for **validating, packaging, and deploying production AI agents**. It does not reinvent agent orchestration, tool protocols, evaluation, or telemetry — it **composes** with existing standards: Google ADK (agent framework), MCP (Model Context Protocol, tool protocol), DeepEval (evals), and OpenTelemetry (tracing).

Core mental model:

- **The manifest is the contract.** A declarative `manifest.yaml` describes an agent's runtime, identity, tools, evals, and observability.
- **The CLI is a thin wrapper** over that manifest: `init`, `validate`, `audit`, `eval`, `pack`, `push`, `deploy`, etc.
- **`zil pack`** produces a signed, portable `.zil` archive (manifest + agent code + MCP tools + SBOM + eval results + cosign signature + SLSA provenance).
- **The SDK** exposes `zil.create_agent(...)`, which reads the manifest and identity files and returns a **fully wired ADK agent**. This is the single chokepoint where every tool is bound to the agent before it runs.

Four guiding principles that constrain this feature:

1. **Built on what exists** — compose with ADK/MCP/DeepEval/OTel; do not invent new protocols.
2. **Declarative-first** — the manifest is the contract; code reads it.
3. **No new runtime** — agents run on the user's existing infra (Cloud Run, Bedrock, k8s…).
4. **No new registry** — use OCI registries the user already has.

> **Constraint implication for this feature:** because of principle 3, enforcement logic must live in the **SDK abstraction layer** (inside `create_agent`'s wiring), *not* in any standalone runtime service. The SDK travels inside the agent and the `.zil` artifact, so it enforces wherever the agent is deployed.

---

## 2. Problem statement (the "why")

AI agents call tools (functions, APIs, MCP servers). Today, tool definitions describe a tool's **type signature** but almost never its **behavioral contract**: whether a call is idempotent, reversible, destructive, whether it touches sensitive data, whether it can transmit data outside the trust boundary, or what must happen before it's legal to call.

The MCP ecosystem has begun standardizing a **vocabulary** for this (see §4), but that vocabulary is **descriptive, not enforced**. It is, in the words of the ecosystem, "a communication vocabulary, not a security boundary." Nothing stops a model from:

- retrying a **non-idempotent** call after a timeout (double-charging, double-sending);
- invoking a **destructive / irreversible** tool with no confirmation;
- calling a tool with **malformed or hallucinated arguments** (the single most common agent tool-use failure);
- passing data obtained from a **sensitive** source into an **egress** tool — the data-exfiltration path (the "lethal trifecta": sensitive data access + exposure to untrusted input + an egress capability);
- calling a tool **out of order**, before its precondition has been satisfied.

These are the failure modes most cited for why agent projects break in production. They are **contract problems**, and they are checkable.

---

## 3. The closed loop (how this feature fits Zil)

Zil already declares and statically checks parts of this. The feature completes a loop so that the *same contract* is honored at every stage with **no drift surface**:

```
manifest.yaml          zil audit              zil pack                 SDK interceptor
(DECLARE)        →     (CHECK statically) →   (ATTEST, signed)    →    (ENFORCE at runtime)
contract block         dataflow findings      contract attestation     allow/block/approve
```

- **Declare:** tool contracts live in `manifest.yaml` (§11).
- **Check:** `zil audit` reads contracts and emits static findings (e.g., a sensitive→egress dataflow that *could* occur). This partly exists conceptually in the audit command today (it already scores injection resilience, PII leakage, indirect-injection surface).
- **Attest:** `zil pack` writes a signed contract attestation into the `.zil` archive.
- **Enforce:** the SDK loads the attested contract and enforces it at tool-call time.

The headline property: **the runtime enforces exactly what was audited and signed.** Because the SDK that loads the attested contract is the same code that wires the interceptor, there is no separate configuration that can drift from the attestation.

---

## 4. Existing standards & prior art (use these; do not reinvent)

**MCP tool annotations (the vocabulary).** As of the MCP 2025-03-26 spec revision, tool annotations include `readOnlyHint`, `idempotentHint`, `destructiveHint`, and `openWorldHint`. Active spec-enhancement proposals add `sensitiveHint` (tool accesses sensitive data), `egressHint` (tool can transmit data outside the system boundary), and `reversibleHint` (effects can be undone). **Verify the exact set and field names against the installed MCP version** — treat MCP as the upstream source of the vocabulary and map onto it rather than inventing parallel names.

**ADK callbacks (the enforcement hook for the first adapter).** Google ADK exposes `before_tool_callback` and `after_tool_callback`. Returning a value from the before-callback short-circuits the tool invocation, which is the mechanism for `BLOCK`/`MUTATE`. **Verify the exact callback signatures and short-circuit semantics against the installed ADK version** before relying on them.

**Lethal trifecta** (Simon Willison's framing) — the conjunction of (a) access to sensitive data, (b) exposure to untrusted/attacker-controllable content, and (c) an ability to exfiltrate. The sensitive→egress dataflow check (§9.6) targets the (a)+(c) leg that Zil can see structurally.

**Agent tool-use eval metrics** (DeepEval and related) — correct tool selection rate, **first-attempt argument validity**, error propagation, recovery quality. The shape-validation check (§9.1) directly improves first-attempt argument validity; these metrics are the natural way to measure this feature's effect in `zil eval`.

**OpenTelemetry** — emit enforcement decisions as spans/events; do not build a bespoke telemetry path.

---

## 5. Goals and non-goals

### Goals
1. A **framework-neutral** core that decides allow/block/approve/mutate for any tool call, reading a declared contract. The core must not import ADK or any framework.
2. A **per-framework adapter** pattern; ship the **ADK adapter** first.
3. Enforce: argument/protocol shape validation, idempotency, destructive/irreversible gating, read-only enforcement, sensitive→egress dataflow, and ordering preconditions.
4. Source contracts from `manifest.yaml`, merged with MCP annotations where available.
5. Configurable enforcement modes (enforce / warn / off) globally and per-check.
6. Emit every decision via OpenTelemetry.
7. Compose as one link in an **interceptor chain**, not a monolith.

### Non-goals (explicitly out of scope)
- **Not** a content/behavior guardrail system (prompt-injection text filtering, persona enforcement). That is `identity/guardrails.yaml`'s concern. This feature is **structural/protocol** enforcement. (See Open Question §17 on how the two pipelines relate.)
- **Not** an inline network proxy, sandbox, or syscall filter. Enforcement is at the tool-dispatch boundary inside the agent process.
- **Not** a replacement for ADK orchestration.
- **Not** the approval *mechanism* itself — the SDK *decides* `REQUIRE_APPROVAL`; the runtime services it (§10).
- **Not** a guarantee against a model that *launders* sensitive data through its own reasoning before egress (see §9.6 limitation — this is honest defense-in-depth, not a complete boundary).

---

## 6. Architecture overview

Ports-and-adapters (hexagonal):

```
        ┌─────────────────────────────────────────────┐
        │              Framework adapter               │   ← knows ADK (or LangGraph, …)
        │   before_tool_callback / after_tool_callback │
        └───────────────────┬─────────────────────────┘
                            │ translates to neutral calls
        ┌───────────────────▼─────────────────────────┐
        │            InterceptorChain (neutral)        │   ← no framework imports
        │   runs ordered ToolCallInterceptors          │
        └───────────────────┬─────────────────────────┘
                            │
        ┌───────────────────▼─────────────────────────┐
        │   ContractInterceptor (neutral)              │
        │   reads ToolContract + CallContext → Decision│
        └──────────────────────────────────────────────┘

   CallContext carries: contracts (static, from manifest/.zil),
   session-scoped InterceptionState (call log + taint set + completed tools),
   and EnforcementConfig.
```

Hard rule: **the neutral package must have zero framework dependencies** and must be unit-testable with a stub adapter. Adapters live in separate modules (e.g. `zil.contract.adapters.adk`).

---

## 7. Neutral core — types and interfaces

Implement in pure Python (the SDK is Python). These are reference signatures; adjust to house style but preserve semantics.

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Protocol


class Verdict(Enum):
    ALLOW = "allow"
    BLOCK = "block"
    REQUIRE_APPROVAL = "require_approval"
    MUTATE = "mutate"      # before_call only: replace args
    REDACT = "redact"      # after_call only: replace/scrub result


@dataclass
class Decision:
    verdict: Verdict
    rule_id: str                              # which check fired, e.g. "shape", "sensitive_egress"
    reason: str                               # operator/log-facing explanation
    model_facing_message: Optional[str] = None  # surfaced back to the model on BLOCK/APPROVAL
    replacement: Optional[Any] = None         # MUTATE: new args dict; REDACT: new result
    metadata: dict = field(default_factory=dict)

    @staticmethod
    def allow(rule_id: str) -> "Decision":
        return Decision(Verdict.ALLOW, rule_id, "ok")


@dataclass
class ToolContract:
    name: str
    read_only: bool = False
    idempotent: bool = False
    destructive: bool = False
    reversible: Optional[bool] = None         # None = unknown
    sensitive: bool = False                    # accesses sensitive data
    egress: bool = False                       # can transmit data outside the boundary
    input_schema: Optional[dict] = None        # JSON Schema for arguments
    preconditions: list[str] = field(default_factory=list)  # tool names that must have completed
    raw: dict = field(default_factory=dict)    # passthrough of MCP annotations / manifest extras


@dataclass
class CallRecord:
    tool_name: str
    args_fingerprint: str                      # stable hash of normalized args
    ok: bool


@dataclass
class InterceptionState:
    """Session-scoped, OWNED BY THIS LAYER. Do not back this with ADK's session object."""
    call_log: list[CallRecord] = field(default_factory=list)
    tainted: set[str] = field(default_factory=set)   # fingerprints of sensitive-origin values
    completed_tools: set[str] = field(default_factory=set)


class EnforcementMode(Enum):
    ENFORCE = "enforce"
    WARN = "warn"
    OFF = "off"


@dataclass
class EnforcementConfig:
    mode: EnforcementMode = EnforcementMode.ENFORCE        # global default
    overrides: dict[str, EnforcementMode] = field(default_factory=dict)  # per rule_id
    fail_mode: str = "closed"                              # "closed" | "open"

    def mode_for(self, rule_id: str) -> EnforcementMode:
        return self.overrides.get(rule_id, self.mode)


@dataclass
class CallContext:
    session_id: str
    contracts: dict[str, ToolContract]
    state: InterceptionState
    config: EnforcementConfig


class ToolCallInterceptor(Protocol):
    def before_call(self, tool_name: str, args: dict, ctx: CallContext) -> Decision: ...
    def after_call(self, tool_name: str, args: dict, result: Any, ctx: CallContext) -> Decision: ...
```

### Chain semantics

```python
class InterceptorChain:
    def __init__(self, interceptors: list[ToolCallInterceptor]): ...

    def before_call(self, tool_name, args, ctx) -> Decision:
        # Run in order. First BLOCK or REQUIRE_APPROVAL short-circuits and is returned.
        # MUTATE applies its replacement to args, records it, and continues the chain.
        # If none fire, return Decision.allow("chain").
        ...

    def after_call(self, tool_name, args, result, ctx) -> Decision:
        # Same, but REDACT replaces the result and continues.
        ...
```

**Mode application:** a check computes its *intended* verdict; the chain then downgrades it according to `config.mode_for(rule_id)`. In `WARN` mode a `BLOCK` becomes an `ALLOW` **plus** an emitted warning event. In `OFF` mode the check is skipped entirely. `ENFORCE` applies the verdict as-is.

---

## 8. Framework adapter — ADK (first adapter)

The adapter is the only place allowed to import ADK. It builds the two callbacks that `create_agent` attaches to the wired agent.

```python
# zil/contract/adapters/adk.py   (verify ADK signatures against installed version)

def make_adk_callbacks(chain, ctx_provider, approval_port=None):
    def before_tool_callback(tool, args, tool_context):
        ctx = ctx_provider(tool_context)            # resolves session_id + InterceptionState
        d = chain.before_call(tool.name, args, ctx)
        if d.verdict is Verdict.BLOCK:
            return {"error": d.model_facing_message or d.reason}   # short-circuits the tool
        if d.verdict is Verdict.REQUIRE_APPROVAL:
            if approval_port is None:
                return {"error": d.model_facing_message or "Approval required; no approver configured."}
            return approval_port.request(tool.name, args, d, ctx)  # runtime-serviced (§10)
        if d.verdict is Verdict.MUTATE:
            args.clear(); args.update(d.replacement)
        return None    # proceed to real tool

    def after_tool_callback(tool, args, tool_context, tool_response):
        ctx = ctx_provider(tool_context)
        d = chain.after_call(tool.name, args, tool_response, ctx)
        if d.verdict is Verdict.REDACT:
            return d.replacement
        if d.verdict is Verdict.BLOCK:
            return {"error": d.model_facing_message or d.reason}
        return None

    return before_tool_callback, after_tool_callback
```

`ctx_provider` maps the framework's per-invocation object to a stable `session_id` and the layer-owned `InterceptionState` (create-on-first-use, keyed by session). **Session lifetime = one agent conversation/session; provide an explicit reset.**

### Wiring into the SDK

`zil.create_agent(...)` should:
1. Load contracts (manifest → `ToolContract`s; merge MCP annotations; prefer the `.zil` attestation when running from a packed archive — §11/§12).
2. Build the `ContractInterceptor` (+ any others) into an `InterceptorChain`.
3. Build ADK callbacks via the adapter and attach them to the wired agent.
4. Be a **no-op when no contracts are declared and `fail_mode: open`** (zero behavior change for users who haven't adopted contracts), so the feature is strictly additive.

---

## 9. The checks (functional requirements)

Each check has a stable `rule_id`, a phase (before/after), a state requirement, and an intended verdict. Implement each as a small function the `ContractInterceptor` dispatches to.

### 9.1 Shape / protocol validation — `rule_id: "shape"` · before · stateless
Validate `args` against `contract.input_schema` (JSON Schema). On violation → `BLOCK` with a `model_facing_message` naming the offending field(s) so the model can self-correct. **Highest-value, cheapest, implement first.** For non-MCP plain-Python tools without a schema, derive one from type hints / pydantic signatures if available; otherwise skip with a warning.

### 9.2 Idempotency — `rule_id: "idempotency"` · before · stateful
If `contract.idempotent is False` and `call_log` already contains a `CallRecord` with the same `(tool_name, args_fingerprint)` → intended `BLOCK` (default `WARN` — see defaults §12). Fingerprint = stable hash of normalized args (sorted keys, canonical JSON).

### 9.3 Destructive gating — `rule_id: "destructive"` · before · stateless
If `contract.destructive` → intended `REQUIRE_APPROVAL`. If `reversible is False`, raise severity (still `REQUIRE_APPROVAL`, but mark `metadata["irreversible"]=True` for the approver UI).

### 9.4 Read-only enforcement — `rule_id: "read_only"` · before · stateless
If `contract.read_only is True` but the tool is also flagged `destructive`/`egress`, that is a **contract contradiction** → `BLOCK` and surface as a configuration error (this should also be caught earlier by `zil validate`).

### 9.5 Precondition / ordering — `rule_id: "precondition"` · before · stateful
If any name in `contract.preconditions` is not in `state.completed_tools` → `BLOCK` with a message naming the missing prerequisite.

### 9.6 Sensitive→egress dataflow (lethal-trifecta leg) — `rule_id: "sensitive_egress"` · before+after · stateful
- **after_call:** if the just-completed tool's `contract.sensitive is True`, compute fingerprints of values in `result` and add them to `state.tainted`.
- **before_call:** if `contract.egress is True`, check whether any fingerprint of the values in `args` is in `state.tainted` → intended `BLOCK`.

> **Honest limitation — document in code and to the operator:** this catches **direct passthrough** of sensitive values into an egress call. It does **not** catch a model that paraphrases, summarizes, or re-encodes sensitive data before egress (taint is defeated by transformation). This check is **defense-in-depth alongside** the static `zil audit` finding and content guardrails — not a complete exfiltration boundary. Do not let the implementation or the docs claim otherwise.

---

## 10. `REQUIRE_APPROVAL` — decision vs. servicing

The SDK **decides** `REQUIRE_APPROVAL`. It does **not** implement how a human approves. Define a narrow port:

```python
class ApprovalPort(Protocol):
    def request(self, tool_name: str, args: dict, decision: Decision, ctx: CallContext) -> Any:
        """Return a tool-result-shaped object: an approved passthrough, a denial, or a
        'pending' sentinel. Blocking vs async is the adapter's choice."""
```

Provide two reference adapters:
- **Interactive** (`zil run` / `zil web`): prompt on the console / UI inline.
- **Deployed/autonomous**: emit to an approval queue and return a `pending` result; the **reference runtime** (e.g. the GCP FastAPI service) services the queue. This is the legitimate role of the runtime service — the decision stays in the SDK, the mechanism lives in the runtime.

---

## 11. Manifest schema additions

Extend the manifest `tools` entries with an optional `contract`, and add a top-level `contract_enforcement` block. Backward compatible: absence of `contract` ⇒ unknown ⇒ governed by `fail_mode`.

```yaml
spec:
  tools:
    - name: send_email
      contract:
        destructive: true
        reversible: false
        egress: true
        idempotent: false
    - name: read_customer_record
      contract:
        read_only: true
        sensitive: true
        idempotent: true
    - name: create_ticket
      contract:
        destructive: true
        reversible: true
        idempotent: false
        preconditions: [authenticate_user]

  contract_enforcement:
    mode: enforce            # enforce | warn | off   (global default)
    fail_mode: closed        # closed | open  — when a called tool has NO contract, or a check errors
    overrides:               # per rule_id
      idempotency: warn
      destructive: require_approval   # note: 'require_approval' is allowed as an override target for gating checks
      sensitive_egress: block
```

Field names should **map onto MCP annotation names** where they exist (e.g. manifest `read_only` ⇄ MCP `readOnlyHint`). Provide a documented mapping table in code. `zil validate` must validate this block (presence, types, contradictions like read_only+destructive); `zil audit` consumes it for the static dataflow finding.

---

## 12. Configuration & defaults

Recommended defaults for v1 (tunable; chosen to favor adoption while hard-stopping the dangerous cases):

| Check (`rule_id`) | Default mode | Default verdict when fired |
|---|---|---|
| `shape` | enforce | BLOCK |
| `sensitive_egress` | enforce | BLOCK |
| `destructive` | enforce | REQUIRE_APPROVAL |
| `precondition` | enforce | BLOCK |
| `read_only` (contradiction) | enforce | BLOCK |
| `idempotency` | **warn** | BLOCK (downgraded to warn) |

`fail_mode` default: **`closed`** for the security-sensitive checks is ideal, but for v0.x preview adoption consider shipping global `fail_mode: open` for *undeclared* tools (so unannotated tools don't suddenly break) while keeping declared dangerous contracts at enforce. Make this an explicit, documented decision, not an accident.

---

## 13. Observability

Every non-trivial decision (anything other than `ALLOW`, plus all `WARN`-downgrades) emits an OpenTelemetry event/span attribute set: `tool_name`, `rule_id`, `verdict`, `mode`, `session_id`, `reason`, and (for dataflow) a non-reversible taint indicator — **never log the sensitive values themselves.** Reuse the agent's existing OTel config (`observability/config.yaml`); do not create a separate exporter.

---

## 14. Acceptance criteria (write these as tests)

The neutral core test-suite must run **without importing any agent framework** (use a stub adapter).

1. **Shape:** missing required arg ⇒ `BLOCK`, message names the field; valid args ⇒ `ALLOW`.
2. **Idempotency:** non-idempotent tool called twice with identical args in one session ⇒ 2nd call fires `idempotency` (WARN by default, BLOCK under override); idempotent tool ⇒ never fires.
3. **Destructive:** destructive tool ⇒ `REQUIRE_APPROVAL`; with no `ApprovalPort` ⇒ effectively blocked with an approval message; irreversible flag set in metadata.
4. **Sensitive→egress:** sensitive tool result taints state; subsequent egress call carrying a tainted value ⇒ `BLOCK`; egress call with only fresh/untainted args ⇒ `ALLOW`.
5. **Precondition:** tool with unmet precondition ⇒ `BLOCK`; after prerequisite completes ⇒ `ALLOW`.
6. **Modes:** same scenario under `enforce` vs `warn` vs `off` yields block / allow-with-event / skipped, respectively.
7. **Fail mode:** undeclared tool under `closed` ⇒ blocked/flagged; under `open` ⇒ allowed.
8. **Framework neutrality:** core suite passes with zero framework dependency installed.
9. **ADK adapter integration:** an end-to-end ADK agent with one destructive tool and one sensitive+one egress tool exhibits the expected gating/blocking through real `before/after_tool_callback`.
10. **Additivity:** an agent with no `contract` blocks and `fail_mode: open` behaves identically with and without the interceptor wired in.

---

## 15. Phased implementation plan (build order)

**Phase 1 — MVP (neutral core + ADK + the two cheapest high-value checks).**
Neutral types (§7), `InterceptorChain`, `ContractInterceptor`, ADK adapter (§8), `shape` (9.1) and `destructive` gating (9.3, block/approve), contracts sourced from `manifest.yaml`. Stub-adapter test suite (criteria 1, 3, 6, 8, 10). No state required yet beyond a trivial log.

**Phase 2 — stateful checks + dataflow.**
`InterceptionState`, idempotency (9.2), preconditions (9.5), sensitive→egress (9.6 incl. the documented limitation). MCP annotation ingestion: read hints from MCP servers and merge into `ToolContract`s (mapping table). OTel events (§13). Criteria 2, 4, 5.

**Phase 3 — approval servicing + second framework.**
`ApprovalPort` (§10) with interactive + queue adapters; integrate the queue adapter with the reference runtime (GCP FastAPI). Add a second framework adapter (LangGraph or OpenAI Agents SDK) to prove neutrality.

**Phase 4 — close the loop.**
Wire `zil audit` to emit the static sensitive→egress finding from the same contracts; write the contract attestation into the `.zil` archive in `zil pack`; have `create_agent` prefer the attested contract when running from a packed archive. Add a parity test: what `audit` flags statically and what the runtime enforces dynamically agree.

---

## 16. File / module layout (suggested)

```
zil/
  contract/
    __init__.py
    types.py            # Verdict, Decision, ToolContract, CallContext, InterceptionState, EnforcementConfig
    chain.py            # InterceptorChain, mode application
    checks.py           # ContractInterceptor + the per-rule check functions
    loader.py           # manifest → ToolContract; MCP annotation merge; .zil attestation loader
    approval.py         # ApprovalPort protocol + interactive/queue reference adapters
    adapters/
      __init__.py
      adk.py            # make_adk_callbacks  (ONLY file allowed to import ADK)
      stub.py           # test-only neutral adapter
  ...
tests/
  contract/
    test_checks.py
    test_chain_modes.py
    test_dataflow.py
    test_adk_adapter.py
```

---

## 17. Open questions (resolve during implementation; don't block Phase 1)

1. **Relationship to `identity/guardrails.yaml`.** Content guardrails and contract enforcement are conceptually distinct (behavioral vs structural) but could share one interceptor pipeline. Decide: one chain with two interceptor kinds, or two separate pipelines? Recommendation: one chain, two interceptor categories, so ordering and observability are unified.
2. **Taint granularity.** Value-fingerprint matching (proposed) is simple but brittle to transformation. Is field-level provenance worth it later? Document the v1 choice and its limits.
3. **Schema source for non-MCP tools.** MCP gives `inputSchema`; plain Python tools need derivation from type hints/pydantic. Define the fallback precisely.
4. **Approval protocol shape** between SDK `Decision` and the reference runtime queue (payload, identity, timeout, denial semantics).
5. **`fail_mode` default for the preview.** Adoption-friendly `open`-for-undeclared vs secure `closed`. Make it an explicit documented decision (§12).

---

## 18. Definition of done (Phase 1)

- Neutral core + ADK adapter merged, `pip install zil-ai` exposes the interceptor wiring through `create_agent`.
- Acceptance criteria 1, 3, 6, 8, 10 pass in CI.
- Manifest `contract` + `contract_enforcement` blocks parsed and validated by `zil validate`.
- Zero behavior change for agents that declare no contracts under `fail_mode: open`.
- Docs page added under `getzil.dev/docs` describing the manifest blocks and enforcement modes, **including the §9.6 limitation stated plainly.**

---

## 19. References (verify against installed versions)

- Model Context Protocol — tool annotations (`readOnlyHint`, `idempotentHint`, `destructiveHint`, `openWorldHint`) and proposed `sensitiveHint` / `egressHint` / `reversibleHint`.
- Google ADK — `before_tool_callback` / `after_tool_callback` and short-circuit semantics.
- "Lethal trifecta" — sensitive data + untrusted input + egress.
- DeepEval / agent eval metrics — argument validity, tool selection, recovery.
- OpenTelemetry — span/event emission.
- Zil docs — manifest schema, `create_agent`, `zil audit`, `zil pack`, `.zil` archive, cosign/SLSA attestation.
