"""Write eval cases and update suite YAML files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from zil.sdk.eval.models import EvalCase


def append_case_to_group(
    evals_dir: Path,
    group_file: str,
    group_name: str,
    case: EvalCase,
) -> Path:
    """Append a case to a group YAML file, creating it if needed.

    Args:
        evals_dir: The evals/ directory.
        group_file: Relative path like ``cases/accuracy.yaml``.
        group_name: Human-readable group name (used when creating new files).
        case: The EvalCase to append.

    Returns:
        The resolved path to the group file.
    """
    path = (evals_dir / group_file).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    case_dict = _case_to_dict(case)

    if path.is_file():
        raw = _load_yaml(path)
        raw.setdefault("name", group_name)
        raw.setdefault("cases", [])
        raw["cases"].append(case_dict)
    else:
        raw = {"name": group_name, "cases": [case_dict]}

    _write_yaml(path, raw)
    return path


def register_group_in_suite(
    evals_dir: Path,
    suite_name: str,
    group_file: str,
    weight: float = 1.0,
) -> None:
    """Ensure a case group file is listed in the suite YAML.

    If the group_file is already referenced, this is a no-op.
    """
    suite_path = evals_dir / f"{suite_name}.yaml"
    if not suite_path.is_file():
        return

    raw = _load_yaml(suite_path)
    suite = raw.setdefault("eval_suite", {})
    cases = suite.setdefault("cases", [])

    # Normalise file refs for comparison
    normalised = group_file if group_file.startswith("./") else f"./{group_file}"
    for entry in cases:
        ref = entry.get("file", "")
        ref_n = ref if ref.startswith("./") else f"./{ref}"
        if ref_n == normalised:
            return  # already registered

    cases.append({"file": normalised, "weight": weight})
    _write_yaml(suite_path, raw)


def _case_to_dict(case: EvalCase) -> dict[str, Any]:
    """Convert an EvalCase to a serialisable dict, omitting empty fields."""
    d: dict[str, Any] = {"input": case.input}
    if case.expected_output:
        d["expected_output"] = case.expected_output
    if case.expected_contains:
        d["expected_contains"] = case.expected_contains
    if case.expected_tool:
        d["expected_tool"] = case.expected_tool
    if case.expected_action:
        d["expected_action"] = case.expected_action
    if case.context:
        d["context"] = case.context
    if case.metrics:
        d["metrics"] = case.metrics
    return d


def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
