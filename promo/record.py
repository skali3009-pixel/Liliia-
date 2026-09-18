"""Запись экрана живого приложения для промо-ролика.

Снимается настоящее приложение на настоящих данных — не макет. Ролики Аи
подменяются на лету на перекодированные копии: Chromium в этом контейнере
собран без H.264 и иначе показал бы застывшую заставку вместо движения.
Кадры те же, меняется только упаковка, и только для записи — в проекте
ролики остаются как есть.

Время считается от первого кадра записи, а не от конца настройки: иначе
отсечку пришлось бы вычислять вычитанием, и она уезжала бы при каждой
правке сценария.
"""
import asyncio, os, sys, pathlib

ЗДЕСЬ = pathlib.Path(__file__).resolve().parent
СБОРКА = ЗДЕСЬ / "build"
СБОРКА.mkdir(exist_ok=True)
sys.path.insert(0, str(ЗДЕСЬ))
from stage import поднять

PORT = 9103
WEBM = СБОРКА / "webm"
ВИДЕО = СБОРКА / "raw"
Ш, В = 390, 844


async def main():
    await поднять(PORT, str(СБОРКА / "record.db"))
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        браузер = await pw.chromium.launch(
            executable_path="/opt/pw-browsers/chromium",
            args=["--autoplay-policy=no-user-gesture-required",
                  # Без этого захват изредка рисует страницу в четверть
                  # буфера, а вокруг кладёт серое поле. Поймано глазами на
                  # третьей записи: вторая с теми же настройками вышла целой.
                  "--force-device-scale-factor=2"])
        контекст = await браузер.new_context(
            viewport={"width": Ш, "height": В}, device_scale_factor=2,
            record_video_dir=str(ВИДЕО),
            record_video_size={"width": Ш * 2, "height": В * 2})

        async def подменить(route):
            имя = pathlib.Path(route.request.url.split("?")[0]).stem + ".webm"
            файл = WEBM / имя
            if файл.exists():
                await route.fulfill(status=200, body=файл.read_bytes(),
                                    headers={"Content-Type": "video/webm",
                                             "Accept-Ranges": "bytes"})
            else:
                await route.continue_()

        await контекст.route("**/trainer/animations/*.mp4", подменить)

        page = await контекст.new_page()
        часы = asyncio.get_event_loop()
        нуль = часы.time()                      # первый кадр записи
        метки = []

        def отметить(имя):
            метки.append((имя, часы.time() - нуль))
            print(f"МЕТКА {имя:18} {метки[-1][1]:6.2f}")

        page.on("pageerror", lambda e: print("ОШИБКА СТРАНИЦЫ:", str(e)[:200]))
        await page.goto(f"http://127.0.0.1:{PORT}/")
        await page.wait_for_timeout(2500)
        await page.evaluate("localStorage.setItem('aura.tour', JSON.stringify("
                            "['today','world','gym','cube','progress']))")
        await page.reload()
        await page.wait_for_timeout(4000)
        await page.evaluate(
            "for (const el of document.querySelectorAll('.pop')) el.style.display='none'")
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(600)

        async def пауза(мс): await page.wait_for_timeout(мс)

        async def к(селектор, мс=1500, место="center"):
            """Подвести нужный блок к глазам — по элементу, а не по координате."""
            await page.evaluate(
                "([s, b]) => { const el = document.querySelector(s);"
                " if (el) el.scrollIntoView({behavior:'smooth', block:b}); }",
                [селектор, место])
            await пауза(мс)

        async def вкладка(имя, мс=1500):
            await page.click(f'.tab[data-screen="{имя}"]')
            await пауза(мс)

        отметить("НАЧАЛО")                       # отсюда режем чистовик

        # --- 1. «Сегодня»: шапка и «Твой ход».
        # Первые две сцены держим дольше остального. Две секунды на шапку
        # пролетают и без голоса, а с голосом туда не помещается даже одна
        # фраза — а первая фраза в промо и есть та, ради которой смотрят
        # дальше.
        await пауза(4400)
        отметить("ход")
        await к("#turn", 1700, "center")
        await пауза(2700)

        # --- 2. Кольцо калорий и БЖУ.
        отметить("кольца")
        await к("#kcal-left", 1500, "center")
        await пауза(1800)

        # --- 3. Шаги.
        отметить("шаги")
        await к("#steps-value", 1400, "center")
        await пауза(1500)

        # --- 4. Еда.
        отметить("еда")
        await вкладка("cube", 1700)
        await к("#decide-btn", 1400, "center")
        await пауза(1600)

        # --- 5. Спорт: подбор под время.
        отметить("спорт")
        await вкладка("gym", 1700)
        чипы = await page.query_selector_all("#pick-time .chip-btn")
        if len(чипы) > 1:
            await чипы[1].click()                # 15 минут
        await пауза(2300)
        await к("#pick-card", 1200, "center")
        await пауза(1200)

        # --- 6. Проводник: живое движение Аи.
        отметить("проводник")
        кнопка = await page.query_selector("#start-workout")
        if кнопка:
            await кнопка.click()
            await пауза(6200)                    # больше одного круга ролика
        видно = await page.evaluate(
            "(() => { const v = document.querySelector('#player video');"
            " return v ? {есть:1, идёт:!v.paused, время:v.currentTime,"
            " файл:(v.currentSrc||'').split('/').pop()} : {есть:0}; })()")
        print("РОЛИК В ПРОВОДНИКЕ:", видно)
        закрыть = await page.query_selector("#player-close")
        if закрыть:
            await закрыть.click()
            await пауза(900)

        # --- 7. Прогресс: график веса.
        отметить("вес")
        await вкладка("progress", 1600)
        await к("#chart-box", 1500, "center")
        await пауза(1900)

        # --- 8. Женский календарь — то, ради чего всё и затевалось.
        отметить("календарь")
        await к("#cycle-card", 1500, "center")
        await пауза(4400)

        # --- 9. Мой мир.
        отметить("мир")
        await вкладка("world", 1700)
        await к("#world-zones", 1500, "center")
        await пауза(2000)

        отметить("КОНЕЦ")
        await пауза(400)
        путь = await page.video.path()
        await контекст.close()
        await браузер.close()

        (СБОРКА / "marks.txt").write_text(
            "\n".join(f"{имя}\t{t:.2f}" for имя, t in метки), encoding="utf-8")
        (СБОРКА / "raw_path").write_text(путь)
        print("файл:", путь)
        return проверить(путь, метки)


def проверить(путь, метки):
    """Цела ли запись. Сбой захвата плавающий — глазами его не подстеречь.

    Примета поломки: страница нарисована в четверть буфера, вокруг —
    ровное серое (128,128,128). Такого цвета в тёмной палитре проекта нет
    нигде, поэтому его доля и есть мера.
    """
    import subprocess
    from PIL import Image
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    нуль = dict(метки)["НАЧАЛО"]
    беды = []
    for сдвиг in (5, 15, 25, 35):
        кадр = СБОРКА / f"_check_{сдвиг}.png"
        subprocess.run([ff, "-v", "error", "-ss", str(нуль + сдвиг), "-i", путь,
                        "-frames:v", "1", "-y", str(кадр)], check=True)
        im = Image.open(кадр).convert("RGB")
        п = im.load()
        шаг = 20
        точки = [(x, y) for y in range(0, im.size[1], шаг)
                 for x in range(0, im.size[0], шаг)]
        серых = sum(1 for x, y in точки
                    if all(abs(п[x, y][i] - 128) < 6 for i in range(3)))
        доля = 100 * серых // len(точки)
        кадр.unlink(missing_ok=True)
        print(f"  проверка на {сдвиг:2} с: размер {im.size}, серого {доля}%")
        if доля > 5:
            беды.append(сдвиг)
    if беды:
        print("ЗАПИСЬ ИСПОРЧЕНА — серое поле на секундах:", беды)
        return False
    print("Запись цела.")
    return True

if __name__ == "__main__":
    # Проверку сторожа гоняют импортом этого файла — тогда съёмка
    # начинаться не должна.
    if not asyncio.run(main()):
        sys.exit(1)
