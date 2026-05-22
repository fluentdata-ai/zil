# Changelog

All notable changes to the `zil-ai` package will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.16] — 2026-05-22

### Added

- **`spec.runtime.dependencies`** — new manifest section for declarative non-Python runtime dependencies. Supports types: `apt`, `apt-nodesource` (Node.js via NodeSource), `apt-gh` (GitHub CLI via official repo), `npm-global` (global npm packages), and `pip`. Zil generates ordered `RUN` stanzas in the Dockerfile with correct installation order (apt → nodesource → gh → pip → npm-global).
- **Dockerfile auto-regeneration on `zil web --docker`** — regenerates the `Dockerfile` from `manifest.yaml` before `docker build`, ensuring `spec.runtime.dependencies` and `spec.tools.host_dependencies` are always reflected in the container without a static `Dockerfile`.
- **`ProjectContext.runtime_deps`** — new SDK context field exposing parsed `spec.runtime.dependencies` entries.
- **`zil validate` runtime dep checks** — warns on unknown dependency types and on `npm-global` entries declared without a preceding `apt-nodesource` (Node.js) entry.
- **Skills convention** — `spec.skills` for per-agent skill allowlists; skills live under `skills/` and are discoverable at runtime. `zil init --skills` scaffolds skill stubs.

## [0.1.15] — 2026-05-21

### Added

- **Cloud SQL auto-wiring** — `zil deploy` auto-detects the Cloud SQL instance from `SESSION_DB_URI` and attaches it via `--add-cloudsql-instances`, eliminating the need to pass it manually.
- **`zil deploy --output json`** — machine-readable deploy result with service URL, webhook endpoints, HITL endpoint, and Cloud SQL instance. Suitable for CI pipelines.
- **Multi-agent scaffolding (`zil init --agents`)** — scaffold multi-agent projects with per-agent identity directories, MCP server assignments, and a root orchestrator wired to sub-agents.
- **Webhook service scaffolding (`zil init --service webhook`)** — generates `app.py` (FastAPI) and `runner.py` for webhook-driven agents with HITL support.
- **HITL (Human-in-the-Loop) SDK** — `zil.sdk.hitl` module with `request_human_input` / `resolve_human_input` for pausing agent execution and resuming on human callback.
- **Multi-agent schema validation** — `zil validate` checks `spec.agents` entries: identity directories, LLM model references, and MCP server name references.
- **`spec.agents` manifest section** — declare sub-agents with name, role, identity, description, LLM config, and tool assignments.

## [0.1.14] — 2026-05-20

### Added

- **Generic `tools/` convention** — external tool dependencies (MCP servers, CLI tools, binaries) live under `tools/{name}/` in the project directory. Bundled into archives and Docker images during pack/deploy.
- **`entry_point` field** — new optional field in `mcpServer` schema specifying the tool's entry point relative to its source directory (e.g. `dist/index.js`, `server.py`). Replaces hardcoded path assumptions.
- **`.bundleignore` support** — per-tool exclusion file to control what gets bundled. Extends default exclusions (`.git/`, `src/`, `tests/`, `docs/`, `__pycache__/`, etc.).
- **Centralized Dockerfile generation** — new `packaging/dockerfile.py` module used by `zil init`, `zil web --docker`, and `zil deploy`. Single source of truth for container configuration.
- **`zil validate` source/entry_point checks** — validates source directory exists, entry_point file is present, and warns if source is outside the `tools/` convention.
- **`zil web --docker` loads `.env.local`** — Docker runs now pick up both `.env` and `.env.local` files for complete environment configuration.

### Fixed

- **MCP path resolution in containers** — MCP server paths now resolve relative to the project root (where `tools/` lives) instead of the module subdirectory.
- **`.dockerignore` no longer excludes `tools/*/dist/`** — changed `dist/` to `/dist/` so only the project-root dist directory is ignored, preserving tool build artifacts.

## [0.1.13] — 2026-05-19

### Added

- **MCP server integration** — declare MCP servers in `spec.tools.mcp_servers` with stdio/SSE transport, env var resolution, tool filters, and timeouts.
- **`host_dependencies`** — declare system packages (nodejs, git, uv) needed by MCP servers; installed in container during deploy.
- **`--mcp` preset for `zil init`** — scaffolds MCP configuration (filesystem, git, or custom presets).
- **MCP source bundling** — `source` field on mcpServer; `zil pack`/`zil deploy` bundles tool source under `tools/{name}/`.
- **MCP permission audit** — `zil audit` flags over-permissioned servers, risky host deps, and long timeouts.
- 34 MCP tests; 329 total tests.

## [0.1.12] — 2026-05-15

### Added

- **`zil deploy --allow-unauthenticated`** — new flag to allow unauthenticated access to the Cloud Run service. Passes `--allow-unauthenticated` to `gcloud run deploy` via the `--` separator. Works with both direct deploy and `--from` artifact deploy.

## [0.1.11] — 2026-05-13

### Added

- **Token-based cost tracking** — new `spec.cost` manifest section for declaring token budgets (`max_tokens_per_request`, `max_tokens_per_session`, `alert_threshold_pct`, `track_by_model`). No USD — Zil tracks raw token counts; dollar pricing is delegated to the future Zil Runtime.
- **`zil.cost` singleton** — module-level cost tracker accessible as `zil.cost.total_tokens`, `zil.cost.by_model`, `zil.cost.budget_remaining`, `zil.cost.reset()`.
- **`CostTracker` class** — thread-safe token usage accumulator with per-request and per-session budget enforcement. Returns `CostResult` (allowed/warned/blocked) on each recording.
- **`CostCallback`** — ADK-compatible callback that extracts usage metadata from LLM responses (Gemini, OpenAI, Anthropic) and feeds it to the tracker. Emits OTel span attributes (`llm.usage.input_tokens`, `llm.usage.output_tokens`, `llm.usage.model`).
- **`create_agent(enable_cost_tracking=True)`** — automatically initializes cost tracking from `spec.cost` and attaches the callback. Access via `agent._zil_cost`.
- **`zil validate` cost checks** — warns if `spec.cost` is absent, flags inconsistencies (session < request budget, exceeds resource_limits).
- **`zil inspect` cost display** — shows budget configuration from archived manifests.
- **`zil pack --sign`** — signs the `.zil` archive using cosign (keyless/Sigstore OIDC by default). Produces a Sigstore `.bundle` file alongside the archive.
- **`zil pack --sign --key <path>`** — key-based cosign signing for CI environments.
- **`zil inspect --verify`** — verifies the cosign signature of a `.zil` archive (keyless or `--key`).
- **`zil push` signature attachment** — automatically pushes the `.bundle` alongside the OCI artifact when present.
- **`zil init` template** — new commented-out `spec.cost` section in scaffolded `manifest.yaml`.
- 45 new tests (`test_cost.py`, `test_signing.py`); 295 total tests.

## [0.1.10] — 2026-05-12

### Added

- **`zil audit` command** — agent-native security audit focused exclusively on LLM-specific attack surfaces. Produces a Rich-formatted report (or `--format=json` for CI) with exit codes for pass/warn/critical.
- **Guardrail coverage scoring** — scores coverage across 5 dimensions: injection detection, PII output, PII input, output constraints, denied topics.
- **Injection resilience testing** — runs 20 adversarial prompts through the `GuardrailEngine` across 6 attack categories (ignore instructions, DAN, system prompt extraction, tag injection, rule override, instruction forget).
- **Output leakage scan** — checks if persona, instructions, or system prompt content could leak through output undetected by guardrail filters.
- **Indirect injection surface analysis** — AST-scans tool functions for external data ingestion (HTTP, DB, file reads, subprocesses) and flags tools whose return values bypass guardrail checks.
- **Instruction consistency check** — detects contradictions between permissive persona language and restrictive guardrails that create social-engineering gaps.
- **Context window risk assessment** — measures system prompt token usage as a percentage of model context window and warns if adversarial context stuffing is feasible.
- **Identity hardening review** — checks persona.md/instructions.md for anti-patterns (vague boundaries, generic assistant persona, missing refusal language).
- **`--fix` flag** — appends actionable remediation suggestions to each finding.
- Strengthened built-in injection patterns (10 patterns, up from 8): added instruction extraction and task override detection.
- 34 new tests (`test_audit.py`); 250 total tests.

## [0.1.9] — 2026-05-12

### Added

- **Runtime Guardrail Engine** — new `zil.sdk.guardrails` module with `GuardrailEngine` class that enforces rules at runtime via `check_input()` and `check_output()` methods returning structured `GuardrailResult` objects.
- **Built-in prompt injection detection** — 8 regex patterns detecting common jailbreak techniques (ignore instructions, DAN, system prompt extraction, XML/instruction tag injection, rule overrides).
- **Built-in PII detection** — blocks SSN and credit card patterns in agent output by default; optionally scans input too.
- **Custom blocked patterns** — define regex patterns in `guardrails.yaml` targeting input, output, or both with configurable severity (`block` / `warn` / `log`).
- **Denied topics** — keyword-based input blocking for restricted subject areas.
- **Output constraints** — configurable `max_response_length` enforcement.
- **OTel guardrail spans** — `GuardrailCallback` emits `guardrail.check.input` / `guardrail.check.output` spans with violation attributes when a tracer is available.
- **`zil validate` guardrail checks** — validates `guardrails.yaml` structure, counts enforceable rules, checks regex validity, and warns on missing output protections.
- **`zil create_agent(enable_guardrails=True)`** — guardrail engine auto-loads from `identity/guardrails.yaml` and attaches to the agent as `agent._zil_guardrails`.
- **Updated `zil init` templates** — scaffolded `guardrails.yaml` now includes the runtime-enforceable format with `detection`, `blocked_patterns`, `denied_topics`, and `output_constraints` sections.
- 46 new tests (`test_guardrails.py`); 216 total tests.

## [0.1.8] — 2026-05-11

### Added

- **`spec.env` declarations** — agents can declare required environment variables in `manifest.yaml` with `name`, `description`, `required`, `default`, and `secret` fields.
- **`zil deploy --env-file`** — provide a dotenv file for automated deploys; falls back to interactive prompts (secrets masked) when no file is given.
- **`zil.config` SDK object** — dict-like runtime access to declared env vars from agent code (`zil.config["VAR_NAME"]`). Resolves from `os.environ` with defaults; raises `MissingConfigError` for missing required vars.
- **Auto-load `.env.local`** — `zil.config` loads `.env` and `.env.local` from the project and module directories into `os.environ` at startup (never overrides existing values), so local dev works without manual env setup.
- **Pack env cross-check** — `zil pack` scans `.env`/`.env.local` files against `spec.env` declarations. Fails on undeclared vars (drift detection), warns on missing vars, and records coverage in `BUILD_META.json`.
- **`zil inspect` env coverage** — shows declared env var count, secret count, and local resolution coverage from the archive.
- **`zil validate` env checks** — reports declared env var count, warns if `spec.env` is missing, and cross-references adapter `env_var` references.
- **`zil init` env templates** — scaffolded manifests include `spec.env` with the LLM provider's API key pre-declared.
- 34 new tests (`test_env.py`, `test_pack.py::TestEnvCoverage`); 170 total tests.

### Changed

- **Deploy env injection** — environment variables are passed to Cloud Run via `gcloud` `--set-env-vars` after the `--` separator (fixes compatibility with ADK's deploy command).
- **`load_project` walks up** — when `project_dir` points to a module subdirectory without `manifest.yaml`, the SDK walks up to find the project root (fixes `zil run` in local dev).
- **Archive size display** — uses KB for archives under 1 MB (previously showed `0.0 MB`).

## [0.1.7] — 2026-05-08

### Added

- **`zil pack` — real archive builder** — validates the project, runs evals (gate), generates a CycloneDX 1.5 SBOM, and creates a `.zil` tar.gz archive with manifest, identity, adapters, evals, observability, code, SBOM, and eval results.
- **`zil inspect` — archive inspector** — reads `.zil` archives and displays a rich summary with component table, SBOM dependency count, and eval scores. Supports `--show` (print specific file) and `--json` (machine-readable output).
- **`zil push` command** — push `.zil` archives to any OCI-compatible registry (Artifact Registry, GHCR, ECR, Docker Hub) using ORAS.
- **`zil deploy --from`** — deploy from a `.zil` archive or OCI registry reference instead of a local project directory.
- **SBOM generation** (`zil.packaging.sbom`) — generates CycloneDX 1.5 SBOMs from `requirements.txt`.
- **`oras`** added as a core dependency for registry operations.
- 24 new packaging tests (`tests/test_pack.py`); 135 total tests.

### Changed

- **`zil init` options trimmed** — removed `--framework`, `--language`, `--target`, and `--eval-framework` options (only supported values were used). Only `--llm` remains as a choice.
- **Eval runner uses persistent event loop** — suppresses noisy Google GenAI async client cleanup errors during eval runs.
- CLI now has nine commands (added `push`).
- CLI docs updated with `push`, `deploy --from`, and revised `init`/`pack`/`inspect` sections.

### Removed

- **`--no-sign` flag from `zil pack`** — cosign signing deferred to a future release.
- **`[registry]` optional extra** — `oras` is now a core dependency.

## [0.1.6] — 2026-05-07

### Added

- **`zil web --docker`** — build and run the agent in a Docker container with the ADK web UI for local testing.
- **Grafana OTEL-LGTM observability stack** — `zil web --docker --trace` starts a `grafana/otel-lgtm` container providing traces (Tempo), metrics (Mimir), and logs (Loki) with Grafana UI at `http://localhost:3000`.
- **Module-level `requirements.txt`** — `zil init` now generates a `requirements.txt` inside the agent module directory, required by ADK's Cloud Run deployer.

### Changed

- **Eval gate blocks deployment** — `zil deploy` now exits with error when evals fail (previously warn-only). Use `--skip-evals` to override.
- **Deploy copies project context** — `manifest.yaml`, `identity/`, `adapters/`, and `observability/` are automatically included in Cloud Run deploys so `zil.create_agent()` works at runtime.
- **`create_agent()` auto-detects project dir** — falls back to caller's file location instead of CWD when `project_dir` is not specified.
- **Agent template uses explicit `project_dir`** — `Path(__file__).parent` ensures Cloud Run compatibility without requiring the latest SDK version.

### Removed

- **`--local` flag from `zil deploy`** — replaced by `zil web --docker`.
- **Jaeger integration** — replaced by Grafana OTEL-LGTM which supports traces, metrics, and logs in a single container.

## [0.1.5] — 2026-05-06

### Added

- **`zil deploy` command** — deploy agents locally (Docker) or to Google Cloud Run in one step.
- **Local deployment mode** (`--local`) — builds Docker image and runs the agent container locally with the ADK web UI.
- **Jaeger auto-start** — `zil deploy --local --trace` automatically starts a Jaeger all-in-one container (UI at `:16686`, OTLP at `:4318`) and configures the agent to export spans.
- **Cloud Run deployment** — wraps `adk deploy cloud_run` with project/region resolution from CLI flags, environment variables, or `gcloud config`.
- **Cloud Trace integration** — `zil deploy --trace` passes `--otel_to_cloud` to Cloud Run for native GCP observability.
- **Pre-deploy eval gate** — runs eval suite before deploying; warns on failure but does not block (use `--skip-evals` to skip entirely).
- 15 new tests for deploy command (109 total tests).

### Changed

- CLI now has eight commands (added `deploy`).
- Getting-started guide updated with deploy workflow (replaces `zil pack` section).
- DeepEval added to "composes with" across all documentation and website surfaces.

## [0.1.4] — 2026-05-05

### Added

- **`zil eval` command group** — refactored from a single command into four subcommands: `run`, `add`, `record`, and `generate`.
- **`zil eval add`** — interactively create eval cases by chatting with the agent; cases are saved to YAML and auto-registered in the suite.
- **`zil eval record`** — record a full chat session with the agent and convert selected turns into eval cases, with auto-detected keywords.
- **`zil eval generate`** — use the judge LLM to synthesize eval cases from agent identity files (persona, instructions, guardrails). Supports `--count`, `--category`, and `--no-review`.
- **Per-metric thresholds** — `metric_thresholds` in `evals/config.yaml` lets you set custom pass thresholds per DeepEval metric.
- **Execution controls** — `execution.concurrency`, `execution.retries`, and `execution.timeout` in `evals/config.yaml` for parallel eval runs and retry logic.
- **Eval case writer** (`zil.sdk.eval.writer`) — programmatic API for appending cases to group files and auto-registering groups in suite YAML.
- **Eval case generator** (`zil.sdk.eval.generator`) — LLM-powered case synthesis with support for Gemini, OpenAI, and Anthropic judge providers.
- **Lazy judge model resolution** — the DeepEval adapter now defers judge model initialization until LLM metrics are actually needed, avoiding import errors for deterministic-only evals.
- 14 new tests for writer, config enhancements, generator parsing, and keyword extraction (46 eval tests total).

### Changed

- **`zil eval` is now a command group** — use `zil eval run` instead of `zil eval` to run suites (no backward compatibility needed; the command was unused).
- **DeepEval adapter** stores `_config` for lazy judge model creation; accepts `_metric_thresholds` from engine config.
- Eval runner uses `ThreadPoolExecutor` for concurrent case evaluation with configurable retries and timeout.
- Eval docs page expanded with full documentation for all subcommands and new config fields.
- CLI reference docs updated to reflect the eval command group structure.

## [0.1.3] — 2026-05-05

### Added

- **OpenTelemetry tracing integration** — `zil run --trace` exports spans to any OTLP-compatible backend (Jaeger, Cloud Trace, Datadog, etc.); `zil run --trace-console` prints spans to stderr for local development.
- **`setup_telemetry()` and `setup_console_telemetry()`** — new SDK functions for programmatic tracing control, exported from `zil.sdk`.
- **`enable_telemetry` parameter** on `zil.create_agent()` — automatically configures OTel tracing from `observability/config.yaml` (default: `True`).
- **Observability config loading** — `ProjectContext` now reads `observability/config.yaml` when referenced in the manifest.
- **`agent.txt`** — agent-friendly documentation at `getzil.dev/agent.txt` and `getzil.dev/docs/agent.txt`.
- `opentelemetry-exporter-otlp-proto-http>=1.20.0` added to `[adk]` optional extra.
- 10 new tests for telemetry setup and observability config loading.

### Changed

- **Observability config template** — uses standard `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` env var (replaces `OTEL_COLLECTOR_URL`), adds `resource_attributes` section.
- **`.env.example` template** — references `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` (commented out by default).
- **`--trace-console` runs in-process** — uses ADK's `run_cli` directly so the `ConsoleSpanExporter` is active during agent execution.
- Observability docs page fully rewritten with dev/prod guide, SDK integration, and CLI flags.
- CLI reference docs updated with `--trace` and `--trace-console` flags for `zil run` and `zil web`.

## [0.1.2] — 2026-05-04

### Added

- **`zil run` command** — runs the agent interactively by wrapping `adk run` with automatic module detection from `manifest.yaml`.
- **`zil web` command** — starts the ADK web UI for testing, wrapping `adk web` with configurable port.
- **Gemini (AI Studio) provider** — new default LLM provider using `GOOGLE_API_KEY`, with link to API key generation in `.env.example`.
- Gemini embedding adapter support (`text-embedding-004`).

### Changed

- **Project scaffold restructured** — `agent.py` now lives inside a Python package directory (`{module_name}/agent.py` with `__init__.py`) for ADK compatibility.
- **Default LLM provider** changed from `anthropic` to `gemini` for easier onboarding.
- `.env.example` moved into the agent module directory (ADK loads `.env` from there).
- Vertex AI `llm.yaml` template now includes `GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_LOCATION` env var references.
- Dockerfile `CMD` updated to use `python -m {module_name}.agent`.
- README template updated with new project layout and `zil run`/`zil web` commands.

### Fixed

- **Agent naming error** — kebab-case manifest names (e.g., `qbo-bookkeeper`) are now automatically converted to snake_case (`qbo_bookkeeper`) for ADK's `LlmAgent`, fixing `pydantic ValidationError`.
- **`adk run` directory error** — agent code now lives in a proper Python package, fixing `Directory does not exist` errors.

## [0.1.1] — 2026-05-02

### Added

- **SDK layer** (`zil.create_agent()`) — reads `manifest.yaml`, identity files, and adapter config, then wires them into an ADK `LlmAgent` automatically.
- **Auto-install dependencies** — `zil init` now creates a `.venv` and installs `requirements.txt` after scaffolding.
- **Model resolution** — maps adapter config (Anthropic, OpenAI, Vertex) to ADK-compatible model strings via LiteLLM prefix convention.
- **Identity composition** — persona, instructions, and guardrails are merged into a single structured instruction for the LLM.
- 20 new SDK tests (`tests/test_sdk.py`).
- `[adk]` optional dependency extra in `pyproject.toml`.

### Changed

- `agent.py` template now uses `zil.create_agent(tools=[])` instead of a stub.
- `requirements.txt` template includes `zil-ai[adk]` instead of commented-out ADK.
- Sdist excludes `artifacts/`, `docs/`, `website/`, `.windsurf/` (85 MB → 17 KB).

### Fixed

- Lint cleanup across `commands/`, `templates/`, `schema/` (ruff UP037, E501, E402, F821).

## [0.1.0] — 2026-04-30

### Added

- Initial release.
- CLI with four commands: `zil init`, `zil validate`, `zil pack` (stub), `zil inspect` (stub).
- `zil init` scaffolds 18 files: manifest, identity, adapters, evals, observability, Dockerfile, CI pipeline, README.
- `zil validate` checks manifest schema + file structure.
- JSON Schema for Zil v1 manifest (`spec/v1/manifest.schema.json`).
- 15 CLI tests.

[0.1.16]: https://github.com/fluentdata-co/zil/compare/v0.1.15...v0.1.16
[0.1.15]: https://github.com/fluentdata-co/zil/compare/v0.1.14...v0.1.15
[0.1.14]: https://github.com/fluentdata-co/zil/compare/v0.1.13...v0.1.14
[0.1.13]: https://github.com/fluentdata-co/zil/compare/v0.1.12...v0.1.13
[0.1.12]: https://github.com/fluentdata-co/zil/compare/v0.1.11...v0.1.12
[0.1.11]: https://github.com/fluentdata-co/zil/compare/v0.1.10...v0.1.11
[0.1.10]: https://github.com/fluentdata-co/zil/compare/v0.1.9...v0.1.10
[0.1.9]: https://github.com/fluentdata-co/zil/compare/v0.1.8...v0.1.9
[0.1.8]: https://github.com/fluentdata-co/zil/compare/v0.1.7...v0.1.8
[0.1.7]: https://github.com/fluentdata-co/zil/compare/v0.1.6...v0.1.7
[0.1.6]: https://github.com/fluentdata-co/zil/compare/v0.1.5...v0.1.6
[0.1.5]: https://github.com/fluentdata-co/zil/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/fluentdata-co/zil/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/fluentdata-co/zil/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/fluentdata-co/zil/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/fluentdata-co/zil/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/fluentdata-co/zil/releases/tag/v0.1.0
