"""Tests for the Zil evaluation engine."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from zil.sdk.eval.loader import (
    load_eval_engine_config,
    load_eval_suite,
)
from zil.sdk.eval.models import (
    CaseResult,
    CaseVerdict,
    EvalCase,
    EvalEngineConfig,
    GroupResult,
    SuiteResult,
)
from zil.sdk.eval.runner import run_eval_suite

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def eval_project(tmp_path: Path) -> Path:
    """Create a minimal project with eval files."""
    evals_dir = tmp_path / "evals"
    evals_dir.mkdir()
    cases_dir = evals_dir / "cases"
    cases_dir.mkdir()

    # evals/config.yaml
    config = {
        "eval_engine": {
            "framework": "deepeval",
            "judge": {"provider": "gemini", "model": "gemini-2.0-flash"},
        }
    }
    (evals_dir / "config.yaml").write_text(yaml.dump(config))

    # evals/baseline.yaml
    suite = {
        "eval_suite": {
            "name": "baseline",
            "pass_threshold": 0.85,
            "metrics": ["answer_relevancy"],
            "cases": [
                {"file": "./cases/accuracy.yaml", "weight": 0.6},
                {"file": "./cases/tool_use.yaml", "weight": 0.4},
            ],
        }
    }
    (evals_dir / "baseline.yaml").write_text(yaml.dump(suite))

    # evals/cases/accuracy.yaml
    accuracy = {
        "name": "accuracy",
        "cases": [
            {
                "input": "What is Zil?",
                "expected_output": "Zil is a framework for production AI agents",
                "expected_contains": ["framework", "agent"],
                "context": ["Zil is an open-source framework by FluentData"],
            },
            {
                "input": "Hello",
                "expected_contains": ["hello"],
                "metrics": [],
            },
        ],
    }
    (cases_dir / "accuracy.yaml").write_text(yaml.dump(accuracy))

    # evals/cases/tool_use.yaml
    tool_use = {
        "name": "tool_use",
        "cases": [
            {
                "input": "Look up order #12345",
                "expected_tool": "lookup_order",
                "expected_contains": ["order"],
            }
        ],
    }
    (cases_dir / "tool_use.yaml").write_text(yaml.dump(tool_use))

    return tmp_path


@pytest.fixture
def minimal_eval_project(tmp_path: Path) -> Path:
    """Create a project with only deterministic eval cases (no metrics)."""
    evals_dir = tmp_path / "evals"
    evals_dir.mkdir()
    cases_dir = evals_dir / "cases"
    cases_dir.mkdir()

    config = {"eval_engine": {"framework": "deepeval"}}
    (evals_dir / "config.yaml").write_text(yaml.dump(config))

    suite = {
        "eval_suite": {
            "name": "baseline",
            "pass_threshold": 0.80,
            "metrics": [],
            "cases": [
                {"file": "./cases/basic.yaml", "weight": 1.0},
            ],
        }
    }
    (evals_dir / "baseline.yaml").write_text(yaml.dump(suite))

    basic = {
        "name": "basic",
        "cases": [
            {"input": "Say hello", "expected_contains": ["hello"]},
            {"input": "What is 2+2?", "expected_contains": ["4"]},
        ],
    }
    (cases_dir / "basic.yaml").write_text(yaml.dump(basic))

    return tmp_path


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestModels:
    """Test data model construction and properties."""

    def test_suite_result_properties(self) -> None:
        case1 = CaseResult(
            case=EvalCase(input="test1"),
            verdict=CaseVerdict.PASS,
            actual_output="response",
            score=1.0,
        )
        case2 = CaseResult(
            case=EvalCase(input="test2"),
            verdict=CaseVerdict.FAIL,
            actual_output="bad",
            score=0.0,
        )
        group = GroupResult(
            name="test_group",
            weight=1.0,
            pass_rate=0.5,
            case_results=[case1, case2],
        )
        result = SuiteResult(
            suite_name="test",
            score=0.5,
            passed=False,
            threshold=0.85,
            group_results=[group],
        )
        assert result.total_cases == 2
        assert result.passed_cases == 1
        assert result.failed_cases == 1

    def test_eval_engine_config_defaults(self) -> None:
        config = EvalEngineConfig()
        assert config.framework == "deepeval"
        assert config.judge.provider == "gemini"
        assert config.judge.model == "gemini-2.0-flash"

    def test_case_verdict_enum(self) -> None:
        assert CaseVerdict.PASS.value == "pass"
        assert CaseVerdict.FAIL.value == "fail"
        assert CaseVerdict.ERROR.value == "error"


# ---------------------------------------------------------------------------
# Loader tests
# ---------------------------------------------------------------------------


class TestLoader:
    """Test eval config and case loading."""

    def test_load_eval_engine_config(self, eval_project: Path) -> None:
        config = load_eval_engine_config(eval_project)
        assert config.framework == "deepeval"
        assert config.judge.provider == "gemini"
        assert config.judge.model == "gemini-2.0-flash"

    def test_load_eval_engine_config_defaults(self, tmp_path: Path) -> None:
        """Returns defaults when no config file exists."""
        config = load_eval_engine_config(tmp_path)
        assert config.framework == "deepeval"

    def test_load_eval_suite(self, eval_project: Path) -> None:
        suite = load_eval_suite(eval_project, "baseline")
        assert suite.name == "baseline"
        assert suite.pass_threshold == 0.85
        assert suite.metrics == ["answer_relevancy"]
        assert len(suite.groups) == 2

        # Check accuracy group
        accuracy = suite.groups[0]
        assert accuracy.name == "accuracy"
        assert accuracy.weight == 0.6
        assert len(accuracy.cases) == 2
        assert accuracy.cases[0].input == "What is Zil?"
        assert accuracy.cases[0].expected_contains == ["framework", "agent"]
        assert accuracy.cases[0].context == [
            "Zil is an open-source framework by FluentData"
        ]

        # Check tool_use group
        tool_use = suite.groups[1]
        assert tool_use.name == "tool_use"
        assert tool_use.weight == 0.4
        assert tool_use.cases[0].expected_tool == "lookup_order"

    def test_load_eval_suite_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="Eval suite not found"):
            load_eval_suite(tmp_path, "baseline")

    def test_load_eval_suite_missing_case_file(self, tmp_path: Path) -> None:
        evals_dir = tmp_path / "evals"
        evals_dir.mkdir()
        suite = {
            "eval_suite": {
                "name": "broken",
                "pass_threshold": 0.85,
                "cases": [{"file": "./cases/nonexistent.yaml", "weight": 1.0}],
            }
        }
        (evals_dir / "broken.yaml").write_text(yaml.dump(suite))
        with pytest.raises(FileNotFoundError, match="Eval case file not found"):
            load_eval_suite(tmp_path, "broken")

    def test_case_metrics_override(self, eval_project: Path) -> None:
        """Per-case metrics override suite-level metrics."""
        suite = load_eval_suite(eval_project, "baseline")
        # Second accuracy case has metrics: [] (overrides suite-level)
        assert suite.groups[0].cases[1].metrics == []


# ---------------------------------------------------------------------------
# Runner tests (with mocked agent)
# ---------------------------------------------------------------------------


class TestRunner:
    """Test the eval runner with a mocked agent function."""

    def test_run_suite_all_pass(self, minimal_eval_project: Path) -> None:
        """All cases pass when agent returns expected content."""

        def mock_agent(user_input: str) -> str:
            if "hello" in user_input.lower():
                return "Hello! How can I help you?"
            if "2+2" in user_input:
                return "The answer is 4."
            return "I don't know."

        result = run_eval_suite(
            minimal_eval_project,
            agent_fn=mock_agent,
        )
        assert result.passed is True
        assert result.score == 1.0
        assert result.total_cases == 2
        assert result.passed_cases == 2

    def test_run_suite_partial_fail(self, minimal_eval_project: Path) -> None:
        """Score reflects partial failures."""

        def mock_agent(user_input: str) -> str:
            if "hello" in user_input.lower():
                return "Hello! How can I help you?"
            return "I don't know the answer."

        result = run_eval_suite(
            minimal_eval_project,
            agent_fn=mock_agent,
        )
        assert result.passed is False
        assert result.score == 0.5
        assert result.passed_cases == 1
        assert result.failed_cases == 1

    def test_run_suite_all_fail(self, minimal_eval_project: Path) -> None:
        """Score is 0 when all cases fail."""

        def mock_agent(user_input: str) -> str:
            return "Completely irrelevant response."

        result = run_eval_suite(
            minimal_eval_project,
            agent_fn=mock_agent,
        )
        assert result.passed is False
        assert result.score == 0.0

    def test_threshold_override(self, minimal_eval_project: Path) -> None:
        """Threshold override changes pass/fail verdict."""

        def mock_agent(user_input: str) -> str:
            if "hello" in user_input.lower():
                return "Hello! How can I help you?"
            return "nope"

        # Default threshold is 0.80, score is 0.5 → fail
        result = run_eval_suite(
            minimal_eval_project,
            agent_fn=mock_agent,
        )
        assert result.passed is False

        # Override threshold to 0.4 → pass
        result = run_eval_suite(
            minimal_eval_project,
            agent_fn=mock_agent,
            threshold_override=0.4,
        )
        assert result.passed is True

    def test_run_suite_agent_error(self, minimal_eval_project: Path) -> None:
        """Agent errors are captured as ERROR verdict."""

        def failing_agent(user_input: str) -> str:
            raise RuntimeError("Agent crashed!")

        result = run_eval_suite(
            minimal_eval_project,
            agent_fn=failing_agent,
        )
        assert result.passed is False
        assert result.score == 0.0
        for group in result.group_results:
            for cr in group.case_results:
                assert cr.verdict == CaseVerdict.ERROR
                assert cr.error == "Agent crashed!"

    def test_run_suite_file_not_found(self, tmp_path: Path) -> None:
        """Raises FileNotFoundError when no suite exists."""
        with pytest.raises(FileNotFoundError):
            run_eval_suite(tmp_path, agent_fn=lambda x: x)


# ---------------------------------------------------------------------------
# Adapter tests
# ---------------------------------------------------------------------------


class TestDeepEvalAdapter:
    """Test the DeepEval adapter's deterministic evaluation logic."""

    def test_deterministic_pass(self) -> None:
        """Deterministic checks pass when output contains expected strings."""
        from zil.sdk.eval.adapters.deepeval import _check_deterministic

        case = EvalCase(
            input="What is Zil?",
            expected_contains=["framework", "agent"],
        )
        assert _check_deterministic(case, "Zil is a framework for AI agents") is True

    def test_deterministic_fail(self) -> None:
        """Deterministic checks fail when output misses expected strings."""
        from zil.sdk.eval.adapters.deepeval import _check_deterministic

        case = EvalCase(
            input="What is Zil?",
            expected_contains=["framework", "agent"],
        )
        assert _check_deterministic(case, "I don't know") is False

    def test_deterministic_tool_check(self) -> None:
        """expected_tool check looks for tool name in output."""
        from zil.sdk.eval.adapters.deepeval import _check_deterministic

        case = EvalCase(
            input="Look up order",
            expected_tool="lookup_order",
        )
        assert _check_deterministic(case, "Calling lookup_order...") is True
        assert _check_deterministic(case, "Looking things up") is False

    def test_deterministic_action_check(self) -> None:
        """expected_action check looks for action in output."""
        from zil.sdk.eval.adapters.deepeval import _check_deterministic

        case = EvalCase(
            input="I need a human",
            expected_action="escalate",
        )
        assert _check_deterministic(case, "I will escalate this.") is True
        assert _check_deterministic(case, "Let me help you.") is False

    def test_deterministic_case_insensitive(self) -> None:
        """Deterministic checks are case-insensitive."""
        from zil.sdk.eval.adapters.deepeval import _check_deterministic

        case = EvalCase(
            input="hi",
            expected_contains=["Hello"],
        )
        assert _check_deterministic(case, "HELLO world") is True

    def test_evaluate_case_deterministic_only(self) -> None:
        """evaluate_case works with no LLM metrics (deterministic only)."""
        from zil.sdk.eval.adapters.deepeval import DeepEvalAdapter

        adapter = DeepEvalAdapter()
        # Configure with a mock — we won't use LLM metrics
        adapter._configured = True
        adapter._judge_model = None
        adapter._metric_thresholds = {}

        case = EvalCase(
            input="Hello",
            expected_contains=["hello"],
        )
        result = adapter.evaluate_case(case, "Hello there!", metrics=[])
        assert result.verdict == CaseVerdict.PASS
        assert result.score == 1.0

    def test_evaluate_case_deterministic_fail(self) -> None:
        """evaluate_case returns FAIL for deterministic failure."""
        from zil.sdk.eval.adapters.deepeval import DeepEvalAdapter

        adapter = DeepEvalAdapter()
        adapter._configured = True
        adapter._judge_model = None
        adapter._metric_thresholds = {}

        case = EvalCase(
            input="Hello",
            expected_contains=["hello"],
        )
        result = adapter.evaluate_case(case, "Goodbye!", metrics=[])
        assert result.verdict == CaseVerdict.FAIL
        assert result.score == 0.0

    def test_available_metrics(self) -> None:
        """Adapter reports supported metrics."""
        from zil.sdk.eval.adapters.deepeval import DeepEvalAdapter

        adapter = DeepEvalAdapter()
        metrics = adapter.available_metrics()
        assert "hallucination" in metrics
        assert "answer_relevancy" in metrics
        assert "faithfulness" in metrics


# ---------------------------------------------------------------------------
# Adapter registry tests
# ---------------------------------------------------------------------------


class TestAdapterRegistry:
    """Test adapter lookup."""

    def test_get_deepeval_adapter(self) -> None:
        from zil.sdk.eval.adapters import get_adapter
        from zil.sdk.eval.adapters.deepeval import DeepEvalAdapter

        adapter = get_adapter("deepeval")
        assert isinstance(adapter, DeepEvalAdapter)

    def test_get_unknown_adapter(self) -> None:
        from zil.sdk.eval.adapters import get_adapter

        with pytest.raises(ValueError, match="Unknown eval framework"):
            get_adapter("nonexistent")


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------


class TestEvalCLI:
    """Test the zil eval CLI command."""

    def test_eval_help(self) -> None:
        from click.testing import CliRunner

        from zil.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["eval", "--help"])
        assert result.exit_code == 0
        assert "run" in result.output
        assert "add" in result.output
        assert "record" in result.output
        assert "generate" in result.output

    def test_eval_run_help(self) -> None:
        from click.testing import CliRunner

        from zil.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["eval", "run", "--help"])
        assert result.exit_code == 0
        assert "--suite" in result.output
        assert "--verbose" in result.output
        assert "--json-output" in result.output
        assert "--threshold" in result.output

    def test_eval_no_suite_file(self, tmp_path: Path) -> None:
        from click.testing import CliRunner

        from zil.cli import cli

        runner = CliRunner()
        result = runner.invoke(
            cli, ["eval", "run", "--project-dir", str(tmp_path)],
        )
        assert result.exit_code == 1
        assert "Eval suite not found" in result.output

    def test_eval_json_output(self, minimal_eval_project: Path) -> None:
        """JSON output mode produces valid JSON."""
        import json

        from click.testing import CliRunner

        from zil.cli import cli

        # Patch the runner to use a mock agent
        def mock_agent(user_input: str) -> str:
            return "hello! The answer is 4."

        with patch(
            "zil.sdk.eval.runner._build_default_agent_fn",
            return_value=mock_agent,
        ):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["eval", "run", "--project-dir", str(minimal_eval_project), "--json-output"],
            )

        # Should produce valid JSON regardless of pass/fail
        output = json.loads(result.output)
        assert "score" in output
        assert "passed" in output
        assert "groups" in output


# ---------------------------------------------------------------------------
# Init template tests
# ---------------------------------------------------------------------------


class TestInitWithEvalFramework:
    """Test that zil init generates eval config with framework selection."""

    def test_init_creates_eval_config(self) -> None:
        from click.testing import CliRunner

        from zil.cli import cli

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(
                cli,
                ["init", "test-agent", "--non-interactive"],
            )
            assert result.exit_code == 0

            config_path = Path("test-agent/evals/config.yaml")
            assert config_path.exists()

            content = yaml.safe_load(config_path.read_text())
            assert content["eval_engine"]["framework"] == "deepeval"
            assert content["eval_engine"]["judge"]["provider"] == "gemini"

    def test_init_creates_enhanced_baseline(self) -> None:
        from click.testing import CliRunner

        from zil.cli import cli

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(
                cli,
                ["init", "test-agent", "--non-interactive"],
            )
            assert result.exit_code == 0

            baseline_path = Path("test-agent/evals/baseline.yaml")
            assert baseline_path.exists()

            content = yaml.safe_load(baseline_path.read_text())
            suite = content["eval_suite"]
            assert "metrics" in suite
            assert "answer_relevancy" in suite["metrics"]

    def test_init_no_evals_skips_config(self) -> None:
        from click.testing import CliRunner

        from zil.cli import cli

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(
                cli,
                ["init", "test-agent", "--no-evals", "--non-interactive"],
            )
            assert result.exit_code == 0

            config_path = Path("test-agent/evals/config.yaml")
            assert not config_path.exists()


# ---------------------------------------------------------------------------
# Writer tests
# ---------------------------------------------------------------------------


class TestWriter:
    """Test eval case writer and suite registration."""

    def test_append_case_creates_file(self, tmp_path: Path) -> None:
        from zil.sdk.eval.writer import append_case_to_group

        evals_dir = tmp_path / "evals"
        evals_dir.mkdir()
        case = EvalCase(input="Hello", expected_contains=["hello"])
        path = append_case_to_group(evals_dir, "cases/test.yaml", "test", case)
        assert path.exists()
        raw = yaml.safe_load(path.read_text())
        assert raw["name"] == "test"
        assert len(raw["cases"]) == 1
        assert raw["cases"][0]["input"] == "Hello"

    def test_append_case_appends_to_existing(self, tmp_path: Path) -> None:
        from zil.sdk.eval.writer import append_case_to_group

        evals_dir = tmp_path / "evals"
        evals_dir.mkdir()
        case1 = EvalCase(input="First", expected_contains=["one"])
        case2 = EvalCase(input="Second", expected_contains=["two"])
        append_case_to_group(evals_dir, "cases/test.yaml", "test", case1)
        append_case_to_group(evals_dir, "cases/test.yaml", "test", case2)
        path = evals_dir / "cases" / "test.yaml"
        raw = yaml.safe_load(path.read_text())
        assert len(raw["cases"]) == 2

    def test_register_group_in_suite(self, tmp_path: Path) -> None:
        from zil.sdk.eval.writer import register_group_in_suite

        evals_dir = tmp_path / "evals"
        evals_dir.mkdir()
        suite = {"eval_suite": {"name": "baseline", "cases": []}}
        (evals_dir / "baseline.yaml").write_text(yaml.dump(suite))
        register_group_in_suite(evals_dir, "baseline", "cases/new.yaml")
        raw = yaml.safe_load((evals_dir / "baseline.yaml").read_text())
        files = [e["file"] for e in raw["eval_suite"]["cases"]]
        assert "./cases/new.yaml" in files

    def test_register_group_no_duplicate(self, tmp_path: Path) -> None:
        from zil.sdk.eval.writer import register_group_in_suite

        evals_dir = tmp_path / "evals"
        evals_dir.mkdir()
        suite = {
            "eval_suite": {
                "name": "baseline",
                "cases": [{"file": "./cases/existing.yaml", "weight": 1.0}],
            }
        }
        (evals_dir / "baseline.yaml").write_text(yaml.dump(suite))
        register_group_in_suite(evals_dir, "baseline", "cases/existing.yaml")
        raw = yaml.safe_load((evals_dir / "baseline.yaml").read_text())
        assert len(raw["eval_suite"]["cases"]) == 1


# ---------------------------------------------------------------------------
# Config enhancement tests
# ---------------------------------------------------------------------------


class TestConfigEnhancements:
    """Test metric_thresholds and execution config."""

    def test_load_metric_thresholds(self, tmp_path: Path) -> None:
        evals_dir = tmp_path / "evals"
        evals_dir.mkdir()
        config = {
            "eval_engine": {
                "framework": "deepeval",
                "judge": {"provider": "gemini", "model": "gemini-2.0-flash"},
                "metric_thresholds": {
                    "answer_relevancy": 0.7,
                    "hallucination": 0.9,
                },
            }
        }
        (evals_dir / "config.yaml").write_text(yaml.dump(config))
        loaded = load_eval_engine_config(tmp_path)
        assert loaded.metric_thresholds == {
            "answer_relevancy": 0.7,
            "hallucination": 0.9,
        }

    def test_load_execution_config(self, tmp_path: Path) -> None:
        evals_dir = tmp_path / "evals"
        evals_dir.mkdir()
        config = {
            "eval_engine": {
                "framework": "deepeval",
                "execution": {
                    "concurrency": 4,
                    "retries": 2,
                    "timeout": 30,
                },
            }
        }
        (evals_dir / "config.yaml").write_text(yaml.dump(config))
        loaded = load_eval_engine_config(tmp_path)
        assert loaded.execution.concurrency == 4
        assert loaded.execution.retries == 2
        assert loaded.execution.timeout == 30

    def test_execution_config_defaults(self, tmp_path: Path) -> None:
        loaded = load_eval_engine_config(tmp_path)
        assert loaded.execution.concurrency == 1
        assert loaded.execution.retries == 0
        assert loaded.execution.timeout == 60


# ---------------------------------------------------------------------------
# Generator parse tests
# ---------------------------------------------------------------------------


class TestGeneratorParsing:
    """Test case generation parsing (no LLM calls)."""

    def test_parse_valid_json(self) -> None:
        from zil.sdk.eval.generator import _parse_cases

        raw = '[{"input": "Hello", "expected_contains": ["hi"]}]'
        cases = _parse_cases(raw)
        assert len(cases) == 1
        assert cases[0].input == "Hello"
        assert cases[0].expected_contains == ["hi"]

    def test_parse_json_with_fences(self) -> None:
        from zil.sdk.eval.generator import _parse_cases

        raw = '```json\n[{"input": "test"}]\n```'
        cases = _parse_cases(raw)
        assert len(cases) == 1
        assert cases[0].input == "test"

    def test_parse_json_with_surrounding_text(self) -> None:
        from zil.sdk.eval.generator import _parse_cases

        raw = 'Here are the cases:\n[{"input": "test"}]\nDone!'
        cases = _parse_cases(raw)
        assert len(cases) == 1

    def test_parse_invalid_json_raises(self) -> None:
        from zil.sdk.eval.generator import _parse_cases

        with pytest.raises(ValueError, match="Could not parse"):
            _parse_cases("not json at all")


# ---------------------------------------------------------------------------
# Keyword extraction tests
# ---------------------------------------------------------------------------


class TestKeywordExtraction:
    """Test the keyword extraction helper."""

    def test_basic_extraction(self) -> None:
        from zil.commands.eval import _extract_keywords

        text = "Zil is a framework for production AI agents by FluentData."
        kw = _extract_keywords(text)
        assert len(kw) <= 3
        assert all(isinstance(k, str) for k in kw)

    def test_stop_words_filtered(self) -> None:
        from zil.commands.eval import _extract_keywords

        text = "The is are was were the the the"
        kw = _extract_keywords(text)
        assert kw == []

    def test_empty_input(self) -> None:
        from zil.commands.eval import _extract_keywords

        assert _extract_keywords("") == []
