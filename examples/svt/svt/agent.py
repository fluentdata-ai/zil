"""
svt/agent.py

Builds the VTL root agent via zil.create_agent(), then injects filesystem
and shell tools directly onto the VTA and VTD sub-agents.

This demonstrates zil's SDK extensibility: manifest.yaml handles model
selection, identity loading, MCP wiring, and SkillToolset — while the
agent module adds inline Python tools post-hoc by mutating the sub-agent
tool lists returned by zil's _build_sub_agents().
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import zil
from svt.tools.filesystem import grep_files, list_files, read_file, set_workspace, write_file
from svt.tools.shell import run_shell_command
from svt.tools.task import execute_plan, work_on_ticket

log = logging.getLogger(__name__)

def _find_project_dir() -> Path:
    """Walk up from this file looking for manifest.yaml."""
    current = Path(__file__).parent.resolve()
    for d in [current, *current.parents]:
        if (d / "manifest.yaml").is_file():
            return d
    # Fallback to original assumption (two levels up)
    return Path(__file__).parent.parent

_PROJECT_DIR = _find_project_dir()

# In the ADK dev UI there is no TaskRunner to call set_workspace().
# Bootstrap a local scratch directory so filesystem tools work immediately.
_DEV_WORKSPACE = Path(os.environ.get("DEV_WORKSPACE", "/tmp/svt-dev-workspace"))
_DEV_WORKSPACE.mkdir(parents=True, exist_ok=True)
set_workspace(_DEV_WORKSPACE)
log.info("Dev workspace bootstrapped: %s", _DEV_WORKSPACE)


def build_vtl(workspace: Path, *, dev_ui: bool = False) -> Any:  # noqa: ANN401
    """Build and return the VTL root agent wired for *workspace*.

    The VTL only gets ``read_file`` (read-only repo access for onboarding).
    VTA and VTD get the full tool suite: list_files, read_file, write_file,
    run_shell_command.  MCP toolsets and SkillToolsets are auto-wired by
    zil from manifest.yaml.

    Args:
        workspace: Absolute path to the cloned repo for this task run.
            The ContextVar in tools/filesystem.py must be set to this
            path *before* calling this function (done by runner.py via
            set_workspace()).
        dev_ui: When True, adds ``work_on_ticket`` so the ADK dev UI can
            trigger the full pipeline via chat. Must be False when called
            from TaskRunner to prevent recursive invocation.

    Returns:
        A configured ``google.adk.agents.LlmAgent`` instance.
    """
    vtl_tools = [work_on_ticket, execute_plan] if dev_ui else []
    vtl = zil.create_agent(
        tools=vtl_tools,
        project_dir=_PROJECT_DIR,  # always the manifest root, never the task workspace
        enable_mcp=True,
    )

    _inject_sub_agent_tools(vtl)

    log.info(
        "VTL built (workspace=%s, sub-agents=%d)",
        workspace,
        sum(1 for t in vtl.tools if _is_agent_tool(t)),
    )
    return vtl



def _inject_sub_agent_tools(vtl: Any) -> None:
    """Walk vtl.tools, find AgentTool wrappers, inject filesystem/shell tools.

    VTA gets: grep_files, read_file, write_file (minimal — no shell, no list_files)
    VTD gets: grep_files, list_files, read_file, write_file, run_shell_command
    Keeping VTA's tool count low avoids MALFORMED_FUNCTION_CALL from Gemini.
    """
    vta_tools = [grep_files, read_file, write_file]
    vtd_tools = [grep_files, list_files, read_file, write_file, run_shell_command]

    for tool in vtl.tools:
        if not _is_agent_tool(tool):
            continue
        agent = tool.agent
        tools_to_inject = vta_tools if agent.name == "vta" else vtd_tools
        agent.tools = list(agent.tools or []) + tools_to_inject
        log.info(
            "Injected %d inline tools into sub-agent %r",
            len(tools_to_inject),
            agent.name,
        )


def _is_agent_tool(tool: Any) -> bool:
    """Return True if *tool* is an ADK AgentTool wrapper."""
    try:
        from google.adk.tools.agent_tool import AgentTool
        return isinstance(tool, AgentTool)
    except ImportError:
        return False


# ADK dev runner compatibility — exposes root_agent at module level.
# MCP is enabled so VTA/VTD can reach Jira in the dev UI.
# Filesystem tools will return an error if no workspace ContextVar is set
# (i.e. no task has been dispatched yet) — this is expected and harmless.
root_agent = build_vtl(workspace=_PROJECT_DIR, dev_ui=True)
