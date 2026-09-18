"""Живое приложение с наполненными данными — общая сцена для съёмки промо.

Пустое приложение в промо-ролике хуже, чем никакого ролика: человек видит
нули и решает, что там нечего делать. Поэтому здесь два месяца настоящей
жизни — вес с недельной пилой, отметки цикла, еда за день, вода, шаги,
тренировки, достижения.
"""
import asyncio, contextlib, os, pathlib, sys, random, time
from datetime import date, datetime, timedelta

# Час съёмки. Машина живёт по UTC, и в московском времени сейчас глубокая
# ночь: приложение честно здоровается «доброй ночи» и говорит, что гепард
# свернулся клубком. Для промо это неверная нота — день должен быть почти
# собран, а не закончен. Поэтому часовой пояс сцены выбран так, чтобы
# «сейчас» приходилось на вечер; тот же пояс записан и человеку, иначе
# сутки у приложения и у данных разъедутся.
ПОЯС = os.environ.get("AURA_DEMO_TZ", "America/Sao_Paulo")
os.environ["TZ"] = ПОЯС
time.tzset()

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
os.environ.setdefault("BOT_TOKEN", "123456:AAAA")
os.environ.setdefault("ANTHROPIC_API_KEY", "x")

USER_ID = 4242


async def поднять(порт: int, путь_бд: str):
    """Поднять настоящее приложение на localhost. Возвращает runner."""
    if os.path.exists(путь_бд):
        os.remove(путь_бд)
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///" + путь_бд

    from aiohttp import web
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    import db as db_module
    from models import (Base, DietTypeEnum, GenderEnum, GoalEnum,
                        SubscriptionSource, User)
    from services.subscriptions import activate

    engine = create_async_engine(os.environ["DATABASE_URL"])
    maker = async_sessionmaker(engine, expire_on_commit=False)

    @contextlib.asynccontextmanager
    async def get_session():
        async with maker() as session:
            yield session

    import webapp.api as api
    api.get_session = get_session
    db_module.get_session = get_session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with maker() as s:
        from seed.nutrition.loader import seed_nutrition
        from seed.loader import seed_workouts
        await seed_nutrition(s)
        await seed_workouts(s)
        s.add(User(id=USER_ID, full_name="Лилия", gender=GenderEnum.FEMALE, age=31,
                   height_cm=167, current_weight_kg=64.2, target_weight_kg=60,
                   goal=GoalEnum.LOSE_WEIGHT, diet_type=DietTypeEnum.REGULAR,
                   timezone=ПОЯС, daily_calories=1700, daily_protein_g=125,
                   daily_fat_g=52, daily_carbs_g=170, daily_fiber_g=24,
                   daily_water_ml=2100, onboarding_completed=True))
        await s.commit()
        await activate(s, USER_ID, days=30, source=SubscriptionSource.MANUAL)
        await наполнить(s)

    from webapp import server as srv
    import webapp.auth as auth
    from types import SimpleNamespace
    fake = SimpleNamespace(id=USER_ID, first_name="Лилия", username="lili",
                           language_code="ru", is_premium=False)
    auth.verify_init_data = lambda *a, **k: fake
    api.verify_init_data = lambda *a, **k: fake

    app = srv.create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", порт).start()
    return runner


async def наполнить(s):
    """Два месяца жизни: вес, цикл, еда, вода, шаги, тренировки."""
    from models import (Achievement, BodyMeasurement, CycleLog, Meal,
                        MealSourceEnum, MealTypeEnum, StepLog, WaterLog,
                        Workout, WorkoutLog)
    from sqlalchemy import select

    сейчас = datetime.now()
    сегодня = сейчас.date()
    случай = random.Random(17)

    # --- Вес: снижение с недельной пилой и всплеском перед месячными.
    # Ради этой картинки календарь и заведён: плюс полтора килограмма
    # после недели без нарушений — самая частая причина бросить.
    цикл_старт = [сегодня - timedelta(days=d) for d in (58, 30, 2)]
    for л in цикл_старт:
        s.add(CycleLog(user_id=USER_ID, started_on=л))

    for дней_назад in range(60, -1, -1):
        д = сегодня - timedelta(days=дней_назад)
        # Всплеск — в четыре дня перед началом, а не после: именно тогда
        # человек встаёт на весы, видит плюс полтора и решает, что всё зря.
        впереди = [(н - д).days for н in цикл_старт if 0 < (н - д).days <= 4]
        всплеск = 1.5 - 0.2 * впереди[0] if впереди else 0.0
        основа = 66.8 - (60 - дней_назад) * 0.045
        вес = основа + всплеск + случай.uniform(-0.25, 0.25)
        if дней_назад % 2 == 0 or дней_назад < 7:
            s.add(BodyMeasurement(
                user_id=USER_ID, weight_kg=round(вес, 1),
                waist_cm=round(74 - (60 - дней_назад) * 0.03, 1) if дней_назад % 14 == 0 else None,
                hips_cm=round(98 - (60 - дней_назад) * 0.025, 1) if дней_назад % 14 == 0 else None,
                measured_at=datetime.combine(д, datetime.min.time()) + timedelta(hours=8)))

    # --- Шаги за две недели.
    for дней_назад in range(14, -1, -1):
        д = сегодня - timedelta(days=дней_назад)
        s.add(StepLog(user_id=USER_ID, day=д, source="shortcut",
                      steps=случай.randint(6200, 12400) if дней_назад else 7840))

    # --- Еда за сегодня: три приёма, чтобы кольцо было заполнено, но не закрыто.
    еда = [
        (MealTypeEnum.BREAKFAST, "Овсянка на молоке с ягодами", 240, 318, 11, 8, 49, 6, 8),
        (MealTypeEnum.LUNCH, "Гречка с куриной грудкой и салатом", 330, 462, 41, 11, 47, 7, 14),
        (MealTypeEnum.SNACK, "Творог 5% с грушей", 180, 214, 22, 9, 16, 3, 17),
    ]
    for тип, имя, г, ккал, б, ж, у, кл, час in еда:
        s.add(Meal(user_id=USER_ID, meal_type=тип, name=имя, weight_g=г,
                   calories=ккал, protein_g=б, fat_g=ж, carbs_g=у, fiber_g=кл,
                   source=MealSourceEnum.PHOTO if тип == MealTypeEnum.LUNCH
                   else MealSourceEnum.TEXT,
                   logged_at=datetime.combine(сегодня, datetime.min.time())
                   + timedelta(hours=час)))

    # --- Вода: больше половины нормы, чтобы кольцо жило, а «Твой ход» имел повод.
    for час, мл in ((8, 250), (10, 250), (12, 300), (14, 250), (16, 250)):
        s.add(WaterLog(user_id=USER_ID, amount_ml=мл,
                       logged_at=datetime.combine(сегодня, datetime.min.time())
                       + timedelta(hours=час)))

    # --- Тренировки: три за последнюю неделю.
    упражнения = (await s.execute(
        select(Workout).where(Workout.program_code.is_not(None)).limit(40))).scalars().all()
    for i, дней_назад in enumerate((6, 4, 1)):
        for у in упражнения[i * 3:i * 3 + 3]:
            s.add(WorkoutLog(user_id=USER_ID, workout_id=у.id, sets_done=3,
                             reps_done=12, duration_minutes=7,
                             calories_burned=38 + i * 4,
                             completed_at=сейчас - timedelta(days=дней_назад)))

    for код, титул, дней in (("first_meal", "Первая запись", 58),
                             ("week_streak", "Неделя подряд", 41),
                             ("water_7", "Семь дней воды", 22),
                             ("workout_10", "Десять тренировок", 9)):
        s.add(Achievement(user_id=USER_ID, code=код, title=титул,
                          earned_at=сейчас - timedelta(days=дней)))

    await s.commit()
