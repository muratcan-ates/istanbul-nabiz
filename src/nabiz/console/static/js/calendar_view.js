/* The Takvim tab as a calendar: a week strip and an hour grid (day on a phone, week on a wide screen), like the
   phone's own calendar. It draws three sources: plans kept in this browser (a visitor's plans stay on the device,
   P06), the account's server plans when /api/plans answers, and the E73 day plan. Other modules add a plan with
   the `nabiz:calendar-add` event; nothing here calls İBB or a model. */
import { API_BASE } from './config.js';
import { currentLang, t } from './i18n_text.js';

export const STORE_KEY = 'nabiz.calendar.v1';
const DAY_PLAN_KEY = 'nabiz.dayplan.v1';
const HOUR_PX = 52;
const FIRST_HOUR = 0;
const SCROLL_TO_HOUR = 7;
const WIDE = '(min-width: 900px)';
const MS_DAY = 86400000;

const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[char]));
const pad = (value) => String(value).padStart(2, '0');
const locale = () => (currentLang() === 'en' ? 'en-GB' : 'tr-TR');
const isoDay = (date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
const hhmm = (date) => `${pad(date.getHours())}:${pad(date.getMinutes())}`;
const startOfDay = (date) => new Date(date.getFullYear(), date.getMonth(), date.getDate());
const addDays = (date, days) => new Date(date.getFullYear(), date.getMonth(), date.getDate() + days);
const mondayOf = (date) => addDays(startOfDay(date), -((date.getDay() + 6) % 7));

function copy() {
  return {
    region: t('ui.calendar.region', 'Takvim'),
    today: t('ui.calendar.today', 'Bugün'),
    prev: t('ui.calendar.prev', 'Önceki'),
    next: t('ui.calendar.next', 'Sonraki'),
    day: t('ui.calendar.day', 'Gün'),
    week: t('ui.calendar.week', 'Hafta'),
    allDay: t('ui.calendar.all_day', 'Tüm gün'),
    add: t('ui.calendar.add', 'Etkinlik ekle'),
    title: t('ui.calendar.form_title', 'Başlık'),
    date: t('ui.calendar.form_date', 'Tarih'),
    start: t('ui.calendar.form_start', 'Başlangıç'),
    end: t('ui.calendar.form_end', 'Bitiş'),
    place: t('ui.calendar.form_place', 'Yer (isteğe bağlı)'),
    save: t('ui.calendar.save', 'Kaydet'),
    cancel: t('ui.calendar.cancel', 'Vazgeç'),
    close: t('ui.calendar.close', 'Kapat'),
    del: t('ui.calendar.delete', 'Sil'),
    delAsk: t('ui.calendar.delete_confirm', 'Bu etkinlik silinsin mi?'),
    deleted: t('ui.calendar.deleted', 'Etkinlik silindi.'),
    saved: t('ui.calendar.saved', 'Takvime eklendi.'),
    ics: t('ui.calendar.ics', 'Takvim dosyası indir'),
    source: t('ui.calendar.source_link', 'Kaynağı aç'),
    emptyDay: t('ui.calendar.empty_day', 'Bu gün için kayıt yok.'),
    emptyWeek: t('ui.calendar.empty_week', 'Bu hafta için kayıt yok.'),
    device: t('ui.calendar.where_device', 'Bu takvim bu tarayıcıda saklanır; hesabınızla giriş yaptığınızda kayıtlarınız da burada görünür.'),
    errTitle: t('ui.calendar.error_title', 'Başlık yazın.'),
    errTime: t('ui.calendar.error_time', 'Bitiş başlangıçtan sonra olmalı.'),
    now: t('ui.calendar.now', 'Şimdi'),
    account: t('ui.calendar.from_account', 'Hesabınızdaki kayıt'),
    dayPlan: t('ui.calendar.day_plan', 'Gün planı'),
    sample: t('ui.calendar.sample_note', 'Örnek etkinlik: gösterim için eklendi.'),
  };
}

/* ---- sources ---- */

function readJson(key) {
  try { return JSON.parse(window.localStorage.getItem(key) || 'null'); } catch (error) { return null; }
}
export function readDevicePlans() {
  const value = readJson(STORE_KEY);
  return Array.isArray(value) ? value.filter((plan) => plan && plan.id && plan.title && plan.starts_at) : [];
}
function writeDevicePlans(plans) {
  try { window.localStorage.setItem(STORE_KEY, JSON.stringify(plans)); return true; } catch (error) { return false; }
}

/* Four sample plans, written once into an empty calendar so the week is not blank on first open (owner, 30 Sep).
   They are marked sample: the panel says so, and they can be deleted like any other plan. The first is the
   recorded Kültür AŞ listing; the others are examples, not real events. */
export const SAMPLES_KEY = 'nabiz.calendar.samples.v1';
export function samplePlans(today = new Date()) {
  const day = (offset) => isoDay(addDays(startOfDay(today), offset));
  const saturday = (6 - today.getDay() + 7) % 7 || 7;
  return [
    { id: 'sample-1', sample: true, title: t('ui.calendar.sample_1', 'Harbiye Açık Hava konseri'), place: t('ui.calendar.sample_1_place', 'Harbiye Cemil Topuzlu Açık Hava Tiyatrosu'),
      starts_at: `${day(0)}T20:30`, ends_at: `${day(0)}T22:30`, source_url: 'https://kultur.istanbul/' },
    { id: 'sample-2', sample: true, title: t('ui.calendar.sample_2', 'Çocuk atölyesi'), place: t('ui.calendar.sample_2_place', 'Kadıköy'),
      starts_at: `${day(1)}T14:00`, ends_at: `${day(1)}T15:30` },
    { id: 'sample-3', sample: true, title: t('ui.calendar.sample_3', 'Kütüphane randevusu'), place: t('ui.calendar.sample_3_place', 'Atatürk Kitaplığı'),
      starts_at: `${day(2)}T10:00`, ends_at: `${day(2)}T11:00` },
    { id: 'sample-4', sample: true, title: t('ui.calendar.sample_4', 'Ailece orman yürüyüşü'), place: t('ui.calendar.sample_4_place', 'Belgrad Ormanı'),
      starts_at: `${day(saturday)}T11:00`, ends_at: `${day(saturday)}T13:00` },
  ];
}
function seedSamples() {
  try {
    if (window.localStorage.getItem(SAMPLES_KEY) || readDevicePlans().length) return;
    writeDevicePlans(samplePlans());
    window.localStorage.setItem(SAMPLES_KEY, '1');
  } catch (error) { /* storage may be disabled: the calendar stays empty */ }
}
function parseMoment(value, allDay) {
  if (typeof value !== 'string' || !value) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/.exec(value);
  if (!match) return null;
  const [, y, m, d, hh, mm] = match;
  if (!allDay && /(?:Z|[+-]\d{2}:?\d{2})$/.test(value)) {
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }
  return new Date(Number(y), Number(m) - 1, Number(d), Number(hh || 0), Number(mm || 0));
}
export function normalize(plan, origin) {
  const allDay = Boolean(plan.all_day) || !/[T ]\d{2}:\d{2}/.test(String(plan.starts_at || ''));
  const start = parseMoment(plan.starts_at, allDay);
  if (!start) return null;
  let end = parseMoment(plan.ends_at, allDay);
  if (!end || end <= start) end = allDay ? addDays(start, 1) : new Date(start.getTime() + 3600000);
  return {
    id: `${origin}:${plan.id}`, rawId: plan.id, origin, title: String(plan.title), start, end, allDay,
    place: plan.place || '', url: plan.source_url || '', sample: Boolean(plan.sample),
  };
}
function dayPlanItem() {
  const plan = readJson(DAY_PLAN_KEY);
  if (!plan || plan.v !== 1 || !plan.event?.id || typeof plan.date !== 'string') return null;
  const time = /^\d{2}:\d{2}/.test(plan.event.time || '') ? plan.event.time.slice(0, 5) : '';
  return normalize({
    id: plan.event.id, title: plan.event.title || '', starts_at: time ? `${plan.date}T${time}` : plan.date,
    all_day: !time, place: plan.event.venue || '', source_url: plan.event.link || '',
  }, 'dayplan');
}
async function serverPlans() {
  try {
    const response = await fetch(`${API_BASE}/api/plans`, { credentials: 'same-origin', headers: { Accept: 'application/json' } });
    if (!response.ok) return [];
    const body = await response.json();
    return Array.isArray(body?.plans) ? body.plans : [];
  } catch (error) { return []; }
}

/* ---- layout ---- */

export function lanes(items) {
  const sorted = [...items].sort((a, b) => a.start - b.start || b.end - a.end);
  const placed = [];
  let cluster = [];
  let clusterEnd = 0;
  const flush = () => {
    const width = Math.max(1, ...cluster.map((item) => item.lane + 1));
    cluster.forEach((item) => { item.lanes = width; placed.push(item); });
    cluster = [];
  };
  for (const item of sorted) {
    if (cluster.length && item.start.getTime() >= clusterEnd) flush();
    const taken = new Set(cluster.filter((other) => other.end > item.start).map((other) => other.lane));
    let lane = 0;
    while (taken.has(lane)) lane += 1;
    cluster.push({ ...item, lane });
    clusterEnd = Math.max(clusterEnd, item.end.getTime());
  }
  if (cluster.length) flush();
  return placed;
}

export function icsText(item, stamp = new Date()) {
  const utc = (date) => `${date.getUTCFullYear()}${pad(date.getUTCMonth() + 1)}${pad(date.getUTCDate())}T${pad(date.getUTCHours())}${pad(date.getUTCMinutes())}00Z`;
  const dateOnly = (date) => `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}`;
  const text = (value) => String(value).replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\r?\n/g, '\\n');
  const lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Istanbul Nabiz//Calendar//TR', 'CALSCALE:GREGORIAN', 'BEGIN:VEVENT',
    `UID:${text(item.id)}@nabiz`, `DTSTAMP:${utc(stamp)}`];
  if (item.allDay) lines.push(`DTSTART;VALUE=DATE:${dateOnly(item.start)}`, `DTEND;VALUE=DATE:${dateOnly(item.end)}`);
  else lines.push(`DTSTART:${utc(item.start)}`, `DTEND:${utc(item.end)}`);
  lines.push(`SUMMARY:${text(item.title)}`);
  if (item.place) lines.push(`LOCATION:${text(item.place)}`);
  if (item.url) lines.push(`URL:${text(item.url)}`);
  lines.push('END:VEVENT', 'END:VCALENDAR');
  return `${lines.join('\r\n')}\r\n`;
}

/* ---- view ---- */

function createView(doc, host) {
  const state = { anchor: startOfDay(new Date()), mode: null, items: [], server: [], open: null, status: '' };
  const wide = () => (typeof window.matchMedia === 'function' ? window.matchMedia(WIDE).matches : true);
  const mode = () => state.mode || (wide() ? 'week' : 'day');
  const days = () => (mode() === 'week' ? Array.from({ length: 7 }, (_, index) => addDays(mondayOf(state.anchor), index)) : [state.anchor]);

  function collect() {
    const device = readDevicePlans().map((plan) => normalize(plan, 'device'));
    const server = state.server.map((plan) => normalize(plan, 'account'));
    state.items = [...device, ...server, dayPlanItem()].filter(Boolean);
  }
  const onDay = (item, day) => item.start < addDays(day, 1) && item.end > day;

  function header(c) {
    const fmt = new Intl.DateTimeFormat(locale(), mode() === 'week' ? { month: 'long', year: 'numeric' } : { weekday: 'long', day: 'numeric', month: 'long' });
    const label = fmt.format(state.anchor);
    const seg = (value, text) => `<button type="button" class="cal-seg" data-mode="${value}" aria-pressed="${mode() === value}">${esc(text)}</button>`;
    return `<div class="cal-toolbar">
      <div class="cal-nav">
        <button type="button" class="cal-icon" data-step="-1" aria-label="${esc(c.prev)}"><span aria-hidden="true">‹</span></button>
        <button type="button" class="cal-today" data-today>${esc(c.today)}</button>
        <button type="button" class="cal-icon" data-step="1" aria-label="${esc(c.next)}"><span aria-hidden="true">›</span></button>
        <h3 class="cal-label" aria-live="polite">${esc(label)}</h3>
      </div>
      <div class="cal-tools">
        <div class="cal-segs" role="group" aria-label="${esc(c.region)}">${seg('day', c.day)}${seg('week', c.week)}</div>
        <button type="button" class="btn btn-primary cal-add" data-add>${esc(c.add)}</button>
      </div>
    </div>`;
  }

  function strip() {
    const week = Array.from({ length: 7 }, (_, index) => addDays(mondayOf(state.anchor), index));
    const today = isoDay(new Date());
    const name = new Intl.DateTimeFormat(locale(), { weekday: 'short' });
    const full = new Intl.DateTimeFormat(locale(), { weekday: 'long', day: 'numeric', month: 'long' });
    return `<div class="cal-strip">${week.map((day) => {
      const busy = state.items.some((item) => onDay(item, day));
      const selected = mode() === 'day' ? isoDay(day) === isoDay(state.anchor) : false;
      return `<button type="button" class="cal-strip-day${isoDay(day) === today ? ' is-today' : ''}" data-pick="${isoDay(day)}"
        aria-pressed="${selected}" aria-label="${esc(full.format(day))}">
        <span class="cal-strip-name" aria-hidden="true">${esc(name.format(day))}</span>
        <span class="cal-strip-num" aria-hidden="true">${day.getDate()}</span>
        <span class="cal-strip-dot${busy ? ' is-busy' : ''}" aria-hidden="true"></span></button>`;
    }).join('')}</div>`;
  }

  function eventButton(item, c) {
    const time = item.allDay ? c.allDay : `${hhmm(item.start)}-${hhmm(item.end)}`;
    const label = t('ui.calendar.event_label', '{time}, {title}', { time, title: item.title });
    return `<button type="button" class="cal-event cal-origin-${item.origin}${item.sample ? ' cal-sample' : ''}" data-open="${esc(item.id)}" aria-label="${esc(label)}${item.place ? `, ${esc(item.place)}` : ''}">
      <span class="cal-event-title">${esc(item.title)}</span>
      <span class="cal-event-meta">${esc(item.allDay ? (item.place || c.allDay) : `${hhmm(item.start)}${item.place ? ` · ${item.place}` : ''}`)}</span></button>`;
  }

  function grid(c) {
    const list = days();
    const now = new Date();
    const full = new Intl.DateTimeFormat(locale(), { weekday: 'short', day: 'numeric' });
    const cols = `style="--cal-cols:${list.length}"`;
    const head = list.length > 1
      ? `<div class="cal-head" ${cols}><span></span>${list.map((day) => `<span class="cal-head-day${isoDay(day) === isoDay(now) ? ' is-today' : ''}">${esc(full.format(day))}</span>`).join('')}</div>`
      : '';
    const allDay = list.map((day) => state.items.filter((item) => item.allDay && onDay(item, day)));
    const allDayRow = allDay.some((row) => row.length)
      ? `<div class="cal-allday" ${cols}><span class="cal-allday-label">${esc(c.allDay)}</span>${allDay.map((row) => `<div class="cal-allday-cell">${row.map((item) => eventButton(item, c)).join('')}</div>`).join('')}</div>`
      : '';
    const hours = Array.from({ length: 24 - FIRST_HOUR }, (_, index) => FIRST_HOUR + index);
    const ruler = hours.map((hour) => `<div class="cal-hour"><span>${pad(hour)}:00</span></div>`).join('');
    const columns = list.map((day) => {
      const timed = lanes(state.items.filter((item) => !item.allDay && onDay(item, day)));
      const blocks = timed.map((item) => {
        const from = Math.max(item.start.getTime(), day.getTime());
        const to = Math.min(item.end.getTime(), day.getTime() + MS_DAY);
        const top = ((from - day.getTime()) / 3600000 - FIRST_HOUR) * HOUR_PX;
        const height = Math.max(24, ((to - from) / 3600000) * HOUR_PX - 2);
        const style = `top:${top}px;height:${height}px;left:calc(${(item.lane / item.lanes) * 100}% + 2px);width:calc(${100 / item.lanes}% - 4px)`;
        return `<div class="cal-block" style="${style}">${eventButton(item, c)}</div>`;
      }).join('');
      const nowLine = isoDay(day) === isoDay(now)
        ? `<div class="cal-now" style="top:${((now - day) / 3600000 - FIRST_HOUR) * HOUR_PX}px" aria-hidden="true" title="${esc(c.now)}"></div>` : '';
      return `<div class="cal-col" role="group" aria-label="${esc(new Intl.DateTimeFormat(locale(), { weekday: 'long', day: 'numeric', month: 'long' }).format(day))}">${blocks}${nowLine}</div>`;
    }).join('');
    const empty = state.items.some((item) => list.some((day) => onDay(item, day))) ? '' : `<p class="cal-empty">${esc(list.length > 1 ? c.emptyWeek : c.emptyDay)}</p>`;
    return `${head}${allDayRow}${empty}<div class="cal-scroll" tabindex="-1"><div class="cal-body" style="--cal-cols:${list.length};--cal-hour:${HOUR_PX}px">
      <div class="cal-ruler" aria-hidden="true">${ruler}</div>${columns}</div></div>`;
  }

  function detail(c) {
    const item = state.items.find((entry) => entry.id === state.open);
    if (!item) return '';
    const when = item.allDay
      ? `${new Intl.DateTimeFormat(locale(), { weekday: 'long', day: 'numeric', month: 'long' }).format(item.start)} · ${c.allDay}`
      : `${new Intl.DateTimeFormat(locale(), { weekday: 'long', day: 'numeric', month: 'long' }).format(item.start)} · ${hhmm(item.start)}-${hhmm(item.end)}`;
    const note = item.sample ? c.sample : item.origin === 'account' ? c.account : item.origin === 'dayplan' ? c.dayPlan : '';
    const remove = item.origin === 'device'
      ? (state.confirm ? `<p class="cal-ask">${esc(c.delAsk)}</p><button type="button" class="btn" data-delete-yes>${esc(c.del)}</button><button type="button" class="btn-quiet" data-delete-no>${esc(c.cancel)}</button>`
        : `<button type="button" class="btn-quiet" data-delete>${esc(c.del)}</button>`) : '';
    return `<div class="cal-detail" role="dialog" aria-labelledby="cal-detail-title">
      <h3 id="cal-detail-title" tabindex="-1">${esc(item.title)}</h3>
      <p>${esc(when)}</p>${item.place ? `<p>${esc(item.place)}</p>` : ''}${note ? `<p class="cal-note">${esc(note)}</p>` : ''}
      <div class="cal-detail-actions">
        <button type="button" class="btn" data-ics>${esc(c.ics)}</button>
        ${item.url ? `<a class="btn-quiet" href="${esc(item.url)}" target="_blank" rel="noopener noreferrer">${esc(c.source)}</a>` : ''}
        ${remove}
        <button type="button" class="btn-quiet" data-close>${esc(c.close)}</button>
      </div></div>`;
  }

  function form(c) {
    if (!state.adding) return '';
    const day = isoDay(state.anchor);
    return `<form class="cal-form" novalidate>
      <label>${esc(c.title)}<input name="title" required maxlength="120" autocomplete="off"></label>
      <div class="cal-form-row">
        <label>${esc(c.date)}<input name="date" type="date" value="${day}" required></label>
        <label>${esc(c.start)}<input name="start" type="time" value="10:00"></label>
        <label>${esc(c.end)}<input name="end" type="time" value="11:00"></label>
      </div>
      <label>${esc(c.place)}<input name="place" maxlength="200" autocomplete="off"></label>
      <p class="cal-error" role="alert"></p>
      <div class="cal-detail-actions"><button type="submit" class="btn btn-primary">${esc(c.save)}</button><button type="button" class="btn-quiet" data-cancel>${esc(c.cancel)}</button></div>
    </form>`;
  }

  function render(focus) {
    const previous = host.querySelector('.cal-scroll')?.scrollTop;
    collect();
    const c = copy();
    host.innerHTML = `<div class="cal" aria-label="${esc(c.region)}">${header(c)}${form(c)}${strip()}${detail(c)}
      <div class="cal-grid">${grid(c)}</div>
      <p class="cal-foot">${esc(c.device)}</p>
      <p class="cal-status" role="status" aria-live="polite">${esc(state.status)}</p></div>`;
    state.status = '';
    const scroller = host.querySelector('.cal-scroll');
    if (scroller && !state.scrolled && scroller.clientHeight > 0 && scroller.scrollHeight > scroller.clientHeight) {
      const now = new Date();
      const hour = days().some((day) => isoDay(day) === isoDay(now)) ? Math.max(0, now.getHours() - 1) : SCROLL_TO_HOUR;
      scroller.scrollTop = (hour - FIRST_HOUR) * HOUR_PX;
      state.scrolled = true;
    } else if (scroller && typeof previous === 'number') scroller.scrollTop = previous;
    if (focus) host.querySelector(focus)?.focus();
  }

  function download(item) {
    const blob = new Blob([icsText(item)], { type: 'text/calendar;charset=utf-8' });
    const link = doc.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `nabiz-${isoDay(item.start)}.ics`;
    doc.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  }

  function add(plan, announce = true) {
    const saved = { id: plan.id || `p${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`, ...plan };
    const plans = readDevicePlans().filter((entry) => entry.id !== saved.id);
    plans.push(saved);
    writeDevicePlans(plans);
    const item = normalize(saved, 'device');
    if (item) { state.anchor = startOfDay(item.start); state.scrolled = false; }
    if (announce) state.status = copy().saved;
    render();
  }

  host.addEventListener('click', (event) => {
    const target = event.target.closest('button, a');
    if (!target || !host.contains(target)) return;
    const data = target.dataset;
    if (data.step) { state.anchor = addDays(state.anchor, Number(data.step) * (mode() === 'week' ? 7 : 1)); state.scrolled = false; render(); }
    else if ('today' in data) { state.anchor = startOfDay(new Date()); state.scrolled = false; render('[data-today]'); }
    else if (data.mode) { state.mode = data.mode; state.scrolled = false; render(`[data-mode="${data.mode}"]`); }
    else if (data.pick) { state.anchor = parseMoment(data.pick, true); state.mode = 'day'; state.scrolled = false; render(`[data-pick="${data.pick}"]`); }
    else if ('add' in data) { state.adding = true; state.open = null; render('.cal-form input[name="title"]'); }
    else if ('cancel' in data) { state.adding = false; render('[data-add]'); }
    else if (data.open) { state.open = data.open; state.confirm = false; state.adding = false; render('#cal-detail-title'); }
    else if ('close' in data) { const id = state.open; state.open = null; render(`[data-open="${CSS.escape(id || '')}"]`); }
    else if ('ics' in data) { const item = state.items.find((entry) => entry.id === state.open); if (item) download(item); }
    else if ('delete' in data) { state.confirm = true; render('[data-delete-yes]'); }
    else if ('deleteNo' in data) { state.confirm = false; render('[data-delete]'); }
    else if ('deleteYes' in data) {
      const item = state.items.find((entry) => entry.id === state.open);
      if (item) writeDevicePlans(readDevicePlans().filter((plan) => plan.id !== item.rawId));
      state.open = null; state.confirm = false; state.status = copy().deleted; render('[data-add]');
    }
  });

  host.addEventListener('submit', (event) => {
    event.preventDefault();
    const formEl = event.target;
    const c = copy();
    const value = (name) => String(formEl.elements[name]?.value || '').trim();
    const error = formEl.querySelector('.cal-error');
    if (!value('title')) { error.textContent = c.errTitle; formEl.elements.title.focus(); return; }
    const date = value('date') || isoDay(state.anchor);
    const start = value('start');
    const end = value('end');
    if (start && end && end <= start) { error.textContent = c.errTime; formEl.elements.end.focus(); return; }
    state.adding = false;
    add({
      title: value('title').slice(0, 120), place: value('place').slice(0, 200) || null,
      starts_at: start ? `${date}T${start}` : date, ends_at: start ? `${date}T${end || start}` : date, all_day: !start,
    });
  });

  host.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && (state.open || state.adding)) { state.open = null; state.adding = false; render('[data-add]'); }
  });

  return {
    render,
    add,
    shown() { if (!state.scrolled) render(); },
    tick() { if (!state.adding && !state.open) render(); },
    async refresh() { state.server = await serverPlans(); render(); },
  };
}

function mount(doc) {
  const host = doc.getElementById('takvim-mount');
  if (!host || host.dataset.calendar) return null;
  host.dataset.calendar = 'on';
  doc.getElementById('takvim-empty')?.setAttribute('hidden', '');
  seedSamples();
  const view = createView(doc, host);
  if (!doc.querySelector('link[data-calendar-style]')) {
    const link = doc.createElement('link');
    link.rel = 'stylesheet'; link.href = '/css/calendar_view.css'; link.dataset.calendarStyle = 'true';
    link.addEventListener('load', () => view.shown());
    doc.head.append(link);
  }
  view.render();
  view.refresh();
  window.addEventListener('nabiz:lang', () => view.render());
  window.addEventListener('nabiz:calendar-add', (event) => { if (event.detail?.title && event.detail?.starts_at) view.add(event.detail); });
  window.addEventListener('storage', (event) => { if (event.key === STORE_KEY || event.key === DAY_PLAN_KEY) view.render(); });
  window.addEventListener('hashchange', () => { if (window.location.hash === '#takvim') view.refresh(); });
  if (typeof IntersectionObserver === 'function') {
    new IntersectionObserver((entries) => { if (entries.some((entry) => entry.isIntersecting)) view.shown(); }).observe(host);
  }
  setInterval(() => { if (!host.closest('[hidden]')) view.tick(); }, 60000);
  return view;
}

if (typeof document !== 'undefined') {
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => mount(document));
  else mount(document);
}
