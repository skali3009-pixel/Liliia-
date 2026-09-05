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
    // Подписка кончилась — показываем экран оплаты вместо любого другого ответа.
    if (response.status === 402 && body.need_subscription) {
      showPaywall(body);
      throw new Error('Подписка закончилась');
    }
    throw new Error(body.error || `Ошибка ${response.status}`);
  }
  return response.json();
}

function showPaywall(body) {
  const price = body.price_stars ? `${body.price_stars} ⭐ в месяц` : 'подписка';
  const trial = body.access?.is_trial;
  document.getElementById('paywall-title').textContent =
    trial ? 'Пробный период закончился' : 'Доступ закрыт';
  document.getElementById('paywall-text').textContent =
    `Всё записанное сохранено и ждёт тебя. Чтобы продолжить, оформи доступ — ` +
    `${price}. Счёт выставляет бот в чате.`;
  document.getElementById('paywall').hidden = false;
  document.getElementById('loading').hidden = true;
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
  [23, '🌙', 'Добрый вечер,\nдень почти собран.'],
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
    { key: 'energy', icon: '⚡', label: 'Энергия',
      value: state.energy ? `${state.energy}` : null, suffix: '/10' },
    { key: 'mood', icon: '🤍', label: 'Настроение', value: state.mood || null, text: true },
    { key: 'focus', icon: '🎯', label: 'Фокус',
      value: state.focus ? `${state.focus}` : null, suffix: '/10' },
    { key: 'stress', icon: '〰️', label: 'Стресс', value: state.stress || null, text: true },
  ];
  const grid = document.getElementById('state-grid');
  grid.innerHTML = '';
  for (const tile of tiles) {
    const box = document.createElement('div');
    box.className = 'state';
    box.onclick = () => openState(tile.key);
    const filled = tile.value !== null;
    box.innerHTML = `
      <div class="state-icon"></div>
      <div class="state-value"></div>
      <div class="state-label"></div>`;
    box.querySelector('.state-icon').textContent = tile.icon;
    const value = box.querySelector('.state-value');
    value.textContent = filled ? tile.value + (tile.suffix || '') : '＋';
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

/* --- Фигура тела на экране «Прогресс» -----------------------------------

   Силуэт не картинка, а расчёт: API отдаёт полуширины в долях высоты фигуры,
   поэтому тело меняется вместе с замерами, а фигура-цель отличается от
   нынешней ровно настолько, насколько отличается вес.
*/

/* Вертикальные ориентиры фигуры в системе координат 200 × 470.
   Расставлены по канону: макушка — пол это рост, талия на 64% от пола,
   промежность на 47%, колено на 24%. С «на глаз» фигура выглядит бочкой —
   проверено. */
const FIG = {
  cx: 100, top: 36, bottom: 446,
  bunY: 34, bunR: 10,
  headCy: 58, headRx: 16, headRy: 22,
  chin: 80, shoulder: 112, bust: 144, underbust: 166, waist: 186,
  hip: 232, crotch: 254, thighMid: 302, knee: 346, calf: 374, ankle: 428,
};
const FIG_H = FIG.bottom - FIG.top;

// Ширина системы координат одна на оба режима: иначе одинокая фигура
// растягивается на всю карточку и та прыгает в высоте при переключении.
const STAGE_W = 430;

let bodyMode = 'goal';
let bodyZone = 'waist';

const n1 = (value) => Math.round(value * 10) / 10;
const pt = (x, y) => `${n1(x)} ${n1(y)}`;
const between = (from, to, share) => from + (to - from) * share;

/* Половину контура задаём явно, вторая получается отражением — так фигура
   гарантированно симметрична, и править нужно только одну сторону. */
function mirrored(axis, start, segs) {
  const flip = ([x, y]) => [2 * axis - x, y];
  const out = [`M ${pt(...start)}`];
  for (const [c1, c2, end] of segs) out.push(`C ${pt(...c1)} ${pt(...c2)} ${pt(...end)}`);

  const last = segs.length ? segs[segs.length - 1][2] : start;
  out.push(`L ${pt(...flip(last))}`);
  for (let i = segs.length - 1; i >= 0; i--) {
    const prev = i ? segs[i - 1][2] : start;
    // У обратного кубика контрольные точки меняются местами.
    out.push(`C ${pt(...flip(segs[i][1]))} ${pt(...flip(segs[i][0]))} ${pt(...flip(prev))}`);
  }
  return `${out.join(' ')} Z`;
}

/* Конечность: опорные точки [y, центр, полуширина] сверху вниз. Центр может
   смещаться — так нога сходится к щиколотке, а рука идёт вдоль тела. */
function taperPath(stops) {
  const side = (sign, up) => {
    const list = up ? [...stops].reverse() : stops;
    const out = [];
    for (let i = 1; i < list.length; i++) {
      const [y0, c0, w0] = list[i - 1];
      const [y1, c1, w1] = list[i];
      const lean = (y1 - y0) * 0.4;
      out.push(`C ${pt(c0 + sign * w0, y0 + lean)} ${pt(c1 + sign * w1, y1 - lean)} ` +
               `${pt(c1 + sign * w1, y1)}`);
    }
    return out;
  };
  const first = stops[0];
  const last = stops[stops.length - 1];
  return [
    `M ${pt(first[1] + first[2], first[0])}`,
    ...side(1, false),
    `L ${pt(last[1] - last[2], last[0])}`,
    ...side(-1, true),
    'Z',
  ].join(' ');
}

/* Гладкая кривая через анатомические точки: Catmull-Rom переводим в
   кубические Безье. Так контур задаётся точками тела (подмышка, талия,
   гребень таза), а не подбором контрольных «усов» на глаз. */
function smoothHalf(points) {
  const segs = [];
  for (let i = 0; i < points.length - 1; i++) {
    const p0 = points[i - 1] || points[i];
    const p1 = points[i];
    const p2 = points[i + 1];
    const p3 = points[i + 2] || p2;
    segs.push([
      [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6],
      [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6],
      p2,
    ]);
  }
  return segs;
}

/* Торс по анатомии: трапеция от шеи к плечу, подмышка, грудная клетка,
   талия, гребень таза, бедро. Без промежуточных точек силуэт получается
   мешком — талия и таз должны быть разными событиями на контуре. */
function torsoPath(s) {
  const c = FIG.cx;
  const sh = s.shoulder * FIG_H;
  const bu = s.bust * FIG_H;
  const wa = s.waist * FIG_H;
  const hi = s.hip * FIG_H;

  const points = [
    [c, FIG.chin + 2],
    [c + sh * 0.42, FIG.shoulder - 12],          // скат трапеции
    [c + sh * 0.86, FIG.shoulder + 6],           // точка плеча
    [c + bu * 0.94, FIG.bust - 24],              // подмышка
    [c + bu, FIG.bust + 2],                      // грудь, самое широкое
    [c + bu * 0.84, FIG.underbust],              // под грудью
    [c + wa, FIG.waist],                         // талия
    [c + wa * 1.1, FIG.waist + 20],              // гребень таза
    [c + hi, FIG.hip],                           // бедро, самое широкое
    [c + hi * 0.94, FIG.crotch - 12],
    [c + hi * 0.72, FIG.crotch + 2],
  ];
  return mirrored(c, points[0], smoothHalf(points));
}

/* Нога по анатомии: бедро, надколенная впадина, колено, икра выше
   середины голени, тонкая щиколотка. На четырёх точках нога выходит
   конусом — а конус не читается как нога. */
function legStops(s, side) {
  const hi = s.hip * FIG_H;
  const th = s.thigh * FIG_H;
  const top = FIG.cx + side * hi * 0.44;
  const foot = FIG.cx + side * hi * 0.36;
  const at = (y) => between(top, foot, (y - FIG.crotch) / (FIG.ankle - FIG.crotch));
  const p = (y, w) => [y, at(y), th * w];
  return [
    p(FIG.crotch - 16, 0.99),
    p(FIG.thighMid, 0.9),
    p(FIG.knee - 16, 0.62),      // над коленом нога уже самого колена
    p(FIG.knee, 0.58),
    p(FIG.knee + 12, 0.55),
    p(FIG.calf, 0.64),           // икра — выше середины голени
    p(FIG.calf + 26, 0.46),
    p(FIG.ankle, 0.26),
  ];
}

/* Рука отведена от тела чуть сильнее, чем в жизни. Это сознательно: если
   опустить её анатомически близко, рука закрывает талию и бёдра — то самое,
   ради чего фигуру и рисуем. В макете руки тоже висят с просветом. */
function armStops(s, side) {
  const sh = s.shoulder * FIG_H;
  const ar = s.arm * FIG_H;
  const hi = s.hip * FIG_H;
  const top = FIG.cx + side * (sh - ar * 0.3);
  const wrist = FIG.cx + side * Math.max(hi + ar * 0.2, sh + ar * 0.6);
  const wristY = FIG.crotch - 4;
  const at = (y) => between(top, wrist, (y - FIG.shoulder) / (wristY - FIG.shoulder));
  const p = (y, w) => [y, at(y), ar * w];
  return [
    p(FIG.shoulder - 2, 0.98),
    p(FIG.bust - 6, 0.94),         // бицепс
    p(FIG.underbust + 8, 0.74),    // над локтем
    p(FIG.waist + 6, 0.7),         // локоть
    p(FIG.hip - 14, 0.62),         // предплечье
    p(wristY, 0.42),               // запястье
  ];
}

/* Тело собирается из отдельных форм с общей заливкой: в глазах они
   сливаются в один силуэт, но каждая живёт по своему замеру. */
function bodyShapes(s) {
  const bu = s.bust * FIG_H;
  const th = s.thigh * FIG_H;
  const ar = s.arm * FIG_H;
  const neck = s.neck * FIG_H;
  const legs = [-1, 1].map((side) => legStops(s, side));
  const arms = [-1, 1].map((side) => armStops(s, side));

  const parts = [
    // Пучок волос: две формы вместо шарика — так это причёска, а не мяч.
    `<ellipse cx="${FIG.cx}" cy="${FIG.bunY}" rx="${n1(FIG.bunR * 1.15)}" ` +
      `ry="${n1(FIG.bunR * 0.9)}"/>`,
    `<ellipse cx="${FIG.cx}" cy="${n1(FIG.bunY + 9)}" rx="${n1(FIG.headRx * 0.95)}" ry="9"/>`,
    `<ellipse cx="${FIG.cx}" cy="${FIG.headCy}" rx="${FIG.headRx}" ry="${FIG.headRy}"/>`,
    `<path d="${taperPath([
      [FIG.chin - 8, FIG.cx, neck],
      [FIG.shoulder + 2, FIG.cx, neck * 1.45],
    ])}"/>`,
    `<path d="${torsoPath(s)}"/>`,
  ];
  for (const stops of legs) {
    const foot = stops[stops.length - 1];
    parts.push(`<path d="${taperPath(stops)}"/>`);
    // Стопа перекрывает срез голени, иначе она висит отдельным камешком.
    parts.push(`<ellipse cx="${n1(foot[1])}" cy="${FIG.bottom - 7}" ` +
               `rx="${n1(th * 0.32)}" ry="7"/>`);
  }
  for (const stops of arms) {
    const top = stops[0];
    const hand = stops[stops.length - 1];
    // Круглая «дельта» на плече: без неё верх руки срезан по прямой и на
    // контуре видна горизонтальная черта поперёк плеча.
    parts.push(`<circle cx="${n1(top[1])}" cy="${n1(top[0] + 4)}" r="${n1(top[2] * 0.86)}"/>`);
    parts.push(`<path d="${taperPath(stops)}"/>`);
    parts.push(`<ellipse cx="${n1(hand[1])}" cy="${n1(hand[0] + 7)}" ` +
               `rx="${n1(ar * 0.45)}" ry="8"/>`);
  }
  return parts.join('');
}

/* Объём: мягкие блики поверх силуэта. Именно они отличают «фигуру» от
   плоского пятна — грудь, живот и бёдра должны быть выпуклыми. */
function bodyVolume(s) {
  const bu = s.bust * FIG_H;
  const wa = s.waist * FIG_H;
  const hi = s.hip * FIG_H;
  const th = s.thigh * FIG_H;
  const legs = [-1, 1].map((side) => legStops(s, side));

  const parts = [
    // Грудь
    `<ellipse cx="${n1(FIG.cx - bu * 0.42)}" cy="${n1(FIG.bust - 2)}" ` +
      `rx="${n1(bu * 0.36)}" ry="${n1(bu * 0.32)}"/>`,
    `<ellipse cx="${n1(FIG.cx + bu * 0.42)}" cy="${n1(FIG.bust - 2)}" ` +
      `rx="${n1(bu * 0.36)}" ry="${n1(bu * 0.32)}"/>`,
    // Живот и таз
    `<ellipse cx="${FIG.cx}" cy="${n1(FIG.waist + 26)}" ` +
      `rx="${n1(wa * 0.7)}" ry="${n1((FIG.hip - FIG.waist) * 0.62)}"/>`,
    // Ключицы — короткая мягкая дуга под шеей
    `<ellipse cx="${FIG.cx}" cy="${n1(FIG.shoulder + 10)}" ` +
      `rx="${n1(bu * 0.62)}" ry="6"/>`,
  ];
  for (const stops of legs) {
    const [topY, topX] = stops[0];
    parts.push(`<ellipse cx="${n1(topX)}" cy="${n1(FIG.thighMid - 10)}" ` +
               `rx="${n1(th * 0.6)}" ry="${n1((FIG.knee - topY) * 0.34)}"/>`);
  }
  return parts.join('');
}

/* Ноги вплотную сходятся у промежности: без тёмного шва они читаются одной
   тумбой. Линия идёт по оси и гаснет там, где ноги и так расходятся. */
function legSeam(s) {
  const th = s.thigh * FIG_H;
  return `<path class="fig-seam" d="M ${FIG.cx} ${n1(FIG.crotch - th * 0.45)} ` +
         `L ${FIG.cx} ${n1(FIG.thighMid + 24)}"/>`;
}

/* Ореол за головой, кольцо на полу и золотые точки — из макета. */
function figureDecor() {
  const floor = FIG.bottom - 2;
  // Размеры сняты с макета и переведены в систему координат сцены:
  // ореол r≈115 и эллипс пола 190×45 в исходнике — это 43 и 71×17 здесь.
  return `
    <circle cx="${FIG.cx}" cy="${FIG.headCy}" r="43" class="fig-halo"/>
    <circle cx="${FIG.cx}" cy="${FIG.headCy}" r="52" class="fig-halo dotted"/>
    <ellipse cx="${FIG.cx}" cy="${floor}" rx="71" ry="17" class="fig-ring"/>
    <ellipse cx="${FIG.cx}" cy="${floor}" rx="52" ry="12" class="fig-ring faint"/>
    <circle cx="${FIG.cx}" cy="10" r="2.6" class="fig-spark"/>
    <circle cx="${FIG.cx}" cy="30" r="1.8" class="fig-spark"/>
    <circle cx="${FIG.cx - 43}" cy="${FIG.headCy}" r="2.6" class="fig-spark"/>
    <circle cx="${FIG.cx + 43}" cy="${FIG.headCy}" r="2.6" class="fig-spark"/>
    <circle cx="${FIG.cx - 71}" cy="${floor}" r="2.6" class="fig-spark"/>
    <circle cx="${FIG.cx + 71}" cy="${floor}" r="2.6" class="fig-spark"/>`;
}

/* Вертикальные панели по краям сцены — как в макете. Скругление только по
   внутреннему краю: снаружи панель уходит за границу кадра. */
function stagePanels() {
  const w = 26;
  const inset = 14;
  const panel = (x, flip) =>
    `<rect class="fig-panel" x="${x}" y="${inset}" width="${w}" height="${470 - inset * 2}" ` +
    `rx="13" ry="13" transform="${flip ? `translate(${x * 2 + w} 0) scale(-1 1)` : ''}"/>`;
  return panel(-8, false) + panel(STAGE_W - w + 8, true);
}

/* --- Рисованная фигура из макета ----------------------------------------

   Тело — не набор кривых, а картинка, которую Лилия сделала сама. Чтобы она
   не осталась просто украшением, картинка растягивается по строкам: каждая
   строка пикселей сжимается или расширяется по своему коэффициенту, и
   рисунок принимает пропорции конкретного тела.

   Голова, шея и стопы не трогаются (там коэффициент 1) — тянется только то,
   что и правда меняется от веса. */

const ART = {
  src: '/static/img/body.webp', w: 340, h: 1172, crown: 34,
  // Стопы — это пальцы, а не нижний край картинки: ниже идёт отражение в
  // полу, и если считать его частью тела, фигура повисает над кольцом.
  feet: 1068,
  // Центр — по торсу, а не по габаритам кадра: обрезка вышла несимметричной,
  // и по габаритам фигура уезжает вбок от колец и пола.
  cx: 142,
  // Пропорции самой нарисованной фигуры в долях её роста: по ним ложится
  // подсветка зон. Свет в картинке падает слева, правый контур почти не
  // читается — числа сняты по левому краю и симметрии, потом выверены
  // рендером.
  zones: {
    bust: 0.082, waist: 0.070, hip: 0.092,
    thigh: { dx: 0.036, w: 0.032 },
    arm: { dx: 0.082, w: 0.016 },
  },
};

// Доля высоты тела → какая зона там находится. Совпадает с ориентирами FIG,
// поэтому подсветка зон ложится ровно на картинку.
const WARP_STOPS = [
  [0.00, null], [0.17, null], [0.20, null],
  [0.264, 'bust'], [0.366, 'waist'], [0.478, 'hip'], [0.649, 'thigh'],
  [0.86, 'calf'], [1.00, null],
];

function warpAt(warp, t) {
  const value = (zone) => {
    if (zone === null) return 1;
    // Икра меняется слабее бедра: к щиколотке растяжение сходит на нет.
    if (zone === 'calf') return 1 + ((warp.thigh || 1) - 1) * 0.35;
    return warp[zone] || 1;
  };
  for (let i = 1; i < WARP_STOPS.length; i++) {
    const [t0, z0] = WARP_STOPS[i - 1];
    const [t1, z1] = WARP_STOPS[i];
    if (t <= t1 || i === WARP_STOPS.length - 1) {
      const share = t1 === t0 ? 0 : Math.min(Math.max((t - t0) / (t1 - t0), 0), 1);
      return between(value(z0), value(z1), share);
    }
  }
  return 1;
}

let artPromise = null;

function loadArt() {
  if (artPromise) return artPromise;
  artPromise = new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve(img);
    // Картинки нет — рисуем фигуру кривыми, экран не должен остаться пустым.
    img.onerror = () => resolve(null);
    img.src = ART.src;
  });
  return artPromise;
}

/* Одна фигура на холст: строка исходника → строка на экране со своим
   горизонтальным масштабом. Высота строки берётся с запасом, иначе между
   строками остаются волосяные щели. */
function paintFigure(ctx, img, { dx, warp, alpha, unit }) {
  const bodyPx = (FIG.bottom - FIG.top) * unit;
  const k = bodyPx / (ART.feet - ART.crown);
  const cxDst = (FIG.cx + dx) * unit;
  const topDst = FIG.top * unit;

  // Полупрозрачную фигуру собираем на отдельном холсте и накладываем одним
  // куском. Если гасить каждую строку по отдельности, соседние строки
  // перекрываются на пиксель и смешиваются дважды — по телу идут полосы.
  const solo = alpha < 1;
  let target = ctx;
  if (solo) {
    const buffer = document.createElement('canvas');
    buffer.width = ctx.canvas.width;
    buffer.height = ctx.canvas.height;
    target = buffer.getContext('2d');
  }

  for (let sy = 0; sy < ART.h; sy++) {
    const t = (sy - ART.crown) / (ART.feet - ART.crown);
    const scale = warpAt(warp, Math.min(Math.max(t, 0), 1));
    target.drawImage(
      img, 0, sy, ART.w, 1,
      cxDst - ART.cx * k * scale, topDst + (sy - ART.crown) * k,
      ART.w * k * scale, k + 1,
    );
  }

  if (solo) {
    ctx.globalAlpha = alpha;
    ctx.drawImage(target.canvas, 0, 0);
    ctx.globalAlpha = 1;
  }
}

async function paintStage(data) {
  const canvas = document.getElementById('fig-canvas');
  if (!canvas) return;
  const img = await loadArt();
  if (!img) return;

  const box = canvas.getBoundingClientRect();
  const ratio = Math.min(window.devicePixelRatio || 1, 2.5);
  canvas.width = Math.round(box.width * ratio);
  canvas.height = Math.round(box.height * ratio);

  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const unit = canvas.width / STAGE_W;

  const single = bodyMode === 'zones' || !data.goal;
  paintFigure(ctx, img, {
    dx: single ? STAGE_W / 2 - FIG.cx : 0,
    warp: data.warp || {}, alpha: 1, unit,
  });
  if (!single) {
    paintFigure(ctx, img, { dx: 230, warp: data.goal_warp || {}, alpha: 0.62, unit });
  }
}

let figureSeq = 0;

/* Где на теле проходят зоны. Для нарисованной фигуры — из пропорций самой
   картинки, растянутых теми же коэффициентами; для запасного силуэта — из
   его собственных полуширин. Иначе подсветка съезжает с тела. */
function zoneGeometry(figure, warp) {
  if (warp) {
    const k = (value, zone) => value * FIG_H * (warp[zone] || 1);
    return {
      bust: k(ART.zones.bust, 'bust'),
      waist: k(ART.zones.waist, 'waist'),
      hip: k(ART.zones.hip, 'hip'),
      thigh: { dx: k(ART.zones.thigh.dx, 'thigh'), w: k(ART.zones.thigh.w, 'thigh') },
      arm: { dx: k(ART.zones.arm.dx, 'arm'), w: k(ART.zones.arm.w, 'arm') },
    };
  }
  const hip = figure.hip * FIG_H;
  return {
    bust: figure.bust * FIG_H,
    waist: figure.waist * FIG_H,
    hip,
    thigh: { dx: hip * 0.44, w: figure.thigh * FIG_H },
    arm: { dx: figure.shoulder * FIG_H - figure.arm * FIG_H * 0.3, w: figure.arm * FIG_H },
  };
}

/* Подсветка зон из второго макета: полосы на талии, груди и бёдрах,
   панели на руках и ногах. Выбранная зона горит, остальные приглушены. */
function zoneShapes(geometry, active) {
  const wrap = (code, inner) =>
    `<g class="zone${code === active ? ' on' : ''}" data-zone="${code}">${inner}</g>`;

  const band = (code, y, halfWidth) => wrap(code,
    `<ellipse cx="${FIG.cx}" cy="${y}" rx="${n1(halfWidth + 4)}" ry="7"/>` +
    `<ellipse cx="${FIG.cx}" cy="${y}" rx="${n1(halfWidth + 4)}" ry="7" class="dotted"/>`);

  /* Подсветка конечности — толстая линия по её оси со скруглёнными концами:
     она повторяет форму руки или бедра, а не рисует коробку поперёк. */
  const limbs = (code, part, y0, y1) => wrap(code,
    [-1, 1].map((side) => {
      const cx = FIG.cx + side * part.dx;
      return `<path class="zone-cap" d="M ${pt(cx, y0)} L ${pt(cx, y1)}" ` +
             `stroke-width="${n1(part.w * 2 + 4)}"/>`;
    }).join(''));

  return [
    limbs('arm', geometry.arm, FIG.shoulder + 10, FIG.bust + 34),
    band('bust', FIG.bust, geometry.bust),
    band('waist', FIG.waist, geometry.waist),
    band('hip', FIG.hip, geometry.hip),
    limbs('thigh', geometry.thigh, FIG.crotch - 6, FIG.thighMid + 4),
  ].join('');
}

function figureGroup(s, { dx = 0, dim = false, zones = '' } = {}) {
  const shapes = bodyShapes(s);
  const clip = `fig-clip-${figureSeq++}`;
  // Самая широкая точка фигуры — внешний край руки: по ней растягиваем
  // градиент тени, чтобы её края совпали с краями тела.
  const half = Math.max(...armStops(s, 1).map(([, cx, w]) => cx - FIG.cx + w));
  // Отражение под полом: тот же силуэт, сжатый и почти прозрачный.
  const mirror = FIG.bottom + 0.35 * FIG.bottom;
  // Контур берём фильтром по всей фигуре, а не обводкой каждой детали:
  // иначе внутри силуэта видны швы между рукой, торсом и шеей.
  return `
    <g transform="translate(${dx} 0)" class="figure${dim ? ' dim' : ''}">
      <clipPath id="${clip}">${shapes}</clipPath>
      ${figureDecor()}
      <g transform="translate(0 ${n1(mirror)}) scale(1 -0.35)" class="fig-mirror">${shapes}</g>
      <g class="fig-glow">${shapes}</g>
      <g class="fig-rim">${shapes}</g>
      <g class="fig-body">${shapes}</g>
      <!-- Свет на фигуре один, поэтому и тень одна: прямоугольник во всю
           ширину тела, обрезанный силуэтом. Если затенять каждую деталь
           отдельно, её собственные тёмные края видны швами внутри тела. -->
      <rect class="fig-shade" clip-path="url(#${clip})"
            x="${n1(FIG.cx - half)}" y="0" width="${n1(half * 2)}" height="470"/>
      <!-- Блики объёма обрезаем силуэтом, иначе живот вылезает за талию. -->
      <g class="fig-volume" clip-path="url(#${clip})">${bodyVolume(s)}</g>
      <g class="fig-body">${legSeam(s)}</g>
      ${zones}
    </g>`;
}

/* Фиолетовый поток между фигурами — из первого макета. */
function nebula(x) {
  const y = FIG.waist + 20;
  const curves = [
    [-104, 34, -44, -34, 40, 62, 104, -18, ''],
    [-96, 62, -34, 2, 40, 88, 96, 12, ' thin'],
    [-88, 6, -30, 54, 44, 22, 92, 48, ' thin'],
    [-72, 86, -20, 30, 36, 104, 84, 40, ' hair'],
  ].map(([x1, y1, c1x, c1y, c2x, c2y, x2, y2, extra]) =>
    `<path class="${extra.trim()}" d="M ${x + x1} ${y + y1} ` +
    `C ${x + c1x} ${y + c1y} ${x + c2x} ${y + c2y} ${x + x2} ${y + y2}"/>`).join('');

  const sparks = [[-58, -46], [-22, 14], [18, -34], [46, 40], [-70, 62], [66, -58],
                  [-8, 70], [34, 74]]
    .map(([sx, sy], index) =>
      `<circle cx="${x + sx}" cy="${y + sy}" r="${0.9 + (index % 3) * 0.5}" class="fig-spark"/>`)
    .join('');

  return `<g class="nebula">${curves}</g>${sparks}`;
}

const FIG_DEFS = `
  <defs>
    <!-- Заливка непрозрачная, прозрачность задаётся всей группе. Иначе в
         местах, где формы налезают друг на друга (шея на торс, дельта на
         руку, таз на бёдра), альфа складывается и по телу идут светлые швы. -->
    <!-- gradientUnits="userSpaceOnUse" обязателен: по умолчанию градиент
         считается по границам каждой формы, и тогда ноги начинаются заново
         со светлого — поперёк бёдер идёт резкая ступенька. Здесь свет течёт
         по всей фигуре от макушки до пола. -->
    <linearGradient id="fig-fill" gradientUnits="userSpaceOnUse"
                    x1="0" y1="${FIG.top}" x2="0" y2="${FIG.bottom}">
      <stop offset="0" stop-color="#CFC2FF"/>
      <stop offset="55%" stop-color="#8B5CF6"/>
      <stop offset="1" stop-color="#4C4BC4"/>
    </linearGradient>
    <!-- Скругление объёма: тёмные края, светлая полоса ближе к левому краю —
         так тело читается стеклянной трубкой, а не плоским пятном. -->
    <linearGradient id="fig-round" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#0A0912" stop-opacity=".45"/>
      <stop offset="16%" stop-color="#0A0912" stop-opacity=".06"/>
      <stop offset="36%" stop-color="#FFFFFF" stop-opacity=".14"/>
      <stop offset="66%" stop-color="#0A0912" stop-opacity=".06"/>
      <stop offset="1" stop-color="#0A0912" stop-opacity=".45"/>
    </linearGradient>
    <radialGradient id="fig-lume">
      <stop offset="0" stop-color="#EDEAFB" stop-opacity=".3"/>
      <stop offset="1" stop-color="#EDEAFB" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="fig-mirror-fill" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#C4B5FD" stop-opacity=".22"/>
      <stop offset="1" stop-color="#C4B5FD" stop-opacity="0"/>
    </linearGradient>
    <filter id="fig-blur" x="-40%" y="-40%" width="180%" height="180%">
      <feGaussianBlur stdDeviation="9"/>
    </filter>
    <!-- Кромка света по краю всей фигуры. Именно кольцо: расширенный силуэт
         минус исходный. Без вычитания фильтр заливает фигуру целиком —
         полупрозрачное тело поверх такую заливку не скрывает. -->
    <filter id="fig-rim" x="-20%" y="-20%" width="140%" height="140%">
      <feMorphology in="SourceAlpha" operator="dilate" radius="1.2" result="fat"/>
      <feComposite in="fat" in2="SourceAlpha" operator="out" result="ring"/>
      <feGaussianBlur in="ring" stdDeviation=".6" result="soft"/>
      <feFlood flood-color="#C9B8E8" flood-opacity=".85"/>
      <feComposite operator="in" in2="soft"/>
    </filter>
    <filter id="fig-blur-soft" x="-30%" y="-30%" width="160%" height="160%">
      <feGaussianBlur stdDeviation="3"/>
    </filter>
    <filter id="fig-nebula" x="-40%" y="-60%" width="180%" height="220%">
      <feGaussianBlur stdDeviation="6"/>
    </filter>
  </defs>`;

async function renderBody(data) {
  const stage = document.getElementById('body-stage');
  const note = document.getElementById('body-note');
  const chips = document.getElementById('body-zones');
  if (!data) { stage.innerHTML = ''; return; }

  note.textContent = data.estimated ? 'примерно — нет замеров' : '';

  // Если картинка не загрузилась, фигуру рисуем кривыми: экран прогресса
  // не должен оставаться пустым из-за одного файла.
  const art = await loadArt();
  const single = bodyMode === 'zones' || !data.goal;
  const middle = STAGE_W / 2 - FIG.cx;
  const drawn = (figure, options) => (art ? '' : figureGroup(figure, options));

  const overlay = `
    <svg class="fig-svg" viewBox="0 0 ${STAGE_W} 470" preserveAspectRatio="xMidYMid meet">
      ${FIG_DEFS}
      ${stagePanels()}
      ${!single && data.goal ? nebula(215) : ''}
      <g transform="translate(${single ? middle : 0} 0)">${figureDecor()}</g>
      ${!single ? `<g transform="translate(230 0)">${figureDecor()}</g>` : ''}
      ${drawn(data.now, { dx: single ? middle : 0 })}
      ${!single && data.goal ? drawn(data.goal, { dx: 230, dim: true }) : ''}
      ${bodyMode === 'zones'
        ? `<g transform="translate(${middle} 0)">` +
          `${zoneShapes(zoneGeometry(data.now, art ? data.warp : null), bodyZone)}</g>` : ''}
    </svg>`;

  if (bodyMode === 'zones') {
    chips.hidden = false;
    stage.innerHTML = `<div class="fig-wrap">
        <canvas id="fig-canvas" class="fig-canvas"></canvas>${overlay}
      </div>`;
    renderZoneChips(data.zones);
  } else {
    chips.hidden = true;
    stage.innerHTML = `
      <div class="fig-wrap">
        <canvas id="fig-canvas" class="fig-canvas"></canvas>${overlay}
      </div>
      <div class="fig-captions${data.goal ? '' : ' single'}">
        <div><b>Сейчас</b><span>${progress?.summary?.current_weight
          ? `${fmt(progress.summary.current_weight)} кг` : 'вес не записан'}</span></div>
        ${data.goal ? `<div><b>Цель</b><span>${fmt(progress.summary.target_weight)} кг</span></div>` : ''}
      </div>
      ${data.goal ? '' : '<p class="hint">Поставь цель по весу в анкете — покажу, ' +
        'как будет выглядеть фигура.</p>'}`;
  }

  await paintStage(data);

  renderInsights(data.insights);
  for (const group of stage.querySelectorAll('.zone')) {
    group.onclick = () => {
      bodyZone = group.dataset.zone;
      const zone = (data.zones || []).find((item) => item.code === bodyZone);
      if (zone) setMetric(zone.metric);
      renderBody(data);
    };
  }
}

function renderZoneChips(zones) {
  const box = document.getElementById('body-zones');
  box.innerHTML = '';
  for (const zone of zones || []) {
    const button = document.createElement('button');
    button.className = `chip-btn${zone.code === bodyZone ? ' active' : ''}`;
    button.textContent = zone.has_data ? `${zone.label} ${fmt(zone.value)}` : zone.label;
    button.onclick = () => {
      bodyZone = zone.code;
      setMetric(zone.metric);
      renderBody(progress.body);
    };
    box.appendChild(button);
  }
}

function renderInsights(items) {
  const box = document.getElementById('body-insights');
  box.innerHTML = '';
  for (const item of items || []) {
    const row = document.createElement('div');
    row.className = 'insight';
    row.innerHTML = '<div class="insight-icon"></div><div class="insight-main">' +
      '<div class="insight-title"></div><div class="insight-text"></div></div>';
    row.querySelector('.insight-icon').textContent = item.icon;
    row.querySelector('.insight-title').textContent = item.title;
    row.querySelector('.insight-text').textContent = item.text;
    box.appendChild(row);
  }
}

/* Выбор зоны переключает и график: нажал на талию — видишь её динамику. */
function setMetric(next) {
  if (metric === next) return;
  metric = next;
  for (const button of document.querySelectorAll('#metric-switch .chip-btn')) {
    button.classList.toggle('active', button.dataset.metric === next);
  }
  refreshProgress().catch((e) => toast(e.message));
}

async function refreshProgress() {
  progress = await api(`/api/progress?metric=${metric}&period=${period}`);

  const s = progress.summary;
  document.getElementById('stat-weight').textContent = s.current_weight ? fmt(s.current_weight) : '—';
  document.getElementById('stat-change').textContent =
    s.changed > 0 ? `+${fmt(s.changed)}` : fmt(s.changed || 0);
  document.getElementById('stat-streak').textContent = s.streak;
  document.getElementById('stat-streak-label').textContent =
    `${plural(s.streak, 'день', 'дня', 'дней')} подряд`;
  document.getElementById('chart-title').textContent = progress.title;

  renderBody(progress.body);
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
  document.getElementById('gym-count-label').textContent =
    plural(data.week.workouts, 'тренировка', 'тренировки', 'тренировок');
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

/* --- Быстрая отметка состояния прямо с плитки --- */
const STATE_FIELDS = {
  energy: {
    title: 'Энергия',
    hint: '1 — на нуле, 10 — полна сил. Отметится текущим временем.',
    scale: 10,
  },
  focus: {
    title: 'Фокус',
    hint: '1 — мысли разбегаются, 10 — собрана.',
    scale: 10,
  },
  mood: {
    title: 'Настроение',
    hint: 'Выбери то, что ближе всего.',
    options: ['спокойно', 'бодро', 'радостно', 'устала', 'тревожно', 'грустно', 'раздражённо'],
  },
  stress: {
    title: 'Стресс',
    hint: 'Насколько напряжённым получился день.',
    options: ['низкий', 'средний', 'высокий'],
  },
};

function openState(key) {
  const field = STATE_FIELDS[key];
  if (!field) return;

  document.getElementById('state-head').textContent = field.title;
  document.getElementById('state-hint').textContent = field.hint;

  const box = document.getElementById('state-options');
  box.innerHTML = '';
  const current = state?.state?.[key];
  const values = field.scale
    ? Array.from({ length: field.scale }, (_, i) => i + 1)
    : field.options;

  for (const value of values) {
    const button = document.createElement('button');
    button.className = `state-opt${field.options ? ' wide' : ''}` +
      (String(value) === String(current) ? ' on' : '');
    button.textContent = value;
    button.onclick = () => saveState(key, value);
    box.appendChild(button);
  }
  document.getElementById('state-sheet').hidden = false;
}

async function saveState(key, value) {
  try {
    await api('/api/checkin', { method: 'POST', body: JSON.stringify({ [key]: value }) });
    document.getElementById('state-sheet').hidden = true;
    haptic('medium');
    toast(`${STATE_FIELDS[key].title}: ${value}`);
    await refresh();
  } catch (e) {
    toast(e.message);
  }
}

/* --- «Расскажи, что происходит»: распознали → показали → сохранили --- */
let pendingMoment = null;

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

/* --- живой фон: арт отстаёт от прокрутки --- */
const PARALLAX_DEPTH = 0.22;   // насколько медленнее арта едет за экраном
const PARALLAX_LIMIT = 56;     // дальше сдвигать некуда: под артом пустота

function moveArt() {
  const shift = Math.min(window.scrollY * PARALLAX_DEPTH, PARALLAX_LIMIT);
  for (const art of document.querySelectorAll('.hero-art, .world-art')) {
    art.style.transform = `translate3d(0, ${shift.toFixed(1)}px, 0)`;
  }
}

function startParallax() {
  // Кому анимация мешает — тому неподвижная картинка.
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  let ticking = false;
  const onScroll = () => {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(() => { moveArt(); ticking = false; });
  };
  window.addEventListener('scroll', onScroll, { passive: true });
  moveArt();
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
  moveArt();

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
  document.getElementById('paywall-open').onclick = () => tg?.close?.();
  document.getElementById('state-close').onclick = () => {
    document.getElementById('state-sheet').hidden = true;
  };
  startParallax();
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
  for (const button of document.querySelectorAll('#body-switch .seg-btn')) {
    button.onclick = () => {
      bodyMode = button.dataset.body;
      document.querySelectorAll('#body-switch .seg-btn').forEach((b) => b.classList.remove('active'));
      button.classList.add('active');
      renderBody(progress?.body);
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
    if (e.message.includes('Подписка')) return;   // экран оплаты уже показан
    document.getElementById('loading').textContent =
      e.message.includes('Профиль')
        ? 'Сначала пройди анкету в чате: /start'
        : `Не удалось загрузить: ${e.message}`;
  }
}

init();
