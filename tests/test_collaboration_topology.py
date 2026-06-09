"""Tests for declared-topology graph + cycle detection (RFC-005 §10.1)."""

from zil.collaboration.topology import (
    build_topology_graph,
    find_cycles,
    manifest_agent_name,
)


def _manifest(name, peers):
    return {
        "metadata": {"name": name},
        "spec": {"collaborators": [{"name": p} for p in peers]},
    }


class TestBuildTopologyGraph:
    def test_maps_name_to_collaborators(self):
        graph = build_topology_graph([
            _manifest("a", ["b", "c"]),
            _manifest("b", []),
        ])
        assert graph == {"a": ["b", "c"], "b": []}

    def test_skips_manifest_without_name(self):
        graph = build_topology_graph([{"spec": {"collaborators": [{"name": "x"}]}}])
        assert graph == {}

    def test_ignores_unnamed_collaborators(self):
        graph = build_topology_graph([
            {"metadata": {"name": "a"}, "spec": {"collaborators": [{"url": "u"}]}},
        ])
        assert graph == {"a": []}

    def test_manifest_agent_name_helper(self):
        assert manifest_agent_name({"metadata": {"name": "a"}}) == "a"
        assert manifest_agent_name({}) is None


class TestFindCycles:
    def test_acyclic_returns_none(self):
        graph = {"a": ["b"], "b": ["c"], "c": []}
        assert find_cycles(graph) == []

    def test_detects_self_loop(self):
        assert find_cycles({"a": ["a"]}) == [["a"]]

    def test_detects_two_node_cycle(self):
        cycles = find_cycles({"a": ["b"], "b": ["a"]})
        assert len(cycles) == 1
        assert set(cycles[0]) == {"a", "b"}

    def test_ignores_external_peers(self):
        # 'b' is not a known agent (no manifest) — edge ignored, no cycle.
        assert find_cycles({"a": ["b"]}) == []

    def test_reports_each_cycle_once(self):
        # a->b->a reachable from both nodes; reported a single time.
        cycles = find_cycles({"a": ["b"], "b": ["a"]})
        assert len(cycles) == 1
