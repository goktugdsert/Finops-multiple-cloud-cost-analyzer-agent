"""Typed application configuration, loaded from environment / .env.

Secrets are never hardcoded. All settings come from environment variables (prefixed
`MCCA_`) or a local `.env` file. See `.env.example` for the documented set.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the agent and its data-access layer."""

    model_config = SettingsConfigDict(
        env_prefix="MCCA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Warehouse -----------------------------------------------------------
    database_url: str = Field(
        default="postgresql+psycopg://mcca:mcca@localhost:5432/mcca",
        description="SQLAlchemy URL for the warehouse (Postgres in v1).",
    )

    # --- AWS (read-only, least-privilege) ------------------------------------
    aws_region: str = Field(default="us-east-1")
    aws_profile: str | None = Field(default=None)
    aws_access_key_id: str | None = Field(default=None)
    aws_secret_access_key: str | None = Field(default=None)
    aws_session_token: str | None = Field(default=None)

    # --- LangSmith (tracing wired in from day one) ---------------------------
    langsmith_tracing: bool = Field(default=False)
    langsmith_project: str = Field(default="mcca-agent")
    langsmith_api_key: str | None = Field(default=None)
    langsmith_endpoint: str | None = Field(default=None)

    # --- App -----------------------------------------------------------------
    log_level: str = Field(default="INFO")


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (single source of truth per process)."""
    return Settings()
