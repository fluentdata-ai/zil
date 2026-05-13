"""Audit check: Indirect injection surface analysis.

AST-scans tool functions for external data ingestion (HTTP calls, DB queries,
file reads) and flags tools whose return values could carry injected content
without passing through guardrail output checks.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

from zil.sdk.audit import AuditFinding, AuditSection, Category, Severity

logger = logging.getLogger(__name__)

# Patterns indicating external data ingestion
_EXTERNAL_CALL_PATTERNS: dict[str, list[str]] = {
    "HTTP": [
        "requests.get", "requests.post", "requests.put", "requests.patch",
        "requests.delete", "httpx.get", "httpx.post", "httpx.AsyncClient",
        "aiohttp.ClientSession", "urllib.request.urlopen", "fetch",
    ],
    "Database": [
        "cursor.execute", "session.execute", "session.query",
        "connection.execute", "engine.execute",
        ".fetchone", ".fetchall", ".fetchmany",
        "sqlalchemy", "psycopg", "pymongo", "redis",
    ],
    "File system": [
        "open(", "Path(", ".read_text(", ".read_bytes(",
        "os.read", "io.open",
    ],
    "Subprocess": [
        "subprocess.run", "subprocess.Popen", "subprocess.call",
        "os.system", "os.popen",
    ],
}


def _find_agent_module(project_dir: Path) -> Path | None:
    """Find the agent.py file in the project."""
    # Look for {module}/agent.py pattern
    for child in project_dir.iterdir():
        if child.is_dir() and not child.name.startswith("."):
            agent_file = child / "agent.py"
            if agent_file.is_file():
                return agent_file
    # Fallback: agent.py in root
    root_agent = project_dir / "agent.py"
    if root_agent.is_file():
        return root_agent
    return None


def _extract_tool_functions(source: str) -> list[tuple[str, ast.FunctionDef]]:
    """Extract functions that look like tool functions from source code."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    tools: list[tuple[str, ast.FunctionDef]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            # Heuristic: tool functions are top-level, have docstrings,
            # and are not prefixed with underscore
            if not node.name.startswith("_") and node.name != "main":
                tools.append((node.name, node))

    return tools


def _check_function_for_external_calls(
    func_name: str, func_node: ast.FunctionDef, source_lines: list[str]
) -> list[tuple[str, str]]:
    """Check if a function body contains external data ingestion calls."""
    findings: list[tuple[str, str]] = []  # (category, matched_pattern)

    # Get the source text of the function body
    start = func_node.lineno - 1
    end = func_node.end_lineno or start + 1
    func_source = "\n".join(source_lines[start:end])

    for category, patterns in _EXTERNAL_CALL_PATTERNS.items():
        for pattern in patterns:
            if pattern in func_source:
                findings.append((category, pattern))
                break  # One match per category is enough

    return findings


def check_indirect_injection(project_dir: Path) -> AuditSection:
    """Scan tool functions for indirect injection surfaces."""
    section = AuditSection(
        category=Category.INDIRECT_INJECTION,
        title="Indirect Injection Surface",
    )

    agent_file = _find_agent_module(project_dir)
    if agent_file is None:
        section.findings.append(AuditFinding(
            category=Category.INDIRECT_INJECTION,
            severity=Severity.INFO,
            message="No agent.py found — skipping tool analysis",
        ))
        section.score = "N/A"
        return section

    source = agent_file.read_text()
    source_lines = source.splitlines()
    tools = _extract_tool_functions(source)

    if not tools:
        section.findings.append(AuditFinding(
            category=Category.INDIRECT_INJECTION,
            severity=Severity.PASS,
            message="No tool functions detected",
        ))
        section.score = "PASS"
        return section

    # Also scan any other .py files in the same directory for tool implementations
    additional_sources: list[tuple[Path, str]] = []
    agent_dir = agent_file.parent
    for py_file in agent_dir.glob("*.py"):
        if py_file != agent_file and py_file.name != "__init__.py":
            try:
                additional_sources.append((py_file, py_file.read_text()))
            except Exception:
                pass

    for py_path, py_source in additional_sources:
        py_lines = py_source.splitlines()
        extra_tools = _extract_tool_functions(py_source)
        for name, node in extra_tools:
            tools.append((name, node))
            # Extend source_lines tracking
            # We'll re-check with the file's own lines
            externals = _check_function_for_external_calls(name, node, py_lines)
            if externals:
                categories = [cat for cat, _ in externals]
                section.findings.append(AuditFinding(
                    category=Category.INDIRECT_INJECTION,
                    severity=Severity.WARNING,
                    message=(
                        f"tool: {name}() — returns external data "
                        f"({', '.join(categories)})"
                    ),
                    detail=(
                        f"In {py_path.name}: output from external sources could "
                        f"contain injected instructions"
                    ),
                    fix=(
                        f"Route {name}() return value through "
                        f"`guardrails.check_output()` before returning to the agent"
                    ),
                ))
            else:
                section.findings.append(AuditFinding(
                    category=Category.INDIRECT_INJECTION,
                    severity=Severity.PASS,
                    message=f"tool: {name}() — pure computation, no external input",
                ))

    # Check tools from agent.py itself
    risky_count = 0
    for name, node in _extract_tool_functions(source):
        externals = _check_function_for_external_calls(name, node, source_lines)
        if externals:
            categories = [cat for cat, _ in externals]
            risky_count += 1
            section.findings.append(AuditFinding(
                category=Category.INDIRECT_INJECTION,
                severity=Severity.WARNING,
                message=(
                    f"tool: {name}() — returns external data "
                    f"({', '.join(categories)})"
                ),
                detail=(
                    "Output from external sources could contain injected instructions"
                ),
                fix=(
                    f"Route {name}() return value through "
                    f"`guardrails.check_output()` before returning to the agent"
                ),
            ))
        else:
            section.findings.append(AuditFinding(
                category=Category.INDIRECT_INJECTION,
                severity=Severity.PASS,
                message=f"tool: {name}() — pure computation, no external input",
            ))

    if risky_count == 0:
        section.score = "PASS"
    else:
        section.score = f"{risky_count} risk(s)"

    return section
