"""Load eval configuration and case files from disk."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from zil.sdk.eval.models import (
    CaseGroup,
    EvalCase,
    EvalEngineConfig,
    EvalSuiteConfig,
    ExecutionConfig,
    JudgeConfig,
)


def load_eval_engine_config(project_dir: Path) -> EvalEngineConfig:
    """Load evals/config.yaml and return an EvalEngineConfig."""
    config_path = project_dir / "evals" / "config.yaml"
    if not config_path.is_file():
        return EvalEngineConfig()

    raw = _load_yaml(config_path)
    engine = raw.get("eval_engine", {})

    judge_raw = engine.get("judge", {})
    judge = JudgeConfig(
        provider=judge_raw.get("provider", "gemini"),
        model=judge_raw.get("model", "gemini-2.0-flash"),
        api_key_env=judge_raw.get("api_key_env", "GOOGLE_API_KEY"),
    )

    metric_thresholds = engine.get("metric_thresholds", {})

    exec_raw = engine.get("execution", {})
    execution = ExecutionConfig(
        concurrency=int(exec_raw.get("concurrency", 1)),
        retries=int(exec_raw.get("retries", 0)),
        timeout=int(exec_raw.get("timeout", 60)),
    )

    return EvalEngineConfig(
        framework=engine.get("framework", "deepeval"),
        judge=judge,
        metric_thresholds=metric_thresholds,
        execution=execution,
    )


def load_eval_suite(
    project_dir: Path,
    suite_name: str = "baseline",
) -> EvalSuiteConfig:
    """Load an eval suite definition and all referenced case files."""
    suite_path = project_dir / "evals" / f"{suite_name}.yaml"
    if not suite_path.is_file():
        raise FileNotFoundError(
            f"Eval suite not found: {suite_path}. "
            f"Create evals/{suite_name}.yaml or run 'zil init'."
        )

    raw = _load_yaml(suite_path)
    suite_raw = raw.get("eval_suite", {})

    suite = EvalSuiteConfig(
        name=suite_raw.get("name", suite_name),
        pass_threshold=float(suite_raw.get("pass_threshold", 0.85)),
        metrics=suite_raw.get("metrics", []),
    )

    cases_entries = suite_raw.get("cases", [])
    evals_dir = project_dir / "evals"

    for entry in cases_entries:
        file_ref = entry.get("file", "")
        weight = float(entry.get("weight", 1.0))
        group = _load_case_group(evals_dir, file_ref, weight)
        suite.groups.append(group)

    return suite


def _load_case_group(evals_dir: Path, file_ref: str, weight: float) -> CaseGroup:
    """Load a single case group from a YAML file reference."""
    case_path = (evals_dir / file_ref).resolve()
    if not case_path.is_file():
        raise FileNotFoundError(f"Eval case file not found: {case_path}")

    raw = _load_yaml(case_path)
    name = raw.get("name", case_path.stem)
    cases_raw = raw.get("cases", [])

    cases = [_parse_case(c) for c in cases_raw]
    return CaseGroup(name=name, cases=cases, weight=weight)


def _parse_case(raw: dict[str, Any]) -> EvalCase:
    """Parse a single case dict into an EvalCase."""
    return EvalCase(
        input=raw.get("input", ""),
        expected_output=raw.get("expected_output"),
        expected_contains=raw.get("expected_contains", []),
        expected_tool=raw.get("expected_tool"),
        expected_action=raw.get("expected_action"),
        context=raw.get("context", []),
        metrics=raw.get("metrics", []),
    )


def _load_yaml(path: Path) -> dict[str, Any]:
    """Read and parse a YAML file."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
