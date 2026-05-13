# hello-agent

A minimal Zil reference agent demonstrating identity composition, runtime guardrails, and the standard project layout.

## Quick start

```bash
# From the repo root
cd examples/hello-agent

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set up your API key
cp hello_agent/.env.example hello_agent/.env
# Edit hello_agent/.env with your Gemini API key

# Validate the project
zil validate

# Run a security audit
zil audit

# Run the agent interactively
zil run

# Or start the ADK web UI
zil web
```

## Project structure

```
hello-agent/
├── manifest.yaml              # Agent manifest (Zil v1 schema)
├── hello_agent/               # ADK agent module
│   ├── __init__.py
│   ├── agent.py               # Agent entry point with example tool
│   └── .env.example           # API key template
├── adapters/                  # LLM and embedding configuration
│   ├── llm.yaml
│   └── embed.yaml
├── identity/                  # Agent identity files
│   ├── persona.md             # Who the agent is
│   ├── instructions.md        # How the agent behaves
│   └── guardrails.yaml        # Runtime-enforced rules
└── requirements.txt
```

## What this demonstrates

- **Identity composition** — persona, instructions, and guardrails are composed into a single system prompt by `zil.create_agent()`
- **Runtime guardrails** — prompt injection detection and PII scanning are enforced at runtime via `enable_guardrails=True`
- **Declarative manifest** — the agent is fully described by `manifest.yaml` and validated with `zil validate`
- **Security audit** — run `zil audit` to check for injection vulnerabilities, identity hardening issues, and guardrail coverage gaps

## Learn more

- [Documentation](https://getzil.dev/docs)
- [CLI Reference](https://getzil.dev/docs/cli)
- [Guardrails Guide](https://getzil.dev/docs/identity/guardrails)
