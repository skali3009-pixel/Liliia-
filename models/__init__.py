"""Модели SQLAlchemy. Импортируются все вместе, чтобы relationship()
корректно резолвил forward-references между таблицами и чтобы
Base.metadata содержал полную схему БД (users, meals, water_log, workouts,
workout_log, body_measurements, progress_photos, achievements)."""

from models.achievement import Achievement
from models.base import Base
from models.body import BodyMeasurement, ProgressPhoto
from models.checkin import Checkin
from models.nutrition import Dish, DishComponent, Prep, PrepComponent, Product
from models.usage import ApiUsage
from models.day_stat import DayStat
from models.meal import Meal, MealSourceEnum, MealTypeEnum
from models.friendship import Friendship, Invite
from models.steps import StepLog
from models.team import Team, TeamMember
from models.user_prep import UserPrep
from models.user import (
    ActivityLevelEnum,
    DietTypeEnum,
    GenderEnum,
    GoalEnum,
    User,
)
from models.subscription import (
    Payment,
    Subscription,
    SubscriptionSource,
    SubscriptionStatus,
)
from models.supplement import ScheduleTypeEnum, Supplement, SupplementLog
from models.water import WaterLog
from models.workout import LevelEnum, LocationEnum, Workout, WorkoutLog, WorkoutTypeEnum

__all__ = [
    "Base",
    "StepLog",
    "Team",
    "TeamMember",
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
    "Checkin",
    "UserPrep",
    "Friendship",
    "Invite",
    "Subscription",
    "SubscriptionStatus",
    "SubscriptionSource",
    "Payment",
    "Supplement",
    "SupplementLog",
    "ScheduleTypeEnum",
    "Dish",
    "DishComponent",
    "Product",
    "Prep",
    "PrepComponent",
    "ApiUsage",
]
