# Memory (RFC-003)

Zil gives agents **long-term memory** through a framework-neutral core plus
pluggable providers. The same `adapters/memory.yaml` works whether your agent
runs on ADK or OpenHands — Zil wires the provider onto each framework's native
memory surface.

## Concepts

**Scopes** decide *who* a memory belongs to:

| Scope     | Lifetime           | Partition key | Use for |
|-----------|--------------------|---------------|---------|
| `session` | one conversation   | `session_id`  | short-term working context |
| `user`    | across sessions    | `user_id`     | per-user preferences/history |
| `agent`   | shared, long-term  | `namespace`   | segmented knowledge shared by a group of agents |

**Namespace** is the `agent`-scope group key. It is the **cross-agent sharing
contract**: any independent Zil agents that declare the *same* top-level
`namespace` **and** connect to the *same* provider (e.g. the same Mem0
org/project) share one knowledge pool. Different namespaces — or different
provider connections — stay isolated. Sharing happens at the provider
connection, not inside a single manifest.

**Provider** is the backing store. Built in:

- `stub` — in-process, zero-dependency (local dev / tests).
- `mem0` — [Mem0](https://mem0.ai), in three deployment topologies:

| Topology | `memory.yaml` | Connects to | Needs |
|----------|---------------|-------------|-------|
| Mem0 SaaS | `mode: managed` | `api.mem0.ai` | `MEM0_API_KEY` |
| Self-hosted Mem0 **server** | `mode: managed` + `host:` | your private Mem0 REST API | `MEM0_API_KEY` + base URL |
| Mem0 **OSS**, in-process | `mode: self_hosted` + `config:` | your own vector DB (Qdrant/pgvector) directly | the vector/LLM/embedder config |

The neutral core (`zil.sdk.memory`) imports **no** provider or framework SDK,
so it works even when nothing else is installed.

## Configure

Add a memory adapter and reference it from the manifest:

```yaml
# manifest.yaml
spec:
  memory: ./adapters/memory.yaml
  env:
    - name: MEM0_API_KEY
      secret: true
```

```yaml
# adapters/memory.yaml
provider: mem0
mode: managed            # managed | self_hosted
namespace: coding        # default agent-scope group key
scopes: [session, user, agent]
retention:               # governance: long-term scopes should set this
  user: 90d
  agent: 90d
persist:
  exclude_pii: true      # strip PII before persisting long-term/shared memory
```

Install the optional dependency for Mem0:

```bash
uv pip install 'zil-ai[memory]'
```

### Self-hosted Mem0 server

To point the agent at a **privately-deployed Mem0 server** (its REST API running
in your own VPC/cluster) instead of the SaaS endpoint, keep `mode: managed` and
set a `host`. The base URL is not a secret, so it can live in `memory.yaml` or
come from an env var; the API key/token stays in env.

```yaml
# adapters/memory.yaml
provider: mem0
mode: managed
host: https://mem0.my-vpc.internal   # literal URL, or omit and use MEM0_API_BASE
namespace: coding
scopes: [session, user, agent]
```

```bash
# Connection resolved as: host config → MEM0_API_BASE → MEM0_HOST → SaaS default
export MEM0_API_KEY=...                       # server auth token
export MEM0_API_BASE=https://mem0.my-vpc.internal
```

Declare `MEM0_API_BASE` in `spec.env` so it flows through `zil deploy`. (For an
embedded, server-less setup, use `mode: self_hosted` + a `config:` block
pointing Mem0 OSS at your own vector DB instead.)

### Cross-agent shared memory

Shared ("segmented") knowledge is a contract *between independent agents*, not a
sub-agent setting. Two separately deployed agents share a pool when both:

1. set the same top-level `namespace` in their `adapters/memory.yaml`, and
2. point at the same provider connection.

For Mem0 the connection is the org/project, selected via env:

```yaml
# adapters/memory.yaml (in EACH agent that should share the pool)
provider: mem0
namespace: coding          # same namespace → same AGENT-scope pool
scopes: [agent]
```

```bash
# Same Mem0 org/project across the agents → shared store
export MEM0_API_KEY=...
export MEM0_ORG_ID=org_123
export MEM0_PROJECT_ID=proj_abc
```

A `backend-coder` and a `frontend-coder` deployed independently with
`namespace: coding` share knowledge; an `analyst` with `namespace: finance`
(or a different Mem0 project) stays isolated.

## How it wires per framework

- **ADK** — Zil installs a `BaseMemoryService` (backed by your provider) on the
  `Runner` and attaches the `load_memory` recall tool. Completed turns are
  written back automatically; recall reads the `user`/`agent` scope.
- **OpenHands** — short-term context stays with OpenHands' native condenser.
  Zil adds long-term recall at the SDK boundary: relevant memories are injected
  before each turn and the exchange is persisted afterward.

## Curating what gets persisted

By default Zil hands the full turn to the provider, which LLM-extracts "facts" —
useful, but noisy (e.g. *"User asked if they can work on ticket X"*) and a way
for PII to leak into long-term/shared memory. The `persist` block curates the
exchange **before** it reaches the provider (applied for both ADK and OpenHands):

```yaml
# adapters/memory.yaml
persist:
  strategy: explicit         # turn | assistant_only | explicit | off
  marker: "MEMORY:"          # token the agent emits (explicit strategy)
  exclude_pii: true          # enforce PII policy on the write path
  pii_mode: drop             # drop | redact
```

- **`strategy`**
    - `turn` *(default)* — persist the full user+assistant exchange.
    - `assistant_only` — persist only the agent's messages. Note: the provider
      still LLM-extracts facts, so a verbose agent can produce many entries.
    - `explicit` — persist **only** lines the agent marks with `marker`
      (default `MEMORY:`). Each marked fact is written as a single curated
      message, so the provider yields ~one clean memory instead of exploding a
      whole transcript. Everything else is ignored — the highest
      signal-to-noise option.
    - `off` — don't persist conversation turns (recall + seeds still work).
- **`exclude_pii`** — when true, messages matching a PII pattern (email, phone,
  SSN, credit card, IP) are dropped or redacted on the write path, not just in
  packed seeds. Heuristic and high-signal — it does **not** detect personal
  names, so name-bearing content can still be stored.

### Explicit-signal persistence

`strategy: explicit` is the antidote to noisy auto-extraction. The agent decides
what is durable and emits it on its own line:

```
MEMORY: Jesus is the sole owner of ticket INCA-225.
```

Zil extracts the text after `marker`, applies the PII policy, and writes each
fact verbatim. To make this work you must **instruct the agent** to emit the
marker — see the `## Long-term Memory` section in the svt-openhands example's
`identity/instructions.md`. Without that instruction, nothing is persisted.

## SDK

Memory is on by default when an adapter is declared. Toggle it explicitly:

```python
import zil

agent = zil.create_agent(
    enable_memory=True,   # build provider from adapters/memory.yaml
)
```

Use the neutral API directly:

```python
from zil.sdk.memory import MemoryConfig, build_provider
from zil.sdk.memory.types import MemoryKeys, MemoryQuery, MemoryScope

provider = build_provider(MemoryConfig.from_dict({"provider": "stub"}))
provider.write("User prefers Python", scope=MemoryScope.USER, keys=MemoryKeys(user_id="u1"))
hits = provider.retrieve(MemoryQuery("language?", scope=MemoryScope.USER, keys=MemoryKeys(user_id="u1")))
provider.delete(scope=MemoryScope.USER, keys=MemoryKeys(user_id="u1"))  # right-to-be-forgotten
```

## Seeding memories

Ship an agent with pre-loaded AGENT-scope knowledge ("what it is supposed to
do") so it starts useful on first deploy. Seeds come from a committed file
and/or a live snapshot, are PII-filtered into the archive, and self-install
idempotently at startup.

Author a seed file and point to it from the adapter:

```yaml
# adapters/memory.yaml
seed:
  file: ../memory/seed.yaml
```

```yaml
# memory/seed.yaml
version: 1
namespace: coding          # optional; defaults to the adapter namespace
memories:
  - content: "Always run pytest before committing."
  - content: "Use ruff for linting and formatting."
    metadata: { topic: tooling }
```

Only the **AGENT** scope is packable — `session`/`user` are never shipped.

```bash
zil pack                      # bundles the authored seed (PII-filtered)
zil pack --export-memory      # also snapshot live AGENT-scope memories
zil pack --no-memory-seed     # skip seeding entirely
```

- **PII filtering** — entries containing emails, phone numbers, SSNs, credit
  cards, or IPs are *dropped* (with warnings) before they enter the archive,
  and again at runtime as defense-in-depth. The raw `seed.yaml` is never
  bundled — only the filtered `memory/seed.jsonl`.
- **Idempotent install** — on startup Zil seeds the bundle once per namespace,
  keyed by a content digest marker; restarts and redeploys do not duplicate
  memories, and a grown seed only adds the new entries. Requires the provider
  to support `list_all` (Mem0 does). Disable with `enable_memory_seed=False`
  or `ZIL_MEMORY_SEED=0`.

## Governance

- `zil validate` checks the provider is registered, every requested scope is
  supported, substrate presence matches the provider, retention is well-formed,
  long-term scopes declare retention + PII handling, and the seed file (if any)
  parses and is AGENT-scope.
- `zil audit` adds a **Memory Governance** section surfacing PII exposure,
  unbounded retention, the stored-injection/poisoning risk of shared
  (agent-namespace) memory, and PII in the seed file.
- `zil pack` records a sanitized memory **binding** (provider, mode, scopes,
  namespace, retention, PII policy, and seed digest/count) in `BUILD_META.json`.
  Configuration and PII-filtered AGENT-scope seed knowledge are packaged —
  never SESSION/USER data or secrets (auth stays env-referenced).
