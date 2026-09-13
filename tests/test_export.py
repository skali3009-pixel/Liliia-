"""Выгрузка данных: что внутри архива и можно ли этим пользоваться."""

import asyncio
import contextlib
import csv
import io
import zipfile
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import config
from models import (Base, BodyMeasurement, Checkin, DietTypeEnum, GenderEnum, GoalEnum, Meal,
                    MealSourceEnum, MealTypeEnum, ProgressPhoto, ScheduleTypeEnum, Supplement,
                    SupplementLog, User, WaterLog, Workout, WorkoutLog, WorkoutTypeEnum,
                    LocationEnum, LevelEnum)
from services.export import MAX_PHOTO_BYTES, build_export
from utils.plural import with_count

USER_ID = 11
OTHER_ID = 22
NOW = datetime(2026, 3, 10, 9, 30, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def photos_in_tmp(tmp_path, monkeypatch):
    """Фото пишем в папку теста и возвращаем настройку на место после него."""
    monkeypatch.setattr(config, "PHOTOS_DIR", str(tmp_path))


async def make_session(tmp_path):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, maker


async def fill(session) -> User:
    user = User(id=USER_ID, full_name="Лилия Иванова", gender=GenderEnum.FEMALE, age=34,
                height_cm=165, current_weight_kg=70.5, target_weight_kg=62,
                goal=GoalEnum.LOSE_WEIGHT, diet_type=DietTypeEnum.REGULAR,
                timezone="Europe/Moscow", daily_calories=1600, daily_protein_g=120,
                daily_fat_g=48, daily_carbs_g=160, daily_fiber_g=22, daily_water_ml=2100,
                onboarding_completed=True)
    other = User(id=OTHER_ID, full_name="Кто-то ещё", timezone="Europe/Moscow",
                 onboarding_completed=True)
    session.add_all([user, other])

    session.add(Meal(user_id=USER_ID, meal_type=MealTypeEnum.BREAKFAST,
                     name='Овсянка; с "ягодами"', weight_g=250, calories=320, protein_g=9,
                     fat_g=7, carbs_g=55, fiber_g=6, source=MealSourceEnum.PHOTO,
                     logged_at=NOW))
    session.add(Meal(user_id=OTHER_ID, name="Чужой обед", calories=700,
                     source=MealSourceEnum.TEXT, logged_at=NOW))
    session.add(WaterLog(user_id=USER_ID, amount_ml=250, logged_at=NOW))
    session.add(BodyMeasurement(user_id=USER_ID, weight_kg=70.5, waist_cm=78.0,
                                measured_at=NOW))
    session.add(Checkin(user_id=USER_ID, energy=7, mood="бодро", sleep_minutes=430,
                        note="день\nв две строки", logged_at=NOW))

    workout = Workout(id=1, name="Приседания", workout_type=WorkoutTypeEnum.STRENGTH,
                      location=LocationEnum.HOME, level=LevelEnum.BEGINNER, met_value=5.0)
    session.add(workout)
    session.add(WorkoutLog(user_id=USER_ID, workout_id=1, sets_done=3, reps_done=12,
                           duration_minutes=8, calories_burned=45, completed_at=NOW))

    supplement = Supplement(id=1, user_id=USER_ID, name="D3", dose="5000 МЕ",
                            schedule_type=ScheduleTypeEnum.DAILY, created_at=NOW)
    session.add(supplement)
    session.add(SupplementLog(user_id=USER_ID, supplement_id=1, skipped=False, logged_at=NOW))
    await session.commit()
    return user


def sheet(archive: zipfile.ZipFile, name: str) -> list[list[str]]:
    text = archive.read(f"{name}.csv").decode("utf-8")
    assert text.startswith("﻿"), "без BOM Excel покажет кракозябры"
    return list(csv.reader(io.StringIO(text.lstrip("﻿")), delimiter=";"))


def build(tmp_path, extra=None):
    """Собрать архив на временной базе; вернуть Export и открытый zip."""
    async def scenario():
        engine, maker = await make_session(tmp_path)
        async with maker() as session:
            user = await fill(session)
            if extra:
                await extra(session, user, tmp_path)
            export = await build_export(session, user, today=date(2026, 3, 10))
        await engine.dispose()
        return export
    export = asyncio.run(scenario())
    return export, zipfile.ZipFile(io.BytesIO(export.content))


def test_archive_holds_every_kind_of_record(tmp_path):
    export, archive = build(tmp_path)
    assert export.filename == "AURA-2026-03-10.zip"
    for name in ("Профиль", "Еда", "Вода", "Вес и замеры", "Тренировки", "Шаги",
                 "Самочувствие", "Добавки", "Приём добавок"):
        assert f"{name}.csv" in archive.namelist(), name
    assert "Что внутри.txt" in archive.namelist()


def test_meals_are_written_in_human_words_and_local_time(tmp_path):
    _, archive = build(tmp_path)
    header, row = sheet(archive, "Еда")
    assert header[:4] == ["Дата", "Время", "Приём пищи", "Блюдо"]
    # 09:30 UTC — это 12:30 в Москве: в таблице время человека, а не сервера.
    assert row[:5] == ["2026-03-10", "12:30", "завтрак", 'Овсянка; с "ягодами"', "250"]
    assert row[-1] == "фото"


def test_separators_inside_a_dish_name_do_not_break_the_table(tmp_path):
    """Точка с запятой в названии не должна разъезжаться по столбцам."""
    _, archive = build(tmp_path)
    rows = sheet(archive, "Еда")
    assert len(rows) == 2 and len(rows[1]) == len(rows[0])


def test_a_note_with_a_line_break_stays_one_record(tmp_path):
    export, archive = build(tmp_path)
    assert export.rows["Самочувствие"] == 1
    rows = sheet(archive, "Самочувствие")
    assert rows[1][-1] == "день\nв две строки"


def test_profile_is_readable_without_a_dictionary(tmp_path):
    _, archive = build(tmp_path)
    values = dict(row for row in sheet(archive, "Профиль")[1:])
    # Дробное через запятую: с точкой русский Excel считает столбец текстом.
    assert values["Вес сейчас, кг"] == "70,5"
    assert values["Рост, см"] == "165"
    assert values["Цель"] == "похудение"
    assert values["Пол"] == "женский"
    assert values["Норма, ккал"] == "1600"
    assert values["Напоминания"] == "включены"


def test_the_export_holds_only_your_own_records(tmp_path):
    _, archive = build(tmp_path)
    assert "Чужой обед" not in archive.read("Еда.csv").decode("utf-8")


def test_photos_come_along_and_are_counted(tmp_path):
    async def add_photos(session, user, tmp):
        directory = tmp / str(user.id)
        directory.mkdir(parents=True, exist_ok=True)
        for index in range(2):
            (directory / f"p{index}.jpg").write_bytes(b"\xff\xd8" + bytes(100))
            session.add(ProgressPhoto(user_id=user.id, file_name=f"p{index}.jpg",
                                      taken_at=NOW))
        await session.commit()

    export, archive = build(tmp_path, extra=add_photos)
    assert export.photos_included == 2
    assert sorted(n for n in archive.namelist() if n.startswith("Фото/")) == [
        "Фото/2026-03-10-1.jpg", "Фото/2026-03-10-2.jpg"]
    assert "2 фото" in archive.read("Что внутри.txt").decode("utf-8")


def test_a_photo_lost_on_disk_does_not_break_the_export(tmp_path):
    async def broken_photo(session, user, tmp):
        session.add(ProgressPhoto(user_id=user.id, file_name="нет-такого.jpg", taken_at=NOW))
        await session.commit()

    export, archive = build(tmp_path, extra=broken_photo)
    assert export.photos_included == 0
    assert export.photos_skipped == 1
    assert "Еда.csv" in archive.namelist()


def test_photos_stop_at_the_size_limit_and_the_rest_are_reported(tmp_path):
    """В Telegram помещается один файл: лишние фото нельзя терять молча."""
    async def heavy_photos(session, user, tmp):
        directory = tmp / str(user.id)
        directory.mkdir(parents=True, exist_ok=True)
        chunk = MAX_PHOTO_BYTES // 2 + 1
        for index in range(3):
            (directory / f"h{index}.jpg").write_bytes(bytes(chunk))
            session.add(ProgressPhoto(user_id=user.id, file_name=f"h{index}.jpg", taken_at=NOW))
        await session.commit()

    export, _ = build(tmp_path, extra=heavy_photos)
    assert export.photos_included == 1
    assert export.photos_skipped == 2
    assert "не поместились" in export.caption()


def test_caption_counts_records_in_russian(tmp_path):
    export, _ = build(tmp_path)
    assert "1 запись о еде" in export.caption()
    assert "1 взвешивание" in export.caption()
    assert "1 тренировка" in export.caption()


def test_an_empty_diary_still_produces_a_valid_archive(tmp_path):
    async def scenario():
        engine, maker = await make_session(tmp_path)
        async with maker() as session:
            user = User(id=99, full_name="Новичок", timezone="Europe/Moscow",
                        onboarding_completed=True)
            session.add(user)
            await session.commit()
            export = await build_export(session, user, today=date(2026, 3, 10))
        await engine.dispose()
        return export

    export = asyncio.run(scenario())
    archive = zipfile.ZipFile(io.BytesIO(export.content))
    assert sheet(archive, "Еда") == [["Дата", "Время", "Приём пищи", "Блюдо", "Вес, г", "Ккал",
                                     "Белки, г", "Жиры, г", "Углеводы, г", "Клетчатка, г",
                                     "Как записано"]]
    assert "0 записей о еде" in export.caption()
    assert "Фото прогресса в этой выгрузке нет" in archive.read("Что внутри.txt").decode("utf-8")


def test_russian_word_forms():
    assert with_count(1, "запись", "записи", "записей") == "1 запись"
    assert with_count(2, "запись", "записи", "записей") == "2 записи"
    assert with_count(5, "запись", "записи", "записей") == "5 записей"
    # 11–14 — исключение: «11 записей», а не «11 запись».
    assert with_count(11, "запись", "записи", "записей") == "11 записей"
    assert with_count(21, "запись", "записи", "записей") == "21 запись"
    assert with_count(0, "запись", "записи", "записей") == "0 записей"


def test_the_bot_sends_the_archive_and_removes_the_waiting_note(tmp_path):
    """Путь из чата целиком: собрали, отправили файлом, убрали «собираю…»."""
    class Note:
        def __init__(self):
            self.deleted = False

        async def delete(self):
            self.deleted = True

    class FakeMessage:
        def __init__(self):
            self.notes, self.documents = [], []

        async def answer(self, text, **kwargs):
            self.notes.append(text)
            return Note()

        async def answer_document(self, document, caption=None, **kwargs):
            self.documents.append((document, caption))

    async def scenario():
        import handlers.profile as handler

        engine, maker = await make_session(tmp_path)
        async with maker() as session:
            await fill(session)

        @contextlib.asynccontextmanager
        async def get_session():
            async with maker() as session:
                yield session

        original, handler.get_session = handler.get_session, get_session
        message = FakeMessage()
        try:
            await handler.send_export(message, USER_ID)
        finally:
            handler.get_session = original
            await engine.dispose()
        return message

    message = asyncio.run(scenario())
    assert message.notes == ["Собираю файл со всеми твоими записями…"]
    document, caption = message.documents[0]
    assert document.filename.startswith("AURA-") and document.filename.endswith(".zip")
    assert "запись о еде" in caption


def test_a_stranger_without_a_profile_gets_an_answer_not_a_crash(tmp_path):
    class FakeMessage:
        def __init__(self):
            self.said = []

        async def answer(self, text, **kwargs):
            self.said.append(text)
            return None

        async def answer_document(self, *args, **kwargs):
            raise AssertionError("нечего выгружать, а файл всё же ушёл")

    async def scenario():
        import handlers.profile as handler

        engine, maker = await make_session(tmp_path)

        @contextlib.asynccontextmanager
        async def get_session():
            async with maker() as session:
                yield session

        original, handler.get_session = handler.get_session, get_session
        message = FakeMessage()
        try:
            await handler.send_export(message, 12345)
        finally:
            handler.get_session = original
            await engine.dispose()
        return message

    message = asyncio.run(scenario())
    assert message.said == ["Профиль ещё не настроен. Напиши /start."]


def test_the_export_carries_the_steps_too(tmp_path):
    """Шаги появились позже выгрузки — и в неё не попадали."""
    async def add_steps(session, user, _tmp):
        from services import steps as step_service

        await step_service.record(session, user.id, 9200, day=date(2026, 3, 9))

    _, archive = build(tmp_path, extra=add_steps)
    assert "Шаги.csv" in archive.namelist()
    # И в описании архива: файл без объяснения человек просто не откроет.
    assert "Шаги.csv" in archive.read("Что внутри.txt").decode("utf-8")

    header, row = sheet(archive, "Шаги")
    assert header == ["Дата", "Шаги"]
    assert row == ["09.03.2026", "9200"]


def test_the_export_says_what_the_step_goal_is(tmp_path):
    async def set_goal(session, user, _tmp):
        user.daily_steps = 9000
        await session.commit()

    _, archive = build(tmp_path, extra=set_goal)
    rows = sheet(archive, "Профиль")
    assert ["Шаги, цель", "9000"] in rows
