---
name: fd-format-code
description: >
  Runs the project's code formatter and linter (ruff, black, isort, etc.)
  and reports any remaining issues. Use before committing to ensure
  code style compliance.
license: Apache-2.0
---

# fd-format-code

## Overview

Use this skill to ensure code style compliance before committing. It
detects the formatter from project config and runs it automatically.

## Steps

1. Detect the formatter:
   - Check `pyproject.toml` for `[tool.ruff]`, `[tool.black]`, `[tool.isort]`
   - Check `.ruff.toml`, `setup.cfg`, `.flake8`
2. Run the formatter with `run_shell_command`:
   - Ruff (preferred): `ruff check --fix . && ruff format .`
   - Black + isort: `isort . && black .`
3. Run the linter in check mode to confirm no remaining issues:
   - `ruff check .`
4. If there are unfixable lint errors, report them and do not proceed
   with submission until they are resolved.

## Notes

- Do not change formatter config files — only run the existing config.
- If no formatter is configured, skip this skill and note the absence
  in your final answer.
