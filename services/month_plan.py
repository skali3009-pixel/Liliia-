"""A practical four-week route backed by the existing workout catalogue."""
from html import escape

from services.workout_picker import pick


def render_plan(data: dict) -> str:
    from handlers.onboarding import TRAINING_PACES, TRAINING_PLACES
    from keyboards.onboarding import GOAL_LABELS, DIET_LABELS
    from models import DietTypeEnum
    from utils.formulas import Goal
    minutes, days, _ = TRAINING_PACES[data.get("training_pace", "gentle")]
    place = data.get("training_place", "none")
    lines = [
        f"✨ {escape(data.get('profile_name') or '')}, твой план на 30 дней",
        f"🎯 Цель: {GOAL_LABELS[Goal(data['goal'])]}",
        "🥗 Питание\nОриентируйся на суточные КБЖУ и воду из расчёта выше. "
        "В первую неделю записывай привычные блюда фото, голосом или текстом: "
        "проверяй состав и порцию перед сохранением.\n"
        "Со второй недели подбирай блюда в разделе «Еда» под оставшиеся калории "
        "и белок. Пропущенные записи не означают, что ты ничего не ел.",
        f"Твой тип питания: {DIET_LABELS[DietTypeEnum(data['diet_type'])]}. "
        f"Исключения: {escape(data.get('allergies') or 'не указаны')}. "
        "Проверяй состав выбранных блюд.",
    ]
    if place == "none":
        lines.append("🚶 Движение\nПока без обязательных тренировок. "
                     "Записывай привычную активность и шаги; начать занятия можно "
                     "в разделе «Тренировки», когда будешь готов.")
    else:
        picks = pick(minutes_available=minutes, location=place, category="body", limit=2)
        schedule = "например, вторник и суббота" if days == 2 else "например, понедельник, среда и суббота"
        lines.append(f"🏋️ Движение: {TRAINING_PLACES[place].lower()}\n"
                     f"{days} занятия в неделю, около {minutes} минут — {schedule}. "
                     "Между силовыми занятиями оставляй день отдыха.")
        if picks:
            lines.append("Из каталога AURA подходят:\n" + "\n".join(
                f"• {escape(item.title)} — около {item.minutes} мин." for item in picks
            ) + "\nОни доступны в разделе «Тренировки». Перед началом проверь "
                "список упражнений и нужный инвентарь.")
        else:
            lines.append("В каталоге пока нет полной программы под это сочетание места "
                         "и времени. Можно выбрать упражнения вручную или записать "
                         "свою активность; готовую программу под эти условия не обещаем.")
        lines.append("Неделя 1: освой технику в комфортном темпе.\n"
                     "Недели 2–3: сохраняй выбранный ритм и отмечай выполненные занятия.\n"
                     "Неделя 4: сравни записи и самочувствие; повышать нагрузку автоматически не нужно.")
    lines.append("📊 Контроль результата\nСделай начальный замер в «Прогрессе» и повтори "
                 "его в конце месяца. Дни 29–30 — время сравнить питание, активность "
                 "и замеры. AURA покажет записанные изменения, а не обещанный результат.")
    return "\n\n".join(lines)


def _user_plan_data(user) -> dict:
    """Данные плана из сохранённого профиля, без FSM."""
    from handlers.onboarding import TRAINING_PACES
    from models import DietTypeEnum
    from utils.formulas import Goal

    pace = "gentle"
    for key, (minutes, days, _) in TRAINING_PACES.items():
        if user.training_minutes == minutes and user.training_days == days:
            pace = key
            break
    goal = getattr(user.goal, "value", user.goal) or "maintain"
    diet = getattr(user.diet_type, "value", user.diet_type) or "regular"
    return {
        "profile_name": user.full_name or "",
        "goal": goal,
        "diet_type": diet,
        "allergies": user.allergies,
        "training_place": user.training_place or "none",
        "training_pace": pace,
    }


def preview_for_user(user) -> str:
    """Короткое превью плана: без цены и без длинного текста."""
    from handlers.onboarding import TRAINING_PACES
    from keyboards.onboarding import DIET_LABELS, GOAL_LABELS
    from models import DietTypeEnum
    from utils.formulas import Goal

    data = _user_plan_data(user)
    name = escape(data["profile_name"])
    goal = GOAL_LABELS[Goal(data["goal"])]
    diet = DIET_LABELS[DietTypeEnum(data["diet_type"])]
    minutes, days, _ = TRAINING_PACES[data["training_pace"]]
    if data["training_place"] == "none":
        movement = "пока без обязательных тренировок"
    else:
        movement = f"{days} занятия в неделю по {minutes} минут"
    return (
        f"✨ {name}, твой план на 30 дней готов.\n\n"
        f"🎯 Цель: {goal}\n"
        f"🍽 Питание: {diet}, аллергии: {escape(data['allergies'] or 'нет')}\n"
        f"🏋️ Движение: {movement}\n"
        "📊 Контроль: замер в начале и в конце месяца.\n\n"
        "Полный план с расписанием, тренировками и рекомендациями на каждый день уже собран."
    )


def render_plan_for_user(user) -> str:
    """Полный план для отправки после оплаты."""
    return render_plan(_user_plan_data(user))


__all__ = ["preview_for_user", "render_plan", "render_plan_for_user"]
