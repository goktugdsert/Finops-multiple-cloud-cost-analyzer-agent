"""Tracing is off unless explicitly enabled with Langfuse keys."""

from __future__ import annotations

from mcca.config import Settings
from mcca.tracing import get_callback_handler, tracing_config


def test_disabled_by_default() -> None:
    settings = Settings(_env_file=None)
    assert get_callback_handler(settings) is None
    assert tracing_config(settings) == {}


def test_enabled_without_keys_stays_off() -> None:
    settings = Settings(_env_file=None, langfuse_enabled=True)
    assert get_callback_handler(settings) is None  # needs keys too


def test_config_shape_when_off() -> None:
    # tracing_config must always return a dict (empty when off) so it is safe to pass
    # straight into graph.invoke(..., config=...).
    assert tracing_config(Settings(_env_file=None)) == {}
