---
name: fd-explore-repo
description: >
  Systematic repository exploration procedure. Lists directory trees,
  reads key files (README, pyproject.toml, package.json, etc.), and
  produces a structured summary of the codebase layout. Use before
  planning any implementation task.
license: Apache-2.0
---

# fd-explore-repo

## Overview

Use this skill to understand a repository's structure before planning
implementation work. It guides you through a systematic exploration
of the codebase to gather the context needed for accurate planning.

## Steps

1. Read the root listing with `list_files(".")`.
2. Read `README.md` (or `README.rst`) if present.
3. Read the primary package manifest (`pyproject.toml`, `package.json`,
   `pom.xml`, `go.mod`, etc.) to understand the tech stack and deps.
4. List the main source directory (e.g. `src/`, `lib/`, `app/`).
5. Read any `CONTRIBUTING.md` or `DEVELOPMENT.md` for local conventions.
6. Summarize: repo purpose, tech stack, key directories, test framework.

## Notes

- Be surgical — do not read every file. Focus on structure and config.
- Stop exploring once you have enough context to write a complete plan.
