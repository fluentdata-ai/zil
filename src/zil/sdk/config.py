"""Zil runtime configuration — validated access to declared env vars."""

from __future__ import annotations

import os
import warnings
from collections.abc import Iterator
from pathlib import Path
from typing import Any


class MissingConfigError(KeyError):
    """Raised when a required config variable is not set."""

    def __init__(self, name: str, description: str = "") -> None:
        detail = f" ({description})" if description else ""
        super().__init__(
            f"Required env var '{name}'{detail} is not set. "
            f"Declare it in spec.env and ensure it is provided at deploy time."
        )
        self.name = name


class AgentConfig:
    """Dict-like access to declared environment variables.

    Resolves values from os.environ using declarations from spec.env
    in the manifest. Validates coverage on initialization.

    Usage::

        import zil

        root_agent = zil.create_agent(...)
        db_url = zil.config["MCP_DB_CONNECTION_STRING"]
        endpoint = zil.config.get("OTEL_ENDPOINT", "http://localhost:4318")
    """

    def __init__(self, declarations: list[dict[str, Any]] | None = None) -> None:
        self._declarations: list[dict[str, Any]] = declarations or []
        self._values: dict[str, str] = {}
        self._secrets: set[str] = set()
        self._initialized = False

    def _initialize(
        self,
        declarations: list[dict[str, Any]],
        project_dir: Path | None = None,
        module_dir: Path | None = None,
    ) -> None:
        """Load values from os.environ based on declarations.

        If *project_dir* or *module_dir* are provided, ``.env`` and
        ``.env.local`` files in those directories are loaded into
        ``os.environ`` first (existing values are never overridden).
        """
        self._declarations = declarations
        self._values = {}
        self._secrets = set()

        # Load dotenv files into os.environ (never override existing)
        _load_env_files(project_dir, module_dir)

        for decl in declarations:
            name = decl.get("name", "")
            if not name:
                continue

            required = decl.get("required", True)
            default = decl.get("default")
            is_secret = decl.get("secret", False)
            description = decl.get("description", "")

            if is_secret:
                self._secrets.add(name)

            # Resolve from environment
            value = os.environ.get(name)

            # Apply default
            if value is None and default is not None:
                value = default

            if value is not None:
                self._values[name] = value
            elif required:
                raise MissingConfigError(name, description)
            else:
                warnings.warn(
                    f"Optional env var '{name}' is not set (no default).",
                    stacklevel=2,
                )

        self._initialized = True

    def __getitem__(self, name: str) -> str:
        """Get a config value by name. Raises KeyError if not found."""
        if not self._initialized:
            raise RuntimeError(
                "zil.config is not initialized. Call zil.create_agent() first."
            )
        if name in self._values:
            return self._values[name]
        # Check if it's a declared but unset optional var
        for decl in self._declarations:
            if decl.get("name") == name:
                raise MissingConfigError(name, decl.get("description", ""))
        raise KeyError(f"'{name}' is not declared in spec.env")

    def get(self, name: str, default: str | None = None) -> str | None:
        """Get a config value with an optional fallback."""
        try:
            return self[name]
        except (KeyError, MissingConfigError):
            return default

    def __contains__(self, name: str) -> bool:
        """Check if a config value is set."""
        return name in self._values

    def __iter__(self) -> Iterator[str]:
        """Iterate over declared variable names that have values."""
        return iter(self._values)

    def __len__(self) -> int:
        """Number of resolved values."""
        return len(self._values)

    def is_secret(self, name: str) -> bool:
        """Check if a variable is marked as secret."""
        return name in self._secrets

    def keys(self) -> list[str]:
        """All resolved variable names."""
        return list(self._values.keys())

    def items(self) -> list[tuple[str, str]]:
        """All resolved (name, value) pairs."""
        return list(self._values.items())

    def __repr__(self) -> str:
        if not self._initialized:
            return "AgentConfig(<not initialized>)"
        redacted = {}
        for k, v in self._values.items():
            redacted[k] = "***" if k in self._secrets else v
        return f"AgentConfig({redacted})"


# ---------------------------------------------------------------------------
# Dotenv file loading
# ---------------------------------------------------------------------------

_ENV_FILENAMES = (".env", ".env.local")


def _load_env_files(
    project_dir: Path | None = None,
    module_dir: Path | None = None,
) -> None:
    """Load ``.env`` and ``.env.local`` into ``os.environ``.

    Files are loaded in order of increasing specificity so that
    more-specific values win.  **Existing** ``os.environ`` entries are
    never overridden — real env vars always take precedence.

    Load order (each fills in what's missing):
      1. ``{project_dir}/.env``
      2. ``{project_dir}/.env.local``
      3. ``{module_dir}/.env``        (skipped if same as project_dir)
      4. ``{module_dir}/.env.local``   (skipped if same as project_dir)
    """
    dirs: list[Path] = []
    if project_dir:
        dirs.append(project_dir.resolve())
    if module_dir:
        resolved = module_dir.resolve()
        if not dirs or resolved != dirs[0]:
            dirs.append(resolved)

    for directory in dirs:
        for filename in _ENV_FILENAMES:
            env_path = directory / filename
            if env_path.is_file():
                for key, val in _parse_dotenv(env_path).items():
                    if key not in os.environ:
                        os.environ[key] = val


def _parse_dotenv(path: Path) -> dict[str, str]:
    """Parse a dotenv file into a dict (comments/blanks skipped)."""
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
            val = val[1:-1]
        values[key] = val
    return values
