/* A short citizen report stays beside the lift card and survives its refreshes. */

import { MOCK, get, post } from './api.js';
import { LIFT_TR } from './cards.js';
import { esc } from './format.js';
import { icon } from './icons.js';
import { parseStored, POLL_MS } from './request_status.js';

const pageDocument = typeof document === 'undefined' ? null : document;
const host = pageDocument?.querySelector('#alternative') || null;
const STORAGE_KEY = 'nabiz.report.v1';
const WINDOW_MS = 30 * 60 * 1000;
const view = { key: '', station: '', kind: '', open: false, busy: false, bucket: null, status: '', bad: false, done: null };
let focusKey = '';
let focusBucket = null;

function keyFor(station, kind) {
  return station.toLocaleLowerCase('tr') + '|' + kind;
}

function readMarks() {
  try {
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
    if (!stored || typeof stored !== 'object' || Array.isArray(stored)) return {};
    const cutoff = Date.now() - WINDOW_MS;
    const valid = {};
    Object.entries(stored).forEach(([key, stamp]) => {
      if (typeof stamp === 'number' && stamp >= cutoff && stamp <= Date.now()) valid[key] = stamp;
    });
    if (Object.keys(valid).length !== Object.keys(stored).length) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(valid));
    }
    return valid;
  } catch (error) {
    return {};
  }
}

function saveMark(key) {
  try {
    const marks = readMarks();
    marks[key] = Date.now();
    localStorage.setItem(STORAGE_KEY, JSON.stringify(marks));
  } catch (error) {
    /* Storage can be disabled; the server response still completes this report. */
  }
}

function liftKind(card) {
  const body = card.querySelector('.card-body')?.textContent || '';
  const status = card.dataset.lift
    || (body.includes(LIFT_TR.out_of_service) ? 'out_of_service'
      : body.includes(LIFT_TR.working) ? 'working' : 'unknown');
  return status === 'out_of_service' ? 'data_wrong' : 'not_working';
}

function selectCard() {
  const card = host.querySelector('#alternative-card');
  if (!card) return null;
  const station = card.dataset.station || card.querySelector('.card-body b')?.textContent.trim() || '';
  if (!station) return null;
  const kind = liftKind(card);
  const key = keyFor(station, kind);
  if (view.key !== key) {
    Object.assign(view, { key, station, kind, open: false, busy: false, bucket: null, status: '', bad: false, done: null });
    if (readMarks()[key]) view.done = { count: null, checking: false };
    if (focusKey && focusKey !== key) {
      focusKey = '';
      focusBucket = null;
    }
  }
  return { card, station, kind, key };
}

function reportMarkup(station, kind) {
  const label = kind === 'data_wrong' ? 'Kayıt yanlış görünüyor, bildir' : 'Asansör kapalıydı, bildir';
  const done = view.done
    ? '<span class="tag is-info report-done">' + icon('circle-check') + 'Zaten bildirildi'
      + (Number.isInteger(view.done.count) ? ' · ' + esc(view.done.count) + ' kişi' : '') + '</span>'
    : '<button type="button" class="btn report-open" id="report-open" aria-expanded="'
      + (view.open ? 'true' : 'false') + '" aria-controls="report-confirm">'
      + icon('alert-triangle') + esc(label) + '</button>';
  const choicesDisabled = view.busy ? ' disabled' : '';
  const statusClass = view.bad ? ' is-bad' : '';
  return '<div class="report" id="report-box">'
    + done
    + '<div class="report-confirm" id="report-confirm"' + (view.open ? '' : ' hidden') + '>'
    + '<p class="report-q" id="report-q">' + esc(station) + ' istasyonunda bunu ne zaman gördünüz?</p>'
    + '<div class="report-choices" role="group" aria-labelledby="report-q">'
    + '<button type="button" class="btn btn-primary" data-bucket="now"' + choicesDisabled + '>Şimdi</button>'
    + '<button type="button" class="btn" data-bucket="today"' + choicesDisabled + '>Bugün, daha önce</button>'
    + '<button type="button" class="btn report-cancel"' + choicesDisabled + '>Vazgeç</button>'
    + '</div>'
    + '<p class="report-note">Gönderilen yalnız istasyon, durum ve zaman. Konumunuz, adınız ve yazı gönderilmez. '
    + 'Resmî İBB başvurusu değildir; resmî kayıt için <a href="tel:153">153</a>.</p>'
    + '</div>'
    + '<p class="status-line report-status' + statusClass
    + '" id="report-status" role="status" aria-live="polite" tabindex="-1">'
    + esc(view.status) + '</p>'
    + '</div>';
}

function focusAfterRender(box, key, descriptor) {
  if (!descriptor || descriptor.key !== key) return;
  const target = descriptor.bucket
    ? box.querySelector('[data-bucket="' + descriptor.bucket + '"]')
    : box.querySelector('#report-open');
  if (target) target.focus({ preventScroll: true });
}

function render(selection, descriptor = null) {
  if (!selection) return null;
  const oldBox = selection.card.querySelector('#report-box');
  const hadFocus = oldBox && oldBox.contains(document.activeElement);
  const remembered = descriptor || (hadFocus ? { key: view.key, bucket: document.activeElement.dataset.bucket || null } : null);
  const box = document.createElement('div');
  box.innerHTML = reportMarkup(selection.station, selection.kind);
  if (oldBox) oldBox.replaceWith(box.firstElementChild);
  else selection.card.append(box.firstElementChild);
  const current = selection.card.querySelector('#report-box');
  focusAfterRender(current, selection.key, remembered);
  return current;
}

async function refreshCount(selection) {
  if (!view.done || view.done.checking) return;
  view.done.checking = true;
  const { station, kind, key } = selection;
  try {
    const result = await get('/api/report/status', { station, kind });
    if (view.key !== key || !view.done) return;
    view.done.count = result.support_count;
    render(selectCard());
  } catch (error) {
    if (view.key === key && view.done) render(selectCard());
  }
}

function attach() {
  if (!host || MOCK) return;
  const selection = selectCard();
  if (!selection || selection.card.querySelector('#report-box')) return;
  const box = render(selection, focusKey === selection.key ? { key: focusKey, bucket: focusBucket } : null);
  if (view.done) refreshCount(selection);
  return box;
}

async function sendReport(selection, bucket) {
  const { station, kind, key } = selection;
  Object.assign(view, { open: true, busy: true, bucket, status: '', bad: false });
  render(selection, { key, bucket });
  try {
    const result = await post('/api/report', { station, kind, bucket });
    saveMark(key);
    void trackReport(result.station, result.kind);
    if (view.key !== key) return;
    Object.assign(view, {
      open: false,
      busy: false,
      bucket: null,
      status: result.message + ' ' + result.note,
      bad: false,
      done: { count: result.support_count, checking: true },
    });
    const current = render(selectCard());
    if (current) current.querySelector('#report-status')?.focus({ preventScroll: true });
  } catch (error) {
    if (view.key !== key) return;
    Object.assign(view, { busy: false, status: error.message, bad: true });
    render(selectCard(), { key, bucket });
  }
}

if (host && !MOCK) {
  host.addEventListener('focusin', (event) => {
    const box = event.target.closest('#report-box');
    if (!box) return;
    focusKey = view.key;
    focusBucket = event.target.dataset.bucket || null;
  });
  host.addEventListener('focusout', (event) => {
    if (!event.target.closest('#report-box')) return;
    const next = event.relatedTarget;
    if (next && !next.closest?.('#report-box')) {
      focusKey = '';
      focusBucket = null;
    }
  });
  host.addEventListener('click', (event) => {
    const selection = selectCard();
    if (!selection) return;
    if (event.target.closest('#report-open')) {
      Object.assign(view, { open: true, status: '', bad: false });
      render(selection, { key: view.key, bucket: 'now' });
      return;
    }
    if (event.target.closest('.report-cancel')) {
      Object.assign(view, { open: false, busy: false, bucket: null });
      render(selection, { key: view.key, bucket: null });
      return;
    }
    const choice = event.target.closest('[data-bucket]');
    if (choice && !view.busy && !view.done) sendReport(selection, choice.dataset.bucket);
  });
  host.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape' || !event.target.closest('#report-box') || !view.open || view.busy) return;
    const selection = selectCard();
    if (!selection) return;
    event.preventDefault();
    Object.assign(view, { open: false, bucket: null });
    render(selection, { key: view.key, bucket: null });
  });
  new MutationObserver(attach).observe(host, { childList: true });
  attach();
}

/* E33 · Bildirimim ne oldu? */
const OUTCOME_KEY = 'nabiz.report-codes.v1';
const OUTCOME_KIND = { not_working: 'asansör kapalıydı', data_wrong: 'kayıt yanlış görünüyor' };
const OUTCOME_WAITING = {
  code: '', station: 'Bildirim', kind_text: 'durum bilgisi', status: 'waiting', label: 'Onay bekliyor',
  text: 'Onay bekliyor: simüle operatör henüz karar vermedi.',
};
const OUTCOME_STYLES = {
  waiting: { tag: 'is-info', glyph: 'clock' },
  approved: { tag: 'is-ok', glyph: 'circle-check' },
  not_published: { tag: '', glyph: 'info-circle' },
  expired: { tag: 'is-warn', glyph: 'clock' },
};
let outcomeContext = null;

function outcomeMarkup(outcome) {
  const style = OUTCOME_STYLES[outcome.status] || OUTCOME_STYLES.waiting;
  const tag = style.tag ? ` ${style.tag}` : '';
  return `<li class="report-outcome is-${esc(outcome.status)}" data-code="${esc(outcome.code)}">`
    + `<span class="report-outcome-what"><b>${esc(outcome.station)}</b> · ${esc(outcome.kind_text)}</span>`
    + `<span class="tag${tag}">${icon(style.glyph)}${esc(outcome.label)}</span>`
    + `<span class="report-outcome-text" lang="tr">${esc(outcome.text)}</span>`
    + '<button type="button" class="btn" data-outcome="remove">Bu cihazdan kaldır</button></li>';
}

function readOutcomeItems(storage) {
  try { return parseStored(storage?.getItem(OUTCOME_KEY)); } catch { return []; }
}

function writeOutcomeItems(context) {
  try {
    context.storage?.setItem(OUTCOME_KEY, JSON.stringify({ version: 1, items: context.items.slice(-10) }));
  } catch { /* private mode keeps this list in memory for this visit */ }
}

function renderOutcomeList(context) {
  const active = context.list.contains(context.doc.activeElement)
    ? [...context.list.querySelectorAll('li')].find((row) => row.contains(context.doc.activeElement))?.dataset.code
    : null;
  context.block.hidden = context.items.length === 0;
  context.list.innerHTML = context.items.map((item) => outcomeMarkup(context.views.get(item.code) || {
    ...OUTCOME_WAITING, code: item.code,
  })).join('');
  if (active) {
    const row = [...context.list.querySelectorAll('li')].find((item) => item.dataset.code === active);
    row?.querySelector('[data-outcome="remove"]')?.focus({ preventScroll: true });
  }
}

function forgetOutcome(context, code) {
  context.items = context.items.filter((item) => item.code !== code);
  context.views.delete(code);
  writeOutcomeItems(context);
  renderOutcomeList(context);
}

async function refreshOutcome(context, code) {
  try {
    const outcome = await get(`/api/report/outcome/${encodeURIComponent(code)}`);
    const previous = context.views.get(code);
    context.views.set(code, outcome);
    renderOutcomeList(context);
    if (previous && previous.status !== outcome.status) {
      context.status.textContent = `${outcome.station} bildiriminiz: ${outcome.text}`;
    }
  } catch (error) {
    if (error.status !== 404) return;
    const item = context.items.find((entry) => entry.code === code);
    if (item && Date.now() - item.at > 120_000) forgetOutcome(context, code);
  }
}

function startOutcomePolling(context) {
  clearInterval(context.timer);
  context.timer = null;
  const waiting = context.items.filter((item) => (context.views.get(item.code) || OUTCOME_WAITING).status === 'waiting');
  if (!waiting.length) return;
  context.timer = setInterval(() => {
    if (context.doc.hidden) return;
    const pending = context.items.filter((item) => (context.views.get(item.code) || OUTCOME_WAITING).status === 'waiting');
    if (!pending.length) {
      clearInterval(context.timer);
      context.timer = null;
      return;
    }
    pending.forEach((item) => { void refreshOutcome(context, item.code); });
  }, POLL_MS);
}

function mountOutcomes(doc, storage) {
  if (MOCK || !doc) return null;
  const target = doc.getElementById('alternative');
  if (!target) return null;
  let block = doc.getElementById('report-outcomes');
  if (!block) {
    const wrapper = doc.createElement('div');
    wrapper.innerHTML = '<div class="report-outcomes" id="report-outcomes" role="region" aria-labelledby="report-outcomes-title" hidden>'
      + '<h3 id="report-outcomes-title">Bildirimlerim (bu cihazda)</h3><ul class="report-outcome-list"></ul>'
      + '<p class="report-note">Hesap yok: bildirim kimliği yalnız bu cihazda durur (30 gün). '
      + 'Resmî İBB başvurusu değildir; resmî kayıt için <a href="tel:153">153</a>.</p>'
      + '<p class="sr-only" id="report-outcomes-status" role="status"></p></div>';
    block = wrapper.firstElementChild;
    target.after(block);
  }
  if (outcomeContext?.doc === doc && outcomeContext.block === block) return outcomeContext;
  const list = block.querySelector('.report-outcome-list');
  const status = block.querySelector('#report-outcomes-status');
  if (!list || !status) return null;
  const context = { doc, storage, target, block, list, status, items: readOutcomeItems(storage), views: new Map(), timer: null };
  context.items.forEach((item) => context.views.set(item.code, { ...OUTCOME_WAITING, code: item.code }));
  outcomeContext = context;
  renderOutcomeList(context);
  block.addEventListener('click', (event) => {
    const button = event.target.closest('[data-outcome="remove"]');
    if (!button) return;
    const row = button.closest('.report-outcome');
    const rows = [...list.querySelectorAll('li')];
    const nextCode = rows[rows.indexOf(row) + 1]?.dataset.code;
    forgetOutcome(context, row.dataset.code);
    const next = nextCode && [...list.querySelectorAll('li')].find((item) => item.dataset.code === nextCode);
    const remove = next?.querySelector('[data-outcome="remove"]');
    if (remove) remove.focus({ preventScroll: true });
    else {
      target.tabIndex = -1;
      target.focus({ preventScroll: true });
    }
  });
  void Promise.all(context.items.map((item) => refreshOutcome(context, item.code))).then(() => startOutcomePolling(context));
  return context;
}

async function trackReport(station, kind) {
  if (MOCK || !outcomeContext) return;
  try {
    const result = await get('/api/report/code', { station, kind });
    const now = Date.now();
    if (parseStored(JSON.stringify({ version: 1, items: [{ code: result.code, at: now }] })).length !== 1) return;
    let item = outcomeContext.items.find((entry) => entry.code === result.code);
    if (!item) {
      item = { code: result.code, at: now };
      outcomeContext.items.push(item);
      outcomeContext.items = outcomeContext.items.slice(-10);
    }
    outcomeContext.views.set(result.code, {
      ...OUTCOME_WAITING,
      code: result.code,
      station: result.station || station,
      kind_text: OUTCOME_KIND[result.kind] || OUTCOME_WAITING.kind_text,
    });
    writeOutcomeItems(outcomeContext);
    renderOutcomeList(outcomeContext);
    await refreshOutcome(outcomeContext, result.code);
    startOutcomePolling(outcomeContext);
  } catch { /* the citizen report already has its own confirmation */ }
}

if (pageDocument) {
  let storage = null;
  try { storage = globalThis.localStorage; } catch { /* private mode */ }
  mountOutcomes(pageDocument, storage);
  pageDocument.addEventListener?.('nabiz:report-sent', (event) => {
    if (event.detail?.station && event.detail?.kind) void trackReport(event.detail.station, event.detail.kind);
  });
}

export { OUTCOME_KEY, outcomeMarkup, trackReport, mountOutcomes };
