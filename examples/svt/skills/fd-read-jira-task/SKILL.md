---
name: fd-read-jira-task
description: >
  Reads a Jira task and all linked issues, returning a structured
  summary including title, description, acceptance criteria, comments,
  linked epics, and sub-tasks. Use at the start of every planning session.
license: Apache-2.0
---

# fd-read-jira-task

## Overview

Use this skill to fully understand a Jira task before planning or
implementing anything. It ensures you gather all relevant context
including linked issues, comments, and acceptance criteria.

## Steps

1. Use the `get_issue` MCP tool to fetch the issue by key.
2. Extract: summary, description, issue type, priority, status, assignee.
3. Check the `description` field for acceptance criteria sections.
4. Use `search_issues` with a JQL like `issue in linkedIssues("KEY")` to fetch linked issues if needed.
5. Return a structured summary with all extracted information.

## Notes

- If the Jira MCP tool is unavailable, report the error and proceed
  with only the issue key as context.
- Do not modify the Jira issue — this is a read-only skill.
