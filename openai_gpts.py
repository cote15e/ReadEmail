"""
Модуль связи с OpenAI (ChatGPT) GPTs для краткого анализа ОДНОЙ статьи.

Отправляет в ChatGPT только заголовок и текст одной статьи и возвращает текст аннотации.
"""

import os
from typing import Dict, Any, Optional


SINGLE_ARTICLE_SYSTEM_INSTRUCTION = (
    "Ты — аналитик статей. На вход ты получаешь заголовок и полный текст одной статьи.\n"
    "Сформируй краткую аннотацию на РУССКОМ языке, объёмом 2–4 предложения.\n"
    "Не придумывай факты, которых нет в тексте. Тон нейтральный, без эмоциональных оценок.\n"
    "Ответ верни ТОЛЬКО в виде чистого текста аннотации, без JSON, списков и пояснений."
)


def summarize_article(
    title: str,
    text: str,
    api_key: Optional[str] = None,
    model: str = "gpt-4o",
    system_instruction: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Анализирует одну статью и возвращает краткую аннотацию (summary).

    Args:
        title: заголовок статьи
        text: полный текст статьи
        api_key: OpenAI API ключ (по умолчанию берётся из OPENAI_API_KEY)
        model: модель OpenAI (по умолчанию gpt-4o)
        system_instruction: необязательная своя системная инструкция
        **kwargs: дополнительные параметры для client.chat.completions.create

    Returns:
        {"summary": "..."} либо {"error": "..."}
    """
    try:
        from openai import OpenAI
    except ImportError:
        return {"error": "OpenAI package not installed. Run: pip install openai"}

    key = api_key or os.getenv("OPENAI_API_KEY")
    if not key or not key.strip():
        return {"error": "OPENAI_API_KEY is not set"}

    client = OpenAI(api_key=key)

    system_content = system_instruction or SINGLE_ARTICLE_SYSTEM_INSTRUCTION

    user_content = (
        f"Заголовок:\n{title.strip()}\n\n"
        f"Текст статьи:\n{text.strip()}"
    )

    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]

    create_kwargs = {"model": model, "messages": messages, **kwargs}

    try:
        response = client.chat.completions.create(**create_kwargs)
        choice = response.choices[0] if response.choices else None
        if choice and choice.message and choice.message.content:
            return {"summary": choice.message.content.strip(), "raw": response}
        return {"summary": "", "raw": response}
    except Exception as e:
        return {"error": str(e)}
