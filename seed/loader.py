"""Заливка библиотеки упражнений в базу.

Вызывается при старте бота. Повторный запуск ничего не дублирует: если
упражнения программы уже есть, она пропускается.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import LevelEnum, LocationEnum, Workout, WorkoutTypeEnum
from seed.workout_programs import CARDIO, PROGRAMS

logger = logging.getLogger(__name__)

CARDIO_CODE = "cardio"

# Упражнение то же, название стало точнее — под ролик, который показывает
# движение. Без этой карты загрузчик счёл бы новое имя новым упражнением, и
# в программе осталась бы вторая, призрачная строка со старым названием:
# удалять он не умеет и не должен, на строки ссылаются записи о тренировках.
# Переименование сохраняет и строку, и весь дневник за ней.
RENAMED: dict[str, str] = {
    "Лёгкие круги под глазами безымянным пальцем":
        "Мягкое разглаживание области под глазами двумя пальцами",
    "Разминание скул подушечками пальцев": "Массаж щёк от носа к ушам",
    "Массаж линии челюсти костяшками": "Массаж по линии нижней челюсти",
    # Блок 15: то же вытяжение шеи, что в «Фейс-йоге», и тот же язык к нёбу —
    # названия сведены к одному, чтобы упражнение было одним и в базе.
    "«Жираф»: вытяжение шеи вверх": "Вытягивание шеи вверх",
    "Язык к нёбу с наклоном головы": "Язык к нёбу с мягким подъёмом подбородка",
    # Блок 16 привязал работу тазового дна к дыханию: движение то же, но
    # теперь названо фазой вдоха и выдоха — иначе подпись под роликом и
    # подсказка в кольце говорили бы о разном.
    "Полное расслабление": "Расслабление тазового дна на вдохе",
    "Короткие сжатия": "Подъём на выдохе — расслабление на вдохе",
    "Ягодичный мостик с дыханием": "Ягодичный мостик с выдохом на подъёме",
}

# Упражнение убрано из программы, но не из базы: запись о тренировке,
# сделанной когда-то по нему, должна остаться правдой. Строка просто
# перестаёт числиться в программе и уходит из каталога.
RETIRED: frozenset[str] = frozenset({
    "Проработка носогубных складок",
    # Блок 15 пересобрал «Второй подбородок» из упражнений, у которых есть
    # показ. Эти четыре из программы ушли; в базе остались.
    "Сопротивление ладонью под подбородком",
    "Произнесение «И — У» с напряжением",
    "Наклон головы назад с движением челюсти",
    "Растяжка передней поверхности шеи",
    # Блок 16 строит программу вокруг дыхания и прямо просит не предлагать
    # держать тазовое дно напряжённым. Удержание и «лифт» — это как раз
    # долгое напряжение; из программы они ушли, в базе остались.
    "Долгое удержание",
    "«Лифт»: подъём по ступеням",
})


async def seed_workouts(session: AsyncSession) -> int:
    """Досоздать недостающее и перенести переехавшие программы.

    Раньше загрузчик просто пропускал всё, что уже есть в базе. Из-за этого
    любое изменение справочника доезжало только до новых установок: йога,
    переехавшая из «Тела» в «Спокойное», на работающем сервере осталась бы
    там же, где лежала, а новые занятия в списке кардио не появились бы
    вовсе — код программы-то на месте.

    Поэтому теперь: недостающее добавляем, переехавшее обновляем, и ничего
    никогда не удаляем. На упражнения ссылаются записи о тренировках, и
    удалённая строка унесла бы с собой чужой дневник.
    """
    rows = (await session.execute(select(Workout))).scalars().all()
    for row in rows:
        renamed = RENAMED.get(row.name)
        if renamed:
            row.name = renamed
        elif row.name in RETIRED:
            row.program_code = None

    by_program: dict[str, list[Workout]] = {}
    for row in rows:
        by_program.setdefault(row.program_code or "", []).append(row)

    added = 0

    for code, program in PROGRAMS.items():
        known = {row.name: row for row in by_program.get(code, [])}

        for row in known.values():
            row.category = program["category"]
            row.style = program.get("style")

        for position, item in enumerate(program["exercises"]):
            name, muscle, sets, reps, rest, met = item[:6]
            seconds_per_set = item[6] if len(item) > 6 else None
            if name in known:
                known[name].position = position
                continue
            session.add(
                Workout(
                    name=name,
                    workout_type=WorkoutTypeEnum.STRENGTH,
                    location=LocationEnum(program["location"]),
                    level=LevelEnum(program["level"]),
                    program_code=code,
                    category=program["category"],
                    style=program.get("style"),
                    position=position,
                    muscle_group=muscle,
                    # Для упражнений на время храним длительность подхода.
                    duration_minutes=seconds_per_set,
                    sets=sets,
                    reps=reps,
                    rest_seconds=rest,
                    met_value=met,
                )
            )
            added += 1

    known_cardio = {row.name: row for row in by_program.get(CARDIO_CODE, [])}
    for position, (name, minutes, met) in enumerate(CARDIO):
        if name in known_cardio:
            known_cardio[name].position = position
            continue
        session.add(
            Workout(
                name=name,
                workout_type=WorkoutTypeEnum.CARDIO,
                location=LocationEnum.HOME,
                level=LevelEnum.BEGINNER,
                program_code=CARDIO_CODE,
                category="body",
                style="cardio",
                position=position,
                duration_minutes=minutes,
                met_value=met,
            )
        )
        added += 1

    # Переносы категорий надо сохранить, даже когда ничего не добавилось.
    await session.commit()

    if added:
        logger.info("Добавлено упражнений в библиотеку: %s", added)
    return added
