"""Resolve a peer through the registry, then call it over A2A (RFC-005 §9).

Same as ``examples/a2a-collaboration/call_peer.py`` but the peer is declared
with a registry **ref** (``zil://fleet/weather-agent``) instead of a hard URL.
``HttpRegistryResolver`` looks the name up in the registry service to discover
the live URL — no code or env change beyond pointing at the registry.

Prerequisites (three shells):

    # 1. weather-agent (callee)
    cd examples/a2a-collaboration/weather-agent && zil serve --port 8001

    # 2. registry service (seeded with weather-agent -> http://localhost:8001)
    python examples/a2a-registry/registry_service.py --port 8500

    # 3. this script
    ZIL_FLEET_REGISTRY_URL=http://localhost:8500 \
        python examples/a2a-registry/call_peer_via_registry.py
"""

import asyncio
import os

from zil.collaboration import A2APeerClient, PeerRef, SkillNotAllowedError
from zil.collaboration.discovery import HttpRegistryResolver


async def main() -> None:
    registry_url = os.environ.get("ZIL_FLEET_REGISTRY_URL", "http://localhost:8500")

    # Declared with a registry ref instead of a URL — discovery is dynamic.
    weather = PeerRef(
        name="weather-agent",
        ref="zil://fleet/weather-agent",
        skills=["get-forecast"],
        auth="none",
    )

    resolver = HttpRegistryResolver(registry_url)
    client = A2APeerClient(weather, caller="trip-planner", resolver=resolver)

    result = await client.call(
        "get-forecast", "What's the weather in Lisbon this weekend?"
    )
    print(f"resolved : {resolver.resolve_url(weather)}")
    print(f"status   : {result.status}")
    print(f"forecast :\n{result.text()}\n")

    # Least authority still holds — enforced before any network/registry call.
    try:
        await client.call("delete-data", "drop everything")
    except SkillNotAllowedError as exc:
        print(f"blocked (as expected): {exc}")


if __name__ == "__main__":
    asyncio.run(main())
