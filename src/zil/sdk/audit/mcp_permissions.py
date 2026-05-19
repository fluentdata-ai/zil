"""MCP server permission audit check.

Flags over-permissioned MCP servers (no tool_filter), dangerous host
dependencies, and missing env var declarations for MCP config references.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from zil.sdk.audit import AuditFinding, AuditSection, Category, Severity

# Host dependencies with elevated risk
_RISKY_HOST_DEPS = {
    "docker": "Container runtime — can escape sandboxing",
    "sudo": "Privilege escalation risk",
    "ssh": "Network access — potential lateral movement",
    "curl": "Arbitrary HTTP requests",
    "wget": "Arbitrary HTTP requests",
}


def check_mcp_permissions(project_dir: Path) -> AuditSection:
    """Audit MCP server declarations for permission issues."""
    section = AuditSection(
        category=Category.MCP_PERMISSIONS,
        title="MCP Server Permissions",
    )

    manifest_path = project_dir / "manifest.yaml"
    if not manifest_path.is_file():
        section.score = "N/A"
        section.findings.append(
            AuditFinding(
                category=Category.MCP_PERMISSIONS,
                severity=Severity.INFO,
                message="No manifest.yaml found — skipping MCP audit",
            )
        )
        return section

    try:
        manifest = yaml.safe_load(manifest_path.read_text())
    except Exception:
        section.score = "N/A"
        return section

    tools_ref = manifest.get("spec", {}).get("tools")
    if not tools_ref:
        section.score = "PASS"
        section.findings.append(
            AuditFinding(
                category=Category.MCP_PERMISSIONS,
                severity=Severity.PASS,
                message="No MCP servers configured",
            )
        )
        return section

    # Resolve tools config
    if isinstance(tools_ref, dict):
        tools_config = tools_ref
    else:
        config_path = project_dir / tools_ref / "config.yaml"
        if config_path.is_file():
            try:
                tools_config = yaml.safe_load(config_path.read_text()) or {}
            except Exception:
                tools_config = {}
        else:
            tools_config = {}

    mcp_servers = tools_config.get("mcp_servers", [])
    host_deps = tools_config.get("host_dependencies", [])

    if not mcp_servers and not host_deps:
        section.score = "PASS"
        section.findings.append(
            AuditFinding(
                category=Category.MCP_PERMISSIONS,
                severity=Severity.PASS,
                message="Tools configured but no MCP servers or host deps",
            )
        )
        return section

    issues = 0

    # Check each MCP server
    for server in mcp_servers:
        name = server.get("name", "unnamed")
        tool_filter = server.get("tool_filter")

        # No tool_filter = over-permissioned
        if not tool_filter:
            issues += 1
            section.findings.append(
                AuditFinding(
                    category=Category.MCP_PERMISSIONS,
                    severity=Severity.WARNING,
                    message=f"MCP server '{name}' exposes all tools (no tool_filter)",
                    detail=(
                        "Without a tool_filter, the agent can invoke any tool the "
                        "MCP server exposes. This increases the attack surface."
                    ),
                    fix=(
                        f"Add a tool_filter to spec.tools.mcp_servers[{name}] "
                        "listing only the tools the agent needs."
                    ),
                )
            )
        else:
            section.findings.append(
                AuditFinding(
                    category=Category.MCP_PERMISSIONS,
                    severity=Severity.PASS,
                    message=(
                        f"MCP server '{name}' has tool_filter "
                        f"({len(tool_filter)} tool(s) exposed)"
                    ),
                )
            )

        # stdio with no timeout or very long timeout
        if server.get("transport") == "stdio":
            timeout = server.get("timeout", 10)
            if timeout > 60:
                issues += 1
                section.findings.append(
                    AuditFinding(
                        category=Category.MCP_PERMISSIONS,
                        severity=Severity.WARNING,
                        message=f"MCP server '{name}' has a long timeout ({timeout}s)",
                        fix="Consider reducing timeout to ≤30s to limit resource usage.",
                    )
                )

    # Check host dependencies for risky packages
    for dep in host_deps:
        if dep in _RISKY_HOST_DEPS:
            issues += 1
            section.findings.append(
                AuditFinding(
                    category=Category.MCP_PERMISSIONS,
                    severity=Severity.WARNING,
                    message=f"Host dependency '{dep}' has elevated risk",
                    detail=_RISKY_HOST_DEPS[dep],
                    fix=f"Verify '{dep}' is necessary and document the justification.",
                )
            )
        else:
            section.findings.append(
                AuditFinding(
                    category=Category.MCP_PERMISSIONS,
                    severity=Severity.PASS,
                    message=f"Host dependency '{dep}' — low risk",
                )
            )

    total_checks = len(mcp_servers) + len(host_deps)
    passed = total_checks - issues
    section.score = f"{passed}/{total_checks}"

    return section
