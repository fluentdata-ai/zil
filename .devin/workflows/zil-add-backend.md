---
description: Add a new framework backend to Zil (e.g., CrewAI, LangGraph, AutoGen) — scaffold backend class, register it, update templates and schema, add optional deps, and write unit tests. Use this when adding a new AI agent framework integration.
---

# Add a New Framework Backend

Scaffold and wire a new `FrameworkBackend` implementation into Zil.

**Reference implementations:**
- ADK backend: `src/zil/sdk/frameworks/adk/backend.py`
- OpenHands backend: `src/zil/sdk/frameworks/openhands/backend.py`
- Protocol definition: `src/zil/sdk/frameworks/base.py`
- Session types: `src/zil/sdk/session.py` (`SessionEvent`, `SessionResponse`, `Session`)

---

## 1. Gather information

Ask the user for:

- **Framework name** (kebab-case, e.g. `crewai`, `langgraph`, `autogen`)
- **SDK package(s)** on PyPI (e.g. `crewai`, `langgraph-sdk`)
- **Key SDK entry points** — the classes/functions the backend will use (e.g. `Agent`, `LLM`, `Tool`)
- **Required env vars** for the framework (e.g. `OPENAI_API_KEY`)
- **Model string format** — how the framework expects model identifiers (e.g. `provider/model-name`)
- **Session/runner model** — how the framework manages conversation state (e.g. session objects, thread IDs, conversation history lists)
- **Event/callback model** — how the framework exposes streaming events during execution (e.g. callbacks, async generators, event streams)

---

## 2. Add optional dependency group

Add a `[<framework>]` optional dep group to `pyproject.toml` under `[project.optional-dependencies]`:

```toml
[project.optional-dependencies]
<framework> = ["<sdk-package>>=<min-version>"]
```

Install it into the local venv:
```bash
cd /Users/jdiaz/wdir/zil && .venv/bin/pip install -e ".[<framework>]"
```

---

## 3. Create the backend module

Create `src/zil/sdk/frameworks/<framework>/__init__.py`:

```python
"""Zil <Framework> backend."""

from .backend import <Framework>Backend

__all__ = ["<Framework>Backend"]
```

Create `src/zil/sdk/frameworks/<framework>/backend.py` implementing the `FrameworkBackend` protocol. Use the ADK and OpenHands backends as reference. The backend MUST implement these methods:

### 3a. Static/config methods

- `name` property — returns the framework registry key (matches `spec.runtime.framework`)
- `wire(spec: AgentSpec) -> WiredAgent` — construct framework-specific agent from neutral spec
- `run_local(agent: WiredAgent, **kwargs)` — run the agent locally
- `deploy_descriptor(agent: WiredAgent, spec: AgentSpec) -> dict` — deployment metadata
- `validate(project_dir: Path, manifest: dict) -> list[CheckResult]` — framework-specific validation checks
- `scaffold_config() -> dict | None` — init template overrides for `zil init --framework`

### 3b. `invoke()` — the core streaming method (CRITICAL)

This is the most important method. It powers `zil serve`, the SSE stream, and the UI's activity feed.

```python
async def invoke(
    self,
    agent: <Framework>WiredAgent,
    message: str,
    *,
    session_id: str | None = None,
    workspace: str | Path | None = None,
) -> AsyncIterator:
```

**It MUST yield `SessionEvent` instances** with these types:

| Event type     | Required fields                    | When to emit                                      |
|----------------|------------------------------------|----------------------------------------------------|
| `tool_call`    | `tool_name`, `args` (dict or None) | Agent decides to call a tool/function               |
| `tool_result`  | `tool_name`, `result` (str or None)| Tool/function returns a result                      |
| `text`         | `text`                             | Agent produces text output (intermediate or final)  |
| `error`        | `text`                             | Any exception during execution                      |
| `done`         | `metadata` (dict)                  | Always yield as the LAST event                      |

**CRITICAL implementation rules:**

1. **Emit ALL event types** — the UI relies on `tool_call` + `tool_result` pairs to show activity segments with running/done status. If you only emit `text`, the UI shows a blank spinner with no visibility.

2. **Study the framework's event model carefully** — each framework exposes events differently:
   - ADK: events have `content.parts[]` with `.function_call` and `.function_response` attributes. Use `event.get_function_calls()` and `event.get_function_responses()` helpers. Do NOT look at `event.actions` — that's metadata only (skip_summarization, state_delta, etc.), not function calls.
   - OpenHands: uses callbacks (`ActionEvent` → tool_call, `ObservationEvent` → tool_result, `MessageEvent` → text, `AgentErrorEvent` → error) with an `asyncio.Queue`.
   - For new frameworks: read the SDK source to find where tool invocations and results appear in the event stream. Don't guess attribute names.

3. **Emit text only from pure-text events** — skip text extraction from events that also contain function_call or function_response parts, to avoid mixing tool metadata with text output.

4. **Multi-agent hierarchies** — if the framework supports sub-agents (like ADK's AgentTool), the runner may yield events from ALL agents in the hierarchy. Emit tool_call/tool_result for every agent, not just the root. The `author` field (if available) can help identify which agent produced each event.

### 3c. Token usage tracking (CRITICAL for cost visibility)

The `done` event MUST include `token_usage` in its `metadata` so that `zil serve`, the Session API, and the composable-app UI can display token consumption. Without this, the UI shows "0 tokens" for every conversation.

**Pattern — accumulate token counts during invoke() and emit in done:**

```python
total_input_tokens = 0
total_output_tokens = 0
total_tokens = 0

async for event in framework_runner.run(...):
    # Extract token usage from the framework's event/response objects
    usage = extract_usage(event)  # framework-specific
    if usage:
        total_input_tokens += usage.input
        total_output_tokens += usage.output
        total_tokens += usage.total
    yield ...  # tool_call, tool_result, text events

# Include token_usage in the done event metadata
done_metadata = {"session_id": logical_sid, ...}
if total_tokens > 0 or total_input_tokens > 0 or total_output_tokens > 0:
    done_metadata["token_usage"] = {
        "input": total_input_tokens,
        "output": total_output_tokens,
        "total": total_tokens,
    }
yield SessionEvent(type="done", metadata=done_metadata)
```

**How each framework exposes token usage:**
- **ADK**: Each `Event` inherits from `LlmResponse` which has `event.usage_metadata` — a `GenerateContentResponseUsageMetadata` with `prompt_token_count`, `candidates_token_count`, `total_token_count`. Accumulate across all events.
- **OpenHands**: After `conversation.arun()`, call `conversation.conversation_stats.get_combined_metrics()` which returns a `Metrics` object with `accumulated_token_usage.prompt_tokens`, `accumulated_token_usage.completion_tokens`, and `accumulated_cost`.
- **New frameworks**: Check the SDK docs for metrics/usage APIs. Common patterns:
  - `response.usage` (OpenAI-style): `prompt_tokens`, `completion_tokens`
  - `response.usage_metadata` (Gemini-style): `prompt_token_count`, `candidates_token_count`
  - `llm.metrics` or `conversation.stats` (aggregated post-run)
  - Callbacks/hooks with per-call usage data

**Cost tracker integration** — if `agent._zil_cost` is set (via `create_agent(enable_cost_tracking=True)`), feed it per-event:

```python
cost_cb = getattr(agent._agent, '_zil_cost', None)
if cost_cb and hasattr(cost_cb, 'record') and usage:
    cost_cb.record(input_tokens=usage.input, output_tokens=usage.output)
```

**The `token_usage` dict keys** are `input`, `output`, `total` (integers). Optionally include `cost` (float, USD) if the framework provides it. The composable-app frontend reads `evt.token_usage.input`, `evt.token_usage.output`, `evt.token_usage.total` from the SSE `done` event — `zil serve` surfaces `metadata.token_usage` at the top level of the SSE payload automatically.

### 3d. Session persistence (CRITICAL for multi-turn)

The `invoke()` method is called ONCE PER MESSAGE. Without caching, each call creates a fresh session and loses conversation history.

**Pattern — cache session state by `session_id`:**

```python
# Class-level cache
_session_cache: dict[str, tuple[Any, ...]] = {}

async def invoke(self, agent, message, *, session_id=None, workspace=None):
    logical_sid = session_id or uuid.uuid4().hex

    if logical_sid in self._session_cache:
        # REUSE existing session — conversation history preserved
        runner, framework_session_id, ... = self._session_cache[logical_sid]
    else:
        # FIRST CALL — create session service, runner, etc.
        runner = ...
        framework_session_id = ...
        self._session_cache[logical_sid] = (runner, framework_session_id, ...)

    # Run with the cached runner + session
    async for event in runner.run(session_id=framework_session_id, message=message):
        yield ...
```

What to cache varies by framework:
- **ADK**: `(InMemorySessionService, Runner, user_id, adk_session_id)` — the Runner and SessionService hold conversation history
- **OpenHands**: `(Conversation, queue_holder)` — the Conversation object persists across turns, queue_holder is a mutable list so the callback always writes to the current invocation's queue
- **New frameworks**: identify what holds conversation state (thread ID, message history list, session object) and cache it

### 3e. `close_session()` — cleanup

```python
def close_session(self, session_id: str) -> None:
    """Release cached resources for a session."""
    entry = self._session_cache.pop(session_id, None)
    if entry is not None:
        # Framework-specific cleanup (close connections, delete temp files, etc.)
        ...
```

Called by `Session.close()`. Must remove the session from the cache and free any framework resources.

### 3f. Key implementation patterns

- **Lazy imports**: Import the framework SDK inside methods, not at module top-level. This prevents import errors when the optional dep isn't installed. Always wrap in try/except ImportError and yield a `SessionEvent(type="error", ...)` if missing.
- **Model resolution**: Create a `resolve_model_<framework>()` helper that maps Zil's LLM provider strings (gemini, openai, anthropic, etc.) to the framework's expected model format.
- **MCP config mapping**: Transform `AgentSpec.mcp_server_configs` to the framework's tool/server format.
- **CheckResult usage**: Use `CheckResult(status="pass"|"warn"|"fail", message="...")` for validation.

---

## 4. Register the backend

Edit `src/zil/sdk/frameworks/__init__.py` — add a lazy-loading try/except block for the new backend, following the existing OpenHands pattern:

```python
try:
    from zil.sdk.frameworks.<framework>.backend import <Framework>Backend
    registry.register(<Framework>Backend())
except Exception:
    pass
```

---

## 5. Update the manifest schema

Edit `src/zil/spec/v1/manifest.schema.json`:

- Add `"<framework>"` to the `framework` enum in `$defs/runtime/properties/framework/enum`

---

## 6. Update scaffold templates

Edit `src/zil/templates/files.py` to add framework-conditional rendering. Files that need conditionals:

1. **`_manifest()`** — Add framework-specific env vars to the `env:` section
2. **`_agent_py()`** — Render framework-specific agent boilerplate (imports, agent setup)
3. **`_requirements()`** — Use `zil-ai[<framework>]` instead of `zil-ai[adk]`
4. **`_module_requirements()`** — Same as above for the module-level requirements
5. **`_persona()`** — Optionally adjust persona template for the framework's agent style
6. **`_instructions()`** — Optionally adjust instructions for framework conventions

Pattern for conditionals:
```python
if cfg.framework == "<framework>":
    # framework-specific content
else:
    # existing adk content
```

---

## 7. Verify SSE stream integration

The SSE stream in `src/zil/commands/serve.py` serializes `SessionEvent` fields into JSON for the frontend. Verify your backend's events work correctly by checking:

1. **All fields are serialized** — `serve.py` sends: `type`, `text`, `tool_name`, `args`, `result`, `metadata`. If your backend populates a new field on `SessionEvent`, add it to the SSE payload in `serve.py`.

2. **Frontend parser compatibility** — The frontend parser (`packages/zil-core/src/lib/parse-agent-events.ts`) expects:
   - `tool_call` events with `tool_name` (string) and optional `args` (object) → creates a "running" activity item
   - `tool_result` events with `tool_name` (string) matching a prior `tool_call` → marks that activity as "done"
   - `text` events with `text` (string) → appends to the current segment
   - `error` events with `text` (string) → creates an error activity item
   - `done` events → marks the response as complete

3. **Custom agent entry points** — If the framework supports custom agent modules (like ADK's `agent.py` with `root_agent`), `zil serve` will auto-detect `<project_dir>/<agent_name>/agent.py` and import its `root_agent` attribute. See `_load_agent()` in `serve.py`. Your backend's `WiredAgent` wrapper must be returned from `_wrap_raw_agent()` in `session.py` — add a clause there for your framework's agent class.

---

## 8. Write unit tests

Create `tests/test_<framework>.py` with comprehensive tests. Use `tests/test_openhands.py` as the reference. Required test classes:

1. **TestRegistration** — Backend registers in the global registry
2. **TestWire** — `wire()` produces a WiredAgent with correct config (mock SDK imports)
3. **TestRunLocal** — `run_local()` calls the SDK correctly (mock SDK)
4. **TestValidate** — Validation checks pass/warn/fail appropriately
5. **TestDeployDescriptor** — Returns correct deployment metadata
6. **TestScaffoldConfig** — Returns expected template overrides
7. **TestInvoke** — `invoke()` yields correct `SessionEvent` sequence: tool_call → tool_result → text → done. Verify multi-turn by calling invoke twice with the same session_id and confirming the second call reuses cached state. Verify the `done` event includes `metadata.token_usage` with `input`, `output`, `total` keys.
8. **TestCloseSession** — `close_session()` removes cached state
9. **TestCLIInit** — `zil init --framework <name> --non-interactive --skip-install` produces correct files
10. **TestSchema** — Framework is accepted in the manifest schema enum

Mock pattern for SDK imports:
```python
@pytest.fixture(autouse=True)
def mock_sdk(monkeypatch):
    fake_module = types.ModuleType("<sdk_package>")
    # Add fake classes/functions as needed
    monkeypatch.setitem(sys.modules, "<sdk_package>", fake_module)
```

Run the tests:
// turbo
```bash
cd /Users/jdiaz/wdir/zil && .venv/bin/python -m pytest tests/test_<framework>.py -q --tb=short
```

---

## 9. Run full test suite

Verify no regressions:
// turbo
```bash
cd /Users/jdiaz/wdir/zil && .venv/bin/python -m pytest tests/ -q --tb=short
```

All tests must pass. If any fail, fix them before proceeding.

---

## 10. Final checklist

Present this checklist to the user:

- [ ] `src/zil/sdk/frameworks/<framework>/__init__.py` exists
- [ ] `src/zil/sdk/frameworks/<framework>/backend.py` implements all protocol methods
- [ ] `invoke()` yields all 5 event types: `tool_call`, `tool_result`, `text`, `error`, `done`
- [ ] `invoke()` emits `token_usage` in the `done` event metadata (`input`, `output`, `total`)
- [ ] `invoke()` feeds `CostCallback` (if attached) with per-event token counts
- [ ] `invoke()` persists session state across calls (multi-turn works)
- [ ] `close_session()` cleans up cached session state
- [ ] `_wrap_raw_agent()` in `session.py` handles the framework's agent class
- [ ] Backend registered in `src/zil/sdk/frameworks/__init__.py`
- [ ] Schema updated with new framework name
- [ ] `pyproject.toml` has `[<framework>]` optional dep group
- [ ] Scaffold templates render correctly for the new framework
- [ ] `tests/test_<framework>.py` covers registration, wire, invoke, session persistence, close_session, validate, scaffold, CLI init, and schema
- [ ] Full test suite passes with no regressions
