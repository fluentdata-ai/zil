"""Tests for zil pack, inspect, and packaging module."""

from __future__ import annotations

import json
import tarfile
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from zil.cli import cli

runner = CliRunner()


@pytest.fixture
def zil_project(tmp_path: Path) -> Path:
    """Create a minimal zil project for testing."""
    project = tmp_path / "test-agent"
    project.mkdir()

    # manifest.yaml
    manifest = {
        "apiVersion": "zil/v1",
        "kind": "Agent",
        "metadata": {
            "name": "test-agent",
            "version": "1.0.0",
            "description": "A test agent.",
        },
        "spec": {
            "runtime": {
                "framework": "adk",
                "language": "python",
                "llm": {"adapter": "./adapters/llm.yaml"},
            },
            "identity": "./identity",
            "evals": "./evals",
            "observability": "./observability",
        },
    }
    (project / "manifest.yaml").write_text(yaml.dump(manifest))

    # identity/
    identity = project / "identity"
    identity.mkdir()
    (identity / "persona.md").write_text("# Test Agent\n")
    (identity / "instructions.md").write_text("# Instructions\n")
    (identity / "guardrails.yaml").write_text(yaml.dump({"rules": []}))

    # adapters/
    adapters = project / "adapters"
    adapters.mkdir()
    (adapters / "llm.yaml").write_text(yaml.dump({"provider": "gemini"}))

    # evals/
    evals = project / "evals"
    evals.mkdir()
    (evals / "baseline.yaml").write_text(yaml.dump({"eval_suite": {"name": "baseline"}}))

    # observability/
    obs = project / "observability"
    obs.mkdir()
    (obs / "config.yaml").write_text(yaml.dump({"tracing": {"exporter": "otlp"}}))

    # module directory
    module = project / "test_agent"
    module.mkdir()
    (module / "__init__.py").write_text("")
    (module / "agent.py").write_text("root_agent = None\n")

    # requirements.txt
    (project / "requirements.txt").write_text(
        "zil-ai[adk]>=0.1.6\ndeepeval>=2.0\n"
    )

    return project


class TestBuildArchive:
    """Test archive creation."""

    def test_creates_archive(self, zil_project: Path) -> None:
        from zil.packaging.archive import build_archive

        out = zil_project / "dist"
        archive = build_archive(zil_project, out)

        assert archive.exists()
        assert archive.name == "test-agent-1.0.0.zil"
        assert archive.suffix == ".zil"

    def test_archive_contains_manifest(self, zil_project: Path) -> None:
        from zil.packaging.archive import build_archive

        out = zil_project / "dist"
        archive = build_archive(zil_project, out)

        with tarfile.open(archive, "r:gz") as tar:
            names = tar.getnames()
            assert "manifest.yaml" in names

    def test_archive_contains_identity(self, zil_project: Path) -> None:
        from zil.packaging.archive import build_archive

        out = zil_project / "dist"
        archive = build_archive(zil_project, out)

        with tarfile.open(archive, "r:gz") as tar:
            names = tar.getnames()
            assert "identity/persona.md" in names
            assert "identity/instructions.md" in names
            assert "identity/guardrails.yaml" in names

    def test_archive_contains_module(self, zil_project: Path) -> None:
        from zil.packaging.archive import build_archive

        out = zil_project / "dist"
        archive = build_archive(zil_project, out)

        with tarfile.open(archive, "r:gz") as tar:
            names = tar.getnames()
            assert "test_agent/__init__.py" in names
            assert "test_agent/agent.py" in names

    def test_archive_contains_sbom(self, zil_project: Path) -> None:
        from zil.packaging.archive import build_archive
        from zil.packaging.sbom import generate_sbom

        sbom = generate_sbom(zil_project, "test-agent", "1.0.0")
        out = zil_project / "dist"
        archive = build_archive(zil_project, out, sbom=sbom)

        with tarfile.open(archive, "r:gz") as tar:
            names = tar.getnames()
            assert "SBOM.cyclonedx.json" in names
            f = tar.extractfile(tar.getmember("SBOM.cyclonedx.json"))
            assert f is not None
            data = json.loads(f.read())
            assert data["bomFormat"] == "CycloneDX"

    def test_archive_contains_eval_results(self, zil_project: Path) -> None:
        from zil.packaging.archive import build_archive

        eval_results = {"score": 0.92, "threshold": 0.85, "passed": True}
        out = zil_project / "dist"
        archive = build_archive(zil_project, out, eval_results=eval_results)

        with tarfile.open(archive, "r:gz") as tar:
            f = tar.extractfile(tar.getmember("EVAL_RESULTS.json"))
            assert f is not None
            data = json.loads(f.read())
            assert data["score"] == 0.92

    def test_archive_contains_build_meta(self, zil_project: Path) -> None:
        from zil.packaging.archive import build_archive

        out = zil_project / "dist"
        archive = build_archive(zil_project, out)

        with tarfile.open(archive, "r:gz") as tar:
            f = tar.extractfile(tar.getmember("BUILD_META.json"))
            assert f is not None
            data = json.loads(f.read())
            assert data["name"] == "test-agent"
            assert data["version"] == "1.0.0"
            assert data["builder"] == "zil-ai"

    def test_missing_manifest_raises(self, tmp_path: Path) -> None:
        from zil.packaging.archive import build_archive

        with pytest.raises(FileNotFoundError, match="manifest.yaml"):
            build_archive(tmp_path, tmp_path / "dist")


class TestReadArchive:
    """Test archive reading."""

    def test_reads_metadata(self, zil_project: Path) -> None:
        from zil.packaging.archive import build_archive, read_archive
        from zil.packaging.sbom import generate_sbom

        sbom = generate_sbom(zil_project, "test-agent", "1.0.0")
        out = zil_project / "dist"
        archive = build_archive(zil_project, out, sbom=sbom)

        meta = read_archive(archive)
        assert meta.name == "test-agent"
        assert meta.version == "1.0.0"
        assert meta.description == "A test agent."
        assert meta.framework == "adk"
        assert meta.language == "python"
        assert meta.sbom_dependency_count == 2
        assert meta.archive_size > 0
        assert meta.created_at != ""

    def test_reads_eval_results(self, zil_project: Path) -> None:
        from zil.packaging.archive import build_archive, read_archive

        eval_results = {"score": 0.95, "threshold": 0.85, "passed": True}
        out = zil_project / "dist"
        archive = build_archive(zil_project, out, eval_results=eval_results)

        meta = read_archive(archive)
        assert meta.eval_score == 0.95
        assert meta.eval_threshold == 0.85

    def test_lists_components(self, zil_project: Path) -> None:
        from zil.packaging.archive import build_archive, read_archive

        out = zil_project / "dist"
        archive = build_archive(zil_project, out)

        meta = read_archive(archive)
        assert "manifest.yaml" in meta.components
        assert "identity" in meta.components
        assert "test_agent" in meta.components


class TestExtractArchive:
    """Test archive extraction."""

    def test_extracts_to_directory(self, zil_project: Path, tmp_path: Path) -> None:
        from zil.packaging.archive import build_archive, extract_archive

        out = zil_project / "dist"
        archive = build_archive(zil_project, out)

        target = tmp_path / "extracted"
        extract_archive(archive, target)

        assert (target / "manifest.yaml").exists()
        assert (target / "identity" / "persona.md").exists()
        assert (target / "test_agent" / "agent.py").exists()


class TestSBOM:
    """Test SBOM generation."""

    def test_generates_cyclonedx(self, zil_project: Path) -> None:
        from zil.packaging.sbom import generate_sbom

        sbom = generate_sbom(zil_project, "test-agent", "1.0.0")
        assert sbom["bomFormat"] == "CycloneDX"
        assert sbom["specVersion"] == "1.5"
        assert sbom["metadata"]["component"]["name"] == "test-agent"

    def test_parses_requirements(self, zil_project: Path) -> None:
        from zil.packaging.sbom import generate_sbom

        sbom = generate_sbom(zil_project, "test-agent", "1.0.0")
        components = sbom["components"]
        names = [c["name"] for c in components]
        assert "zil-ai" in names
        assert "deepeval" in names

    def test_empty_requirements(self, tmp_path: Path) -> None:
        from zil.packaging.sbom import generate_sbom

        sbom = generate_sbom(tmp_path, "empty", "0.0.1")
        assert sbom["components"] == []


class TestPackCommand:
    """Test the zil pack CLI command."""

    def test_pack_creates_archive(self, zil_project: Path) -> None:
        result = runner.invoke(
            cli,
            ["pack", "--project-dir", str(zil_project), "--skip-evals"],
        )
        assert result.exit_code == 0
        assert "Wrote:" in result.output

        archive = zil_project / "dist" / "test-agent-1.0.0.zil"
        assert archive.exists()

    def test_pack_custom_output_dir(self, zil_project: Path) -> None:
        out = zil_project / "custom-out"
        result = runner.invoke(
            cli,
            [
                "pack",
                "--project-dir", str(zil_project),
                "--output-dir", str(out),
                "--skip-evals",
            ],
        )
        assert result.exit_code == 0
        archive = out / "test-agent-1.0.0.zil"
        assert archive.exists()

    def test_pack_fails_on_invalid_project(self, tmp_path: Path) -> None:
        result = runner.invoke(
            cli,
            ["pack", "--project-dir", str(tmp_path), "--skip-evals"],
        )
        assert result.exit_code == 1
        assert "validation failed" in result.output.lower() or "not found" in result.output.lower()


class TestInspectCommand:
    """Test the zil inspect CLI command."""

    def test_inspect_shows_summary(self, zil_project: Path) -> None:
        # First pack
        runner.invoke(
            cli,
            ["pack", "--project-dir", str(zil_project), "--skip-evals"],
        )
        archive = zil_project / "dist" / "test-agent-1.0.0.zil"

        result = runner.invoke(cli, ["inspect", str(archive)])
        assert result.exit_code == 0
        assert "test-agent" in result.output
        assert "1.0.0" in result.output
        assert "Components" in result.output

    def test_inspect_json_output(self, zil_project: Path) -> None:
        runner.invoke(
            cli,
            ["pack", "--project-dir", str(zil_project), "--skip-evals"],
        )
        archive = zil_project / "dist" / "test-agent-1.0.0.zil"

        result = runner.invoke(cli, ["inspect", str(archive), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["name"] == "test-agent"
        assert data["version"] == "1.0.0"

    def test_inspect_show_file(self, zil_project: Path) -> None:
        runner.invoke(
            cli,
            ["pack", "--project-dir", str(zil_project), "--skip-evals"],
        )
        archive = zil_project / "dist" / "test-agent-1.0.0.zil"

        result = runner.invoke(cli, ["inspect", str(archive), "--show", "manifest.yaml"])
        assert result.exit_code == 0
        assert "apiVersion" in result.output

    def test_inspect_show_missing_file(self, zil_project: Path) -> None:
        runner.invoke(
            cli,
            ["pack", "--project-dir", str(zil_project), "--skip-evals"],
        )
        archive = zil_project / "dist" / "test-agent-1.0.0.zil"

        result = runner.invoke(cli, ["inspect", str(archive), "--show", "nonexistent.txt"])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_inspect_rejects_non_zil(self, tmp_path: Path) -> None:
        fake = tmp_path / "test.tar.gz"
        fake.write_bytes(b"fake")
        result = runner.invoke(cli, ["inspect", str(fake)])
        assert result.exit_code == 1
        assert "Expected a .zil archive" in result.output


class TestPushCommand:
    """Test the zil push CLI command (validation only — no real registry)."""

    def test_push_rejects_non_zil(self, tmp_path: Path) -> None:
        fake = tmp_path / "test.tar.gz"
        fake.write_bytes(b"fake")
        result = runner.invoke(
            cli,
            ["push", str(fake), "--registry", "us-docker.pkg.dev/proj/repo"],
        )
        assert result.exit_code == 1
        assert "Expected a .zil archive" in result.output


class TestEnvCoverage:
    """Test env cross-check during pack."""

    def test_coverage_pass(self, zil_project: Path) -> None:
        """Pack succeeds when .env.local vars match spec.env."""
        from zil.commands.pack import _check_env_coverage

        manifest = yaml.safe_load((zil_project / "manifest.yaml").read_text())
        manifest["spec"]["env"] = [
            {"name": "API_KEY", "required": True, "secret": True},
        ]
        (zil_project / "manifest.yaml").write_text(yaml.dump(manifest))

        # Put the var in module dir .env.local
        module_dir = zil_project / "test_agent"
        (module_dir / ".env.local").write_text("API_KEY=sk-test\n")

        coverage = _check_env_coverage(zil_project, manifest)
        assert coverage is not None
        assert "API_KEY" in coverage["resolved_locally"]
        assert coverage["missing_locally"] == []

    def test_coverage_undeclared_fails(self, zil_project: Path) -> None:
        """Pack fails when .env.local has vars not in spec.env."""
        from zil.commands.pack import _check_env_coverage

        manifest = yaml.safe_load((zil_project / "manifest.yaml").read_text())
        manifest["spec"]["env"] = [
            {"name": "API_KEY", "required": True},
        ]
        (zil_project / "manifest.yaml").write_text(yaml.dump(manifest))

        # .env.local has an extra undeclared var
        module_dir = zil_project / "test_agent"
        (module_dir / ".env.local").write_text("API_KEY=sk-test\nUNDECLARED_VAR=oops\n")

        with pytest.raises(SystemExit):
            _check_env_coverage(zil_project, manifest)

    def test_coverage_missing_warns(self, zil_project: Path, capsys) -> None:
        """Missing vars from env files produce warnings but don't fail."""
        from zil.commands.pack import _check_env_coverage

        manifest = yaml.safe_load((zil_project / "manifest.yaml").read_text())
        manifest["spec"]["env"] = [
            {"name": "API_KEY", "required": True, "secret": True},
            {"name": "OPTIONAL_VAR", "required": False},
        ]
        (zil_project / "manifest.yaml").write_text(yaml.dump(manifest))

        # Only provide one of two declared vars
        module_dir = zil_project / "test_agent"
        (module_dir / ".env.local").write_text("API_KEY=sk-test\n")

        coverage = _check_env_coverage(zil_project, manifest)
        assert coverage is not None
        assert "API_KEY" in coverage["resolved_locally"]
        assert "OPTIONAL_VAR" in coverage["missing_locally"]

    def test_coverage_in_build_meta(self, zil_project: Path) -> None:
        """env_coverage is written to BUILD_META.json in the archive."""
        from zil.packaging.archive import build_archive, read_archive

        manifest = yaml.safe_load((zil_project / "manifest.yaml").read_text())
        manifest["spec"]["env"] = [
            {"name": "MY_KEY", "required": True, "secret": True},
        ]
        (zil_project / "manifest.yaml").write_text(yaml.dump(manifest))

        env_coverage = {
            "declared": ["MY_KEY"],
            "resolved_locally": ["MY_KEY"],
            "missing_locally": [],
        }

        out = zil_project / "dist"
        archive = build_archive(zil_project, out, env_coverage=env_coverage)

        # Verify BUILD_META.json contains env_coverage
        with tarfile.open(archive, "r:gz") as tar:
            meta_file = tar.extractfile("BUILD_META.json")
            assert meta_file is not None
            build_meta = json.loads(meta_file.read())
            assert "env_coverage" in build_meta
            assert build_meta["env_coverage"]["declared"] == ["MY_KEY"]

        # Verify read_archive extracts it
        meta = read_archive(archive)
        assert meta.env_coverage is not None
        assert meta.env_coverage["resolved_locally"] == ["MY_KEY"]

    def test_no_spec_env_returns_none(self, zil_project: Path) -> None:
        """No spec.env means no cross-check (returns None)."""
        from zil.commands.pack import _check_env_coverage

        manifest = yaml.safe_load((zil_project / "manifest.yaml").read_text())
        # No spec.env key
        coverage = _check_env_coverage(zil_project, manifest)
        assert coverage is None
