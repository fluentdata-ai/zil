---
name: fd-run-tests
description: >
  Runs the project's test suite and reports pass/fail results. Detects
  the test framework from the project config and runs the appropriate
  command. Use after every implementation change before submitting.
license: Apache-2.0
---

# fd-run-tests

## Overview

Use this skill to verify your implementation is correct before submitting.
Always run tests after making changes. If tests fail, fix and re-run.

## Steps

1. Detect the test framework:
   - `pytest` if `pyproject.toml` or `setup.cfg` references pytest
   - `pnpm test` or `pnpm turbo test` if `pnpm-workspace.yaml` exists
   - `npm test` if `package.json` exists with a `test` script (no pnpm)
   - `make test` if `Makefile` has a `test` target
   - Otherwise check `.agents/onboarding.md`
2. Run the test command with `run_shell_command`, e.g.:
   ```
   pnpm turbo test --filter=<changed-package>
   ```
3. Report: total tests, passed, failed, error output.
4. If tests fail, identify the failure and fix the code before proceeding.

## Notes

- Do not skip tests or mark them as expected failures unless the
  onboarding document explicitly allows it.
- If the test suite takes > 5 minutes, run only the tests in the
  modified files first, then run the full suite.
