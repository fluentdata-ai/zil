"""
svt/tools/filesystem.py

Filesystem tools for agents to safely explore and modify the cloned repo.
All paths are validated against the workspace root to prevent path traversal.

The active workspace is injected via a ContextVar that runner.py sets
before invoking the agent session.
"""
from __future__ import annotations

import contextvars
from pathlib import Path

_workspace_ctx: contextvars.ContextVar[Path] = contextvars.ContextVar("agent_workspace")


def set_workspace(path: Path) -> contextvars.Token:
    return _workspace_ctx.set(path.resolve())


def reset_workspace(token: contextvars.Token) -> None:
    _workspace_ctx.reset(token)


def _resolve_safe(relative_path: str) -> Path:
    """Resolves a relative path against the workspace and verifies it stays inside."""
    workspace = _workspace_ctx.get()
    target = (workspace / relative_path).resolve()
    if workspace != target and workspace not in target.parents:
        raise ValueError(
            f"Path '{relative_path}' is outside the workspace. "
            f"Only paths relative to {workspace} are allowed."
        )
    return target


resolve_safe = _resolve_safe  # public alias


# -----------------------------------------------------------------------------
# Tools exposed to the LLM
# -----------------------------------------------------------------------------

def list_files(relative_path: str = ".") -> dict:
    """Lists files and directories inside the workspace.

    Args:
        relative_path: path relative to the repo root. Use "." for root.

    Returns:
        dict with status, entries (with "/" suffix for directories), and
        error if something went wrong.
    """
    try:
        target = _resolve_safe(relative_path)
        if not target.exists():
            return {"status": "error", "error": f"does not exist: {relative_path}"}
        if not target.is_dir():
            return {"status": "error", "error": f"not a directory: {relative_path}"}

        entries = []
        for child in sorted(target.iterdir()):
            if child.name == ".git":
                continue  # don't pollute the LLM's context with .git internals
            entries.append(child.name + ("/" if child.is_dir() else ""))
        return {"status": "ok", "entries": entries}
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "error": str(e)}


def read_file(relative_path: str) -> dict:
    """Reads the content of a text file from the repo.

    Args:
        relative_path: path relative to the repo root.

    Returns:
        dict with status, content, and error if applicable.
    """
    try:
        target = _resolve_safe(relative_path)
        if not target.is_file():
            return {"status": "error", "error": f"not a file: {relative_path}"}
        max_bytes = 200_000
        if target.stat().st_size > max_bytes:
            return {
                "status": "error",
                "error": f"file too large (> {max_bytes} bytes), read it in chunks",
            }
        return {"status": "ok", "content": target.read_text(encoding="utf-8")}
    except UnicodeDecodeError:
        return {"status": "error", "error": "binary file, cannot read as text"}
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "error": str(e)}


def grep_files(pattern: str, path: str = ".", include: str = "") -> dict:
    """Search for a regex pattern across files in the workspace.

    Much faster than listing directories and reading files one-by-one.
    Use this to locate relevant files before reading them.

    Args:
        pattern: regex pattern to search for (passed to grep -E).
        path: directory or file to search in, relative to repo root.
            Defaults to "." (entire workspace).
        include: optional glob to restrict file types, e.g. "*.ts" or "*.py".
            Leave empty to search all text files.

    Returns:
        dict with status, matches (list of "file:line:text" strings, max 100),
        and error if something went wrong.
    """
    import subprocess  # noqa: PLC0415

    try:
        target = _resolve_safe(path)
        cmd = ["grep", "-rEn", "--include=*.ts,*.js,*.py,*.json,*.md,*.yaml,*.yml" if not include else f"--include={include}", pattern, str(target)]
        if include:
            cmd = ["grep", "-rEn", f"--include={include}", pattern, str(target)]
        else:
            cmd = ["grep", "-rEn",
                   "--include=*.ts", "--include=*.tsx", "--include=*.js",
                   "--include=*.py", "--include=*.json", "--include=*.md",
                   "--include=*.yaml", "--include=*.yml",
                   "--exclude-dir=.git", "--exclude-dir=node_modules",
                   "--exclude-dir=dist", "--exclude-dir=.next",
                   pattern, str(target)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        workspace = _workspace_ctx.get()
        lines = result.stdout.splitlines()
        # Strip absolute workspace prefix from paths for readability
        matches = [l.replace(str(workspace) + "/", "") for l in lines[:100]]
        return {
            "status": "ok",
            "matches": matches,
            "truncated": len(lines) > 100,
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "grep timed out (>15s)"}
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "error": str(e)}


def write_file(relative_path: str, content: str) -> dict:
    """Writes (or overwrites) a text file in the repo.

    Args:
        relative_path: path relative to the repo root. Parent directories
            are created automatically.
        content: full content for the file.

    Returns:
        dict with status, bytes_written, and error if applicable.
    """
    try:
        target = _resolve_safe(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        data = content.encode("utf-8")
        target.write_bytes(data)
        return {"status": "ok", "bytes_written": len(data)}
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "error": str(e)}
