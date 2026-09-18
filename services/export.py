"""Выгрузка всех данных человека одним файлом.

Данные принадлежат человеку, а не приложению: он должен уметь забрать их
и уйти. Заодно это лечит главный страх дневника — «а если бот пропадёт,
я потеряю год записей».

Формат — zip с таблицами CSV, без новых зависимостей и без программ,
которые надо ставить: на iPad архив разворачивается «Файлами», а таблицы
открываются в Numbers или Excel. Разделитель — точка с запятой, в начале
BOM: иначе Excel в русской раскладке склеивает всё в один столбец и
показывает кириллицу кракозябрами.
"""

from __future__ import annotations

import csv
import io
import logging
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import (BodyMeasurement, Checkin, Meal, ProgressPhoto, StepLog, Supplement,
                    SupplementLog, User, WaterLog, Workout, WorkoutLog)
from services.profile import ACTIVITY_RU, DIET_RU, GENDER_RU, GOAL_RU
from services.progress import photos_dir
from utils.meal_time import MEAL_TYPE_RU
from utils.plural import plural, with_count
from utils.timeframe import to_local

logger = logging.getLogger(__name__)

# Телеграм не примет документ больше 50 МБ, и упереться в этот предел
# человек должен не молча. Фото складываем, пока не набрали лимит, а
# остальные честно пересчитываем в описании.
MAX_PHOTO_BYTES = 20 * 1024 * 1024

SOURCE_RU = {
    "photo": "фото",
    "text": "текст",
    "voice": "голос",
    "barcode": "штрихкод",
}
SCHEDULE_RU = {
    "daily": "каждый день",
    "weekdays": "по дням недели",
    "interval": "через день и реже",
}

README = """Выгрузка из AURA

Внутри — всё, что записано о тебе в приложении, обычными таблицами.
Каждый файл открывается в Numbers, Excel или Google Таблицах.

Профиль.csv — анкета и норма на день.
Еда.csv — каждый приём пищи: что, сколько, откуда взялась запись.
Вода.csv — каждая отметка о воде.
Вес и замеры.csv — взвешивания и объёмы.
Тренировки.csv — что выполнено и сколько на это ушло.
Шаги.csv — сколько шагов за каждый день.
Самочувствие.csv — энергия, фокус, настроение, стресс, сон.
Добавки.csv — список приёма и расписание.
Приём добавок.csv — когда приняла и когда пропустила.
{photos}

Время везде местное — то, которое было у тебя на часах в тот момент.
Пустая клетка означает, что этого не записывали.
Дробные числа записаны через запятую — так их ждут Numbers и Excel.

Файл собран {stamp}.
"""


@dataclass
class Export:
    """Готовый архив и то, что о нём стоит сказать человеку."""

    filename: str
    content: bytes
    rows: dict[str, int] = field(default_factory=dict)
    photos_included: int = 0
    photos_skipped: int = 0

    @property
    def size_mb(self) -> float:
        return round(len(self.content) / 1024 / 1024, 1)

    def caption(self) -> str:
        parts = [
            "📦 Твои данные — "
            + with_count(self.rows.get("Еда", 0), "запись", "записи", "записей")
            + " о еде, "
            + with_count(self.rows.get("Вес и замеры", 0),
                         "взвешивание", "взвешивания", "взвешиваний")
            + ", "
            + with_count(self.rows.get("Тренировки", 0),
                         "тренировка", "тренировки", "тренировок")
            + "."
        ]
        if self.photos_included:
            parts.append(f"Фото внутри: {self.photos_included}.")
        if self.photos_skipped:
            parts.append(
                f"Ещё {self.photos_skipped} "
                + plural(self.photos_skipped, "фото не поместилось", "фото не поместились",
                         "фото не поместились")
                + " в один файл — они остались в приложении."
            )
        parts.append("Таблицы открываются в Numbers и Excel.")
        return " ".join(parts)


def _ru(value, mapping: dict[str, str]) -> str:
    """Значение анкеты по-русски: коды из базы человеку ничего не говорят."""
    if value is None:
        return ""
    raw = getattr(value, "value", value)
    return mapping.get(raw, str(raw))


def _moment(value: datetime | None, timezone_name: str | None) -> tuple[str, str]:
    """Дата и время местные, отдельными столбцами — так их удобно сортировать."""
    if value is None:
        return "", ""
    local = to_local(value, timezone_name)
    return local.strftime("%Y-%m-%d"), local.strftime("%H:%M")


def _number(value) -> str:
    """Число для таблицы: без хвоста «.0» и с запятой вместо точки.

    Точка в дробном — не мелочь: в русской раскладке Excel и Numbers читают
    «70.5» как текст, и по такому столбцу нельзя ни сложить, ни построить
    график. С запятой это настоящее число.
    """
    if value is None:
        return ""
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value).replace(".", ",")
    return str(value)


def _sheet(headers: list[str], rows: list[list]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(headers)
    writer.writerows([[_number(cell) for cell in row] for row in rows])
    # BOM — не украшение: без него Excel открывает кириллицу нечитаемой.
    return ("﻿" + buffer.getvalue()).encode("utf-8")


def profile_rows(user: User) -> list[list]:
    """Профиль — двумя столбцами: в одну строку он не читается."""
    return [
        ["Имя", user.full_name or ""],
        ["Пол", _ru(user.gender, GENDER_RU)],
        ["Возраст", user.age],
        ["Рост, см", user.height_cm],
        ["Вес сейчас, кг", user.current_weight_kg],
        ["Вес цели, кг", user.target_weight_kg],
        ["Цель", _ru(user.goal, GOAL_RU)],
        ["Активность", _ru(user.activity_level, ACTIVITY_RU)],
        ["Питание", _ru(user.diet_type, DIET_RU)],
        ["Аллергии", user.allergies or ""],
        ["Часовой пояс", user.timezone or ""],
        ["Норма, ккал", user.daily_calories],
        ["Белки, г", user.daily_protein_g],
        ["Жиры, г", user.daily_fat_g],
        ["Углеводы, г", user.daily_carbs_g],
        ["Клетчатка, г", user.daily_fiber_g],
        ["Вода, мл", user.daily_water_ml],
        ["Шаги, цель", user.daily_steps or ""],
        ["Напоминания", "включены" if user.reminders_enabled else "выключены"],
    ]


async def _tables(session: AsyncSession, user: User,
                  tz: str | None) -> dict[str, tuple[list[str], list[list]]]:
    """Все таблицы выгрузки. Порядок строк — от старых к новым."""
    uid = user.id

    meals = (await session.execute(
        select(Meal).where(Meal.user_id == uid).order_by(Meal.logged_at))).scalars().all()
    water = (await session.execute(
        select(WaterLog).where(WaterLog.user_id == uid)
        .order_by(WaterLog.logged_at))).scalars().all()
    measures = (await session.execute(
        select(BodyMeasurement).where(BodyMeasurement.user_id == uid)
        .order_by(BodyMeasurement.measured_at))).scalars().all()
    workouts = (await session.execute(
        select(WorkoutLog, Workout).join(Workout, WorkoutLog.workout_id == Workout.id)
        .where(WorkoutLog.user_id == uid).order_by(WorkoutLog.completed_at))).all()
    checkins = (await session.execute(
        select(Checkin).where(Checkin.user_id == uid)
        .order_by(Checkin.logged_at))).scalars().all()
    steps = (await session.execute(
        select(StepLog).where(StepLog.user_id == uid)
        .order_by(StepLog.day))).scalars().all()
    supplements = (await session.execute(
        select(Supplement).where(Supplement.user_id == uid)
        .order_by(Supplement.created_at))).scalars().all()
    intakes = (await session.execute(
        select(SupplementLog, Supplement)
        .join(Supplement, SupplementLog.supplement_id == Supplement.id)
        .where(SupplementLog.user_id == uid).order_by(SupplementLog.logged_at))).all()

    return {
        "Профиль": (["Поле", "Значение"], profile_rows(user)),
        "Еда": (
            ["Дата", "Время", "Приём пищи", "Блюдо", "Вес, г", "Ккал", "Белки, г",
             "Жиры, г", "Углеводы, г", "Клетчатка, г", "Как записано"],
            [[*_moment(m.logged_at, tz),
              MEAL_TYPE_RU.get(m.meal_type, "") if m.meal_type else "",
              m.name, m.weight_g, m.calories, m.protein_g, m.fat_g, m.carbs_g, m.fiber_g,
              SOURCE_RU.get(m.source.value, m.source.value) if m.source else ""]
             for m in meals]),
        "Вода": (
            ["Дата", "Время", "Объём, мл"],
            [[*_moment(w.logged_at, tz), w.amount_ml] for w in water]),
        "Вес и замеры": (
            ["Дата", "Время", "Вес, кг", "Талия, см", "Бёдра, см", "Бедро, см",
             "Грудь, см", "Рука, см"],
            [[*_moment(m.measured_at, tz), m.weight_kg, m.waist_cm, m.hips_cm,
              m.thigh_cm, m.chest_cm, m.arm_cm] for m in measures]),
        "Тренировки": (
            ["Дата", "Время", "Упражнение", "Подходы", "Повторы", "Минуты", "Ккал"],
            [[*_moment(log.completed_at, tz), workout.name, log.sets_done, log.reps_done,
              log.duration_minutes, log.calories_burned] for log, workout in workouts]),
        "Шаги": (
            ["Дата", "Шаги"],
            [[entry.day.strftime("%d.%m.%Y"), entry.steps] for entry in steps]),
        "Самочувствие": (
            ["Дата", "Время", "Энергия", "Фокус", "Настроение", "Стресс", "Сон, ч", "Заметка"],
            [[*_moment(c.logged_at, tz), c.energy, c.focus, c.mood or "", c.stress or "",
              round(c.sleep_minutes / 60, 1) if c.sleep_minutes else "", c.note or ""]
             for c in checkins]),
        "Добавки": (
            ["Название", "Доза", "Расписание", "Дни недели", "Раз в дней", "Время",
             "Принимаю сейчас"],
            [[s.name, s.dose or "",
              SCHEDULE_RU.get(s.schedule_type.value, s.schedule_type.value),
              s.weekdays or "", s.interval_days,
              s.reminder_time.strftime("%H:%M") if s.reminder_time else "",
              "да" if s.is_active else "нет"] for s in supplements]),
        "Приём добавок": (
            ["Дата", "Время", "Название", "Отметка"],
            [[*_moment(log.logged_at, tz), supplement.name,
              "пропуск" if log.skipped else "принято"] for log, supplement in intakes]),
    }


async def build_export(session: AsyncSession, user: User, *, today: date | None = None) -> Export:
    """Собрать архив со всеми данными человека."""
    tz = user.timezone
    tables = await _tables(session, user, tz)

    photos = (await session.execute(
        select(ProgressPhoto)
        .where(ProgressPhoto.user_id == user.id, ProgressPhoto.file_name.is_not(None))
        .order_by(ProgressPhoto.taken_at))).scalars().all()

    buffer = io.BytesIO()
    included, skipped, photo_bytes = 0, 0, 0
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, (headers, rows) in tables.items():
            archive.writestr(f"{name}.csv", _sheet(headers, rows))

        directory = photos_dir(user.id)
        for photo in photos:
            path = directory / photo.file_name
            try:
                data = path.read_bytes()
            except OSError:
                # Файла нет на диске — запись в базе осталась, это не повод
                # ронять всю выгрузку.
                logger.warning("Фото %s не найдено на диске", path)
                skipped += 1
                continue
            if photo_bytes + len(data) > MAX_PHOTO_BYTES:
                skipped += 1
                continue
            day, _ = _moment(photo.taken_at, tz)
            archive.writestr(f"Фото/{day}-{photo.id}.jpg", data)
            photo_bytes += len(data)
            included += 1

        stamp = (today or date.today()).strftime("%d.%m.%Y")
        photo_line = (f"Фото/ — {included} фото прогресса." if included
                      else "Фото прогресса в этой выгрузке нет.")
        archive.writestr("Что внутри.txt",
                         README.format(photos=photo_line, stamp=stamp).encode("utf-8"))

    day = (today or date.today()).isoformat()
    return Export(
        filename=f"AURA-{day}.zip",
        content=buffer.getvalue(),
        rows={name: len(rows) for name, (_, rows) in tables.items()},
        photos_included=included,
        photos_skipped=skipped,
    )


__all__ = ["Export", "MAX_PHOTO_BYTES", "build_export", "profile_rows"]
