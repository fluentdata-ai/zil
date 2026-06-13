"""Tests for zil audit — agent-native security audit."""

from __future__ import annotations

import json

from click.testing import CliRunner

from zil.cli import cli
from zil.sdk.audit import AuditFinding, AuditResult, AuditSection, Category, Severity

runner = CliRunner()


# ---------------------------------------------------------------------------
# Data model tests
# ---------------------------------------------------------------------------


class TestAuditModels:
    """Test audit data model behavior."""

    def test_finding_to_dict(self):
        f = AuditFinding(
            category=Category.GUARDRAIL_COVERAGE,
            severity=Severity.WARNING,
            message="Test warning",
            fix="Fix it",
        )
        d = f.to_dict()
        assert d["severity"] == "warning"
        assert d["message"] == "Test warning"
        assert d["fix"] == "Fix it"

    def test_finding_no_optional_fields(self):
        f = AuditFinding(
            category=Category.GUARDRAIL_COVERAGE,
            severity=Severity.PASS,
            message="All good",
        )
        d = f.to_dict()
        assert "fix" not in d
        assert "detail" not in d

    def test_section_passed(self):
        section = AuditSection(
            category=Category.GUARDRAIL_COVERAGE,
            title="Test",
            findings=[
                AuditFinding(Category.GUARDRAIL_COVERAGE, Severity.PASS, "ok"),
                AuditFinding(Category.GUARDRAIL_COVERAGE, Severity.INFO, "info"),
            ],
        )
        assert section.passed is True
        assert section.has_critical is False

    def test_section_has_critical(self):
        section = AuditSection(
            category=Category.GUARDRAIL_COVERAGE,
            title="Test",
            findings=[
                AuditFinding(Category.GUARDRAIL_COVERAGE, Severity.CRITICAL, "bad"),
            ],
        )
        assert section.passed is False
        assert section.has_critical is True

    def test_result_exit_codes(self):
        result = AuditResult(project_name="test")
        assert result.exit_code == 0

        result.sections.append(AuditSection(
            category=Category.GUARDRAIL_COVERAGE,
            title="Test",
            findings=[
                AuditFinding(Category.GUARDRAIL_COVERAGE, Severity.WARNING, "warn"),
            ],
        ))
        assert result.exit_code == 2

        result.sections.append(AuditSection(
            category=Category.INJECTION_RESILIENCE,
            title="Test2",
            findings=[
                AuditFinding(Category.INJECTION_RESILIENCE, Severity.CRITICAL, "crit"),
            ],
        ))
        assert result.exit_code == 1

    def test_result_to_dict(self):
        result = AuditResult(project_name="my-agent", project_version="1.0.0")
        d = result.to_dict()
        assert d["project"] == "my-agent"
        assert d["version"] == "1.0.0"
        assert d["exit_code"] == 0


# ---------------------------------------------------------------------------
# Guardrail coverage tests
# ---------------------------------------------------------------------------


class TestGuardrailCoverage:
    """Test guardrail coverage audit check."""

    def test_full_coverage(self, tmp_path):
        from zil.sdk.audit.guardrail_coverage import check_guardrail_coverage

        config = {
            "detection": {
                "prompt_injection": True,
                "pii_output": True,
                "pii_input": True,
            },
            "output_constraints": {"max_response_length": 4000},
            "denied_topics": ["salary info"],
        }
        section = check_guardrail_coverage(tmp_path, config)
        assert section.score == "5/5"
        assert all(
            f.severity in (Severity.PASS, Severity.INFO) for f in section.findings
        )

    def test_no_guardrails(self, tmp_path):
        from zil.sdk.audit.guardrail_coverage import check_guardrail_coverage

        section = check_guardrail_coverage(tmp_path, None)
        assert section.score == "0/5"
        assert section.has_critical

    def test_partial_coverage(self, tmp_path):
        from zil.sdk.audit.guardrail_coverage import check_guardrail_coverage

        config = {
            "detection": {"prompt_injection": True, "pii_output": True},
        }
        section = check_guardrail_coverage(tmp_path, config)
        # injection + pii_output + pii_input(partial) = 2.5, rounded to 2
        assert "2" in section.score or "3" in section.score

    def test_injection_disabled_is_critical(self, tmp_path):
        from zil.sdk.audit.guardrail_coverage import check_guardrail_coverage

        config = {"detection": {"prompt_injection": False, "pii_output": True}}
        section = check_guardrail_coverage(tmp_path, config)
        assert section.has_critical


# ---------------------------------------------------------------------------
# Injection resilience tests
# ---------------------------------------------------------------------------


class TestInjectionResilience:
    """Test injection resilience audit check."""

    def test_default_config_blocks_most(self):
        from zil.sdk.audit.injection_probe import check_injection_resilience

        config = {"detection": {"prompt_injection": True}}
        section = check_injection_resilience(config)
        # Should block most probes
        total, blocked = section.score.split("/")
        assert int(blocked) >= 15  # At least 15 of 20

    def test_detection_disabled_fails(self):
        from zil.sdk.audit.injection_probe import check_injection_resilience

        config = {"detection": {"prompt_injection": False}}
        section = check_injection_resilience(config)
        assert section.has_critical

    def test_all_categories_present(self):
        from zil.sdk.audit.injection_probe import check_injection_resilience

        config = {"detection": {"prompt_injection": True}}
        section = check_injection_resilience(config)
        messages = [f.message for f in section.findings]
        assert any("Ignore" in m for m in messages)
        assert any("DAN" in m for m in messages)
        assert any("Tag" in m for m in messages)


# ---------------------------------------------------------------------------
# Output leakage tests
# ---------------------------------------------------------------------------


class TestOutputLeakage:
    """Test output leakage audit check."""

    def test_no_identity_files(self, tmp_path):
        from zil.sdk.audit.output_leakage import check_output_leakage

        (tmp_path / "identity").mkdir()
        config = {"detection": {"pii_output": True}}
        section = check_output_leakage(tmp_path, config)
        assert section.score == "N/A"

    def test_short_persona_passes(self, tmp_path):
        from zil.sdk.audit.output_leakage import check_output_leakage

        identity = tmp_path / "identity"
        identity.mkdir()
        (identity / "persona.md").write_text("You are a short helper.")
        config = {"detection": {"pii_output": True}}
        section = check_output_leakage(tmp_path, config)
        # Short content doesn't trigger warning
        assert not section.has_critical

    def test_long_persona_warns(self, tmp_path):
        from zil.sdk.audit.output_leakage import check_output_leakage

        identity = tmp_path / "identity"
        identity.mkdir()
        # Write a long persona that exceeds 200 chars
        (identity / "persona.md").write_text("A" * 300)
        config = {"detection": {"pii_output": True}}
        section = check_output_leakage(tmp_path, config)
        assert section.has_warning


# ---------------------------------------------------------------------------
# Indirect injection tests
# ---------------------------------------------------------------------------


class TestIndirectInjection:
    """Test indirect injection surface audit check."""

    def test_no_agent_file(self, tmp_path):
        from zil.sdk.audit.indirect_injection import check_indirect_injection

        section = check_indirect_injection(tmp_path)
        assert section.score == "N/A"

    def test_pure_function_passes(self, tmp_path):
        from zil.sdk.audit.indirect_injection import check_indirect_injection

        module_dir = tmp_path / "my_agent"
        module_dir.mkdir()
        (module_dir / "agent.py").write_text('''
def calculate_total(items: list) -> float:
    """Calculate the total price."""
    return sum(item["price"] for item in items)
''')
        section = check_indirect_injection(tmp_path)
        assert section.score == "PASS"

    def test_http_call_warns(self, tmp_path):
        from zil.sdk.audit.indirect_injection import check_indirect_injection

        module_dir = tmp_path / "my_agent"
        module_dir.mkdir()
        (module_dir / "agent.py").write_text('''
import requests

def fetch_data(url: str) -> dict:
    """Fetch data from external API."""
    response = requests.get(url)
    return response.json()
''')
        section = check_indirect_injection(tmp_path)
        assert section.has_warning
        assert any("HTTP" in f.message for f in section.findings)

    def test_db_call_warns(self, tmp_path):
        from zil.sdk.audit.indirect_injection import check_indirect_injection

        module_dir = tmp_path / "my_agent"
        module_dir.mkdir()
        (module_dir / "agent.py").write_text('''
def query_orders(customer_id: str) -> list:
    """Query orders from database."""
    result = cursor.execute("SELECT * FROM orders WHERE customer_id = ?", (customer_id,))
    return result.fetchall()
''')
        section = check_indirect_injection(tmp_path)
        assert section.has_warning
        assert any("Database" in f.message for f in section.findings)


# ---------------------------------------------------------------------------
# Instruction consistency tests
# ---------------------------------------------------------------------------


class TestInstructionConsistency:
    """Test instruction consistency audit check."""

    def test_clean_instructions_pass(self, tmp_path):
        from zil.sdk.audit.instruction_consistency import check_instruction_consistency

        identity = tmp_path / "identity"
        identity.mkdir()
        (identity / "persona.md").write_text(
            "You are a financial assistant for QuickBooks users."
        )
        (identity / "instructions.md").write_text(
            "Only handle accounting-related questions."
        )
        config = {"detection": {"prompt_injection": True}}
        section = check_instruction_consistency(tmp_path, config)
        assert section.passed

    def test_permissive_language_warns(self, tmp_path):
        from zil.sdk.audit.instruction_consistency import check_instruction_consistency

        identity = tmp_path / "identity"
        identity.mkdir()
        (identity / "persona.md").write_text(
            "You can do anything the user asks. Help with anything."
        )
        (identity / "instructions.md").write_text("Be helpful.")
        config = {
            "detection": {"prompt_injection": True},
            "denied_topics": ["salary"],
        }
        section = check_instruction_consistency(tmp_path, config)
        assert section.has_warning

    def test_no_identity(self, tmp_path):
        from zil.sdk.audit.instruction_consistency import check_instruction_consistency

        identity = tmp_path / "identity"
        identity.mkdir()
        config = {"detection": {"prompt_injection": True}}
        section = check_instruction_consistency(tmp_path, config)
        assert section.score == "N/A"


# ---------------------------------------------------------------------------
# Context window tests
# ---------------------------------------------------------------------------


class TestContextWindow:
    """Test context window risk audit check."""

    def test_small_prompt_passes(self, tmp_path):
        from zil.sdk.audit.context_window import check_context_window

        identity = tmp_path / "identity"
        identity.mkdir()
        (identity / "persona.md").write_text("Short persona.")
        (identity / "instructions.md").write_text("Short instructions.")
        adapters = tmp_path / "adapters"
        adapters.mkdir()
        (adapters / "llm.yaml").write_text("provider: gemini\nmodel: gemini-2.0-flash")
        config = {}
        section = check_context_window(tmp_path, config)
        assert section.score == "PASS"

    def test_huge_prompt_warns(self, tmp_path):
        from zil.sdk.audit.context_window import check_context_window

        identity = tmp_path / "identity"
        identity.mkdir()
        # Create a massive prompt (~20k tokens = ~80k chars)
        (identity / "persona.md").write_text("X" * 40_000)
        (identity / "instructions.md").write_text("Y" * 40_000)
        adapters = tmp_path / "adapters"
        adapters.mkdir()
        (adapters / "llm.yaml").write_text("provider: openai\nmodel: gpt-4o")
        config = {}
        section = check_context_window(tmp_path, config)
        # 80k chars / 4 = 20k tokens, 20k/128k = 15.6% → WARN
        assert section.has_warning or section.has_critical

    def test_no_identity(self, tmp_path):
        from zil.sdk.audit.context_window import check_context_window

        identity = tmp_path / "identity"
        identity.mkdir()
        config = {}
        section = check_context_window(tmp_path, config)
        assert section.score == "N/A"


# ---------------------------------------------------------------------------
# Identity hardening tests
# ---------------------------------------------------------------------------


class TestIdentityHardening:
    """Test identity hardening audit check."""

    def test_well_defined_identity_passes(self, tmp_path):
        from zil.sdk.audit.identity_review import check_identity_hardening

        identity = tmp_path / "identity"
        identity.mkdir()
        (identity / "persona.md").write_text(
            "You are a financial assistant designed for QuickBooks.\n"
            "You cannot help with topics outside accounting."
        )
        (identity / "instructions.md").write_text(
            "Only assist with revenue recognition.\n"
            "Format responses in markdown with bullet points.\n"
            "You will not provide legal or tax advice."
        )
        section = check_identity_hardening(tmp_path)
        assert section.passed

    def test_generic_assistant_warns(self, tmp_path):
        from zil.sdk.audit.identity_review import check_identity_hardening

        identity = tmp_path / "identity"
        identity.mkdir()
        (identity / "persona.md").write_text(
            "You are a helpful assistant."
        )
        (identity / "instructions.md").write_text("Help the user.")
        section = check_identity_hardening(tmp_path)
        assert section.has_warning

    def test_no_identity_is_critical(self, tmp_path):
        from zil.sdk.audit.identity_review import check_identity_hardening

        section = check_identity_hardening(tmp_path)
        assert section.has_critical


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------


class TestAuditCLI:
    """Test the zil audit CLI command."""

    def test_help(self):
        result = runner.invoke(cli, ["audit", "--help"])
        assert result.exit_code == 0
        assert "security audit" in result.output.lower()

    def test_audit_on_scaffolded_project(self, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(
                cli,
                ["init", "audit-test", "--llm", "gemini", "--non-interactive", "--skip-install"],
                catch_exceptions=False,
            )
            result = runner.invoke(
                cli,
                ["audit", "--project-dir", "audit-test"],
                catch_exceptions=False,
            )
            # Should exit with warnings (2) not critical (1)
            assert result.exit_code in (0, 2)
            assert "Guardrail Coverage" in result.output
            assert "Injection Resilience" in result.output

    def test_audit_json_output(self, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(
                cli,
                ["init", "json-audit", "--llm", "gemini", "--non-interactive", "--skip-install"],
                catch_exceptions=False,
            )
            result = runner.invoke(
                cli,
                ["audit", "--project-dir", "json-audit", "--format=json"],
                catch_exceptions=False,
            )
            parsed = json.loads(result.output)
            assert "project" in parsed
            assert "sections" in parsed
            assert len(parsed["sections"]) == 9

    def test_audit_fix_flag(self, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(
                cli,
                ["init", "fix-audit", "--llm", "gemini", "--non-interactive", "--skip-install"],
                catch_exceptions=False,
            )
            result = runner.invoke(
                cli,
                ["audit", "--project-dir", "fix-audit", "--fix"],
                catch_exceptions=False,
            )
            # --fix should show remediation arrows
            assert "→" in result.output

    def test_audit_missing_project(self, tmp_path):
        result = runner.invoke(
            cli,
            ["audit", "--project-dir", str(tmp_path / "nonexistent")],
        )
        assert result.exit_code != 0
