"""Framework-neutral A2A call demo (ZIL-RFC-005 §7.1).

Calls the weather-agent's `get-forecast` skill over A2A using the native
``A2APeerClient`` — no agent framework required. Also shows that the per-peer
skill allowlist is enforced *before* any network request (least authority).

Prerequisite: the weather-agent must be running, e.g.

    cd examples/a2a-collaboration/weather-agent
    zil serve --port 8001

Then, from the repo root (or anywhere with zil-ai installed):

    WEATHER_AGENT_URL=http://localhost:8001 \
        python examples/a2a-collaboration/call_peer.py
"""

import asyncio
import os

from zil.collaboration import A2APeerClient, PeerRef, SkillNotAllowedError


async def main() -> None:
    url = os.environ.get("WEATHER_AGENT_URL", "http://localhost:8001")

    # The same peer the trip-planner declares in spec.collaborators.
    weather = PeerRef(
        name="weather-agent",
        url=url,
        skills=["get-forecast"],  # allowlist: only this skill may be invoked
        auth="none",              # local quickstart; see README for prod auth
    )

    client = A2APeerClient(weather, caller="trip-planner")

    # 1) Allowed call — fetches the Agent Card, sends message/send, parses artifacts.
    result = await client.call(
        "get-forecast", "What's the weather in Lisbon this weekend?"
    )
    print(f"status   : {result.status}")
    print(f"task_id  : {result.task_id}")
    print(f"forecast :\n{result.text()}\n")

    # 2) Least authority — a skill outside the allowlist is rejected with no
    #    network request at all.
    try:
        await client.call("delete-data", "drop everything")
    except SkillNotAllowedError as exc:
        print(f"blocked (as expected): {exc}")


if __name__ == "__main__":
    asyncio.run(main())
