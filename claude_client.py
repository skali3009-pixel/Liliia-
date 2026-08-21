"""Обёртка над Anthropic API: хранит историю диалога по каждому чату
и отправляет запросы к модели Claude."""

from collections import defaultdict

import anthropic

import config

_client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)

# История сообщений по chat_id: [{"role": "user"/"assistant", "content": "..."}]
_history: dict[int, list[dict]] = defaultdict(list)


def reset_history(chat_id: int) -> None:
    _history.pop(chat_id, None)


async def ask_claude(chat_id: int, user_message: str) -> str:
    """Добавляет сообщение пользователя в историю чата, спрашивает Claude
    и возвращает текстовый ответ (также сохраняя его в историю)."""
    history = _history[chat_id]
    history.append({"role": "user", "content": user_message})
    # Не даём истории расти бесконечно — оставляем последние N сообщений.
    del history[: -config.MAX_HISTORY_MESSAGES]

    response = await _client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=config.MAX_TOKENS,
        system=config.SYSTEM_PROMPT,
        messages=history,
    )

    reply_text = next(
        (block.text for block in response.content if block.type == "text"), ""
    )
    history.append({"role": "assistant", "content": reply_text})
    return reply_text or "(пустой ответ от модели)"
