"""Старые команды AI-ассистента: общий чат с Claude и Instagram-аудит.

Сохранены для обратной совместимости отдельно от нового сценария питания/
тренировок. Подключены последним роутером — сработают только если апдейт не
обработали онбординг и главное меню (например, произвольный текст вне FSM).
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message

import config
from claude_client import ask_claude, reset_history
from composio_instagram import InstagramNotConnected

logger = logging.getLogger(__name__)
router = Router(name="legacy_assistant")

TELEGRAM_LIMIT = 4096


@router.message(Command("reset"))
async def cmd_reset(message: Message) -> None:
    reset_history(message.chat.id)
    await message.answer("История диалога очищена.")


@router.message(Command("audit"))
async def cmd_audit(message: Message) -> None:
    if not config.COMPOSIO_API_KEY:
        await message.answer(
            "Команда /audit не настроена: в .env не задан COMPOSIO_API_KEY. "
            "Инструкция — в README.md."
        )
        return

    status_message = await message.answer(
        "Собираю данные Instagram и готовлю аудит — это займёт около минуты…"
    )
    await message.bot.send_chat_action(message.chat.id, "upload_document")

    # Тяжёлые импорты — только когда команда реально используется.
    from instagram_audit import run_audit
    from report_pdf import render_pdf

    try:
        snapshot, audit = await asyncio.to_thread(run_audit)
        pdf_path = f"/tmp/instagram_audit_{message.chat.id}.pdf"
        await asyncio.to_thread(render_pdf, snapshot, audit, pdf_path)
    except InstagramNotConnected as e:
        await status_message.edit_text(str(e))
        return
    except Exception:
        logger.exception("Ошибка при подготовке Instagram-аудита")
        await status_message.edit_text(
            "Не получилось подготовить аудит. Попробуйте ещё раз чуть позже, "
            "или проверьте логи бота (journalctl -u telegram-bot)."
        )
        return

    await status_message.delete()
    await message.answer_document(
        FSInputFile(pdf_path), caption="Ваш Instagram-аудит готов 📊"
    )


@router.message(F.text)
async def handle_text(message: Message) -> None:
    await message.bot.send_chat_action(message.chat.id, "typing")
    try:
        reply = await ask_claude(message.chat.id, message.text)
    except Exception:
        logger.exception("Ошибка при обращении к Claude API")
        await message.answer(
            "Извините, произошла ошибка при обращении к AI. Попробуйте ещё раз чуть позже."
        )
        return

    # Telegram не принимает сообщения длиннее 4096 символов — режем на части.
    for i in range(0, len(reply), TELEGRAM_LIMIT):
        await message.answer(reply[i : i + TELEGRAM_LIMIT])
