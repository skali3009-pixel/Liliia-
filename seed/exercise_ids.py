"""Постоянный код упражнения.

Названия в этом проекте — ключ ко всему: по ним ищется техника, движение и
теперь анимация тренера. Но название — русская строка, и связывать по ней
файлы нельзя: одна опечатка или запятая, и человек молча остаётся без
показа. Поэтому у каждого упражнения есть короткий постоянный код.

Код не зависит ни от программы, ни от места в ней: одно упражнение стоит в
нескольких программах (планка — в трёх), и код у него один. Числовой `id`
из базы для этого не годится — он выдаётся при заливке и на другом сервере
будет другим.

Коды здесь заданы явно, а не выведены из названия: транслитерация дала бы
разные строки на разных версиях библиотеки, и связь с файлами порвалась бы
без единой ошибки в логах.
"""

from __future__ import annotations

EXERCISE_IDS: dict[str, str] = {
    'Приседания с собственным весом': 'bodyweight_squat',
    'Отжимания с колен': 'knee_pushup',
    'Ягодичный мостик': 'glute_bridge',
    'Тяга в наклоне с бутылками воды': 'bottle_bent_over_row',
    'Планка на локтях': 'forearm_plank',
    'Подъёмы ног лёжа': 'lying_leg_raise',
    'Приседания-плие': 'plie_squat',
    'Отжимания классические': 'standard_pushup',
    'Выпады назад поочерёдно': 'alternating_reverse_lunge',
    'Ягодичный мостик на одной ноге': 'single_leg_glute_bridge',
    'Супермен лёжа': 'superman_raise',
    'Планка с подъёмом руки': 'plank_arm_raise',
    'Скручивания «велосипед»': 'bicycle_crunch',
    'Жим ногами в тренажёре': 'machine_leg_press',
    'Тяга верхнего блока к груди': 'lat_pulldown',
    'Жим в грудном тренажёре': 'machine_chest_press',
    'Сгибание ног в тренажёре': 'machine_leg_curl',
    'Гиперэкстензия': 'back_extension',
    'Приседания со штангой': 'barbell_squat',
    'Румынская тяга с гантелями': 'dumbbell_romanian_deadlift',
    'Жим гантелей лёжа': 'dumbbell_bench_press',
    'Тяга гантели в наклоне': 'single_arm_dumbbell_row',
    'Выпады с гантелями': 'dumbbell_lunge',
    'Жим гантелей сидя': 'seated_dumbbell_shoulder_press',
    'Скручивания на скамье': 'bench_crunch',
    'Джампинг-джек': 'jumping_jack',
    'Бег на месте с высоким подниманием колен': 'high_knees_run',
    'Скалолаз': 'mountain_climber',
    'Прыжки из приседа': 'squat_jump',
    'Выпады в прыжке': 'jump_lunge',
    'Бёрпи': 'burpee',
    'Приседания с резинкой над коленями': 'band_squat',
    'Отведение ноги в сторону стоя': 'standing_hip_abduction',
    '«Ракушка» лёжа на боку': 'side_lying_clamshell',
    'Ягодичный мостик с резинкой': 'band_glute_bridge',
    'Шаги в стороны с резинкой': 'band_lateral_walk',
    'Тяга резинки к поясу сидя': 'seated_band_row',
    'Разведение рук с резинкой': 'band_pull_apart',
    'Кошка-корова': 'cat_cow',
    'Собака мордой вниз': 'downward_dog',
    'Поза воина II': 'warrior_two',
    'Поза дерева': 'tree_pose',
    'Наклон вперёд стоя': 'standing_forward_fold',
    'Поза ребёнка': 'child_pose',
    'Шавасана': 'savasana',
    'Наклон к прямым ногам сидя': 'seated_forward_bend',
    'Растяжка квадрицепса стоя': 'standing_quad_stretch',
    'Поза голубя': 'pigeon_pose',
    'Растяжка груди в дверном проёме': 'doorway_chest_stretch',
    'Скручивание лёжа': 'supine_spinal_twist',
    'Наклоны головы к плечу': 'neck_side_tilt',
    'Растяжка икр у стены': 'wall_calf_stretch',
    'Сотня (The Hundred)': 'pilates_hundred',
    'Роллап': 'pilates_roll_up',
    'Одна нога вверх': 'single_leg_stretch',
    'Мостик с подъёмом таза': 'pilates_pelvic_bridge',
    '«Плавание» лёжа на животе': 'pilates_swimming',
    'Боковая планка': 'side_plank',
    'Ножницы лёжа': 'lying_scissors',
    'Разглаживание лба против сопротивления пальцев': 'forehead_smoothing',
    'Упражнение для круговой мышцы глаза': 'orbicularis_eye_exercise',
    'Надувание щёк с перекатом воздуха': 'cheek_air_roll',
    'Улыбка с сопротивлением уголков губ': 'resisted_smile',
    'Вытягивание языка вниз («лев»)': 'lion_tongue_stretch',
    'Выдвижение челюсти с запрокинутой головой': 'jaw_thrust_head_back',
    'Вытягивание шеи вверх': 'neck_lengthening',
    'Разогрев ладонями': 'palm_warmup',
    'Поглаживание от центра лба к вискам': 'forehead_stroking',
    'Лёгкие круги под глазами безымянным пальцем': 'under_eye_circles',
    'Разминание скул подушечками пальцев': 'cheekbone_kneading',
    'Проработка носогубных складок': 'nasolabial_massage',
    'Массаж линии челюсти костяшками': 'jawline_knuckle_massage',
    'Отток по шее вниз к ключицам': 'neck_lymph_drainage',
    'Частое моргание': 'rapid_blinking',
    'Пальминг: ладони на закрытых глазах': 'palming',
    'Перевод взгляда с близкого на дальнее': 'near_far_focus',
    'Движения взглядом вверх-вниз': 'gaze_vertical',
    'Движения взглядом влево-вправо': 'gaze_horizontal',
    'Круговые движения глазами': 'gaze_circles',
    'Диагонали: угол к углу': 'gaze_diagonals',
    'Втягивание подбородка (chin tuck)': 'chin_tuck',
    'Сведение лопаток стоя': 'standing_scapular_squeeze',
    'Раскрытие груди в дверном проёме': 'doorway_chest_opener',
    '«Стенка»: скольжение руками по стене': 'wall_slide',
    'Шаги на месте с работой рук': 'marching_in_place',
    'Приставной шаг вправо-влево': 'side_step_touch',
    'Круги плечами и раскрытие груди': 'shoulder_circles_chest_open',
    'Волна корпусом': 'body_wave',
    'Восьмёрка бёдрами': 'hip_figure_eight',
    'Захлёст голени с поворотом': 'heel_flick_twist',
    'Растяжка боков стоя': 'standing_side_stretch',
    'Язык к нёбу с наклоном головы': 'tongue_palate_head_tilt',
    '«Жираф»: вытяжение шеи вверх': 'giraffe_neck_stretch',
    'Сопротивление ладонью под подбородком': 'chin_palm_resistance',
    'Произнесение «И — У» с напряжением': 'ee_oo_articulation',
    'Наклон головы назад с движением челюсти': 'head_back_jaw_move',
    'Растяжка передней поверхности шеи': 'front_neck_stretch',
    'Втягивание подбородка у стены': 'wall_chin_tuck',
    'Наклон головы к плечу с рукой': 'assisted_neck_tilt',
    'Круги плечами назад': 'backward_shoulder_circles',
    'Сведение лопаток вниз': 'scapular_depression',
    'Растяжка грудных в дверном проёме': 'doorway_pec_stretch',
    'Диафрагмальное дыхание лёжа': 'supine_diaphragmatic_breathing',
    'Короткие сжатия': 'quick_pelvic_squeeze',
    'Долгое удержание': 'long_pelvic_hold',
    '«Лифт»: подъём по ступеням': 'pelvic_elevator',
    'Полное расслабление': 'full_pelvic_release',
    'Ягодичный мостик с дыханием': 'glute_bridge_with_breath',
}


def id_for(name: str) -> str | None:
    """Код упражнения по названию. Нет в справочнике — нет и кода."""
    return EXERCISE_IDS.get(name)
