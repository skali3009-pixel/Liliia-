"""Ответ на то, что бот не понял.

До этого он просто молчал. Молчание — худший из возможных ответов: человек
не знает, дошло ли сообщение, сломался ли бот или он сам сделал что-то не
так. Тестировщицы из этого сделали вывод, что перед каждым фото надо
нажимать «Добавить еду», — и нажимали, хотя это никогда не требовалось.

Роутер подключается последним: сюда попадает только то, что не разобрал
никто до него.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from keyboards.main_menu import main_menu_keyboard

logger = logging.getLogger(__name__)
router = Router(name="fallback")

HELP = (
    "Не понял, что с этим делать.\n\n"
    "Еду можно прислать тремя способами, и ни для одного не надо ничего "
    "нажимать заранее:\n"
    "📷 фото блюда\n"
    "🎤 голосовым: «съела тарелку борща»\n"
    "⌨️ текстом — так же словами\n\n"
    "Остальное — кнопками внизу."
)


@router.message(F.document | F.video | F.animation | F.sticker)
async def not_a_photo(message: Message, state: FSMContext) -> None:
    """Файл вместо фото — частая история: айфон отправляет как документ."""
    await state.clear()
    await message.answer(
        "Это пришло файлом, а не фото — так я его не разберу.\n\n"
        "Отправь снимок обычным способом, через 📷, или просто опиши блюдо "
        "словами: «тарелка борща и два куска хлеба».",
        reply_markup=main_menu_keyboard(),
    )


@router.message()
async def did_not_understand(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(HELP, reply_markup=main_menu_keyboard())


__all__ = ["HELP", "router"]
