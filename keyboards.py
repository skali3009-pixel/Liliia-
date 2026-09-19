"""Инлайн-клавиатуры завода. Вся навигация кнопками — она работает с телефона."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

PLATFORMS = [("tiktok", "TikTok"), ("instagram", "Instagram")]


def _kb(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def main_menu() -> InlineKeyboardMarkup:
    return _kb([
        [InlineKeyboardButton(text="📝 Новый пост", callback_data="zv:new")],
        [InlineKeyboardButton(text="📅 Очередь", callback_data="zv:queue")],
        [InlineKeyboardButton(text="🎵 Песни и припевы", callback_data="zv:songs")],
    ])


def song_list(songs: list[dict], action: str) -> InlineKeyboardMarkup:
    """action: 'pick' — выбрать для поста, 'chorus' — вписать припев."""
    rows = []
    for song in songs:
        mark = "🇹" if song["lang"] == "tat" else ""
        chorus = "" if song.get("chorus") else " ·  без припева"
        rows.append([InlineKeyboardButton(
            text=f"{mark} {song['title']}{chorus}".strip(),
            callback_data=f"zv:{action}:{song['id']}",
        )])
    rows.append([InlineKeyboardButton(text="‹ Назад", callback_data="zv:menu")])
    return _kb(rows)


def platform_choice(song_id: str) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=name, callback_data=f"zv:gen:{song_id}:{key}")]
            for key, name in PLATFORMS]
    rows.append([InlineKeyboardButton(text="‹ Назад", callback_data="zv:new")])
    return _kb(rows)


def variant_actions(draft_id: str, index: int) -> InlineKeyboardMarkup:
    return _kb([
        [InlineKeyboardButton(text="✅ Беру", callback_data=f"zv:take:{draft_id}:{index}"),
         InlineKeyboardButton(text="📋 Текст", callback_data=f"zv:copy:{draft_id}:{index}")],
        [InlineKeyboardButton(text="🔄 Ещё три", callback_data=f"zv:more:{draft_id}"),
         InlineKeyboardButton(text="✏️ Переписать", callback_data=f"zv:note:{draft_id}")],
        [InlineKeyboardButton(text="‹ В меню", callback_data="zv:menu")],
    ])


def queue_item(item_id: str) -> InlineKeyboardMarkup:
    return _kb([
        [InlineKeyboardButton(text="📋 Текст", callback_data=f"zv:qtext:{item_id}"),
         InlineKeyboardButton(text="✔️ Выложила", callback_data=f"zv:done:{item_id}")],
        [InlineKeyboardButton(text="🗑 Убрать", callback_data=f"zv:drop:{item_id}")],
    ])


def back_to_menu() -> InlineKeyboardMarkup:
    return _kb([[InlineKeyboardButton(text="‹ В меню", callback_data="zv:menu")]])
