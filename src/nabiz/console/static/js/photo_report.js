/* Consented photo reports for the citizen page. This file owns its closed panel and local code cards. */

import { del, get, post } from './api.js';
import { isMock } from './config.js';
import { esc } from './format.js';
import { currentLang, onLang } from './i18n_text.js';
import { EMERGENCY_EVENT } from './emergency.js';

const STORAGE_KEY = 'nabiz.photo-reports.v1';
const KEEP_DAYS = 30;
const KEEP_MAX = 20;
const POLL_MS = 20_000;
const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;
const MAX_CLEAN_BYTES = 2 * 1024 * 1024;
const STYLESHEET = '/css/photo_report.css';
const CODE_RE = /^[2-9A-HJKMNP-Z]{8}$/;
const CANVAS_NEUTRAL = '#f2f3f4';

const COPY = Object.freeze({
  tr: Object.freeze({
    title: 'Fotoğrafla sorun bildirin', warning: 'Fotoğrafta kişi yüzü ya da araç plakası olmamasına dikkat edin. Ad, telefon, TC kimlik gibi bilgileri yazmayın.',
    photo: 'Fotoğraf seçin', photoAlt: 'Gönderilecek fotoğrafın önizlemesi', ready: 'Fotoğraf hazır: {width} × {height} px, {size} KB. Konum ve cihaz bilgileri (EXIF) silindi.',
    type: 'Ne tür bir sorun?', pavement: 'Kaldırım ve yol', lift: 'Asansör ve yürüyen merdiven', litter: 'Çöp ve temizlik', lighting: 'Aydınlatma', other: 'Diğer',
    description: 'Kısa açıklama (isteğe bağlı)', remaining: 'Kalan {count} karakter',
    where: 'Sorun nerede?', stationKind: 'İstasyon', districtKind: 'İlçe', station: 'İstasyon adı', district: 'İlçe',
    consent: 'Fotoğrafı, açıklamayı ve seçtiğim yeri simüle İBB operatörüne göndermeye ve 30 gün saklanmasına açık rıza veriyorum.',
    details: 'Ayrıntılar', submit: 'Bildir', cancel: 'Vazgeç', loading: 'Bildirim formu yükleniyor.',
    loadError: 'Bildirim formu açılamadı. Yeniden deneyin.', retry: 'Yeniden dene', sending: 'Gönderiliyor.',
    choosePhoto: 'Önce bir fotoğraf seçin.', choosePlace: 'İstasyondan ya da ilçeden birini seçin.', needConsent: 'Göndermek için açık rıza kutusunu işaretleyin.',
    tooLarge: 'Fotoğraf 25 MB sınırını aşıyor. Daha küçük bir fotoğraf seçin.', badType: 'Yalnız JPEG, PNG ya da WebP fotoğraf seçin.',
    resizeError: 'Fotoğraf küçültülemedi; başka bir fotoğraf seçin.',
    mine: 'Bildirimlerim (bu cihazda)', received: 'Bildiriminiz alındı. Kodunuz: {code}',
    statusNew: 'Alındı', statusReviewed: 'İncelendi', statusForwarded: 'İletildi', statusClosed: 'Kapatıldı', sample: 'Örnek akış',
    pavement: 'Kaldırım ve yol', lift: 'Asansör ve yürüyen merdiven', litter: 'Çöp ve temizlik', lighting: 'Aydınlatma', other: 'Diğer',
    sentenceNew: 'Alındı: simüle operatör henüz bakmadı.', sentenceReviewed: 'İncelendi: simüle operatör fotoğrafı inceledi.',
    sentenceForwarded: 'İletildi: simüle operatör bildirimi ilgili birim için işaretledi. Örnek akış: gerçek bir İBB birimine gönderilmez.',
    sentenceClosed: 'Kapatıldı: fotoğraf silindi.', simulated: 'Prototip: operatör rolü simüledir; resmî İBB hizmeti değildir.', official: 'Resmî kayıt için 153.',
    operatorNote: 'Simüle operatör notu:', more: 'Daha fazla', removeDevice: 'Bu cihazdan kaldır', delete: 'Bildirimi sil',
    deleteFirst: 'Bildirim sunucudan silinecek; geri alınamaz. Onaylamak için yeniden basın.', deleted: 'Bildirim silindi.', removed: 'Kod bu cihazdan kaldırıldı.',
    missing: 'Bildirim bulunamadı ya da 30 günlük süre doldu.',
  }),
  en: Object.freeze({
    title: 'Report a problem with a photo', warning: 'Make sure no faces or vehicle plates appear in the photo. Do not include names, phone numbers, or national ID numbers.',
    photo: 'Choose a photo', photoAlt: 'Preview of the photo to send', ready: 'Photo ready: {width} × {height} px, {size} KB. Location and device details (EXIF) were removed.',
    type: 'What is the problem?', pavement: 'Sidewalk and road', lift: 'Elevator and escalator', litter: 'Waste and cleanliness', lighting: 'Lighting', other: 'Other',
    description: 'Short description (optional)', remaining: '{count} characters remaining',
    where: 'Where is the problem?', stationKind: 'Station', districtKind: 'District', station: 'Station name', district: 'District',
    consent: 'I consent to sending the photo, description, and place I chose to the simulated İBB operator and keeping them for 30 days.',
    details: 'Details', submit: 'Report', cancel: 'Cancel', loading: 'Loading the report form.',
    loadError: 'The report form could not be loaded. Try again.', retry: 'Try again', sending: 'Sending.',
    choosePhoto: 'Choose a photo first.', choosePlace: 'Choose a station or a district.', needConsent: 'Check the consent box before sending.',
    tooLarge: 'The photo is over 25 MB. Choose a smaller photo.', badType: 'Choose a JPEG, PNG, or WebP photo.',
    resizeError: 'The photo could not be reduced. Choose another photo.',
    mine: 'My reports (on this device)', received: 'Your report was received. Your code: {code}',
    statusNew: 'Received', statusReviewed: 'Reviewed', statusForwarded: 'Marked for referral', statusClosed: 'Closed', sample: 'Example flow',
    pavement: 'Sidewalk and road', lift: 'Elevator and escalator', litter: 'Waste and cleanliness', lighting: 'Lighting', other: 'Other',
    sentenceNew: 'Received: the simulated operator has not reviewed it yet.', sentenceReviewed: 'Reviewed: the simulated operator reviewed the photo.',
    sentenceForwarded: 'Marked for referral: the simulated operator flagged the report for a relevant unit. Example flow: it is not sent to a real İBB unit.',
    sentenceClosed: 'Closed: the photo was deleted.', simulated: 'Prototype: the operator role is simulated; this is not an official İBB service.', official: 'For an official record, call 153.',
    operatorNote: 'Simulated operator note:', more: 'More', removeDevice: 'Remove from this device', delete: 'Delete report',
    deleteFirst: 'The report will be deleted from the server and cannot be restored. Press again to confirm.', deleted: 'The report was deleted.', removed: 'The code was removed from this device.',
    missing: 'The report was not found or its 30-day period ended.',
  }),
});

function copy(language, key, vars = {}) {
  const text = COPY[language === 'en' ? 'en' : 'tr'][key] || '';
  return text.replace(/\{(\w+)\}/g, (_, name) => String(vars[name] ?? ''));
}

function sniffPhoto(bytes) {
  const data = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes || []);
  if (data.length >= 3 && data[0] === 255 && data[1] === 216 && data[2] === 255) return 'jpeg';
  if ([137, 80, 78, 71, 13, 10, 26, 10].every((value, index) => data[index] === value)) return 'png';
  if (data.length >= 12 && String.fromCharCode(...data.slice(0, 4)) === 'RIFF'
    && String.fromCharCode(...data.slice(8, 12)) === 'WEBP') return 'webp';
  return null;
}

function fitWithin(width, height, edge = 1600) {
  if (!(width > 0 && height > 0 && edge > 0)) return [0, 0];
  const scale = Math.min(1, edge / Math.max(width, height));
  return [Math.max(1, Math.round(width * scale)), Math.max(1, Math.round(height * scale))];
}

function parseStored(raw, now = Date.now()) {
  let value;
  try { value = JSON.parse(raw || 'null'); } catch { return []; }
  if (!value || value.version !== 1 || !Array.isArray(value.items)) return [];
  const oldest = now - KEEP_DAYS * 86_400_000;
  return value.items.filter((item) => item && CODE_RE.test(item.code) && Number.isFinite(item.at)
    && item.at > oldest && item.at <= now).slice(-KEEP_MAX);
}

function readCodes(storage) {
  try { return parseStored(storage.getItem(STORAGE_KEY)); } catch { return []; }
}

function writeCodes(storage, items) {
  try { storage.setItem(STORAGE_KEY, JSON.stringify({ version: 1, items: items.slice(-KEEP_MAX) })); } catch { /* private mode */ }
}

function statusLabel(status, language) {
  return copy(language, ({ new: 'statusNew', reviewed: 'statusReviewed', forwarded: 'statusForwarded', closed: 'statusClosed' })[status] || 'statusNew');
}

function statusSentence(status, language = 'tr') {
  return copy(language, ({ new: 'sentenceNew', reviewed: 'sentenceReviewed', forwarded: 'sentenceForwarded', closed: 'sentenceClosed' })[status] || 'sentenceNew');
}

function formMarkup(options = {}, language = 'tr', state = {}) {
  const t = (key, vars) => copy(language, key, vars);
  const categories = options.categories || [
    { key: 'pavement' }, { key: 'lift' }, { key: 'litter' }, { key: 'lighting' }, { key: 'other' },
  ];
  const districts = options.districts || [];
  const stations = options.stations || [];
  const categoryRows = categories.map((item) => {
    const id = `photo-category-${esc(item.key)}`;
    const selected = (state.category || 'pavement') === item.key ? ' checked' : '';
    return `<div><input id="${id}" type="radio" name="photo-category" value="${esc(item.key)}"${selected}>`
      + `<label for="${id}">${esc(t(item.key) || item[language] || item.tr || item.en || item.key)}</label></div>`;
  }).join('');
  const districtOptions = districts.map((item) => {
    const name = typeof item === 'string' ? item : item.name;
    return `<option value="${esc(name)}"${state.district === name ? ' selected' : ''}>${esc(name)}</option>`;
  }).join('');
  const stationOptions = stations.map((name) => `<option value="${esc(name)}">`).join('');
  const stationChecked = (state.placeKind || 'station') === 'station';
  const districtChecked = !stationChecked;
  const prepared = state.prepared;
  const preview = prepared
    ? `<figure class="photo-report-preview"><img src="${esc(prepared.dataUrl)}" alt="${esc(t('photoAlt'))}">`
      + `<figcaption>${esc(t('ready', { width: prepared.width, height: prepared.height, size: Math.max(1, Math.round(prepared.bytes / 1024)) }))}</figcaption></figure>` : '';
  const errors = state.errors || {};
  const error = (key) => errors[key] ? `<p class="field-error" id="photo-error-${key}" data-error="${key}" role="alert">${esc(errors[key])}</p>` : `<p class="field-error" id="photo-error-${key}" data-error="${key}" hidden></p>`;
  return `<form class="photo-report-form" novalidate><p class="callout callout-warn" role="note">${esc(t('warning'))}</p>`
    + `<div class="field"><label for="photo-file">${esc(t('photo'))}</label><input id="photo-file" type="file" accept="image/jpeg,image/png,image/webp" aria-describedby="photo-error-photo">${error('photo')}${preview}</div>`
    + `<fieldset class="photo-report-fieldset"><legend>${esc(t('type'))}</legend>${categoryRows}</fieldset>`
    + `<div class="field"><label for="photo-description">${esc(t('description'))}</label><textarea id="photo-description" maxlength="280" rows="3" aria-describedby="photo-description-count photo-error-description">${esc(state.description || '')}</textarea>`
    + `<p class="field-hint" id="photo-description-count" aria-live="polite">${esc(t('remaining', { count: 280 - String(state.description || '').length }))}</p>${error('description')}</div>`
    + `<fieldset class="photo-report-fieldset"><legend>${esc(t('where'))}</legend>`
    + `<div><input id="photo-place-station" type="radio" name="photo-place-kind" value="station"${stationChecked ? ' checked' : ''}><label for="photo-place-station">${esc(t('stationKind'))}</label></div>`
    + `<div><input id="photo-place-district" type="radio" name="photo-place-kind" value="district"${districtChecked ? ' checked' : ''}><label for="photo-place-district">${esc(t('districtKind'))}</label></div>`
    + `<div class="field"${stationChecked ? '' : ' hidden'}><label for="photo-station">${esc(t('station'))}</label><input id="photo-station" list="photo-stations" maxlength="80" value="${esc(state.station || '')}" aria-describedby="photo-error-place"><datalist id="photo-stations">${stationOptions}</datalist></div>`
    + `<div class="field"${districtChecked ? '' : ' hidden'}><label for="photo-district">${esc(t('district'))}</label><select id="photo-district" aria-describedby="photo-error-place"><option value="">${esc(t('district'))}</option>${districtOptions}</select></div>${error('place')}</fieldset>`
    + `<div class="photo-report-consent"><input id="photo-consent" type="checkbox" aria-describedby="photo-error-consent"${state.consent ? ' checked' : ''}>`
    + `<label for="photo-consent">${esc(t('consent'))} <a href="/kvkk.html#kvkk-foto">${esc(t('details'))}</a></label>${error('consent')}</div>`
    + `<div class="photo-report-actions"><button type="submit" class="btn btn-primary" data-action="submit">${esc(t('submit'))}</button>`
    + `<button type="button" class="btn btn-quiet" data-action="cancel">${esc(t('cancel'))}</button></div>`
    + `<p class="status-line" role="status" aria-live="polite" data-form-status></p></form>`;
}

function cardMarkup(view, language = 'tr') {
  const code = esc(view.code || '');
  const status = view.status || 'new';
  const place = view.place && view.place.name ? view.place.name : '';
  const category = view.category_tr || copy(language, view.category) || view.category || '';
  const history = Array.isArray(view.history) ? view.history : [];
  const reason = history.slice().reverse().find((entry) => entry && entry.reason)?.reason;
  const simulatedTag = status === 'forwarded' ? `<span class="tag">${esc(copy(language, 'sample'))}</span>` : '';
  const note = reason ? `<p class="photo-report-operator-note" lang="tr"><b>${esc(copy(language, 'operatorNote'))}</b> ${esc(reason)}</p>` : '';
  const safeCategory = esc(category);
  return `<article class="photo-report-card" data-code="${code}"><h3 id="photo-report-title-${code}" tabindex="-1">${esc(copy(language, 'received', { code: view.code }))}</h3>`
    + `<p><span class="tag">${esc(statusLabel(status, language))}</span> ${simulatedTag}</p>`
    + `<p>${safeCategory} · ${esc(place)}</p><p>${esc(statusSentence(status, language))}</p>${note}`
    + `<p class="field-hint">${esc(copy(language, 'simulated'))}</p><p class="field-hint">${esc(copy(language, 'official'))}</p>`
    + `<details class="more"><summary>${esc(copy(language, 'more'))}</summary><div class="photo-report-actions">`
    + `<button type="button" class="btn btn-quiet" data-action="remove-device" data-code="${code}">${esc(copy(language, 'removeDevice'))}</button>`
    + `<button type="button" class="btn btn-danger" data-action="delete-report" data-code="${code}">${esc(copy(language, 'delete'))}</button></div></details></article>`;
}

function addStylesheet(doc) {
  if (doc.head.querySelector(`link[href="${STYLESHEET}"]`)) return;
  const link = doc.createElement('link');
  link.rel = 'stylesheet';
  link.href = STYLESHEET;
  doc.head.append(link);
}

function readImage(file, win) {
  if (typeof win.createImageBitmap === 'function') {
    return win.createImageBitmap(file, { imageOrientation: 'from-image' }).then((bitmap) => ({ image: bitmap, width: bitmap.width, height: bitmap.height, close: () => bitmap.close?.() }));
  }
  return new Promise((resolve, reject) => {
    const reader = new win.FileReader();
    reader.onerror = () => reject(new Error('image_read'));
    reader.onload = () => {
      const image = new win.Image();
      image.onload = () => resolve({ image, width: image.naturalWidth, height: image.naturalHeight, close: () => {} });
      image.onerror = () => reject(new Error('image_read'));
      image.src = String(reader.result || '');
    };
    reader.readAsDataURL(file);
  });
}

function toBlob(canvas, win, quality) {
  return new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', quality));
}

async function preparePhoto(file, win, language) {
  if (file.size > MAX_UPLOAD_BYTES) throw new Error(copy(language, 'tooLarge'));
  if (!sniffPhoto(new Uint8Array(await file.slice(0, 12).arrayBuffer()))) throw new Error(copy(language, 'badType'));
  const decoded = await readImage(file, win);
  try {
    let [width, height] = fitWithin(decoded.width, decoded.height, 1600);
    const canvas = win.document.createElement('canvas');
    let cleaned = null;
    for (let pass = 0; pass < 2; pass += 1) {
      if (pass === 1) [width, height] = fitWithin(width, height, 1280);
      canvas.width = width;
      canvas.height = height;
      const context = canvas.getContext('2d', { alpha: false });
      if (!context) throw new Error('canvas_unavailable');
      context.fillStyle = CANVAS_NEUTRAL;
      context.fillRect(0, 0, width, height);
      context.drawImage(decoded.image, 0, 0, width, height);
      for (const quality of [0.85, 0.75, 0.65]) {
        cleaned = await toBlob(canvas, win, quality);
        if (cleaned && cleaned.size <= MAX_CLEAN_BYTES) break;
      }
      if (cleaned && cleaned.size <= MAX_CLEAN_BYTES) break;
    }
    if (!cleaned || cleaned.size > MAX_CLEAN_BYTES) throw new Error(copy(language, 'resizeError'));
    const dataUrl = await new Promise((resolve, reject) => {
      const reader = new win.FileReader();
      reader.onerror = () => reject(new Error(copy(language, 'resizeError')));
      reader.onload = () => resolve(String(reader.result || ''));
      reader.readAsDataURL(cleaned);
    });
    return { dataUrl, base64: String(dataUrl).split(',')[1] || '', bytes: cleaned.size, width, height };
  } finally { decoded.close(); }
}

function mountPhotoReport(doc, storage) {
  if (!doc || isMock((doc.defaultView && doc.defaultView.location.search) || '')) return null;
  if (doc.getElementById('foto-bildirim')) return null;
  const cityTools = doc.getElementById('city-tools');
  const account = doc.getElementById('hesabim');
  const main = doc.getElementById('main');
  const panel = doc.createElement('details');
  panel.className = 'more tool-detail photo-report-panel';
  panel.id = 'foto-bildirim';
  panel.innerHTML = `<summary><h2 id="foto-bildirim-title">${esc(copy(currentLang(), 'title'))}</h2></summary>`
    + '<section aria-labelledby="foto-bildirim-title"><div class="photo-report-content" id="photo-report-content">'
    + '<div id="photo-report-form-region"></div><div id="photo-report-cards"></div></div></section>';
  if (account) account.append(panel);
  else if (cityTools) cityTools.append(panel);
  else if (main) main.append(panel);
  else return null;
  addStylesheet(doc);
  const win = doc.defaultView || globalThis.window;
  if (!storage) {
    try { storage = win.localStorage; } catch { storage = { getItem: () => null, setItem: () => {} }; }
  }
  const region = doc.getElementById('photo-report-form-region');
  const cardsNode = doc.getElementById('photo-report-cards');
  const codes = new Map(readCodes(storage).map((item) => [item.code, item]));
  const views = new Map();
  let options = null;
  let stations = [];
  let optionsPromise = null;
  let timer = null;
  let deletePending = null;
  let emergencyCard = '';

  function announce(text) {
    const status = region.querySelector('[data-form-status]') || cardsNode.querySelector('.photo-report-global-status');
    if (status) status.textContent = text;
    else {
      const node = doc.createElement('p');
      node.className = 'status-line photo-report-global-status';
      node.setAttribute('role', 'status');
      node.setAttribute('aria-live', 'polite');
      node.textContent = text;
      cardsNode.prepend(node);
    }
  }

  function formState(form) {
    const active = form && form.contains(doc.activeElement) ? doc.activeElement.id : '';
    return {
      category: form?.querySelector('[name="photo-category"]:checked')?.value || 'pavement',
      description: form?.querySelector('#photo-description')?.value || '',
      placeKind: form?.querySelector('[name="photo-place-kind"]:checked')?.value || 'station',
      station: form?.querySelector('#photo-station')?.value || '',
      district: form?.querySelector('#photo-district')?.value || '',
      consent: Boolean(form?.querySelector('#photo-consent')?.checked),
      focused: active,
    };
  }

  let state = { category: 'pavement', placeKind: 'station', errors: {}, prepared: null };
  function renderForm(focus = '') {
    if (!options || emergencyCard) return;
    region.innerHTML = formMarkup({ ...options, stations }, currentLang(), state);
    const form = region.querySelector('form');
    if (focus) form.querySelector(`#${focus}`)?.focus();
    else if (state.focused) form.querySelector(`#${state.focused}`)?.focus();
    state.focused = '';
  }

  function renderCards() {
    const selected = currentLang();
    const content = [...views.values()].map((view) => cardMarkup(view, selected)).join('');
    const title = `<h3>${esc(copy(selected, 'mine'))}</h3>`;
    cardsNode.innerHTML = `${title}${emergencyCard}${content}`;
  }

  async function refresh(code, { startup = false } = {}) {
    try {
      const view = await get(`/api/photo-reports/${encodeURIComponent(code)}`);
      const previous = views.get(code);
      views.set(code, view);
      renderCards();
      if (previous && previous.status !== view.status) {
        announce(`${view.code}: ${statusLabel(view.status, currentLang())}.`);
        startPolling();
      }
      return view;
    } catch (error) {
      if (error.status === 404) {
        views.delete(code);
        codes.delete(code);
        writeCodes(storage, [...codes.values()]);
        renderCards();
        if (!startup) announce(copy(currentLang(), 'missing'));
      }
      return null;
    }
  }

  function startPolling() {
    win.clearInterval(timer);
    const open = [...views.values()].some((view) => view.status !== 'closed');
    if (!open) { timer = null; return; }
    timer = win.setInterval(() => {
      if (doc.hidden) return;
      [...views.values()].filter((view) => view.status !== 'closed').forEach((view) => { void refresh(view.code); });
    }, POLL_MS);
  }

  async function loadOptions() {
    if (options) return;
    if (optionsPromise) return optionsPromise;
    optionsPromise = Promise.all([get('/api/photo-reports/options'), get('/api/map/stations')]).then(([available, collection]) => {
      options = available;
      stations = [...new Set((collection.features || []).map((feature) => feature.properties?.name).filter(Boolean))]
        .sort((a, b) => a.localeCompare(b, 'tr'));
      renderForm();
    }).catch(() => {
      optionsPromise = null;
      region.innerHTML = `<p class="status-line" role="status" aria-live="polite">${esc(copy(currentLang(), 'loadError'))}</p>`
        + `<button type="button" class="btn" data-action="retry">${esc(copy(currentLang(), 'retry'))}</button>`;
    });
    return optionsPromise;
  }

  function setError(form, name, message, targetId) {
    state.errors = { ...state.errors, [name]: message };
    const node = form.querySelector(`[data-error="${name}"]`);
    node.textContent = message;
    node.hidden = false;
    const target = form.querySelector(`#${targetId}`);
    target?.setAttribute('aria-invalid', 'true');
    target?.focus();
  }

  async function submit(form) {
    const language = currentLang();
    const busy = form.querySelector('[data-action="submit"]');
    if (busy.getAttribute('aria-disabled') === 'true') return;
    form.querySelectorAll('[aria-invalid="true"]').forEach((node) => node.removeAttribute('aria-invalid'));
    form.querySelectorAll('.field-error').forEach((node) => { node.hidden = true; node.textContent = ''; });
    const activeState = formState(form);
    state = { ...state, ...activeState, errors: {} };
    if (!state.prepared) return setError(form, 'photo', copy(language, 'choosePhoto'), 'photo-file');
    const placeName = state.placeKind === 'station' ? state.station.trim() : state.district;
    if (!placeName) return setError(form, 'place', copy(language, 'choosePlace'), state.placeKind === 'station' ? 'photo-station' : 'photo-district');
    if (!state.consent) return setError(form, 'consent', copy(language, 'needConsent'), 'photo-consent');
    const button = form.querySelector('[data-action="submit"]');
    button.setAttribute('aria-busy', 'true');
    button.setAttribute('aria-disabled', 'true');
    announce(copy(language, 'sending'));
    try {
      const view = await post('/api/photo-reports', {
        photo: state.prepared.base64,
        category: state.category,
        description: state.description,
        place: { kind: state.placeKind, name: placeName },
        lang: language,
        consent: true,
      });
      if (view.emergency) {
        emergencyCard = `<p class="callout callout-warn" role="alert">${esc(view.message || '')}</p>`;
        state.prepared = null;
        dispatchEmergency(view.hazard);
        renderCards();
        region.innerHTML = '';
        return;
      }
      codes.set(view.code, { code: view.code, at: Date.now() });
      writeCodes(storage, [...codes.values()]);
      views.set(view.code, view);
      region.innerHTML = '';
      renderCards();
      doc.getElementById(`photo-report-title-${view.code}`)?.focus();
      startPolling();
    } catch (error) {
      announce(error.message || copy(language, 'loadError'));
      form.querySelector('[data-action="submit"]')?.removeAttribute('aria-busy');
      form.querySelector('[data-action="submit"]')?.removeAttribute('aria-disabled');
    }
  }

  function dispatchEmergency(hazard) {
    if (typeof win.CustomEvent === 'function') doc.dispatchEvent(new win.CustomEvent(EMERGENCY_EVENT, {
      detail: { lang: currentLang(), hazard },
    }));
  }

  panel.addEventListener('toggle', () => { if (panel.open) void loadOptions(); });
  if ((win.location && win.location.hash) === '#foto-bildirim') { panel.open = true; void loadOptions(); }
  panel.addEventListener('change', async (event) => {
    const target = event.target;
    if (target.id === 'photo-file') {
      const form = target.closest('form');
      const file = target.files && target.files[0];
      state = { ...state, errors: {}, prepared: null };
      if (!file) { renderForm('photo-file'); return; }
      try {
        state.prepared = await preparePhoto(file, win, currentLang());
        renderForm();
      } catch (error) {
        state.errors = { ...state.errors, photo: error.message || copy(currentLang(), 'resizeError') };
        renderForm('photo-file');
      }
      return;
    }
    if (target.name === 'photo-place-kind' || target.name === 'photo-category') {
      state = { ...state, ...formState(target.closest('form')), errors: {} };
      renderForm(target.id);
    }
    if (target.id === 'photo-district' || target.id === 'photo-consent') {
      state = { ...state, ...formState(target.closest('form')) };
      if (target.id === 'photo-consent' && target.checked) {
        const error = target.closest('form').querySelector('[data-error="consent"]');
        error.hidden = true;
        error.textContent = '';
        target.removeAttribute('aria-invalid');
        const { consent, ...errors } = state.errors;
        state.errors = errors;
      }
    }
  });
  panel.addEventListener('input', (event) => {
    if (event.target.id === 'photo-description' || event.target.id === 'photo-station') {
      state = { ...state, ...formState(event.target.closest('form')) };
      if (event.target.id === 'photo-description') {
        const count = event.target.closest('form').querySelector('#photo-description-count');
        count.textContent = copy(currentLang(), 'remaining', { count: 280 - event.target.value.length });
      }
    }
  });
  panel.addEventListener('submit', (event) => {
    if (event.target.matches('.photo-report-form')) { event.preventDefault(); void submit(event.target); }
  });
  panel.addEventListener('click', (event) => {
    const button = event.target.closest('[data-action]');
    if (!button) return;
    const action = button.dataset.action;
    if (action === 'cancel') { panel.open = false; region.innerHTML = ''; state.prepared = null; return; }
    if (action === 'retry') { void loadOptions(); return; }
    if (action === 'remove-device') {
      const code = button.dataset.code;
      codes.delete(code);
      views.delete(code);
      writeCodes(storage, [...codes.values()]);
      renderCards();
      announce(copy(currentLang(), 'removed'));
    }
    if (action === 'delete-report') {
      const code = button.dataset.code;
      const now = Date.now();
      if (!deletePending || deletePending.code !== code || deletePending.until < now) {
        deletePending = { code, until: now + 10_000 };
        announce(copy(currentLang(), 'deleteFirst'));
        return;
      }
      deletePending = null;
      void del(`/api/photo-reports/${encodeURIComponent(code)}`).then(() => {
        codes.delete(code);
        views.delete(code);
        writeCodes(storage, [...codes.values()]);
        renderCards();
        announce(copy(currentLang(), 'deleted'));
        startPolling();
      }).catch((error) => announce(error.message || copy(currentLang(), 'loadError')));
    }
  });

  const stored = [...codes.keys()];
  if (stored.length) {
    renderCards();
    Promise.all(stored.map((code) => refresh(code, { startup: true }))).then(startPolling);
  }
  onLang(() => {
    const form = region.querySelector('form');
    if (form) state = { ...state, ...formState(form) };
    panel.querySelector('summary h2').textContent = copy(currentLang(), 'title');
    if (form) renderForm(state.focused);
    renderCards();
  });
  return panel;
}

export {
  COPY, KEEP_DAYS, KEEP_MAX, POLL_MS, STORAGE_KEY, cardMarkup, fitWithin, formMarkup, mountPhotoReport,
  parseStored, sniffPhoto, statusSentence,
};

if (typeof document !== 'undefined') mountPhotoReport(document);
