"""Учёт расходов на модель, лимиты и сжатие фотографий."""

import asyncio
import contextlib
import inspect
import io
from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import config
from models import ApiUsage, Base, User
from services import usage
from utils import images
from utils.disk import DiskUsage, render_warning


@contextlib.asynccontextmanager
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with maker() as session:
        session.add(User(id=1, full_name="Лилия", onboarding_completed=True))
        await session.commit()
        yield session
    await engine.dispose()


def run(scenario):
    asyncio.run(scenario())


class FakeUsage:
    def __init__(self, **fields):
        for name, value in fields.items():
            setattr(self, name, value)


# --- цены -----------------------------------------------------------------

def test_photo_on_sonnet_is_cheaper_than_on_opus():
    """Ради этого и переходили: то же фото втрое дешевле."""
    sonnet = usage.cost_usd("claude-sonnet-5", input_tokens=1500, output_tokens=300)
    opus = usage.cost_usd("claude-opus-5", input_tokens=1500, output_tokens=300)
    assert sonnet < opus
    assert opus / sonnet == pytest.approx(2.5, abs=0.01)


def test_cache_reads_are_ten_times_cheaper_than_fresh_input():
    fresh = usage.cost_usd("claude-sonnet-5", input_tokens=1000)
    cached = usage.cost_usd("claude-sonnet-5", cache_read_tokens=1000)
    assert cached == pytest.approx(fresh / 10)


def test_an_unknown_model_is_priced_as_the_most_expensive():
    """Ошибиться в большую сторону безопаснее: потолок сработает раньше."""
    unknown = usage.cost_usd("claude-что-то-новое", input_tokens=1000)
    assert unknown == usage.cost_usd("claude-opus-5", input_tokens=1000)


# --- учёт -----------------------------------------------------------------

def test_a_request_is_recorded_with_its_cost():
    async def scenario():
        async with db() as session:
            spent = await usage.record(
                session, user_id=1, kind="photo", model="claude-sonnet-5",
                usage=FakeUsage(input_tokens=1500, output_tokens=300,
                                cache_creation_input_tokens=0, cache_read_input_tokens=0))
            assert spent > 0
            row = (await session.execute(select(ApiUsage))).scalar_one()
            assert row.kind == "photo" and row.input_tokens == 1500
            assert row.cost_usd == pytest.approx(spent)
    run(scenario)


def test_a_response_without_usage_does_not_break_anything():
    """Учёт — вспомогательная вещь: без него человек всё равно ест."""
    async def scenario():
        async with db() as session:
            assert await usage.record(session, user_id=1, kind="photo",
                                      model="claude-sonnet-5", usage=None) == 0.0
            assert (await usage.spent_today(session)).calls == 0
    run(scenario)


def test_daily_spend_is_split_by_kind():
    async def scenario():
        async with db() as session:
            for kind, tokens in (("photo", 1500), ("photo", 1500), ("build", 3000)):
                await usage.record(session, user_id=1, kind=kind, model="claude-sonnet-5",
                                   usage=FakeUsage(input_tokens=tokens, output_tokens=200))
            spend = await usage.spent_today(session)
            assert spend.calls == 3
            assert set(spend.by_kind) == {"photo", "build"}
            assert spend.total_usd == pytest.approx(sum(spend.by_kind.values()))
    run(scenario)


# --- потолки --------------------------------------------------------------

def test_the_daily_cap_stops_recognition():
    async def scenario():
        async with db() as session:
            assert not await usage.over_budget(session)
            # Один дорогой запрос, выбирающий весь дневной потолок.
            await usage.record(session, user_id=1, kind="photo", model="claude-opus-5",
                               usage=FakeUsage(input_tokens=5_000_000, output_tokens=0))
            assert await usage.over_budget(session)
    run(scenario)


def test_a_zero_cap_means_no_cap():
    """Владелец может снять ограничение, поставив ноль."""
    async def scenario():
        async with db() as session:
            await usage.record(session, user_id=1, kind="photo", model="claude-opus-5",
                               usage=FakeUsage(input_tokens=9_000_000))
            original = config.DAILY_COST_LIMIT_USD
            config.DAILY_COST_LIMIT_USD = 0
            try:
                assert not await usage.over_budget(session)
            finally:
                config.DAILY_COST_LIMIT_USD = original
    run(scenario)


def test_one_person_cannot_eat_the_whole_budget():
    async def scenario():
        async with db() as session:
            left = await usage.photo_limit_left(session, 1)
            assert left == config.PHOTO_LIMIT_PER_DAY

            for _ in range(config.PHOTO_LIMIT_PER_DAY):
                await usage.record(session, user_id=1, kind="photo",
                                   model="claude-sonnet-5",
                                   usage=FakeUsage(input_tokens=1500, output_tokens=200))
            assert await usage.photo_limit_left(session, 1) == 0
            # Лимит персональный: соседа он не касается.
            assert await usage.photo_limit_left(session, 2) == config.PHOTO_LIMIT_PER_DAY
    run(scenario)


def test_the_limit_counts_only_photos_and_only_today():
    async def scenario():
        async with db() as session:
            await usage.record(session, user_id=1, kind="build", model="claude-opus-5",
                               usage=FakeUsage(input_tokens=1000))
            assert await usage.photo_limit_left(session, 1) == config.PHOTO_LIMIT_PER_DAY

            session.add(ApiUsage(user_id=1, kind="photo", model="claude-sonnet-5",
                                 input_tokens=1500, cost_usd=0.01,
                                 day=date.today() - timedelta(days=1)))
            await session.commit()
            assert await usage.photo_limit_left(session, 1) == config.PHOTO_LIMIT_PER_DAY
    run(scenario)


def test_old_records_are_cleaned_up():
    async def scenario():
        async with db() as session:
            session.add(ApiUsage(user_id=1, kind="photo", model="claude-sonnet-5",
                                 cost_usd=0.01, day=date.today() - timedelta(days=200)))
            await session.commit()
            assert await usage.cleanup(session) == 1
            assert (await session.execute(select(ApiUsage))).first() is None
    run(scenario)


def test_the_report_reads_like_a_sentence():
    spend = usage.Spend(total_usd=6.4, calls=312, by_kind={"photo": 6.0, "build": 0.4})
    text = usage.render_report(spend)
    assert "6.40 $" in text and "312" in text and "фото" in text

    assert "ничего" in usage.render_report(usage.Spend(0.0, 0, {}))


# --- фотографии -----------------------------------------------------------

def photo_bytes(width: int, height: int) -> bytes:
    from PIL import Image

    image = Image.new("RGB", (width, height), (120, 90, 60))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()


def test_a_phone_photo_is_shrunk_for_the_model():
    """Токены картинки — это ширина на высоту делить на 750."""
    from PIL import Image

    big = photo_bytes(3000, 2000)
    small = images.for_food(big)
    assert len(small) < len(big)
    assert max(Image.open(io.BytesIO(small)).size) == images.FOOD_MAX_SIDE


def test_a_progress_photo_keeps_more_detail_than_a_food_photo():
    from PIL import Image

    shrunk = images.for_progress(photo_bytes(3000, 2000))
    assert max(Image.open(io.BytesIO(shrunk)).size) == images.PROGRESS_MAX_SIDE
    assert images.PROGRESS_MAX_SIDE > images.FOOD_MAX_SIDE


def test_a_small_photo_is_left_alone():
    """Пережимать и без того маленький снимок незачем — станет только хуже."""
    small = photo_bytes(400, 300)
    assert len(images.for_food(small)) <= len(small)


def test_a_broken_file_does_not_break_the_record():
    """Битое фото — не повод потерять запись о еде."""
    junk = "\x00\x01\x02 это не картинка".encode("utf-8")
    assert images.for_food(junk) == junk
    assert images.for_food(b"") == b""


# --- диск -----------------------------------------------------------------

def test_disk_warnings_come_before_the_stop():
    calm = DiskUsage(total_gb=30, used_gb=10, free_gb=20, percent=33)
    warn = DiskUsage(total_gb=30, used_gb=25, free_gb=5, percent=83)
    full = DiskUsage(total_gb=30, used_gb=28, free_gb=2, percent=93)

    assert not calm.warning and not calm.full
    assert warn.warning and not warn.full
    assert full.warning and full.full

    assert "перестал принимать" in render_warning(full)
    assert "пора расширять" in render_warning(warn)


# --- что видит человек ----------------------------------------------------

class FakeMessage:
    """Сообщение в чате: нам важно только, что бот ответил."""

    def __init__(self):
        self.said: list[str] = []

    async def answer(self, text, **kwargs):
        self.said.append(text)
        return self


def test_the_bot_explains_the_daily_cap_instead_of_failing():
    """Дойдя до потолка, бот не молчит и не ломается — он предлагает выход."""
    async def scenario():
        import handlers.food as food
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        @contextlib.asynccontextmanager
        async def get_session():
            async with maker() as session:
                yield session

        original, food.get_session = food.get_session, get_session
        try:
            message = FakeMessage()
            assert await food._photo_allowed(message, 1) is True
            assert not message.said

            async with maker() as session:
                await usage.record(session, user_id=1, kind="photo",
                                   model="claude-opus-5",
                                   usage=FakeUsage(input_tokens=5_000_000))

            message = FakeMessage()
            assert await food._photo_allowed(message, 1) is False
            assert "дневной лимит" in message.said[0]
            # Отказ обязан предложить, что делать дальше.
            assert "словами" in message.said[0]
        finally:
            food.get_session = original
            await engine.dispose()
    run(scenario)


def test_a_person_who_hit_their_own_limit_is_told_the_number():
    async def scenario():
        import handlers.food as food
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        @contextlib.asynccontextmanager
        async def get_session():
            async with maker() as session:
                yield session

        original, food.get_session = food.get_session, get_session
        try:
            async with maker() as session:
                for _ in range(config.PHOTO_LIMIT_PER_DAY):
                    await usage.record(session, user_id=1, kind="photo",
                                       model="claude-sonnet-5",
                                       usage=FakeUsage(input_tokens=1500))
            message = FakeMessage()
            assert await food._photo_allowed(message, 1) is False
            assert str(config.PHOTO_LIMIT_PER_DAY) in message.said[0]
        finally:
            food.get_session = original
            await engine.dispose()
    run(scenario)


def test_the_same_photo_is_not_paid_for_twice():
    """Пересланное второй раз фото должно браться из памяти."""
    import handlers.food as food
    from services.food_vision import FoodAnalysis

    food._recent_photos.clear()
    analysis = FoodAnalysis(name="Овсянка", weight_g=250, calories=320, protein_g=9,
                            fat_g=7, carbs_g=55, fiber_g=6, confidence="high", comment="")
    food._remember_photo("uniq-1", analysis)
    assert food._recent_photos.get("uniq-1") is analysis
    assert food._recent_photos.get("uniq-2") is None


def test_photo_memory_does_not_grow_without_limit():
    import handlers.food as food
    from services.food_vision import FoodAnalysis

    food._recent_photos.clear()
    analysis = FoodAnalysis(name="Х", weight_g=1, calories=1, protein_g=0, fat_g=0,
                            carbs_g=0, fiber_g=0, confidence="low", comment="")
    for index in range(food._RECENT_LIMIT + 50):
        food._remember_photo(f"key-{index}", analysis)
    assert len(food._recent_photos) == food._RECENT_LIMIT
    # Вытесняются самые старые.
    assert food._recent_photos.get("key-0") is None
    assert food._recent_photos.get(f"key-{food._RECENT_LIMIT + 49}") is analysis


# --- фото еды не хранится -------------------------------------------------

def test_a_food_photo_leaves_no_trace_in_the_database():
    """Снимок еды нужен на время распознавания и не должен переживать его.

    Раньше в записи оставалась ссылка на файл в Телеграме: её никто не читал,
    но по ней можно было скачать чужой обед спустя год.
    """
    from models import Meal

    assert not hasattr(Meal, "photo_file_id"), "ссылки на фото в записи быть не должно"

    import inspect

    from services.meals import save_meal

    assert "photo_file_id" not in inspect.signature(save_meal).parameters


def test_only_progress_photos_are_written_to_disk():
    """На диск попадает только то, что человек загрузил осознанно."""
    import services.progress as progress

    source = inspect.getsource(progress.save_photo)
    assert "write_bytes" in source

    import services.food_vision as vision

    text = inspect.getsource(vision)
    for forbidden in ("write_bytes", "open(", "photos_dir"):
        assert forbidden not in text, f"распознавание не должно трогать диск: {forbidden}"
