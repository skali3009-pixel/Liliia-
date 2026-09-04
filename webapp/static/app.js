/* Логика мини-приложения. Данные берём из того же API, что и бот, —
   база одна, так что съеденное появляется здесь сразу после фото в чате. */

const tg = window.Telegram?.WebApp;
const RING_LENGTH = 327; // длина окружности радиуса 52
const DIAL_LENGTH = 113; // длина окружности радиуса 18

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
// Время суток и род слова: «спокойное утро», но «спокойный вечер».
const DAY_TITLES = [
  [5, 'Ночь', 'f'], [12, 'Утро', 'n'], [17, 'День', 'm'],
  [23, 'Вечер', 'm'], [24, 'Ночь', 'f'],
];
const TONES = {
  'спокойно': ['Спокойное', 'Спокойный', 'Спокойная'],
  'бодро': ['Бодрое', 'Бодрый', 'Бодрая'],
  'радостно': ['Светлое', 'Светлый', 'Светлая'],
  'устала': ['Тихое', 'Тихий', 'Тихая'],
  'тревожно': ['Тревожное', 'Тревожный', 'Тревожная'],
  'грустно': ['Тихое', 'Тихий', 'Тихая'],
  'раздражённо': ['Колючее', 'Колючий', 'Колючая'],
};

function dayTitle(state) {
  const hour = new Date().getHours();
  const [, base, gender] = DAY_TITLES.find(([until]) => hour < until) || DAY_TITLES[1];
  // Настроение делает заголовок личным: «Спокойное утро» вместо «Утро».
  const tone = TONES[state?.mood];
  if (!tone) return base;
  return `${tone[{ n: 0, m: 1, f: 2 }[gender]]} ${base.toLowerCase()}`;
}

const GREETINGS = [
  [5, '🌙', 'Доброй ночи.'],
  [12, '☀️', 'Доброе утро,\nты в фокусе.'],
  [17, '🌤️', 'Добрый день,\nты в ритме.'],
  [23, '🌘', 'Добрый вечер,\nдень почти собран.'],
  [24, '🌙', 'Доброй ночи.'],
];

function renderHero(data) {
  const state = data.state || {};
  const hour = new Date().getHours();
  const [, icon, greeting] = GREETINGS.find(([until]) => hour < until) || GREETINGS[0];
  document.getElementById('hero-greeting').textContent = greeting;
  document.getElementById('hero-state-icon').textContent = icon;
  document.getElementById('hero-title').textContent = dayTitle(state);

  const parts = [];
  if (state.sleep_minutes) {
    const h = Math.floor(state.sleep_minutes / 60);
    const m = state.sleep_minutes % 60;
    parts.push(`Сон ${h} ч ${String(m).padStart(2, '0')} м`);
  }
  if (state.energy) parts.push(`Энергия ${state.energy}/10`);
  if (!parts.length) parts.push(`${data.totals.calories} из ${data.norms.calories} ккал`);
  document.getElementById('hero-sub').textContent = parts.join(' · ');

  const tiles = [
    { icon: '⚡', label: 'Энергия', value: state.energy ? `${state.energy}` : null, suffix: '/10' },
    { icon: '🤍', label: 'Настроение', value: state.mood || null, text: true },
    { icon: '🎯', label: 'Фокус', value: state.focus ? `${state.focus}` : null, suffix: '/10' },
    { icon: '〰️', label: 'Стресс', value: state.stress || null, text: true },
  ];
  const grid = document.getElementById('state-grid');
  grid.innerHTML = '';
  for (const tile of tiles) {
    const box = document.createElement('div');
    box.className = 'state';
    const filled = tile.value !== null;
    box.innerHTML = `
      <div class="state-icon"></div>
      <div class="state-value"></div>
      <div class="state-label"></div>`;
    box.querySelector('.state-icon').textContent = tile.icon;
    const value = box.querySelector('.state-value');
    value.textContent = filled ? tile.value + (tile.suffix || '') : '—';
    value.classList.toggle('text', Boolean(tile.text) && filled);
    value.classList.toggle('empty', !filled);
    box.querySelector('.state-label').textContent = tile.label;
    grid.appendChild(box);
  }
}

function renderTimeline(events) {
  const box = document.getElementById('timeline');
  box.innerHTML = events.length
    ? ''
    : '<div class="empty">День ещё пустой. Расскажи, что происходит 👇</div>';
  document.getElementById('timeline-count').textContent =
    events.length ? `${events.length} ${plural(events.length, 'событие', 'события', 'событий')}` : '';

  for (const event of events) {
    const row = document.createElement('div');
    row.className = 'event';
    row.dataset.kind = event.kind;
    row.innerHTML = `
      <div class="event-dot"></div>
      <div class="event-main">
        <div class="event-time"></div>
        <div class="event-title"></div>
        <div class="event-sub"></div>
      </div>
      <div class="event-value"></div>`;
    row.querySelector('.event-dot').textContent = event.icon;
    row.querySelector('.event-time').textContent = event.time;
    row.querySelector('.event-title').textContent = event.title;
    row.querySelector('.event-sub').textContent = event.subtitle;
    row.querySelector('.event-value').textContent = event.value;

    // У еды справа стоят правка и удаление, у остальных событий — галочка:
    // они уже случились, и делать с ними в ленте нечего.
    if (event.kind !== 'meal') {
      const check = document.createElement('div');
      check.className = 'event-check';
      check.textContent = '✓';
      row.appendChild(check);
    }
    if (event.kind === 'meal' && event.id) {
      const meal = (state?.meals || []).find((item) => item.id === event.id);
      if (meal) {
        const actions = document.createElement('div');
        actions.className = 'event-actions';
        actions.innerHTML = `
          <button class="icon-btn" title="Изменить вес">✎</button>
          <button class="icon-btn" title="Удалить">🗑</button>`;
        const [editBtn, deleteBtn] = actions.querySelectorAll('.icon-btn');
        editBtn.onclick = () => editWeight(meal);
        deleteBtn.onclick = () => removeMeal(meal);
        row.appendChild(actions);
      }
    }
    box.appendChild(row);
  }
}

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
  // Обычный день — фиолетовый градиент; подход к норме и перебор красим
  // сплошным цветом, чтобы предупреждение читалось однозначно.
  ring.style.stroke = over ? 'var(--over)' : ratio > 0.9 ? 'var(--warn)' : 'url(#ring-gradient)';

  // Клетчатка — четвёртое кольцо: калорий не даёт, но цель у неё своя.
  const macros = [
    ['p', totals.protein_g, norms.protein_g],
    ['f', totals.fat_g, norms.fat_g],
    ['c', totals.carbs_g, norms.carbs_g],
    ['fib', totals.fiber_g ?? 0, norms.fiber_g ?? 0],
  ];
  for (const [key, value, norm] of macros) {
    const share = norm ? Math.min(value / norm, 1) : 0;
    document.getElementById(`dial-${key}`).style.strokeDashoffset = DIAL_LENGTH * (1 - share);
    document.getElementById(`val-${key}`).textContent = Math.round(value);
    document.getElementById(`norm-${key}`).textContent = `/ ${norm} г`;
  }

  document.getElementById('water-val').textContent =
    `${totals.water_ml} / ${norms.water_ml} мл`;
  document.getElementById('bar-water').style.width =
    norms.water_ml ? `${Math.min((totals.water_ml / norms.water_ml) * 100, 100)}%` : '0%';

  renderHero(data);
  renderTimeline(data.timeline || []);
}

/* --- игра: уровень, кристалл, задания дня --- */
function renderGame(game) {
  if (!game) return;

  document.getElementById('crystal').dataset.stage = game.crystal;
  document.getElementById('hud-level').textContent = `Уровень ${game.level}`;
  document.getElementById('hud-streak').textContent =
    game.streak ? `🔥 ${game.streak} ${plural(game.streak, 'день', 'дня', 'дней')} подряд` : '';
  document.getElementById('xp-fill').style.width = `${Math.round(game.level_share * 100)}%`;
  document.getElementById('xp-text').textContent =
    `${game.xp_in_level} / ${game.xp_to_next} 💎`;
  document.getElementById('xp-today').textContent =
    game.xp_today ? `+${game.xp_today} сегодня` : '';

  document.getElementById('quest-count').textContent =
    `${game.quests_done} из ${game.quests_total}`;

  const box = document.getElementById('quests');
  box.innerHTML = '';
  for (const quest of game.quests) {
    const row = document.createElement('div');
    row.className = `quest${quest.done ? ' done' : ''}`;
    row.innerHTML = `
      <span class="q-icon"></span>
      <div class="q-main">
        <div class="q-title"></div>
        <div class="q-line">
          <div class="q-track"><i></i></div>
          <span class="q-hint"></span>
        </div>
      </div>
      <span class="q-xp"></span>`;
    row.querySelector('.q-icon').textContent = quest.done ? '✓' : quest.icon;
    row.querySelector('.q-title').textContent = quest.title;
    row.querySelector('.q-track i').style.width = `${Math.round(quest.share * 100)}%`;
    row.querySelector('.q-hint').textContent = quest.hint;
    row.querySelector('.q-xp').textContent = `+${quest.xp}`;
    box.appendChild(row);
  }
}

function plural(count, one, few, many) {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}

function renderAwards(awards) {
  if (!awards) return;
  const box = document.getElementById('awards');
  box.innerHTML = '';
  for (const award of awards) {
    const tile = document.createElement('div');
    tile.className = `award${award.earned ? ' earned' : ''}`;
    tile.innerHTML = `
      <div class="a-icon"></div><div class="a-title"></div><div class="a-goal"></div>`;
    tile.querySelector('.a-icon').textContent = award.icon;
    tile.querySelector('.a-title').textContent = award.title;
    tile.querySelector('.a-goal').textContent = award.goal;
    box.appendChild(tile);
  }
  const earned = awards.filter((a) => a.earned).length;
  document.getElementById('award-count').textContent = `${earned} из ${awards.length}`;

  // Подсказываем ровно одно следующее открытие: список целей целиком
  // превращается в список долгов.
  const next = awards.find((a) => !a.earned);
  document.getElementById('award-next').textContent =
    next ? `Следующее открытие: ${next.title} — ${next.goal}.` : 'Все открытия собраны.';

  // Карточка последнего открытия: чем оно было и что дальше.
  const last = [...awards].reverse().find((a) => a.earned);
  document.getElementById('discovery-title').textContent =
    last ? last.title : 'Первое открытие ждёт';
  document.getElementById('discovery-why').textContent =
    last ? last.goal : 'запиши первый приём пищи';
  document.getElementById('discovery-next').textContent =
    next ? `${next.title} — ${next.goal}` : 'всё собрано';

  // Три шага до следующего открытия — просто и наглядно.
  const steps = document.getElementById('discovery-steps');
  steps.innerHTML = '';
  const done = Math.min(earned, 3);
  for (let i = 0; i < 3; i += 1) {
    if (i) {
      const line = document.createElement('b');
      line.className = i <= done - 1 ? 'on' : '';
      steps.appendChild(line);
    }
    const dot = document.createElement('i');
    dot.className = i < done ? 'on' : '';
    dot.textContent = i < done ? '✓' : i + 1;
    steps.appendChild(dot);
  }

  const world = document.getElementById('world-sub');
  if (world) {
    world.textContent = earned
      ? `Открыто ${earned} ${plural(earned, 'место', 'места', 'мест')} из ${awards.length}. Мир растёт с каждым закрытым заданием.`
      : 'Пока пусто. Закрой первое задание дня — и мир начнёт открываться.';
  }
}

/* Награда — редкое событие, поэтому единственное окно в приложении.
   Если их пришло несколько, показываем по очереди. */
function celebrate(game) {
  if (!game) return;
  // Тосты не накапливаются, поэтому про первое задание говорим словами,
  // а про остальные — числом.
  const closed = (game.just_completed || [])
    .map((code) => game.quests.find((q) => q.code === code))
    .filter(Boolean);
  if (closed.length) {
    const extra = closed.length > 1 ? ` и ещё ${closed.length - 1}` : '';
    toast(`${closed[0].icon} ${closed[0].title} — готово${extra}, +${game.xp_today} 💎`);
    haptic('medium');
  }

  const queue = [...(game.new_awards || [])];
  const pop = document.getElementById('award-pop');
  const showNext = () => {
    const award = queue.shift();
    if (!award) { pop.hidden = true; return; }
    document.getElementById('pop-icon').textContent = award.icon;
    document.getElementById('pop-title').textContent = award.title;
    pop.hidden = false;
    tg?.HapticFeedback?.notificationOccurred?.('success');
  };
  document.getElementById('pop-close').onclick = showNext;
  if (queue.length) showNext();
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
    thigh_cm: document.getElementById('m-thigh').value,
    chest_cm: document.getElementById('m-chest').value,
    arm_cm: document.getElementById('m-arm').value,
  };
  try {
    const result = await api('/api/measurements', { method: 'POST', body: JSON.stringify(body) });
    for (const id of ['m-weight', 'm-waist', 'm-hips', 'm-thigh', 'm-chest', 'm-arm']) {
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
let category = 'body';
let style = null;
let programCode = null;
const doneExercises = new Set();
let restTimer = null;

function renderWorkouts(data) {
  const program = data.programs.find((p) => p.code === data.selected);
  document.getElementById('program-title').textContent = program ? program.title : 'Программа';
  document.getElementById('program-sub').textContent = program ? program.subtitle : '';
  document.getElementById('gym-count').textContent = data.week.workouts;
  document.getElementById('gym-kcal').textContent = data.week.calories;

  renderChips('category-switch', data.categories, category, (code) => {
    category = code;
    style = null;
    programCode = null;
    refreshWorkouts().catch((e) => toast(e.message));
  });
  renderChips('style-switch', data.styles, style, (code) => {
    style = style === code ? null : code;   // повторный тап снимает фильтр
    programCode = null;
    refreshWorkouts().catch((e) => toast(e.message));
  });
  renderChips(
    'program-switch',
    data.programs.map((p) => ({ code: p.code, label: p.title })),
    data.selected,
    (code) => {
      programCode = code;
      refreshWorkouts().catch((e) => toast(e.message));
    },
  );

  const note = document.getElementById('program-note');
  note.textContent = data.note || '';
  note.hidden = !data.note;
  document.getElementById('cardio-card').hidden = data.cardio.length === 0;

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

function renderChips(containerId, items, activeCode, onPick) {
  const box = document.getElementById(containerId);
  box.innerHTML = '';
  for (const item of items) {
    const button = document.createElement('button');
    button.className = `chip-btn${item.code === activeCode ? ' active' : ''}`;
    button.textContent = item.label;
    button.onclick = () => { haptic(); onPick(item.code); };
    box.appendChild(button);
  }
}

function exerciseRow(exercise, { cardio = false } = {}) {
  const done = doneExercises.has(exercise.id);
  const row = document.createElement('div');
  row.className = 'exercise';

  // Упражнение на время описывается подходами и секундами, а не повторами.
  const load = exercise.seconds_per_set
    ? `${exercise.sets} подхода по ${exercise.seconds_per_set} с`
    : `${exercise.sets}×${exercise.reps}`;
  const kcal = gym?.show_calories ? ` · ~${exercise.calories} ккал` : '';
  const detail = cardio
    ? `${exercise.minutes} мин${kcal}`
    : `${load} · отдых ${exercise.rest_seconds} с${kcal}`;

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
  const params = new URLSearchParams({ category });
  if (style) params.set('style', style);
  if (programCode) params.set('program', programCode);

  gym = await api(`/api/workouts?${params}`);
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
      `Ж ${Math.round(item.fat_g)} · У ${Math.round(item.carbs_g)}` +
      (item.fiber_g ? ` · 🥦 ${Math.round(item.fiber_g)}` : '');
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

/* --- «Расскажи, что происходит»: распознали → показали → сохранили --- */
let pendingMoment = null;

function toChat(hint) {
  toast(hint);
  haptic();
  setTimeout(() => tg?.close?.(), 900);
}

function openMoment() {
  pendingMoment = null;
  document.getElementById('moment-head').textContent = 'Что происходит?';
  document.getElementById('moment-input').hidden = false;
  document.getElementById('moment-result').hidden = true;
  document.getElementById('moment-sheet').hidden = false;
  document.getElementById('moment-text').focus();
}

function closeMoment() {
  document.getElementById('moment-sheet').hidden = true;
  document.getElementById('moment-text').value = '';
  pendingMoment = null;
}

const TRUST_NOTES = {
  high: 'Эти данные точно отражают твоё сообщение.',
  medium: 'Порция оценена приблизительно — поправь, если знаешь точнее.',
  low: 'Оценка грубая: скажи подробнее или поправь цифры.',
};
const TRUST_LABELS = { high: 'Высокая', medium: 'Средняя', low: 'Низкая' };

function renderFacts(facts) {
  const box = document.getElementById('moment-facts');
  box.innerHTML = '';
  for (const fact of facts) {
    const row = document.createElement('div');
    row.className = 'fact';
    row.innerHTML = `<div class="fact-icon"></div><div class="fact-label"></div>
                     <div class="fact-value"></div>`;
    row.querySelector('.fact-icon').textContent = fact.icon;
    row.querySelector('.fact-label').textContent = fact.label;
    row.querySelector('.fact-value').textContent = fact.value;

    if (fact.type && fact.type !== 'readonly') {
      const pencil = document.createElement('button');
      pencil.className = 'fact-edit';
      pencil.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M4 20h4l10-10-4-4L4 16z"/><path d="M13.5 6.5l4 4"/></svg>`;
      pencil.title = 'Поправить';
      pencil.onclick = () => editFact(row, fact);
      row.appendChild(pencil);
    }
    box.appendChild(row);
  }
}

/* Правка одного факта: значение превращается в поле, а после ввода
   момент пересобирает сервер — правила пересчёта живут только там. */
function editFact(row, fact) {
  const cell = row.querySelector('.fact-value');
  const editor = fact.type === 'choice'
    ? document.createElement('select')
    : document.createElement('input');
  editor.className = 'fact-input';

  if (fact.type === 'choice') {
    for (const option of fact.options || []) {
      const item = document.createElement('option');
      item.value = option;
      item.textContent = option;
      item.selected = option === fact.raw;
      editor.appendChild(item);
    }
  } else if (fact.type === 'time') {
    editor.type = 'time';
    editor.value = fact.raw;
  } else if (fact.type === 'text') {
    editor.type = 'text';
    editor.value = fact.raw;
  } else {
    editor.type = 'number';
    editor.value = fact.raw;
    editor.min = fact.type === 'score' ? 1 : 1;
    if (fact.type === 'score') editor.max = 10;
  }

  cell.replaceWith(editor);
  editor.focus();

  const apply = async () => {
    editor.onblur = null;
    await applyFact(fact, editor.value);
  };
  editor.onblur = apply;
  editor.onchange = () => { if (fact.type === 'choice' || fact.type === 'time') apply(); };
  editor.onkeydown = (e) => { if (e.key === 'Enter') editor.blur(); };
}

async function applyFact(fact, value) {
  const moment = pendingMoment;
  if (!moment) return;

  if (fact.key === 'weight_g') {
    // Вес тянет за собой всё остальное: пересчитываем порцию пропорционально.
    const next = Math.max(Number(value) || 0, 1);
    const ratio = next / (moment.food.weight_g || next);
    for (const key of ['calories', 'protein_g', 'fat_g', 'carbs_g', 'fiber_g']) {
      moment.food[key] = Math.round(moment.food[key] * ratio * 10) / 10;
    }
    moment.food.weight_g = next;
  } else if (fact.key === 'food_name') {
    moment.food.name = String(value).trim().slice(0, 60) || moment.food.name;
  } else if (fact.key === 'energy' || fact.key === 'focus') {
    moment[fact.key] = Math.min(Math.max(Number(value) || 1, 1), 10);
  } else if (fact.key === 'at') {
    moment.at = value;
  } else {
    moment[fact.key] = value;
  }

  try {
    const data = await api('/api/moment/facts', {
      method: 'POST', body: JSON.stringify({ moment }),
    });
    pendingMoment = data.moment;
    renderFacts(data.facts);
    haptic();
  } catch (e) {
    toast(e.message);
  }
}

async function recognizeMoment() {
  const text = document.getElementById('moment-text').value.trim();
  if (!text) { toast('Напиши пару слов'); return; }

  const button = document.getElementById('moment-send');
  button.disabled = true;
  button.textContent = 'Разбираю…';
  try {
    const data = await api('/api/moment', { method: 'POST', body: JSON.stringify({ text }) });
    pendingMoment = data.moment;

    document.getElementById('moment-head').textContent = 'Проверь момент';
    document.getElementById('moment-quote').textContent = text;
    renderFacts(data.facts);

    const trust = data.moment.food ? data.moment.food.confidence : 'high';
    document.getElementById('moment-trust').textContent = TRUST_LABELS[trust] || 'Средняя';
    document.getElementById('moment-trust-note').textContent =
      TRUST_NOTES[trust] || TRUST_NOTES.medium;

    document.getElementById('moment-input').hidden = true;
    document.getElementById('moment-result').hidden = false;
    haptic();
  } catch (e) {
    toast(e.message);
  } finally {
    button.disabled = false;
    button.textContent = 'Распознать';
  }
}

async function saveMoment() {
  if (!pendingMoment) return;
  const button = document.getElementById('moment-save');
  button.disabled = true;
  try {
    const result = await api('/api/moment/confirm', {
      method: 'POST', body: JSON.stringify({ moment: pendingMoment }),
    });
    closeMoment();
    haptic('medium');
    toast(result.saved.length ? `Записала: ${result.saved.join(' и ')}` : 'Записала');
    await refresh();
  } catch (e) {
    toast(e.message);
  } finally {
    button.disabled = false;
  }
}

/* --- загрузка и переключение вкладок --- */
async function refresh() {
  state = await api('/api/today');
  renderToday(state);
  renderGame(state.game);
  renderAwards(state.game?.awards);
  renderPills(state.supplements);
  // Награда и закрытое задание приходят от сервера ровно один раз — если не
  // показать их сейчас, пользователь о них не узнает.
  celebrate(state.game);
}

function switchScreen(name) {
  for (const tab of document.querySelectorAll('.tab')) {
    tab.classList.toggle('active', tab.dataset.screen === name);
  }
  for (const screen of ['today', 'world', 'gym', 'progress']) {
    document.getElementById(`screen-${screen}`).hidden = screen !== name;
  }
  // Кнопка ввода живёт на «Сегодня»: на других экранах она бы закрывала списки.
  document.getElementById('moment-open').classList.toggle('hidden-screen', name !== 'today');
  window.scrollTo(0, 0);

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
  document.getElementById('pill-form-toggle').onclick = () => {
    const form = document.getElementById('pill-form');
    form.hidden = !form.hidden;
  };

  document.getElementById('moment-open').onclick = openMoment;
  // Записать голос или снять фото умеет чат: там для этого есть всё, чего
  // мини-приложению не даёт Telegram. Поэтому просто уходим туда.
  document.getElementById('capture-voice').onclick = () => toChat('🎤 Зажми микрофон в чате и расскажи');
  document.getElementById('capture-photo').onclick = () => toChat('📷 Пришли фото еды в чат');
  document.getElementById('moment-close').onclick = closeMoment;
  document.getElementById('moment-send').onclick = recognizeMoment;
  document.getElementById('moment-save').onclick = saveMoment;
  document.getElementById('moment-edit').onclick = () => {
    document.getElementById('moment-input').hidden = false;
    document.getElementById('moment-result').hidden = true;
    document.getElementById('moment-head').textContent = 'Что происходит?';
  };
  for (const tab of document.querySelectorAll('.tab')) {
    tab.onclick = () => switchScreen(tab.dataset.screen);
  }
  for (const button of document.querySelectorAll('#metric-switch .chip-btn')) {
    button.onclick = () => {
      metric = button.dataset.metric;
      document.querySelectorAll('#metric-switch .chip-btn').forEach((b) => b.classList.remove('active'));
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
