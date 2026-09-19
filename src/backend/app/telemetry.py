"""OpenTelemetry wiring. Traces export to Application Insights when configured."""

from __future__ import annotations

import logging

from opentelemetry import trace

from .config import get_settings

logger = logging.getLogger(__name__)
_TRACER_NAME = "supply-disruption-response"


def configure_telemetry() -> None:
    settings = get_settings()
    _configure_azure_monitor(settings)
    _instrument_foundry(settings)


def _configure_azure_monitor(settings) -> None:
    if not settings.appinsights_connection:
        logger.info("Application Insights not configured; traces stay local.")
        return
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor

        configure_azure_monitor(
            connection_string=settings.appinsights_connection,
            disable_offline_storage=True,
        )
        logger.info("Application Insights telemetry configured.")
    except Exception as exc:  # telemetry must never break the app
        logger.warning("Could not configure Application Insights: %s", exc)


def _instrument_foundry(settings) -> None:
    """Emits gen_ai spans (agent name, model, token counts) for every Foundry agent call."""
    if not settings.enable_foundry_hosted:
        return
    try:
        from azure.ai.projects.telemetry import AIProjectInstrumentor

        AIProjectInstrumentor().instrument(enable_content_recording=settings.record_prompt_content)
        logger.info(
            "Foundry agent tracing enabled (content recording=%s).", settings.record_prompt_content
        )
    except Exception as exc:
        logger.warning("Could not enable Foundry agent tracing: %s", exc)


def get_tracer() -> trace.Tracer:
    return trace.get_tracer(_TRACER_NAME)
