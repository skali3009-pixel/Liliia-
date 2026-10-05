"""Old keyboards route to current handlers without mutating the original message."""
import asyncio
from datetime import datetime, timezone
from aiogram.types import Message, Chat, User
from keyboards.main_menu import LEGACY_MENU, MENU_ADD_MEAL
from middlewares.menu_aliases import MenuAliasesMiddleware


def test_old_keyboard_is_normalized_before_router(monkeypatch):
    calls = []
    async def answer(self, text, **kwargs): calls.append(kwargs["reply_markup"])
    monkeypatch.setattr(Message, "answer", answer)
    async def handler(event, data): return event.text, data
    for old, new in LEGACY_MENU.items():
        msg = Message(message_id=1, date=datetime.now(timezone.utc), chat=Chat(id=1,type="private"),
                      from_user=User(id=1,is_bot=False,first_name="Test"), text=old)
        assert asyncio.run(MenuAliasesMiddleware()(handler,msg,{"context":"kept"})) == (new,{"context":"kept"})
        assert msg.text == old
    assert len(calls) == len(LEGACY_MENU)
    assert any(b.text == MENU_ADD_MEAL for row in calls[0].keyboard for b in row)


def test_plain_food_text_is_untouched_and_does_not_send_menu(monkeypatch):
    async def answer(*args, **kwargs): raise AssertionError("Unexpected menu message")
    monkeypatch.setattr(Message, "answer", answer)
    msg = Message(message_id=1, date=datetime.now(timezone.utc), chat=Chat(id=1,type="private"),
                  from_user=User(id=1,is_bot=False,first_name="Test"), text="борщ 250 г")
    async def handler(event, data): return event
    assert asyncio.run(MenuAliasesMiddleware()(handler,msg,{})) is msg
