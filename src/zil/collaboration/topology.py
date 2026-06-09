"""Declared-topology graph + cycle detection (ZIL-RFC-005 §10.1).

The set of ``spec.collaborators`` on each agent *is* the allowed topology:
who-talks-to-whom. These framework-neutral helpers build a directed graph from
a set of manifests and detect cycles (including self-loops).

Single-manifest ``zil validate`` only knows its own collaborators, so it checks
self-reference directly (see ``zil.schema.loader._check_collaborators``).
Fleet-wide cycle detection needs *all* manifests; the multi-manifest source is
the RFC-007 registry, so these primitives are provided here for that caller
without taking a dependency on it.
"""

from __future__ import annotations

from collections.abc import Iterable

# A directed graph: agent name -> list of declared collaborator names.
TopologyGraph = dict[str, list[str]]

# DFS node colors for cycle detection.
_WHITE, _GRAY, _BLACK = 0, 1, 2


def manifest_agent_name(manifest: dict) -> str | None:
    """Return an agent manifest's own name (``metadata.name``)."""
    return (manifest.get("metadata") or {}).get("name")


def build_topology_graph(manifests: Iterable[dict]) -> TopologyGraph:
    """Map each agent name to its declared collaborator names.

    Manifests without a ``metadata.name`` are skipped. Collaborators without a
    ``name`` are ignored. Edges to agents not present among *manifests* are
    retained (they are "external"/unknown peers); ``find_cycles`` ignores them.
    """
    graph: TopologyGraph = {}
    for manifest in manifests:
        name = manifest_agent_name(manifest)
        if not name:
            continue
        collaborators = (manifest.get("spec") or {}).get("collaborators") or []
        peers = [p.get("name") for p in collaborators if p.get("name")]
        graph[name] = peers
    return graph


def find_cycles(graph: TopologyGraph) -> list[list[str]]:
    """Return simple cycles in *graph* (each as an ordered node list).

    Self-loops (an agent listing itself) are returned as a single-node cycle.
    Edges to nodes absent from *graph* (external peers) are ignored. Each
    distinct cycle (by node set) is reported once.
    """
    color: dict[str, int] = dict.fromkeys(graph, _WHITE)
    stack: list[str] = []
    cycles: list[list[str]] = []
    seen: set[frozenset[str]] = set()

    def visit(node: str) -> None:
        color[node] = _GRAY
        stack.append(node)
        for nxt in graph.get(node, []):
            if nxt not in color:
                # External / unknown peer — not part of this graph.
                continue
            if color[nxt] == _GRAY:
                cycle = stack[stack.index(nxt):]
                key = frozenset(cycle)
                if key not in seen:
                    seen.add(key)
                    cycles.append(list(cycle))
            elif color[nxt] == _WHITE:
                visit(nxt)
        stack.pop()
        color[node] = _BLACK

    for node in graph:
        if color[node] == _WHITE:
            visit(node)
    return cycles
