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
    aws_billing_account_id: str | None = Field(
        default=None,
        description=(
            "Payer/billing account id stamped onto FOCUS rows ingested via Cost "
            "Explorer, which omits the account unless grouped by LINKED_ACCOUNT "
            "(and CE allows only 2 group-by dimensions). Falls back to 'unknown'."
        ),
    )

    # --- Azure (read-only, least-privilege) ----------------------------------
    azure_billing_account_id: str | None = Field(default=None)
    azure_subscription_id: str | None = Field(default=None)
    azure_tenant_id: str | None = Field(default=None)

    # --- GCP (read-only; BigQuery billing export) ----------------------------
    gcp_billing_account_id: str | None = Field(default=None)
    gcp_project_id: str | None = Field(default=None)

    # --- Agent LLM (reasoning/orchestration only — never a source of figures) ---
    # Provider is swappable via config alone; the graph/tools are provider-agnostic.
    # Options: "google" (free tier), "ollama" (free, local), "anthropic", "openai".
    llm_provider: str = Field(default="google")
    agent_model: str | None = Field(default=None)  # None -> provider's default model
    anthropic_api_key: str | None = Field(default=None)
    google_api_key: str | None = Field(default=None)
    openai_api_key: str | None = Field(default=None)
    ollama_base_url: str = Field(default="http://localhost:11434")

    # --- Langfuse (LLM tracing/observability; free cloud tier or self-hosted) --
    langfuse_enabled: bool = Field(default=False)
    langfuse_public_key: str | None = Field(default=None)
    langfuse_secret_key: str | None = Field(default=None)
    langfuse_host: str = Field(default="https://cloud.langfuse.com")

    # --- App -----------------------------------------------------------------
    log_level: str = Field(default="INFO")


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (single source of truth per process)."""
    return Settings()
