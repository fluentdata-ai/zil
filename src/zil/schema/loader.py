"""Schema loading and project validation."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import jsonschema
import yaml

SCHEMA_PATH = Path(__file__).parent.parent / "spec" / "v1" / "manifest.schema.json"


@dataclass
class CheckResult:
    status: str  # "pass" | "fail" | "warn"
    message: str

    def to_dict(self) -> dict:
        return {"status": self.status, "message": self.message}


@dataclass
class ValidationResult:
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        statuses = {c.status for c in self.checks}
        if "fail" in statuses:
            return 1
        if "warn" in statuses:
            return 2
        return 0

    @property
    def error_count(self) -> int:
        return sum(1 for c in self.checks if c.status == "fail")

    @property
    def warning_count(self) -> int:
        return sum(1 for c in self.checks if c.status == "warn")

    def to_dict(self) -> dict:
        return {
            "valid": self.exit_code == 0,
            "exit_code": self.exit_code,
            "errors": self.error_count,
            "warnings": self.warning_count,
            "checks": [c.to_dict() for c in self.checks],
        }


def load_schema() -> dict:
    """Load the Zil manifest JSON Schema."""
    with open(SCHEMA_PATH) as f:
        return json.load(f)


def validate_project(project_dir: Path) -> ValidationResult:
    """Validate a Zil project directory against the manifest schema."""
    result = ValidationResult()

    manifest_path = project_dir / "manifest.yaml"
    if not manifest_path.exists():
        result.checks.append(CheckResult("fail", "manifest.yaml — not found"))
        return result

    # Parse manifest
    try:
        with open(manifest_path) as f:
            manifest = yaml.safe_load(f)
    except yaml.YAMLError as e:
        result.checks.append(CheckResult("fail", f"manifest.yaml — invalid YAML: {e}"))
        return result

    # Schema validation
    try:
        schema = load_schema()
        jsonschema.validate(instance=manifest, schema=schema)
        result.checks.append(CheckResult("pass", "manifest.yaml — schema valid"))
    except jsonschema.ValidationError as e:
        result.checks.append(CheckResult("fail", f"manifest.yaml — {e.message}"))
    except FileNotFoundError:
        result.checks.append(CheckResult("fail", "manifest.schema.json — schema file not found"))
        return result

    # File reference checks
    _check_identity(project_dir, manifest, result)
    _check_adapters(project_dir, manifest, result)
    _check_evals(project_dir, manifest, result)
    _check_observability(project_dir, manifest, result)
    _check_env(project_dir, manifest, result)
    _check_guardrails(project_dir, manifest, result)

    return result


def _check_identity(project_dir: Path, manifest: dict, result: ValidationResult) -> None:
    """Check identity directory files exist."""
    spec = manifest.get("spec", {})
    identity_ref = spec.get("identity")
    if not identity_ref:
        return

    identity_dir = project_dir / "identity"
    required_files = ["persona.md", "instructions.md", "guardrails.yaml"]
    for fname in required_files:
        fpath = identity_dir / fname
        if fpath.exists():
            result.checks.append(CheckResult("pass", f"identity/{fname} — present"))
        else:
            result.checks.append(CheckResult("fail", f"identity/{fname} — missing"))


def _check_adapters(project_dir: Path, manifest: dict, result: ValidationResult) -> None:
    """Check adapter files referenced in the manifest exist."""
    spec = manifest.get("spec", {})
    runtime = spec.get("runtime", {})

    for adapter_key in ["llm", "embedding"]:
        adapter = runtime.get(adapter_key, {})
        adapter_path = adapter.get("adapter")
        if adapter_path:
            full_path = project_dir / adapter_path
            if full_path.exists():
                result.checks.append(CheckResult("pass", f"{adapter_path} — present"))
            else:
                result.checks.append(CheckResult("fail", f"{adapter_path} — missing"))


def _check_evals(project_dir: Path, manifest: dict, result: ValidationResult) -> None:
    """Check eval suite files exist."""
    spec = manifest.get("spec", {})
    evals_ref = spec.get("evals")
    if not evals_ref:
        result.checks.append(CheckResult("warn", "evals — not referenced in manifest"))
        return

    evals_path = project_dir / "evals" / "baseline.yaml"
    if evals_path.exists():
        result.checks.append(CheckResult("pass", "evals/baseline.yaml — present"))
    else:
        result.checks.append(CheckResult("fail", "evals/baseline.yaml — missing"))


def _check_observability(project_dir: Path, manifest: dict, result: ValidationResult) -> None:
    """Check observability config exists and has recommended attributes."""
    spec = manifest.get("spec", {})
    obs_ref = spec.get("observability")
    if not obs_ref:
        result.checks.append(CheckResult("warn", "observability — not referenced in manifest"))
        return

    obs_path = project_dir / "observability" / "config.yaml"
    if obs_path.exists():
        result.checks.append(CheckResult("pass", "observability/config.yaml — present"))
        # Check for recommended attributes
        try:
            with open(obs_path) as f:
                obs_config = yaml.safe_load(f)
            required_attrs = obs_config.get("observability", {}).get("required_attributes", [])
            if "cost.usd" not in required_attrs:
                result.checks.append(
                    CheckResult(
                        "warn",
                        "observability/config.yaml — missing recommended attribute: cost.usd",
                    )
                )
        except Exception:
            pass
    else:
        result.checks.append(CheckResult("fail", "observability/config.yaml — missing"))


def _check_env(project_dir: Path, manifest: dict, result: ValidationResult) -> None:
    """Check spec.env declarations and cross-reference with adapter env vars."""
    spec = manifest.get("spec", {})
    env_declarations = spec.get("env")

    if not env_declarations:
        result.checks.append(CheckResult("warn", "spec.env — not declared in manifest"))
        return

    # Validate each entry has a name
    declared_names: set[str] = set()
    for entry in env_declarations:
        name = entry.get("name")
        if not name:
            result.checks.append(CheckResult("fail", "spec.env — entry missing 'name' field"))
        else:
            declared_names.add(name)

    count = len(declared_names)
    secret_count = sum(1 for e in env_declarations if e.get("secret"))
    result.checks.append(
        CheckResult("pass", f"spec.env — {count} variable(s) declared ({secret_count} secret)")
    )

    # Cross-reference: warn if adapter env_var not in spec.env
    runtime = spec.get("runtime", {})
    for adapter_key in ["llm", "embedding"]:
        adapter_ref = runtime.get(adapter_key, {}).get("adapter")
        if not adapter_ref:
            continue
        adapter_path = project_dir / adapter_ref
        if not adapter_path.is_file():
            continue
        try:
            adapter_config = yaml.safe_load(adapter_path.read_text())
            auth = adapter_config.get("auth", {})
            for key in ("env_var", "project_env_var", "location_env_var"):
                env_var = auth.get(key)
                if env_var and env_var not in declared_names:
                    result.checks.append(
                        CheckResult(
                            "warn",
                            f"spec.env — adapter {adapter_key} references '{env_var}' "
                            f"but it is not declared in spec.env",
                        )
                    )
        except Exception:
            pass


def _check_guardrails(project_dir: Path, manifest: dict, result: ValidationResult) -> None:
    """Validate guardrails.yaml structure and rule quality."""
    import re

    spec = manifest.get("spec", {})
    identity_ref = spec.get("identity")
    if not identity_ref:
        return

    guardrails_path = project_dir / "identity" / "guardrails.yaml"
    if not guardrails_path.is_file():
        # Already flagged by _check_identity — don't duplicate
        return

    try:
        config = yaml.safe_load(guardrails_path.read_text())
    except yaml.YAMLError as e:
        result.checks.append(
            CheckResult("fail", f"identity/guardrails.yaml — invalid YAML: {e}")
        )
        return

    if not config or not isinstance(config, dict):
        result.checks.append(
            CheckResult("warn", "identity/guardrails.yaml — empty or not a mapping")
        )
        return

    # Check for runtime-enforceable sections
    has_blocked_patterns = bool(config.get("blocked_patterns"))
    has_denied_topics = bool(config.get("denied_topics"))
    has_output_constraints = bool(config.get("output_constraints"))

    # Count enforceable rules
    enforceable = 0
    detection = config.get("detection", {})
    if detection.get("prompt_injection", True):
        enforceable += 1
    if detection.get("pii_output", True):
        enforceable += 1
    if detection.get("pii_input", False):
        enforceable += 1

    if has_blocked_patterns:
        enforceable += len(config["blocked_patterns"])
    if has_denied_topics:
        enforceable += len(config["denied_topics"])
    if has_output_constraints:
        enforceable += 1

    if enforceable > 0:
        result.checks.append(
            CheckResult(
                "pass",
                f"identity/guardrails.yaml — {enforceable} enforceable rule(s) detected",
            )
        )
    else:
        result.checks.append(
            CheckResult(
                "warn",
                "identity/guardrails.yaml — no enforceable rules found "
                "(add detection, blocked_patterns, denied_topics, or output_constraints)",
            )
        )

    # Validate blocked_patterns regexes
    for i, bp in enumerate(config.get("blocked_patterns", [])):
        pattern_str = bp.get("pattern", "")
        if not pattern_str:
            result.checks.append(
                CheckResult(
                    "warn",
                    f"identity/guardrails.yaml — blocked_patterns[{i}] has no 'pattern' field",
                )
            )
            continue
        try:
            re.compile(pattern_str)
        except re.error as e:
            result.checks.append(
                CheckResult(
                    "fail",
                    f"identity/guardrails.yaml — blocked_patterns[{i}] "
                    f"has invalid regex: {e}",
                )
            )

    # Warn if no output checks
    has_output = has_output_constraints or has_blocked_patterns
    has_pii_output = detection.get("pii_output", True)
    if not has_output and not has_pii_output:
        result.checks.append(
            CheckResult(
                "warn",
                "identity/guardrails.yaml — no output checks configured "
                "(consider adding output_constraints or pii_output detection)",
            )
        )
