"""Guards the shipped A2A collaboration example (examples/a2a-collaboration).

These tests load the *real* example manifests on disk — not synthetic
fixtures — so the example stays in lockstep with the collaboration code
(ZIL-RFC-005). They cover manifest validity, the declared collaborator
wiring, the declared topology graph, and the cross-agent invariant that the
caller's skill allowlist references a skill the callee actually advertises.
"""

import asyncio
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

from zil.collaboration.client import A2APeerClient, SkillNotAllowedError
from zil.collaboration.contract import ContextTransferPolicy, PeerRef
from zil.collaboration.topology import build_topology_graph, find_cycles
from zil.schema.loader import validate_project
from zil.sdk.loader import load_project

# examples/ lives at the repo root, alongside tests/.
EXAMPLE_DIR = Path(__file__).parent.parent / "examples" / "a2a-collaboration"
TRIP_PLANNER = EXAMPLE_DIR / "trip-planner"
WEATHER_AGENT = EXAMPLE_DIR / "weather-agent"

pytestmark = pytest.mark.skipif(
    not EXAMPLE_DIR.is_dir(),
    reason="a2a-collaboration example not present",
)


def _manifest(project_dir: Path) -> dict:
    return yaml.safe_load((project_dir / "manifest.yaml").read_text())


# ---------------------------------------------------------------------------
# Manifest validity (offline)
# ---------------------------------------------------------------------------


class TestExampleManifestsValidate:
    def test_weather_agent_has_no_errors(self):
        result = validate_project(WEATHER_AGENT)
        failures = [c.message for c in result.checks if c.status == "fail"]
        assert result.error_count == 0, failures

    def test_trip_planner_has_no_errors(self):
        # `auth: none` intentionally emits a warning, not an error.
        result = validate_project(TRIP_PLANNER)
        failures = [c.message for c in result.checks if c.status == "fail"]
        assert result.error_count == 0, failures

    def test_trip_planner_auth_none_warns(self):
        result = validate_project(TRIP_PLANNER)
        assert any(
            c.status == "warn" and "disables" in c.message for c in result.checks
        )


# ---------------------------------------------------------------------------
# Declared collaborator wiring
# ---------------------------------------------------------------------------


class TestTripPlannerCollaborators:
    def test_declares_weather_agent_peer(self):
        ctx = load_project(TRIP_PLANNER)
        assert len(ctx.collaborators) == 1
        peer = ctx.collaborators[0]
        assert isinstance(peer, PeerRef)
        # Handle matches the callee's metadata.name so `zil topology` links them.
        assert peer.name == "weather-agent"
        # Registry discovery (RFC-007): the peer is resolved by logical name via
        # `ref: zil://fleet/<name>`, not a hard-coded url.
        assert peer.url is None
        assert peer.ref == "zil://fleet/weather-agent"
        assert peer.skills == ["get-forecast"]
        assert peer.auth == "none"

    def test_context_transfer_policy(self):
        ctx = load_project(TRIP_PLANNER)
        ct = ctx.collaborators[0].context_transfer
        assert isinstance(ct, ContextTransferPolicy)
        assert ct.send == "message_only"
        assert ct.receive == "artifacts"
        assert "user_email" in ct.redact


# ---------------------------------------------------------------------------
# Cross-agent invariant — caller allowlist matches callee's advertised skills
# ---------------------------------------------------------------------------


class TestSkillAllowlistMatchesCallee:
    def test_weather_agent_advertises_declared_skills(self):
        ctx = load_project(WEATHER_AGENT)
        assert ctx.skills_dir is not None
        advertised = {
            d.name
            for d in ctx.skills_dir.iterdir()
            if d.is_dir() and (d / "SKILL.md").is_file()
        }
        assert "get-forecast" in advertised

        # Every skill the trip-planner is allowed to call must be advertised
        # by the weather-agent — guards against drift between the two manifests.
        caller = load_project(TRIP_PLANNER)
        allowlist = set(caller.collaborators[0].skills)
        assert allowlist <= advertised, (allowlist, advertised)


# ---------------------------------------------------------------------------
# Declared topology (RFC-005 §10.1)
# ---------------------------------------------------------------------------


class TestExampleTopology:
    def test_graph_has_caller_to_callee_edge(self):
        graph = build_topology_graph([_manifest(TRIP_PLANNER), _manifest(WEATHER_AGENT)])
        assert graph["trip-planner"] == ["weather-agent"]
        assert graph["weather-agent"] == []

    def test_no_cycles(self):
        graph = build_topology_graph([_manifest(TRIP_PLANNER), _manifest(WEATHER_AGENT)])
        assert find_cycles(graph) == []


# ---------------------------------------------------------------------------
# Live end-to-end (opt-in) — boots the real weather-agent via `zil serve`
# and calls its get-forecast skill over A2A with the native client.
#
# Gated behind an env flag + a real key so it never runs in normal CI:
#   ZIL_LIVE_A2A=1 GOOGLE_API_KEY=... pytest tests/test_examples_a2a.py -k Live
# ---------------------------------------------------------------------------

_LIVE_ENABLED = os.environ.get("ZIL_LIVE_A2A", "").lower() in ("1", "true", "yes")
_HAS_KEY = bool(os.environ.get("GOOGLE_API_KEY"))

requires_live = pytest.mark.skipif(
    not (_LIVE_ENABLED and _HAS_KEY),
    reason="live A2A test requires ZIL_LIVE_A2A=1 and GOOGLE_API_KEY",
)


def _free_port() -> int:
    """Reserve an ephemeral port and return it (closed before reuse)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_healthy(base_url: str, proc: subprocess.Popen, timeout: float) -> None:
    """Poll ``/health`` until 200, or fail if the server dies / times out."""
    import httpx

    deadline = time.monotonic() + timeout
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            out = (proc.stdout.read() if proc.stdout else "") or ""
            raise RuntimeError(f"zil serve exited early (code={proc.returncode}):\n{out}")
        try:
            resp = httpx.get(f"{base_url}/health", timeout=2.0)
            if resp.status_code == 200:
                return
        except Exception as exc:  # noqa: BLE001 — connection refused while booting
            last_err = exc
        time.sleep(0.5)
    raise TimeoutError(f"weather-agent not healthy within {timeout}s: {last_err}")


@pytest.fixture
def live_weather_server():
    """Start the example weather-agent on a free port; yield its base URL."""
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    zil_bin = Path(sys.executable).parent / "zil"
    cmd = [str(zil_bin)] if zil_bin.exists() else [sys.executable, "-m", "zil.cli"]
    cmd += ["serve", "--project-dir", str(WEATHER_AGENT), "--port", str(port),
            "--host", "127.0.0.1"]

    proc = subprocess.Popen(
        cmd,
        cwd=str(WEATHER_AGENT),
        env={**os.environ},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        _wait_healthy(base_url, proc, timeout=60.0)
        yield base_url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


@requires_live
class TestLiveA2ARoundTrip:
    def test_get_forecast_over_a2a(self, live_weather_server):
        """End-to-end: discover the card, call get-forecast, get a real answer."""
        peer = PeerRef(
            name="weather-agent",
            url=live_weather_server,
            skills=["get-forecast"],
            auth="none",
        )
        client = A2APeerClient(peer, caller="trip-planner")

        async def run():
            return await client.call(
                "get-forecast", "What's the weather in Lisbon this weekend?"
            )

        result = asyncio.run(run())
        assert result.status == "completed", result
        assert result.text().strip(), "expected a non-empty forecast"

    def test_disallowed_skill_blocked_pre_network(self, live_weather_server):
        """A skill outside the allowlist is rejected before any network call."""
        peer = PeerRef(
            name="weather-agent",
            url=live_weather_server,
            skills=["get-forecast"],
            auth="none",
        )
        client = A2APeerClient(peer, caller="trip-planner")

        async def run():
            return await client.call("delete-data", "drop everything")

        with pytest.raises(SkillNotAllowedError):
            asyncio.run(run())
