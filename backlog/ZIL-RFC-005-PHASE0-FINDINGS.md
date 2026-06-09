# ZIL-RFC-005 — Phase 0 Verification Findings (A2A interoperability)

| Field | Value |
|---|---|
| **Status** | Findings / pins APIs for RFC-005 Phase 1 |
| **Date** | 2026-06-08 |
| **Method** | Inspected **installed** packages (authoritative for pinned versions), diffed against the shipped `zil serve` A2A surface. |
| **Sources pinned** | `a2a-sdk` **1.0.3** (in `tmp/svt/.venv`, `tmp/revreq/.venv`); `google-adk` **1.32.0** (main `.venv`). `a2a-sdk` is **not** installed in the main `.venv`. |

> **Headline:** the shipped `zil serve` A2A server implements an **outdated (legacy v0.1-style) A2A surface** that is **not interoperable** with current A2A clients (`a2a-sdk` 1.0.x, and `google-adk`'s `RemoteA2aAgent` when `a2a-sdk` is present). Interop-first means **server conformance must be fixed before (or with) building the client.** This materially re-sequences RFC-005.

> **⚠️ Correction (2026-06-08, Phase 1b build):** the `a2a-sdk` **1.0.3** version pinned below came from the unrelated `tmp/*/.venv` envs and is **the wrong reference for our toolchain.** `google-adk` 1.32 pins **`a2a-sdk>=0.3.4,<0.4`**, and its `RemoteA2aAgent` imports `a2a.client.ClientEvent`, which **does not exist in `a2a-sdk` 1.0.x/1.1.x** — so installing 1.x **breaks** ADK. The build standardizes on **`a2a-sdk` 0.3.x** (installed 0.3.26), matching what `pip install zil-ai[adk]` resolves. **All conformance conclusions still hold on 0.3.x:** the well-known path is identical (`AGENT_CARD_WELL_KNOWN_PATH == "/.well-known/agent-card.json"`), the JSON-RPC method set matches, `AgentSkill.tags` is required, and our served card validates against `a2a.types.AgentCard` (the pydantic model lives at **`a2a.types`** in 0.3.x, not `a2a.compat.v0_3.types` which is 1.x-only). Read every "1.0.3" below as "0.3.x" for our toolchain.

---

## 1. Current A2A protocol (pinned from `a2a-sdk` 1.0.3)

### 1.1 Well-known path
- **Current:** `AGENT_CARD_WELL_KNOWN_PATH = "/.well-known/agent-card.json"` (`a2a/utils/constants.py`).
- **Default RPC URL:** `DEFAULT_RPC_URL = "/"`.
- **Version header:** `A2A-Version`. `PROTOCOL_VERSION_CURRENT = "1.0"` (with `"0.3"` supported).
- Transports: `JSONRPC` (default), `HTTP+JSON`, `GRPC`.

> Note: `google-adk` 1.32 has a **fallback** `AGENT_CARD_WELL_KNOWN_PATH = "/.well-known/agent.json"` used only when `a2a-sdk` is absent; when `a2a-sdk` is installed it imports the SDK constant (`/.well-known/agent-card.json`). So a current client resolving a card by URL will hit `/.well-known/agent-card.json` first.

### 1.2 RPC methods (JSON-RPC 2.0; `a2a/compat/v0_3/types.py`)
`message/send`, `message/stream`, `tasks/get`, `tasks/cancel`, `tasks/resubscribe`, `tasks/pushNotificationConfig/{set,get,list,delete}`, `agent/getAuthenticatedExtendedCard`.
All are JSON-RPC 2.0 envelopes: `{ "jsonrpc": "2.0", "id", "method", "params" }`, POSTed to the single RPC URL (`/`).

### 1.3 AgentCard (required fields; camelCase on the wire)
`A2ABaseModel` uses `alias_generator=to_camel` + `populate_by_name=True`, so JSON is camelCase.
- **Required:** `capabilities`, `defaultInputModes`, `defaultOutputModes`, `description`, `name`, `skills`, `url`, `version`.
- **Defaulted:** `protocolVersion` (`"0.3.0"`), `preferredTransport` (`"JSONRPC"`).
- **Optional:** `additionalInterfaces`, `provider`, `security`, `securitySchemes`, `signatures`, `documentationUrl`, `iconUrl`, `supportsAuthenticatedExtendedCard`.

### 1.4 AgentSkill (required fields)
- **Required:** `id`, `name`, `description`, **`tags: list[str]`**.
- **Optional:** `examples`, `inputModes`, `outputModes`, `security`.

### 1.5 `AgentCapabilities`
`streaming`, `pushNotifications`, `stateTransitionHistory`, `extensions` — all optional.

---

## 2. Shipped `zil serve` surface (from `src/zil/commands/serve.py`)

- **Well-known path:** `GET /.well-known/agent.json` — **legacy** (current = `/.well-known/agent-card.json`).
- **Methods:** `POST /tasks/send`, `POST /tasks/sendSubscribe`, `GET /tasks/{id}` — **legacy A2A v0.1 REST naming.** No JSON-RPC envelope; not the `message/send` + `message/stream` of current spec, nor the HTTP+JSON binding.
- **Card:** missing `protocolVersion` and `preferredTransport`.
- **Skills (post-§8):** emits `{id, name, description}` — **missing the required `tags` field**, so a strict client validating the card rejects the skills.

---

## 3. Diff / discrepancies (interop-blocking → cosmetic)

| # | Area | Shipped (Zil) | Current spec (a2a-sdk 1.0.3) | Severity |
|---|---|---|---|---|
| 1 | Well-known path | `/.well-known/agent.json` | `/.well-known/agent-card.json` | **Blocking** (clients can't find the card) |
| 2 | Transport / methods | REST `tasks/send`, `tasks/sendSubscribe`, `tasks/{id}` | JSON-RPC `message/send`, `message/stream`, `tasks/get` at `/` (or HTTP+JSON binding) | **Blocking** (clients can't invoke) |
| 3 | AgentSkill `tags` | absent | required | **High** (card fails validation) |
| 4 | Card `protocolVersion` | absent | present (default `0.3.0`) | Medium (no version negotiation) |
| 5 | Card `preferredTransport` | absent | present (default `JSONRPC`) | Medium (transport ambiguous) |
| 6 | Skill modes/security | absent | optional | Low |

---

## 4. `RemoteA2aAgent` (client primitive) — viable

`google.adk.agents.RemoteA2aAgent(BaseAgent)` (ADK 1.32) constructor accepts:
- `agent_card: Union[AgentCard, str]` — an `AgentCard` object, a **URL** to the card, or a **file path**. (Raises on `None`/empty.)
- Plus `httpx_client`, `timeout`, converters, `a2a_client_factory`, `config: A2aRemoteAgentConfig`, request interceptors.
- Handles card resolution/validation, httpx lifecycle, A2A message conversion, and session state.

**Conclusion:** the ADK adapter for RFC-005's client can wrap a peer via `RemoteA2aAgent(name=..., agent_card="<peer-url>")` and expose it through `AgentTool` — **but only if the peer serves a current, conformant card at the current well-known path.** That circles back to the server gaps (§3).

---

## 5. Implications for RFC-005 (re-sequencing)

1. **Add a server-conformance item BEFORE the client.** Bring `zil serve` to the current A2A spec — new well-known path `/.well-known/agent-card.json` (keep `/.well-known/agent.json` as a deprecated alias for back-compat), JSON-RPC `message/send`/`message/stream`/`tasks/get` at `/`, and `protocolVersion`/`preferredTransport` on the card. Decide transport: **JSONRPC** (spec default, what `RemoteA2aAgent` expects) vs **HTTP+JSON**. Recommend **JSONRPC** for max client compatibility.
2. **Fix AgentSkill `tags`** in the §8 card emission now (trivial; emit `tags: []` until skills declare tags). Keeps the just-shipped change forward-conformant.
3. **Pin `a2a-sdk` as the conformance reference.** Add `a2a-sdk` (>=1.0.3) to the `serve` extra so the server can reuse `a2a` types/server helpers instead of hand-rolling JSON-RPC, and so tests validate against real `AgentCard`/`AgentSkill` models.
4. **Client adapter is unblocked** once the server is conformant: ADK `RemoteA2aAgent` by URL is the path.
5. **Verification owns the contract.** Add a conformance test that builds the card with `a2a.compat.v0_3.types.AgentCard(**card)` (will raise on missing `tags`/fields) — turning "conformant" into a test, not a claim.

### Suggested revised Phase 1 order
**(1a) Server conformance** (well-known path + JSON-RPC methods + card fields + `tags`) → **(1b) card validated against `a2a-sdk` types in tests** → **(1c) `spec.collaborators` + A2A client via ADK `RemoteA2aAgent`**.

---

## 6. Open items to confirm before Phase 1 build
- **Protocol target:** `0.3.0` vs `1.0` — `a2a-sdk` 1.0.3 reports `PROTOCOL_VERSION_CURRENT = "1.0"` but ships `compat/v0_3`. Confirm which the server should advertise (recommend `0.3.0` card + `1.0`-capable, verify against the spec/site).
- **Transport choice:** JSONRPC vs HTTP+JSON for the Zil server (recommend JSONRPC).
- **Reuse vs hand-roll:** adopt `a2a-sdk`'s server (`a2a.server`) request handlers, or keep FastAPI routes and just match shapes? (Reuse reduces drift risk.)
- **Back-compat window:** keep legacy `/tasks/send` + `/.well-known/agent.json` as deprecated aliases, or hard-cut?

---

## 7. References (pinned, verify on upgrade)
- `tmp/svt/.venv/.../a2a/utils/constants.py` — well-known path, transports, version header.
- `tmp/svt/.venv/.../a2a/compat/v0_3/types.py` — `AgentCard` (L1723), `AgentSkill` (L134), `AgentCapabilities` (L1089); JSON-RPC method literals.
- `tmp/svt/.venv/.../a2a/_base.py` — camelCase alias generator / `populate_by_name`.
- `.venv/.../google/adk/agents/remote_a2a_agent.py` — `RemoteA2aAgent.__init__` (L124), well-known fallback (L51–54).
- `src/zil/commands/serve.py` — shipped server (`_register_a2a_endpoints`, `_load_skill_cards`).
