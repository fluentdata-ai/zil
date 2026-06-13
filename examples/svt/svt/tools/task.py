"""
svt/tools/task.py

Two-phase interactive tools for the VTL agent:

  1. work_on_ticket(issue_key)
     Clones the repo and runs VTA to produce a plan.
     VTL presents the plan to the user for review/corrections.

  2. execute_plan(issue_key)
     Runs VTD on the workspace prepared by work_on_ticket.
     VTL calls this only after the user confirms ("go!", "looks good", etc.)

The TaskRunner instance is kept in a module-level registry so the workspace
survives across turns in the same server process.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from svt.runner import TaskRunner

log = logging.getLogger(__name__)

_runners: dict[str, TaskRunner] = {}


async def work_on_ticket(issue_key: str) -> dict:
    """Clone the repo and run VTA to produce an implementation plan.

    Presents the plan for user review. The user can then ask for corrections
    or say "go!" to trigger execute_plan().

    Args:
        issue_key: Jira issue key (e.g. "INCA-229").

    Returns:
        dict with plan_content (the full plan text) and workspace path.
    """
    from svt.runner import TaskRunner

    issue_key = issue_key.strip().upper()
    log.info("work_on_ticket: planning %s", issue_key)

    try:
        runner = TaskRunner(issue_key)
        _runners[issue_key] = runner
        result = await runner.plan()
        plan_content = result.get("plan_content", "(no plan generated)")
        return {
            "status": "ok",
            "plan_exists": result.get("plan_exists", False),
            "workspace": result.get("workspace", ""),
            "plan": (
                f"\n\n{plan_content}\n\n---\n"
                "Does this plan look good? You can ask for corrections, "
                "or say **go!** to start implementation."
            ),
        }
    except Exception as exc:  # noqa: BLE001
        log.exception("work_on_ticket: plan failed for %s", issue_key)
        return {"status": "error", "error": str(exc), "issue_key": issue_key}


async def execute_plan(issue_key: str) -> dict:
    """Run VTD to implement the plan produced by work_on_ticket().

    Must be called after work_on_ticket() has successfully generated a plan
    and the user has confirmed they want to proceed.

    Args:
        issue_key: Jira issue key (e.g. "INCA-229"). Must match a prior
            work_on_ticket() call in this session.

    Returns:
        dict with agent_response from VTD (branch/PR details).
    """
    issue_key = issue_key.strip().upper()
    log.info("execute_plan: executing %s", issue_key)

    runner = _runners.get(issue_key)
    if runner is None:
        return {
            "status": "error",
            "error": f"No plan found for {issue_key}. Call work_on_ticket('{issue_key}') first.",
        }

    try:
        result = await runner.execute()
        return {"status": "ok", **result}
    except Exception as exc:  # noqa: BLE001
        log.exception("execute_plan: execution failed for %s", issue_key)
        return {"status": "error", "error": str(exc), "issue_key": issue_key}
