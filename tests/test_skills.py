"""Tests for skills support: schema, loader, validator, agent builder, and init scaffold."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from zil.schema.loader import validate_project
from zil.sdk.loader import AgentSpec, load_project

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_SKILL_MD = """\
---
name: {name}
description: A test skill that does something useful for agents.
license: Apache-2.0
---

# {name}

## Steps

1. Do something.
"""


def _make_skill_dir(parent: Path, name: str) -> Path:
    """Create a minimal valid skill directory at parent/<name>/SKILL.md."""
    skill_dir = parent / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(_VALID_SKILL_MD.format(name=name), encoding="utf-8")
    return skill_dir


def _base_manifest(extras: dict | None = None) -> dict:
    m = {
        "apiVersion": "zil/v1",
        "kind": "Agent",
        "metadata": {"name": "test-agent", "version": "0.1.0"},
        "spec": {
            "runtime": {
                "framework": "adk",
                "language": "python",
                "llm": {"adapter": "./adapters/llm.yaml"},
            },
            "identity": "./identity",
        },
    }
    if extras:
        m["spec"].update(extras)
    return m


def _write_project(tmp_path: Path, manifest: dict) -> Path:
    (tmp_path / "manifest.yaml").write_text(yaml.dump(manifest))
    adapters = tmp_path / "adapters"
    adapters.mkdir(exist_ok=True)
    (adapters / "llm.yaml").write_text(
        yaml.dump({"provider": "anthropic", "model": "claude-sonnet-4-20250514"})
    )
    identity = tmp_path / "identity"
    identity.mkdir(exist_ok=True)
    (identity / "persona.md").write_text("# Agent")
    (identity / "instructions.md").write_text("# Instructions")
    (identity / "guardrails.yaml").write_text(
        yaml.dump({"detection": {"prompt_injection": True, "pii_output": True}})
    )
    return tmp_path


# ---------------------------------------------------------------------------
# 1. JSON Schema — agentTools.skills
# ---------------------------------------------------------------------------

class TestSkillsSchema:
    def _load_schema(self) -> dict:
        from zil.schema.loader import load_schema
        return load_schema()

    def test_agent_tools_skills_field_present(self):
        """agentTools.$defs has a skills array property."""
        schema = self._load_schema()
        agent_tools = schema["$defs"]["agentTools"]
        assert "skills" in agent_tools["properties"]
        assert agent_tools["properties"]["skills"]["type"] == "array"

    def test_agent_tools_skills_items_are_strings(self):
        schema = self._load_schema()
        items = schema["$defs"]["agentTools"]["properties"]["skills"]["items"]
        assert items["type"] == "string"

    def test_manifest_with_agent_skills_passes_schema_validation(self, tmp_path):
        """A manifest with agents having tools.skills passes JSON schema."""
        m = _base_manifest()
        m["spec"]["agents"] = [
            {
                "name": "vta",
                "identity": "./agents/vta/identity",
                "tools": {"skills": ["fd-explore-repo"]},
            }
        ]
        proj = _write_project(tmp_path, m)
        d = proj / "agents" / "vta" / "identity"
        d.mkdir(parents=True)
        (d / "instructions.md").write_text("instructions")

        result = validate_project(proj)
        fail_msgs = [c.message for c in result.checks if c.status == "fail"]
        schema_fails = [m for m in fail_msgs if "schema" in m.lower()]
        assert not schema_fails, f"Schema validation failed: {schema_fails}"

    def test_spec_skills_string_field_in_schema(self):
        """spec.skills is a string type in the top-level spec."""
        schema = self._load_schema()
        spec_props = schema["properties"]["spec"]["properties"]
        assert "skills" in spec_props
        assert spec_props["skills"]["type"] == "string"


# ---------------------------------------------------------------------------
# 2. SDK Loader — AgentSpec.skill_names + ProjectContext.skills_dir
# ---------------------------------------------------------------------------

class TestSkillsLoader:
    def _multi_skill_project(self, tmp_path: Path) -> Path:
        """Project with spec.skills dir and two sub-agents with skill allowlists."""
        m = {
            "apiVersion": "zil/v1",
            "kind": "Agent",
            "metadata": {"name": "svt-agent", "version": "0.1.0"},
            "spec": {
                "runtime": {
                    "framework": "adk",
                    "language": "python",
                    "llm": {"adapter": "./adapters/llm.yaml"},
                },
                "identity": "./identity",
                "skills": "./skills",
                "agents": [
                    {
                        "name": "vta",
                        "identity": "./agents/vta/identity",
                        "tools": {"skills": ["fd-explore-repo", "fd-read-jira-task"]},
                    },
                    {
                        "name": "vtd",
                        "identity": "./agents/vtd/identity",
                        "tools": {"skills": ["fd-submit-changes"]},
                    },
                ],
            },
        }
        (tmp_path / "manifest.yaml").write_text(yaml.dump(m))
        (tmp_path / "adapters").mkdir()
        (tmp_path / "adapters" / "llm.yaml").write_text(
            yaml.dump({"provider": "anthropic", "model": "claude-sonnet-4-20250514"})
        )
        id_dir = tmp_path / "identity"
        id_dir.mkdir()
        (id_dir / "persona.md").write_text("persona")
        (id_dir / "instructions.md").write_text("instructions")
        for name in ("vta", "vtd"):
            d = tmp_path / "agents" / name / "identity"
            d.mkdir(parents=True)
            (d / "instructions.md").write_text(f"# {name}")

        # Create skills directory
        skills_dir = tmp_path / "skills"
        for skill in ("fd-explore-repo", "fd-read-jira-task", "fd-submit-changes"):
            _make_skill_dir(skills_dir, skill)

        return tmp_path

    def test_skills_dir_loaded_into_context(self, tmp_path):
        proj = self._multi_skill_project(tmp_path)
        ctx = load_project(proj)
        assert ctx.skills_dir is not None
        assert ctx.skills_dir.name == "skills"

    def test_skills_dir_is_absolute(self, tmp_path):
        proj = self._multi_skill_project(tmp_path)
        ctx = load_project(proj)
        assert ctx.skills_dir.is_absolute()

    def test_skill_names_loaded_on_vta(self, tmp_path):
        proj = self._multi_skill_project(tmp_path)
        ctx = load_project(proj)
        vta = next(a for a in ctx.agents if a.name == "vta")
        assert vta.skill_names == ["fd-explore-repo", "fd-read-jira-task"]

    def test_skill_names_loaded_on_vtd(self, tmp_path):
        proj = self._multi_skill_project(tmp_path)
        ctx = load_project(proj)
        vtd = next(a for a in ctx.agents if a.name == "vtd")
        assert vtd.skill_names == ["fd-submit-changes"]

    def test_no_skills_declared_gives_empty_list(self, tmp_path):
        """Agent with no tools.skills gives empty skill_names."""
        m = _base_manifest()
        m["spec"]["agents"] = [
            {"name": "vta", "identity": "./agents/vta/identity"}
        ]
        proj = _write_project(tmp_path, m)
        d = proj / "agents" / "vta" / "identity"
        d.mkdir(parents=True)
        (d / "instructions.md").write_text("instructions")

        ctx = load_project(proj)
        vta = next(a for a in ctx.agents if a.name == "vta")
        assert vta.skill_names == []

    def test_no_spec_skills_gives_none_skills_dir(self, tmp_path):
        """When spec.skills is not declared, skills_dir is None."""
        m = _base_manifest()
        proj = _write_project(tmp_path, m)
        ctx = load_project(proj)
        assert ctx.skills_dir is None

    def test_spec_skills_path_missing_gives_none(self, tmp_path):
        """When spec.skills points to a non-existent dir, skills_dir is None."""
        m = _base_manifest()
        m["spec"]["skills"] = "./skills"  # dir not created
        proj = _write_project(tmp_path, m)
        ctx = load_project(proj)
        assert ctx.skills_dir is None

    def test_agent_spec_default_skill_names_is_list(self):
        """AgentSpec.skill_names defaults to an empty list, not None."""
        spec = AgentSpec(
            name="test",
            role="sub-agent",
            identity=None,  # type: ignore[arg-type]
            identity_path=Path("."),
            llm_adapter={},
            model_env_var=None,
            mcp_server_names=[],
            description="test",
        )
        assert spec.skill_names == []
        assert isinstance(spec.skill_names, list)


# ---------------------------------------------------------------------------
# 3. Schema Validator — _check_skills()
# ---------------------------------------------------------------------------

class TestSkillsValidator:
    def test_spec_skills_dir_present_passes(self, tmp_path):
        """Valid spec.skills dir with real skills produces a pass check."""
        m = _base_manifest()
        m["spec"]["skills"] = "./skills"
        proj = _write_project(tmp_path, m)
        skills_dir = proj / "skills"
        _make_skill_dir(skills_dir, "fd-explore-repo")

        result = validate_project(proj)
        pass_msgs = " ".join(c.message for c in result.checks if c.status == "pass")
        assert "spec.skills" in pass_msgs
        assert "fd-explore-repo" in pass_msgs

    def test_spec_skills_dir_missing_warns(self, tmp_path):
        """Declared spec.skills dir that doesn't exist produces a warning."""
        m = _base_manifest()
        m["spec"]["skills"] = "./skills"
        proj = _write_project(tmp_path, m)
        # Do NOT create skills dir

        result = validate_project(proj)
        warn_msgs = [c.message for c in result.checks if c.status == "warn"]
        assert any("spec.skills" in msg and "not found" in msg for msg in warn_msgs)

    def test_unknown_skill_name_in_agent_warns(self, tmp_path):
        """Sub-agent referencing a skill not in spec.skills dir warns."""
        m = _base_manifest()
        m["spec"]["skills"] = "./skills"
        m["spec"]["agents"] = [
            {
                "name": "vtd",
                "identity": "./agents/vtd/identity",
                "tools": {"skills": ["nonexistent-skill"]},
            }
        ]
        proj = _write_project(tmp_path, m)
        d = proj / "agents" / "vtd" / "identity"
        d.mkdir(parents=True)
        (d / "instructions.md").write_text("instructions")
        _make_skill_dir(proj / "skills", "fd-submit-changes")

        result = validate_project(proj)
        warn_msgs = [c.message for c in result.checks if c.status == "warn"]
        assert any("nonexistent-skill" in msg for msg in warn_msgs)

    def test_known_skill_name_does_not_warn(self, tmp_path):
        """Sub-agent referencing a valid skill does not warn."""
        m = _base_manifest()
        m["spec"]["skills"] = "./skills"
        m["spec"]["agents"] = [
            {
                "name": "vta",
                "identity": "./agents/vta/identity",
                "tools": {"skills": ["fd-explore-repo"]},
            }
        ]
        proj = _write_project(tmp_path, m)
        d = proj / "agents" / "vta" / "identity"
        d.mkdir(parents=True)
        (d / "instructions.md").write_text("instructions")
        _make_skill_dir(proj / "skills", "fd-explore-repo")

        result = validate_project(proj)
        warn_msgs = [c.message for c in result.checks if c.status == "warn"]
        skill_warns = [m for m in warn_msgs if "fd-explore-repo" in m and "skills" in m.lower()]
        assert not skill_warns

    def test_no_spec_skills_skips_check(self, tmp_path):
        """If spec.skills is not declared, no skill checks are emitted."""
        m = _base_manifest()
        proj = _write_project(tmp_path, m)

        result = validate_project(proj)
        all_msgs = " ".join(c.message for c in result.checks)
        assert "spec.skills" not in all_msgs

    def test_skills_count_in_pass_message(self, tmp_path):
        """Pass message includes the count of discovered skills."""
        m = _base_manifest()
        m["spec"]["skills"] = "./skills"
        proj = _write_project(tmp_path, m)
        skills_dir = proj / "skills"
        _make_skill_dir(skills_dir, "fd-explore-repo")
        _make_skill_dir(skills_dir, "fd-submit-changes")

        result = validate_project(proj)
        pass_msgs = " ".join(c.message for c in result.checks if c.status == "pass")
        assert "2 skill" in pass_msgs

    def test_skills_dir_without_skill_md_not_counted(self, tmp_path):
        """A subdir without SKILL.md is not counted as a skill."""
        m = _base_manifest()
        m["spec"]["skills"] = "./skills"
        proj = _write_project(tmp_path, m)
        skills_dir = proj / "skills"
        (skills_dir / "not-a-skill").mkdir(parents=True)  # no SKILL.md
        _make_skill_dir(skills_dir, "fd-explore-repo")

        result = validate_project(proj)
        pass_msgs = " ".join(c.message for c in result.checks if c.status == "pass")
        assert "1 skill" in pass_msgs

    def test_multiple_agents_with_mixed_skill_validity(self, tmp_path):
        """One agent has valid skills, another has an unknown skill — only unknown warns."""
        m = _base_manifest()
        m["spec"]["skills"] = "./skills"
        m["spec"]["agents"] = [
            {
                "name": "vta",
                "identity": "./agents/vta/identity",
                "tools": {"skills": ["fd-explore-repo"]},
            },
            {
                "name": "vtd",
                "identity": "./agents/vtd/identity",
                "tools": {"skills": ["fd-missing"]},
            },
        ]
        proj = _write_project(tmp_path, m)
        for name in ("vta", "vtd"):
            d = proj / "agents" / name / "identity"
            d.mkdir(parents=True)
            (d / "instructions.md").write_text("instructions")
        _make_skill_dir(proj / "skills", "fd-explore-repo")

        result = validate_project(proj)
        warn_msgs = [c.message for c in result.checks if c.status == "warn"]
        assert any("fd-missing" in m for m in warn_msgs)
        assert not any("fd-explore-repo" in m and "not found" in m for m in warn_msgs)


# ---------------------------------------------------------------------------
# 4. SDK Agent builder — _load_skills() and SkillToolset wiring
# ---------------------------------------------------------------------------

class TestLoadSkills:
    def test_load_skills_none_returns_empty(self):
        from zil.sdk.agent import _load_skills
        assert _load_skills(None) == {}

    def test_load_skills_missing_dir_returns_empty(self, tmp_path):
        from zil.sdk.agent import _load_skills
        missing = tmp_path / "does-not-exist"
        result = _load_skills(missing)
        assert result == {}

    def test_load_skills_empty_dir_returns_empty(self, tmp_path):
        from zil.sdk.agent import _load_skills
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        result = _load_skills(skills_dir)
        assert result == {}

    def test_load_skills_ignores_dirs_without_skill_md(self, tmp_path):
        from zil.sdk.agent import _load_skills
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "not-a-skill").mkdir()
        result = _load_skills(skills_dir)
        assert result == {}

    def test_load_skills_loads_valid_skill(self, tmp_path):
        """_load_skills returns a populated index when google-adk is available."""
        from zil.sdk.agent import _load_skills
        skills_dir = tmp_path / "skills"
        _make_skill_dir(skills_dir, "fd-explore-repo")
        try:
            result = _load_skills(skills_dir)
            assert "fd-explore-repo" in result
        except ImportError:
            pytest.skip("google-adk not installed")

    def test_load_skills_indexes_by_skill_name(self, tmp_path):
        """The index key is the skill's frontmatter name, not the dir name."""
        from zil.sdk.agent import _load_skills
        skills_dir = tmp_path / "skills"
        _make_skill_dir(skills_dir, "fd-explore-repo")
        try:
            result = _load_skills(skills_dir)
            for key, skill in result.items():
                assert key == skill.name
        except ImportError:
            pytest.skip("google-adk not installed")

    def test_load_skills_loads_multiple_skills(self, tmp_path):
        from zil.sdk.agent import _load_skills
        skills_dir = tmp_path / "skills"
        for name in ("fd-explore-repo", "fd-submit-changes", "fd-run-tests"):
            _make_skill_dir(skills_dir, name)
        try:
            result = _load_skills(skills_dir)
            assert len(result) == 3
        except ImportError:
            pytest.skip("google-adk not installed")


# ---------------------------------------------------------------------------
# 5. Init scaffold — --skills flag
# ---------------------------------------------------------------------------

class TestSkillsInitScaffold:
    def _make_config(self, skill_names=None, agent_names=None):
        from zil.commands.init import InitConfig
        return InitConfig(
            name="team-agent",
            framework="adk",
            language="python",
            llm_provider="gemini",
            eval_framework="deepeval",
            deploy_target="cloud-run",
            include_evals=False,
            include_otel=False,
            mcp_preset=None,
            agent_names=agent_names or [],
            skill_names=skill_names or [],
        )

    def test_manifest_contains_skills_line_when_skill_names_set(self):
        from zil.templates.files import _manifest
        config = self._make_config(skill_names=["fd-submit-changes"])
        content = _manifest(config)
        assert "skills: ./skills" in content

    def test_manifest_comments_out_skills_when_no_skill_names(self):
        from zil.templates.files import _manifest
        config = self._make_config()
        content = _manifest(config)
        assert "# skills: ./skills" in content
        assert "skills: ./skills" not in content.replace("# skills: ./skills", "")

    def test_render_skill_files_creates_skills_dir(self, tmp_path):
        from zil.templates.files import _render_skill_files
        config = self._make_config(skill_names=["fd-submit-changes"])
        _render_skill_files(tmp_path, config)
        assert (tmp_path / "skills").is_dir()

    def test_render_skill_files_creates_skill_md(self, tmp_path):
        from zil.templates.files import _render_skill_files
        config = self._make_config(skill_names=["fd-submit-changes"])
        _render_skill_files(tmp_path, config)
        assert (tmp_path / "skills" / "fd-submit-changes" / "SKILL.md").is_file()

    def test_render_skill_files_creates_multiple_skills(self, tmp_path):
        from zil.templates.files import _render_skill_files
        config = self._make_config(skill_names=["fd-submit-changes", "fd-run-tests"])
        _render_skill_files(tmp_path, config)
        assert (tmp_path / "skills" / "fd-submit-changes" / "SKILL.md").is_file()
        assert (tmp_path / "skills" / "fd-run-tests" / "SKILL.md").is_file()

    def test_render_skill_files_no_op_when_no_skills(self, tmp_path):
        from zil.templates.files import _render_skill_files
        config = self._make_config()
        _render_skill_files(tmp_path, config)
        assert not (tmp_path / "skills").exists()

    def test_skill_md_contains_valid_frontmatter(self, tmp_path):
        from zil.templates.files import _render_skill_files
        config = self._make_config(skill_names=["my-skill"])
        _render_skill_files(tmp_path, config)
        content = (tmp_path / "skills" / "my-skill" / "SKILL.md").read_text()
        assert content.startswith("---")
        assert "name: my-skill" in content
        assert "description:" in content

    def test_skill_md_template_has_required_frontmatter_fields(self):
        from zil.templates.files import _skill_md_template
        content = _skill_md_template("test-skill")
        assert "name: test-skill" in content
        assert "description:" in content
        assert content.startswith("---")

    def test_agents_block_includes_skills_hint_when_skill_names_set(self):
        from zil.templates.files import _manifest_agents_block
        config = self._make_config(agent_names=["vta"], skill_names=["fd-explore-repo"])
        content = _manifest_agents_block(config)
        assert "skills" in content
        assert "fd-explore-repo" in content

    def test_agents_block_no_skills_hint_when_no_skill_names(self):
        from zil.templates.files import _manifest_agents_block
        config = self._make_config(agent_names=["vta"])
        content = _manifest_agents_block(config)
        assert "fd-explore-repo" not in content

    def test_init_config_skill_names_defaults_to_empty_list(self):
        from zil.commands.init import InitConfig
        config = InitConfig(
            name="x", framework="adk", language="python",
            llm_provider="gemini", eval_framework="deepeval",
            deploy_target="cloud-run", include_evals=False, include_otel=False,
        )
        assert config.skill_names == []
        assert isinstance(config.skill_names, list)

    def test_render_extra_files_calls_render_skill_files(self, tmp_path):
        """_render_extra_files creates skills/ when skill_names is set."""
        from zil.templates.files import _render_extra_files
        config = self._make_config(skill_names=["fd-submit-changes"])
        _render_extra_files(tmp_path, config)
        assert (tmp_path / "skills" / "fd-submit-changes" / "SKILL.md").is_file()
