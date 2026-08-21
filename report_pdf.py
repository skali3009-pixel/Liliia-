"""Рендер Instagram-аудита (снимок данных + разбор Claude) в PDF."""

from __future__ import annotations

import re
from datetime import datetime
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable, ListFlowable, ListItem, PageBreak, Paragraph,
    SimpleDocTemplate, Spacer, Table, TableStyle,
)

PINK = colors.HexColor("#C2185B")
DARK = colors.HexColor("#222222")
GRAY = colors.HexColor("#666666")
LIGHT = colors.HexColor("#F6F1F3")
BORDER = colors.HexColor("#E5D5DD")

# Стандартный путь пакета fonts-dejavu-core на Debian/Ubuntu.
_FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
_FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

_fonts_registered = False

# DejaVu Sans (наш кириллический шрифт) не содержит глифов эмодзи — без них
# такие символы рисуются как пустые прямоугольники. Claude иногда добавляет
# эмодзи в текст, поэтому вычищаем их перед вставкой в PDF.
_EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FFFF"  # эмодзи и пиктограммы всех плоскостей
    "\U00002600-\U000027BF"  # прочие символы и дингбаты
    "\U00002B00-\U00002BFF"  # прочие символы и стрелки
    "\U0000FE00-\U0000FE0F"  # селекторы вариаций
    "\U0000200D"              # ZWJ
    "\U000020E0-\U000020FF"  # объединяющие метки (keycap и т.п.)
    "]+"
)


def _safe(text) -> str:
    """Готовит текст от Claude к вставке в Paragraph: убирает эмодзи (нет
    глифов в шрифте) и экранирует XML-спецсимволы (<, >, &), которые
    reportlab иначе попытается разобрать как разметку."""
    if not text:
        return ""
    text = _EMOJI_RE.sub("", str(text))
    text = re.sub(r"[ \t]+", " ", text)
    # Убираем пробел, оставшийся на месте вырезанного эмодзи в начале/конце строки.
    text = re.sub(r"^[ \t]+|[ \t]+$", "", text, flags=re.MULTILINE)
    return escape(text.strip())


def _ensure_fonts() -> None:
    global _fonts_registered
    if _fonts_registered:
        return
    try:
        pdfmetrics.registerFont(TTFont("DejaVu", _FONT_REGULAR))
        pdfmetrics.registerFont(TTFont("DejaVu-Bold", _FONT_BOLD))
    except Exception as e:
        raise RuntimeError(
            "Не найден шрифт с поддержкой кириллицы. Установите пакет "
            "fonts-dejavu-core (sudo apt install fonts-dejavu-core)."
        ) from e
    _fonts_registered = True


def _build_styles():
    styles = getSampleStyleSheet()

    def add(name: str, **kw) -> None:
        base = dict(fontName="DejaVu", fontSize=10.5, leading=15, textColor=DARK, spaceAfter=6)
        base.update(kw)
        styles.add(ParagraphStyle(name=name, **base))

    add("H1", fontName="DejaVu-Bold", fontSize=20, leading=24, textColor=PINK, spaceAfter=4)
    add("Sub", fontSize=11, leading=14, textColor=GRAY, spaceAfter=18)
    add("H2", fontName="DejaVu-Bold", fontSize=14, leading=18, textColor=PINK, spaceBefore=14, spaceAfter=8)
    add("H3", fontName="DejaVu-Bold", fontSize=11.5, leading=15, spaceBefore=8, spaceAfter=4)
    add("Body", spaceAfter=6)
    add("Small", fontSize=9, leading=12, textColor=GRAY)
    add("Stat", fontName="DejaVu-Bold", fontSize=15, leading=18, textColor=PINK, alignment=1)
    add("StatLabel", fontSize=8.5, leading=11, textColor=GRAY, alignment=1)
    add("Bio", fontSize=10.5, leading=16, textColor=DARK)
    add("TableHead", fontName="DejaVu-Bold", fontSize=9.5, leading=13, textColor=colors.white)
    add("TableCell", fontName="DejaVu-Bold", fontSize=9.5, leading=13, textColor=PINK)
    return styles


def _fmt(n) -> str:
    try:
        return f"{int(n):,}".replace(",", " ")
    except (TypeError, ValueError):
        return str(n)


def _fmt_signed(n) -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return str(n)
    sign = "+" if n >= 0 else ""
    return f"{sign}{n:,}".replace(",", " ")


def render_pdf(snapshot: dict, audit: dict, output_path: str) -> str:
    """Строит PDF-отчёт из данных Instagram (snapshot) и разбора Claude (audit)."""
    _ensure_fonts()
    styles = _build_styles()
    story = []

    profile = snapshot["profile"]
    metrics = snapshot["account_metrics"]
    period = snapshot["period"]
    username = profile.get("username") or ""

    story.append(Paragraph(f"Instagram-аудит: @{_safe(username)}", styles["H1"]))
    story.append(Paragraph(
        f"Личный бренд · подготовлено {datetime.now().strftime('%d.%m.%Y')} · "
        f"период анализа: {period['since']}–{period['until']} (30 дней)",
        styles["Sub"],
    ))

    def stat_cell(value: str, label: str):
        return [Paragraph(value, styles["Stat"]), Paragraph(label, styles["StatLabel"])]

    stats = Table([[
        stat_cell(_fmt(profile.get("followers_count")), "подписчиков"),
        stat_cell(_fmt_signed(metrics.get("follower_change_30d")), "рост за 30 дней"),
        stat_cell(_fmt(metrics.get("reach_30d")), "охват (30 дней)"),
        stat_cell(_fmt(metrics.get("total_interactions")), "взаимодействий"),
    ]], colWidths=[42 * mm] * 4)
    stats.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(stats)
    story.append(Spacer(1, 6 * mm))

    # 1. Профиль и био
    story.append(Paragraph("1. Профиль и био", styles["H2"]))
    if audit.get("bio_first_impression"):
        story.append(Paragraph(_safe(audit["bio_first_impression"]), styles["Body"]))
    if audit.get("bio_improved"):
        story.append(Paragraph("<b>Улучшенный вариант био:</b>", styles["H3"]))
        # Экранируем построчно, чтобы сохранить переносы строк как <br/>.
        bio_text = "<br/>".join(_safe(line) for line in audit["bio_improved"].split("\n"))
        bio_table = Table([[Paragraph(bio_text, styles["Bio"])]], colWidths=[160 * mm])
        bio_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
            ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
            ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(bio_table)

    # 2. Что работает
    story.append(Paragraph("2. Что работает — топ постов за 30 дней", styles["H2"]))
    for post in audit.get("top_posts") or []:
        if post.get("caption_snippet"):
            story.append(Paragraph(_safe(post["caption_snippet"]), styles["H3"]))
        if post.get("why"):
            story.append(Paragraph(_safe(post["why"]), styles["Body"]))

    # 3. Что не работает
    story.append(Paragraph("3. Что не работает", styles["H2"]))
    weak_items = audit.get("weak_content") or []
    if weak_items:
        story.append(ListFlowable(
            [ListItem(Paragraph(_safe(x), styles["Body"]), leftIndent=8) for x in weak_items],
            bulletType="bullet", start="•", bulletColor=PINK, leftIndent=12,
        ))
    if audit.get("stop_doing"):
        story.append(Paragraph(f"<b>Что прекратить делать:</b> {_safe(audit['stop_doing'])}", styles["Body"]))

    story.append(PageBreak())

    # 4. Стратегия
    story.append(Paragraph("4. Стратегия — контент-рубрики", styles["H2"]))
    for pillar in audit.get("content_pillars") or []:
        if pillar.get("title"):
            story.append(Paragraph(_safe(pillar["title"]), styles["H3"]))
        if pillar.get("description"):
            story.append(Paragraph(_safe(pillar["description"]), styles["Body"]))

    # 5. Быстрые победы
    story.append(Paragraph("5. Быстрые победы — на эту неделю", styles["H2"]))
    wins = audit.get("quick_wins") or []
    if wins:
        story.append(ListFlowable(
            [ListItem(Paragraph(_safe(x), styles["Body"]), leftIndent=8) for x in wins],
            bulletType="1", start=1, leftIndent=14,
        ))

    # 6. План на 90 дней
    story.append(Paragraph("6. План на 90 дней", styles["H2"]))
    plan_rows = [["Месяц", "Ключевая задача"]]
    for item in audit.get("plan_90_days") or []:
        plan_rows.append([item.get("month", ""), item.get("task", "")])
    if len(plan_rows) > 1:
        header, body_rows = plan_rows[0], plan_rows[1:]
        table_data = [[Paragraph(_safe(c), styles["TableHead"]) for c in header]]
        for month, task in body_rows:
            table_data.append([Paragraph(_safe(month), styles["TableCell"]), Paragraph(_safe(task), styles["Body"])])
        pt = Table(table_data, colWidths=[24 * mm, 134 * mm])
        pt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), PINK),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#DDDDDD")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(pt)

    story.append(Spacer(1, 8 * mm))
    story.append(HRFlowable(width="100%", color=BORDER))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(
        "Источник данных: Instagram Graph API через Composio. Метрики за 30 дней "
        "и по последним публикациям — реальные данные, без прогнозов и допущений.",
        styles["Small"],
    ))

    doc = SimpleDocTemplate(
        output_path, pagesize=A4, topMargin=18 * mm, bottomMargin=16 * mm,
        leftMargin=18 * mm, rightMargin=18 * mm, title=f"Instagram-аудит @{username}",
    )
    doc.build(story)
    return output_path
