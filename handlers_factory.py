"""Контент-завод: команда /zavod и вся навигация кнопками.

Поток такой же, как её порядок согласования: она выбирает песню, выбирает
площадку, получает три варианта, одобряет или просит переписать. Ничего
не уходит в публикацию само — очередь это список готового, который она
выкладывает сама.
"""

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

import factory
import keyboards as kb
import playbook
import storage

logger = logging.getLogger(__name__)

router = Router(name="factory")

TELEGRAM_LIMIT = 4096

# Чего бот ждёт текстом от конкретного чата: ("chorus", song_id) или
# ("note", draft_id). Переживать перезапуск не обязано — она просто повторит.
_pending: dict[int, tuple[str, str]] = {}

MENU_TEXT = (
    "🏭 <b>Контент-завод</b>\n\n"
    "Выбираешь песню и площадку — я пишу три варианта поста по своду правил: "
    "крючок, история, пересылаемая строка, просьба.\n\n"
    "Что берёшь — уходит в очередь."
)


async def _safe_send(message: Message, text: str, **kwargs) -> None:
    """Telegram режет всё длиннее 4096 символов."""
    for i in range(0, len(text), TELEGRAM_LIMIT):
        chunk = text[i : i + TELEGRAM_LIMIT]
        # Кнопки вешаем только на последний кусок.
        last = i + TELEGRAM_LIMIT >= len(text)
        await message.answer(chunk, **(kwargs if last else {}))


@router.message(Command("zavod"))
async def cmd_zavod(message: Message) -> None:
    _pending.pop(message.chat.id, None)
    await message.answer(MENU_TEXT, reply_markup=kb.main_menu(), parse_mode="HTML")


@router.callback_query(F.data == "zv:menu")
async def cb_menu(call: CallbackQuery) -> None:
    _pending.pop(call.message.chat.id, None)
    await call.message.answer(MENU_TEXT, reply_markup=kb.main_menu(), parse_mode="HTML")
    await call.answer()


# --- Новый пост ------------------------------------------------------------

@router.callback_query(F.data == "zv:new")
async def cb_new(call: CallbackQuery) -> None:
    await call.message.answer(
        "Какая песня?", reply_markup=kb.song_list(storage.list_songs(), "pick")
    )
    await call.answer()


@router.callback_query(F.data.startswith("zv:pick:"))
async def cb_pick(call: CallbackQuery) -> None:
    song_id = call.data.split(":")[2]
    song = storage.get_song(song_id)
    if not song:
        await call.answer("Песня не найдена", show_alert=True)
        return
    note = "" if song.get("chorus") else (
        "\n\nПрипева у неё нет — напишу по теме названия. "
        "Припев можно вписать в разделе «Песни»."
    )
    await call.message.answer(
        f"«{song['title']}». Куда пишем?{note}",
        reply_markup=kb.platform_choice(song_id),
    )
    await call.answer()


async def _generate(call_or_msg, chat_id: int, song: dict, platform: str, note: str = ""):
    status = await call_or_msg.answer("Пишу три варианта, секунд двадцать…")
    try:
        variants = await factory.make_variants(song, platform, note)
    except factory.FactoryError as e:
        await status.edit_text(f"Не получилось: {e}\n\nПопробуй ещё раз.")
        return
    except Exception:
        logger.exception("Сбой генерации поста")
        await status.edit_text(
            "Сбой при генерации. Попробуй ещё раз, а если повторится — "
            "загляни в логи: journalctl -u telegram-bot -n 50"
        )
        return

    draft_id = storage.save_draft(chat_id, {
        "song_id": song["id"], "song_title": song["title"],
        "platform": platform, "variants": variants, "note": note,
    })
    await status.delete()

    for i, variant in enumerate(variants):
        await _safe_send(
            status, factory.format_variant(variant, i + 1, len(variants)),
            reply_markup=kb.variant_actions(draft_id, i),
        )

    await status.answer(
        f"Лучшее время для {platform}: {playbook.BEST_TIME.get(platform, '—')}.\n"
        f"Смотрим на {playbook.TARGET_METRIC.get(platform, 'пересылки')}, "
        f"не на лайки."
    )


@router.callback_query(F.data.startswith("zv:gen:"))
async def cb_gen(call: CallbackQuery) -> None:
    _, _, song_id, platform = call.data.split(":")
    song = storage.get_song(song_id)
    if not song:
        await call.answer("Песня не найдена", show_alert=True)
        return
    await call.answer()
    await _generate(call.message, call.message.chat.id, song, platform)


@router.callback_query(F.data.startswith("zv:more:"))
async def cb_more(call: CallbackQuery) -> None:
    draft = storage.get_draft(call.data.split(":")[2])
    if not draft:
        await call.answer("Черновик потерялся, начни заново", show_alert=True)
        return
    song = storage.get_song(draft["song_id"])
    await call.answer()
    await _generate(call.message, call.message.chat.id, song, draft["platform"],
                    draft.get("note", ""))


@router.callback_query(F.data.startswith("zv:note:"))
async def cb_note(call: CallbackQuery) -> None:
    draft_id = call.data.split(":")[2]
    _pending[call.message.chat.id] = ("note", draft_id)
    await call.message.answer(
        "Напиши, что поменять. Своими словами — «жёстче», «убери про маму», "
        "«зайди с вопроса». Учту и перепишу заново."
    )
    await call.answer()


# --- Одобрение и очередь ---------------------------------------------------

def _variant_of(draft_id: str, index: int):
    draft = storage.get_draft(draft_id)
    if not draft:
        return None, None
    variants = draft["variants"]
    if index >= len(variants):
        return draft, None
    return draft, variants[index]


@router.callback_query(F.data.startswith("zv:copy:"))
async def cb_copy(call: CallbackQuery) -> None:
    _, _, draft_id, idx = call.data.split(":")
    _, variant = _variant_of(draft_id, int(idx))
    if not variant:
        await call.answer("Черновик потерялся", show_alert=True)
        return
    await _safe_send(call.message, factory.copy_text(variant))
    await call.answer("Текст отдельным сообщением — копируй целиком")


@router.callback_query(F.data.startswith("zv:take:"))
async def cb_take(call: CallbackQuery) -> None:
    _, _, draft_id, idx = call.data.split(":")
    draft, variant = _variant_of(draft_id, int(idx))
    if not variant:
        await call.answer("Черновик потерялся", show_alert=True)
        return
    item = storage.add_to_queue({
        "song_title": draft["song_title"],
        "platform": draft["platform"],
        "text": factory.copy_text(variant),
        "forward_line": variant["forward_line"],
        "best_time": playbook.BEST_TIME.get(draft["platform"], "—"),
    })
    await call.message.answer(
        f"В очередь. «{draft['song_title']}» → {draft['platform']}, "
        f"выкладывать {item['best_time']}.",
        reply_markup=kb.main_menu(),
    )
    await call.answer("Взято")


@router.callback_query(F.data == "zv:queue")
async def cb_queue(call: CallbackQuery) -> None:
    items = storage.list_queue("ждёт")
    if not items:
        await call.message.answer("Очередь пустая.", reply_markup=kb.main_menu())
        await call.answer()
        return
    await call.message.answer(f"В очереди {len(items)}:")
    for item in items:
        head = (f"«{item['song_title']}» → {item['platform']}\n"
                f"Время: {item['best_time']}\n\n")
        await _safe_send(call.message, head + item["text"],
                         reply_markup=kb.queue_item(item["id"]))
    await call.answer()


@router.callback_query(F.data.startswith("zv:qtext:"))
async def cb_qtext(call: CallbackQuery) -> None:
    item_id = call.data.split(":")[2]
    item = next((q for q in storage.list_queue() if q["id"] == item_id), None)
    if not item:
        await call.answer("Не нашёл", show_alert=True)
        return
    await _safe_send(call.message, item["text"])
    await call.answer("Копируй целиком")


@router.callback_query(F.data.startswith("zv:done:"))
async def cb_done(call: CallbackQuery) -> None:
    storage.set_queue_status(call.data.split(":")[2], "выложено")
    await call.answer("Отмечено")
    await call.message.answer("Отметил как выложенное.", reply_markup=kb.main_menu())


@router.callback_query(F.data.startswith("zv:drop:"))
async def cb_drop(call: CallbackQuery) -> None:
    storage.set_queue_status(call.data.split(":")[2], "убрано")
    await call.answer("Убрал")


# --- Песни и припевы -------------------------------------------------------

@router.callback_query(F.data == "zv:songs")
async def cb_songs(call: CallbackQuery) -> None:
    await call.message.answer(
        "Выбери песню, чтобы вписать припев.\n"
        "С припевом посты получаются заметно точнее: поворот ищется в "
        "противопоставлении его строк.",
        reply_markup=kb.song_list(storage.list_songs(), "chorus"),
    )
    await call.answer()


@router.callback_query(F.data.startswith("zv:chorus:"))
async def cb_chorus(call: CallbackQuery) -> None:
    song_id = call.data.split(":")[2]
    song = storage.get_song(song_id)
    if not song:
        await call.answer("Песня не найдена", show_alert=True)
        return
    _pending[call.message.chat.id] = ("chorus", song_id)
    current = f"\n\nСейчас записано:\n{song['chorus']}" if song.get("chorus") else ""
    await call.message.answer(
        f"Пришли припев «{song['title']}» одним сообщением.{current}"
    )
    await call.answer()


# --- Ввод текстом ----------------------------------------------------------

async def try_consume_pending(message: Message) -> bool:
    """Если бот ждёт от этого чата текст — забирает его и возвращает True.

    Вызывается из общего текстового обработчика ДО обращения к Claude,
    иначе припев уехал бы в обычный диалог.
    """
    pending = _pending.get(message.chat.id)
    if not pending or not message.text:
        return False
    kind, ref = pending
    _pending.pop(message.chat.id, None)

    if kind == "chorus":
        storage.set_chorus(ref, message.text)
        song = storage.get_song(ref)
        await message.answer(
            f"Припев «{song['title']}» записан. Теперь посты по ней будут точнее.",
            reply_markup=kb.main_menu(),
        )
        return True

    if kind == "note":
        draft = storage.get_draft(ref)
        if not draft:
            await message.answer("Черновик потерялся, начни заново.",
                                 reply_markup=kb.main_menu())
            return True
        song = storage.get_song(draft["song_id"])
        await _generate(message, message.chat.id, song, draft["platform"], message.text)
        return True

    return False
