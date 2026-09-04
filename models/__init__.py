"""Модели SQLAlchemy. Импортируются все вместе, чтобы relationship()
корректно резолвил forward-references между таблицами и чтобы
Base.metadata содержал полную схему БД (users, meals, water_log, workouts,
workout_log, body_measurements, progress_photos, achievements)."""

from models.achievement import Achievement
from models.base import Base
from models.body import BodyMeasurement, ProgressPhoto
from models.day_stat import DayStat
from models.meal import Meal, MealSourceEnum, MealTypeEnum
from models.user import (
    ActivityLevelEnum,
    DietTypeEnum,
    GenderEnum,
    GoalEnum,
    User,
)
from models.supplement import ScheduleTypeEnum, Supplement, SupplementLog
from models.water import WaterLog
from models.workout import LevelEnum, LocationEnum, Workout, WorkoutLog, WorkoutTypeEnum

__all__ = [
    "Base",
    "User",
    "GenderEnum",
    "ActivityLevelEnum",
    "GoalEnum",
    "DietTypeEnum",
    "Meal",
    "MealTypeEnum",
    "MealSourceEnum",
    "WaterLog",
    "Workout",
    "WorkoutLog",
    "LocationEnum",
    "LevelEnum",
    "WorkoutTypeEnum",
    "BodyMeasurement",
    "ProgressPhoto",
    "Achievement",
    "DayStat",
    "Supplement",
    "SupplementLog",
    "ScheduleTypeEnum",
]
