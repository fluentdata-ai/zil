"""Reference A2A registry-of-record service (ZIL-RFC-005 §9 / RFC-007 seam).

A *minimal, stateless* HTTP registry that maps a logical agent name to a
deployed URL (and, best-effort, its live Agent Card). It implements the small
contract that :class:`zil.collaboration.discovery.HttpRegistryResolver` speaks,
so a fleet of agents can resolve ``ref: zil://fleet/<name>`` peers without
hard-coding URLs.

    GET  /agents            -> {"agents": [{"name", "url", "skills"}]}
    GET  /agents/{name}     -> {"name", "url", "card"}        (404 if unknown)
    POST /agents            -> register/replace {"name", "url"}
    GET  /health            -> {"status": "ok"}

THIS IS A REFERENCE EXAMPLE, NOT A PRODUCTION SERVICE. It keeps the fleet map
in memory (optionally seeded from ``agents.json``) and has no auth, persistence,
or multi-tenancy. The production *registry of record* (workspace-scoped, backed
by a real datastore, GCP ID-token auth) lives in the platform runtime — see the
plan/RFC-007. The value here is the **contract**, which both sides agree on.

Run it::

    pip install "zil-ai[serve]"          # fastapi + uvicorn + httpx (via a2a-sdk)
    python examples/a2a-registry/registry_service.py --port 8500
    # or: uvicorn registry_service:app --port 8500
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("a2a-registry")

WELL_KNOWN_CARD_PATH = "/.well-known/agent-card.json"
SEED_FILE = Path(__file__).parent / "agents.json"

# In-memory fleet map: name -> base url. Seeded from agents.json if present.
_fleet: dict[str, str] = {}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _load_seed()
    yield


app = FastAPI(title="A2A Reference Registry", version="0.1.0", lifespan=lifespan)


class AgentRegistration(BaseModel):
    name: str
    url: str


def _load_seed() -> None:
    """Seed the in-memory fleet from agents.json and AGENTS_JSON env override."""
    _fleet.clear()
    seed_path = Path(os.environ.get("AGENTS_JSON", SEED_FILE))
    if not seed_path.is_file():
        logger.info("No seed file at %s — starting with an empty fleet", seed_path)
        return
    try:
        data = json.loads(seed_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read seed file %s: %s", seed_path, exc)
        return
    for entry in data.get("agents", []):
        name, url = entry.get("name"), entry.get("url")
        if name and url:
            _fleet[name] = url
    logger.info("Seeded %d agent(s) from %s: %s", len(_fleet), seed_path, sorted(_fleet))


def _fetch_card(base_url: str) -> dict | None:
    """Best-effort fetch of the peer's well-known Agent Card (None on failure)."""
    well_known = base_url.rstrip("/") + WELL_KNOWN_CARD_PATH
    try:
        resp = httpx.get(well_known, timeout=5.0)
        resp.raise_for_status()
        return resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.info("Card fetch failed for %s: %s", well_known, exc)
        return None


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "agents": len(_fleet)}


@app.get("/agents")
def list_agents() -> dict:
    """List all known agents, embedding advertised skill ids when reachable."""
    agents = []
    for name, url in sorted(_fleet.items()):
        card = _fetch_card(url)
        skills = [s.get("id") for s in (card or {}).get("skills", [])] if card else []
        agents.append({"name": name, "url": url, "skills": skills})
    return {"agents": agents}


@app.get("/agents/{name}")
def resolve_agent(name: str) -> dict:
    """Resolve one agent to its URL + (best-effort) live Agent Card.

    This is the endpoint ``HttpRegistryResolver`` calls. ``card`` may be null if
    the peer is unreachable — the resolver then falls back to fetching the
    peer's well-known card directly.
    """
    url = _fleet.get(name)
    if not url:
        raise HTTPException(status_code=404, detail=f"agent '{name}' not in registry")
    return {"name": name, "url": url, "card": _fetch_card(url)}


@app.post("/agents")
def register_agent(reg: AgentRegistration) -> dict:
    """Register (or replace) an agent's URL. Demo convenience only."""
    _fleet[reg.name] = reg.url
    logger.info("Registered %s -> %s", reg.name, reg.url)
    return {"name": reg.name, "url": reg.url}


def main() -> None:
    parser = argparse.ArgumentParser(description="A2A reference registry service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8500)
    args = parser.parse_args()

    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
