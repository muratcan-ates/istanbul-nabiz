/* The simulated operator's photo-report queue. */

import { get, post } from './api.js';
import { isMock } from './config.js';
import { clock, esc } from './format.js';
import { currentLang, loadCatalogs, onLang } from './i18n_text.js';

const LIST_PATH = '/api/console/photo-reports';
const POLL_MS = 20_000;
const STYLESHEET = '/css/console_photo_reports.css';
const NEXT_STATUS = Object.freeze({ new: 'reviewed', reviewed: 'forwarded', forwarded: 'closed', closed: null });
const ALLOWED = Object.freeze({ new: ['reviewed', 'forwarded', 'closed'], reviewed: ['forwarded', 'closed'], forwarded: ['closed'], closed: [] });
const COPY = Object.freeze({
  tr: Object.freeze({
    title: 'Fotoğraflı bildirimler', description: 'Vatandaşın açık rızayla gönderdiği fotoğraflar. EXIF silinmiş gelir; kapatınca fotoğraf, 30 gün sonra kayıt silinir. Örnek akış: gerçek bir İBB birimine iletilmez.',
    pavement: 'Kaldırım ve yol', lift: 'Asansör ve yürüyen merdiven', litter: 'Çöp ve temizlik', lighting: 'Aydınlatma', other: 'Diğer',
    count: '({count} açık)', status: 'Fotoğraflı bildirimler yükleniyor.', loading: 'yükleniyor', none: 'Açık fotoğraflı bildirim yok.',
    failed: 'Fotoğraflı bildirimler alınamadı. Yeniden deneyin.', list: 'Fotoğraflı bildirimler', select: 'Listeden bir bildirim seçin.',
    new: 'Alındı', reviewed: 'İncelendi', forwarded: 'İletildi', closed: 'Kapatıldı',
    alt: 'Vatandaşın gönderdiği fotoğraf: {category}, {place}', closedPhoto: 'Fotoğraf, bildirim kapatılınca silindi.',
    photoCaption: '{type} · {width} × {height} px · {size} KB · EXIF silindi',
    history: 'Geçmiş', reason: 'Gerekçe (vatandaş kod kartında görür)', reasonRequired: 'Durum değiştirmek için gerekçe yazın.',
    next_reviewed: 'İncelendi olarak işaretle', next_forwarded: 'İlgili birime ilet (örnek)', next_closed: 'Kapat',
    other: 'Başka durum', closeHint: 'Kapatınca fotoğraf silinir.', save: 'Durum kaydediliyor.',
  }),
  en: Object.freeze({
    title: 'Photo reports', description: 'Photos sent by citizens with explicit consent. EXIF is removed; the photo is deleted on closure, and the record after 30 days. Example flow: reports are not sent to a real İBB unit.',
    pavement: 'Sidewalk and road', lift: 'Elevator and escalator', litter: 'Waste and cleanliness', lighting: 'Lighting', other: 'Other',
    count: '({count} open)', status: 'Loading photo reports.', loading: 'loading', none: 'There are no open photo reports.',
    failed: 'Photo reports could not be loaded. Try again.', list: 'Photo reports', select: 'Select a report from the list.',
    new: 'Received', reviewed: 'Reviewed', forwarded: 'Marked for referral', closed: 'Closed',
    alt: 'Photo submitted by a citizen: {category}, {place}', closedPhoto: 'The photo was deleted when the report was closed.',
    photoCaption: '{type} · {width} × {height} px · {size} KB · EXIF was removed',
    history: 'History', reason: 'Reason (visible on the citizen code card)', reasonRequired: 'Write a reason before changing the status.',
    next_reviewed: 'Mark as reviewed', next_forwarded: 'Mark for referral (example)', next_closed: 'Close',
    other: 'Other status', closeHint: 'Closing deletes the photo.', save: 'Saving status.',
  }),
});

function copy(language, key, vars = {}) {
  return (COPY[language === 'en' ? 'en' : 'tr'][key] || '').replace(/\{(\w+)\}/g, (_, name) => String(vars[name] ?? ''));
}

function statusLabel(status, language) {
  return copy(language, status in COPY.tr ? status : 'new');
}

function categoryLabel(item, language) {
  return item.category_tr || copy(language, item.category) || item.category || '';
}

function listItem(item, current, language = 'tr') {
  const selected = item.code === current ? ' aria-current="true"' : '';
  return `<li><button type="button" class="op-item photo-report-item" data-code="${esc(item.code)}"${selected}>`
    + `<b>#${esc(item.code)} · ${esc(statusLabel(item.status, language))}</b>`
    + `<span class="op-meta">${esc(categoryLabel(item, language))} · ${esc(item.place?.name || '')} · ${esc(clock(item.created_at))}</span></button></li>`;
}

function listMarkup(items, current, language = 'tr') {
  if (!items.length) return `<li class="section-note">${esc(copy(language, 'none'))}</li>`;
  return items.map((item) => listItem(item, current, language)).join('');
}

function closeAction(status, language, primary = false) {
  const label = copy(language, `next_${status}`);
  const cls = primary ? 'btn btn-primary' : 'btn';
  return `<div class="photo-report-transition"><button type="button" class="${cls}" data-action="transition" data-status="${esc(status)}">${esc(label)}</button>`
    + (status === 'closed' ? `<p class="field-hint">${esc(copy(language, 'closeHint'))}</p>` : '') + '</div>';
}

function detailMarkup(item, language = 'tr') {
  if (!item) return `<p class="section-note">${esc(copy(language, 'select'))}</p>`;
  const category = categoryLabel(item, language);
  const place = item.place?.name || '';
  const photo = item.has_photo && item.status !== 'closed'
    ? `<figure class="photo-report-figure"><img src="/api/console/photo-reports/${encodeURIComponent(item.code)}/photo" alt="${esc(copy(language, 'alt', { category, place }))}" loading="lazy">`
      + `<figcaption>${esc(copy(language, 'photoCaption', {
        type: (item.photo_meta?.type || 'jpeg').toUpperCase(), width: item.photo_meta?.width,
        height: item.photo_meta?.height, size: Math.max(1, Math.round((item.photo_meta?.bytes || 0) / 1024)),
      }))}</figcaption></figure>`
    : `<p class="section-note">${esc(copy(language, 'closedPhoto'))}</p>`;
  const history = (item.history || []).map((entry) => `<li><b>${esc(statusLabel(entry.status, language))}</b> · ${esc(clock(entry.at))}`
    + (entry.reason ? `<blockquote lang="tr">${esc(entry.reason)}</blockquote>` : '') + '</li>').join('');
  const description = `<div><h3>${esc(category)}</h3><p class="op-meta">${esc(place)} · ${esc(clock(item.created_at))}</p>`
    + `<blockquote lang="${esc(item.lang || 'tr')}">${esc(item.description || '')}</blockquote>`
    + (item.masked_count ? `<p class="field-hint">${esc(item.masked_count)} kişisel bilgi maskelendi</p>` : '') + '</div>';
  let decision = '';
  if (item.status !== 'closed') {
    const next = NEXT_STATUS[item.status];
    const others = ALLOWED[item.status].filter((status) => status !== next);
    const alternative = others.length
      ? `<details class="more"><summary>${esc(copy(language, 'other'))}</summary>${others.map((status) => closeAction(status, language)).join('')}</details>` : '';
    decision = `<div class="photo-report-decision"><label for="photo-report-reason">${esc(copy(language, 'reason'))}</label>`
      + '<textarea id="photo-report-reason" maxlength="280" rows="3" aria-describedby="photo-report-reason-error"></textarea>'
      + '<p class="field-error" id="photo-report-reason-error" hidden></p>'
      + `${closeAction(next, language, true)}${alternative}</div>`;
  }
  return `<article class="photo-report-detail"><div class="photo-report-detail-grid"><div>${photo}${description}</div>`
    + `<div><h3>${esc(copy(language, 'history'))}</h3><ol class="photo-report-history">${history}</ol>${decision}</div></div></article>`;
}

function sectionMarkup(language = 'tr') {
  return `<div class="section-head"><h2 id="photo-reports-title">${esc(copy(language, 'title'))}</h2><span class="section-note" id="photo-reports-count"></span></div>`
    + `<p class="section-note photo-report-description">${esc(copy(language, 'description'))}</p>`
    + `<p class="status-line" id="photo-reports-status" role="status" aria-live="polite">${esc(copy(language, 'status'))}</p>`
    + `<div class="photo-reports-grid"><ol class="op-list photo-report-list" id="photo-reports-list" aria-label="${esc(copy(language, 'list'))}"><li class="section-note">${esc(copy(language, 'loading'))}</li></ol>`
    + '<div id="photo-reports-detail" tabindex="-1"></div></div>';
}

function addStylesheet(doc) {
  if (doc.head.querySelector(`link[href="${STYLESHEET}"]`)) return;
  const link = doc.createElement('link');
  link.rel = 'stylesheet';
  link.href = STYLESHEET;
  doc.head.append(link);
}

async function mountPhotoReportsConsole(doc) {
  const win = doc && doc.defaultView;
  if (!doc || isMock((win && win.location.search) || '')) return null;
  const anchor = doc.getElementById('citizen-requests');
  const main = doc.getElementById('main');
  if (!anchor && !main) return null;
  if (win && new URLSearchParams(win.location.search).get('lang') === 'en') await loadCatalogs('en');
  const section = doc.createElement('section');
  section.id = 'photo-reports';
  section.setAttribute('aria-labelledby', 'photo-reports-title');
  section.innerHTML = sectionMarkup(currentLang());
  if (anchor) anchor.insertAdjacentElement('afterend', section);
  else main.append(section);
  addStylesheet(doc);
  const $ = (selector) => section.querySelector(selector);
  let items = [];
  let current = null;
  let timer = null;

  function showStatus(message, server = false) {
    $('#photo-reports-status').textContent = message;
    $('#photo-reports-status').lang = server ? 'tr' : currentLang();
  }

  function renderDetail(preserve = false) {
    const old = preserve ? $('#photo-reports-detail') : null;
    const reason = old?.querySelector('#photo-report-reason')?.value || '';
    const focused = old && old.contains(doc.activeElement) ? doc.activeElement.id : '';
    const item = items.find((entry) => entry.code === current);
    $('#photo-reports-detail').innerHTML = detailMarkup(item, currentLang());
    if (reason && $('#photo-report-reason')) $('#photo-report-reason').value = reason;
    if (focused) $(`#${focused}`)?.focus();
  }

  function renderList() {
    $('#photo-reports-list').innerHTML = listMarkup(items, current, currentLang());
    const open = Object.entries(lastCounts).filter(([key]) => key !== 'closed').reduce((sum, [, value]) => sum + value, 0);
    $('#photo-reports-count').textContent = copy(currentLang(), 'count', { count: open });
  }

  let lastCounts = { new: 0, reviewed: 0, forwarded: 0, closed: 0 };
  async function load({ announce = false, preserve = false } = {}) {
    try {
      const result = await get(LIST_PATH, { status: 'open' });
      items = result.items || [];
      lastCounts = result.counts || lastCounts;
      if (!items.some((item) => item.code === current)) current = items[0]?.code || null;
      renderList();
      renderDetail(preserve);
      const sentence = items.length ? copy(currentLang(), 'count', { count: items.length }) : copy(currentLang(), 'none');
      if (announce || $('#photo-reports-status').textContent !== sentence) showStatus(sentence);
    } catch (error) {
      showStatus(error.message || copy(currentLang(), 'failed'), Boolean(error.status));
    }
  }

  async function transition(status) {
    const reason = $('#photo-report-reason');
    const error = $('#photo-report-reason-error');
    if (!reason || !reason.value.trim()) {
      error.textContent = copy(currentLang(), 'reasonRequired');
      error.hidden = false;
      reason?.setAttribute('aria-invalid', 'true');
      reason?.focus();
      return;
    }
    showStatus(copy(currentLang(), 'save'));
    try {
      const result = await post(`${LIST_PATH}/${encodeURIComponent(current)}/status`, { status, reason: reason.value.trim() });
      await load();
      showStatus(result.message, true);
      const EventType = (win && win.CustomEvent) || globalThis.CustomEvent;
      if (typeof EventType === 'function') doc.dispatchEvent(new EventType('nabiz:ledger-changed'));
    } catch (failure) { showStatus(failure.message || copy(currentLang(), 'failed'), true); }
  }

  section.addEventListener('click', (event) => {
    const item = event.target.closest('.photo-report-item');
    if (item) {
      current = item.dataset.code;
      renderList();
      renderDetail();
      $('#photo-reports-detail').focus();
      return;
    }
    const button = event.target.closest('[data-action="transition"]');
    if (button) void transition(button.dataset.status);
  });
  section.addEventListener('input', (event) => {
    if (event.target.id === 'photo-report-reason' && event.target.value.trim()) {
      event.target.removeAttribute('aria-invalid');
      $('#photo-report-reason-error').hidden = true;
    }
  });
  onLang(() => {
    const reason = $('#photo-report-reason')?.value || '';
    section.innerHTML = sectionMarkup(currentLang());
    renderList();
    renderDetail();
    if ($('#photo-report-reason')) $('#photo-report-reason').value = reason;
  });
  await load();
  timer = win.setInterval(() => { if (!doc.hidden) void load({ preserve: true }); }, POLL_MS);
  return section;
}

export { COPY, NEXT_STATUS, detailMarkup, listItem, mountPhotoReportsConsole, sectionMarkup };

if (typeof document !== 'undefined') void mountPhotoReportsConsole(document);
