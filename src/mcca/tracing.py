"""LLM tracing via Langfuse (observability for agent runs).

Off by default; enabled by config (MCCA_LANGFUSE_* + MCCA_LANGFUSE_ENABLED=true). When
enabled, `tracing_config()` returns a LangChain config carrying a Langfuse callback
handler, which is passed to `graph.invoke(...)` so every agent run is traced. Works with
Langfuse Cloud (free tier) or a self-hosted instance (set MCCA_LANGFUSE_HOST). Secret
values are never logged.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from mcca.config import Settings, get_settings

logger = logging.getLogger(__name__)


def _enabled(settings: Settings) -> bool:
    return bool(
        settings.langfuse_enabled and settings.langfuse_public_key and settings.langfuse_secret_key
    )


def get_callback_handler(settings: Settings | None = None) -> Any | None:
    """Return a Langfuse LangChain callback handler if tracing is enabled, else None."""
    settings = settings or get_settings()
    if not _enabled(settings):
        return None

    os.environ["LANGFUSE_PUBLIC_KEY"] = settings.langfuse_public_key or ""
    os.environ["LANGFUSE_SECRET_KEY"] = settings.langfuse_secret_key or ""
    os.environ["LANGFUSE_HOST"] = settings.langfuse_host

    try:  # langfuse v3
        from langfuse.langchain import CallbackHandler
    except ImportError:
        try:  # langfuse v2
            from langfuse.callback import CallbackHandler  # type: ignore[no-redef]
        except ImportError as exc:
            logger.warning("Langfuse enabled but not importable: %s", exc)
            return None

    try:
        return CallbackHandler()
    except Exception as exc:  # noqa: BLE001 - tracing must never break the app
        logger.warning("Could not initialise Langfuse handler: %s", exc)
        return None


def tracing_config(settings: Settings | None = None) -> dict[str, Any]:
    """A LangChain run config with the Langfuse handler (empty if tracing is off)."""
    handler = get_callback_handler(settings)
    return {"callbacks": [handler]} if handler else {}


def flush_tracing(settings: Settings | None = None) -> None:
    """Flush buffered traces to Langfuse (call before a short-lived process exits)."""
    settings = settings or get_settings()
    if not _enabled(settings):
        return
    try:
        from langfuse import get_client

        get_client().flush()
    except Exception as exc:  # noqa: BLE001 - flushing must never break the app
        logger.warning("Langfuse flush failed: %s", exc)
