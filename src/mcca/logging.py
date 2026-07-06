"""Logging setup and LangSmith environment wiring.

LangSmith is configured from Settings so tracing is available from day one. We only
export the standard LangChain/LangSmith env vars when tracing is explicitly enabled;
we never print or log secret values.
"""

from __future__ import annotations

import logging
import os

from mcca.config import Settings, get_settings


def configure_logging(settings: Settings | None = None) -> None:
    """Configure root logging and, if enabled, LangSmith tracing env vars."""
    settings = settings or get_settings()

    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)-5.5s [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    # Quiet noisy HTTP/provider client logs so agent output stays readable.
    for noisy in ("httpx", "httpcore", "google_genai", "urllib3", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    if settings.langsmith_tracing:
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
        if settings.langsmith_api_key:
            os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
        if settings.langsmith_endpoint:
            os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint
