"""Guards the reference A2A registry example (examples/a2a-registry).

Loads the real ``registry_service.py`` on disk and exercises its HTTP contract
with a FastAPI TestClient (card fetching stubbed — no network). Also verifies
that ``HttpRegistryResolver`` resolves a ``ref:`` peer end-to-end against the
example service, so the OSS resolver and the example stay in lockstep.
"""

import importlib.util
from pathlib import Path

import pytest

from zil.collaboration.contract import PeerRef
from zil.collaboration.discovery import HttpRegistryResolver

EXAMPLE_DIR = Path(__file__).parent.parent / "examples" / "a2a-registry"
SERVICE_FILE = EXAMPLE_DIR / "registry_service.py"

pytestmark = pytest.mark.skipif(
    not SERVICE_FILE.is_file(),
    reason="a2a-registry example not present",
)

pytest.importorskip("fastapi", reason="requires zil-ai[serve]")


def _load_service():
    """Import the example module fresh from its path."""
    spec = importlib.util.spec_from_file_location("a2a_registry_service", SERVICE_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def service(monkeypatch):
    mod = _load_service()
    # Stub card fetching so tests never touch the network.
    cards = {
        "http://localhost:8001": {
            "name": "weather-agent",
            "url": "http://localhost:8001",
            "version": "0.1.0",
            "skills": [{"id": "get-forecast", "name": "Get Forecast", "tags": []}],
        }
    }
    monkeypatch.setattr(mod, "_fetch_card", lambda url: cards.get(url.rstrip("/")))
    # Seed deterministically (ignore any on-disk agents.json env override).
    mod._fleet.clear()
    mod._fleet["weather-agent"] = "http://localhost:8001"
    return mod


@pytest.fixture
def client(service):
    from fastapi.testclient import TestClient

    return TestClient(service.app)


class TestRegistryServiceContract:
    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_resolve_known_agent_embeds_card(self, client):
        resp = client.get("/agents/weather-agent")
        assert resp.status_code == 200
        body = resp.json()
        assert body["url"] == "http://localhost:8001"
        assert [s["id"] for s in body["card"]["skills"]] == ["get-forecast"]

    def test_resolve_unknown_agent_404(self, client):
        assert client.get("/agents/nope").status_code == 404

    def test_list_agents_includes_skills(self, client):
        body = client.get("/agents").json()
        names = {a["name"]: a for a in body["agents"]}
        assert "weather-agent" in names
        assert names["weather-agent"]["skills"] == ["get-forecast"]

    def test_register_then_resolve(self, client):
        client.post("/agents", json={"name": "billing", "url": "http://localhost:9000"})
        resp = client.get("/agents/billing")
        assert resp.status_code == 200
        assert resp.json()["url"] == "http://localhost:9000"


class TestResolverAgainstExample:
    def test_http_resolver_resolves_ref_via_example_service(self, client):
        # Back HttpRegistryResolver's network seam with the in-process TestClient.
        def registry_fetcher(resolve_url: str) -> dict:
            path = resolve_url.split("http://registry", 1)[-1]
            return client.get(path).json()

        resolver = HttpRegistryResolver(
            "http://registry", registry_fetcher=registry_fetcher
        )
        peer = PeerRef(name="weather-agent", ref="zil://fleet/weather-agent")
        assert resolver.resolve_url(peer) == "http://localhost:8001"
        card = resolver.resolve(peer)
        assert card.skill_ids() == ["get-forecast"]
