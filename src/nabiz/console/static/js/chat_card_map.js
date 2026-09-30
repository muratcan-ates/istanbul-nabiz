/* A map card keeps its point list readable before Leaflet loads and if it fails. */
import { registerCardType, releaseCardAction } from './chat_cards.js';
import { t } from './i18n_text.js';

const instances = new Map();
const LEAFLET_CSS = '/vendor/leaflet/leaflet.css';
const LEAFLET_JS = '/vendor/leaflet/leaflet.js';
let leafletLoad = null;
let baseModule = null;
let listening = false;
let dialogCount = 0;

function key(cardId, messageId) { return `${cardId}\0${messageId || ''}`; }

function textNode(tag, className, value) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = value;
  return node;
}

function pointsOf(card) {
  const raw = card.body?.points;
  if (!Array.isArray(raw)) return [];
  return raw.filter((point) => point && typeof point === 'object'
    && Number.isFinite(point.lat) && point.lat >= -90 && point.lat <= 90
    && Number.isFinite(point.lon) && point.lon >= -180 && point.lon <= 180
    && typeof point.label === 'string' && point.label.trim())
    .slice(0, 60);
}

function stylesheet() {
  const existing = document.querySelector?.(`link[href="${LEAFLET_CSS}"]`);
  if (existing?.sheet) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const link = existing || document.createElement('link');
    link.addEventListener('load', resolve, { once: true });
    link.addEventListener('error', () => reject(new Error('leaflet css')), { once: true });
    if (!existing) {
      link.rel = 'stylesheet';
      link.href = LEAFLET_CSS;
      document.head.append(link);
    }
  });
}

function script() {
  if (window.L?.map) return Promise.resolve();
  const existing = document.querySelector?.(`script[src="${LEAFLET_JS}"]`);
  return new Promise((resolve, reject) => {
    const node = existing || document.createElement('script');
    node.addEventListener('load', () => window.L?.map ? resolve() : reject(new Error('leaflet js')), { once: true });
    node.addEventListener('error', () => reject(new Error('leaflet js')), { once: true });
    if (!existing) {
      node.src = LEAFLET_JS;
      document.head.append(node);
    }
  });
}

/* The sample base map (js/map_base.js) is drawn here, imported only once a map card is in view. */
function ensureLeaflet() {
  leafletLoad ||= Promise.all([
    window.L?.map ? null : stylesheet(),
    script(),
    import('./map_base.js').then((module) => { baseModule = module; }),
  ]);
  return leafletLoad;
}

function failure(inst) {
  if (inst.failed) return;
  inst.failed = true;
  inst.map?.remove?.();
  inst.map = null;
  inst.frame.hidden = true;
  inst.status.textContent = t('ui.cards.map_failed', 'Harita yüklenemedi.');
  if (inst.dialog) closeDialog(inst);
  const trigger = inst.root.closest?.('.chat-card')?.querySelector?.('[data-card-action="expand_map"]');
  if (trigger) trigger.hidden = true;
}

function createMap(inst) {
  if (inst.failed || !inst.frame.isConnected) return;
  const map = window.L.map(inst.frame, { zoomControl: true, attributionControl: true, keyboard: true });
  inst.map = map;
  if (inst.points.length === 1) map.setView([inst.points[0].lat, inst.points[0].lon], 15);
  else map.fitBounds(inst.points.map((point) => [point.lat, point.lon]), { padding: [28, 28], maxZoom: 15 });
  baseModule.mockBase(window.L, map, {
    attribution: t('ui.cards.map_base', 'Örnek harita altlığı; kıyılar yaklaşık'),
  }).addTo(map);
  inst.points.forEach((point) => {
    const popup = textNode('span', '', point.label);
    window.L.marker([point.lat, point.lon]).bindPopup(popup).addTo(map);
  });
  map.invalidateSize();
}

function loadVisible(inst) {
  if (inst.loading || inst.failed || !inst.points.length) return;
  inst.loading = true;
  ensureLeaflet().then(() => createMap(inst)).catch(() => failure(inst));
}

function visibleNow(node) {
  if (!node.getBoundingClientRect) return true;
  const box = node.getBoundingClientRect();
  return box.bottom > 0 && box.top < (window.innerHeight || document.documentElement.clientHeight);
}

function observe(inst) {
  if (inst.card.sensitive) { inst.frame.hidden = true; return; }
  if (!inst.points.length) { failure(inst); return; }
  if (typeof IntersectionObserver === 'function') {
    const observer = new IntersectionObserver((entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return;
      observer.disconnect();
      loadVisible(inst);
    });
    observer.observe(inst.frame);
  } else {
    const check = () => {
      if (!inst.frame.isConnected || !visibleNow(inst.frame)) return;
      window.removeEventListener?.('scroll', check);
      window.removeEventListener?.('resize', check);
      loadVisible(inst);
    };
    window.addEventListener?.('scroll', check, { passive: true });
    window.addEventListener?.('resize', check);
    if (typeof requestAnimationFrame === 'function') requestAnimationFrame(check);
    else Promise.resolve().then(check);
  }
}

function closeDialog(inst) {
  const dialog = inst.dialog;
  if (!dialog) return;
  inst.dialog = null;
  if (dialog.open) dialog.close();
  inst.placeholder.after(inst.root);
  inst.placeholder.remove();
  dialog.remove();
  window.scrollTo?.(0, inst.scrollY);
  inst.trigger?.focus?.({ preventScroll: true });
  releaseCardAction(inst.card.id, 'expand_map');
  inst.map?.invalidateSize?.();
}

function openDialog(inst) {
  if (inst.dialog || inst.failed) { releaseCardAction(inst.card.id, 'expand_map'); return; }
  const trigger = inst.root.closest?.('.chat-card')?.querySelector?.('[data-card-action="expand_map"]');
  if (!trigger) { releaseCardAction(inst.card.id, 'expand_map'); return; }
  inst.trigger = trigger;
  inst.scrollY = window.scrollY || 0;
  const dialog = document.createElement('dialog');
  dialog.className = 'chat-map-dialog';
  const heading = textNode('h3', '', inst.card.title);
  heading.id = `chat-map-dialog-title-${++dialogCount}`;
  dialog.setAttribute('aria-labelledby', heading.id);
  const close = textNode('button', 'btn btn-quiet', t('ui.cards.close_map', 'Haritayı kapat'));
  close.type = 'button';
  close.addEventListener('click', () => closeDialog(inst));
  const header = document.createElement('div');
  header.className = 'chat-map-dialog-head';
  header.append(heading, close);
  inst.placeholder = document.createComment('map card position');
  inst.root.before(inst.placeholder);
  dialog.append(header, inst.root);
  document.body.append(dialog);
  inst.dialog = dialog;
  dialog.addEventListener('close', () => closeDialog(inst));
  dialog.addEventListener('cancel', (event) => { event.preventDefault(); closeDialog(inst); });
  try { dialog.showModal(); } catch { closeDialog(inst); return; }
  const size = () => inst.map?.invalidateSize?.();
  if (typeof requestAnimationFrame === 'function') requestAnimationFrame(size);
  else size();
  close.focus();
}

function listenActions() {
  if (listening) return;
  document.addEventListener('nabiz:card-action', (event) => {
    const detail = event.detail || {};
    if (detail.type !== 'map' || detail.action !== 'expand_map') return;
    const inst = instances.get(key(detail.card_id, detail.message_id));
    if (inst) { event.preventDefault(); openDialog(inst); }
  });
  listening = true;
}

export function renderMapCard(card) {
  const root = document.createElement('div');
  root.className = 'chat-card-map';
  const frame = document.createElement('div');
  frame.className = 'chat-card-map-frame';
  frame.setAttribute('role', 'region');
  frame.setAttribute('aria-label', t('ui.cards.map_points', 'Haritadaki konumlar'));
  frame.tabIndex = 0;
  const list = document.createElement('ul');
  list.className = 'chat-card-map-points';
  list.setAttribute('aria-label', t('ui.cards.map_points', 'Haritadaki konumlar'));
  const points = pointsOf(card);
  points.forEach((point) => list.append(textNode('li', '', point.label)));
  const status = textNode('p', 'chat-card-map-status', '');
  status.setAttribute('role', 'status');
  root.append(frame, list, status);
  const inst = { card, root, frame, status, points, loading: false, failed: false,
    map: null, dialog: null, placeholder: null, trigger: null, scrollY: 0 };
  instances.set(key(card.id, card.message_id), inst);
  listenActions();
  observe(inst);
  return root;
}

registerCardType('map', renderMapCard);
