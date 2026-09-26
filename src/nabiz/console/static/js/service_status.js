import { MOCK, get } from './api.js';

const STATUS_PATH = '/api/service-status';
const POLL_MS = 30000;
const descriptions = new WeakMap();
const mounted = new WeakSet();

function isPaused(body) {
  return body?.chat === 'paused';
}

function escapeText(value) {
  return String(value).replace(/[&<>"']/g, (character) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character]
  ));
}

function bandMarkup(body) {
  const message = escapeText(body?.message || "Sohbet geçici olarak durduruldu. 153'ü arayabilirsiniz.");
  return `<p class="service-status-text" id="service-status-text">${message}</p>
    <a class="service-status-call" href="tel:153">153'ü ara</a>`;
}

function addStylesheet(doc) {
  if (doc.querySelector('link[data-service-status-styles]')) return;
  const link = doc.createElement('link');
  link.rel = 'stylesheet';
  link.href = '/css/service_status.css';
  link.dataset.serviceStatusStyles = 'true';
  doc.head.append(link);
}

function applyStatus(doc, body) {
  const root = doc.documentElement;
  const paused = isPaused(body);
  const mode = paused ? 'paused' : 'open';
  if (root.dataset.chat === mode) return;
  const form = doc.getElementById('chat-form');
  if (!form) return;
  let band = doc.getElementById('service-status');
  if (!band) {
    band = doc.createElement('div');
    band.className = 'service-status';
    band.id = 'service-status';
    band.setAttribute('role', 'status');
    band.hidden = true;
    const offline = doc.getElementById('pwa-chat-offline');
    if (offline && offline.parentNode === form.parentNode) offline.before(band);
    else form.before(band);
  }
  const input = doc.getElementById('chat-input');
  const submit = doc.getElementById('chat-submit');
  if (input && !descriptions.has(input)) descriptions.set(input, input.getAttribute('aria-describedby') || '');
  if (paused) {
    band.innerHTML = bandMarkup(body);
    band.hidden = false;
    if (input) {
      input.disabled = true;
      const original = descriptions.get(input).split(/\s+/).filter(Boolean);
      input.setAttribute('aria-describedby', [...new Set([...original, 'service-status-text'])].join(' '));
    }
    if (submit) submit.disabled = true;
  } else {
    band.replaceChildren();
    band.hidden = true;
    if (input) {
      input.disabled = false;
      const original = descriptions.get(input);
      if (original) input.setAttribute('aria-describedby', original);
      else input.removeAttribute('aria-describedby');
    }
    if (submit) submit.disabled = false;
  }
  root.dataset.chat = mode;
}

function mountServiceStatus(doc) {
  if (mounted.has(doc)) return;
  mounted.add(doc);
  const form = doc.getElementById('chat-form');
  if (!form) return;
  addStylesheet(doc);
  let band = doc.getElementById('service-status');
  if (!band) {
    band = doc.createElement('div');
    band.className = 'service-status';
    band.id = 'service-status';
    band.setAttribute('role', 'status');
    band.hidden = true;
    const offline = doc.getElementById('pwa-chat-offline');
    if (offline && offline.parentNode === form.parentNode) offline.before(band);
    else form.before(band);
  }
  const guard = (event) => {
    if (event.target !== form || doc.documentElement.dataset.chat !== 'paused') return;
    event.preventDefault();
    event.stopImmediatePropagation();
    doc.querySelector('.service-status-call')?.focus();
  };
  window.addEventListener('submit', guard, true);
  if (MOCK) return;
  let timer = null;
  const check = async () => {
    try {
      applyStatus(doc, await get(STATUS_PATH));
    } catch {
      // A failed read preserves the last known state until the next successful response.
    }
  };
  void check();
  timer = setInterval(check, POLL_MS);
  doc.addEventListener('visibilitychange', () => {
    if (doc.hidden) {
      clearInterval(timer);
      timer = null;
    } else {
      if (timer === null) timer = setInterval(check, POLL_MS);
      void check();
    }
  });
}

if (typeof document !== 'undefined') mountServiceStatus(document);

export { STATUS_PATH, POLL_MS, isPaused, bandMarkup, applyStatus, mountServiceStatus };
