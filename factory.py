"""Генерация текстов постов: обращение к Claude по своду правил завода
и разбор структурированного ответа."""

import json
import logging
import re

import anthropic

import config
import playbook

logger = logging.getLogger(__name__)

_client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)


class FactoryError(Exception):
    """Не удалось получить пригодный текст — показываем это пользователю."""


def _extract_json(raw: str) -> dict:
    """Достаёт JSON из ответа модели.

    Модель иногда оборачивает ответ в ```json ... ``` или добавляет строку
    до/после, поэтому на голый json.loads полагаться нельзя.
    """
    raw = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(.+?)\s*```", raw, re.S)
    if fenced:
        raw = fenced.group(1)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Последняя попытка: взять кусок от первой { до последней }.
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise FactoryError("Модель вернула ответ, который не удалось разобрать.")


def _clean_variant(v: dict) -> dict | None:
    body = (v.get("body") or "").strip()
    if not body:
        return None
    tags = v.get("hashtags") or []
    if isinstance(tags, str):
        tags = tags.split()
    tags = [t if t.startswith("#") else f"#{t}" for t in tags if str(t).strip()]
    return {
        "hook": (v.get("hook") or body.split("\n", 1)[0]).strip(),
        "body": body,
        "forward_line": (v.get("forward_line") or "").strip(),
        "hashtags": tags[:8],
        "why": (v.get("why") or "").strip(),
    }


async def make_variants(song: dict, platform: str, note: str = "") -> list[dict]:
    """Просит у Claude три варианта поста. Возвращает список готовых вариантов."""
    system = playbook.build_system_prompt(platform, song)

    user = f"Напиши три варианта поста для площадки {platform} по песне «{song['title']}»."
    if note:
        user += (
            f"\n\nОтдельное указание от Лилии, оно важнее общих правил:\n{note}"
        )

    try:
        response = await _client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=3000,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
    except Exception as e:
        logger.exception("Claude API не ответил при генерации поста")
        raise FactoryError(f"AI не ответил: {e}") from e

    raw = next((b.text for b in response.content if b.type == "text"), "")
    data = _extract_json(raw)

    variants = [c for c in (_clean_variant(v) for v in data.get("variants", [])) if c]
    if not variants:
        raise FactoryError("Модель не вернула ни одного пригодного варианта.")
    return variants[:3]


def format_variant(variant: dict, index: int, total: int) -> str:
    """Собирает вариант в сообщение для Telegram."""
    lines = [f"Вариант {index} из {total}", "", variant["body"]]
    if variant["hashtags"]:
        lines += ["", " ".join(variant["hashtags"])]
    if variant["forward_line"]:
        lines += ["", "— — —", f"Перешлют вот это:\n{variant['forward_line']}"]
    if variant["why"]:
        lines += ["", f"Почему: {variant['why']}"]
    return "\n".join(lines)


def copy_text(variant: dict) -> str:
    """Чистый текст поста для копирования — без служебных пометок."""
    text = variant["body"]
    if variant["hashtags"]:
        text += "\n\n" + " ".join(variant["hashtags"])
    return text
