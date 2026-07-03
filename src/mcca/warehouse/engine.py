"""SQLAlchemy engine factory for the warehouse.

Isolated here so nothing else constructs engines directly. The URL comes from Settings
(env/.env), never hardcoded.
"""

from __future__ import annotations

from sqlalchemy import Engine, create_engine

from mcca.config import Settings, get_settings


def create_warehouse_engine(settings: Settings | None = None, **kwargs) -> Engine:
    """Create a SQLAlchemy Engine for the warehouse from Settings.database_url."""
    settings = settings or get_settings()
    return create_engine(settings.database_url, future=True, **kwargs)
