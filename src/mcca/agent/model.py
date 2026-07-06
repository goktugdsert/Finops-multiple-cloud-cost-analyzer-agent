"""Chat model factory for the agent — provider-agnostic, selected by config.

The LLM is a reasoning/orchestration engine only; it selects tools and explains their
results, and never produces a figure. Which provider LangChain calls is chosen by
`MCCA_LLM_PROVIDER` (+ the matching key), so it can be swapped with NO code change:

    google    — Gemini (has a free tier)          [langchain-google-genai]
    ollama    — a local model, free, no API key    [langchain-ollama]
    anthropic — Claude (best tool use; paid)        [langchain-anthropic]
    openai    — GPT (paid)                           [langchain-openai]

Provider SDKs are imported lazily so only the one you use needs to be installed/keyed.
"""

from __future__ import annotations

from typing import Any

from mcca.config import Settings, get_settings

# Sensible default model per provider when MCCA_AGENT_MODEL is unset.
DEFAULT_MODELS: dict[str, str] = {
    "google": "gemini-2.5-flash",
    "ollama": "llama3.1",
    "anthropic": "claude-sonnet-5",
    "openai": "gpt-4o-mini",
}


def build_model(settings: Settings | None = None, **kwargs: Any) -> Any:
    """Construct the configured chat model (temperature 0 for determinism)."""
    settings = settings or get_settings()
    provider = settings.llm_provider.lower()
    if provider not in DEFAULT_MODELS:
        raise ValueError(
            f"Unknown MCCA_LLM_PROVIDER {provider!r}. Choose one of {sorted(DEFAULT_MODELS)}."
        )
    model = settings.agent_model or DEFAULT_MODELS[provider]

    if provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI

        extra = {"google_api_key": settings.google_api_key} if settings.google_api_key else {}
        return ChatGoogleGenerativeAI(model=model, temperature=0, **extra, **kwargs)

    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(model=model, temperature=0, base_url=settings.ollama_base_url, **kwargs)

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        extra = {"api_key": settings.anthropic_api_key} if settings.anthropic_api_key else {}
        return ChatAnthropic(model=model, temperature=0, **extra, **kwargs)

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        extra = {"api_key": settings.openai_api_key} if settings.openai_api_key else {}
        return ChatOpenAI(model=model, temperature=0, **extra, **kwargs)

    # Unreachable: provider membership is validated above.
    raise AssertionError(provider)
