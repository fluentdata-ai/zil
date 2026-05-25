# ZIL-RFC-002a — Framework Backend Abstraction

| Field | Value |
|---|---|
| **Status** | Draft / Backlog |
| **Target component** | `zil-ai` Python SDK (`create_agent`, framework backend interface + registry), `zil run`, `zil deploy` |
| **Owner** | FluentData / Zil maintainers |
| **Zil version target** | post-v0.1 |
| **License** | Apache 2.0 |
| **Related** | **Enables RFC-002b (OpenHands Framework Backend)** and every future framework adapter. Part of the **portability theme** (see gap analysis §4.1) alongside RFC-004 (provider adapters) and RFC-011 (runtime conformance). **No dependency on RFC-001 or RFC-003.** |
| **Document purpose** | Implementation spec intended to be handed to an LLM coding agent. Be pragmatic. Prefer the smallest correct increment. |

---

## 0. How to read this document

This spec is written so an implementer (human or LLM) with **no prior knowledge of Zil** can build the feature. Section 1 orients on Zil. Section 2 is the "why." Sections 3–9 are design and requirements. Section 10 is acceptance criteria. Section 11 is the build plan.

When this document and the live Zil codebase disagree, the codebase wins; flag the discrepancy. Verify ADK SDK entry points against the version pinned in the project before relying on them.

> **This RFC was split out of the original RFC-002.** RFC-002 bundled (a) this framework-agnostic abstraction and (b) the OpenHands backend. They live in different delivery waves with a dependency between them, so they are now separate specs. This document is (a); RFC-002b is (b) and depends on this.

---

## 1. Primer: what Zil is

Zil is an open-source CLI and Python SDK for **validating, packaging, and deploying production AI agents**. It composes with existing standards (ADK as the current agent framework, MCP for tools, DeepEval for evals, OpenTelemetry for tracing) rather than reinventing them.

Core mental model:
- **The manifest is the contract.** A declarative `manifest.yaml` describes runtime, identity, adapters, tools, evals, observability.
- **The CLI is a thin wrapper:** `init`, `validate`, `audit`, `eval`, `pack`, `push`, `deploy`.
- **The SDK** exposes `zil.create_agent(...)`, which reads the manifest/identity and returns a fully wired agent. **Today it returns a wired ADK agent, with ADK-specific logic inline in `create_agent`.**
- **Adapters** are how Zil composes with external systems declaratively (e.g. `adapters/llm.yaml`).

Four guiding principles:
1. **Built on what exists** — compose with frameworks; don't reinvent orchestration.
2. **Declarative-first** — the manifest is the contract; code reads it.
3. **No new runtime** — agents run on the user's existing infra.
4. **No new registry** — use existing OCI registries.

> **The current state this RFC changes:** `create_agent` assumes a single framework (ADK). The manifest already has a `runtime.framework` field, but only `adk` is honored and the wiring is hardwired. This RFC turns that into a **framework-backend abstraction** so ADK becomes one backend among many.

---

## 2. Problem statement (the "why")

The Zil framework spec sells **tooling-agnostic** portability — "Gemini Enterprise Agent Platform, Bedrock Agents, Vertex AI, LangGraph, CrewAI, custom frameworks, or a mix" — as a core commercial argument (enterprises avoiding single-provider dependency). The implementation is **ADK-only**, with framework specifics baked into `create_agent`.

"Support frameworks other than ADK" is fundamentally an **abstraction problem, not a per-framework problem.** Adding a second framework by branching inside `create_agent` would bury framework-specific code inline and make the third and fourth frameworks progressively worse. The correct, one-time move is to define a `FrameworkBackend` interface, refactor the existing ADK path into one implementation of it, and dispatch by `runtime.framework`. After that, every new framework (OpenHands per RFC-002b, later LangGraph/CrewAI) is a self-contained adapter.

This abstraction is **foundational and small**, and it is the prerequisite for the entire framework-portability half of the spec's no-lock-in promise. It is the framework-layer sibling of RFC-004 (provider adapters) and RFC-011 (runtime conformance) — the same "turn a hardwired dependency into a swappable adapter" move at the framework layer.

---

## 3. Goals and non-goals

### Goals
1. Define a **framework-neutral `FrameworkBackend` interface** plus a `name → backend` registry.
2. Define a framework-neutral **`AgentSpec`** (parsed from manifest + identity files) and an opaque **`WiredAgent`** handle the rest of Zil treats uniformly.
3. **Refactor the existing ADK wiring** out of `create_agent` into an `AdkBackend` implementing the interface — behavior-preserving.
4. Make `create_agent` dispatch by `runtime.framework`; unknown framework → clear validation error.
5. Back `zil run` and `zil deploy` through the backend interface (each backend supplies local-run and deploy-descriptor behavior).
6. Provide a **test-only stub backend** so the abstraction is unit-testable without any framework installed.

### Non-goals (out of scope)
- **Any specific non-ADK framework.** OpenHands is RFC-002b; LangGraph/CrewAI/etc. are future adapters. This RFC ships exactly the abstraction + the ADK backend refactor + a stub.
- **A new runtime** (principle 3). The backend decides how to run/deploy on existing infra; it does not introduce a Zil runtime. (Runtime *conformance* is RFC-011.)
- **Provider adapters** (LLM/embedding/vector) — RFC-004.
- **Changing ADK behavior.** This is a refactor; existing ADK agents must behave identically.

---

## 4. Architecture overview

```
            zil.create_agent(manifest, identity, tools, ...)
                              │
                              │ parse → AgentSpec; read runtime.framework
                              ▼
                   FrameworkBackend registry (name → backend)
                ┌───────────────┬──────────────────────────────┐
                ▼               ▼                               ▼
           AdkBackend     StubBackend (test-only)      (future: OpenHandsBackend → RFC-002b,
        (existing ADK                                    LangGraphBackend, …)
         logic, moved)
                │
                ▼
        WiredAgent  ── consumed uniformly by zil run / deploy / pack
```

Hard rules:
- `create_agent` must know **only** the `FrameworkBackend` interface — no inline framework branches.
- Each backend is the **only** module importing its framework's SDK (`AdkBackend` is the only place importing ADK).
- The neutral interface + registry have zero framework imports and are testable with `StubBackend`.

---

## 5. Neutral core — types and interfaces

Reference signatures; adjust to house style but preserve semantics.

```python
from typing import Protocol, Any
from dataclasses import dataclass, field


@dataclass
class AgentSpec:
    """Framework-neutral, parsed from manifest + identity files."""
    name: str
    version: str
    instructions: str            # composed from identity/persona.md + instructions.md (+ guardrails)
    model: dict                  # from adapters/llm.yaml (provider, model, params)
    tools: list[Any]             # python tool callables + resolved MCP tools
    mcp_servers: list[dict]      # MCP server configs from manifest
    observability: dict          # OTel config
    raw_manifest: dict


class WiredAgent(Protocol):
    """Opaque handle the rest of Zil treats uniformly."""
    @property
    def framework(self) -> str: ...


class FrameworkBackend(Protocol):
    name: str  # "adk" | "openhands" | "stub" | ...

    def wire(self, spec: AgentSpec) -> WiredAgent:
        """Build and return a runnable agent for this framework."""
        ...

    def run_local(self, agent: WiredAgent, **kwargs) -> None:
        """Back `zil run` for this framework."""
        ...

    def deploy_descriptor(self, agent: WiredAgent, spec: AgentSpec) -> dict:
        """Return framework-specific deploy metadata `zil deploy` needs
        (e.g. runtime image, entrypoint, sandbox/runtime requirements)."""
        ...


class BackendRegistry:
    """Maps runtime.framework → FrameworkBackend. Backends self-register."""
    def register(self, backend: FrameworkBackend) -> None: ...
    def get(self, name: str) -> FrameworkBackend: ...   # raises clear error on unknown
```

`create_agent` becomes: parse manifest/identity → build `AgentSpec` → `registry.get(runtime.framework)` → `backend.wire(spec)`.

---

## 6. The ADK backend refactor (the bulk of this RFC)

Move the existing ADK-specific wiring out of `create_agent` into `AdkBackend(FrameworkBackend)`:
- `wire(spec)` → the current ADK `LlmAgent` construction (model resolution via LiteLLM prefix convention, identity composition, tool/MCP wiring, telemetry/cost/guardrail attachment as today).
- `run_local(agent)` → what `zil run` does today (wrap `adk run`).
- `deploy_descriptor(agent, spec)` → what `zil deploy` needs today (Cloud Run image/entrypoint/env).

This is mechanical and **behavior-preserving** — the test bar is that existing ADK agents are unaffected (criterion 1). Do not change ADK semantics; only relocate.

---

## 7. CLI / SDK wiring

- `create_agent` dispatches via the registry (§5).
- `zil run` calls `backend.run_local`.
- `zil deploy` uses `backend.deploy_descriptor` for the framework-specific portion (keeping the existing Cloud Run flow for `adk`).
- `zil validate` validates `runtime.framework` against registered backends and errors clearly on unknown values.
- `create_agent` should be a **no-op change for existing projects**: an ADK manifest with no other edits behaves exactly as before.

---

## 8. Manifest

`runtime.framework` already exists. This RFC formalizes it as the backend selector. No new manifest fields are required for the abstraction itself; specific backends (e.g. RFC-002b) add their own framework-scoped blocks and validation.

---

## 9. File / module layout (suggested)

```
zil/
  agent.py                 # create_agent: parse → AgentSpec → registry.get → wire
  frameworks/
    __init__.py            # FrameworkBackend protocol + BackendRegistry + default registrations
    base.py                # AgentSpec, WiredAgent, FrameworkBackend, BackendRegistry
    adk/
      __init__.py
      backend.py           # AdkBackend (existing ADK logic moved here; ONLY ADK import site)
    stub/
      __init__.py
      backend.py           # StubBackend (test-only, no framework deps)
  ...
tests/
  frameworks/
    test_backend_registry.py
    test_adk_unchanged.py
    test_stub_backend.py
```

---

## 10. Acceptance criteria (write these as tests)

1. **ADK unaffected (refactor safety):** all existing ADK agent tests pass unchanged after the extraction.
2. **Dispatch:** `runtime.framework: adk` → `AdkBackend`; an unknown value → clear validation error naming the unknown framework and listing registered backends.
3. **Neutrality:** the core (`FrameworkBackend`, `AgentSpec`, `BackendRegistry`) + `StubBackend` pass tests with **no agent framework installed**.
4. **Registry:** a backend can self-register and be resolved by name; duplicate registration handled deterministically.
5. **CLI passthrough:** `zil run` and `zil deploy` route through the backend interface for the `adk` backend with identical observable behavior to today.
6. **Extensibility proof (lightweight):** `StubBackend` can be wired and `zil run` against it executes the stub's `run_local` — demonstrating a second backend needs no `create_agent` changes.

---

## 11. Phased implementation plan

**Phase 1 — interface + registry + stub.** `base.py` (types, protocol, registry), `StubBackend`, registry wiring in `create_agent`. Criteria 3, 4, 6.

**Phase 2 — ADK refactor.** Move ADK logic into `AdkBackend`; route `create_agent`/`run`/`deploy` through it. Criteria 1, 2, 5.

That's the whole RFC — deliberately small. It exists so RFC-002b (and any later framework) is a self-contained adapter.

---

## 12. Definition of done

- `FrameworkBackend` + `BackendRegistry` + `AgentSpec`/`WiredAgent` merged; core tests pass with no framework installed.
- ADK logic relocated into `AdkBackend`; existing ADK agents behave identically (criterion 1).
- `create_agent`, `zil run`, `zil deploy`, `zil validate` route framework selection through the registry.
- A `StubBackend` proves a second framework needs no `create_agent` changes.
- Docs: a short note on `runtime.framework` and the backend model under `getzil.dev/docs`.

---

## 13. References (verify against installed versions)

- Google ADK — current `create_agent` wiring, `LlmAgent`, run/deploy paths (the logic being relocated).
- ZIL-RFC-002b — OpenHands Framework Backend (the first consumer of this abstraction).
- ZIL-RFC-004 — provider adapters (sibling abstraction at the provider layer).
- ZIL-RFC-011 — runtime conformance (sibling abstraction at the runtime layer).
- Zil docs — manifest schema, `create_agent`, `zil run/deploy/validate`.
