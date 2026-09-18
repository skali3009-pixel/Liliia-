# AURA — что установлено на самом деле

Проверено 13 сентября 2026 года по коду, манифесту и файлам на диске, а не
по инструкциям из присланных архивов. Ничего не менялось: это только опись.

> **14 сентября 2026. Опись устарела.** Установлен восстановительный пакет
> `AURA_recovery_missing_assets_v1`: четыре ролика закрыли «Зал · Новичок»
> (6 из 6) и пять показов закрыли пять упражнений из семи в «Гимнастике
> для глаз». Стало 101 соответствие из 103, шестнадцать программ из
> семнадцати готовы целиком, без показа остались только «Частое моргание»
> и «Пальминг». Всё, что ниже, описывает состояние до этого пакета.

## Откуда взяты числа

- Программы и состав — `seed/workout_programs.py`
- Постоянные коды упражнений — `seed/exercise_ids.py`
- Привязка ролика к упражнению — `webapp/static/trainer/manifest.json`
- Файлы — `webapp/static/trainer/animations/`, `posters/`, `static/`
- Целостность каждого файла проверена отдельно: у роликов разобраны коробки
  MP4 (ни одна не обещает больше байт, чем в файле), картинки открыты до
  последнего байта

## Короткий итог

| Что считали | Сколько |
|---|---|
| Программ тренировок | 17 |
| Строк упражнений во всех программах | 114 |
| Разных названий упражнений | 103 |
| Записей в манифесте | 92 |
| Из них своих | 84 |
| Из них переиспользующих чужой ассет | 8 |
| Разных файлов показа | 84 (81 MP4 + 3 кадра PNG) |
| Файлов в папке `trainer` всего | 165 (172 МБ) |
| Упражнений без показа | 11 |
| Ссылок на отсутствующие файлы | 0 |
| Файлов, которые нигде не используются | 0 |
| Одинаковых файлов под разными именами | 0 |
| Упражнений без текста техники | 0 |
| Битых или обрезанных файлов | 0 |

Установлено пятнадцать пакетов:

`AURA_block_01_home_beginner_v2`, `AURA_block_02_home_intermediate_v2`,
`AURA_corrections_blocks_01-03_v3_compact`,
`AURA_block_04_gym_intermediate_v2_compact`,
`AURA_block_05_cardio_home_v1_compact`, `AURA_block_06_bands_v1_compact`,
`AURA_block_07_yoga_v1_compact`, `AURA_block_08_stretching_v1_compact`,
`AURA_block_09_pilates_v1_compact`, `AURA_block_10_posture_neck_hump_v1`,
`AURA_block_11_dance_warmup_v1_compact`,
`AURA_block_12_face_yoga_v1_compact`,
`AURA_block_13_face_self_massage_v1_compact`,
`AURA_block_15_double_chin_v1_compact`,
`AURA_block_16_pelvic_floor_breathing_v1_compact`.

Блок 03 «Зал · Новичок» не присылали вовсе. От него доехало одно
упражнение — жим ногами, внутри корректирующего пакета.

## Покрытие по программам

| Программа | Направление | Упражнений | С показом | Готова |
|---|---|---|---|---|
| Дом · Новичок | Тело | 6 | 6 | да |
| Дом · Средний | Тело | 7 | 7 | да |
| Зал · Новичок | Тело | 6 | 2 | **нет** |
| Зал · Средний | Тело | 7 | 7 | да |
| Кардио дома | Тело | 6 | 6 | да |
| Резинки | Тело | 7 | 7 | да |
| Йога | Спокойное | 7 | 7 | да |
| Стретчинг | Спокойное | 7 | 7 | да |
| Пилатес | Спокойное | 7 | 7 | да |
| Фейс-йога | Лицо | 7 | 7 | да |
| Самомассаж лица | Лицо | 7 | 7 | да |
| Второй подбородок | Лицо | 6 | 6 | да |
| Гимнастика для глаз | Глаза | 7 | 0 | **нет** |
| Осанка | Осанка | 7 | 7 | да |
| Холка | Осанка | 7 | 7 | да |
| Танцевальная разминка | Танцы | 7 | 7 | да |
| Мышцы тазового дна | Женское | 6 | 6 | да |

## Ответы на два отдельных вопроса

### Блок «Осанка и холка» (пакет 10)

Установлен полностью. В проекте это две программы, а не одна: «Осанка»
(7 упражнений) и «Холка» (7 упражнений), три упражнения у них общие.
Показ есть у всех четырнадцати строк.

**Ассета `anim_chin_tuck_wall` в проекте нет — и не должно быть.** Это имя
из архива блока 15: там лежала резервная копия уже снятого ролика. В
проекте тот же файл стоит под именем **`anim_wall_chin_tuck`** (пришёл с
блоком 10) и работает. Сверено по SHA-256: резервная копия была байт в
байт тем же файлом, поэтому её не копировали — иначе один ролик лежал бы
в двух экземплярах под разными именами. Стоит тест, который падает, если
`anim_chin_tuck_wall` когда-нибудь появится.

Отдельно: «Втягивание подбородка (chin tuck)» из «Осанки» и «Втягивание
подбородка у стены» из «Холки» — **разные упражнения**, у них разные коды
(`chin_tuck` и `wall_chin_tuck`) и разные файлы.

### «Втягивание подбородка у стены» во «Втором подбородке»

**Работает.** Код упражнения `wall_chin_tuck`, ассет `anim_wall_chin_tuck`,
файл `animations/anim_wall_chin_tuck.mp4` на диске есть и цел, заставка
`posters/anim_wall_chin_tuck.jpg` тоже. То же упражнение стоит в «Холке» и
показывает тот же ролик — это одна строка в манифесте на один код, а не
два экземпляра файла.

## Ссылки, файлы и дубли

- **Ссылок на отсутствующие файлы нет.** Все 92 записи манифеста указывают
  на существующие файлы: 89 роликов и 3 кадра, у 91 записи есть заставка.
  Единственная запись без поля `poster` — планка на локтях: у неё показ и
  есть сам кадр, и код берёт его же.
- **Лишних файлов нет.** Каждый из 165 файлов папки назван в манифесте.
- **Одинаковых файлов под разными именами нет.** Сверено по SHA-256 всё
  содержимое обеих папок.
- **Один ассет на несколько упражнений — восемь случаев, все заявленные**
  (поле `reusedFrom`, хозяин существует):

| Ассет | Хозяин | Кто ещё показывает |
|---|---|---|
| `anim_doorway_chest_stretch` | `doorway_chest_stretch` (Стретчинг) | `doorway_chest_opener` (Осанка), `doorway_pec_stretch` (Холка) |
| `anim_neck_side_tilt` | `neck_side_tilt` (Стретчинг) | `assisted_neck_tilt` (Холка) |
| `anim_backward_shoulder_circles` | `backward_shoulder_circles` (Холка) | `shoulder_circles_chest_open` (Танцевальная разминка) |
| `anim_glute_bridge` | `glute_bridge` (Дом · Новичок) | `glute_bridge_with_breath` (Тазовое дно) |
| `anim_child_pose` | `child_pose` (Йога) | `child_pose_breathing` (Тазовое дно) |
| `anim_diaphragmatic_breathing` | `supine_diaphragmatic_breathing` (Тазовое дно) | `full_pelvic_release`, `quick_pelvic_squeeze` (Тазовое дно) |

- **Одинаковые названия в разных программах — девять, все законные**
  (одно упражнение стоит в нескольких программах и показывает один ролик,
  потому что код у него один): «Планка на локтях» (три программы),
  «Кошка-корова» (три), «Супермен лёжа» (две), «Стенка» (две),
  «Втягивание подбородка у стены» (две), «Вытягивание шеи вверх» (две),
  «Выдвижение челюсти с запрокинутой головой» (две), «Массаж по линии
  нижней челюсти» (две), «Отток по шее вниз к ключицам» (две).
- **Двух разных движений под одним названием нет.**

## Единственное расхождение подписи

У «Супермена лёжа» подпись в манифесте — «Половинный Супермен — подъём
корпуса и рук». Это не ошибка: название в каталоге ключ к технике, коду и
записям о тренировках, а подпись к ролику Лилия закрепила отдельно и
просила не трогать. Все остальные 91 подпись совпадают с каталогом
посимвольно.

## Таблица по каждому упражнению

| Блок | Название упражнения | ID упражнения | ID ассета | Файл | Тип | Новый / повторный | Файл есть | Привязка работает | Проблема |
|---|---|---|---|---|---|---|---|---|---|
| Дом · Новичок | Приседания с собственным весом | bodyweight_squat | anim_squat_bodyweight | anim_squat_bodyweight.mp4 | MP4 | свой | да | да | — |
| Дом · Новичок | Отжимания с колен | knee_pushup | anim_pushup_knee | anim_pushup_knee.mp4 | MP4 | свой | да | да | — |
| Дом · Новичок | Ягодичный мостик | glute_bridge | anim_glute_bridge | anim_glute_bridge.mp4 | MP4 | свой | да | да | — |
| Дом · Новичок | Тяга в наклоне с бутылками воды | bottle_bent_over_row | anim_bent_over_row | anim_bent_over_row.mp4 | MP4 | свой | да | да | — |
| Дом · Новичок | Планка на локтях | forearm_plank | anim_plank_forearm | anim_plank_forearm.png | PNG | свой | да | да | — |
| Дом · Новичок | Подъёмы ног лёжа | lying_leg_raise | anim_leg_raise_lying | anim_leg_raise_lying.mp4 | MP4 | свой | да | да | — |
| Дом · Средний | Приседания-плие | plie_squat | anim_plie_squat | anim_plie_squat.mp4 | MP4 | свой | да | да | — |
| Дом · Средний | Отжимания классические | standard_pushup | anim_pushup_standard | anim_pushup_standard.mp4 | MP4 | свой | да | да | — |
| Дом · Средний | Выпады назад поочерёдно | alternating_reverse_lunge | anim_reverse_lunge_alternating | anim_reverse_lunge_alternating.mp4 | MP4 | свой | да | да | — |
| Дом · Средний | Ягодичный мостик на одной ноге | single_leg_glute_bridge | anim_glute_bridge_single_leg | anim_glute_bridge_single_leg.mp4 | MP4 | свой | да | да | — |
| Дом · Средний | Супермен лёжа | superman_raise | anim_superman_raise | anim_superman_raise.mp4 | MP4 | свой | да | да | подпись в манифесте «Половинный Супермен — подъём корпуса и рук» (закреплено Лилией) |
| Дом · Средний | Планка с подъёмом руки | plank_arm_raise | anim_plank_arm_raise | anim_plank_arm_raise.mp4 | MP4 | свой | да | да | — |
| Дом · Средний | Скручивания «велосипед» | bicycle_crunch | anim_bicycle_crunch | anim_bicycle_crunch.mp4 | MP4 | свой | да | да | — |
| Зал · Новичок | Жим ногами в тренажёре | machine_leg_press | anim_machine_leg_press | anim_machine_leg_press.mp4 | MP4 | свой | да | да | — |
| Зал · Новичок | Тяга верхнего блока к груди | lat_pulldown | — | — | — | — | — | — | показа нет — ролик не присылали |
| Зал · Новичок | Жим в грудном тренажёре | machine_chest_press | — | — | — | — | — | — | показа нет — ролик не присылали |
| Зал · Новичок | Сгибание ног в тренажёре | machine_leg_curl | — | — | — | — | — | — | показа нет — ролик не присылали |
| Зал · Новичок | Гиперэкстензия | back_extension | — | — | — | — | — | — | показа нет — ролик не присылали |
| Зал · Новичок | Планка на локтях | forearm_plank | anim_plank_forearm | anim_plank_forearm.png | PNG | свой | да | да | — |
| Зал · Средний | Приседания со штангой | barbell_squat | anim_barbell_squat | anim_barbell_squat.mp4 | MP4 | свой | да | да | — |
| Зал · Средний | Румынская тяга с гантелями | dumbbell_romanian_deadlift | anim_dumbbell_romanian_deadlift | anim_dumbbell_romanian_deadlift.mp4 | MP4 | свой | да | да | — |
| Зал · Средний | Жим гантелей лёжа | dumbbell_bench_press | anim_dumbbell_bench_press | anim_dumbbell_bench_press.mp4 | MP4 | свой | да | да | — |
| Зал · Средний | Тяга гантели в наклоне | single_arm_dumbbell_row | anim_single_arm_dumbbell_row | anim_single_arm_dumbbell_row.mp4 | MP4 | свой | да | да | — |
| Зал · Средний | Выпады с гантелями | dumbbell_lunge | anim_dumbbell_lunge | anim_dumbbell_lunge.mp4 | MP4 | свой | да | да | — |
| Зал · Средний | Жим гантелей сидя | seated_dumbbell_shoulder_press | anim_seated_dumbbell_shoulder_press | anim_seated_dumbbell_shoulder_press.mp4 | MP4 | свой | да | да | — |
| Зал · Средний | Скручивания на скамье | bench_crunch | anim_bench_crunch | anim_bench_crunch.mp4 | MP4 | свой | да | да | — |
| Кардио дома | Джампинг-джек | jumping_jack | anim_jumping_jack | anim_jumping_jack.mp4 | MP4 | свой | да | да | — |
| Кардио дома | Бег на месте с высоким подниманием колен | high_knees_run | anim_high_knees_run | anim_high_knees_run.mp4 | MP4 | свой | да | да | — |
| Кардио дома | Скалолаз | mountain_climber | anim_mountain_climber | anim_mountain_climber.mp4 | MP4 | свой | да | да | — |
| Кардио дома | Прыжки из приседа | squat_jump | anim_squat_jump | anim_squat_jump.mp4 | MP4 | свой | да | да | — |
| Кардио дома | Выпады в прыжке | jump_lunge | anim_jump_lunge | anim_jump_lunge.mp4 | MP4 | свой | да | да | — |
| Кардио дома | Бёрпи | burpee | anim_burpee | anim_burpee.mp4 | MP4 | свой | да | да | — |
| Резинки | Приседания с резинкой над коленями | band_squat | anim_band_squat | anim_band_squat.mp4 | MP4 | свой | да | да | — |
| Резинки | Отведение ноги в сторону стоя | standing_hip_abduction | anim_standing_hip_abduction | anim_standing_hip_abduction.mp4 | MP4 | свой | да | да | — |
| Резинки | «Ракушка» лёжа на боку | side_lying_clamshell | anim_side_lying_clamshell | anim_side_lying_clamshell.mp4 | MP4 | свой | да | да | — |
| Резинки | Ягодичный мостик с резинкой | band_glute_bridge | anim_band_glute_bridge | anim_band_glute_bridge.mp4 | MP4 | свой | да | да | — |
| Резинки | Шаги в стороны с резинкой | band_lateral_walk | anim_band_lateral_walk | anim_band_lateral_walk.mp4 | MP4 | свой | да | да | — |
| Резинки | Тяга резинки к поясу сидя | seated_band_row | anim_seated_band_row | anim_seated_band_row.mp4 | MP4 | свой | да | да | — |
| Резинки | Разведение рук с резинкой | band_pull_apart | anim_band_pull_apart | anim_band_pull_apart.mp4 | MP4 | свой | да | да | — |
| Йога | Кошка-корова | cat_cow | anim_cat_cow | anim_cat_cow.mp4 | MP4 | свой | да | да | — |
| Йога | Собака мордой вниз | downward_dog | anim_downward_dog | anim_downward_dog.mp4 | MP4 | свой | да | да | — |
| Йога | Поза воина II | warrior_two | anim_warrior_two | anim_warrior_two.mp4 | MP4 | свой | да | да | — |
| Йога | Поза дерева | tree_pose | anim_tree_pose | anim_tree_pose.mp4 | MP4 | свой | да | да | — |
| Йога | Наклон вперёд стоя | standing_forward_fold | anim_standing_forward_fold | anim_standing_forward_fold.mp4 | MP4 | свой | да | да | — |
| Йога | Поза ребёнка | child_pose | anim_child_pose | anim_child_pose.mp4 | MP4 | свой | да | да | — |
| Йога | Шавасана | savasana | anim_savasana | anim_savasana.mp4 | MP4 | свой | да | да | — |
| Стретчинг | Наклон к прямым ногам сидя | seated_forward_bend | anim_seated_forward_bend | anim_seated_forward_bend.mp4 | MP4 | свой | да | да | — |
| Стретчинг | Растяжка квадрицепса стоя | standing_quad_stretch | anim_standing_quad_stretch | anim_standing_quad_stretch.mp4 | MP4 | свой | да | да | — |
| Стретчинг | Поза голубя | pigeon_pose | anim_pigeon_pose | anim_pigeon_pose.mp4 | MP4 | свой | да | да | — |
| Стретчинг | Растяжка груди в дверном проёме | doorway_chest_stretch | anim_doorway_chest_stretch | anim_doorway_chest_stretch.mp4 | MP4 | свой | да | да | — |
| Стретчинг | Скручивание лёжа | supine_spinal_twist | anim_supine_spinal_twist | anim_supine_spinal_twist.mp4 | MP4 | свой | да | да | — |
| Стретчинг | Наклоны головы к плечу | neck_side_tilt | anim_neck_side_tilt | anim_neck_side_tilt.mp4 | MP4 | свой | да | да | — |
| Стретчинг | Растяжка икр у стены | wall_calf_stretch | anim_wall_calf_stretch | anim_wall_calf_stretch.mp4 | MP4 | свой | да | да | — |
| Пилатес | Сотня (The Hundred) | pilates_hundred | anim_pilates_hundred | anim_pilates_hundred.mp4 | MP4 | свой | да | да | — |
| Пилатес | Роллап | pilates_roll_up | anim_pilates_roll_up | anim_pilates_roll_up.mp4 | MP4 | свой | да | да | — |
| Пилатес | Одна нога вверх | single_leg_stretch | anim_single_leg_stretch | anim_single_leg_stretch.mp4 | MP4 | свой | да | да | — |
| Пилатес | Мостик с подъёмом таза | pilates_pelvic_bridge | anim_pilates_pelvic_bridge | anim_pilates_pelvic_bridge.mp4 | MP4 | свой | да | да | — |
| Пилатес | «Плавание» лёжа на животе | pilates_swimming | anim_pilates_swimming | anim_pilates_swimming.mp4 | MP4 | свой | да | да | — |
| Пилатес | Боковая планка | side_plank | anim_side_plank | anim_side_plank.mp4 | MP4 | свой | да | да | — |
| Пилатес | Ножницы лёжа | lying_scissors | anim_lying_scissors | anim_lying_scissors.mp4 | MP4 | свой | да | да | — |
| Фейс-йога | Разглаживание лба против сопротивления пальцев | forehead_smoothing | anim_forehead_smoothing | anim_forehead_smoothing.mp4 | MP4 | свой | да | да | — |
| Фейс-йога | Упражнение для круговой мышцы глаза | orbicularis_eye_exercise | anim_orbicularis_eye_exercise | anim_orbicularis_eye_exercise.mp4 | MP4 | свой | да | да | — |
| Фейс-йога | Надувание щёк с перекатом воздуха | cheek_air_roll | anim_cheek_air_roll | anim_cheek_air_roll.mp4 | MP4 | свой | да | да | — |
| Фейс-йога | Улыбка с сопротивлением уголков губ | resisted_smile | anim_resisted_smile | anim_resisted_smile.mp4 | MP4 | свой | да | да | — |
| Фейс-йога | Вытягивание языка вниз («лев») | lion_tongue_stretch | anim_lion_tongue_stretch | anim_lion_tongue_stretch.mp4 | MP4 | свой | да | да | — |
| Фейс-йога | Выдвижение челюсти с запрокинутой головой | jaw_thrust_head_back | anim_jaw_thrust_head_back | anim_jaw_thrust_head_back.mp4 | MP4 | свой | да | да | — |
| Фейс-йога | Вытягивание шеи вверх | neck_lengthening | anim_neck_lengthening | anim_neck_lengthening.png | PNG | свой | да | да | — |
| Самомассаж лица | Разогрев ладонями | palm_warmup | anim_palm_warmup | anim_palm_warmup.mp4 | MP4 | свой | да | да | — |
| Самомассаж лица | Поглаживание от центра лба к вискам | forehead_stroking | anim_forehead_stroking | anim_forehead_stroking.mp4 | MP4 | свой | да | да | — |
| Самомассаж лица | Мягкое разглаживание области под глазами двумя пальцами | under_eye_two_finger_glide | anim_under_eye_two_finger_glide | anim_under_eye_two_finger_glide.mp4 | MP4 | свой | да | да | — |
| Самомассаж лица | Массаж щёк от носа к ушам | cheek_glide | anim_cheek_glide | anim_cheek_glide.mp4 | MP4 | свой | да | да | — |
| Самомассаж лица | Мягкие круговые движения на висках | temple_circles | anim_temple_circles | anim_temple_circles.mp4 | MP4 | свой | да | да | — |
| Самомассаж лица | Массаж по линии нижней челюсти | jawline_glide | anim_jawline_glide | anim_jawline_glide.mp4 | MP4 | свой | да | да | — |
| Самомассаж лица | Отток по шее вниз к ключицам | neck_lymph_drainage | anim_neck_lymph_drainage | anim_neck_lymph_drainage.mp4 | MP4 | свой | да | да | — |
| Гимнастика для глаз | Частое моргание | rapid_blinking | — | — | — | — | — | — | показа нет — ролик не присылали |
| Гимнастика для глаз | Пальминг: ладони на закрытых глазах | palming | — | — | — | — | — | — | показа нет — ролик не присылали |
| Гимнастика для глаз | Перевод взгляда с близкого на дальнее | near_far_focus | — | — | — | — | — | — | показа нет — ролик не присылали |
| Гимнастика для глаз | Движения взглядом вверх-вниз | gaze_vertical | — | — | — | — | — | — | показа нет — ролик не присылали |
| Гимнастика для глаз | Движения взглядом влево-вправо | gaze_horizontal | — | — | — | — | — | — | показа нет — ролик не присылали |
| Гимнастика для глаз | Круговые движения глазами | gaze_circles | — | — | — | — | — | — | показа нет — ролик не присылали |
| Гимнастика для глаз | Диагонали: угол к углу | gaze_diagonals | — | — | — | — | — | — | показа нет — ролик не присылали |
| Осанка | Втягивание подбородка (chin tuck) | chin_tuck | anim_chin_tuck | anim_chin_tuck.mp4 | MP4 | свой | да | да | — |
| Осанка | Сведение лопаток стоя | standing_scapular_squeeze | anim_standing_scapular_squeeze | anim_standing_scapular_squeeze.mp4 | MP4 | свой | да | да | — |
| Осанка | Раскрытие груди в дверном проёме | doorway_chest_opener | anim_doorway_chest_stretch | anim_doorway_chest_stretch.mp4 | MP4 | повторно от `doorway_chest_stretch` | да | да | — |
| Осанка | «Стенка»: скольжение руками по стене | wall_slide | anim_wall_slide | anim_wall_slide.mp4 | MP4 | свой | да | да | — |
| Осанка | Супермен лёжа | superman_raise | anim_superman_raise | anim_superman_raise.mp4 | MP4 | свой | да | да | подпись в манифесте «Половинный Супермен — подъём корпуса и рук» (закреплено Лилией) |
| Осанка | Кошка-корова | cat_cow | anim_cat_cow | anim_cat_cow.mp4 | MP4 | свой | да | да | — |
| Осанка | Планка на локтях | forearm_plank | anim_plank_forearm | anim_plank_forearm.png | PNG | свой | да | да | — |
| Танцевальная разминка | Шаги на месте с работой рук | marching_in_place | anim_marching_in_place | anim_marching_in_place.mp4 | MP4 | свой | да | да | — |
| Танцевальная разминка | Приставной шаг вправо-влево | side_step_touch | anim_side_step_touch | anim_side_step_touch.mp4 | MP4 | свой | да | да | — |
| Танцевальная разминка | Круги плечами и раскрытие груди | shoulder_circles_chest_open | anim_backward_shoulder_circles | anim_backward_shoulder_circles.mp4 | MP4 | повторно от `backward_shoulder_circles` | да | да | — |
| Танцевальная разминка | Волна корпусом | body_wave | anim_body_wave | anim_body_wave.mp4 | MP4 | свой | да | да | — |
| Танцевальная разминка | Восьмёрка бёдрами | hip_figure_eight | anim_hip_figure_eight | anim_hip_figure_eight.mp4 | MP4 | свой | да | да | — |
| Танцевальная разминка | Захлёст голени с поворотом | heel_flick_twist | anim_heel_flick_twist | anim_heel_flick_twist.mp4 | MP4 | свой | да | да | — |
| Танцевальная разминка | Растяжка боков стоя | standing_side_stretch | anim_standing_side_stretch | anim_standing_side_stretch.mp4 | MP4 | свой | да | да | — |
| Второй подбородок | Втягивание подбородка у стены | wall_chin_tuck | anim_wall_chin_tuck | anim_wall_chin_tuck.mp4 | MP4 | свой | да | да | — |
| Второй подбородок | Вытягивание шеи вверх | neck_lengthening | anim_neck_lengthening | anim_neck_lengthening.png | PNG | свой | да | да | — |
| Второй подбородок | Выдвижение челюсти с запрокинутой головой | jaw_thrust_head_back | anim_jaw_thrust_head_back | anim_jaw_thrust_head_back.mp4 | MP4 | свой | да | да | — |
| Второй подбородок | Язык к нёбу с мягким подъёмом подбородка | tongue_palate_chin_lift | anim_tongue_palate_chin_lift | anim_tongue_palate_chin_lift.png | PNG + отсчёт | свой | да | да | — |
| Второй подбородок | Массаж по линии нижней челюсти | jawline_glide | anim_jawline_glide | anim_jawline_glide.mp4 | MP4 | свой | да | да | — |
| Второй подбородок | Отток по шее вниз к ключицам | neck_lymph_drainage | anim_neck_lymph_drainage | anim_neck_lymph_drainage.mp4 | MP4 | свой | да | да | — |
| Холка | Втягивание подбородка у стены | wall_chin_tuck | anim_wall_chin_tuck | anim_wall_chin_tuck.mp4 | MP4 | свой | да | да | — |
| Холка | Наклон головы к плечу с рукой | assisted_neck_tilt | anim_neck_side_tilt | anim_neck_side_tilt.mp4 | MP4 | повторно от `neck_side_tilt` | да | да | — |
| Холка | Круги плечами назад | backward_shoulder_circles | anim_backward_shoulder_circles | anim_backward_shoulder_circles.mp4 | MP4 | свой | да | да | — |
| Холка | Сведение лопаток вниз | scapular_depression | anim_scapular_depression | anim_scapular_depression.mp4 | MP4 | свой | да | да | — |
| Холка | Растяжка грудных в дверном проёме | doorway_pec_stretch | anim_doorway_chest_stretch | anim_doorway_chest_stretch.mp4 | MP4 | повторно от `doorway_chest_stretch` | да | да | — |
| Холка | «Стенка»: скольжение руками по стене | wall_slide | anim_wall_slide | anim_wall_slide.mp4 | MP4 | свой | да | да | — |
| Холка | Кошка-корова | cat_cow | anim_cat_cow | anim_cat_cow.mp4 | MP4 | свой | да | да | — |
| Мышцы тазового дна | Диафрагмальное дыхание лёжа | supine_diaphragmatic_breathing | anim_diaphragmatic_breathing | anim_diaphragmatic_breathing.mp4 | MP4 + кольцо дыхания | свой | да | да | — |
| Мышцы тазового дна | Дыхание рёбрами на 360° | rib_breathing_360 | anim_360_rib_breathing | anim_360_rib_breathing.mp4 | MP4 + кольцо дыхания | свой | да | да | — |
| Мышцы тазового дна | Расслабление тазового дна на вдохе | full_pelvic_release | anim_diaphragmatic_breathing | anim_diaphragmatic_breathing.mp4 | MP4 + кольцо дыхания | повторно от `supine_diaphragmatic_breathing` | да | да | — |
| Мышцы тазового дна | Подъём на выдохе — расслабление на вдохе | quick_pelvic_squeeze | anim_diaphragmatic_breathing | anim_diaphragmatic_breathing.mp4 | MP4 + кольцо дыхания | повторно от `supine_diaphragmatic_breathing` | да | да | — |
| Мышцы тазового дна | Ягодичный мостик с выдохом на подъёме | glute_bridge_with_breath | anim_glute_bridge | anim_glute_bridge.mp4 | MP4 + кольцо дыхания | повторно от `glute_bridge` | да | да | — |
| Мышцы тазового дна | Дыхание в позе ребёнка | child_pose_breathing | anim_child_pose | anim_child_pose.mp4 | MP4 + кольцо дыхания | повторно от `child_pose` | да | да | — |

## Четыре списка

### 1. Полностью готовые блоки (15 из 17)

Показ есть у каждого упражнения программы, все файлы на месте и целы.

1. **Дом · Новичок** — 6 из 6 (5 роликов + кадр планки)
2. **Дом · Средний** — 7 из 7
3. **Зал · Средний** — 7 из 7
4. **Кардио дома** — 6 из 6
5. **Резинки** — 7 из 7
6. **Йога** — 7 из 7
7. **Стретчинг** — 7 из 7
8. **Пилатес** — 7 из 7
9. **Фейс-йога** — 7 из 7 (6 роликов + кадр вытяжения шеи)
10. **Самомассаж лица** — 7 из 7
11. **Второй подбородок** — 6 из 6 (1 свой кадр, 5 ассетов из прежних блоков)
12. **Осанка** — 7 из 7 (часть ассетов из блоков 07 и 08)
13. **Холка** — 7 из 7
14. **Танцевальная разминка** — 7 из 7 (6 роликов + 1 ссылка на блок 10)
15. **Мышцы тазового дна** — 6 из 6 (2 своих ролика, 4 переиспользуют)

### 2. Частично готовые блоки (2 из 17)

1. **Зал · Новичок** — 2 из 6. Есть жим ногами (`machine_leg_press`, доехал
   внутри корректирующего пакета) и планка на локтях (`forearm_plank` —
   то же упражнение стоит в «Доме · Новичок» и «Осанке», и показывает тот
   же кадр). Пакета 03 не присылали вовсе.
2. **Гимнастика для глаз** — 0 из 7. Пакета не было ни одного.

### 3. Отсутствующие упражнения и ассеты (11 упражнений)

Ни у одного из них нет ни ролика, ни кадра. Ошибки привязки тут нет: записи
в манифесте просто не существует, и приложение честно показывает строку
«Анимация техники готовится». Текст техники у всех одиннадцати написан.

**Зал · Новичок (4):**

| Упражнение | Код |
|---|---|
| Тяга верхнего блока к груди | `lat_pulldown` |
| Жим в грудном тренажёре | `machine_chest_press` |
| Сгибание ног в тренажёре | `machine_leg_curl` |
| Гиперэкстензия | `back_extension` |

**Гимнастика для глаз (7):**

| Упражнение | Код |
|---|---|
| Частое моргание | `rapid_blinking` |
| Пальминг: ладони на закрытых глазах | `palming` |
| Перевод взгляда с близкого на дальнее | `near_far_focus` |
| Движения взглядом вверх-вниз | `gaze_vertical` |
| Движения взглядом влево-вправо | `gaze_horizontal` |
| Круговые движения глазами | `gaze_circles` |
| Диагонали: угол к углу | `gaze_diagonals` |

Отсутствующих файлов, битых ассетов и сломанных привязок **нет ни одного**.

### 4. Что осталось сделать, чтобы библиотека закрылась целиком

Всё, что ниже, — это съёмка. Кода дописывать не надо: новый пакет ставится
слиянием манифеста по коду упражнения, как ставились предыдущие пятнадцать.

1. **Заказать блок 03 «Зал · Новичок» — четыре ролика.** Коды:
   `lat_pulldown`, `machine_chest_press`, `machine_leg_curl`,
   `back_extension`. Жим ногами и приседания с гантелями уже есть, их
   присылать не надо. После этого закрывается шестнадцатая программа.
2. **Заказать блок для «Гимнастики для глаз» — семь показов.** Это особый
   случай: движение здесь размером с глаз, и обычный ролик во весь рост
   его не покажет. Нужен крупный план лица или глаза, иначе показ будет
   формально быть и ничего не объяснять. Стоит обсудить это с теми, кто
   делает пакеты, до заказа.
3. **Решить, переснимать ли три ролика блока 05.** В «Прыжках из приседа»
   и «Выпадах в прыжке» на взлёте персонаж показан без головы, в «Бёрпи» —
   со срезанной макушкой, у «Джампинг-джека» подрезаны кончики пальцев.
   Обрезать и пережимать нельзя, вписать уже нечего — голова снята за
   краем кадра. Лечится только новой съёмкой с более общим планом.
4. **Решить, переснимать ли «Наклоны головы к плечу» из блока 08.** Ролик
   целый и правильный, но головой в нём почти не двигают: центр головы
   гуляет на 2,4% ширины кадра против 10,5% у наклона к ногам из того же
   пакета. Учить по нему нечему.
5. **Посмотреть на телефоне блоки 10 и 11.** У них не пришло контрольных
   листов — только по одному кадру на ролик. Отсюда не проверить, что
   ролик показывает само движение; в «Танцевальной разминке» это особенно
   важно, там поза по одному кадру от соседней не отличается.
6. **Посмотреть на телефоне блок 16.** Само воспроизведение из рабочей
   сессии не проверить: Chromium в контейнере собран без нужных кодеков.
   Проверено всё остальное — какой файл подставлен, звук, скорость,
   кадрирование, поведение при выключенном движении.
7. **Решить судьбу упражнений, убранных из программ.** Из базы они не
   удалены, вернуть любое — одна строка:
   - из «Второго подбородка» ушли четыре (сопротивление ладонью,
     «И — У», наклон головы назад, растяжка передней поверхности шеи);
   - из «Мышц тазового дна» ушли два («Долгое удержание», «Лифт»);
   - из «Самомассажа лица» ушла «Проработка носогубных складок».

### Чего делать не надо

- **Искать `anim_chin_tuck_wall`.** Этого имени в проекте нет намеренно:
  файл стоит под именем `anim_wall_chin_tuck`, и на отсутствие второго
  экземпляра стоит тест.
- **Приводить подпись супермена к каталогу.** «Половинный Супермен»
  закреплён отдельным решением.
- **Заводить отдельную программу под блок 10.** Пакет описывал одну
  программу «Осанка и холка», в проекте это две; шесть роликов и три
  ссылки разошлись по обеим, и обе закрыты целиком.
