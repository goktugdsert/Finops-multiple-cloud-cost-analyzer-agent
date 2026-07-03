"""Settings load with sane defaults and read the MCCA_-prefixed env vars."""

from __future__ import annotations

from mcca.config import Settings


def test_defaults(settings: Settings) -> None:
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.aws_region == "us-east-1"
    assert settings.langsmith_tracing is False


def test_env_override(monkeypatch) -> None:
    monkeypatch.setenv("MCCA_AWS_REGION", "eu-west-1")
    monkeypatch.setenv("MCCA_LANGSMITH_TRACING", "true")
    s = Settings(_env_file=None)
    assert s.aws_region == "eu-west-1"
    assert s.langsmith_tracing is True


def test_no_hardcoded_secrets(settings: Settings) -> None:
    # Credentials are absent unless explicitly provided via env/.env.
    assert settings.aws_access_key_id is None
    assert settings.aws_secret_access_key is None
