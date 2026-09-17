"""Подписи к промо-ролику: рисует их сам браузер, настоящими шрифтами.

Почему не ffmpeg drawtext: у него нет ни Playfair Display, ни разрядки
надзаголовка, ни переносов по смыслу. А дизайн-система проекта — это в том
числе типографика; подпись чужим шрифтом читалась бы как чужая.

Правила текста те же, что у техники упражнений: ни обещаний результата,
ни диагнозов, одно предложение на подпись.
"""
import asyncio, json, pathlib, sys

ЗДЕСЬ = pathlib.Path(__file__).resolve().parent
СБОРКА = ЗДЕСЬ / "build"
СБОРКА.mkdir(exist_ok=True)
ВЫХОД = СБОРКА / "caps"
ШИРИНА = 1000          # подписи чуть уже кадра: поля по 40 точек

# (ключ, надзаголовок, строка). Порядок — порядок сцен.
ПОДПИСИ = [
    ("start",  "AURA",                "Приложение, которое не считает тебя ленивой"),
    ("turn",   "Твой ход",            "Одно дело — то, которое нужно сейчас"),
    ("rings",  "Еда",                 "Сколько съедено и сколько осталось — одним кольцом"),
    ("steps",  "День целиком",        "Шаги, вода и задания — на одном экране"),
    ("food",   "Что съесть",          "«Реши за меня» — когда выбирать нет сил"),
    ("gym",    "Спорт",               "Пятнадцать минут? Подберёт под это время"),
    ("player", "Тренировка",          "И покажет движение — прямо здесь, а не ссылкой"),
    ("weight", "Прогресс",            "Вес, объёмы и фото по неделям"),
    ("cycle",  "Женский календарь",   "Вес перед месячными выше не потому,\nчто ты что-то сделала не так"),
    ("world",  "Мой мир",             "А закрытый день открывает кусочек мира"),
]

СТРАНИЦА = """
<!doctype html><html lang="ru"><head><meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700&family=Playfair+Display:ital,wght@0,500;0,600;1,500&display=swap" rel="stylesheet">
<style>
  html, body { margin:0; padding:0; background:transparent; }
  .wrap { width:%(w)dpx; padding:0; font-family:'Manrope',sans-serif;
          text-align:center; }
  .eyebrow { font-size:26px; font-weight:600; letter-spacing:.22em;
             text-transform:uppercase; color:#C9A961; margin:0 0 18px; }
  .line { font-family:'Playfair Display',serif; font-weight:500;
          font-size:%(fs)dpx; line-height:1.24; color:#F4F1FF; margin:0;
          text-shadow:0 2px 24px rgba(10,9,18,.9), 0 0 60px rgba(139,92,246,.35); }
</style></head><body>
<div class="wrap"><p class="eyebrow">%(eyebrow)s</p><p class="line">%(line)s</p></div>
</body></html>
"""


async def main():
    ВЫХОД.mkdir(exist_ok=True)
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        b = await pw.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        page = await b.new_page(viewport={"width": ШИРИНА, "height": 400},
                                device_scale_factor=1)
        размеры = {}
        for ключ, надзаголовок, строка in ПОДПИСИ:
            # Длинная строка набирается мельче: два размера на весь ролик —
            # это уже не типографика, а лотерея.
            кегль = 54 if len(строка) > 46 else 60
            html = СТРАНИЦА % {"w": ШИРИНА, "fs": кегль,
                               "eyebrow": надзаголовок,
                               "line": строка.replace("\n", "<br>")}
            await page.set_content(html)
            await page.wait_for_timeout(700)          # дать шрифтам доехать
            шрифт = await page.evaluate(
                "document.fonts.check('500 60px \"Playfair Display\"')")
            узел = await page.query_selector(".wrap")
            await узел.screenshot(path=str(ВЫХОД / f"{ключ}.png"), omit_background=True)
            рамка = await узел.bounding_box()
            размеры[ключ] = {"высота": round(рамка["height"]), "шрифт": шрифт}
            print(f"  {ключ:8} {round(рамка['height']):4} точек в высоту, "
                  f"Playfair загружен: {шрифт}")
        (СБОРКА / "caps.json").write_text(json.dumps(размеры, ensure_ascii=False, indent=1))
        await b.close()

asyncio.run(main())
