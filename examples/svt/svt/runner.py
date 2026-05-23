"""
svt/runner.py

Workspace-per-task orchestrator for the SVT agent.

Each Jira task gets an isolated directory:
  1. Clone the target repo.
  2. Set the filesystem ContextVar so all agent tools are sandboxed.
  3. Build the VTL agent (MCP + SkillToolset + inline tools).
  4. Run the agent session and collect the final response.
  5. Clean up the workspace directory.
"""
from __future__ import annotations

import json
import logging
import os
import ssl
import subprocess
import uuid
from base64 import b64encode
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from svt.agent import build_vtl
from svt.tools.filesystem import reset_workspace, set_workspace

log = logging.getLogger(__name__)

APP_NAME = "svt-agent"
AGENT_MODE = os.getenv("AGENT_MODE", "plan_only").strip().lower()
VALID_MODES = {"plan_only", "plan_and_execute"}
if AGENT_MODE not in VALID_MODES:
    raise ValueError(f"Invalid AGENT_MODE={AGENT_MODE!r}. Valid: {VALID_MODES}")

_REPO_URL = os.environ.get("GITHUB_REPO_URL", "")
_GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
_BASE_BRANCH = os.getenv("GITHUB_DEFAULT_BASE_BRANCH", "dev")
_WORKSPACE_ROOT = Path(os.getenv("AGENT_WORKSPACE_ROOT", "/tmp/workspaces"))
_REFERENCE_CLONE = _WORKSPACE_ROOT / "_reference_clone"
_reference_clone_ready: bool = False  # in-process flag to skip re-fetch


class TaskRunner:
    """Clones the target repo and orchestrates VTA/VTD for a single Jira task.

    Two-phase interactive flow:
      1. plan()   — clones repo, runs VTA, returns plan content for review.
      2. execute() — runs VTD on the already-cloned workspace.

    The workspace path is persisted between phases so execute() reuses the
    same clone without re-downloading the repo.
    """

    def __init__(self, issue_key: str) -> None:
        self.issue_key = issue_key
        self._workspace_path: Path | None = None

    async def plan(self) -> dict:
        """Clone the repo, run VTA, and return the generated plan for review."""
        log.info("[%s] plan phase starting", self.issue_key)
        workspace = _WORKSPACE_ROOT / f"{self.issue_key}-{uuid.uuid4().hex[:8]}"
        workspace.mkdir(parents=True, exist_ok=True)
        self._workspace_path = workspace

        self._clone(workspace)
        token = set_workspace(workspace)
        try:
            result = await self._run_vta(workspace)
        finally:
            reset_workspace(token)

        log.info("[%s] plan phase done. plan_exists=%s", self.issue_key, result.get("plan_exists"))
        return result

    async def execute(self) -> dict:
        """Run VTD on the workspace prepared by plan(). Must call plan() first."""
        if not self._workspace_path or not self._workspace_path.exists():
            return {"status": "error", "error": "No workspace found. Call plan() first."}

        workspace = self._workspace_path
        log.info("[%s] execute phase starting in %s", self.issue_key, workspace)
        token = set_workspace(workspace)
        try:
            result = await self._run_vtd(workspace)
        finally:
            reset_workspace(token)

        log.info("[%s] execute phase done. response_chars=%d", self.issue_key, len(result.get("agent_response", "")))
        return result

    async def run(self) -> dict:
        """Legacy full pipeline (plan + execute). Used by webhook handler."""
        log.info("[%s] starting (AGENT_MODE=%s)", self.issue_key, AGENT_MODE)

        workspace = _WORKSPACE_ROOT / f"{self.issue_key}-{uuid.uuid4().hex[:8]}"
        workspace.mkdir(parents=True, exist_ok=True)
        self._workspace_path = workspace

        self._clone(workspace)
        token = set_workspace(workspace)
        try:
            result = await self._run_agent(workspace)
        finally:
            reset_workspace(token)

        log.info(
            "[%s] done. plan_exists=%s response_chars=%d",
            self.issue_key,
            result.get("plan_exists"),
            len(result.get("agent_response", "")),
        )
        return result

    async def _run_vta(self, workspace: Path) -> dict[str, Any]:
        """Run VTA via VTL to produce a plan. Returns plan content for review."""
        from svt.agent import build_vtl
        vta_prompt = _build_vta_prompt(self.issue_key)
        vtl_prompt = (
            f"Jira task: **{self.issue_key}**. Operation mode: `plan_only`."
            f" AGENT_MODE=plan_only."
            f"\n\nInvoke the `vta` subagent with the following prompt:\n\n"
            f"{vta_prompt}"
            f"\n\nIMPORTANT: When VTA responds, output its COMPLETE response verbatim."
            f" Do NOT summarize or paraphrase. The full plan must be visible to the user."
        )
        agent_text = await _run_single_agent(
            agent=build_vtl(workspace),
            prompt=vtl_prompt,
            issue_key=self.issue_key,
            max_llm_calls=12,
        )
        plan_path = workspace / f"{self.issue_key}-plan.md"

        if not plan_path.is_file() and agent_text:
            # VTA generated the plan as text but didn't call write_file.
            # Write it ourselves so execute_plan() can find it later.
            plan_path.write_text(agent_text, encoding="utf-8")
            log.info("[%s] plan file written from agent response (%d chars)", self.issue_key, len(agent_text))

        plan_exists = plan_path.is_file()
        if plan_exists:
            plan_content = plan_path.read_text(encoding="utf-8")
            log.info("[%s] plan file read (%d chars)", self.issue_key, len(plan_content))
        else:
            plan_content = "(VTA did not produce a plan — check logs)"
            log.warning("[%s] no plan file and no agent response", self.issue_key)
        return {
            "plan_exists": plan_exists,
            "plan_content": plan_content,
            "workspace": str(workspace),
        }

    async def _run_vtd(self, workspace: Path) -> dict[str, Any]:
        """Run VTD via VTL to execute an existing plan."""
        from svt.agent import build_vtl
        plan_path = workspace / f"{self.issue_key}-plan.md"
        if not plan_path.is_file():
            return {"status": "error", "error": f"Plan file not found: {self.issue_key}-plan.md"}
        vtl_prompt = (
            f"Jira task: **{self.issue_key}**. Operation mode: `plan_and_execute`."
            f" AGENT_MODE=plan_and_execute. The plan has already been written."
            f"\n\nInvoke the `vtd` subagent with: \"Execute the plan for task "
            f"{self.issue_key}. Read `{self.issue_key}-plan.md` and follow every "
            f"implementation step. Use `fd-submit-changes` skill to create a branch, "
            f'commit, and open a PR when done."'
        )
        final_text = await _run_single_agent(
            agent=build_vtl(workspace),
            prompt=vtl_prompt,
            issue_key=self.issue_key,
        )
        return {
            "status": "ok",
            "agent_response": final_text or "(VTD returned no content)",
        }

    async def _run_agent(self, workspace: Path) -> dict[str, Any]:
        vtl = build_vtl(workspace)
        session_svc = InMemorySessionService()
        runner = Runner(
            agent=vtl,
            app_name=APP_NAME,
            session_service=session_svc,
        )

        user_id = "jira-webhook"
        session_id = f"{self.issue_key}-{uuid.uuid4().hex[:8]}"
        await session_svc.create_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=session_id,
        )

        prompt = _build_prompt(self.issue_key)
        message = types.Content(role="user", parts=[types.Part(text=prompt)])

        final_text = ""
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=message,
        ):
            if event.is_final_response():
                author = getattr(event, "author", "?")
                has_content = bool(event.content and event.content.parts)
                log.debug("[%s] final_response from=%s has_content=%s", self.issue_key, author, has_content)
                if has_content:
                    text = "".join(p.text for p in event.content.parts if p.text)
                    if text:
                        final_text = text
                        log.debug("[%s] captured final_text (%d chars) from %s", self.issue_key, len(text), author)

        plan_path = workspace / f"{self.issue_key}-plan.md"
        plan_exists = plan_path.is_file()

        if not final_text and plan_exists:
            final_text = f"PLAN GENERATED: {self.issue_key}-plan.md\n\n{plan_path.read_text(encoding='utf-8')}"
            log.info("[%s] agent response was empty — using plan file content (%d chars)", self.issue_key, len(final_text))

        return {
            "mode": AGENT_MODE,
            "plan_exists": plan_exists,
            "agent_response": final_text or "(no textual response)",
        }

    @contextmanager
    def _workspace(self):
        path = _WORKSPACE_ROOT / f"{self.issue_key}-{uuid.uuid4().hex[:8]}"
        path.mkdir(parents=True, exist_ok=True)
        try:
            yield path
        finally:
            log.info("[%s] workspace preserved at %s", self.issue_key, path)

    def _clone(self, dest: Path) -> None:
        if not _REPO_URL:
            raise RuntimeError("GITHUB_REPO_URL is not set")
        ref = _ensure_reference_clone()
        clone_url = _inject_token(_REPO_URL, _GITHUB_TOKEN)
        subprocess.run(
            ["git", "clone", "--branch", _BASE_BRANCH,
             "--reference", str(ref), clone_url, str(dest)],
            check=True,
        )
        log.info("[%s] cloned (via reference) %s → %s", self.issue_key, _REPO_URL, dest)


def _ensure_reference_clone() -> Path:
    """Maintain a bare reference clone for fast local git clone --reference.

    First call: does a full network clone into _REFERENCE_CLONE (bare).
    Within the same process: skips re-fetch (already up to date).
    New process start with existing cache: fetches latest then reuses.
    The hardlink trick means per-task clones take <1s instead of ~10s.
    """
    global _reference_clone_ready  # noqa: PLW0603
    _WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
    clone_url = _inject_token(_REPO_URL, _GITHUB_TOKEN)
    if not _REFERENCE_CLONE.exists():
        log.info("Reference clone not found — performing initial bare clone (one-time ~10s)")
        subprocess.run(
            ["git", "clone", "--bare", "--branch", _BASE_BRANCH, clone_url, str(_REFERENCE_CLONE)],
            check=True,
        )
        log.info("Reference clone ready at %s", _REFERENCE_CLONE)
    elif not _reference_clone_ready:
        log.info("Fetching reference clone at %s", _REFERENCE_CLONE)
        subprocess.run(
            ["git", "--git-dir", str(_REFERENCE_CLONE), "fetch", "--prune", "origin"],
            check=False,  # non-fatal if offline
        )
    _reference_clone_ready = True
    return _REFERENCE_CLONE


async def _run_single_agent(
    agent: Any, prompt: str, issue_key: str, *, max_llm_calls: int = 25,
) -> str:
    """Run a single agent, collect and return the last final-response text."""
    from google.adk.agents import RunConfig

    session_svc = InMemorySessionService()
    runner = Runner(agent=agent, app_name=APP_NAME, session_service=session_svc)
    user_id = "svt-runner"
    session_id = f"{issue_key}-{uuid.uuid4().hex[:8]}"
    await session_svc.create_session(app_name=APP_NAME, user_id=user_id, session_id=session_id)
    message = types.Content(role="user", parts=[types.Part(text=prompt)])
    run_config = RunConfig(max_llm_calls=max_llm_calls)
    final_text = ""
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=message,
        run_config=run_config,
    ):
        if event.is_final_response() and event.content and event.content.parts:
            text = "".join(p.text for p in event.content.parts if p.text)
            if text:
                final_text = text
    return final_text


def _build_vta_prompt(issue_key: str) -> str:
    """Build the prompt for a standalone VTA invocation."""
    issue_context = _fetch_jira_issue(issue_key)
    if issue_context:
        return (
            f"Plan task {issue_key}.\n\n"
            f"Here is the full Jira issue context — use it directly, "
            f"no need to call `get_issue`:\n\n"
            f"{issue_context}\n\n"
            f"Explore the repo and write the implementation plan to `{issue_key}-plan.md`."
        )
    return (
        f"Plan task {issue_key}. "
        f"Call `get_issue(issue_key=\"{issue_key}\")` to fetch the Jira issue, "
        f"explore the repo, and write the plan to `{issue_key}-plan.md`."
    )


def _inject_token(url: str, token: str) -> str:
    """Embed *token* into an HTTPS GitHub URL for authenticated cloning.

    https://github.com/org/repo  →  https://<token>@github.com/org/repo
    SSH URLs and empty tokens are returned unchanged.
    """
    if not token or not url.startswith("https://"):
        return url
    return url.replace("https://", f"https://{token}@", 1)


def _fetch_jira_issue(issue_key: str) -> str:
    """Fetch Jira issue via REST API and return a formatted context block."""
    base_url = os.environ.get("JIRA_BASE_URL", "").rstrip("/")
    token = os.environ.get("JIRA_API_TOKEN", "")
    email = os.environ.get("JIRA_USER_EMAIL", "")
    if not base_url or not token:
        return ""
    try:
        import certifi
        ssl_ctx = ssl.create_default_context(cafile=certifi.where())
        creds = b64encode(f"{email}:{token}".encode()).decode()
        url = f"{base_url}/rest/api/3/issue/{issue_key}?fields=summary,description,issuetype,priority,status,assignee,comment"
        req = Request(url, headers={"Authorization": f"Basic {creds}", "Accept": "application/json"})
        with urlopen(req, timeout=10, context=ssl_ctx) as resp:
            data = json.loads(resp.read())
        fields = data.get("fields", {})
        summary = fields.get("summary", "(no summary)")
        desc = fields.get("description") or "(no description)"
        if isinstance(desc, dict):  # Atlassian Document Format
            desc = _adf_to_text(desc)
        status = (fields.get("status") or {}).get("name", "?")
        issue_type = (fields.get("issuetype") or {}).get("name", "?")
        comments = []
        for c in (fields.get("comment") or {}).get("comments", [])[-5:]:
            body = c.get("body", "")
            if isinstance(body, dict):
                body = _adf_to_text(body)
            author = (c.get("author") or {}).get("displayName", "?")
            comments.append(f"  [{author}]: {body[:300]}")
        comment_block = "\n".join(comments) or "  (none)"
        log.info("[%s] Jira issue fetched via REST: %s", issue_key, summary)
        return (
            f"## Jira issue: {issue_key}\n"
            f"**Type**: {issue_type} | **Status**: {status}\n"
            f"**Summary**: {summary}\n\n"
            f"**Description**:\n{desc}\n\n"
            f"**Recent comments**:\n{comment_block}\n"
        )
    except (URLError, Exception) as exc:  # noqa: BLE001
        log.warning("[%s] Could not fetch Jira issue via REST: %s", issue_key, exc)
        return ""


def _adf_to_text(node: dict, depth: int = 0) -> str:
    """Recursively extract plain text from Atlassian Document Format JSON."""
    if not isinstance(node, dict):
        return str(node)
    if node.get("type") == "text":
        return node.get("text", "")
    parts = []
    for child in node.get("content", []):
        parts.append(_adf_to_text(child, depth + 1))
    sep = "\n" if node.get("type") in ("paragraph", "listItem", "heading") else ""
    return sep.join(parts)


def _build_prompt(issue_key: str) -> str:
    issue_context = _fetch_jira_issue(issue_key)
    if issue_context:
        vta_prompt = (
            f"Plan task {issue_key}.\n\n"
            f"Here is the full Jira issue context — use it directly, "
            f"no need to call `get_issue`:\n\n"
            f"{issue_context}\n\n"
            f"Now explore the repo and write the implementation plan "
            f"to `{issue_key}-plan.md`."
        )
    else:
        vta_prompt = (
            f"Plan task {issue_key}. "
            f"Call `get_issue(issue_key=\"{issue_key}\")` to fetch the Jira issue, "
            f"explore the repo, and write the plan to `{issue_key}-plan.md`."
        )
    return (
        f"Jira task: **{issue_key}**. Operation mode: `{AGENT_MODE}`.\n\n"
        f"Invoke the `vta` subagent with the following prompt:\n\n"
        f"{vta_prompt}\n\n"
        f"When the VTA responds, follow the rules for mode "
        f"`{AGENT_MODE}` in your system instructions.\n"
    )
