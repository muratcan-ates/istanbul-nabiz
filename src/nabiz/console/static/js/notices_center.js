import { MOCK, get, post } from './api.js';
import { API_BASE } from './config.js';
import { dateTime, esc } from './format.js';
import { FOLLOWS_KEY } from './follow.js';
import { icon } from './icons.js';
import { currentLang, onLang, t } from './i18n_text.js';
import { OUTCOME_KEY } from './report.js';
import { STORAGE_KEY, parseStored } from './request_status.js';

export const STORAGE_KEYS = Object.freeze({ follows: FOLLOWS_KEY, requests: STORAGE_KEY, reports: OUTCOME_KEY });
export const SEEN_KEY = 'nabiz.notices.seen.v1';
export const SEEN_DAYS = 30;
export const SEEN_MAX = 200;
export const SHOWN = 8;
export const STYLESHEET = '/css/notices_center.css';
export const SECTION_ID = 'guncellemeler';
const DAY_MS = 86_400_000;
const ALLOWED_TOPICS = new Set(['metro_line', 'station', 'bus_line', 'knowledge']);

function safeStorage(storage) {
  if (storage) return storage;
  try { return globalThis.localStorage; } catch { return null; }
}

function readStorage(storage, key) {
  try { return storage?.getItem(key) || null; } catch { return null; }
}

function cleanFollows(raw) {
  if (!Array.isArray(raw)) return [];
  const seen = new Set();
  return raw.filter((item) => {
    if (!item || !ALLOWED_TOPICS.has(item.kind) || typeof item.value !== 'string') return false;
    const value = item.value.trim();
    if (!value || value.length > 60) return false;
    const key = `${item.kind}:${value}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  }).slice(0, 10).map(({ kind, value }) => ({ kind, value: value.trim() }));
}

export function readFollows(raw) {
  try { return cleanFollows(JSON.parse(raw || 'null')); } catch { return []; }
}

function boundedMarks(items, now) {
  const oldest = now - SEEN_DAYS * DAY_MS;
  return Object.fromEntries(Object.entries(items || {})
    .filter(([id, stamp]) => /^n_[0-9a-f]{16}$/.test(id) && Number.isFinite(stamp) && stamp > oldest && stamp <= now)
    .sort((a, b) => b[1] - a[1])
    .slice(0, SEEN_MAX));
}

export function parseSeen(raw, now = Date.now()) {
  let value = null;
  try { value = JSON.parse(raw || 'null'); } catch { value = null; }
  if (!value || value.version !== 1 || !value.items || typeof value.items !== 'object' || Array.isArray(value.items)) {
    return { version: 1, items: {} };
  }
  return { version: 1, items: boundedMarks(value.items, now) };
}

export function rememberSeen(seen, ids, now = Date.now()) {
  const items = boundedMarks(seen && seen.version === 1 ? seen.items : {}, now);
  for (const id of ids || []) {
    if (/^n_[0-9a-f]{16}$/.test(id)) items[id] = now;
  }
  return { version: 1, items: boundedMarks(items, now) };
}

export function unreadIds(items, seen) {
  const marks = seen && seen.version === 1 ? seen.items || {} : {};
  return (items || []).filter((item) => item && !Object.hasOwn(marks, item.id)).map((item) => item.id);
}

export function dateLine(item, deviceAt) {
  if (item && item.source === 'report') {
    return Number.isFinite(deviceAt) ? t('ui.notices.date_device', 'bu cihazdan gönderildi · {when}', { when: dateTime(new Date(deviceAt).toISOString()) })
      : t('ui.notices.date_none', 'tarih yok');
  }
  if (!item || !item.recorded_at) return t('ui.notices.date_none', 'tarih yok');
  const when = dateTime(item.recorded_at);
  if (item.date_kind === 'source') return t('ui.notices.date_source', 'İBB kaydı · {when}', { when });
  if (item.date_kind === 'read') return t('ui.notices.date_read', 'Nabız okuması · {when}', { when });
  if (item.date_kind === 'measured') return t('ui.notices.date_measured', 'ölçüldü · {when}', { when });
  if (item.date_kind === 'page') return t('ui.notices.date_page', 'kaynak tarihi · {when}', { when });
  if (item.date_kind === 'sent') return t('ui.notices.date_sent', 'gönderildi · {when}', { when });
  if (item.date_kind === 'answered') return t('ui.notices.date_answered', 'yanıtlandı · {when}', { when });
  return t('ui.notices.date_none', 'tarih yok');
}

function kindLabel(kind) {
  if (kind === 'fault') return t('ui.notices.kind_fault', 'arıza kaydı');
  if (kind === 'measured') return t('ui.notices.kind_measured', 'ölçülen düzensizlik');
  if (kind === 'page') return t('ui.notices.kind_page', 'yeni kaynak');
  if (kind === 'request') return t('ui.notices.kind_request', 'Operatör talebiniz');
  if (kind === 'report') return t('ui.notices.kind_report', 'Asansör bildiriminiz');
  return t('ui.notices.kind_notice', 'duyuru');
}

function bodyCopy(item) {
  if (item.source === 'request') {
    return item.status === 'answered'
      ? { text: t('ui.notices.request_answered', 'Yanıtlandı; yanıtı sohbetteki talep kartında okuyabilirsiniz.'), lang: currentLang() }
      : { text: t('ui.notices.request_waiting', 'Yanıt bekleniyor; yanıt, talebi gönderdiğiniz cihazdaki kartta görünür.'), lang: currentLang() };
  }
  const english = currentLang() === 'en' && item.text_en;
  return { text: english || item.text_tr || '', lang: english ? 'en' : 'tr' };
}

export function itemMarkup(item, { unread = false, deviceAt = null } = {}) {
  const body = bodyCopy(item);
  const label = item.label ? `<b lang="tr">${esc(item.label)}</b>` : '';
  const date = esc(dateLine(item, deviceAt));
  const tags = (unread ? `<span class="nc-tag nc-new">${esc(t('ui.notices.new', 'Yeni'))}</span>` : '')
    + (item.simulated ? `<span class="nc-tag" title="${esc(t('ui.notices.example_note', 'Örnek: operatör rolü simüledir.'))}">${esc(t('ui.notices.example', 'Örnek'))}</span>` : '')
    + (item.severity === 'critical' ? `<span class="nc-tag nc-warn">${esc(t('ui.notices.severity_critical', 'Kritik'))}</span>` : '');
  const calendar = item.calendar
    ? `<button type="button" class="btn btn-quiet" data-nc="calendar" data-id="${esc(item.id)}" aria-describedby="nc-calendar-hint">${esc(t('ui.notices.calendar', 'Takvime ekle'))}</button>`
    : '';
  const statusText = body.text ? `<p class="nc-text" lang="${body.lang}">${esc(body.text)}</p>` : '';
  return `<li class="nc-item${unread ? ' is-unread' : ''}" data-id="${esc(item.id)}">`
    + `<div class="nc-heading">${unread ? '' : ''}${label}<span class="nc-kind">${esc(kindLabel(item.kind))}</span>${tags}</div>`
    + `${statusText}<p class="nc-date">${date}</p>${calendar}</li>`;
}

export function sectionMarkup() {
  return `<details class="more account-detail" id="guncellemeler-detail"><summary><h2 id="notices-title">${icon('bell')} ${esc(t('ui.notices.title', 'Güncellemeler'))}</h2><span class="nc-count" hidden></span></summary>`
    + `<section id="${SECTION_ID}" aria-labelledby="notices-title"><p class="section-note">${esc(t('ui.notices.note', 'takip ettiğiniz konular ve bu cihazdaki kodlar; yalnız kayıtlı veri'))}</p>`
    + `<p class="nc-empty">${esc(t('ui.notices.empty', 'Henüz güncelleme yok; bir konuyu takip ettiğinizde ya da bildirim gönderdiğinizde burada görünür.'))}</p>`
    + '<ul class="nc-unavailable" hidden></ul><ul class="nc-list" hidden></ul>'
    + '<details class="nc-older" hidden><summary class="nc-older-summary"></summary><ul class="nc-list"></ul></details>'
    + `<button type="button" class="btn btn-quiet nc-read-all" hidden>${esc(t('ui.notices.read_all', 'Tümünü okundu say'))}</button>`
    + `<button type="button" class="btn nc-retry" data-nc="retry" hidden>${esc(t('ui.notices.retry', 'Yeniden dene'))}</button>`
    + `<p class="field-hint nc-calendar-hint" id="nc-calendar-hint" hidden>${esc(t('ui.notices.calendar_hint', 'Takvim dosyası kişisel veri içermeyen bir hatırlatıcıdır; aksaklığın ne zaman biteceğini söylemez.'))}</p>`
    + '<p class="status-line nc-status" role="status" aria-live="polite"></p></section></details>';
}

function addStylesheet(doc) {
  if (!doc.head || doc.head.querySelector(`link[href="${STYLESHEET}"]`)) return;
  const link = doc.createElement('link');
  link.rel = 'stylesheet';
  link.href = STYLESHEET;
  doc.head.append(link);
}

function parseCodes(storage, key) {
  return parseStored(readStorage(storage, key));
}

function visibleIds(root, items) {
  const older = root.querySelector('.nc-older');
  return older && older.open ? items.map((item) => item.id) : items.slice(0, SHOWN).map((item) => item.id);
}

export function mountNotices(doc, storage = null) {
  if (!doc || MOCK) return null;
  if (doc.querySelector('#guncellemeler-detail') || doc.querySelector('#guncellemeler')) return null;
  const follow = doc.querySelector('#takip');
  const account = doc.querySelector('#hesabim');
  if (!follow && !account) return null;
  const store = safeStorage(storage);
  const holder = doc.createElement('div');
  holder.innerHTML = sectionMarkup();
  const root = holder.firstElementChild;
  if (follow) {
    const details = follow.closest('details');
    if (details && details.parentNode) details.parentNode.insertBefore(root, details.nextSibling);
    else if (account) account.append(root);
    else return null;
  } else account.append(root);
  addStylesheet(doc);
  if (doc.defaultView?.location?.hash === '#guncellemeler') root.open = true;

  const section = root.querySelector(`#${SECTION_ID}`);
  const seen = parseSeen(readStorage(store, SEEN_KEY));
  const state = { items: [], unavailable: [], lastCheck: 0, stale: false, loaded: false, sources: null, deviceTimes: {} };

  function saveSeen(ids) {
    if (!ids.length) return;
    const next = rememberSeen(seen, ids, Date.now());
    seen.version = next.version;
    seen.items = next.items;
    try { store?.setItem(SEEN_KEY, JSON.stringify(next)); } catch { /* private browsing keeps the current page usable */ }
    render();
  }

  function render() {
    const currentUnread = new Set(unreadIds(state.items, seen));
    const top = state.items.slice(0, SHOWN);
    const older = state.items.slice(SHOWN);
    const list = section.querySelector(':scope > .nc-list');
    const more = section.querySelector('.nc-older');
    const olderList = more.querySelector('.nc-list');
    const unavailable = section.querySelector('.nc-unavailable');
    const empty = section.querySelector('.nc-empty');
    const count = root.querySelector('.nc-count');
    const readAll = section.querySelector('.nc-read-all');
    const hint = section.querySelector('.nc-calendar-hint');
    const unreadCount = currentUnread.size;
    count.hidden = unreadCount === 0;
    count.textContent = t('ui.notices.count', '{count} yeni', { count: unreadCount });
    list.hidden = top.length === 0;
    list.innerHTML = top.map((item) => itemMarkup(item, { unread: currentUnread.has(item.id), deviceAt: state.deviceTimes[item.id] })).join('');
    more.hidden = older.length === 0;
    if (older.length) {
      more.querySelector('.nc-older-summary').textContent = t('ui.notices.more', 'Daha eski {count} güncelleme', { count: older.length });
      olderList.innerHTML = older.map((item) => itemMarkup(item, { unread: currentUnread.has(item.id), deviceAt: state.deviceTimes[item.id] })).join('');
    }
    unavailable.hidden = state.unavailable.length === 0;
    unavailable.innerHTML = state.unavailable.map((item) => `<li>${esc(t('ui.notices.unavailable', 'Kontrol edilemedi:'))} <span lang="tr">${esc(item.text_tr || '')}</span></li>`).join('');
    empty.hidden = state.items.length > 0 || state.unavailable.length > 0;
    readAll.hidden = unreadCount === 0;
    hint.hidden = !state.items.some((item) => item.calendar);
  }

  async function sourceData() {
    let follows = [];
    if (readAccount()) {
      try {
        follows = cleanFollows((await get('/api/account')).follows);
        return { follows, requests: parseCodes(store, STORAGE_KEYS.requests), reports: parseCodes(store, STORAGE_KEYS.reports) };
      } catch { follows = []; }
    }
    if (!follows.length) follows = readFollows(readStorage(store, STORAGE_KEYS.follows));
    const requests = parseCodes(store, STORAGE_KEYS.requests);
    const reports = parseCodes(store, STORAGE_KEYS.reports);
    return { follows, requests, reports };
  }

  async function refresh() {
    if (state.refreshing) { state.stale = true; return; }
    state.refreshing = true;
    const priorUnread = unreadIds(state.items, seen).length;
    const status = section.querySelector('.nc-status');
    const retry = section.querySelector('.nc-retry');
    if (!state.loaded) status.textContent = t('ui.notices.loading', 'Güncellemeler alınıyor.');
    try {
      const sources = await sourceData();
      state.sources = sources;
      if (!sources.follows.length && !sources.requests.length && !sources.reports.length) {
        state.items = [];
        state.unavailable = [];
        state.deviceTimes = {};
      } else {
        const result = await post('/api/notices', {
          topics: sources.follows,
          requests: sources.requests.map((item) => item.code),
          reports: sources.reports.map((item) => item.code),
        });
        state.items = Array.isArray(result.items) ? result.items : [];
        state.unavailable = Array.isArray(result.unavailable) ? result.unavailable : [];
        state.deviceTimes = {};
        for (const item of state.items) {
          if (item.source === 'report') state.deviceTimes[item.id] = sources.reports[item.ref_index]?.at;
        }
      }
      state.lastCheck = Date.now();
      state.stale = false;
      retry.hidden = true;
      const nextUnread = unreadIds(state.items, seen).length;
      if (state.loaded && nextUnread > priorUnread) {
        status.textContent = t('ui.notices.announce', 'Güncellemelerde {count} yeni kayıt var.', { count: nextUnread - priorUnread });
      } else if (!state.loaded) status.textContent = '';
      state.loaded = true;
    } catch (error) {
      const msg = error && error.message ? error.message : '';
      status.innerHTML = `${esc(t('ui.notices.failed', 'Güncellemeler şu an alınamadı: {message}', { message: '' }))}<span lang="tr">${esc(msg)}</span>`;
      retry.hidden = false;
      state.loaded = true;
    } finally {
      state.refreshing = false;
      render();
    }
  }

  async function download(item, button) {
    if (button.getAttribute('aria-busy') === 'true') return;
    button.setAttribute('aria-busy', 'true');
    button.setAttribute('aria-disabled', 'true');
    section.querySelector('.nc-status').textContent = t('ui.notices.calendar_loading', 'Takvim dosyası hazırlanıyor.');
    const sources = state.sources;
    const payload = item.source === 'topic'
      ? { source: 'topic', topic: sources.follows[item.ref_index], code: null }
      : { source: item.source, topic: null, code: sources[item.source === 'request' ? 'requests' : 'reports'][item.ref_index]?.code };
    try {
      const response = await fetch(`${API_BASE}/api/notices/calendar`, {
        method: 'POST',
        headers: { Accept: 'text/calendar', 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...payload, item_id: item.id, lang: currentLang() }),
      });
      if (!response.ok) {
        let problem = null;
        try { problem = await response.json(); } catch { problem = null; }
        throw new Error(problem && problem.message ? problem.message : '');
      }
      const blob = await response.blob();
      const href = URL.createObjectURL(blob);
      const link = doc.createElement('a');
      link.href = href;
      link.download = 'nabiz-hatirlatici.ics';
      link.hidden = true;
      doc.body.append(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(href);
      section.querySelector('.nc-status').textContent = t('ui.notices.calendar_done', 'Takvim dosyası indirildi.');
    } catch (error) {
      const message = error && error.message ? error.message : '';
      section.querySelector('.nc-status').innerHTML = `${esc(t('ui.notices.calendar_failed', 'Takvim dosyası hazırlanamadı: {message}', { message: '' }))}<span lang="tr">${esc(message)}</span>`;
    } finally {
      button.removeAttribute('aria-busy');
      button.removeAttribute('aria-disabled');
    }
  }

  root.addEventListener('click', (event) => {
    const button = event.target.closest('button[data-nc="calendar"]');
    if (button) {
      const item = state.items.find((row) => row.id === button.dataset.id);
      if (item) void download(item, button);
      return;
    }
    if (event.target.closest('[data-nc="retry"]')) { void refresh(); return; }
    if (event.target.closest('.nc-read-all')) {
      saveSeen(visibleIds(root, state.items));
      root.querySelector('summary')?.focus({ preventScroll: true });
    }
  });
  root.addEventListener('toggle', (event) => {
    if (event.target !== root) return;
    if (root.open) {
      if (state.stale || Date.now() - state.lastCheck > 60_000) void refresh();
    } else saveSeen(visibleIds(root, state.items));
  }, true);
  doc.addEventListener('visibilitychange', () => {
    if (doc.visibilityState === 'visible' && Date.now() - state.lastCheck > 5 * 60_000) void refresh();
  });
  doc.addEventListener('nabiz:account-changed', () => { state.stale = true; void refresh(); });
  doc.addEventListener('nabiz:report-sent', () => { state.stale = true; });
  doc.defaultView?.addEventListener('pagehide', () => { if (root.open) saveSeen(visibleIds(root, state.items)); });
  onLang(() => render());
  render();
  void refresh();
  return { refresh, render };
}

if (typeof document !== 'undefined') mountNotices(document);
