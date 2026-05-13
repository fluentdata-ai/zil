<div align="center">

# Zil

**A framework for production AI agents.**

[![PyPI](https://img.shields.io/pypi/v/zil-ai?color=e8c87a&style=flat-square)](https://pypi.org/project/zil-ai/)
[![Python](https://img.shields.io/pypi/pyversions/zil-ai?style=flat-square)](https://pypi.org/project/zil-ai/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue?style=flat-square)](LICENSE)
[![Slack](https://img.shields.io/badge/Slack-Join%20Community-4A154B?style=flat-square&logo=slack)](https://join.slack.com/t/zilorg/shared_invite/zt-3xye83sw1-cU3H1Hb_yFbmyBBgbt5VGQ)

[Documentation](https://getzil.dev/docs) · [Getting Started](https://getzil.dev/docs/getting-started) · [CLI Reference](https://getzil.dev/docs/cli) · [Community Slack](https://join.slack.com/t/zilorg/shared_invite/zt-3xye83sw1-cU3H1Hb_yFbmyBBgbt5VGQ)

</div>

---

Zil composes with [ADK](https://google.github.io/adk-docs/), [A2A](https://google.github.io/A2A/), [MCP](https://modelcontextprotocol.io/), [DeepEval](https://github.com/confident-ai/deepeval), and [OpenTelemetry](https://opentelemetry.io/) to provide a declarative manifest format and CLI for building, validating, auditing, packaging, and deploying AI agents.

## Install

```bash
pip install zil-ai
```

For agent creation with ADK:

```bash
pip install 'zil-ai[adk]'
```

## Quick start

```bash
# Scaffold a new agent project
zil init my-agent
cd my-agent && source .venv/bin/activate

# Validate the project
zil validate

# Security audit
zil audit --fix

# Run the agent interactively
zil run

# Or start the ADK web UI
zil web
```

## Commands

| Command | Description |
|---------|-------------|
| `zil init` | Scaffold a new agent project |
| `zil validate` | Validate project against the manifest schema |
| `zil audit` | Agent-native security audit (injection, leakage, identity hardening) |
| `zil eval run` | Run evaluation suites |
| `zil eval generate` | LLM-powered eval case synthesis |
| `zil run` | Run the agent interactively |
| `zil web` | Start the ADK web UI for testing |
| `zil pack` | Build a versioned `.zil` archive |
| `zil push` | Push archives to an OCI-compatible registry |
| `zil deploy` | Deploy to Google Cloud Run with eval gating |

## SDK

```python
import zil

root_agent = zil.create_agent(
    tools=[],              # your tool functions
    enable_guardrails=True, # runtime guardrail engine
    enable_telemetry=True,  # OpenTelemetry tracing
)
```

See the [SDK Reference](https://getzil.dev/docs/sdk) for the full API.

## Example

The [`examples/hello-agent`](examples/hello-agent) directory contains a minimal reference agent you can run immediately:

```bash
cd examples/hello-agent
pip install -r requirements.txt
zil validate && zil audit && zil run
```

## Community

- **Slack** — [Join the Zil community](https://join.slack.com/t/zilorg/shared_invite/zt-3xye83sw1-cU3H1Hb_yFbmyBBgbt5VGQ) for questions, feedback, and discussion
- **GitHub Discussions** — [Ask questions and share ideas](https://github.com/fluentdata-co/zil/discussions)
- **Issues** — [Report bugs or request features](https://github.com/fluentdata-co/zil/issues)

## Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, testing, and PR guidelines.

## License

[Apache-2.0](LICENSE)

---

<sub>Built by <a href="https://fluentdata.ai">FluentData</a></sub>
