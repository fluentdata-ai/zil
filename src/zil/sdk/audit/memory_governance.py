"""Memory governance audit check (RFC-003).

Surfaces agent-native risks introduced by persistent memory:

- **PII exposure**: long-term/shared (user/agent) memory persisted without
  ``persist.exclude_pii`` set.
- **Unbounded retention**: long-term scopes with no retention policy.
- **Memory poisoning**: untrusted input flowing into persisted memory and
  later retrieved into the prompt (a stored-injection surface), especially
  for shared (agent-namespace) scopes that fan out across agents/users.

These are findings, not hard blocks.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from zil.sdk.audit import AuditFinding, AuditSection, Category, Severity


def check_memory_governance(project_dir: Path) -> AuditSection:
    """Audit the memory configuration for governance risks."""
    section = AuditSection(
        category=Category.MEMORY_GOVERNANCE,
        title="Memory Governance",
    )

    manifest_path = project_dir / "manifest.yaml"
    if not manifest_path.is_file():
        section.score = "N/A"
        section.findings.append(
            AuditFinding(
                category=Category.MEMORY_GOVERNANCE,
                severity=Severity.INFO,
                message="No manifest.yaml found — skipping memory audit",
            )
        )
        return section

    try:
        manifest = yaml.safe_load(manifest_path.read_text())
    except Exception:
        section.score = "N/A"
        return section

    mem_ref = manifest.get("spec", {}).get("memory")
    if not mem_ref:
        section.score = "PASS"
        section.findings.append(
            AuditFinding(
                category=Category.MEMORY_GOVERNANCE,
                severity=Severity.PASS,
                message="No persistent memory configured",
            )
        )
        return section

    candidate = project_dir / mem_ref
    if candidate.is_dir():
        candidate = candidate / "memory.yaml"
    if not candidate.is_file():
        section.score = "N/A"
        section.findings.append(
            AuditFinding(
                category=Category.MEMORY_GOVERNANCE,
                severity=Severity.WARNING,
                message=f"spec.memory references {mem_ref} but the file is missing",
            )
        )
        return section

    try:
        cfg = yaml.safe_load(candidate.read_text()) or {}
    except Exception:
        section.score = "N/A"
        return section

    scopes = [str(s).lower() for s in (cfg.get("scopes") or ["session", "user", "agent"])]
    persist = cfg.get("persist") or {}
    retention = cfg.get("retention") or {}
    exclude_pii = bool(persist.get("exclude_pii", False))

    long_term = [s for s in scopes if s in ("user", "agent")]
    shared = "agent" in scopes  # namespace-shared "segmented knowledge"

    issues = 0

    # --- PII exposure ---
    if long_term and not exclude_pii:
        issues += 1
        section.findings.append(
            AuditFinding(
                category=Category.MEMORY_GOVERNANCE,
                severity=Severity.WARNING,
                message=(
                    "Long-term/shared memory persists data without "
                    "persist.exclude_pii"
                ),
                detail=(
                    f"Scopes {long_term} retain data across sessions; without "
                    "PII exclusion, personal data may be stored indefinitely."
                ),
                fix="Set persist.exclude_pii: true in adapters/memory.yaml.",
            )
        )
    elif long_term:
        section.findings.append(
            AuditFinding(
                category=Category.MEMORY_GOVERNANCE,
                severity=Severity.PASS,
                message="persist.exclude_pii enabled for long-term memory",
            )
        )

    # --- Unbounded retention ---
    for scope in long_term:
        if scope not in retention:
            issues += 1
            section.findings.append(
                AuditFinding(
                    category=Category.MEMORY_GOVERNANCE,
                    severity=Severity.WARNING,
                    message=f"No retention policy for long-term scope '{scope}'",
                    detail="Memory may persist indefinitely with no expiry.",
                    fix=f"Add retention.{scope} (e.g. '90d') in adapters/memory.yaml.",
                )
            )
        else:
            section.findings.append(
                AuditFinding(
                    category=Category.MEMORY_GOVERNANCE,
                    severity=Severity.PASS,
                    message=f"Retention policy set for '{scope}' ({retention[scope]})",
                )
            )

    # --- Memory poisoning / stored injection surface ---
    if shared:
        issues += 1
        section.findings.append(
            AuditFinding(
                category=Category.MEMORY_GOVERNANCE,
                severity=Severity.WARNING,
                message=(
                    "Shared (agent-namespace) memory is a stored-injection / "
                    "poisoning surface"
                ),
                detail=(
                    "Untrusted content written by one agent/turn into a shared "
                    "namespace can be retrieved into other agents' prompts. "
                    "Validate/sanitize content before persisting and constrain "
                    "what is written to shared scopes."
                ),
                fix=(
                    "Restrict writes to shared scopes, sanitize persisted content, "
                    "and keep guardrail output checks enabled on retrieved memory."
                ),
            )
        )
    else:
        section.findings.append(
            AuditFinding(
                category=Category.MEMORY_GOVERNANCE,
                severity=Severity.INFO,
                message="No shared (agent-namespace) memory scope enabled",
            )
        )

    # --- Packable seed: scope + PII scan ---
    seed_cfg = cfg.get("seed") or {}
    seed_ref = seed_cfg.get("file")
    if seed_ref:
        seed_file = (candidate.parent / seed_ref).resolve()
        if not seed_file.is_file():
            issues += 1
            section.findings.append(
                AuditFinding(
                    category=Category.MEMORY_GOVERNANCE,
                    severity=Severity.WARNING,
                    message=f"Memory seed file declared but missing ({seed_ref})",
                )
            )
        else:
            issues += _audit_seed_file(section, seed_file)

    total = max(1, len(long_term) + (1 if long_term else 0) + 1)
    passed = total - issues
    section.score = f"{max(0, passed)}/{total}"
    return section


def _audit_seed_file(section: AuditSection, seed_file: Path) -> int:
    """Scan a memory seed file for PII and scope violations. Returns issue count."""
    from zil.sdk.memory import pii
    from zil.sdk.memory.seed import SeedError, load_seed_file

    try:
        seed = load_seed_file(seed_file)
    except SeedError as exc:
        section.findings.append(
            AuditFinding(
                category=Category.MEMORY_GOVERNANCE,
                severity=Severity.WARNING,
                message=f"Memory seed file is invalid: {exc}",
            )
        )
        return 1

    flagged: list[str] = []
    for entry in seed.entries:
        categories = pii.scan(str(entry.get("content", "")))
        if categories:
            flagged.append(", ".join(categories))

    if flagged:
        section.findings.append(
            AuditFinding(
                category=Category.MEMORY_GOVERNANCE,
                severity=Severity.WARNING,
                message=(
                    f"Memory seed contains PII in {len(flagged)} entr"
                    f"{'y' if len(flagged) == 1 else 'ies'} "
                    f"({', '.join(sorted(set(flagged)))})"
                ),
                detail=(
                    "Seeded memories ship with the agent. PII entries are dropped "
                    "by the pack/runtime filter, but should not be authored at all."
                ),
                fix="Remove personal data from the seed file; keep behavioral knowledge only.",
            )
        )
        return 1

    section.findings.append(
        AuditFinding(
            category=Category.MEMORY_GOVERNANCE,
            severity=Severity.PASS,
            message=f"Memory seed clean ({len(seed)} AGENT-scope entries, no PII)",
        )
    )
    return 0
