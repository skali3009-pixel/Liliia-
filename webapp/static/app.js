/* Логика мини-приложения. Данные берём из того же API, что и бот, —
   база одна, так что съеденное появляется здесь сразу после фото в чате. */

const tg = window.Telegram?.WebApp;
const RING_LENGTH = 327; // длина окружности радиуса 52
const DIAL_LENGTH = 113; // длина окружности радиуса 18
const RING_LENGTH_SMALL = RING_LENGTH; // кольцо шагов того же радиуса, меньше размером

let state = null;

/* --- обращения к серверу: подпись Telegram уходит в заголовке --- */
function deviceZone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || '';
  } catch (e) {
    return '';
  }
}

/* --- Поломка в самом приложении ---------------------------------------- */
// Ошибка на сервере видна в логах, ошибка здесь — нигде: человек смотрит на
// пустой экран, а у бота всё в порядке. Поэтому сообщаем о ней сами.
// Не больше трёх за открытие: сломанный экран умеет сыпать ошибками без
// конца, а повторы одной и той же поломки отсекает уже сервер. Трёх хватает,
// чтобы не потерять вторую, настоящую, ошибку за первой.
const CRASH_LIMIT = 3;
let crashCount = 0;

function reportCrash(message, place) {
  if (crashCount >= CRASH_LIMIT || !message) return;
  crashCount += 1;
  try {
    fetch('/api/crash', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Telegram-Init-Data': tg?.initData || '',
        'X-Timezone': deviceZone(),
      },
      body: JSON.stringify({
        message: String(message).slice(0, 300),
        place: String(place || '').slice(0, 300),
        screen: document.querySelector('.tab.active')?.dataset.screen || 'приложение',
      }),
      // Отчёт не должен мешать: ответ нам не нужен и ошибка его отправки тоже.
      keepalive: true,
    }).catch(() => {});
  } catch (error) {
    // Сообщение о поломке не имеет права ломать что-то ещё.
  }
}

window.addEventListener('error', (event) => {
  // Файл известен не всегда: без него строка «:1» выглядит поломкой сама.
  const place = event.filename ? `${event.filename}:${event.lineno || '?'}` : '';
  reportCrash(event.message, place);
});
window.addEventListener('unhandledrejection', (event) => {
  const reason = event.reason;
  reportCrash(reason?.message || reason, reason?.stack?.split('\n')[1]?.trim());
});


async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'X-Telegram-Init-Data': tg?.initData || '',
      // Часовой пояс знает браузер — спрашивать его у человека незачем.
      'X-Timezone': deviceZone(),
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

  const line = data.profile?.line || '';
  document.getElementById('day-line-text').textContent = line;
  document.getElementById('day-line').hidden = !line;
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
  countTo(document.getElementById('kcal-left'),
          over ? totals.calories - norms.calories : left, { prefix: over ? '+' : '' });
  document.querySelector('.kcal-label').textContent = over ? 'ккал перебор' : 'ккал осталось';
  document.getElementById('kcal-sub').textContent =
    `${totals.calories} из ${norms.calories} ккал`;

  const ratio = norms.calories ? Math.min(totals.calories / norms.calories, 1) : 0;
  const ring = document.getElementById('ring-fill');
  markDone(ring.closest('.ring-wrap'), 'kcal', ratio >= 1 && !over);
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

  renderSteps(data.game && data.game.steps);
  renderHero(data);
  renderTimeline(data.timeline || []);
  renderFrequent(data.frequent || []);
}


/* --- Шаги --------------------------------------------------------------- */
// Число вносит человек: приложение внутри Telegram не имеет доступа ни к
// «Здоровью», ни к датчику шагов — это умеет только отдельное приложение
// из магазина. Поэтому здесь всё построено вокруг одной кнопки.

function renderSteps(steps) {
  if (!steps) return;
  countTo(document.getElementById('steps-value'), steps.today || 0);
  document.getElementById('steps-goal-label').textContent = `из ${steps.goal}`;

  const ring = document.getElementById('steps-fill');
  ring.style.strokeDashoffset = RING_LENGTH_SMALL * (1 - (steps.share || 0));
  markDone(ring.closest('.ring-wrap'), 'steps', Boolean(steps.done));

  document.getElementById('steps-left').textContent = steps.done
    ? 'Норма пройдена 👏'
    : steps.today
      ? `Осталось ${steps.left}`
      : 'Сегодня ещё не отмечено';
  document.getElementById('steps-week').textContent =
    `На этой неделе ${steps.week}` + (steps.best ? ` · лучший день ${steps.best}` : '');
  document.getElementById('steps-streak').textContent =
    steps.streak ? `🔥 ${steps.streak} ${plural(steps.streak, 'день', 'дня', 'дней')} с нормой` : '';
}

/* --- Дошла до цели ------------------------------------------------------- */
// Раньше в этот день не происходило ничего: приложение молча продолжало
// считать дефицит. Это не только обидно — так и уезжают в недоедание, не
// сорвавшись, а старательно продолжая делать то, что говорит приложение.

function showArrival(arrival) {
  const card = document.getElementById('arrival');
  if (!arrival) {
    card.hidden = true;
    return;
  }
  document.getElementById('arrival-text').textContent = arrival.text;
  document.getElementById('arrival-switch').hidden = !arrival.can_switch;
  card.hidden = false;
  card.scrollIntoView({ behavior: 'smooth', block: 'center' });
  haptic('medium');
}

async function switchToMaintain() {
  try {
    const data = await api('/api/profile', {
      method: 'PATCH', body: JSON.stringify({ goal: 'maintain' }),
    });
    document.getElementById('arrival').hidden = true;
    toast(`Теперь поддержание: ${data.norms.calories} ккал`);
    await refresh();
  } catch (error) {
    toast(error.message);
  }
}


/* --- Чтобы шаги приходили сами ------------------------------------------ */
// Вбивать число каждый день не будет почти никто, а без шагов не работает
// ничего вокруг них. Читать «Здоровье» из Telegram нельзя — но телефон умеет
// присылать шаги сам, по расписанию. Здесь ссылка и инструкция к ней.

// Шаги с телефона: ссылка, инструкция, проверка связи.
//
// Приложение внутри Telegram не может прочитать «Здоровье» — такого доступа
// у веб-страницы нет ни на одном телефоне. Присылает телефон, и вся работа
// здесь — сделать эту настройку выполнимой.

let syncData = null;      // ответ сервера: ссылка, карточки, тексты
let guideAt = 0;          // на какой карточке инструкции человек стоит

async function openSync(renew = false) {
  const sheet = document.getElementById('sync-sheet');
  sheet.hidden = false;
  try {
    syncData = await api('/api/steps/sync',
      renew ? { method: 'POST', body: JSON.stringify({ renew: true }) } : {});
    const data = syncData;

    document.getElementById('sync-why').textContent = data.why;
    document.getElementById('sync-android').textContent = data.android;
    document.getElementById('sync-safety').textContent = data.safety;

    // Ссылку показываем только по просьбе: её фотографируют и пересылают,
    // не думая, что это ключ. Копировать можно и не видя её.
    const link = document.getElementById('sync-link');
    const show = document.getElementById('sync-show');
    const hide = () => {
      link.textContent = data.link ? maskLink(data.link) : data.no_site;
      show.textContent = 'Показать ссылку';
      show.dataset.open = '';
    };
    show.hidden = !data.link;
    show.onclick = () => {
      if (show.dataset.open) return hide();
      link.textContent = data.link;
      show.textContent = 'Скрыть';
      show.dataset.open = '1';
    };
    hide();

    const copy = document.getElementById('sync-copy');
    copy.hidden = !data.link;
    copy.onclick = () => {
      navigator.clipboard?.writeText(data.link);
      copy.textContent = 'Скопировано';
      haptic('medium');
    };
    copy.textContent = 'Скопировать личную ссылку';
    document.getElementById('sync-warn').hidden = !data.link;
    document.getElementById('sync-guide').hidden = !data.link;
    document.getElementById('sync-check').hidden = !data.link;
    document.getElementById('sync-renew').hidden = !data.link;
    document.getElementById('sync-state').hidden = true;
    document.getElementById('sync-now').hidden = true;

    const synced = document.getElementById('steps-synced');
    synced.hidden = !data.last;
    synced.textContent = data.last ? `Телефон присылал шаги ${data.last}` : '';
  } catch (error) {
    toast(error.message);
  }
}

// Ссылка на экране: видно, что она есть и что она наша, но не видно ключа.
function maskLink(link) {
  return link.replace(/\/hook\/steps\/[^?]+/, '/hook/steps/••••••');
}

// «Проверить подключение». Настройка длинная, и её итог человек должен
// узнать от нас, а не гадать до полуночи: молчание не отличить от поломки.
async function checkSync() {
  const box = document.getElementById('sync-state');
  const title = document.getElementById('sync-state-title');
  const note = document.getElementById('sync-state-note');
  title.textContent = 'Смотрю…';
  note.textContent = '';
  box.hidden = false;
  box.dataset.code = '';

  try {
    const state = await api('/api/steps/check');
    title.textContent = state.title;
    note.textContent = state.note;
    box.dataset.code = state.code;
    // Кнопку ручного запуска показываем только тому, у кого связь уже была:
    // остальным она предложила бы запустить несуществующую команду.
    document.getElementById('sync-now').hidden = state.code === 'never';
    if (state.ok) haptic('medium');
  } catch (error) {
    title.textContent = 'Не получилось проверить';
    note.textContent = error.message;
  }
}

// «Обновить шаги сейчас». Пытаемся запустить команду на телефоне по её
// имени. Сработает это или нет — зависит от телефона и от того, что
// разрешает Telegram, поэтому обещать ничего нельзя: через несколько
// секунд просто смотрим, изменилось ли число, и если нет — предлагаем
// вписать его руками.
const SYNC_WAIT_MS = 3500;

async function syncNow() {
  const name = encodeURIComponent((syncData && syncData.shortcut) || 'AURA Sync');
  const before = await api('/api/steps/check').catch(() => null);

  try {
    window.location.href = `shortcuts://run-shortcut?name=${name}`;
  } catch (error) {
    // Схему может не пустить сам webview — это не повод падать.
  }

  const button = document.getElementById('sync-now');
  button.disabled = true;
  button.textContent = 'Жду телефон…';
  await new Promise((resolve) => setTimeout(resolve, SYNC_WAIT_MS));
  button.disabled = false;
  button.textContent = 'Обновить шаги сейчас';

  const after = await api('/api/steps/check').catch(() => null);
  // «Пришло новое» — это либо более свежая отметка, либо другое число.
  // Отдельно считаем свежим ответ моложе минуты: два нажатия подряд дают
  // одинаковые «0 минут назад», и объявлять это молчанием телефона нельзя.
  const moved = after && before && after.minutes !== null
    && (before.minutes === null || after.minutes < before.minutes
        || after.steps !== before.steps);
  const fresh = after && after.minutes !== null && after.minutes <= 1;

  if (moved || fresh) {
    await checkSync();
    await refresh();
    toast('Шаги обновились');
    return;
  }

  document.getElementById('sync-state').hidden = false;
  document.getElementById('sync-state').dataset.code = 'zero';
  document.getElementById('sync-state-title').textContent = 'Телефон не ответил';
  document.getElementById('sync-state-note').textContent =
    'Такое бывает: запуск команд из Telegram работает не на всех телефонах. '
    + 'Запусти «' + ((syncData && syncData.shortcut) || 'AURA Sync')
    + '» в «Командах» — или впиши шаги руками.';
}

/* --- инструкция по одной карточке -------------------------------------- */

function openGuide() {
  guideAt = 0;
  document.getElementById('guide-sheet').hidden = false;
  renderGuide();
}

function renderGuide() {
  const cards = (syncData && syncData.cards) || [];
  const card = cards[guideAt];
  if (!card) return;

  document.getElementById('guide-title').textContent = card.title;
  document.getElementById('guide-lead').textContent = card.lead;

  const list = document.getElementById('guide-steps');
  list.innerHTML = '';
  for (const step of card.steps) {
    const item = document.createElement('li');
    item.textContent = step;
    list.appendChild(item);
  }

  const note = document.getElementById('guide-note');
  note.textContent = card.note || '';
  note.hidden = !card.note;
  // Непроверенное на живом телефоне помечаем — обещать то, чего не пробовали,
  // нельзя, а промолчать значит соврать.
  note.dataset.unverified = card.unverified ? '1' : '';

  document.getElementById('guide-count').textContent =
    `Шаг ${guideAt + 1} из ${cards.length}`;
  document.getElementById('guide-back').disabled = guideAt === 0;
  document.getElementById('guide-next').textContent =
    guideAt === cards.length - 1 ? 'Готово' : 'Дальше';
}

function guideStep(delta) {
  const cards = (syncData && syncData.cards) || [];
  if (guideAt + delta >= cards.length) {
    document.getElementById('guide-sheet').hidden = true;
    checkSync();
    return;
  }
  guideAt = Math.max(0, Math.min(guideAt + delta, cards.length - 1));
  haptic();
  renderGuide();
}

async function askSteps() {
  const current = document.getElementById('steps-value').textContent;
  // Кнопок с круглыми числами здесь нет намеренно: шаги переписывают с
  // телефона, и «8000» вместо 7412 — не удобство, а неправда в дневнике.
  const answer = await askNumber({
    title: 'Сколько шагов сегодня?',
    hint: 'Число из «Здоровья» на телефоне.',
    label: 'Шаги',
    value: current === '—' ? null : Number(current.replace(/\D/g, '')) || null,
    min: 0,
    max: 60000,
  });
  if (answer === null) return;
  try {
    const steps = await api('/api/steps', {
      method: 'POST',
      body: JSON.stringify({ steps: answer }),
    });
    renderSteps(steps);
    haptic('medium');
    // Задание дня могло закрыться — цифры и кристаллы должны это показать.
    await refresh();
  } catch (error) {
    toast(error.message);
  }
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

  // Три главных задания видно сразу, остальные — под кнопкой. Семь строк
  // подряд человек не читает, он их пролистывает.
  const box = document.getElementById('quests');
  const rest = document.getElementById('quests-more');
  const toggle = document.getElementById('quests-toggle');
  box.innerHTML = '';
  rest.innerHTML = '';

  // Закрытое только что видно отдельно: строка подсвечивается, а награда
  // улетает к кристаллу в шапке — иначе прибавка происходит где-то в стороне
  // и человек не связывает её с тем, что сделал.
  const justClosed = new Set(game.just_completed || []);
  const flying = [];
  for (const quest of game.quests) {
    const target = quest.main === false ? rest : box;
    const row = questRow(quest);
    if (justClosed.has(quest.code)) {
      row.classList.add('fresh');
      flying.push([row, `+${quest.xp} 💎`]);
    }
    target.appendChild(row);
  }
  // Ждём раскладку: до неё у строки нет координат, и лететь неоткуда.
  if (flying.length) {
    requestAnimationFrame(() => flying.forEach(([row, text], index) => {
      setTimeout(() => flyReward(row, text), index * 240);
    }));
  }

  const hidden = rest.children.length;
  toggle.hidden = hidden === 0;
  toggle.textContent = rest.hidden ? `Ещё задания (${hidden})` : 'Свернуть';
  toggle.onclick = () => {
    rest.hidden = !rest.hidden;
    toggle.textContent = rest.hidden ? `Ещё задания (${hidden})` : 'Свернуть';
  };
}

function questRow(quest) {
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
  return row;
}

/* --- «Твой ход»: одно действие, которое сейчас полезнее всего ------------- */
function renderCheetah(mood, prefix) {
  const line = document.getElementById(prefix);
  if (!mood) { line.hidden = true; return; }
  document.getElementById(`${prefix}-emoji`).textContent = mood.emoji;
  document.getElementById(`${prefix}-line`).textContent = mood.line;
  line.hidden = false;
}

function renderTurn(action) {
  const card = document.getElementById('turn');
  if (!action) {
    // Нечего предложить — карточки нет. Выдуманный совет хуже тишины.
    card.hidden = true;
    return;
  }

  document.getElementById('turn-text').textContent = action.text;
  const cta = document.getElementById('turn-cta');
  cta.textContent = action.cta;
  cta.disabled = false;
  cta.onclick = () => doTurn(action, cta);
  card.hidden = false;
}

async function doTurn(action, button) {
  // Каждое действие ведёт туда, где оно делается, а вода добавляется на месте:
  // ради стакана воды уводить человека на другой экран незачем.
  if (action.target === 'water') {
    button.disabled = true;
    try {
      await api('/api/water', {
        method: 'POST',
        body: JSON.stringify({ amount_ml: action.amount || 250 }),
      });
      await refresh();          // карточка пересчитается сразу
    } catch (error) {
      button.disabled = false;
      toast(error.message);
    }
    return;
  }

  if (action.target === 'steps') {
    // Без этого кнопка «Внести шаги» в «Твоём ходе» молча ничего не делала.
    askSteps();
    return;
  }

  const screens = { cube: 'cube', workout: 'gym', progress: 'progress' };
  if (screens[action.target]) {
    switchScreen(screens[action.target]);
    return;
  }
  if (action.target === 'meal') {
    document.getElementById('moment-open').click();
    return;
  }
  if (action.target === 'checkin') {
    document.querySelector('#state-grid .state')?.click();
  }
}

/* --- Движение ------------------------------------------------------------ */
// Частицы, летящие кристаллы и счётчики чисел. Всё здесь — только украшение:
// если оно не сработает, ни одна цифра и ни одна кнопка от этого не меняются.
// Поэтому ошибки внутри гасятся, а не всплывают наверх.
//
// Системная настройка «уменьшить движение» выключает весь блок целиком:
// человеку с чувствительностью к движению приложение должно остаться
// пригодным, а не просто «менее красивым».

const SPARK_COLORS = ['#C4B5FD', '#8B5CF6', '#5B6CFF', '#2DD4BF', '#C9A961'];
// Больше этого числа частиц на экране одновременно не держим: на слабом
// телефоне каждая — отдельный слой, и прокрутка начинает дёргаться.
const SPARK_LIMIT = 180;

function motion() {
  return !window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
}

function sparkLayer() {
  return document.getElementById('sparkle');
}

/** Взрыв частиц из точки экрана. Координаты — как у события мыши. */
function sparks(x, y, { count = 24, spread = 150, life = 1100, round = false } = {}) {
  const layer = sparkLayer();
  if (!motion() || !layer) return;
  const room = SPARK_LIMIT - layer.childElementCount;
  for (let i = 0; i < Math.min(count, room); i += 1) {
    const dot = document.createElement('i');
    dot.className = round ? 'spark round' : 'spark';
    const angle = Math.random() * Math.PI * 2;
    const far = spread * (0.35 + Math.random() * 0.65);
    const size = 5 + Math.random() * 6;
    dot.style.left = `${x}px`;
    dot.style.top = `${y}px`;
    dot.style.width = `${size}px`;
    dot.style.height = `${size}px`;
    dot.style.background = SPARK_COLORS[Math.floor(Math.random() * SPARK_COLORS.length)];
    dot.style.setProperty('--dx', `${Math.cos(angle) * far}px`);
    // Вниз чуть сильнее, чем вверх: без этого частицы висят кольцом и
    // выглядят как схема, а не как брызги.
    dot.style.setProperty('--dy', `${Math.sin(angle) * far + far * 0.4}px`);
    dot.style.setProperty('--spin', `${Math.round(Math.random() * 720 - 360)}deg`);
    dot.style.setProperty('--life', `${life + Math.random() * 400}ms`);
    dot.addEventListener('animationend', () => dot.remove());
    layer.appendChild(dot);
  }
}

/** Взрыв по центру элемента — чаще всего нужен именно он. */
function sparksAt(element, options) {
  if (!element) return;
  const box = element.getBoundingClientRect();
  if (!box.width && !box.height) return;
  sparks(box.left + box.width / 2, box.top + box.height / 2, options);
}

/** Кристалл коротко вспыхивает: пришла прибавка. */
function pulseCrystal() {
  const crystal = document.getElementById('crystal');
  if (!crystal || !motion()) return;
  crystal.classList.remove('gain');
  void crystal.offsetWidth;          // без этого второй раз подряд не сыграет
  crystal.classList.add('gain');
  crystal.addEventListener('animationend', () => crystal.classList.remove('gain'),
                           { once: true });
}

/** «+15 💎» улетает от карточки к кристаллу в шапке. */
function flyReward(from, text) {
  const to = document.getElementById('crystal');
  const layer = sparkLayer();
  if (!motion() || !from || !to || !layer) return;
  const a = from.getBoundingClientRect();
  const b = to.getBoundingClientRect();
  if (!a.width || !b.width) return;
  const chip = document.createElement('div');
  chip.className = 'fly';
  chip.textContent = text;
  chip.style.left = `${a.left + a.width / 2}px`;
  chip.style.top = `${a.top + a.height / 2}px`;
  chip.style.setProperty('--dx', `${b.left + b.width / 2 - a.left - a.width / 2}px`);
  chip.style.setProperty('--dy', `${b.top + b.height / 2 - a.top - a.height / 2}px`);
  chip.style.setProperty('--life', '950ms');
  chip.addEventListener('animationend', () => {
    chip.remove();
    pulseCrystal();
    sparksAt(to, { count: 14, spread: 70, life: 800, round: true });
  }, { once: true });
  layer.appendChild(chip);
}

/** Число не подставляется, а докручивается от того, что стояло раньше. */
function countTo(element, value, { prefix = '' } = {}) {
  if (!element) return;
  const target = Math.round(value);
  const from = parseInt(String(element.textContent).replace(/[^\d-]/g, ''), 10);
  if (!motion() || !Number.isFinite(from) || from === target) {
    element.textContent = prefix + target;
    return;
  }
  const started = performance.now();
  const span = 700;
  const step = (now) => {
    const share = Math.min((now - started) / span, 1);
    // Быстро в начале, мягко в конце — так число «доезжает», а не тормозит.
    const eased = 1 - (1 - share) ** 3;
    element.textContent = prefix + Math.round(from + (target - from) * eased);
    if (share < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

// Что уже было закрыто, когда экран рисовали в прошлый раз. Вспышка нужна
// в момент перехода «не закрыто → закрыто», а не при каждой перерисовке:
// иначе кольцо мигает после каждого стакана воды.
const doneBefore = {};

/** Кольцо коротко вспыхивает в тот раз, когда норма только что закрылась. */
function markDone(wrap, key, done) {
  const was = doneBefore[key];
  doneBefore[key] = done;
  if (!wrap || !motion() || !done || was !== false) return;
  wrap.classList.remove('done');
  void wrap.offsetWidth;
  wrap.classList.add('done');
  sparksAt(wrap, { count: 22, spread: 120, round: true });
  wrap.addEventListener('animationend', () => wrap.classList.remove('done'),
                        { once: true });
}

/** Карточки экрана въезжают каскадом. Повторный вход играет заново. */
function playEntrance(name) {
  const screen = document.getElementById(`screen-${name}`);
  if (!screen || !motion()) return;
  screen.classList.remove('enter');
  void screen.offsetWidth;
  screen.classList.add('enter');
}

// Круг от пальца. Один слушатель на всё приложение: вешать его на каждую
// кнопку — значит забыть про кнопки, которые рисуются кодом позже.
const RIPPLE_ON = '.btn, .chip, .food-mode, .cube-shop, .quick-act, .tab, .meal-tab';

function wireRipple() {
  document.addEventListener('pointerdown', (event) => {
    if (!motion()) return;
    const target = event.target.closest?.(RIPPLE_ON);
    if (!target || target.disabled) return;
    const box = target.getBoundingClientRect();
    const size = Math.max(box.width, box.height) * 2.2;
    const dot = document.createElement('span');
    dot.className = 'ripple';
    dot.style.width = `${size}px`;
    dot.style.height = `${size}px`;
    dot.style.left = `${event.clientX - box.left}px`;
    dot.style.top = `${event.clientY - box.top}px`;
    dot.addEventListener('animationend', () => dot.remove(), { once: true });
    target.appendChild(dot);
  }, { passive: true });
}

/* --- Быстрые действия ---------------------------------------------------- */
// Четыре самых частых шага дня одним касанием. Ничего нового они не умеют —
// это короткая дорога к тому, что и так есть ниже на экране.

function wireQuick() {
  document.getElementById('quick-food').onclick = () => switchScreen('cube');
  document.getElementById('quick-move').onclick = askSteps;
  document.getElementById('quick-water').onclick = async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      await addWater(250);
    } finally {
      button.disabled = false;
    }
  };
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

  // Находка — приятная мелочь, а не главное событие: тост, не окно.
  if (game.surprise) {
    setTimeout(() => {
      toast(`🎁 Гепард что-то нашёл: +${game.surprise} 💎`);
      haptic('medium');
      pulseCrystal();
      sparksAt(document.getElementById('crystal'),
               { count: 20, spread: 110, round: true });
    }, closed.length ? 2200 : 0);
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
    // Открытие — главное событие в приложении, и выглядеть должно так же.
    const card = pop.querySelector('.pop-card');
    setTimeout(() => sparksAt(card, { count: 44, spread: 260, life: 1500 }), 180);
    setTimeout(() => sparksAt(card, { count: 30, spread: 320, life: 1700 }), 620);
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
      const sure = await askYes({
        title: 'Убрать добавку?',
        text: `«${item.name}» пропадёт из списка. Отметки за прошлые дни `
          + 'останутся.',
        action: 'Убрать', danger: true,
      });
      if (!sure) return;
      await api(`/api/supplements/${item.id}`, { method: 'DELETE' });
      await refresh();
    };
    box.appendChild(row);
  }
}

/* --- действия --- */
async function editWeight(meal) {
  const value = await askNumber({
    title: 'Сколько граммов?',
    hint: `Порция «${meal.name}»`,
    choices: GRAM_CHOICES,
    unit: 'г',
    value: meal.weight_g,
    min: 5,
    max: 3000,
  });
  if (value === null) return;
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
  const sure = await askYes({
    title: 'Удалить запись?',
    text: `«${meal.name}» уйдёт из дневника, калории за день пересчитаются.`,
    action: 'Удалить', danger: true,
  });
  if (!sure) return;
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
    headers: { 'X-Telegram-Init-Data': tg?.initData || '', 'X-Timezone': deviceZone() },
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

/* Рельеф: чем стройнее тело, тем заметнее прорисовка пресса и бёдер.
   Это намёк на форму, а не обещание кубиков, поэтому линии мягкие и
   появляются постепенно — вместе с тем, как сходит объём. */
function relief(warp) {
  const lean = Math.min(Math.max((1 - (warp.waist || 1)) / 0.22, 0), 1);
  if (lean < 0.06) return '';

  const waist = ART.zones.waist * FIG_H * (warp.waist || 1);
  const hip = ART.zones.hip * FIG_H * (warp.hip || 1);
  const thigh = ART.zones.thigh;
  const c = FIG.cx;
  const line = (d, width) => `<path d="${d}" stroke-width="${width}"/>`;

  const ribs = [-1, 1].map((side) =>
    line(`M ${pt(c + side * waist * 0.62, FIG.underbust - 4)} ` +
         `Q ${pt(c + side * waist * 0.5, FIG.underbust + 12)} ` +
         `${pt(c + side * waist * 0.2, FIG.underbust + 18)}`, 1.4)).join('');

  const legs = [-1, 1].map((side) => {
    const cx = c + side * thigh.dx * FIG_H * (warp.thigh || 1);
    return line(`M ${pt(cx + side * thigh.w * FIG_H * 0.5, FIG.crotch + 6)} ` +
                `Q ${pt(cx + side * thigh.w * FIG_H * 0.7, FIG.thighMid)} ` +
                `${pt(cx + side * thigh.w * FIG_H * 0.35, FIG.knee - 12)}`, 1.3);
  }).join('');

  return `<g class="fig-relief" style="opacity:${n1(lean * 0.34)}">
    ${line(`M ${pt(c, FIG.bust + 26)} L ${pt(c, FIG.hip - 12)}`, 1.6)}
    ${ribs}
    ${line(`M ${pt(c - waist * 0.34, FIG.waist + 16)} ` +
           `Q ${pt(c, FIG.waist + 24)} ${pt(c + waist * 0.34, FIG.waist + 16)}`, 1.2)}
    ${legs}
  </g>`;
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
  src: '/static/img/body.webp', w: 380, h: 1037, crown: 24,
  // Стопы — это пальцы, а не нижний край картинки: ниже идёт отражение в
  // полу, и если считать его частью тела, фигура повисает над кольцом.
  feet: 1013,
  // Центр искали по голове: она узкая и симметричная. По ногам его сбивает
  // кольцо на полу, по габаритам кадра — остатки тумана сбоку. Из-за такой
  // ошибки в прошлой версии кадр срезал фигуре руку.
  cx: 190,
  // Пропорции самой нарисованной фигуры в долях её роста: по ним ложится
  // подсветка зон. Сняты по пикам яркости на контуре — на симметричной
  // картинке они читаются с обеих сторон и сходятся до третьего знака.
  zones: {
    bust: 0.086, waist: 0.085, hip: 0.112,
    thigh: { dx: 0.036, w: 0.033 },
    arm: { dx: 0.110, w: 0.021 },
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
      <g transform="translate(${single ? middle : 0} 0)">
        ${figureDecor()}${relief(data.warp || {})}</g>
      ${!single ? `<g transform="translate(230 0)">
        ${figureDecor()}${relief(data.goal_warp || {})}</g>` : ''}
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
  renderCycle(progress.cycle);

  const s = progress.summary;
  document.getElementById('stat-weight').textContent = s.current_weight ? fmt(s.current_weight) : '—';
  document.getElementById('stat-change').textContent =
    s.changed > 0 ? `+${fmt(s.changed)}` : fmt(s.changed || 0);
  countTo(document.getElementById('stat-streak'), s.streak);
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
    // Дошла до цели — об этом нельзя молчать, и спросить надо сразу.
    showArrival(result.arrival);
  } catch (e) { toast(e.message); }
}

async function uploadPhoto(file) {
  const form = new FormData();
  form.append('photo', file, 'photo.jpg');
  toast('Загружаю фото…');
  try {
    await fetch('/api/photos', {
      method: 'POST',
      headers: { 'X-Telegram-Init-Data': tg?.initData || '', 'X-Timezone': deviceZone() },
      body: form,
    }).then((r) => { if (!r.ok) throw new Error('Не удалось загрузить'); });
    haptic('medium');
    await refreshProgress();
  } catch (e) { toast(e.message); }
}


/* --- «Что-то не так» ---------------------------------------------------- */
// Падения бот ловит сам. Но «непонятно, куда нажимать» в логах выглядит
// безупречно — про это можно узнать только от человека.

function wireProblem() {
  const field = document.getElementById('prof-problem');
  const button = document.getElementById('prof-problem-send');
  const hint = document.getElementById('prof-problem-hint');
  if (!field || !button) return;

  button.onclick = async () => {
    const text = field.value.trim();
    if (!text) {
      field.focus();
      return;
    }
    button.disabled = true;
    try {
      await api('/api/feedback', {
        method: 'POST',
        body: JSON.stringify({
          text,
          screen: document.querySelector('.tab.active')?.dataset.screen || '',
        }),
      });
      field.value = '';
      hint.textContent = 'Передала. Спасибо — это правда помогает. 🐆';
      haptic('medium');
    } catch (error) {
      hint.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  };
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
  countTo(document.getElementById('gym-count'), data.week.workouts);
  document.getElementById('gym-count-label').textContent =
    plural(data.week.workouts, 'тренировка', 'тренировки', 'тренировок');
  countTo(document.getElementById('gym-kcal'), data.week.calories);

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
  renderGymWarning(data);

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

// Личные темы открываются только после прочитанного предупреждения.
// Согласие помним в этом браузере: спрашивать каждый раз — значит
// превратить заботу в препятствие.
const AGREED_KEY = 'aura.gym.agreed';

function agreedPrograms() {
  try {
    return new Set(JSON.parse(localStorage.getItem(AGREED_KEY) || '[]'));
  } catch (error) {
    return new Set();
  }
}

function rememberAgreement(code) {
  try {
    const agreed = agreedPrograms();
    agreed.add(code);
    localStorage.setItem(AGREED_KEY, JSON.stringify([...agreed]));
  } catch (error) {
    /* приватный режим — просто спросим ещё раз */
  }
}

function renderGymWarning(data) {
  const box = document.getElementById('gym-warning');
  const list = document.getElementById('exercises');
  const finish = document.getElementById('finish-workout');

  const needed = data.warning && !agreedPrograms().has(data.selected);
  box.hidden = !needed;
  list.hidden = !!needed;
  if (needed) finish.hidden = true;
  if (!needed) return;

  document.getElementById('gym-warning-text').textContent = data.warning;
  document.getElementById('gym-warning-ok').onclick = () => {
    rememberAgreement(data.selected);
    box.hidden = true;
    list.hidden = false;
  };
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

// Числа, которые приложение спрашивает у человека: минуты занятия, шаги
// за день, граммы в порции. Одно окно на все три — своё, а не системное
// окно браузера: то выглядит чужим, обрезает длинный вопрос на телефоне,
// не умеет подсказать привычные варианты и открывает обычную клавиатуру
// вместо цифровой.
const MINUTE_CHOICES = [15, 30, 45, 60, 90];
const GRAM_CHOICES = [50, 100, 150, 200, 300];

function askNumber({ title, hint = '', label = 'Своё число', choices = [],
                     unit = '', value = null, min = 1, max = 100000 }) {
  return new Promise((resolve) => {
    const sheet = document.getElementById('number-sheet');
    const box = document.getElementById('number-choices');
    const own = document.getElementById('number-own');
    const note = document.getElementById('number-hint');

    document.getElementById('number-title').textContent = title;
    document.getElementById('number-label').textContent = label;
    note.textContent = hint;
    note.hidden = !hint;
    box.innerHTML = '';
    box.hidden = choices.length === 0;
    own.value = value === null ? '' : String(value);
    own.min = min;
    own.max = max;

    const close = (result) => { sheet.hidden = true; resolve(result); };

    for (const item of choices) {
      const button = document.createElement('button');
      button.className = 'state-opt wide';
      button.textContent = unit ? `${item} ${unit}` : String(item);
      button.onclick = () => close(item);
      box.appendChild(button);
    }

    const save = () => {
      const entered = Number(own.value);
      const ok = own.value !== '' && Number.isFinite(entered)
        && entered >= min && entered <= max;
      close(ok ? entered : null);
    };
    document.getElementById('number-save').onclick = save;
    document.getElementById('number-close').onclick = () => close(null);
    own.onkeydown = (event) => { if (event.key === 'Enter') save(); };

    sheet.hidden = false;
    // Клавиатуру открываем только там, где поле и есть ответ. Когда есть
    // кнопки с привычными значениями, выехавшая клавиатура закрыла бы их.
    if (choices.length === 0) own.focus();
  });
}

function askMinutes() {
  return askNumber({ title: 'Сколько минут?', choices: MINUTE_CHOICES,
                     unit: 'мин', min: 1, max: 300 });
}

// Вопрос «точно?» — тоже своим окном. У системного окна браузера кнопки
// называются «ОК» и «Отмена»: они не говорят, что именно случится, стоят
// в разном порядке на разных телефонах, и «ОК» на удаление нажимают не
// глядя. Здесь на кнопке написано действие, отмена — ниже, под большим
// пальцем, и крестик тоже значит «нет».
function askYes({ title, text = '', action = 'Да', danger = false }) {
  return new Promise((resolve) => {
    const sheet = document.getElementById('confirm-sheet');
    const note = document.getElementById('confirm-text');
    const yes = document.getElementById('confirm-yes');

    document.getElementById('confirm-title').textContent = title;
    note.textContent = text;
    note.hidden = !text;
    yes.textContent = action;
    yes.classList.toggle('danger', danger);

    const close = (answer) => { sheet.hidden = true; resolve(answer); };
    yes.onclick = () => close(true);
    document.getElementById('confirm-no').onclick = () => close(false);
    document.getElementById('confirm-close').onclick = () => close(false);
    sheet.hidden = false;
  });
}

async function finishWorkout() {
  const ids = [...doneExercises];
  if (ids.length === 0) return;

  // Для занятия спрашиваем реальное время — оно у всех разное. Своим
  // окном, а не системным prompt: тот выглядит чужим, обрезает текст на
  // телефоне и не даёт подсказать привычные варианты.
  const cardioIds = new Set(gym.cardio.map((c) => c.id));
  let minutes = null;
  if (ids.some((id) => cardioIds.has(id))) {
    minutes = await askMinutes();
    if (minutes === null) return;
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


/* --- Ешь как обычно ------------------------------------------------------

   Самое частое действие в дневнике — записать то, что ешь каждый день.
   Гонять это через распознавание бессмысленно: несколько секунд ожидания
   и оплаченный запрос ради «овсянки», которая уже двадцать раз записана.
*/

function renderFrequent(items) {
  const card = document.getElementById('frequent-card');
  const box = document.getElementById('frequent');
  card.hidden = !items || !items.length;
  box.innerHTML = '';

  for (const item of items || []) {
    const row = document.createElement('button');
    row.className = 'often';
    row.innerHTML = `
      <div class="often-main">
        <div class="often-name"></div>
        <div class="often-sub"></div>
      </div>
      <div class="often-kcal"></div>
      <div class="often-add">＋</div>`;
    row.querySelector('.often-name').textContent = item.name;
    row.querySelector('.often-sub').textContent =
      `${item.weight_g} г · Б ${item.protein_g} · Ж ${item.fat_g} · У ${item.carbs_g}` +
      (item.times > 2 ? ` · ${item.times} ${plural(item.times, 'раз', 'раза', 'раз')}` : '');
    row.querySelector('.often-kcal').textContent = `${item.calories}`;

    row.onclick = async () => {
      row.disabled = true;
      try {
        await api('/api/meals', { method: 'POST', body: JSON.stringify(item) });
        haptic('medium');
        toast(`Записала: ${item.name}`);
        await refresh();
      } catch (e) {
        toast(e.message);
        row.disabled = false;
      }
    };
    box.appendChild(row);
  }
}

/* --- Экран «Что съесть»: четыре режима ----------------------------------- */
// Кубик отвечает «съесть прямо сейчас, ничего не готовя» — это наборы
// продуктов, а не блюда. Остальные три — вопросы к одной книге рецептов:
// когда некогда, когда есть время полистать, и когда в холодильнике уже
// что-то стоит.

const FOOD_MODES = [
  ['cube', 'Кубик', 'Съесть прямо сейчас, ничего не готовя'],
  ['quick', 'Быстро', 'Рецепты не дольше 15 минут'],
  ['book', 'Рецепты', 'Меню нутрициолога и блюда по её принципам'],
  ['preps', 'Заготовки', 'Собрать из того, что приготовлено заранее'],
];

// Что обещает главная кнопка экрана в каждом режиме. Обещание разное:
// в «Кубике» это набор из магазина, в остальных — блюдо из книги рецептов.
const DECIDE_TEXT = {
  cube: 'Соберу набор сама — ни одного вопроса.',
  quick: 'Дам блюдо на пятнадцать минут — без вопросов.',
  book: 'Открою одно блюдо из книги — не выбирая.',
  preps: 'Соберу из того, что уже стоит в холодильнике.',
};

let foodMode = 'cube';

function switchFoodMode(mode) {
  foodMode = mode;
  for (const button of document.querySelectorAll('.food-mode')) {
    button.classList.toggle('on', button.dataset.mode === mode);
  }
  document.getElementById('food-hint').textContent =
    (FOOD_MODES.find(([code]) => code === mode) || [])[2] || '';
  document.getElementById('decide-text').textContent = DECIDE_TEXT[mode] || '';

  document.getElementById('cube-mode').hidden = mode !== 'cube';
  document.getElementById('menu-mode').hidden = mode === 'cube';
  document.getElementById('preps-card').hidden = mode !== 'preps';

  if (mode !== 'cube') loadMenu(mealType);
  if (mode === 'preps' && !preps) togglePreps(true);
}

function buildFoodModes() {
  const box = document.getElementById('food-modes');
  box.innerHTML = '';
  for (const [code, label] of FOOD_MODES) {
    const button = document.createElement('button');
    button.className = 'food-mode';
    button.dataset.mode = code;
    button.textContent = label;
    button.onclick = () => switchFoodMode(code);
    box.appendChild(button);
  }
  switchFoodMode(foodMode);
}


/* --- Подбор блюда: меню Анастасии плюс сборка по её принципам ------------ */
// Одна книга рецептов, три вопроса к ней: «быстро», «полистать», «из
// заготовок». Выбор режима — кнопками наверху экрана, а не переключателем
// «готовлю / не готовлю»: не готовить — это «Кубик», отдельный режим рядом.
let mealType = null;
let menuBoard = null;

// Значок у блюд из её меню. Ставится только им — остальное без пометок.
const AUTHOR_MARK = '⭐';

function setMealTabs(active) {
  for (const tab of document.querySelectorAll('.meal-tab')) {
    tab.classList.toggle('on', tab.dataset.meal === active);
  }
}

async function loadMenu(meal) {
  const button = document.getElementById('suggest-btn');
  const box = document.getElementById('suggestions');
  button.disabled = true;
  button.textContent = 'Подбираю…';

  try {
    const params = new URLSearchParams();
    if (meal) params.set('meal', meal);
    params.set('mode', foodMode === 'preps' ? 'preps'
                     : foodMode === 'quick' ? 'quick' : 'book');
    const query = params.toString();
    menuBoard = await api(`/api/menu${query ? '?' + query : ''}`);
    mealType = menuBoard.meal_type;
    setMealTabs(mealType);

    document.getElementById('budget-line').textContent =
      `На ${menuBoard.meal_name} — около ${menuBoard.budget} ккал`;
    document.getElementById('plate-hint').textContent = menuBoard.hint;
    document.getElementById('gap-hint').textContent =
      menuBoard.gap === 'protein_g' ? 'не хватает белка'
      : menuBoard.gap === 'fiber_g' ? 'не хватает клетчатки'
      : menuBoard.gap === 'carbs_g' ? 'не хватает углеводов' : '';

    renderOffers(menuBoard);
    button.textContent = 'Подобрать ещё';
  } catch (e) {
    box.innerHTML = `<div class="empty">${e.message}</div>`;
    button.textContent = 'Попробовать снова';
  } finally {
    button.disabled = false;
  }
}

function renderOffers(data) {
  const box = document.getElementById('suggestions');
  box.innerHTML = '';

  if (!data.offers.length) {
    box.innerHTML = '<div class="empty">' + (data.no_cook
      ? 'Готовых наборов на такой бюджет нет — попробуй другой приём пищи.'
      : 'На такой бюджет подходящего блюда нет. Попробуй другой приём пищи.') +
      '</div>';
    return;
  }
  if (data.approximate) {
    const note = document.createElement('div');
    note.className = 'empty soft';
    note.textContent = 'Точного варианта нет — вот что ближе всего.';
    box.appendChild(note);
  }

  data.offers.forEach((item, index) => {
    const row = document.createElement('div');
    row.className = 'suggestion';
    row.innerHTML = `
      <div class="sug-head">
        <span class="sug-name"></span>
        <span class="sug-kcal">${Math.round(item.calories)} ккал</span>
      </div>
      <div class="sug-macros"></div>
      <div class="sug-why"></div>
      <div class="row">
        <button class="chip sug-recipe">Рецепт</button>
        <button class="chip accent sug-eat">Съела это</button>
      </div>`;

    const name = row.querySelector('.sug-name');
    name.textContent = item.name;
    if (item.author) {
      const mark = document.createElement('span');
      mark.className = 'author-mark';
      mark.textContent = ` ${AUTHOR_MARK}`;
      mark.title = 'Рецепт из меню Анастасии';
      name.appendChild(mark);
    }

    row.querySelector('.sug-macros').textContent =
      `${Math.round(item.weight_g)} г · Б ${Math.round(item.protein_g)} · ` +
      `Ж ${Math.round(item.fat_g)} · У ${Math.round(item.carbs_g)}` +
      (item.fiber_g ? ` · кл ${Math.round(item.fiber_g)}` : '') +
      ` · ${item.minutes} мин`;
    row.querySelector('.sug-why').textContent = item.reason;

    // Что из блюда уже стоит готовым — это её принцип экономии времени.
    if (item.preps?.length) {
      const ready = document.createElement('div');
      ready.className = 'sug-ready';
      ready.textContent = `Из заготовок: ${item.preps.join(', ')}`;
      row.querySelector('.sug-why').after(ready);
    }

    row.querySelector('.sug-recipe').onclick = () => openRecipe(index);
    row.querySelector('.sug-eat').onclick = () => eatOffer(item, row);
    box.appendChild(row);
  });
}

async function eatOffer(item, row) {
  try {
    await api('/api/meals', { method: 'POST', body: JSON.stringify(item) });
    haptic('medium');
    toast(`Записала: ${item.name}`);
    if (row) row.remove();
    document.getElementById('recipe-sheet').hidden = true;
    await refresh();
  } catch (e) { toast(e.message); }
}

function openRecipe(index) {
  const item = menuBoard?.offers?.[index];
  if (!item) return;

  document.getElementById('recipe-title').textContent =
    item.name + (item.author ? ` ${AUTHOR_MARK}` : '');
  document.getElementById('recipe-macros').textContent =
    `${Math.round(item.calories)} ккал · Б ${Math.round(item.protein_g)} · ` +
    `Ж ${Math.round(item.fat_g)} · У ${Math.round(item.carbs_g)} г` +
    (item.fiber_g ? ` · клетчатка ${Math.round(item.fiber_g)} г` : '');

  const parts = document.getElementById('recipe-parts');
  parts.innerHTML = '';
  for (const part of item.components || []) {
    const li = document.createElement('li');
    // «Соль, перец» без граммов: считать их незачем, но в рецепте они нужны.
    li.textContent = part.seasoning
      ? `${part.name} — ${part.raw || 'по вкусу'}`
      : `${part.name} — ${part.grams} г`;
    parts.appendChild(li);
  }

  // Заметку про подобранные порции показываем отдельной строкой ниже, чтобы
  // она не терялась в шагах приготовления.
  document.getElementById('recipe-steps').textContent =
    (item.instructions || '') + (item.notes && !item.estimated ? `\n\n${item.notes}` : '');
  // Три разные вещи — заготовки, подобранные порции и источник — должны
  // читаться как три строки, а не как один серый абзац.
  const footer = document.getElementById('recipe-source');
  footer.innerHTML = '';
  const lines = [];
  if (item.preps?.length) lines.push(`Из заготовок: ${item.preps.join(', ')}`);
  // Откуда рецепт — видно по звёздочке у названия. Писать «меню, неделя 2,
  // день 3» незачем: человеку это ничего не даёт.
  if (item.estimated) lines.push('⚖️ Порции подобраны — точных граммов в рецепте нет.');
  for (const line of lines) {
    const row = document.createElement('div');
    row.className = 'recipe-note';
    row.textContent = line;
    footer.appendChild(row);
  }
  document.getElementById('recipe-eat').onclick = () => eatOffer(item, null);
  document.getElementById('recipe-sheet').hidden = false;
}

/* --- Заготовки: приготовил один раз — ешь несколько дней --- */
let preps = null;

async function togglePreps(open = false) {
  const box = document.getElementById('preps-list');
  const button = document.getElementById('preps-toggle');
  // В режиме «из заготовок» список нужен сразу: человек за этим и пришёл.
  if (!box.hidden && !open) {
    box.hidden = true;
    button.textContent = 'показать';
    return;
  }

  button.textContent = 'загружаю…';
  try {
    if (!preps) {
      const data = await api('/api/preps');
      preps = data.preps;
      myPreps = data.mine || [];
    }
    renderPreps(preps);
    box.hidden = false;
    button.textContent = 'скрыть';
  } catch (e) {
    toast(e.message);
    button.textContent = 'показать';
  }
}

// Что стоит в холодильнике: код заготовки -> сколько ещё хранится.
let myPreps = [];

function renderPreps(items) {
  const box = document.getElementById('preps-list');
  const fridge = new Map((myPreps || []).map((item) => [item.code, item]));
  box.innerHTML = '';

  items.forEach((prep, index) => {
    const have = fridge.get(prep.code);
    const row = document.createElement('div');
    row.className = `prep-row${have ? ' have' : ''}`;
    row.innerHTML = `
      <button class="prep-open">
        <span class="prep-name"></span>
        <span class="prep-keep"></span>
      </button>
      <button class="prep-mark" title="Приготовила"></button>`;
    row.querySelector('.prep-name').textContent = prep.name;
    // Пока заготовки нет — показываем срок хранения из справочника. Когда
    // есть — сколько осталось именно у неё.
    row.querySelector('.prep-keep').textContent = have ? have.hint : (prep.fridge || '');
    if (have && have.expiring) row.querySelector('.prep-keep').classList.add('soon');

    row.querySelector('.prep-open').onclick = () => openPrep(index);
    const mark = row.querySelector('.prep-mark');
    mark.textContent = have ? '✓' : '+';
    mark.onclick = async (event) => {
      event.stopPropagation();
      mark.disabled = true;
      try {
        // Повторное нажатие означает «съела»: холодильник должен пустеть
        // так же легко, как наполняться.
        const data = await api('/api/preps/mine', {
          method: 'POST',
          body: JSON.stringify({ code: prep.code, done: Boolean(have) }),
        });
        myPreps = data.mine || [];
        renderPreps(items);
        toast(have ? 'Убрала из холодильника' : 'Записала: приготовлено сегодня');
      } catch (error) {
        mark.disabled = false;
        toast(error.message);
      }
    };
    box.appendChild(row);
  });
}

function openPrep(index) {
  const prep = preps?.[index];
  if (!prep) return;

  document.getElementById('prep-title').textContent = prep.name;
  const per = prep.per100;
  document.getElementById('prep-macros').textContent =
    `В 100 г — ${per.calories} ккал · Б ${per.protein_g} · Ж ${per.fat_g} · ` +
    `У ${per.carbs_g} г` + (prep.portions ? ` · выход ${prep.portions} порций` : '');

  const storage = [];
  if (prep.fridge) storage.push(`❄️ в холодильнике ${prep.fridge}`);
  if (prep.freezer) storage.push(`🧊 в морозилке ${prep.freezer}`);
  storage.push(`Готовить ${prep.minutes} мин`);
  document.getElementById('prep-storage').textContent = storage.join(' · ');

  const parts = document.getElementById('prep-parts');
  parts.innerHTML = '';
  for (const part of prep.components) {
    const li = document.createElement('li');
    li.textContent = part.grams
      ? `${part.name} — ${part.grams} г`
      : `${part.name} — ${part.raw || 'по вкусу'}`;
    parts.appendChild(li);
  }

  document.getElementById('prep-steps').textContent = prep.instructions;
  document.getElementById('prep-ideas').textContent =
    prep.ideas ? `Что собрать: ${prep.ideas}` : '';
  document.getElementById('prep-sheet').hidden = false;
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

/* --- Профиль: то же, что кнопками в чате, но не выходя из приложения.
   Правка сохраняется сразу после выбора или ухода из поля: кнопка
   «Сохранить» тут только добавила бы шаг и способ потерять изменения. --- */
let profileData = null;
let profileChanged = false;

function optionButtons(boxId, options, current, onPick) {
  const box = document.getElementById(boxId);
  box.innerHTML = '';
  for (const option of options) {
    const button = document.createElement('button');
    button.className = `state-opt wide${option.code === current ? ' on' : ''}`;
    button.textContent = option.label;
    button.onclick = () => { if (option.code !== current) onPick(option.code); };
    box.appendChild(button);
  }
}

function renderProfile(data) {
  const p = data.profile;
  const n = data.norms;
  document.getElementById('prof-norms').textContent = `${n.calories} ккал`;
  document.getElementById('prof-norms-sub').textContent =
    `Б ${n.protein_g} · Ж ${n.fat_g} · У ${n.carbs_g} г · клетчатка ${n.fiber_g} г · ` +
    `вода ${(n.water_ml / 1000).toFixed(1)} л`;

  optionButtons('prof-goal', data.options.goal, p.goal, (code) => saveProfile({ goal: code }));
  optionButtons('prof-activity', data.options.activity, p.activity,
    (code) => saveProfile({ activity: code }));
  optionButtons('prof-diet', data.options.diet, p.diet, (code) => saveProfile({ diet: code }));

  const fields = {
    'prof-height': [p.height_cm, data.limits.height],
    'prof-age': [p.age, data.limits.age],
    'prof-target': [p.target_weight_kg, data.limits.target_weight],
  };
  for (const [id, [value, limits]] of Object.entries(fields)) {
    const input = document.getElementById(id);
    input.value = value ?? '';
    // Границы показываем подсказкой: поле текстовое, min/max браузер бы не читал.
    input.placeholder = `${limits[0]}–${limits[1]}`;
  }

  document.getElementById('prof-weight-hint').textContent = p.weight_kg
    ? `Сейчас ${p.weight_kg} кг. Текущий вес меняется замером на «Прогрессе» — ` +
      'так он попадает в график.'
    : 'Текущий вес добавляется замером на «Прогрессе».';

  document.getElementById('prof-allergies').value = p.allergies || '';

  // Цель по шагам: готовые числа плюс своё. Это не медицинская норма, а
  // договорённость с собой, поэтому выбирает её человек, а не формула.
  const goal = data.steps?.goal || 0;
  optionButtons('prof-steps',
    (data.steps?.choices || []).map((value) => ({ code: String(value), label: String(value) })),
    String(goal), (code) => saveProfile({ steps_goal: code }));
  const own = document.getElementById('prof-steps-own');
  own.value = goal || '';
  own.placeholder = String(goal || '');

  const reminders = document.getElementById('prof-reminders');
  reminders.textContent = p.reminders ? 'включены' : 'выключены';
  reminders.classList.toggle('on', p.reminders);

  renderNotify(data.notifications, p.reminders);

  // Календарь показываем только женщинам: мужчине он бессмыслен, и строка
  // настройки у него была бы просто непонятной.
  const cycleRow = document.getElementById('prof-cycle-row');
  cycleRow.hidden = p.gender !== 'female';
  const cycleButton = document.getElementById('prof-cycle');
  cycleButton.textContent = p.cycle ? 'включён' : 'выключен';
  cycleButton.classList.toggle('on', !!p.cycle);
}

/** Настройки уведомлений: галочки, частота и тихие часы. */
function renderNotify(notify, remindersOn) {
  const toggle = document.getElementById('notif-toggle');
  const box = document.getElementById('notif-box');
  // Выключенные напоминания нечего настраивать: подробности под общим
  // рубильником только сбивают с толку.
  toggle.hidden = !notify || !remindersOn;
  if (toggle.hidden) { box.hidden = true; return; }
  if (!notify) return;

  const kinds = document.getElementById('notif-kinds');
  kinds.innerHTML = '';
  for (const kind of notify.kinds) {
    const button = document.createElement('button');
    button.className = `state-opt wide${kind.on ? ' on' : ''}`;
    button.textContent = kind.label;
    button.onclick = () => saveProfile({ notifications: { [kind.code]: !kind.on } });
    kinds.appendChild(button);
  }

  optionButtons('notif-pace', notify.paces, notify.pace,
    (code) => saveProfile({ notifications: { pace: code } }));

  hourSelect('notif-from', notify.quiet_from,
    (hour) => saveProfile({ notifications: { quiet_from: hour } }));
  hourSelect('notif-to', notify.quiet_to,
    (hour) => saveProfile({ notifications: { quiet_to: hour } }));
}

function hourSelect(id, current, onPick) {
  const box = document.getElementById(id);
  box.innerHTML = '';
  for (let hour = 0; hour < 24; hour += 1) {
    const option = document.createElement('option');
    option.value = String(hour);
    option.textContent = `${String(hour).padStart(2, '0')}:00`;
    if (hour === current) option.selected = true;
    box.appendChild(option);
  }
  box.onchange = () => onPick(Number(box.value));
}

async function saveProfile(changes) {
  try {
    const data = await api('/api/profile', { method: 'PATCH', body: JSON.stringify(changes) });
    profileData = data;
    profileChanged = true;
    renderProfile(data);
    haptic('medium');
    // Смена цели без видимой новой цифры выглядит так, будто ничего не произошло.
    toast(data.recalculated ? `Норма пересчитана: ${data.norms.calories} ккал` : 'Сохранено');
  } catch (e) {
    toast(e.message);
    if (profileData) renderProfile(profileData);   // поле возвращается к сохранённому
  }
}

function saveProfileField(field, input) {
  const value = input.value.trim();
  if (!value) { renderProfile(profileData); return; }   // пустое поле — не «сбросить»
  saveProfile({ [field]: value });
}

async function requestExport() {
  const button = document.getElementById('prof-export');
  button.disabled = true;
  button.textContent = 'Собираю файл…';
  try {
    await api('/api/export', { method: 'POST' });
    haptic('medium');
    toast('Файл ушёл в чат с ботом');
  } catch (e) {
    toast(e.message);
  } finally {
    button.disabled = false;
    button.textContent = '📦 Выгрузить всё одним файлом';
  }
}

async function openProfile() {
  document.getElementById('profile-sheet').hidden = false;
  wireProblem();
  try {
    profileData = await api('/api/profile');
    renderProfile(profileData);
  } catch (e) {
    toast(e.message);
  }
}

async function closeProfile() {
  document.getElementById('profile-sheet').hidden = true;
  // Норма могла измениться — кольцо на «Сегодня» должно это показать.
  if (profileChanged) {
    profileChanged = false;
    await refresh().catch((e) => toast(e.message));
  }
}

/* --- загрузка и переключение вкладок --- */
async function refresh() {
  state = await api('/api/today');
  renderToday(state);
  renderCheetah(state.cheetah, 'cheetah');
  renderTurn(state.next_action);
  renderGame(state.game);
  renderAwards(state.game?.awards);
  renderPills(state.supplements);
  // Награда и закрытое задание приходят от сервера ровно один раз — если не
  // показать их сейчас, пользователь о них не узнает.
  celebrate(state.game);
}


/* --- Команда и рейтинг --------------------------------------------------- */
// Личный счётчик шагов забрасывают через неделю: смотреть в него незачем.
// Работает другое — что тебя видят.

let stepsBoard = null;

async function refreshBoard() {
  stepsBoard = await api('/api/steps/board');
  renderTeam(stepsBoard);
  renderTop(stepsBoard);
}

function boardRow(row, place) {
  const item = document.createElement('div');
  item.className = 'board-row' + (row.me ? ' me' : '');
  const days = row.days ? `<span class="board-days">${row.days} дн. с нормой</span>` : '';
  item.innerHTML = `<span class="board-place">${place}</span>`
    + `<span class="board-name"></span>`
    + `<span class="board-steps">${row.steps}${days}</span>`;
  // Имя приходит от другого человека — вставляем текстом, а не разметкой.
  item.querySelector('.board-name').textContent = row.name;
  return item;
}

function renderTeam(data) {
  const team = data.team;
  document.getElementById('team-none').hidden = Boolean(team);
  document.getElementById('team-mine').hidden = !team;
  document.getElementById('team-total').textContent =
    team ? `${team.total} за неделю` : '';
  if (!team) return;

  document.getElementById('team-name-view').textContent = team.name;
  const rows = document.getElementById('team-rows');
  rows.innerHTML = '';
  team.rows.forEach((row, index) => rows.appendChild(boardRow(row, index + 1)));

  const invite = document.getElementById('team-invite');
  invite.disabled = team.full;
  invite.textContent = team.full ? 'Мест больше нет' : 'Позвать в команду';
  // Ссылку строит сервер: имя бота знает он, а не страница.
  invite.onclick = () => shareInvite(team.invite);
}

function renderTop(data) {
  const rows = document.getElementById('top-rows');
  rows.innerHTML = '';

  // «1. Лилия — 0», когда в таблице ты одна, звучит как насмешка. Пока ходить
  // некому, показываем не таблицу, а причину, по которой её нет.
  const walking = (data.top || []).filter((row) => row.steps > 0);
  if (walking.length < 2) {
    const empty = document.createElement('p');
    empty.className = 'hint';
    empty.textContent = 'Пока в таблице некому соревноваться — на этой неделе '
      + 'шаги записывает слишком мало людей. Позови кого-нибудь в команду.';
    rows.appendChild(empty);
    document.getElementById('top-place').textContent = '';
  } else {
    (data.top || []).forEach((row, index) => rows.appendChild(boardRow(row, index + 1)));
    document.getElementById('top-place').textContent =
      data.place ? `ты ${data.place}-я` : '';
  }

  // Прошлая неделя: иначе понедельник обнуляет всё, чего человек добился.
  const last = data.last || {};
  document.getElementById('top-last').textContent = last.steps
    ? `Прошлая неделя: ${last.steps} шагов`
      + (last.place ? `, ${last.place}-е место` : '')
      + (last.days ? ` · норма ${last.days} дн.` : '')
    : '';
  document.getElementById('top-hint').textContent =
    `В зачёт идёт не больше ${data.cap} шагов за день: приписывать бессмысленно, `
    + 'а до потолка проще дойти ногами.';
}

async function teamAction(body) {
  try {
    await api('/api/team', { method: 'POST', body: JSON.stringify(body) });
    await refreshBoard();
    haptic('medium');
  } catch (error) {
    toast(error.message);
  }
}

function wireTeam() {
  document.getElementById('team-create').onclick = () =>
    teamAction({ action: 'create', name: document.getElementById('team-name').value });
  document.getElementById('team-join').onclick = () =>
    teamAction({ action: 'join', code: document.getElementById('team-code').value.trim() });
  document.getElementById('team-leave').onclick = async () => {
    const sure = await askYes({
      title: 'Выйти из команды?',
      text: 'Её таблица без тебя останется.',
      action: 'Выйти', danger: true,
    });
    if (sure) teamAction({ action: 'leave' });
  };
}


/* --- Кубик: что съесть прямо сейчас ------------------------------------- */
// Настроения. Порядок не случайный: сначала то, что просят чаще.
const CRAVINGS = [
  ['random', '🎲 Всё равно'], ['sweet', '🍫 Сладкого'], ['salty', '🧂 Солёного'],
  ['drink', '🥤 Выпить'], ['crunchy', '🥕 Похрустеть'], ['filling', '🍗 Сытного'],
  ['protein', '💪 Побольше белка'], ['fresh', '🥬 Свежего'], ['comfort', '🫶 Приятного'],
];

// Что уже показывали: одно и то же подряд выглядит как поломка.
const cubeState = { level: '', craving: 'random', recent: [], ready: false,
                    shop: false, basket: new Set() };

function buildCubeControls() {
  const levels = [
    ['light', '🟢', 'Просто пожевать'],
    ['normal', '🟡', 'Нормально голодна'],
    ['hungry', '🔴', 'Сейчас съем кассира'],
    ['meal', '🟣', 'Нужен почти обед'],
  ];
  const box = document.getElementById('cube-levels');
  box.innerHTML = '';
  for (const [code, dot, label] of levels) {
    const button = document.createElement('button');
    button.className = 'cube-level';
    button.dataset.level = code;
    button.innerHTML = `<span>${dot}</span><span>${label}</span>`;
    button.onclick = () => {
      cubeState.level = cubeState.level === code ? '' : code;
      cubeState.recent = [];
      markCubeLevel();
    };
    box.appendChild(button);
  }

  const chips = document.getElementById('cube-cravings');
  chips.innerHTML = '';
  for (const [code, label] of CRAVINGS) {
    const chip = document.createElement('button');
    chip.className = 'chip-btn' + (code === 'random' ? ' active' : '');
    chip.dataset.craving = code;
    chip.textContent = label;
    chip.onclick = () => {
      cubeState.craving = code;
      cubeState.recent = [];
      for (const other of chips.children) {
        other.classList.toggle('active', other === chip);
      }
    };
    chips.appendChild(chip);
  }

  document.getElementById('cube-go').onclick = () => rollCube();
  cubeState.ready = true;
}

// Быстрый путь: один вопрос вместо трёх. Человек уже у полки.
const SHOP_CRAVINGS = [
  ['sweet', '🍫 Сладкого'], ['salty', '🧂 Солёного'], ['drink', '🥤 Выпить'],
  ['crunchy', '🥕 Похрустеть'], ['filling', '🍗 Сытного'], ['random', '🎲 Всё равно'],
];

function buildShopMode() {
  const chips = document.getElementById('cube-shop-cravings');
  chips.innerHTML = '';
  for (const [code, label] of SHOP_CRAVINGS) {
    const chip = document.createElement('button');
    chip.className = 'chip-btn';
    chip.textContent = label;
    // Никаких «а теперь нажми собрать»: выбрал настроение — получил ответ.
    chip.onclick = () => {
      for (const other of chips.children) other.classList.toggle('active', other === chip);
      cubeState.craving = code;
      rollCube(true);
    };
    chips.appendChild(chip);
  }

  document.getElementById('cube-shop').onclick = () => {
    cubeState.shop = !cubeState.shop;
    cubeState.recent = [];
    document.getElementById('cube-shop').classList.toggle('on', cubeState.shop);
    document.getElementById('cube-shop-ask').hidden = !cubeState.shop;
    document.getElementById('cube-ask').hidden = cubeState.shop;
    document.getElementById('cube-results').innerHTML = '';
    if (!cubeState.shop) {
      // Выходя из магазина, возвращаем то настроение, которое человек видит
      // отмеченным на основном экране: иначе бот считает одно, а показывает другое.
      const active = document.querySelector('#cube-cravings .chip-btn.active');
      cubeState.craving = active ? active.dataset.craving : 'random';
      for (const chip of document.getElementById('cube-shop-cravings').children) {
        chip.classList.remove('active');
      }
    }
  };
}

async function buildBasket() {
  const box = document.getElementById('cube-basket');
  const toggle = document.getElementById('cube-basket-toggle');
  toggle.onclick = () => {
    box.hidden = !box.hidden;
    toggle.textContent = box.hidden ? 'показать' : 'скрыть';
  };

  let data;
  try {
    data = await api('/api/cube/basket');
  } catch (error) {
    return;
  }

  box.innerHTML = '';
  for (const row of data.rows) {
    const block = document.createElement('div');
    block.className = 'basket-row';
    block.innerHTML = `<h3>${row.title}</h3><div class="basket-items"></div>`;
    const items = block.querySelector('.basket-items');
    for (const item of row.items) {
      const chip = document.createElement('button');
      chip.className = 'basket-item';
      chip.dataset.code = item.code;
      chip.textContent = item.name;
      chip.onclick = () => {
        chip.classList.toggle('on');
        if (cubeState.basket.has(item.code)) cubeState.basket.delete(item.code);
        else cubeState.basket.add(item.code);
        markBasket();
      };
      items.appendChild(chip);
    }
    box.appendChild(block);
  }

  const count = document.createElement('p');
  count.className = 'basket-count';
  count.id = 'cube-basket-count';
  box.appendChild(count);
  markBasket();
}

function markBasket() {
  const count = document.getElementById('cube-basket-count');
  if (!count) return;
  const size = cubeState.basket.size;
  count.textContent = size
    ? `Отмечено ${size} — собираю только из этого. Нажми ещё раз, чтобы снять.`
    : 'Ничего не отмечено — беру весь магазин.';
  cubeState.recent = [];
}

function syncBasketChips() {
  // Фишки корзины и есть подтверждение: отмеченное с фото должно быть на
  // них видно, иначе счётчик говорит одно, а экран показывает другое.
  for (const chip of document.querySelectorAll('.basket-item')) {
    chip.classList.toggle('on', cubeState.basket.has(chip.dataset.code));
  }
  markBasket();
}


/* --- Сфоткай полку ------------------------------------------------------ */
// Отмечать пятьдесят продуктов пальцем у витрины никто не станет. Фотография
// делает это за человека, но решает всё равно он: сначала показываем, что
// увидели, и только потом собираем набор.

function buildShelf() {
  const input = document.getElementById('shelf-input');
  input.onchange = () => {
    const file = input.files && input.files[0];
    // Сбрасываем сразу: иначе повторный выбор того же файла не сработает.
    input.value = '';
    if (file) sendShelf(file);
  };
}

async function sendShelf(file) {
  const box = document.getElementById('shelf-found');
  box.hidden = false;
  box.innerHTML = '<p class="hint">Смотрю, что на полке…</p>';

  const form = new FormData();
  form.append('photo', file, 'shelf.jpg');
  try {
    const response = await fetch('/api/cube/shelf', {
      method: 'POST',
      headers: { 'X-Telegram-Init-Data': tg?.initData || '', 'X-Timezone': deviceZone() },
      body: form,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `Ошибка ${response.status}`);
    haptic('medium');
    renderShelf(data);
  } catch (error) {
    box.innerHTML = '';
    const line = document.createElement('p');
    line.className = 'hint';
    line.textContent = error.message;
    box.appendChild(line);
  }
}

function renderShelf(data) {
  const box = document.getElementById('shelf-found');
  box.hidden = false;
  box.innerHTML = '';
  const picked = new Set((data.items || []).map((item) => item.code));

  if (!picked.size) {
    box.innerHTML = '<p class="hint">Знакомых продуктов на фото не вижу. '
      + 'Попробуй снять поближе или отметь всё в корзине руками.</p>';
  } else {
    const title = document.createElement('p');
    title.className = 'hint';
    title.textContent = 'Вижу вот это. Нажми на то, чего на полке нет:';
    box.appendChild(title);

    const items = document.createElement('div');
    items.className = 'basket-items';
    for (const item of data.items) {
      const chip = document.createElement('button');
      chip.className = 'basket-item on';
      chip.textContent = item.name;
      chip.onclick = () => {
        if (picked.has(item.code)) picked.delete(item.code);
        else picked.add(item.code);
        chip.classList.toggle('on', picked.has(item.code));
      };
      items.appendChild(chip);
    }
    box.appendChild(items);
  }

  // Еда, которую бот видит, но считать не умеет. Молчать об этом нельзя:
  // человек решит, что бот её проглядел, и перестанет доверять остальному.
  if (data.other && data.other.length) {
    const other = document.createElement('p');
    other.className = 'hint';
    other.textContent = 'Ещё вижу: ' + data.other.join(', ')
      + '. Этого в моём справочнике нет — в набор не возьму.';
    box.appendChild(other);
  }

  if (!picked.size) return;

  const go = document.createElement('button');
  go.className = 'btn';
  go.textContent = 'Собрать из этого';
  go.onclick = () => {
    cubeState.basket = new Set(picked);
    syncBasketChips();
    rollCube(false);
  };
  box.appendChild(go);
}


/* --- «Реши за меня» ------------------------------------------------------ */
// Половина людей на этом экране не хочет отвечать на вопросы — они хотят
// один ответ. Ничего нового этот блок не считает: он зовёт тот же подбор,
// что и кнопки ниже, только не спрашивая ни о чём.

async function decideForMe() {
  const button = document.getElementById('decide-btn');
  button.disabled = true;
  const was = button.textContent;
  button.textContent = 'Подбираю…';
  try {
    if (foodMode === 'cube') {
      await rollCube();
      document.getElementById('cube-results').scrollIntoView(
        { behavior: 'smooth', block: 'start' });
    } else {
      await loadMenu(mealType);
      document.getElementById('suggestions').scrollIntoView(
        { behavior: 'smooth', block: 'start' });
    }
  } finally {
    button.disabled = false;
    button.textContent = was;
  }
}

function markCubeLevel() {
  for (const button of document.querySelectorAll('.cube-level')) {
    button.classList.toggle('on', button.dataset.level === cubeState.level);
  }
}

async function rollCube(inStore = cubeState.shop) {
  const results = document.getElementById('cube-results');
  results.innerHTML = '<div class="card cube-empty">Собираю…</div>';
  try {
    const data = await api('/api/cube', {
      method: 'POST',
      body: JSON.stringify({
        level: cubeState.level,
        craving: cubeState.craving,
        shop: inStore,
        basket: [...cubeState.basket],
        no_spoon: document.getElementById('cube-nospoon').checked,
        recent: cubeState.recent,
      }),
    });
    // Режим мог подставиться сам по остатку калорий — покажем, какой вышел.
    if (!cubeState.level) { cubeState.level = data.level; markCubeLevel(); }
    renderCubeNeeds(data.needs);
    renderCubes(data.cubes);
  } catch (error) {
    results.innerHTML = '';
    toast(error.message);
  }
}

function renderCubeNeeds(needs) {
  // Объясняем, почему подобрали именно это. Молчаливая «умность» выглядит
  // как случайность.
  const hint = document.getElementById('cube-needs');
  const words = { protein: 'белка', fiber: 'клетчатки' };
  const missing = (needs || []).map((code) => words[code]).filter(Boolean);
  hint.textContent = missing.length
    ? `Сегодня не хватает ${missing.join(' и ')} — учла это в подборе.` : '';
  hint.hidden = missing.length === 0;
}

function renderCubes(cubes) {
  const results = document.getElementById('cube-results');
  results.innerHTML = '';
  if (!cubes || !cubes.length) {
    results.innerHTML = '<div class="card cube-empty">'
      + (cubeState.basket.size
        ? 'Из отмеченного набор не складывается — не хватает белка. Отметь ещё '
          + 'что-нибудь из ряда «Белок» или «Выпить».'
        : 'Под эти условия ничего не собралось. Попробуй другое настроение '
          + 'или выключи «без ложки».')
      + '</div>';
    return;
  }

  for (const item of cubes) {
    cubeState.recent.push(item.signature);
    const card = document.createElement('article');
    card.className = 'card cube-card';

    const parts = item.items.map((part) => {
      const swap = part.swaps.length
        ? `<span class="cube-swap">нет — возьми ${part.swaps.join(', ')}</span>` : '';
      return `<li>${part.name} — <span class="cube-measure">${part.measure}</span>${swap}</li>`;
    }).join('');

    const label = item.label ? `<span class="cube-label">${item.label}</span>` : '';
    card.innerHTML = `
      ${label}
      <p class="cube-name">🧊 ${item.title}</p>
      <ul class="cube-items">${parts}</ul>
      <p class="cube-macros">≈ ${item.kcal_low}–${item.kcal_high} ккал ·
        ≈ ${item.protein_low}–${item.protein_high} г белка</p>
      <div class="cube-actions">
        <button class="btn ghost" data-roll="1">🎲 Другой</button>
        <button class="btn" data-eat="1">Съел</button>
      </div>`;

    card.querySelector('[data-roll]').onclick = () => rollCube();
    card.querySelector('[data-eat]').onclick = () => eatCube(item, card);
    results.appendChild(card);
  }
  // Помним только последние наборы: иначе через день предлагать станет нечего.
  cubeState.recent = cubeState.recent.slice(-10);
}

async function eatCube(item, card) {
  const button = card.querySelector('[data-eat]');
  button.disabled = true;
  try {
    await api('/api/meals', {
      method: 'POST',
      body: JSON.stringify({
        name: item.items.map((part) => part.name).join(' + ').slice(0, 60),
        weight_g: item.weight_g, calories: item.kcal,
        protein_g: item.protein_g, fat_g: item.fat_g, carbs_g: item.carbs_g,
      }),
    });
    toast('Записала в дневник');
    await refresh();
  } catch (error) {
    button.disabled = false;
    toast(error.message);
  }
}

/* --- Подбор занятия: два вопроса вместо каталога ------------------------- */
const PICK_TIMES = [[5, '5 минут'], [15, '15 минут'], [30, '30 минут'],
                    [45, '45 минут']];

function buildPicker() {
  const box = document.getElementById('pick-time');
  box.innerHTML = '';
  for (const [minutes, label] of PICK_TIMES) {
    const chip = document.createElement('button');
    chip.className = 'chip-btn';
    chip.textContent = label;
    chip.onclick = () => {
      for (const other of box.children) other.classList.toggle('active', other === chip);
      pickWorkout(minutes);
    };
    box.appendChild(chip);
  }
}

async function pickWorkout(minutes) {
  const out = document.getElementById('pick-result');
  out.innerHTML = '<p class="hint">Подбираю…</p>';
  try {
    const data = await api('/api/workouts/pick', {
      method: 'POST',
      // Пять минут — особый случай: целой программы такой длины нет, и
      // сервер собирает короткий набор из тех же упражнений.
      body: JSON.stringify({ minutes, quick: minutes <= 5 }),
    });
    renderPicks(data);
  } catch (error) {
    out.innerHTML = '';
    toast(error.message);
  }
}

function renderPicks(data) {
  const out = document.getElementById('pick-result');
  out.innerHTML = '';
  const items = data.quick ? data.sets : data.picks;

  if (!items || !items.length) {
    out.innerHTML = '<p class="hint">Под это время ничего не нашлось. '
      + 'Попробуй выбрать побольше.</p>';
    return;
  }

  // Первое — это и есть ответ: у него своя кнопка «Начать». Остальные
  // лежат под ним строчками, на случай «не хочу это».
  items.forEach((item, index) => {
    const first = index === 0;
    const row = document.createElement('div');
    row.className = first ? 'pick now' : 'pick';
    const list = data.quick
      ? `<p class="pick-list">${item.exercises.join(' · ')}</p>` : '';
    row.innerHTML = `
      ${first ? '<div class="eyebrow">Твоя тренировка сейчас</div>' : ''}
      <div class="pick-head">
        <span class="pick-title"></span>
        <span class="pick-min">≈${item.minutes} мин</span>
      </div>
      ${list}
      <p class="pick-why"></p>
      ${first ? '<button class="btn primary pick-start">Начать</button>' : ''}`;
    row.querySelector('.pick-title').textContent = item.title;
    row.querySelector('.pick-why').textContent = item.why;
    // Нажатие открывает ту же программу в каталоге ниже — второго списка
    // упражнений заводить незачем.
    const open = () => openProgram(item.code, item.category);
    if (first) row.querySelector('.pick-start').onclick = open;
    else row.onclick = open;
    out.appendChild(row);
  });
}

function openProgram(code, itemCategory) {
  // Программа может быть из другого направления — переключаем и его, иначе
  // каталог покажет пустоту.
  if (itemCategory && itemCategory !== category) {
    category = itemCategory;
    style = null;
  }
  programCode = code;
  refreshWorkouts()
    .then(() => document.getElementById('exercises').scrollIntoView({ behavior: 'smooth' }))
    .catch((e) => toast(e.message));
}

/* --- Мой мир: места, которые растут ---------------------------------------- */
let world = null;

async function refreshWorld() {
  world = await api('/api/world');
  renderWorld(world);
}

function renderWorld(data) {
  document.getElementById('world-title').textContent = data.title;
  document.getElementById('world-sub').textContent = data.subtitle;
  document.getElementById('world-count').textContent = `${data.open} из ${data.total}`;
  // Гепард радуется новому месту ровно один раз — сервер следит за этим сам.
  renderCheetah(data.cheetah, 'world-cheetah');
  // Уровень и кристаллы — те же, что на «Сегодня»: одна шкала на всё
  // приложение, просто видно её и здесь.
  const level = document.getElementById('world-level');
  level.textContent = state?.game
    ? `Уровень ${state.game.level} · ${state.game.xp} 💎` : '';

  const nextCard = document.getElementById('world-next-card');
  if (data.next) {
    document.getElementById('world-next-icon').textContent = data.next.icon;
    document.getElementById('world-next-title').textContent =
      data.next.open ? data.next.name : `${data.next.name} — закрыто`;
    document.getElementById('world-next-hint').textContent = data.next.hint;
    document.getElementById('world-next-bar').style.width =
      `${Math.round(data.next.share * 100)}%`;
    nextCard.hidden = false;
  } else {
    nextCard.hidden = true;
  }

  renderEvent(data.event);

  // Места — плитки, а не строки списка: мир должно быть видно, а не читать.
  // Открытое светится, закрытое приглушено — разницу видно, не вчитываясь.
  const box = document.getElementById('world-zones');
  const known = openPlaces();
  box.innerHTML = '';
  for (const zone of data.zones) {
    const tile = document.createElement('div');
    tile.className = `place${zone.open ? '' : ' locked'}`;
    // Ступени рисуем полосками: сразу видно, что место растёт, а не просто есть.
    const steps = Array.from({ length: zone.stages }, (_, index) =>
      `<i class="place-step${index < zone.stage ? ' on' : ''}"></i>`).join('');
    tile.innerHTML = `
      <span class="place-icon"></span>
      <div class="place-name"></div>
      <p class="place-story"></p>
      <div class="place-steps">${steps}</div>`;
    tile.querySelector('.place-icon').textContent = zone.icon;
    tile.querySelector('.place-name').textContent = zone.title;
    tile.querySelector('.place-story').textContent = zone.hint;
    // Место, которого не было в прошлый заход, вспыхивает один раз.
    if (zone.open && known && !known.has(zone.title)) {
      tile.classList.add('fresh');
      // Плитка ещё не в раскладке — координаты появятся на следующем кадре.
      requestAnimationFrame(() => sparksAt(tile, { count: 34, spread: 190, life: 1400 }));
    }
    box.appendChild(tile);
  }
  rememberPlaces(data.zones);
}

// Какие места были открыты в прошлый заход. Нужно ровно для одного:
// показать вспышку у нового и не показывать её у всех остальных. Хранится
// в браузере — сервер об этом знать не обязан, а без записи анимация
// повторялась бы при каждом открытии вкладки.
const PLACES_KEY = 'aura.places';

function openPlaces() {
  try {
    const raw = localStorage.getItem(PLACES_KEY);
    return raw ? new Set(JSON.parse(raw)) : null;
  } catch (error) {
    return null;
  }
}

function rememberPlaces(zones) {
  try {
    localStorage.setItem(PLACES_KEY, JSON.stringify(
      zones.filter((zone) => zone.open).map((zone) => zone.title)));
  } catch (error) {
    // Приватный режим или запрет на хранилище — просто без вспышки.
  }
}

function renderEvent(event) {
  const card = document.getElementById('world-event');
  if (!event) {
    // Тихий день — это нормально. Пустая карточка «сегодня ничего» была бы
    // хуже, чем её отсутствие.
    card.hidden = true;
    return;
  }
  card.classList.toggle('done', Boolean(event.rewarded));
  document.getElementById('event-icon').textContent = event.icon;
  document.getElementById('event-title').textContent = event.title;
  document.getElementById('event-hint').textContent = event.hint;
  document.getElementById('event-text').textContent = event.text;
  document.getElementById('event-bar').style.width =
    `${Math.round(event.share * 100)}%`;
  card.hidden = false;
}

/* --- Друзья: только игровой слой, ничего про тело и еду ------------------- */
let friends = null;

async function refreshFriends() {
  friends = await api('/api/friends');
  renderFriends(friends);
}

function renderFriends(data) {
  // Друзья свернуты внутрь команды: разворачивает их тот, кому они нужны.
  const toggle = document.getElementById('friends-toggle');
  const panel = document.getElementById('friends-box');
  toggle.onclick = () => {
    panel.hidden = !panel.hidden;
    toggle.textContent = panel.hidden ? 'показать' : 'скрыть';
  };
  toggle.textContent = panel.hidden ? 'показать' : 'скрыть';

  document.getElementById('friends-count').textContent =
    data.count ? `Друзей: ${data.count} из ${data.limit}`
      : 'Пока никого. Друзья считают кристаллы, команда — шаги.';

  const goal = document.getElementById('challenge');
  if (data.challenge) {
    document.getElementById('challenge-hint').textContent = data.challenge.hint;
    document.getElementById('challenge-bar').style.width =
      `${Math.round(data.challenge.share * 100)}%`;
    goal.hidden = false;
  } else {
    goal.hidden = true;
  }

  const box = document.getElementById('friends-list');
  box.innerHTML = '';
  data.friends.forEach((friend, index) => {
    // Один человек в списке — это не таблица, а просто он сам.
    if (data.friends.length < 2) return;
    const row = document.createElement('div');
    row.className = `friend${friend.me ? ' me' : ''}`;
    row.innerHTML = `
      <span class="friend-place"></span>
      <div class="friend-main">
        <div class="friend-name"></div>
        <div class="friend-sub"></div>
      </div>
      <span class="friend-week"></span>
      ${friend.me ? '' : '<button class="friend-drop" title="Убрать">✕</button>'}`;
    row.querySelector('.friend-place').textContent = `${index + 1}.`;
    row.querySelector('.friend-name').textContent = friend.me ? 'Ты' : friend.name;
    row.querySelector('.friend-sub').textContent =
      `Уровень ${friend.level}${friend.streak ? ` · 🔥 ${friend.streak}` : ''}`;
    row.querySelector('.friend-week').textContent = `${friend.week} 💎`;
    const drop = row.querySelector('.friend-drop');
    if (drop) drop.onclick = () => dropFriend(friend);
    box.appendChild(row);
  });

  document.getElementById('friends-invite').onclick = () => shareInvite(data.invite);
  document.getElementById('friends-renew').onclick = () => renewInvite();
}

function shareInvite(link) {
  if (!link) { toast('Ссылка появится, когда у бота будет имя'); return; }
  const text = 'Присоединяйся — считаем вместе';
  // Пересылка средствами Telegram: так человек выбирает, кому отправить, а
  // приложение не трогает его контакты.
  if (tg?.openTelegramLink) {
    tg.openTelegramLink(
      `https://t.me/share/url?url=${encodeURIComponent(link)}` +
      `&text=${encodeURIComponent(text)}`);
    return;
  }
  navigator.clipboard?.writeText(link);
  toast('Ссылка скопирована');
}

async function renewInvite() {
  const sure = await askYes({
    title: 'Сменить ссылку?',
    text: 'Старая перестанет работать: тем, кому ты её уже отправила, '
      + 'придётся прислать новую.',
    action: 'Сменить',
  });
  if (!sure) return;
  try {
    friends = await api('/api/friends', {
      method: 'POST', body: JSON.stringify({ renew: true }),
    });
    renderFriends(friends);
    toast('Ссылка обновлена');
  } catch (error) {
    toast(error.message);
  }
}

async function dropFriend(friend) {
  const sure = await askYes({
    title: 'Убрать из друзей?',
    text: 'Вы исчезнете из недельной таблицы друг друга.',
    action: 'Убрать', danger: true,
  });
  if (!sure) return;
  try {
    friends = await api('/api/friends', {
      method: 'POST', body: JSON.stringify({ remove: friend.user_id }),
    });
    renderFriends(friends);
  } catch (error) {
    toast(error.message);
  }
}

// Приложение, открытое из подсказки бота, должно открыться там, где
// действие делается, а не на «Сегодня». Иначе человек, нажавший «подобрать
// еду», попадает на главный экран и ищет нужную вкладку сам.
const SCREENS = ['today', 'world', 'gym', 'cube', 'progress'];

function openRequestedScreen() {
  let asked = null;
  try {
    asked = new URLSearchParams(window.location.search).get('screen');
  } catch (error) {
    return;                       // адрес без параметров — обычный запуск
  }
  if (asked && SCREENS.includes(asked) && asked !== 'today') switchScreen(asked);
}

// --- Женский календарь ---------------------------------------------------
// Он стоит на «Прогрессе» не случайно: его задача — объяснить прибавку
// перед месячными ровно там, где человек смотрит на вес и решает, что всё
// зря. Календарь сам по себе тут был бы лишним.

const CYCLE_STRIP_DAYS = 35;

function renderCycle(cycle) {
  const card = document.getElementById('cycle-card');
  if (!cycle || cycle.available === false) { card.hidden = true; return; }
  card.hidden = false;

  document.getElementById('cycle-day').textContent =
    cycle.day ? `день ${cycle.day}` : '';
  document.getElementById('cycle-phase').textContent = cycle.title || 'Пока не отмечено';
  document.getElementById('cycle-note').textContent =
    cycle.note || 'Отметь день, когда начались месячные — дальше я посчитаю сама.';

  // Главная строка карточки. Показывается только когда есть что сказать.
  const weight = document.getElementById('cycle-weight');
  weight.hidden = !cycle.weight_note;
  weight.textContent = cycle.weight_note || '';

  renderCycleStrip(cycle);

  const next = document.getElementById('cycle-next');
  if (cycle.next_start && cycle.days_to_next !== null) {
    const days = cycle.days_to_next;
    next.textContent = days === 0
      ? 'Следующие, скорее всего, начнутся сегодня. Цикл сдвигается — это нормально.'
      : `Следующие примерно через ${days} ${plural(days, 'день', 'дня', 'дней')}. `
        + 'Это оценка, а не расписание.';
  } else {
    next.textContent = cycle.average_length
      ? `Твой обычный цикл — ${cycle.average_length} дней.`
      : 'Отметь ещё пару раз, и я смогу оценивать следующие.';
  }

  document.getElementById('cycle-disclaimer').textContent = cycle.disclaimer || '';
  document.getElementById('cycle-mark').textContent =
    (cycle.starts || []).includes(todayISO())
      ? 'Убрать отметку за сегодня'
      : 'Отметить начало месячных';
}

/** Полоса последних дней: отмеченные начала видно и можно поправить. */
function renderCycleStrip(cycle) {
  const box = document.getElementById('cycle-strip');
  box.innerHTML = '';
  const starts = new Set(cycle.starts || []);
  const now = new Date();

  for (let back = CYCLE_STRIP_DAYS - 1; back >= 0; back -= 1) {
    const moment = new Date(now);
    moment.setDate(now.getDate() - back);
    const iso = isoOf(moment);
    const cell = document.createElement('button');
    cell.className = 'cycle-day';
    if (starts.has(iso)) cell.classList.add('on');
    if (back === 0) cell.classList.add('today');
    cell.textContent = moment.getDate();
    cell.title = iso;
    cell.onclick = () => markCycle(iso);
    box.appendChild(cell);
  }
  // Полоса открывается на сегодняшнем дне, а не на дне месячной давности:
  // человек пришёл отметить сегодня, а не листать назад.
  box.scrollLeft = box.scrollWidth;
}

function isoOf(moment) {
  const pad = (n) => String(n).padStart(2, '0');
  return `${moment.getFullYear()}-${pad(moment.getMonth() + 1)}-${pad(moment.getDate())}`;
}

function todayISO() {
  return isoOf(new Date());
}

async function markCycle(day) {
  try {
    const fresh = await api('/api/cycle', {
      method: 'POST', body: JSON.stringify({ day }),
    });
    haptic('medium');
    renderCycle({ ...fresh, weight_note: null });
    // Вывод про вес считается на сервере вместе с графиком — перезапросим.
    refreshProgress().catch(() => {});
  } catch (error) {
    toast(error.message);
  }
}

function switchScreen(name) {
  for (const tab of document.querySelectorAll('.tab')) {
    tab.classList.toggle('active', tab.dataset.screen === name);
  }
  for (const screen of ['today', 'world', 'gym', 'cube', 'progress']) {
    document.getElementById(`screen-${screen}`).hidden = screen !== name;
  }
  window.scrollTo(0, 0);
  moveArt();
  playEntrance(name);

  if (name === 'cube' && !cubeState.ready) {
    buildCubeControls();
    buildShopMode();
    buildBasket().catch(() => {});
    buildShelf();
    buildFoodModes();
  }
  if (name === 'world') {
    refreshWorld().catch((e) => toast(e.message));
    refreshFriends().catch((e) => toast(e.message));
    refreshBoard().catch((e) => toast(e.message));
  }
  if (name === 'progress' && !progress) refreshProgress().catch((e) => toast(e.message));
  if (name === 'gym' && !gym) {
    buildPicker();
    refreshWorkouts().catch((e) => toast(e.message));
  }
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

  document.getElementById('profile-open').onclick = openProfile;
  document.getElementById('suggest-btn').onclick = () => loadMenu(mealType);
  document.getElementById('recipe-close').onclick = () => {
    document.getElementById('recipe-sheet').hidden = true;
  };
  for (const tab of document.querySelectorAll('.meal-tab')) {
    tab.onclick = () => { mealType = tab.dataset.meal; loadMenu(mealType); };
  }
  document.getElementById('arrival-switch').onclick = switchToMaintain;
  document.getElementById('arrival-close').onclick = () => {
    document.getElementById('arrival').hidden = true;
  };
  document.getElementById('steps-add').onclick = askSteps;
  document.getElementById('steps-sync').onclick = () => openSync();
  document.getElementById('sync-close').onclick = () => {
    document.getElementById('sync-sheet').hidden = true;
  };
  document.getElementById('sync-guide').onclick = openGuide;
  document.getElementById('sync-check').onclick = checkSync;
  document.getElementById('sync-now').onclick = syncNow;
  document.getElementById('guide-close').onclick = () => {
    document.getElementById('guide-sheet').hidden = true;
  };
  document.getElementById('guide-back').onclick = () => guideStep(-1);
  document.getElementById('guide-next').onclick = () => guideStep(1);
  document.getElementById('sync-renew').onclick = async () => {
    const sure = await askYes({
      title: 'Сменить ссылку?',
      text: 'Старая перестанет работать, и команду на айфоне придётся '
        + 'настроить заново.',
      action: 'Сменить',
    });
    if (sure) openSync(true);
  };
  wireTeam();
  document.getElementById('profile-close').onclick = closeProfile;
  document.getElementById('prof-cycle').onclick = () => {
    const on = document.getElementById('prof-cycle').classList.contains('on');
    saveProfile({ cycle: !on });
  };
  document.getElementById('cycle-mark').onclick = () => markCycle(todayISO());
  document.getElementById('notif-toggle').onclick = () => {
    const box = document.getElementById('notif-box');
    box.hidden = !box.hidden;
    document.getElementById('notif-toggle').textContent =
      box.hidden ? 'Настроить подробнее' : 'Свернуть';
  };
  document.getElementById('prof-export').onclick = requestExport;
  document.getElementById('prof-reminders').onclick = () => {
    if (profileData) saveProfile({ reminders: !profileData.profile.reminders });
  };
  document.getElementById('prof-allergies').onchange = (event) =>
    saveProfile({ allergies: event.target.value });
  for (const [id, field] of [['prof-height', 'height'], ['prof-age', 'age'],
                             ['prof-target', 'target_weight'],
                             ['prof-steps-own', 'steps_goal']]) {
    document.getElementById(id).onchange = (event) => saveProfileField(field, event.target);
  }

  wireRipple();
  document.getElementById('moment-open').onclick = openMoment;
  document.getElementById('decide-btn').onclick = decideForMe;
  // Объёмы и «как мерить» — по кнопке: чаще всего записывают один вес.
  for (const [button, box, open, shut] of [
    ['measure-more', 'measure-extra', 'свернуть', 'объёмы'],
    ['measure-help', 'measure-help-text', 'скрыть', 'как мерить'],
  ]) {
    document.getElementById(button).onclick = () => {
      const target = document.getElementById(box);
      target.hidden = !target.hidden;
      document.getElementById(button).textContent = target.hidden ? shut : open;
    };
  }
  wireQuick();
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
  document.getElementById('preps-toggle').onclick = togglePreps;
  document.getElementById('prep-close').onclick = () => {
    document.getElementById('prep-sheet').hidden = true;
  };
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
    // Каскад играет после того, как экран стал видимым: до этого браузер
    // анимировал бы то, чего на экране нет.
    playEntrance('today');
    openRequestedScreen();
  } catch (e) {
    if (e.message.includes('Подписка')) return;   // экран оплаты уже показан
    document.getElementById('loading').textContent =
      e.message.includes('Профиль')
        ? 'Сначала пройди анкету в чате: /start'
        : `Не удалось загрузить: ${e.message}`;
  }
}

init();
