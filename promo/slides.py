"""Слайды для знакомства: цветные карточки, которые бот шлёт в чат.

Зачем. Анкета — девять вопросов подряд, и человек не видит, ради чего
отвечает: до приложения он ещё не дошёл, а на экране только «укажи рост».
Отваливаются именно здесь. Слайд показывает, что дальше, — и делает это
картинкой, потому что ещё одну простыню текста в этом месте не читают.

Почему картинки лежат готовыми, а не рисуются на сервере. Рисует их
браузер — тем же шрифтом и той же палитрой, что и приложение, — а на
сервере браузера нет и быть не должно. Поэтому здесь они отрисовываются
один раз и кладутся в `media/slides/` прямо в репозиторий: это часть
интерфейса, как фигура тела на «Прогрессе».

    python promo/slides.py
"""
import asyncio, base64, pathlib, sys

ЗДЕСЬ = pathlib.Path(__file__).resolve().parent
КОРЕНЬ = ЗДЕСЬ.parent
ВЫХОД = КОРЕНЬ / "media" / "slides"
ПОРТРЕТ = КОРЕНЬ / "webapp" / "static" / "trainer" / "static" / "eye_guide_character.png"

# Квадрат. На 4:5 внизу оставалась пустая треть: содержимого столько нет,
# а растягивать текст ради заполнения — это верстать под холст, а не под
# смысл. Квадрат Telegram показывает на телефоне целиком.
Ш, В = 1080, 1080

ОБЩЕЕ = """
  @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700&family=Playfair+Display:ital,wght@0,500;0,600;1,500&display=swap');
  :root {
    --void:#0A0912; --surface:#151327; --violet:#8B5CF6; --lilac:#C4B5FD;
    --teal:#2DD4BF; --gold:#C9A961; --ink:#F4F1FF; --muted:#A79CC9;
  }
  * { box-sizing:border-box; margin:0; }
  html, body { width:%(w)dpx; height:%(h)dpx; }
  body {
    background:var(--void); color:var(--ink); font-family:'Manrope',sans-serif;
    padding:70px 72px; display:flex; flex-direction:column; overflow:hidden;
    justify-content:space-between;
    position:relative;
  }
  body::before {
    content:''; position:absolute; inset:-25%% -25%% auto -25%%; height:72%%;
    background:radial-gradient(ellipse at 50%% 0%%, rgba(139,92,246,.42), transparent 68%%);
    pointer-events:none;
  }
  .eyebrow {
    font-size:23px; font-weight:600; letter-spacing:.26em; text-transform:uppercase;
    color:var(--gold); margin-bottom:22px;
  }
  h1 {
    font-family:'Playfair Display',serif; font-weight:500; font-size:74px;
    line-height:1.1; letter-spacing:-.01em;
  }
  .lead { font-size:31px; line-height:1.45; color:var(--muted); margin-top:26px; }
  .spacer { flex:1; }
  .foot { font-size:25px; color:var(--muted); letter-spacing:.01em; }
  .card {
    background:var(--surface); border:1px solid rgba(196,181,253,.13);
    border-radius:26px; padding:28px 32px; display:flex; gap:26px; align-items:center;
  }
  .card .ico { width:46px; height:46px; flex:0 0 46px; }
  .card .ico svg { width:46px; height:46px; display:block; }
  .card .txt { font-size:29px; line-height:1.34; }
  .card .txt b { font-weight:700; }
  .card .txt span { color:var(--muted); display:block; font-size:25px; margin-top:5px; }
  .stack { display:flex; flex-direction:column; gap:20px; margin-top:52px; }
  .cmd { display:flex; gap:24px; align-items:baseline; font-size:30px; }
  .cmd code {
    font-family:'Manrope',sans-serif; font-weight:700; color:var(--lilac);
    min-width:210px;
  }
  .cmd span { color:var(--muted); font-size:27px; }
"""


def страница(стиль: str, тело: str) -> str:
    return (f"<!doctype html><html lang='ru'><head><meta charset='utf-8'><style>"
            f"{ОБЩЕЕ % {'w': Ш, 'h': В}}{стиль}</style></head><body>{тело}</body></html>")


def портрет_кодом() -> str:
    """Портрет Аи — тот же, что стоит фоном в гимнастике для глаз.

    Вшивается прямо в страницу: браузер снимает её из памяти, и никакого
    файла рядом класть не надо.
    """
    return "data:image/png;base64," + base64.b64encode(ПОРТРЕТ.read_bytes()).decode()


# Значки рисуются сами, тонкой линией в цветах палитры: системная эмодзи
# рядом с Playfair выглядит чужой наклейкой, а правило дизайн-системы
# прямо говорит «мало эмодзи, аккуратные иконки».
ЗНАЧКИ = {
    "еда": ('<svg viewBox="0 0 48 48" fill="none" stroke="#C4B5FD" stroke-width="2.2"'
            ' stroke-linecap="round" stroke-linejoin="round">'
            '<circle cx="24" cy="24" r="14"/><circle cx="24" cy="24" r="6.5"/>'
            '<path d="M24 4v4M24 40v4M4 24h4M40 24h4"/></svg>'),
    "движение": ('<svg viewBox="0 0 48 48" fill="none" stroke="#2DD4BF" stroke-width="2.2"'
                 ' stroke-linecap="round" stroke-linejoin="round">'
                 '<circle cx="27" cy="9" r="4.5"/>'
                 '<path d="M14 42l7-12 7 5 3-11"/><path d="M21 30l-4-9 10-4 7 7 6 2"/>'
                 '<path d="M31 24l5 14"/></svg>'),
    "прогресс": ('<svg viewBox="0 0 48 48" fill="none" stroke="#C9A961" stroke-width="2.2"'
                 ' stroke-linecap="round" stroke-linejoin="round">'
                 '<path d="M6 34l10-11 8 6 14-17"/><path d="M30 12h8v8"/>'
                 '<path d="M6 42h36"/></svg>'),
}


def слайды() -> list[tuple[str, str, str]]:
    """(имя файла, добавка к стилю, разметка). Порядок — порядок показа."""
    портрет = портрет_кодом()
    return [
        # 1. Сразу после согласия: ради чего вообще отвечать на девять вопросов.
        ("what_is_inside", """
  .top { display:flex; align-items:flex-start; justify-content:space-between; gap:40px; }
  .top h1 { font-size:66px; }
  .face {
    flex:0 0 190px; width:190px; height:190px; border-radius:50%; object-fit:cover;
    object-position:50% 22%; border:2px solid rgba(196,181,253,.28);
    box-shadow:0 0 60px rgba(139,92,246,.45);
  }
  .stack { margin-top:0; }
""", f"""
  <div>
    <div class="eyebrow">AURA</div>
    <div class="top">
      <h1>Питание, движение<br>и тело — в одном месте</h1>
      <img class="face" src="{портрет}" alt="">
    </div>
  </div>
  <div class="stack">
    <div class="card"><div class="ico">{ЗНАЧКИ['еда']}</div><div class="txt">
      <b>Еда без подсчётов</b><span>Сфотографируй, надиктуй или напиши — посчитает сама</span></div></div>
    <div class="card"><div class="ico">{ЗНАЧКИ['движение']}</div><div class="txt">
      <b>17 программ, 103 упражнения</b><span>Тело, лицо, глаза, осанка — каждое движение показано</span></div></div>
    <div class="card"><div class="ico">{ЗНАЧКИ['прогресс']}</div><div class="txt">
      <b>Вес, объёмы и женский календарь</b><span>Видно тело, а не одну цифру на весах</span></div></div>
  </div>
  <div class="foot">Дальше — несколько вопросов о тебе. Это пара минут.</div>
"""),
        # 2. Середина анкеты: человек не понимает, зачем его допрашивают.
        ("why_questions", """
  h1 { font-size:76px; }
  .big {
    font-family:'Playfair Display',serif; font-style:italic; font-weight:500;
    font-size:46px; line-height:1.28; color:var(--lilac);
  }
  .rule { width:150px; height:2px; background:var(--gold); opacity:.7; margin:44px 0; }
""", """
  <div>
    <div class="eyebrow">Ещё немного</div>
    <h1>Почему<br>столько вопросов</h1>
  </div>
  <div>
    <div class="rule"></div>
    <p class="lead">Норма калорий у всех разная. Она зависит от роста, веса,
       возраста и от того, сколько ты двигаешься за день.</p>
    <div class="rule"></div>
    <p class="big">Считаем твою норму,<br>а не среднюю по таблице.</p>
  </div>
  <div class="foot">Ответы можно поменять в любой момент — в профиле.</div>
"""),
        # 3. После анкеты: приложение — не единственный вход, и об этом
        #    иначе не узнают. Команды лежат за синей кнопкой, куда не смотрят.
        ("in_chat_too", """
  h1 { font-size:62px; }
  .stack { gap:24px; }
""", """
  <div>
    <div class="eyebrow">Без приложения тоже</div>
    <h1>Главное работает<br>прямо здесь, в чате</h1>
    <p class="lead">Не хочешь открывать приложение — не открывай.
       Эти команды делают то же самое:</p>
  </div>
  <div class="stack">
    <div class="cmd"><code>/day</code><span>что я сегодня ела</span></div>
    <div class="cmd"><code>/steps</code><span>записать шаги за сегодня</span></div>
    <div class="cmd"><code>/sync</code><span>чтобы шаги приходили сами</span></div>
    <div class="cmd"><code>/preps</code><span>заготовки и сроки хранения</span></div>
    <div class="cmd"><code>/problem</code><span>что-то не так — расскажи мне</span></div>
  </div>
  <div class="foot">Весь список — синяя кнопка слева от поля ввода.</div>
"""),
    ]


async def main() -> None:
    ВЫХОД.mkdir(parents=True, exist_ok=True)
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        b = await pw.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        page = await b.new_page(viewport={"width": Ш, "height": В},
                                device_scale_factor=1)
        for имя, стиль, тело in слайды():
            await page.set_content(страница(стиль, тело))
            await page.wait_for_timeout(900)      # дать шрифтам доехать
            проверка = "document.fonts.check('500 74px \"Playfair Display\"')"
            есть = await page.evaluate(проверка)
            файл = ВЫХОД / f"{имя}.png"
            await page.screenshot(path=str(файл))
            print(f"  {имя:16} {файл.stat().st_size // 1024:4} КБ, "
                  f"Playfair загружен: {есть}")
        await b.close()


if __name__ == "__main__":
    asyncio.run(main())
