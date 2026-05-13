# Contributing to Zil

Thank you for your interest in contributing to Zil! This guide covers the development setup, testing, and pull request process.

## Development setup

```bash
# Clone the repo
git clone https://github.com/fluentdata-co/zil.git
cd zil

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate

# Install in editable mode with dev dependencies
pip install -e '.[dev,adk,eval]'
```

## Project structure

```
src/zil/
├── cli.py              # CLI entry point (Click)
├── commands/           # CLI command implementations
├── schema/             # Manifest validation
├── packaging/          # Archive builder, SBOM
├── sdk/                # Python SDK (create_agent, guardrails, audit)
│   └── audit/          # Security audit modules
└── templates/          # Project scaffolding templates

tests/                  # pytest test suite
docs/                   # Documentation site (Nextra)
website/                # Marketing site (Next.js)
```

## Running tests

```bash
# Run the full suite
pytest

# Run with coverage
pytest --cov=zil --cov-report=term-missing

# Run a specific test file
pytest tests/test_audit.py

# Run a specific test
pytest tests/test_audit.py::TestGuardrailCoverage::test_full_coverage
```

## Linting

We use [ruff](https://docs.astral.sh/ruff/) for linting:

```bash
ruff check src/ tests/
ruff format --check src/ tests/
```

## Making changes

1. **Fork** the repository and create a branch from `main`.
2. **Write tests** for any new functionality.
3. **Run the test suite** and ensure all tests pass.
4. **Run the linter** and fix any issues.
5. **Open a pull request** with a clear description of the change.

### Commit messages

Use clear, concise commit messages. Examples:

- `Add context window check to zil audit`
- `Fix token estimation for empty persona files`
- `Update guardrails docs with runtime engine API`

### Pull request guidelines

- Keep PRs focused — one feature or fix per PR.
- Include tests for new functionality.
- Update documentation if the change affects user-facing behavior.
- Reference any related issues in the PR description.

## Code style

- Python 3.11+
- Follow existing patterns in the codebase.
- Use type hints.
- Keep functions focused and under ~50 lines where practical.

## Community

- **Slack** — [Join the Zil community](https://join.slack.com/t/zilorg/shared_invite/zt-3xye83sw1-cU3H1Hb_yFbmyBBgbt5VGQ)
- **GitHub Discussions** — [Ask questions](https://github.com/fluentdata-co/zil/discussions)

## License

By contributing, you agree that your contributions will be licensed under the [Apache-2.0 License](LICENSE).
