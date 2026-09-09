"""Тренер: готовые ролики персонажа.

Персонажа приложение не рисует и не собирает. Ролики сняты заранее и
ставятся как есть — без ускорения, фильтров и оверлеев.

Всё, что здесь заперто, ломается молча. Опечатка в коде упражнения, файл,
не доехавший до сервера, обрезанная картинка, случайно оставленный ассет
из прошлого пакета — ни одно из этого не бросает ошибку: человек просто
открывает окно и видит пустое место или чужую графику. Узнали бы мы об
этом от Лилии, а не от кода.
"""

import json
import re
import struct
from pathlib import Path

from seed.exercise_ids import EXERCISE_IDS, id_for
from seed.workout_programs import PROGRAMS

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "webapp" / "static"
TRAINER = STATIC / "trainer"
APP_JS = (STATIC / "app.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
STYLES = (STATIC / "styles.css").read_text(encoding="utf-8")
PACK = json.loads((TRAINER / "manifest.json").read_text(encoding="utf-8"))
ASSETS = PACK["assets"]


def component() -> str:
    """Тело компонента показа — до его закрывающей скобки."""
    return APP_JS.split("function ExerciseTrainerAnimation(", 1)[1].split("\n}", 1)[0]


def mp4_facts(path: Path) -> dict:
    """Разбор MP4 без ffmpeg: длительность, размер, число кадров, дорожки.

    Нужен не для красоты: обрезанный или пустой ролик открывается в
    браузере молча — показывается заставка, и всё выглядит «просто не
    запустилось».
    """
    data = path.read_bytes()

    def boxes(start, end):
        i = start
        while i + 8 <= end:
            size = struct.unpack(">I", data[i:i + 4])[0]
            tag = data[i + 4:i + 8].decode("latin1")
            if size == 0:
                size = end - i
            if size < 8:
                return
            yield tag, i + 8, i + size
            i += size

    def walk(start, end):
        for tag, opened, closed in boxes(start, end):
            yield tag, opened, closed
            if tag in ("moov", "trak", "mdia", "minf", "stbl"):
                yield from walk(opened, closed)

    facts = {"tracks": [], "sizes": [], "truncated": []}
    # Обрезанный ролик: коробка объявляет больше байт, чем есть в файле.
    for tag, opened, closed in boxes(0, len(data)):
        if closed > len(data):
            facts["truncated"].append(tag)
        if tag == "mdat":
            facts["mdat"] = closed - opened
    for tag, opened, _ in walk(0, len(data)):
        if tag == "mvhd":
            scale, length = struct.unpack(">II", data[opened + 12:opened + 20])
            facts["seconds"] = round(length / scale, 2)
        elif tag == "tkhd":
            width = struct.unpack(">I", data[opened + 76:opened + 80])[0] >> 16
            height = struct.unpack(">I", data[opened + 80:opened + 84])[0] >> 16
            if width:
                facts["size"] = (width, height)
        elif tag == "stsz":
            uniform, count = struct.unpack(">II", data[opened + 4:opened + 12])
            facts["frames"] = count
            facts["sizes"] = ([uniform] * count if uniform else list(
                struct.unpack(f">{count}I", data[opened + 12:opened + 12 + count * 4])))
        elif tag == "hdlr":
            facts["tracks"].append(data[opened + 8:opened + 12].decode("latin1"))
    return facts


# --- постоянный код упражнения --------------------------------------------


def test_every_exercise_has_a_permanent_code():
    """Название — русская строка, и связывать по ней файлы нельзя.

    Числовой `id` из базы тоже не подходит: он выдаётся при заливке и на
    другом сервере будет другим.
    """
    names = {item[0] for program in PROGRAMS.values() for item in program["exercises"]}
    assert names == set(EXERCISE_IDS)


def test_two_exercises_never_share_one_code():
    """Один код на двоих — это один ролик на два разных движения."""
    assert len(set(EXERCISE_IDS.values())) == len(EXERCISE_IDS)


def test_the_code_is_written_out_and_not_derived_from_the_name():
    """Транслитерация даёт разные строки на разных версиях библиотеки."""
    for name, code in EXERCISE_IDS.items():
        assert re.fullmatch(r"[a-z][a-z0-9_]*", code), (name, code)


def test_one_exercise_in_several_programs_keeps_one_code():
    """Планка стоит в трёх программах, и показ у неё один."""
    assert id_for("Планка на локтях") == "forearm_plank"
    places = [item[0] for program in PROGRAMS.values()
              for item in program["exercises"] if item[0] == "Планка на локтях"]
    assert len(places) == 3, places


# --- пакет ------------------------------------------------------------------


def test_the_manifest_names_exercises_that_exist():
    """Опечатка в коде — ролик не найдётся никогда и молча."""
    unknown = {item["exerciseId"] for item in ASSETS} - set(EXERCISE_IDS.values())
    assert not unknown, unknown


def test_every_file_named_in_the_manifest_is_on_disk():
    for item in ASSETS:
        for key in ("src", "poster"):
            assert (TRAINER / item[key]).exists(), (item["exerciseId"], item[key])


def test_every_picture_opens_to_the_last_byte():
    """Обрезанный файл — это не «нет картинки», а половина картинки.

    В прошлом пакете таких было два, и браузер про это молчал: показывал,
    сколько успел прочитать. Поэтому файлы открываются здесь целиком.
    """
    from PIL import Image

    broken = []
    for path in sorted(TRAINER.rglob("*.png")):
        try:
            picture = Image.open(path)
            picture.load()
        except Exception as trouble:      # noqa: BLE001 — важно любое
            broken.append((path.name, type(trouble).__name__))
    assert not broken, broken


def test_no_video_is_cut_short():
    """Обрезанный ролик браузер не показывает и не ругается.

    Остаётся заставка, и выглядит это как «просто не запустилось» — а
    причина в том, что половина файла не доехала. Декодера в этой сессии
    нет, поэтому целостность проверяется по самому файлу: ни одна коробка
    не должна обещать больше байт, чем в нём есть, а кадры обязаны
    умещаться в отведённые им данные.
    """
    for item in ASSETS:
        if item["format"] != "mp4":
            continue
        path = TRAINER / item["src"]
        facts = mp4_facts(path)
        assert not facts["truncated"], (item["exerciseId"], facts["truncated"])
        assert sum(facts["sizes"]) <= facts["mdat"], item["exerciseId"]
        assert sum(facts["sizes"]) > 0, item["exerciseId"]


def test_every_video_is_whole_and_silent():
    """Ролик обязан быть целым, квадратным и без звука.

    Пустой или обрезанный MP4 в браузере не ругается: остаётся заставка, и
    выглядит это как «просто не запустилось». Звук в мини-приложении
    недопустим: человек открывает технику посреди дня, часто при людях.
    """
    for item in ASSETS:
        if item["format"] != "mp4":
            continue
        facts = mp4_facts(TRAINER / item["src"])
        assert facts.get("size") == (960, 960), (item["exerciseId"], facts.get("size"))
        assert facts.get("frames", 0) > 100, (item["exerciseId"], facts.get("frames"))
        assert facts["tracks"] == ["vide"], (item["exerciseId"], facts["tracks"])


def test_nothing_is_left_from_the_previous_pack():
    """Старые спрайты и animated WebP использовать нельзя.

    Два пакета в одной папке — это два персонажа на вид: тот, что в
    ролике, и тот, что в спрайте. Заодно они молча занимают место.
    """
    leftovers = sorted(p.name for p in TRAINER.rglob("*.webp"))
    assert not leftovers, leftovers
    assert not (TRAINER / "frames").exists()
    assert ".webp" not in component()


# --- как это подключено ----------------------------------------------------


def test_the_asset_is_found_by_code_and_never_by_name():
    """По русскому названию файлы не ищутся никогда."""
    body = APP_JS.split("function trainerFor(", 1)[1].split("\n}", 1)[0]
    assert "item.exerciseId === exerciseId" in body
    assert "titleRu" not in body


def test_only_the_asset_of_this_exercise_is_shown():
    """Показ собирается по одной записи манифеста, а не «по похожему».

    Ошибка здесь означала бы, что человек учится не тому упражнению,
    которое открыл, — и заметить это некому.
    """
    body = component()
    assert "const item = trainerFor(exerciseId);" in body
    assert "if (!item) return false;" in body
    assert "trainerUrl(item.src)" in body


# --- блоки складываются, а не заменяют друг друга --------------------------

# Что именно принёс каждый блок. Список закрыт нарочно: слияние манифестов
# делается скриптом, а скрипт легко написать так, что он затрёт всё
# прежнее — и заметить это будет некому, потому что новый блок при этом
# работает прекрасно.
BLOCK_01 = {
    "bodyweight_squat": "anim_squat_bodyweight",
    "knee_pushup": "anim_pushup_knee",
    "glute_bridge": "anim_glute_bridge",
    "bottle_bent_over_row": "anim_bent_over_row",
    "forearm_plank": "anim_plank_forearm",
    "lying_leg_raise": "anim_leg_raise_lying",
}
BLOCK_02 = {
    "plie_squat": "anim_plie_squat",
    "standard_pushup": "anim_pushup_standard",
    "alternating_reverse_lunge": "anim_reverse_lunge_alternating",
    "single_leg_glute_bridge": "anim_glute_bridge_single_leg",
    "superman_raise": "anim_superman_raise",
    "plank_arm_raise": "anim_plank_arm_raise",
    "bicycle_crunch": "anim_bicycle_crunch",
}


def test_the_first_block_survives_every_later_one():
    """Новый блок добавляется к прежним, а не встаёт на их место."""
    have = {item["exerciseId"]: item["animationAssetId"] for item in ASSETS}
    for code, asset in BLOCK_01.items():
        assert have.get(code) == asset, (code, have.get(code))


def test_the_second_block_is_installed_whole():
    """Семь упражнений «Дом · Средний» — все, а не сколько доехало."""
    have = {item["exerciseId"]: item["animationAssetId"] for item in ASSETS}
    for code, asset in BLOCK_02.items():
        assert have.get(code) == asset, (code, have.get(code))


def test_the_superman_is_the_corrected_half_version():
    """Пятое упражнение блока 02 присылали дважды.

    В первой версии персонаж отрывал от пола и ноги, и таз — это уже не то
    упражнение. В исправленной ноги и таз лежат, поднимаются грудная
    клетка и прямые руки. Проверено глазами по заставке и по контрольному
    листу кадров: декодера H.264 в этой сессии нет, и автоматически
    отличить одно от другого нечем. Здесь заперто то, что проверяется, —
    что стоит именно файл из исправленного пакета и что заставка к нему
    своя.
    """
    superman = next(item for item in ASSETS if item["exerciseId"] == "superman_raise")
    assert superman["src"] == "animations/anim_superman_raise.mp4"
    assert superman["poster"] == "posters/anim_superman_raise.png"
    assert (TRAINER / superman["src"]).exists()
    assert (TRAINER / superman["poster"]).exists()
    assert "AURA_block_02_home_intermediate_v2" in PACK["packages"]


def test_the_manifest_remembers_which_packages_it_is_made_of():
    """Иначе после третьего блока никто не скажет, что откуда взялось."""
    assert PACK["packages"] == ["AURA_block_01_home_beginner_v2",
                                "AURA_block_02_home_intermediate_v2"]
    assert len(ASSETS) == len(BLOCK_01) + len(BLOCK_02)


def test_no_two_exercises_point_at_the_same_file():
    """Один файл на два упражнения — это человек, который учится не тому.

    Ошибка тихая: показ есть, персонаж свой, движение красивое — просто не
    то, что открыли. Поймано тем, что подменили путь одному упражнению на
    файл соседнего, и ни одна проверка не сработала.
    """
    for key in ("animationAssetId", "src", "poster"):
        seen = {}
        for item in ASSETS:
            # Планка показывает заставкой саму себя: у неё src и poster
            # совпадают намеренно, и это единственное такое место.
            seen.setdefault(item[key], []).append(item["exerciseId"])
        doubled = {value: who for value, who in seen.items() if len(who) > 1}
        assert not doubled, (key, doubled)


def test_the_file_name_matches_the_asset_it_claims_to_be():
    """Путь и animationAssetId обязаны говорить об одном и том же.

    Разойтись им ничего не мешает: и то и другое — строки в манифесте.
    """
    for item in ASSETS:
        stem = item["src"].split("/")[-1].rsplit(".", 1)[0]
        assert stem == item["animationAssetId"], (item["exerciseId"], stem)


def test_the_paths_are_built_in_one_place():
    """Папку ассетов меняют правкой одной строки, а не в каждой карточке."""
    assert "const trainerUrl = (path) => TRAINER_ROOT + path;" in APP_JS
    body = component()
    assert "'/static/" not in body and '"/static/' not in body


def test_the_server_sends_the_code_with_every_exercise():
    api = (ROOT / "webapp" / "api.py").read_text(encoding="utf-8")
    assert '"exercise_id": id_for(workout.name),' in api
    assert "exercise_id: item.exercise_id || null," in APP_JS


def test_the_video_plays_by_itself_without_sound():
    """Автозапуск без звука — единственный, который телефон разрешает.

    Без `muted` и `playsinline` iPhone либо не запустит ролик вовсе, либо
    развернёт его на весь экран поверх приложения.
    """
    body = component()
    for line in ("video.autoplay = true;", "video.muted = true;",
                 "video.playsInline = true;", "video.preload = 'metadata';",
                 "video.poster = poster;"):
        assert line in body, line
    assert "setAttribute('playsinline', '')" in body
    assert "source.type = 'video/mp4';" in body


def test_the_video_is_not_sped_up_or_repainted():
    """Скорость и вид ролика не трогаем: он показывается таким, каким снят."""
    body = component()
    for forbidden in ("playbackRate", "filter", "transform", "opacity"):
        assert forbidden not in body, forbidden
    rule = STYLES.split(".exercise-technique-media {", 1)[1].split("}", 1)[0]
    assert "filter" not in rule and "transform" not in rule
    assert "object-fit: contain" in rule
    assert "aspect-ratio: 1 / 1" in rule
    # Фон — цвет сцены из манифеста, иначе поля по краям выглядят дырой.
    assert PACK["backgroundColor"].lower() in rule.lower()


def test_the_video_stops_when_the_window_closes():
    """За кадром ролик крутился бы дальше и жёг батарею.

    А вернувшись, человек застал бы движение с середины — при следующем
    открытии показ собирается заново, то есть всегда с нулевой секунды.
    """
    assert "pauseTrainer(document.getElementById('how-figure'));" in APP_JS
    body = APP_JS.split("function pauseTrainer(", 1)[1].split("\n}", 1)[0]
    assert "video.pause()" in body
    assert "box.innerHTML = '';" in component()


def test_with_motion_switched_off_only_the_poster_is_shown():
    """Человеку с чувствительностью к движению ролик не запускаем вовсе."""
    body = component()
    assert "const still = !motion() || item.format !== 'mp4';" in body
    assert "shot.src = motion() ? trainerUrl(item.src) : poster;" in body


def test_the_plank_is_a_still_pose_and_the_picture_is_untouched():
    """Планка — удержание: двигаться в ней нечему.

    Живым кадр делает только очень слабое дыхание свечения самого
    контейнера. Изображение при этом не трогается: ни масштаба, ни фильтра.
    И это дыхание выключается системной настройкой, как всё остальное.
    """
    plank = next(item for item in ASSETS if item["exerciseId"] == "forearm_plank")
    assert plank["format"] == "png" and plank["animationType"] == "hold"
    assert plank["src"] == "static/anim_plank_forearm.png"
    # Класс вешает тот, кто владеет контейнером: свечение живёт на рамке
    # окна, а не на слоте с картинкой — из слота его срезало бы overflow.
    assert "function trainerIsHold(" in APP_JS
    assert APP_JS.count("classList.toggle('trainer-hold', moving && trainerIsHold(") == 2

    motion_block = STYLES.split("Движение\n", 1)[1]
    allowed = motion_block.split("@media (prefers-reduced-motion: no-preference)", 1)[1]
    assert ".how-demo.trainer-hold { animation: hold-breath 4.8s" in allowed
    breath = STYLES.split("@keyframes hold-breath {", 1)[1].split("}", 2)
    assert "box-shadow" in breath[0] + breath[1]
    assert "transform" not in breath[0] + breath[1]


def test_without_an_asset_nothing_else_is_put_in_its_place():
    """Прежний рисованный персонаж убран из интерфейса.

    Две разные графики в одном экране — это два разных приложения на вид.
    Код старого персонажа оставлен намеренно, а вот вызовов из интерфейса
    быть не должно.
    """
    assert APP_JS.count("showMove(") == 1, "показ рисованной фигуры снова вызывается"
    assert "Анимация техники готовится" in INDEX


def test_the_heavy_file_starts_loading_before_the_window_opens():
    """Ролик весит два с половиной мегабайта."""
    assert "link.onpointerdown = () => preloadTrainer(exercise.exercise_id);" in APP_JS
    rest = APP_JS.split("} else if (phase === 'rest') {", 1)[1].split("\n  }", 1)[0]
    assert "preloadTrainer(next.exercise_id)" in rest
