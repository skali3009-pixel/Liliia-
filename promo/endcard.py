"""Финальная карточка ролика. Рисует браузер — шрифтами самого приложения.

Имя бота в коде пустое (узнаётся на ходу, `services/identity.py`), и
выдумывать его нельзя: промо с несуществующей ссылкой хуже, чем промо без
ссылки. Передаётся аргументом, когда станет известно.
"""
import asyncio, pathlib, sys

ЗДЕСЬ = pathlib.Path(__file__).resolve().parent
СБОРКА = ЗДЕСЬ / "build"
СБОРКА.mkdir(exist_ok=True)

СТРАНИЦА = """
<!doctype html><html lang="ru"><head><meta charset="utf-8">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600&family=Playfair+Display:wght@500&display=swap" rel="stylesheet">
<style>
  html,body{margin:0;height:1920px;width:1080px;background:transparent;
            font-family:'Manrope',sans-serif;}
  .c{position:absolute;left:0;right:0;top:50%%;transform:translateY(-50%%);
     text-align:center;}
  .mark{font-family:'Playfair Display',serif;font-weight:500;font-size:150px;
        letter-spacing:.06em;color:#F4F1FF;margin:0;
        text-shadow:0 0 90px rgba(139,92,246,.55);}
  .rule{width:190px;height:2px;background:#C9A961;opacity:.75;margin:34px auto 30px;}
  .sub{font-size:31px;font-weight:600;letter-spacing:.24em;text-transform:uppercase;
       color:#C9A961;margin:0;}
  .note{font-size:31px;color:#A79CC9;margin:26px 0 0;}
  .handle{font-size:38px;font-weight:600;color:#C4B5FD;margin:44px 0 0;}
</style></head><body>
<div class="c">
  <p class="mark">AURA</p>
  <div class="rule"></div>
  <p class="sub">Питание · Движение · Тело</p>
  <p class="note">Телеграм-бот и приложение</p>
  %(handle)s
</div></body></html>
"""


async def main(ручка: str):
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        b = await pw.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        page = await b.new_page(viewport={"width": 1080, "height": 1920},
                                device_scale_factor=1)
        строка = f'<p class="handle">{ручка}</p>' if ручка else ""
        await page.set_content(СТРАНИЦА % {"handle": строка})
        await page.wait_for_timeout(900)
        await page.screenshot(path=str(СБОРКА / "endtext.png"), omit_background=True)
        # И сразу кладём текст на тот же фон, что у кадров. Прозрачной
        # карточку оставлять нельзя: под ней остаётся кромка окна, и на
        # последней секунде на экране висит пустой контур телефона.
        from PIL import Image
        фон = Image.open(СБОРКА / "bg.png").convert("RGBA")
        текст = Image.open(СБОРКА / "endtext.png").convert("RGBA")
        Image.alpha_composite(фон, текст).convert("RGB").save(СБОРКА / "end.png")
        есть = await page.evaluate("document.fonts.check('500 150px \"Playfair Display\"')")
        print("Playfair загружен:", есть, "| ручка:", ручка or "не задана")
        await b.close()

asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else ""))
