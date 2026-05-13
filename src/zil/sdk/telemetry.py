"""Set up OpenTelemetry tracing from observability/config.yaml."""

from __future__ import annotations

import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

_ENDPOINT_ENV = "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"
_SERVICE_NAME_ENV = "OTEL_SERVICE_NAME"
_RESOURCE_ATTRS_ENV = "OTEL_RESOURCE_ATTRIBUTES"

_ENV_PATTERN = re.compile(r"\$\{([^}]+)}")


def _resolve_env_refs(value: str) -> str:
    """Replace ``${VAR}`` placeholders with their environment values."""

    def _replace(m: re.Match[str]) -> str:
        return os.environ.get(m.group(1), "")

    return _ENV_PATTERN.sub(_replace, value)


def setup_telemetry(
    observability: dict[str, Any] | None,
    *,
    agent_name: str = "",
    agent_version: str = "",
) -> bool:
    """Configure OTel providers based on observability config.

    Sets standard OTel environment variables, injects Zil-specific
    resource attributes, then calls ADK's ``maybe_set_otel_providers()``
    to register exporters.

    Returns ``True`` if tracing was activated, ``False`` otherwise.
    """
    if not observability:
        return False

    tracing = observability.get("observability", {}).get("tracing", {})
    endpoint = tracing.get("endpoint", "")
    if not endpoint:
        return False

    # Resolve ${ENV_VAR} references in endpoint
    resolved_endpoint = _resolve_env_refs(endpoint)
    if not resolved_endpoint:
        logger.debug("Tracing endpoint resolved to empty — skipping telemetry setup.")
        return False

    # Set standard OTel env vars (only if not already set by user)
    if not os.environ.get(_ENDPOINT_ENV):
        os.environ[_ENDPOINT_ENV] = resolved_endpoint

    if not os.environ.get(_SERVICE_NAME_ENV) and agent_name:
        os.environ[_SERVICE_NAME_ENV] = agent_name

    # Build resource attributes
    resource_attrs: dict[str, str] = {}
    if agent_name:
        resource_attrs["agent.name"] = agent_name
    if agent_version:
        resource_attrs["agent.version"] = agent_version

    # Merge with any user-defined resource attributes from config
    config_attrs = observability.get("observability", {}).get("resource_attributes", {})
    if isinstance(config_attrs, dict):
        for k, v in config_attrs.items():
            resource_attrs.setdefault(str(k), _resolve_env_refs(str(v)))

    # Append to existing OTEL_RESOURCE_ATTRIBUTES
    existing = os.environ.get(_RESOURCE_ATTRS_ENV, "")
    new_pairs = ",".join(f"{k}={v}" for k, v in resource_attrs.items() if v)
    if existing and new_pairs:
        os.environ[_RESOURCE_ATTRS_ENV] = f"{existing},{new_pairs}"
    elif new_pairs:
        os.environ[_RESOURCE_ATTRS_ENV] = new_pairs

    # Call ADK's telemetry setup
    try:
        from google.adk.telemetry.setup import maybe_set_otel_providers

        maybe_set_otel_providers()
        logger.info("Telemetry active — exporting traces to %s", resolved_endpoint)
        return True
    except ImportError:
        logger.debug("google-adk telemetry not available — skipping.")
        return False
    except Exception:
        logger.warning("Failed to initialise OTel providers.", exc_info=True)
        return False


def setup_console_telemetry(
    *,
    agent_name: str = "",
    agent_version: str = "",
) -> bool:
    """Set up a console span exporter for local development.

    Prints span summaries to stderr — no external collector needed.
    Returns ``True`` if the console exporter was installed.
    """
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            ConsoleSpanExporter,
            SimpleSpanProcessor,
        )
    except ImportError:
        logger.debug("opentelemetry-sdk not installed — cannot set up console tracing.")
        return False

    attrs: dict[str, str] = {}
    if agent_name:
        attrs["service.name"] = agent_name
        attrs["agent.name"] = agent_name
    if agent_version:
        attrs["agent.version"] = agent_version

    resource = Resource.create(attrs)
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)

    logger.info("Console tracing active — spans printed to stderr.")
    return True
