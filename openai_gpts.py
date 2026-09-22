"""
Модуль связи с AI (OpenAI-совместимый Chat Completions) для краткого анализа ОДНОЙ статьи.

Поддерживаемые провайдеры (переключение через AI_PROVIDER):
  - openai     — https://api.openai.com/v1
  - openrouter — https://openrouter.ai/api/v1
  - routerai   — https://routerai.ru/api/v1

Отправляет только заголовок и текст одной статьи и возвращает текст аннотации.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional


SINGLE_ARTICLE_SYSTEM_INSTRUCTION = (
    "Ты — аналитик статей. На вход ты получаешь заголовок и полный текст одной статьи.\n"
    "Сформируй краткую аннотацию на РУССКОМ языке, объёмом 2–4 предложения.\n"
    "Не придумывай факты, которых нет в тексте. Тон нейтральный, без эмоциональных оценок.\n"
    "Ответ верни ТОЛЬКО в виде чистого текста аннотации, без JSON, списков и пояснений."
)

# Имена провайдеров (значение AI_PROVIDER)
PROVIDER_OPENAI = "openai"
PROVIDER_OPENROUTER = "openrouter"
PROVIDER_ROUTERAI = "routerai"

_SUPPORTED_PROVIDERS = (PROVIDER_OPENAI, PROVIDER_OPENROUTER, PROVIDER_ROUTERAI)

_PROVIDER_DEFAULTS: Dict[str, Dict[str, Any]] = {
    PROVIDER_OPENAI: {
        "base_url": None,  # официальный OpenAI SDK default
        "api_key_env": ("OPENAI_API_KEY", "AI_API_KEY"),
        "default_model": "gpt-4o",
        "default_headers": None,
    },
    PROVIDER_OPENROUTER: {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": ("OPENROUTER_API_KEY", "AI_API_KEY", "OPENAI_API_KEY"),
        "default_model": "openai/gpt-4o",
        "default_headers": {
            # Опциональная атрибуция для рейтингов OpenRouter
            "HTTP-Referer": "https://github.com/medium-digest-reader",
            "X-OpenRouter-Title": "Medium Digest Reader",
        },
    },
    PROVIDER_ROUTERAI: {
        "base_url": "https://routerai.ru/api/v1",
        "api_key_env": ("ROUTERAI_API_KEY", "AI_API_KEY", "OPENAI_API_KEY"),
        "default_model": "openai/gpt-4o",
        "default_headers": None,
    },
}


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    api_key: str
    base_url: Optional[str]
    model: str
    default_headers: Optional[Dict[str, str]] = None


def normalize_provider(name: Optional[str]) -> str:
    """Normalize provider name; unknown values fall back to openai."""
    raw = (name or PROVIDER_OPENAI).strip().lower()
    aliases = {
        "openai": PROVIDER_OPENAI,
        "open-ai": PROVIDER_OPENAI,
        "openrouter": PROVIDER_OPENROUTER,
        "open-router": PROVIDER_OPENROUTER,
        "routerai": PROVIDER_ROUTERAI,
        "router-ai": PROVIDER_ROUTERAI,
        "router.ai": PROVIDER_ROUTERAI,
    }
    return aliases.get(raw, raw if raw in _SUPPORTED_PROVIDERS else PROVIDER_OPENAI)


def _first_env(*names: str) -> Optional[str]:
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return None


def resolve_provider_config(
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
) -> ProviderConfig:
    """
    Resolve provider settings from arguments and environment.

    Env:
      AI_PROVIDER          — openai | openrouter | routerai
      AI_MODEL / OPENAI_MODEL — имя модели
      AI_BASE_URL          — переопределение base_url
      AI_API_KEY           — общий ключ (fallback)
      OPENAI_API_KEY / OPENROUTER_API_KEY / ROUTERAI_API_KEY — ключи провайдеров
    """
    name = normalize_provider(provider or os.getenv("AI_PROVIDER"))
    defaults = _PROVIDER_DEFAULTS[name]

    key = (api_key or "").strip() or _first_env(*defaults["api_key_env"])
    if not key:
        env_hint = " / ".join(defaults["api_key_env"])
        raise ValueError(f"API key is not set for provider '{name}' (checked: {env_hint})")

    resolved_model = (
        (model or "").strip()
        or _first_env("AI_MODEL", "OPENAI_MODEL")
        or defaults["default_model"]
    )

    resolved_base = (
        (base_url or "").strip()
        or _first_env("AI_BASE_URL")
        or defaults["base_url"]
    )

    return ProviderConfig(
        name=name,
        api_key=key,
        base_url=resolved_base or None,
        model=resolved_model,
        default_headers=defaults.get("default_headers"),
    )


def create_client(config: ProviderConfig):
    """Create an OpenAI-compatible client for the given provider config."""
    from openai import OpenAI

    kwargs: Dict[str, Any] = {"api_key": config.api_key}
    if config.base_url:
        kwargs["base_url"] = config.base_url
    if config.default_headers:
        kwargs["default_headers"] = config.default_headers
    return OpenAI(**kwargs)


def summarize_article(
    title: str,
    text: str,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    base_url: Optional[str] = None,
    system_instruction: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Анализирует одну статью и возвращает краткую аннотацию (summary).

    Args:
        title: заголовок статьи
        text: полный текст статьи
        api_key: API-ключ (иначе из env выбранного провайдера)
        model: модель (иначе AI_MODEL / OPENAI_MODEL / default провайдера)
        provider: openai | openrouter | routerai (иначе AI_PROVIDER)
        base_url: переопределение endpoint (иначе AI_BASE_URL / default)
        system_instruction: необязательная своя системная инструкция
        **kwargs: дополнительные параметры для client.chat.completions.create

    Returns:
        {"summary": "...", "provider": "...", "model": "..."} либо {"error": "..."}
    """
    try:
        from openai import OpenAI  # noqa: F401 — проверка установки пакета
    except ImportError:
        return {"error": "OpenAI package not installed. Run: pip install openai"}

    try:
        config = resolve_provider_config(
            provider=provider,
            api_key=api_key,
            model=model,
            base_url=base_url,
        )
    except ValueError as e:
        return {"error": str(e)}

    client = create_client(config)

    system_content = system_instruction or SINGLE_ARTICLE_SYSTEM_INSTRUCTION
    user_content = (
        f"Заголовок:\n{title.strip()}\n\n"
        f"Текст статьи:\n{text.strip()}"
    )

    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]

    create_kwargs = {"model": config.model, "messages": messages, **kwargs}

    try:
        response = client.chat.completions.create(**create_kwargs)
        choice = response.choices[0] if response.choices else None
        summary = ""
        if choice and choice.message and choice.message.content:
            summary = choice.message.content.strip()
        return {
            "summary": summary,
            "provider": config.name,
            "model": config.model,
            "raw": response,
        }
    except Exception as e:
        return {"error": str(e), "provider": config.name, "model": config.model}
