"""Аудит личного бренда в Instagram: реальные данные (Composio) + анализ Claude."""

from __future__ import annotations

import json
import re

import anthropic

import config
from composio_instagram import fetch_snapshot

_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

AUDIT_SYSTEM_PROMPT = """Ты — эксперт по личному бренду и росту в Instagram.

Тебе дан JSON с РЕАЛЬНЫМИ данными Instagram-аккаунта: профиль, метрики за
30 дней и метрики последних постов (views/reach/likes/comments/saved/shares/
total_interactions). Используй только эти данные — никаких выдуманных цифр
и домыслов. Вовлечённость поста считай как total_interactions / reach.

Ответь СТРОГО валидным JSON (без markdown, без ```, без комментариев) вот
такой структуры:

{
  "bio_first_impression": "1-2 предложения: первое впечатление от профиля и био, ясность позиционирования",
  "bio_improved": "готовый улучшенный текст био, короткий, с переносами строк \\n",
  "top_posts": [
    {"caption_snippet": "первые слова подписи поста", "why": "почему пост сработал, с конкретными цифрами из данных"}
  ],
  "weak_content": ["что не работает, пункт 1", "пункт 2", "..."],
  "stop_doing": "1-2 предложения: что конкретно прекратить делать",
  "content_pillars": [
    {"title": "название рубрики с эмодзи", "description": "описание с опорой на данные/примеры из постов"}
  ],
  "quick_wins": ["изменение на этой неделе 1", "изменение 2", "изменение 3"],
  "plan_90_days": [
    {"month": "Месяц 1", "task": "ключевая задача"},
    {"month": "Месяц 2", "task": "ключевая задача"},
    {"month": "Месяц 3", "task": "ключевая задача"}
  ]
}

"top_posts" — 3-5 постов, отсортированных по вовлечённости (total_interactions/reach),
не просто по числу лайков. "content_pillars" — 3-4 рубрики."""


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```\s*$", "", text.strip())
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1:
        text = text[start : end + 1]
    return json.loads(text)


def run_audit() -> tuple[dict, dict]:
    """Возвращает (snapshot, audit): сырые данные Instagram и разбор от Claude."""
    snapshot = fetch_snapshot()

    digest = json.dumps(snapshot, ensure_ascii=False, indent=2)
    response = _client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=6000,
        system=AUDIT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": digest}],
    )
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        audit = _extract_json(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Claude вернул невалидный JSON: {e}\n\n{text[:500]}") from e

    return snapshot, audit
