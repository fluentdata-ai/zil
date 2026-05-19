"""Translate Zil MCP server declarations into framework-specific toolsets.

This module is the adapter layer between the framework-agnostic YAML
configuration in ``spec.tools.mcp_servers`` and the ADK ``McpToolset``
runtime objects.  When Zil adds support for other frameworks (CrewAI,
LangChain), each will get its own adapter function here.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

# Regex for ${VAR} environment variable references in YAML values.
_ENV_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _resolve_env_refs(value: str) -> str:
    """Replace ``${VAR}`` placeholders with values from ``os.environ``.

    If a referenced variable is not set, the placeholder is left as-is
    (the MCP server process may resolve it itself, or the connection
    will fail with a clear error).
    """
    def _sub(m: re.Match) -> str:
        var_name = m.group(1)
        return os.environ.get(var_name, m.group(0))
    return _ENV_VAR_RE.sub(_sub, value)


def _resolve_env_refs_in_list(items: list[str]) -> list[str]:
    """Resolve ``${VAR}`` references in a list of strings."""
    return [_resolve_env_refs(item) for item in items]


def _resolve_env_refs_in_dict(mapping: dict[str, str]) -> dict[str, str]:
    """Resolve ``${VAR}`` references in dict values."""
    return {k: _resolve_env_refs(v) for k, v in mapping.items()}


# ---------------------------------------------------------------------------
# ADK adapter
# ---------------------------------------------------------------------------


def create_mcp_toolsets_adk(
    mcp_servers: list[dict[str, Any]],
) -> list[Any]:
    """Create ADK ``McpToolset`` instances from Zil MCP server declarations.

    Each entry in *mcp_servers* is a dict matching the ``mcpServer`` schema
    (name, transport, command/url, args, env, tool_filter, timeout).

    Returns a list of ``McpToolset`` instances ready to pass to
    ``LlmAgent(tools=...)``.

    Raises ``ImportError`` if the required ADK/MCP packages are not installed.
    """
    try:
        from google.adk.tools.mcp_tool import McpToolset
        from google.adk.tools.mcp_tool.mcp_session_manager import (
            SseConnectionParams,
            StdioConnectionParams,
        )
        from mcp import StdioServerParameters
    except ImportError:
        raise ImportError(
            "google-adk and mcp are required for MCP server integration. "
            "Install them with: pip install 'zil-ai[adk]'"
        ) from None

    toolsets: list[Any] = []

    for server in mcp_servers:
        name = server["name"]
        transport = server["transport"]
        tool_filter = server.get("tool_filter") or None
        timeout = server.get("timeout", 10)

        if transport == "stdio":
            command = server.get("command")
            if not command:
                logger.warning(
                    "MCP server %r has transport=stdio but no command — skipping",
                    name,
                )
                continue

            args = _resolve_env_refs_in_list(server.get("args", []))
            env_vars = _resolve_env_refs_in_dict(server.get("env", {}))

            # Merge with current environment so the child process inherits
            # PATH and other essentials.
            process_env = {**os.environ, **env_vars} if env_vars else None

            toolset = McpToolset(
                connection_params=StdioConnectionParams(
                    server_params=StdioServerParameters(
                        command=command,
                        args=args,
                        env=process_env,
                    ),
                    timeout=timeout,
                ),
                tool_filter=tool_filter,
            )
            toolsets.append(toolset)

            logger.info(
                "MCP server %r configured (stdio: %s %s, filter=%s)",
                name,
                command,
                " ".join(args),
                tool_filter or "all",
            )

        elif transport == "sse":
            url = server.get("url")
            if not url:
                logger.warning(
                    "MCP server %r has transport=sse but no url — skipping",
                    name,
                )
                continue

            url = _resolve_env_refs(url)
            headers = _resolve_env_refs_in_dict(server.get("headers", {}))

            toolset = McpToolset(
                connection_params=SseConnectionParams(
                    url=url,
                    headers=headers or None,
                ),
                tool_filter=tool_filter,
            )
            toolsets.append(toolset)

            logger.info(
                "MCP server %r configured (sse: %s, filter=%s)",
                name,
                url,
                tool_filter or "all",
            )

        else:
            logger.warning(
                "MCP server %r has unknown transport %r — skipping",
                name,
                transport,
            )

    return toolsets
