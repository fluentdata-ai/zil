"""Tests for the `zil topology` command (RFC-005 §10.1)."""

import json

import yaml
from click.testing import CliRunner

from zil.commands.topology import _load_manifests, topology


def _write_agent(root, name, peers):
    agent_dir = root / name
    agent_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "version": "1",
        "metadata": {"name": name, "version": "1.0.0"},
        "spec": {"collaborators": [{"name": p, "url": f"https://{p}"} for p in peers]},
    }
    (agent_dir / "manifest.yaml").write_text(yaml.dump(manifest))


class TestLoadManifests:
    def test_loads_nested_manifests(self, tmp_path):
        _write_agent(tmp_path, "a", ["b"])
        _write_agent(tmp_path, "b", [])
        manifests = _load_manifests(tmp_path)
        names = {m["metadata"]["name"] for m in manifests}
        assert names == {"a", "b"}

    def test_skips_invalid_yaml(self, tmp_path):
        (tmp_path / "manifest.yaml").write_text("name: : : bad")
        # Invalid YAML is skipped rather than raising.
        assert _load_manifests(tmp_path) == []


class TestTopologyCommand:
    def test_acyclic_exits_zero(self, tmp_path):
        _write_agent(tmp_path, "a", ["b"])
        _write_agent(tmp_path, "b", [])
        result = CliRunner().invoke(topology, ["--dir", str(tmp_path)])
        assert result.exit_code == 0
        assert "No cycles detected" in result.output
        assert "a" in result.output and "b" in result.output

    def test_cycle_exits_one(self, tmp_path):
        _write_agent(tmp_path, "a", ["b"])
        _write_agent(tmp_path, "b", ["a"])
        result = CliRunner().invoke(topology, ["--dir", str(tmp_path)])
        assert result.exit_code == 1
        assert "cycle(s) detected" in result.output

    def test_json_output(self, tmp_path):
        _write_agent(tmp_path, "a", ["b"])
        _write_agent(tmp_path, "b", ["a"])
        result = CliRunner().invoke(
            topology, ["--dir", str(tmp_path), "--format", "json"]
        )
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["graph"]["a"] == ["b"]
        assert payload["cycles"]

    def test_no_manifests_is_clean(self, tmp_path):
        result = CliRunner().invoke(topology, ["--dir", str(tmp_path)])
        assert result.exit_code == 0
        assert "No agent manifests" in result.output
