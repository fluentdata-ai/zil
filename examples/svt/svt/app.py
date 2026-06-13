"""
svt/app.py

FastAPI webhook entry point for the SVT agent.

Endpoints:
  POST /webhooks/jira    — inbound Jira webhook (HMAC-validated)
  POST /debug/run-task   — manual trigger (DEBUG_TOKEN required)
  GET  /health           — container health check

Run locally:  uvicorn svt.app:app --reload --port 8080
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, status
from pydantic import BaseModel

from svt.runner import TaskRunner

log = logging.getLogger("svt.app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="svt-agent", version="0.1.0", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# HMAC signature verification
# ---------------------------------------------------------------------------

def _verify_jira_signature(raw_body: bytes, signature_header: str | None) -> None:
    secret = os.environ.get("JIRA_WEBHOOK_SECRET", "")
    if not secret:
        log.warning("JIRA_WEBHOOK_SECRET not set — skipping signature check")
        return
    if not signature_header:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing X-Hub-Signature header")
    provided = (
        signature_header.split("=", 1)[1]
        if "=" in signature_header
        else signature_header
    )
    expected = hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, provided):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid signature")


# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------

class JiraIssueRef(BaseModel):
    key: str


class JiraWebhookPayload(BaseModel):
    webhookEvent: str  # noqa: N815 — field name fixed by Jira's webhook payload
    issue: JiraIssueRef


class DebugRunTaskRequest(BaseModel):
    issue_key: str


# ---------------------------------------------------------------------------
# Jira webhook (production path)
# ---------------------------------------------------------------------------

@app.post("/webhooks/jira", status_code=status.HTTP_202_ACCEPTED)
async def jira_webhook(request: Request, background: BackgroundTasks) -> dict[str, str]:
    """Accept a Jira issue event and dispatch the SVT agent in the background."""
    raw = await request.body()
    _verify_jira_signature(raw, request.headers.get("X-Hub-Signature"))

    payload = JiraWebhookPayload.model_validate_json(raw)
    log.info("Webhook event=%s issue=%s", payload.webhookEvent, payload.issue.key)

    if payload.webhookEvent not in {"jira:issue_created", "jira:issue_updated"}:
        return {"status": "ignored", "reason": f"event {payload.webhookEvent} not handled"}

    background.add_task(_run_task_safely, payload.issue.key)
    return {"status": "accepted", "issue": payload.issue.key}


# ---------------------------------------------------------------------------
# Debug endpoint — manual trigger (no Jira webhook required)
# ---------------------------------------------------------------------------

@app.post("/debug/run-task", status_code=status.HTTP_202_ACCEPTED)
async def debug_run_task(
    request: Request,
    payload: DebugRunTaskRequest,
    background: BackgroundTasks,
) -> dict[str, str]:
    """Trigger the agent manually. Requires DEBUG_TOKEN header."""
    debug_token = os.environ.get("DEBUG_TOKEN")
    if not debug_token:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    provided = request.headers.get("X-Debug-Token", "")
    if not hmac.compare_digest(debug_token, provided):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid debug token")

    log.info("Debug trigger: issue=%s", payload.issue_key)
    background.add_task(_run_task_safely, payload.issue_key)
    return {"status": "accepted", "issue": payload.issue_key, "mode": "debug"}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _run_task_safely(issue_key: str) -> None:
    try:
        await TaskRunner(issue_key).run()
    except Exception:
        log.exception("Task %s failed", issue_key)
