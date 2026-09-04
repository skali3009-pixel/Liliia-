/* Логика мини-приложения. Данные берём из того же API, что и бот, —
   база одна, так что съеденное появляется здесь сразу после фото в чате. */

const tg = window.Telegram?.WebApp;
const RING_LENGTH = 327; // длина окружности радиуса 52

let state = null;

/* --- обращения к серверу: подпись Telegram уходит в заголовке --- */
async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'X-Telegram-Init-Data': tg?.initData || '',
      ...(options.headers || {}),
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.error || `Ошибка ${response.status}`);
  }
  return response.json();
}

function toast(text) {
  const el = document.getElementById('toast');
  el.textContent = text;
  el.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { el.hidden = true; }, 2000);
}

function haptic(type = 'light') {
  tg?.HapticFeedback?.impactOccurred?.(type);
}

/* --- отрисовка --- */
function renderToday(data) {
  const { totals, norms, meals } = data;

  const left = Math.max(norms.calories - totals.calories, 0);
  const over = totals.calories > norms.calories;
  document.getElementById('kcal-left').textContent = over ? `+${totals.calories - norms.calories}` : left;
  document.querySelector('.kcal-label').textContent = over ? 'ккал перебор' : 'ккал осталось';
  document.getElementById('kcal-sub').textContent =
    `${totals.calories} из ${norms.calories} ккал`;

  const ratio = norms.calories ? Math.min(totals.calories / norms.calories, 1) : 0;
  const ring = document.getElementById('ring-fill');
  ring.style.strokeDashoffset = RING_LENGTH * (1 - ratio);
  ring.style.stroke = over ? 'var(--over)' : ratio > 0.85 ? 'var(--warn)' : 'var(--ok)';

  const macros = [
    ['p', totals.protein_g, norms.protein_g],
    ['f', totals.fat_g, norms.fat_g],
    ['c', totals.carbs_g, norms.carbs_g],
  ];
  for (const [key, value, norm] of macros) {
    document.getElementById(`bar-${key}`).style.width =
      norm ? `${Math.min((value / norm) * 100, 100)}%` : '0%';
    document.getElementById(`val-${key}`).textContent = `${value} / ${norm} г`;
  }

  document.getElementById('water-val').textContent =
    `${totals.water_ml} / ${norms.water_ml} мл`;
  document.getElementById('bar-water').style.width =
    norms.water_ml ? `${Math.min((totals.water_ml / norms.water_ml) * 100, 100)}%` : '0%';

  const list = document.getElementById('meals');
  list.innerHTML = meals.length
    ? ''
    : '<div class="empty">Пока пусто. Пришли боту фото еды 📷</div>';

  for (const meal of meals) {
    const row = document.createElement('div');
    row.className = 'meal';
    row.innerHTML = `
      <div class="meal-main">
        <div class="meal-name"></div>
        <div class="meal-sub"></div>
      </div>
      <div class="meal-kcal">${meal.calories}</div>
      <button class="icon-btn" title="Изменить вес">✎</button>
      <button class="icon-btn" title="Удалить">🗑</button>`;
    row.querySelector('.meal-name').textContent = meal.name;
    row.querySelector('.meal-sub').textContent =
      `${meal.time} · ${meal.weight_g} г · Б ${meal.protein_g} Ж ${meal.fat_g} У ${meal.carbs_g}`;

    const [editBtn, deleteBtn] = row.querySelectorAll('.icon-btn');
    editBtn.onclick = () => editWeight(meal);
    deleteBtn.onclick = () => removeMeal(meal);
    list.appendChild(row);
  }
}

function renderPills(supplements) {
  const box = document.getElementById('pills');
  box.innerHTML = supplements.length
    ? ''
    : '<div class="empty">На сегодня ничего не запланировано</div>';

  for (const item of supplements) {
    const row = document.createElement('div');
    row.className = 'pill';
    row.innerHTML = `
      <button class="pill-check${item.taken ? ' done' : ''}">✓</button>
      <div class="pill-main">
        <div class="pill-name${item.taken ? ' done' : ''}"></div>
        <div class="pill-sub"></div>
      </div>
      <button class="icon-btn" title="Убрать из списка">🗑</button>`;
    row.querySelector('.pill-name').textContent = item.name;
    row.querySelector('.pill-sub').textContent =
      [item.dose, item.schedule].filter(Boolean).join(' · ');

    row.querySelector('.pill-check').onclick = async () => {
      haptic();
      await api(`/api/supplements/${item.id}/mark`, {
        method: 'POST',
        body: JSON.stringify({ skipped: item.taken }),
      });
      await refresh();
    };
    row.querySelector('.icon-btn').onclick = async () => {
      if (!confirm(`Убрать «${item.name}» из списка?`)) return;
      await api(`/api/supplements/${item.id}`, { method: 'DELETE' });
      await refresh();
    };
    box.appendChild(row);
  }
}

/* --- действия --- */
async function editWeight(meal) {
  const value = prompt(`Сколько граммов в порции «${meal.name}»?`, meal.weight_g);
  if (!value) return;
  try {
    await api(`/api/meals/${meal.id}`, {
      method: 'PATCH',
      body: JSON.stringify({ weight_g: Number(value) }),
    });
    haptic('medium');
    await refresh();
  } catch (e) { toast(e.message); }
}

async function removeMeal(meal) {
  if (!confirm(`Удалить «${meal.name}»?`)) return;
  await api(`/api/meals/${meal.id}`, { method: 'DELETE' });
  haptic('medium');
  await refresh();
}

async function addWater(amount) {
  haptic();
  try {
    await api('/api/water', { method: 'POST', body: JSON.stringify({ amount_ml: amount }) });
    await refresh();
  } catch (e) { toast(e.message); }
}

async function addPill() {
  const name = document.getElementById('pill-name').value.trim();
  if (!name) { toast('Впиши название'); return; }

  const scheduleType = document.getElementById('pill-schedule').value;
  const weekdays = [...document.querySelectorAll('#weekday-picker .chip.on')]
    .map((b) => b.dataset.day).join(',');

  try {
    await api('/api/supplements', {
      method: 'POST',
      body: JSON.stringify({
        name,
        dose: document.getElementById('pill-dose').value.trim(),
        schedule_type: scheduleType,
        weekdays: scheduleType === 'weekdays' ? weekdays : '',
        interval_days: scheduleType === 'interval'
          ? Number(document.getElementById('pill-interval').value) || 7 : null,
        reminder_time: document.getElementById('pill-time').value,
      }),
    });
    document.getElementById('pill-name').value = '';
    document.getElementById('pill-dose').value = '';
    haptic('medium');
    toast('Добавлено');
    await refresh();
  } catch (e) { toast(e.message); }
}


/* --- Экран прогресса --------------------------------------------------- */

let progress = null;
let metric = 'weight';
let period = 'month';
let tableMode = false;

const CHART = { w: 320, h: 150, padL: 34, padR: 12, padT: 12, padB: 22 };

function buildChart(data) {
  const box = document.getElementById('chart-box');
  const points = data.points;

  if (points.length === 0) {
    box.innerHTML = '<div class="empty">Пока нет данных за этот период</div>';
    return;
  }
  if (points.length === 1) {
    const only = points[0];
    box.innerHTML = `<div class="empty">Одна точка: ${fmt(only.value)} ${data.unit} ·
      ${dayLabel(only.day)}<br>Добавь ещё замер — появится динамика.</div>`;
    return;
  }

  // Шкала: захватываем и цель, чтобы её линия не ушла за край.
  const values = points.map((p) => p.value);
  if (data.goal) values.push(data.goal);
  let min = Math.min(...values);
  let max = Math.max(...values);
  const pad = (max - min) * 0.15 || Math.max(max * 0.05, 1);
  min -= pad; max += pad;

  const { w, h, padL, padR, padT, padB } = CHART;
  const plotW = w - padL - padR;
  const plotH = h - padT - padB;
  const x = (i) => padL + (plotW * i) / (points.length - 1);
  const y = (v) => padT + plotH * (1 - (v - min) / (max - min));

  const ticks = [max, (max + min) / 2, min];
  const grid = ticks.map((t) => `
    <line class="grid-line" x1="${padL}" y1="${y(t).toFixed(1)}" x2="${w - padR}" y2="${y(t).toFixed(1)}"/>
    <text class="axis-text" x="0" y="${(y(t) + 3).toFixed(1)}">${fmt(t)}</text>`).join('');

  const path = points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(' ');

  // Подписываем только последнюю точку — число у каждой превращается в кашу.
  const last = points[points.length - 1];
  const lastX = x(points.length - 1);
  const lastY = y(last.value);

  const goalLine = data.goal ? `
    <line class="goal-line" x1="${padL}" y1="${y(data.goal).toFixed(1)}"
          x2="${w - padR}" y2="${y(data.goal).toFixed(1)}"/>
    <text class="goal-text" x="${w - padR}" y="${(y(data.goal) - 4).toFixed(1)}"
          text-anchor="end">цель ${fmt(data.goal)}</text>` : '';

  const dots = points.map((p, i) =>
    `<circle class="series-dot" data-i="${i}" cx="${x(i).toFixed(1)}" cy="${y(p.value).toFixed(1)}" r="${points.length > 20 ? 0 : 3}"/>`
  ).join('');

  box.innerHTML = `
    <svg class="chart" viewBox="0 0 ${w} ${h}" role="img"
         aria-label="${data.title} за период: от ${fmt(points[0].value)} до ${fmt(last.value)} ${data.unit}">
      ${grid}${goalLine}
      <path class="series-line" d="${path}"/>
      ${dots}
      <circle class="series-dot active" cx="${lastX.toFixed(1)}" cy="${lastY.toFixed(1)}" r="4"/>
      <text class="axis-text" x="${padL}" y="${h - 6}">${dayLabel(points[0].day)}</text>
      <text class="axis-text" x="${w - padR}" y="${h - 6}" text-anchor="end">${dayLabel(last.day)}</text>
      <g id="hover-layer"></g>
      <rect id="hit-area" x="${padL}" y="0" width="${plotW}" height="${h}" fill="transparent"/>
    </svg>`;

  attachHover(box.querySelector('svg'), points, data, { x, y, plotW, padL });
}

/* Палец толще точки: ищем ближайшую по горизонтали, а не попадание в кружок. */
function attachHover(svg, points, data, geom) {
  const layer = svg.querySelector('#hover-layer');
  const hit = svg.querySelector('#hit-area');

  const show = (event) => {
    const rect = svg.getBoundingClientRect();
    const touch = event.touches ? event.touches[0] : event;
    const localX = ((touch.clientX - rect.left) / rect.width) * CHART.w;

    let nearest = 0;
    let best = Infinity;
    points.forEach((_, i) => {
      const distance = Math.abs(geom.x(i) - localX);
      if (distance < best) { best = distance; nearest = i; }
    });

    const point = points[nearest];
    const px = geom.x(nearest);
    const py = geom.y(point.value);
    const label = `${dayLabel(point.day)} · ${fmt(point.value)} ${data.unit}`;
    const boxW = label.length * 5.6 + 14;
    const boxX = Math.min(Math.max(px - boxW / 2, 2), CHART.w - boxW - 2);

    layer.innerHTML = `
      <line class="crosshair" x1="${px.toFixed(1)}" y1="${CHART.padT}"
            x2="${px.toFixed(1)}" y2="${CHART.h - CHART.padB}"/>
      <circle class="series-dot active" cx="${px.toFixed(1)}" cy="${py.toFixed(1)}" r="4.5"/>
      <rect class="tip-box" x="${boxX.toFixed(1)}" y="0" width="${boxW.toFixed(1)}" height="18" rx="6"/>
      <text class="tip-text" x="${(boxX + boxW / 2).toFixed(1)}" y="13" text-anchor="middle">${label}</text>`;
  };

  hit.addEventListener('touchstart', show, { passive: true });
  hit.addEventListener('touchmove', show, { passive: true });
  hit.addEventListener('mousemove', show);
  hit.addEventListener('touchend', () => { layer.innerHTML = ''; });
  hit.addEventListener('mouseleave', () => { layer.innerHTML = ''; });
}

function buildTable(data) {
  const box = document.getElementById('chart-table');
  box.innerHTML = data.points.length
    ? data.points.slice().reverse().map((p) =>
        `<div class="table-row"><span>${dayLabel(p.day)}</span><span>${fmt(p.value)} ${data.unit}</span></div>`
      ).join('')
    : '<div class="empty">Пока нет данных</div>';
}

function fmt(value) {
  return Number.isInteger(value) ? value : Number(value).toFixed(1);
}

function dayLabel(iso) {
  const [, month, day] = iso.split('-');
  return `${day}.${month}`;
}

async function renderPhotos(photos) {
  const box = document.getElementById('photo-compare');
  const hint = document.getElementById('photo-hint');
  box.innerHTML = '';

  if (photos.length === 0) {
    hint.textContent = 'Пока нет фото. Первое станет точкой отсчёта «до».';
    return;
  }
  hint.textContent = photos.length === 1
    ? 'Есть первое фото. Следующее встанет рядом для сравнения.'
    : 'Снимай в одинаковой позе и при одном свете — так разница видна честнее.';

  const first = photos[0];
  const last = photos[photos.length - 1];
  box.innerHTML = `
    <div class="compare">
      <figure><img id="photo-a" alt="Фото до"><figcaption>${first.date}</figcaption></figure>
      <figure><img id="photo-b" alt="Фото после"><figcaption>${last.date}</figcaption></figure>
    </div>`;
  await loadPhoto(first.id, document.getElementById('photo-a'));
  if (photos.length > 1) await loadPhoto(last.id, document.getElementById('photo-b'));
  else document.getElementById('photo-b').closest('figure').remove();
}

/* Картинку тянем с подписью в заголовке: <img src> её передать не может. */
async function loadPhoto(id, img) {
  const response = await fetch(`/api/photos/${id}`, {
    headers: { 'X-Telegram-Init-Data': tg?.initData || '' },
  });
  if (!response.ok) return;
  img.src = URL.createObjectURL(await response.blob());
}

async function refreshProgress() {
  progress = await api(`/api/progress?metric=${metric}&period=${period}`);

  const s = progress.summary;
  document.getElementById('stat-weight').textContent = s.current_weight ? fmt(s.current_weight) : '—';
  document.getElementById('stat-change').textContent =
    s.changed > 0 ? `+${fmt(s.changed)}` : fmt(s.changed || 0);
  document.getElementById('stat-streak').textContent = s.streak;
  document.getElementById('chart-title').textContent = progress.title;

  buildChart(progress);
  buildTable(progress);
  await renderPhotos(progress.photos);
}

async function saveMeasurement() {
  const body = {
    weight_kg: document.getElementById('m-weight').value,
    waist_cm: document.getElementById('m-waist').value,
    hips_cm: document.getElementById('m-hips').value,
    chest_cm: document.getElementById('m-chest').value,
    arm_cm: document.getElementById('m-arm').value,
  };
  try {
    const result = await api('/api/measurements', { method: 'POST', body: JSON.stringify(body) });
    for (const id of ['m-weight', 'm-waist', 'm-hips', 'm-chest', 'm-arm']) {
      document.getElementById(id).value = '';
    }
    haptic('medium');
    toast(result.norms_updated
      ? `Записал. Норма пересчитана: ${result.norms.calories} ккал`
      : 'Записал');
    await refreshProgress();
    await refresh();
  } catch (e) { toast(e.message); }
}

async function uploadPhoto(file) {
  const form = new FormData();
  form.append('photo', file, 'photo.jpg');
  toast('Загружаю фото…');
  try {
    await fetch('/api/photos', {
      method: 'POST',
      headers: { 'X-Telegram-Init-Data': tg?.initData || '' },
      body: form,
    }).then((r) => { if (!r.ok) throw new Error('Не удалось загрузить'); });
    haptic('medium');
    await refreshProgress();
  } catch (e) { toast(e.message); }
}


/* --- Тренировки -------------------------------------------------------- */

let gym = null;
let place = 'home';
let level = 'beginner';
const doneExercises = new Set();
let restTimer = null;

function renderWorkouts(data) {
  const program = data.programs.find((p) => p.code === data.selected);
  document.getElementById('program-title').textContent = program ? program.title : 'Программа';
  document.getElementById('program-sub').textContent = program ? program.subtitle : '';
  document.getElementById('gym-count').textContent = data.week.workouts;
  document.getElementById('gym-kcal').textContent = data.week.calories;

  const box = document.getElementById('exercises');
  box.innerHTML = '';
  for (const exercise of data.exercises) {
    box.appendChild(exerciseRow(exercise));
  }

  const cardio = document.getElementById('cardio-list');
  cardio.innerHTML = '';
  for (const exercise of data.cardio) {
    cardio.appendChild(exerciseRow(exercise, { cardio: true }));
  }

  updateFinishButton();
}

function exerciseRow(exercise, { cardio = false } = {}) {
  const done = doneExercises.has(exercise.id);
  const row = document.createElement('div');
  row.className = 'exercise';

  // Упражнение на время описывается подходами и секундами, а не повторами.
  const load = exercise.seconds_per_set
    ? `${exercise.sets} подхода по ${exercise.seconds_per_set} с`
    : `${exercise.sets}×${exercise.reps}`;
  const detail = cardio
    ? `${exercise.minutes} мин · ~${exercise.calories} ккал`
    : `${load} · отдых ${exercise.rest_seconds} с · ~${exercise.calories} ккал`;

  row.innerHTML = `
    <button class="ex-check${done ? ' done' : ''}">✓</button>
    <div class="ex-main">
      <div class="ex-name${done ? ' done' : ''}"></div>
      <div class="ex-sub"></div>
      <div class="ex-actions">
        <a class="ex-link" target="_blank" rel="noopener">как делать →</a>
        ${cardio ? '' : '<button class="ex-link rest-btn">запустить отдых</button>'}
      </div>
    </div>`;

  row.querySelector('.ex-name').textContent = exercise.name;
  row.querySelector('.ex-sub').textContent =
    [exercise.muscle, detail].filter(Boolean).join(' · ');
  row.querySelector('.ex-link').href = exercise.demo_url;

  row.querySelector('.ex-check').onclick = () => {
    if (doneExercises.has(exercise.id)) doneExercises.delete(exercise.id);
    else {
      doneExercises.add(exercise.id);
      haptic();
      // После отметки сразу предлагаем отдых — так и делают между подходами.
      if (!cardio && exercise.rest_seconds) startRest(exercise.rest_seconds);
    }
    renderWorkouts(gym);
  };

  const restButton = row.querySelector('.rest-btn');
  if (restButton) restButton.onclick = () => startRest(exercise.rest_seconds);

  return row;
}

function updateFinishButton() {
  const button = document.getElementById('finish-workout');
  const count = doneExercises.size;
  button.hidden = count === 0;
  button.textContent = `Записать тренировку (${count})`;
}

function startRest(seconds) {
  clearInterval(restTimer);
  let left = seconds;

  const overlay = document.getElementById('rest-overlay');
  const display = document.getElementById('rest-time');
  display.textContent = left;
  overlay.hidden = false;

  restTimer = setInterval(() => {
    left -= 1;
    display.textContent = Math.max(left, 0);
    if (left <= 0) {
      stopRest();
      haptic('heavy');
      tg?.HapticFeedback?.notificationOccurred?.('success');
    }
  }, 1000);
}

function stopRest() {
  clearInterval(restTimer);
  restTimer = null;
  document.getElementById('rest-overlay').hidden = true;
}

async function refreshWorkouts() {
  gym = await api(`/api/workouts?location=${place}&level=${level}`);
  renderWorkouts(gym);
}

async function finishWorkout() {
  const ids = [...doneExercises];
  if (ids.length === 0) return;

  // Для кардио спрашиваем реальное время — оно у всех разное.
  const cardioIds = new Set(gym.cardio.map((c) => c.id));
  let minutes = null;
  if (ids.some((id) => cardioIds.has(id))) {
    const answer = prompt('Сколько минут кардио?', '30');
    if (answer === null) return;
    minutes = Number(answer);
  }

  try {
    const result = await api('/api/workouts/log', {
      method: 'POST',
      body: JSON.stringify({ exercise_ids: ids, minutes }),
    });
    doneExercises.clear();
    haptic('medium');
    toast(`Записано: ${result.minutes} мин, ${result.calories} ккал`);
    await refreshWorkouts();
  } catch (e) { toast(e.message); }
}


/* --- Что съесть -------------------------------------------------------- */

async function loadSuggestions() {
  const button = document.getElementById('suggest-btn');
  const box = document.getElementById('suggestions');

  button.disabled = true;
  button.textContent = 'Подбираю…';

  try {
    const data = await api('/api/suggestions', { method: 'POST' });
    document.getElementById('gap-hint').textContent =
      data.gap ? `не хватает ${data.gap}` : '';
    renderSuggestions(data.suggestions);
    button.textContent = 'Подобрать ещё';
  } catch (e) {
    box.innerHTML = `<div class="empty">${e.message}</div>`;
    button.textContent = 'Попробовать снова';
  } finally {
    button.disabled = false;
  }
}

function renderSuggestions(items) {
  const box = document.getElementById('suggestions');
  box.innerHTML = items.length ? '' : '<div class="empty">Ничего не подобралось</div>';

  for (const item of items) {
    const row = document.createElement('div');
    row.className = 'suggestion';
    row.innerHTML = `
      <div class="sug-head">
        <span class="sug-name"></span>
        <span class="sug-kcal">${Math.round(item.calories)} ккал</span>
      </div>
      <div class="sug-macros"></div>
      <div class="sug-why"></div>
      <button class="sug-eat">Съела это</button>`;

    row.querySelector('.sug-name').textContent = item.name;
    row.querySelector('.sug-macros').textContent =
      `${Math.round(item.weight_g)} г · Б ${Math.round(item.protein_g)} · ` +
      `Ж ${Math.round(item.fat_g)} · У ${Math.round(item.carbs_g)}`;
    row.querySelector('.sug-why').textContent = item.why;

    row.querySelector('.sug-eat').onclick = async () => {
      try {
        await api('/api/meals', { method: 'POST', body: JSON.stringify(item) });
        haptic('medium');
        toast(`Записала: ${item.name}`);
        row.remove();
        await refresh();
      } catch (e) { toast(e.message); }
    };
    box.appendChild(row);
  }
}

/* --- загрузка и переключение вкладок --- */
async function refresh() {
  state = await api('/api/today');
  renderToday(state);
  renderPills(state.supplements);
}

function switchScreen(name) {
  for (const tab of document.querySelectorAll('.tab')) {
    tab.classList.toggle('active', tab.dataset.screen === name);
  }
  document.getElementById('screen-today').hidden = name !== 'today';
  document.getElementById('screen-progress').hidden = name !== 'progress';
  document.getElementById('screen-gym').hidden = name !== 'gym';
  document.getElementById('screen-pills').hidden = name !== 'pills';

  if (name === 'progress' && !progress) refreshProgress().catch((e) => toast(e.message));
  if (name === 'gym' && !gym) refreshWorkouts().catch((e) => toast(e.message));
}

function buildWeekdayPicker() {
  const box = document.getElementById('weekday-picker');
  ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс'].forEach((label, index) => {
    const button = document.createElement('button');
    button.className = 'chip';
    button.textContent = label;
    button.dataset.day = index;
    button.onclick = () => button.classList.toggle('on');
    box.appendChild(button);
  });
}

async function init() {
  tg?.ready();
  tg?.expand();

  buildWeekdayPicker();

  for (const button of document.querySelectorAll('[data-water]')) {
    button.onclick = () => addWater(Number(button.dataset.water));
  }
  document.getElementById('water-undo').onclick = async () => {
    await api('/api/water/undo', { method: 'POST' });
    haptic();
    await refresh();
  };
  document.getElementById('pill-add').onclick = addPill;
  for (const tab of document.querySelectorAll('.tab')) {
    tab.onclick = () => switchScreen(tab.dataset.screen);
  }
  for (const button of document.querySelectorAll('#metric-switch .seg-btn')) {
    button.onclick = () => {
      metric = button.dataset.metric;
      document.querySelectorAll('#metric-switch .seg-btn').forEach((b) => b.classList.remove('active'));
      button.classList.add('active');
      refreshProgress().catch((e) => toast(e.message));
    };
  }
  for (const button of document.querySelectorAll('#period-switch .seg-btn')) {
    button.onclick = () => {
      period = button.dataset.period;
      document.querySelectorAll('#period-switch .seg-btn').forEach((b) => b.classList.remove('active'));
      button.classList.add('active');
      refreshProgress().catch((e) => toast(e.message));
    };
  }
  document.getElementById('table-toggle').onclick = (event) => {
    tableMode = !tableMode;
    document.getElementById('chart-box').hidden = tableMode;
    document.getElementById('chart-table').hidden = !tableMode;
    event.target.textContent = tableMode ? 'график' : 'таблица';
  };
  document.getElementById('m-save').onclick = saveMeasurement;

  for (const button of document.querySelectorAll('#place-switch .seg-btn')) {
    button.onclick = () => {
      place = button.dataset.place;
      document.querySelectorAll('#place-switch .seg-btn').forEach((b) => b.classList.remove('active'));
      button.classList.add('active');
      refreshWorkouts().catch((e) => toast(e.message));
    };
  }
  for (const button of document.querySelectorAll('#level-switch .seg-btn')) {
    button.onclick = () => {
      level = button.dataset.level;
      document.querySelectorAll('#level-switch .seg-btn').forEach((b) => b.classList.remove('active'));
      button.classList.add('active');
      refreshWorkouts().catch((e) => toast(e.message));
    };
  }
  document.getElementById('finish-workout').onclick = finishWorkout;
  document.getElementById('suggest-btn').onclick = loadSuggestions;
  document.getElementById('rest-skip').onclick = stopRest;
  document.getElementById('photo-input').onchange = (event) => {
    if (event.target.files[0]) uploadPhoto(event.target.files[0]);
  };

  document.getElementById('pill-schedule').onchange = (event) => {
    document.getElementById('weekday-picker').hidden = event.target.value !== 'weekdays';
    document.getElementById('pill-interval').hidden = event.target.value !== 'interval';
  };

  try {
    await refresh();
    document.getElementById('loading').hidden = true;
    document.getElementById('app').hidden = false;
  } catch (e) {
    document.getElementById('loading').textContent =
      e.message.includes('Профиль')
        ? 'Сначала пройди анкету в чате: /start'
        : `Не удалось загрузить: ${e.message}`;
  }
}

init();
