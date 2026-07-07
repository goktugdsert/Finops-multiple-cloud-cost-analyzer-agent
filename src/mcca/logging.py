"""Logging setup. LLM tracing lives in `mcca.tracing` (Langfuse)."""

from __future__ import annotations

import logging

from mcca.config import Settings, get_settings


def configure_logging(settings: Settings | None = None) -> None:
    """Configure root logging levels (quieting noisy client libraries)."""
    settings = settings or get_settings()

    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)-5.5s [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    # Quiet noisy HTTP/provider client logs so agent output stays readable.
    for noisy in ("httpx", "httpcore", "google_genai", "urllib3", "anthropic", "langfuse"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
