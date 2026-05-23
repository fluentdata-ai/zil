"""
svt/tools/shell.py

Tool to execute shell commands inside the workspace. Uses a binary
allowlist and denies dangerous flag patterns.
"""
from __future__ import annotations

import shlex
import subprocess

from svt.tools.filesystem import _workspace_ctx

# Allowed binaries. Tweak for the target repo's actual tooling.
ALLOWED_BINARIES: set[str] = {
    # Python tooling
    "python", "python3", "pip", "uv",
    "pytest", "ruff", "black", "mypy", "isort",
    "protoc", "buf",
    # Node / JS monorepo tooling (composable-app uses pnpm + turbo)
    "node", "npm", "npx", "pnpm", "turbo",
    "tsc", "prettier", "eslint",
    # Unix utilities
    "ls", "cat", "grep", "find", "head", "tail", "wc", "echo", "test",
    "make",
    # VCS / PR tooling (needed for fd-submit-changes)
    "git", "gh",
}

# Dangerous flag patterns — denied even if the binary is allowed.
DENIED_SUBSTRINGS: tuple[str, ...] = (
    "--force",
    "-f ",
    "push -f",
    "reset --hard",
    "clean -fdx",
    "filter-branch",
    "rm -rf",
    "sudo",
)

DEFAULT_TIMEOUT_SECS = 300
MAX_TIMEOUT_SECS = 900
MAX_OUTPUT_BYTES = 20_000


def run_shell_command(command: str, timeout_seconds: int = DEFAULT_TIMEOUT_SECS) -> dict:
    """Executes a shell command inside the repo workspace.

    Only allowlisted binaries are permitted. The command runs without a
    shell layer (no pipes or redirections). Dangerous flags (`--force`,
    `reset --hard`, `rm -rf`...) are blocked even for allowed binaries.

    Args:
        command: command with arguments, e.g. "pytest -q tests/".
        timeout_seconds: max execution time. Default 120, max 900.

    Returns:
        dict with status, returncode, stdout/stderr (truncated), error.
    """
    try:
        parts = shlex.split(command)
        if not parts:
            return {"status": "error", "error": "empty command"}

        binary = parts[0]
        if binary not in ALLOWED_BINARIES:
            return {
                "status": "error",
                "error": (
                    f"binary '{binary}' not allowed. "
                    f"Allowed: {sorted(ALLOWED_BINARIES)}"
                ),
            }

        lowered = command.lower()
        for pattern in DENIED_SUBSTRINGS:
            if pattern in lowered:
                return {
                    "status": "error",
                    "error": f"denied flag pattern: '{pattern.strip()}'",
                }

        timeout = min(max(1, timeout_seconds), MAX_TIMEOUT_SECS)
        workspace = _workspace_ctx.get()

        result = subprocess.run(  # noqa: S603
            parts,
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "status": "ok",
            "returncode": result.returncode,
            "stdout": _truncate(result.stdout),
            "stderr": _truncate(result.stderr),
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": f"timeout after {timeout_seconds}s"}
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "error": str(e)}


def _truncate(text: str) -> str:
    data = text.encode("utf-8", errors="replace")
    if len(data) <= MAX_OUTPUT_BYTES:
        return text
    cut = data[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
    return cut + f"\n...[truncated, {len(data) - MAX_OUTPUT_BYTES} bytes omitted]"
