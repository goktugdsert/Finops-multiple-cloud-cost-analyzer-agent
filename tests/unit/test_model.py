"""The model factory selects a provider from config and fails clearly on a bad one."""

from __future__ import annotations

import pytest

from mcca.agent.model import DEFAULT_MODELS, build_model
from mcca.config import Settings


def test_defaults_for_every_supported_provider() -> None:
    assert set(DEFAULT_MODELS) == {"google", "ollama", "anthropic", "openai"}


def test_unknown_provider_raises() -> None:
    settings = Settings(_env_file=None, llm_provider="not-a-provider")
    with pytest.raises(ValueError, match="Unknown MCCA_LLM_PROVIDER"):
        build_model(settings)
