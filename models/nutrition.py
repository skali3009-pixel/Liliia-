"""Справочник питания: продукты, блюда и их состав.

Три причины, почему это отдельные таблицы, а не текст в промпте модели:
считать КБЖУ должна арифметика, а не языковая модель; состав нужен, чтобы
отсеивать аллергены по продуктам, а не по названию блюда; и порцию нужно
уметь пересчитать под норму конкретного человека.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base


class Product(Base):
    """Продукт и его КБЖУ на 100 г съедобной части."""

    __tablename__ = "nutrition_products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Код латиницей — стабильный ключ: название можно поправить, ссылки не сломаются.
    code: Mapped[str] = mapped_column(String(60), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Синонимы через «;» — «белая рыба» и «треска» это одна строка справочника.
    aliases: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    category: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    kcal: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    protein: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    fat: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    carbs: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    fiber: Mapped[float] = mapped_column(Float, default=0, nullable=False)

    # Вес одной штуки/ломтика/зубчика — чтобы «1 яблоко» стало граммами.
    gram_per_piece: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Соль, перец, специи: в тарелке есть, в подсчёте не участвуют.
    is_seasoning: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    vegan: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    vegetarian: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    gluten_free: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Аллергены через «;»: молоко, яйцо, рыба, морепродукты, орехи, глютен, соя, кунжут, мёд.
    allergens: Mapped[str] = mapped_column(String(200), default="", nullable=False)

    # Роль в тарелке: белок / крупа / овощи / фрукты / жир / молочное / прочее.
    role: Mapped[str] = mapped_column(String(20), default="прочее", nullable=False)


class Prep(Base):
    """Заготовка: готовим один раз — едим несколько дней.

    Главное здесь не рецепт, а сроки хранения: без них система заготовок
    превращается в «наготовила и выбросила».
    """

    __tablename__ = "nutrition_preps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(60), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    instructions: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)

    # Сколько порций выходит из партии. Не везде указано — тогда None, и
    # показываем КБЖУ на 100 г, а не выдумываем порцию.
    portions: Mapped[float | None] = mapped_column(Float, nullable=True)
    fridge_days: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    freezer_days: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    # Что из этой заготовки собирают — её же идеи, короткой строкой.
    ideas: Mapped[str] = mapped_column(String(300), default="", nullable=False)

    # На 100 г готовой заготовки.
    kcal: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    protein_g: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    fat_g: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    carbs_g: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    fiber_g: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    batch_g: Mapped[float] = mapped_column(Float, default=0, nullable=False)

    components: Mapped[list["PrepComponent"]] = relationship(
        back_populates="prep", cascade="all, delete-orphan", lazy="selectin"
    )


class PrepComponent(Base):
    """Продукт в заготовке: граммы на всю партию."""

    __tablename__ = "nutrition_prep_components"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prep_id: Mapped[int] = mapped_column(
        ForeignKey("nutrition_preps.id", ondelete="CASCADE"), index=True, nullable=False
    )
    product_code: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    grams: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    raw_amount: Mapped[str] = mapped_column(String(60), default="", nullable=False)

    prep: Mapped["Prep"] = relationship(back_populates="components")


class Dish(Base):
    """Блюдо: состав, способ приготовления и посчитанное КБЖУ на порцию."""

    __tablename__ = "nutrition_dishes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(60), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Приёмы пищи через «;»: одно блюдо честно бывает и обедом, и ужином.
    meal_types: Mapped[str] = mapped_column(String(60), nullable=False)
    # На сколько порций рассчитан состав. КБЖУ ниже — уже на одну порцию.
    portions: Mapped[float] = mapped_column(Float, default=1, nullable=False)

    instructions: Mapped[str] = mapped_column(Text, default="", nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    minutes: Mapped[int] = mapped_column(Integer, default=20, nullable=False)

    # Рецепт из меню Анастасии — в интерфейсе помечается значком.
    author: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    # Коды заготовок через «;»: что из этого блюда уже стоит готовым в холодильнике.
    prep_codes: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    # Порции подобраны нами, а не взяты из источника. Человек должен это видеть.
    estimated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Собирается без готовки: купил в магазине и сложил в миску.
    no_cook: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    kcal: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    protein_g: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    fat_g: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    carbs_g: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    fiber_g: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    weight_g: Mapped[float] = mapped_column(Float, default=0, nullable=False)

    components: Mapped[list["DishComponent"]] = relationship(
        back_populates="dish", cascade="all, delete-orphan", lazy="selectin"
    )


class DishComponent(Base):
    """Один продукт в блюде: сколько граммов на весь состав."""

    __tablename__ = "nutrition_dish_components"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dish_id: Mapped[int] = mapped_column(
        ForeignKey("nutrition_dishes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    product_code: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    grams: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    # Как это написано у нутрициолога: «2 ст. л.», «горсть», «1 шт».
    raw_amount: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    optional: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Штучные продукты не масштабируются дробно: яйцо не бывает 1,4 штуки.
    countable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    dish: Mapped["Dish"] = relationship(back_populates="components")


__all__ = ["Dish", "DishComponent", "Prep", "PrepComponent", "Product"]
