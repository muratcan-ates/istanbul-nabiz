import { CARD_TEXT, REVIEWED_LANGS, RTL_LANGS, TR_BLOCK, UNVERIFIED_LABEL } from './emergency_text.js';

export const EMERGENCY_EVENT = 'nabiz:emergency';
// The card's text lives in emergency_text.js (a copy of the server's emergency_text.py). The page itself
// stays Turkish or English (DECISIONS #35); only this card speaks the detected language (DECISIONS #40).
export { CARD_TEXT };

let activeDocument = null;
let previousInert = new Map();
let currentCoords = null;
let locationRequested = false;

export function pickLang(value) {
  const code = String(value ?? '').trim().toLowerCase().slice(0, 2);
  return Object.hasOwn(CARD_TEXT, code) ? code : 'tr';
}

function textDir(lang) {
  return RTL_LANGS.includes(lang) ? 'rtl' : 'ltr';
}

// Every translation but Turkish and English is unchecked by a native reader: the card says so, in Turkish.
function draftLabel(lang) {
  if (REVIEWED_LANGS.includes(lang)) return '';
  return `<p class="emergency-draft" lang="tr" dir="ltr">${UNVERIFIED_LABEL}</p>`;
}

// The large Turkish block is on every card: the person shows it to anyone nearby.
function turkishBlock(gas) {
  const gasLine = gas ? `<p class="emergency-tr-gas">${TR_BLOCK.gas}</p>` : '';
  return `<div class="emergency-tr" id="emergency-tr" lang="tr" dir="ltr" tabindex="-1">`
    + `<p class="emergency-tr-plea">${TR_BLOCK.plea}</p>${gasLine}</div>`;
}

// 187 is İGDAŞ's natural gas emergency line, named in İBB's 2025 activity report
// (uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf, "187 Doğal Gaz Acil Hattı").
// It is shown only for a gas hazard and only after the 112 button (DECISIONS #36).
export function cardMarkup(lang = 'tr', hazard = null) {
  const code = pickLang(lang);
  const text = CARD_TEXT[code];
  const gas = hazard === 'gas';
  const gasLink = gas ? `<a class="emergency-gas" href="tel:187">${text.gas}</a>` : '';
  return `<section class="emergency-card" id="emergency-card" role="alertdialog" aria-modal="true" aria-labelledby="emergency-title" aria-describedby="emergency-desc" lang="${code}" dir="${textDir(code)}">`
    + `<h2 id="emergency-title">${text.title}</h2>${draftLabel(code)}`
    + `<p id="emergency-desc">${text.show}</p><p class="emergency-note">${text.note}</p>`
    + '<p class="emergency-live" aria-live="assertive"></p>'
    + `<a class="emergency-call" href="tel:112">${text.call}</a>`
    + gasLink
    + `<button type="button" class="emergency-locate" data-act="locate">${text.locate}</button>`
    + '<p class="emergency-location" role="status"></p>'
    + `<button type="button" class="emergency-copy" data-act="copy" hidden>${text.copy}</button>`
    + turkishBlock(gas)
    + `<button type="button" class="emergency-grow" data-act="grow" aria-pressed="false" aria-controls="emergency-tr">${text.grow}</button>`
    + `<a class="emergency-153" href="tel:153">${text.line153}</a>`
    + `<button type="button" class="emergency-back" data-act="back">${text.back}</button>`
    + `<p class="emergency-foot">${text.foot}</p></section>`;
}

export function formatCoords(lat, lon) {
  if (!Number.isFinite(lat) || !Number.isFinite(lon) || lat < -90 || lat > 90 || lon < -180 || lon > 180) {
    return null;
  }
  return `${lat.toFixed(5)}, ${lon.toFixed(5)}`;
}

// Coordinates read left to right in every card: inside an Arabic or Persian sentence they are isolated,
// or the bidi algorithm could show "28.97612 ,41.01235" to someone reading them to 112.
export function locationMessage(kind, coords, lang = 'tr') {
  const code = pickLang(lang);
  const text = CARD_TEXT[code][kind] || CARD_TEXT.tr.denied;
  const safeCoords = coords == null ? '' : coords;
  const shown = safeCoords && RTL_LANGS.includes(code) ? `⁦${safeCoords}⁩` : safeCoords;
  return text.replace('{coords}', shown);
}

function filled(value) {
  return typeof value === 'string' && value.trim().length > 0;
}

function emergencyMessage(doc) {
  return doc.querySelector('.chat-msg.is-emergency');
}

function resolveLang(doc, eventLang, message) {
  if (filled(eventLang)) return pickLang(eventLang);
  const messageLang = message?.closest('[lang]')?.lang;
  if (filled(messageLang)) return pickLang(messageLang);
  if (filled(doc.documentElement?.lang)) return pickLang(doc.documentElement.lang);
  return 'tr';
}

function addStylesheet(doc) {
  if (doc.querySelector('[data-emergency-styles]')) return;
  const link = doc.createElement('link');
  link.rel = 'stylesheet';
  link.href = '/css/emergency.css';
  link.setAttribute('data-emergency-styles', '');
  (doc.head || doc.documentElement).appendChild(link);
}

function setBackgroundInert(doc, card) {
  previousInert = new Map();
  for (const child of doc.body.children) {
    if (child === card) continue;
    previousInert.set(child, Boolean(child.inert));
    if (!child.inert) child.inert = true;
  }
  doc.documentElement.classList.add('emergency-open');
}

function restoreBackground(doc) {
  for (const [element, wasInert] of previousInert) {
    if (element.isConnected) element.inert = wasInert;
  }
  previousInert.clear();
  doc.documentElement.classList.remove('emergency-open');
}

function focusables(card) {
  return Array.from(card.querySelectorAll('a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])'))
    .filter((element) => !element.hidden && !element.inert);
}

function trapFocus(card, event) {
  if (event.key === 'Escape') {
    event.preventDefault();
    closeEmergency();
    return;
  }
  if (event.key !== 'Tab') return;
  const items = focusables(card);
  if (!items.length) return;
  const first = items[0];
  const last = items[items.length - 1];
  if (event.shiftKey && card.ownerDocument.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && card.ownerDocument.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function updateLocation(card, kind, coords, lang) {
  const status = card.querySelector('.emergency-location');
  status.textContent = locationMessage(kind, coords, lang);
  if (kind === 'shown') card.querySelector('[data-act="copy"]').hidden = false;
}

function locate(card, lang) {
  if (locationRequested) return;
  locationRequested = true;
  card.querySelector('[data-act="locate"]').disabled = true;
  updateLocation(card, 'waiting', null, lang);
  const geolocation = activeDocument?.defaultView?.navigator?.geolocation;
  const positionMethod = 'getCurrentPosition';
  const requestPosition = geolocation?.[positionMethod];
  if (typeof requestPosition !== 'function') {
    updateLocation(card, 'denied', null, lang);
    return;
  }
  requestPosition.call(
    geolocation,
    (position) => {
      const coords = formatCoords(position.coords.latitude, position.coords.longitude);
      if (!coords) {
        updateLocation(card, 'denied', null, lang);
        return;
      }
      currentCoords = coords;
      updateLocation(card, 'shown', coords, lang);
    },
    () => updateLocation(card, 'denied', null, lang),
    { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 },
  );
}

async function copyLocation(card, lang) {
  const clipboard = activeDocument?.defaultView?.navigator?.clipboard;
  if (!currentCoords || typeof clipboard?.writeText !== 'function') {
    updateLocation(card, 'copyfail', currentCoords, lang);
    return;
  }
  try {
    await clipboard.writeText(currentCoords);
    updateLocation(card, 'copied', currentCoords, lang);
  } catch {
    updateLocation(card, 'copyfail', currentCoords, lang);
  }
}

// "Show the Turkish larger": the Turkish block fills the width in very large letters, and scrolls into view
// so the person can turn the phone to whoever is next to them. Pressed again, it returns to its size.
export function toggleTurkish(card) {
  const button = card.querySelector('[data-act="grow"]');
  const grown = !card.classList.contains('is-grown');
  card.classList.toggle('is-grown', grown);
  button?.setAttribute('aria-pressed', String(grown));
  const block = card.querySelector('.emergency-tr');
  if (grown && typeof block?.scrollIntoView === 'function') block.scrollIntoView({ block: 'start' });
  return grown;
}

function wireCard(card, lang) {
  card.addEventListener('keydown', (event) => trapFocus(card, event));
  card.addEventListener('click', (event) => {
    const action = event.target?.closest?.('[data-act]');
    if (!action || !card.contains(action)) return;
    if (action.dataset.act === 'back') closeEmergency();
    if (action.dataset.act === 'locate') locate(card, lang);
    if (action.dataset.act === 'copy') void copyLocation(card, lang);
    if (action.dataset.act === 'grow') toggleTurkish(card);
  });
}

export function openEmergency(lang, hazard = null) {
  const doc = activeDocument || (typeof document === 'undefined' ? null : document);
  if (!doc?.body) return;
  const current = doc.getElementById('emergency-card');
  if (current) {
    current.querySelector('.emergency-call')?.focus();
    return;
  }
  const message = emergencyMessage(doc);
  const selectedLang = resolveLang(doc, lang, message);
  const holder = doc.createElement('div');
  holder.innerHTML = cardMarkup(selectedLang, hazard);
  const card = holder.firstElementChild;
  doc.body.appendChild(card);
  setBackgroundInert(doc, card);
  card.querySelector('.emergency-live').textContent = CARD_TEXT[selectedLang].live;
  wireCard(card, selectedLang);
  currentCoords = null;
  locationRequested = false;
  card.querySelector('.emergency-call').focus();
}

export function closeEmergency() {
  const doc = activeDocument || (typeof document === 'undefined' ? null : document);
  const card = doc?.getElementById('emergency-card');
  if (!doc || !card) return;
  card.remove();
  restoreBackground(doc);
  currentCoords = null;
  locationRequested = false;
  doc.getElementById('chat-input')?.focus();
}

function markExistingMessages(log) {
  for (const message of log.querySelectorAll('.chat-msg.is-emergency')) {
    message.dataset.emergencySeen = '1';
  }
}

function inspectNode(node, doc) {
  if (node.nodeType !== 1) return;
  const candidates = [];
  if (node.matches?.('.chat-msg.is-emergency')) candidates.push(node);
  candidates.push(...node.querySelectorAll('.chat-msg.is-emergency'));
  for (const message of candidates) {
    if (message.dataset.emergencySeen === '1') continue;
    message.dataset.emergencySeen = '1';
    openEmergency(resolveLang(doc, null, message));
  }
}

export function mountEmergency(doc) {
  if (!doc || !doc.body || doc.__nabizEmergencyMounted) return;
  doc.__nabizEmergencyMounted = true;
  activeDocument = doc;
  addStylesheet(doc);
  doc.addEventListener(EMERGENCY_EVENT, (event) => openEmergency(
    resolveLang(doc, event.detail?.lang, emergencyMessage(doc)),
    event.detail?.hazard,
  ));
  const log = doc.getElementById('chat-log');
  if (!log) return;
  markExistingMessages(log);
  const MutationObserver = doc.defaultView?.MutationObserver || globalThis.MutationObserver;
  if (!MutationObserver) return;
  const observer = new MutationObserver((records) => {
    for (const record of records) {
      if (record.type === 'attributes') inspectNode(record.target, doc);
      for (const node of record.addedNodes) inspectNode(node, doc);
    }
  });
  observer.observe(log, { childList: true, subtree: true, attributes: true, attributeFilter: ['class'] });
}

if (typeof document !== 'undefined') mountEmergency(document);
