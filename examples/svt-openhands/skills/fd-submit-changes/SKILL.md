---
name: fd-submit-changes
description: >
  Creates a feature branch, stages all changes, commits with a
  conventional commit message, pushes the branch, and opens a GitHub
  pull request. Use at the end of every implementation task after
  all tests pass.
license: Apache-2.0
---

# fd-submit-changes

## Overview

Use this skill to submit your implementation as a pull request. Follow
these steps exactly — do not improvise branch names or commit formats.

## Steps

1. Determine the Jira issue key (e.g. `PIP-123`) from context.
2. Create and switch to a feature branch:
   ```
   git checkout -b feat/PIP-123-short-description
   ```
   Branch naming: `feat/<KEY>-<3-5-word-slug>` (all lowercase, hyphens).
3. Stage all changes:
   ```
   git add -A
   ```
4. Commit with a conventional commit message:
   ```
   git commit -m "feat(PIP-123): <imperative short description>"
   ```
5. Push the branch:
   ```
   git push origin HEAD
   ```
6. Open a pull request using `gh pr create`:
   ```
   gh pr create --title "feat(PIP-123): <description>" \
     --body "Closes PIP-123\n\n<summary of changes>" \
     --base dev
   ```
7. Report the PR URL in your final answer.

## Notes

- Never use `--force` push.
- If `gh` is not available, report the branch name and ask a human to
  open the PR manually.
- Prefer running validations (tests, linters) before calling this skill.
  If the environment prevents running them (missing binary, network, etc.),
  submit anyway and note the skipped validations in the PR body.
