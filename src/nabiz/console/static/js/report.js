/* A short citizen report stays beside the lift card and survives its refreshes. */

import { MOCK, get, post } from './api.js';
import { LIFT_TR } from './cards.js';
import { esc } from './format.js';
import { icon } from './icons.js';

const host = document.querySelector('#alternative');
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
