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
  document.getElementById('screen-pills').hidden = name !== 'pills';
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
