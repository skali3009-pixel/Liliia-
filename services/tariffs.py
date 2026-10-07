"""Public price catalogue. Viewing a plan never grants access or creates a bill.

Prices and allowances describe the planned paid launch. The existing beta
continues under its current access rules until the commercial module is ready.
"""

from dataclasses import asdict, dataclass
from html import escape


TITLE = "Питание, движение и прогресс в одном месте"
STATUS = "Платные тарифы готовятся к запуску. Сейчас AURA работает в тестовом режиме без оплаты."
BENEFITS = (
    "Записывай еду фото, голосом или текстом; проверяй КБЖУ и поправляй порции.",
    "Выбирай, что съесть: рецепты, заготовки и подбор продуктов с полки.",
    "Занимайся дома или в зале: программы, упражнения и запись тренировок.",
    "Следи за водой, шагами, весом, замерами и фото прогресса.",
    "Настраивай напоминания и отмечай небольшие шаги в игровом мире AURA.",
)
ALLOWANCE_NOTE = (
    "Лимиты ниже относятся к будущему платному запуску и пока не действуют. "
    "Распознавания и подбор с полки используют общий лимит; готовые рецепты "
    "не расходуют лимит создания блюд."
)


@dataclass(frozen=True)
class Tariff:
    id: str
    name: str
    days: int
    price_rub: int
    purpose: str
    recognitions: int
    dish_builds: int
    saving_rub: int = 0


PLANS = (
    Tariff("30", "На 30 дней", 30, 490, "Познакомиться с AURA и найти удобный ритм.", 120, 10),
    Tariff("90", "На 90 дней", 90, 1290, "Для регулярного использования без продления каждый месяц.", 360, 30, 180),
)


def find_plan(plan_id: str) -> Tariff | None:
    return next((plan for plan in PLANS if plan.id == plan_id), None)


def catalogue() -> dict:
    return {"title": TITLE, "status": STATUS, "sales_enabled": False,
            "benefits": list(BENEFITS), "allowance_note": ALLOWANCE_NOTE,
            "plans": [asdict(plan) for plan in PLANS]}


def overview_text() -> str:
    return (f"AURA · Тарифы\n\n{TITLE}\n\n"
            "Один состав функций — выбирай удобный срок.\n"
            "30 дней — 490 ₽\n90 дней — 1 290 ₽\n\n"
            f"{STATUS}\n\nНажми на срок, чтобы посмотреть состав и лимиты.")


def plan_text(plan: Tariff) -> str:
    saving = (f"\n430 ₽ за каждые 30 дней. Экономия {plan.saving_rub} ₽ "
              "по сравнению с тремя периодами по 490 ₽." if plan.saving_rub else "")
    return (f"AURA · {plan.name}\n{plan.price_rub:,} ₽ за весь срок".replace(",", " ")
            + f"{saving}\n\n{plan.purpose}\n\nВ состав тарифа входит:\n"
            + "\n".join(f"• {benefit}" for benefit in BENEFITS)
            + f"\n\nПосле запуска: {plan.recognitions} распознаваний еды и подборов с полки, "
              f"{plan.dish_builds} созданий блюда с ИИ за {plan.days} дней.\n\n"
            + f"{ALLOWANCE_NOTE}\n\n{STATUS}\n"
              "Просмотр тарифа ничего не списывает и не оформляет подписку.")


def render_page(documents: list[dict]) -> str:
    """Public, mobile friendly price tab for people and payment moderation."""
    cards = []
    for plan in PLANS:
        saving = (f"<p class='saving'>430 ₽ / 30 дней · экономия {plan.saving_rub} ₽ "
                  "по сравнению с тремя периодами по 490 ₽</p>" if plan.saving_rub else "")
        cards.append(
            f"<details class='plan'><summary><span>{escape(plan.name)}</span>"
            f"<strong>{plan.price_rub:,} ₽</strong><small>за весь срок · открыть описание</small>"
            "</summary>".replace(",", " ")
            + f"<p>{escape(plan.purpose)}</p>{saving}<h2>Что входит</h2><ul>"
            + "".join(f"<li>{escape(benefit)}</li>" for benefit in BENEFITS)
            + f"</ul><p><b>После запуска:</b> {plan.recognitions} распознаваний еды и подборов с полки, "
              f"{plan.dish_builds} созданий блюда с ИИ за {plan.days} дней.</p>"
            + f"<p class='muted'>{escape(ALLOWANCE_NOTE)}</p></details>"
        )
    links = "".join(f"<a href='{escape(doc['url'], quote=True)}'>{escape(doc['title'])}</a>"
                    for doc in documents)
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>AURA · Тарифы и цены</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#0e1020;color:#f7f3fb;font:16px/1.5 system-ui,sans-serif}}
main{{max-width:720px;margin:auto;padding:28px 18px}}h1{{font-size:30px;line-height:1.2}}h2{{font-size:18px}}
.eyebrow,.muted,small{{color:#c6bed5}}.notice{{background:#24213c;border-radius:16px;padding:16px}}
.plan{{margin:16px 0;padding:18px;background:#191a30;border:1px solid #50476b;border-radius:20px}}
summary{{cursor:pointer;min-height:90px;display:grid;gap:6px}}summary:focus-visible,a:focus-visible{{outline:3px solid #d4a7ff}}
summary span{{font-weight:650}}summary strong{{font-size:32px;color:#f4d5ad}}summary small{{font-size:14px}}
li{{margin-bottom:10px}}ul{{padding-left:20px}}.saving{{color:#e1b9fc}}nav{{display:grid;gap:10px}}
a{{color:#dcc2ff;min-height:44px;display:flex;align-items:center}}footer{{margin-top:28px}}
</style></head><body><main><p class="eyebrow">AURA · Тарифы и цены</p>
<h1>{escape(TITLE)}</h1><p>Один состав функций — выбирай удобный срок.</p>
<p class="notice">{escape(STATUS)} Просмотр цены ничего не списывает.</p>
{''.join(cards)}<p class="muted">AURA предназначена для взрослых. Расчёты КБЖУ приблизительные;
сервис не заменяет консультацию врача.</p><footer><h2>Документы</h2><nav>{links}</nav></footer>
</main></body></html>"""
