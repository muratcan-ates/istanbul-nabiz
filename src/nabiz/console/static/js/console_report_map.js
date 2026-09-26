/* The simulated operator's report map is optional; its text list works without Leaflet. */

import { MOCK, get } from './api.js';
import { REFRESH_MS } from './config.js';
import { esc, int } from './format.js';
import { icon } from './icons.js';

const LEAFLET_VERSION = '1.9.4';
const KIND_TEXT = { not_working: 'asansör kapalıydı', data_wrong: 'kayıt yanlış görünüyor' };
const stylesheetLoads = new Map();

let leafletLoad = null;
let map = null;
let dots = null;

function setStatus(element, message) {
  if (element && element.textContent !== message) element.textContent = message;
}

function countText(row) {
  return Object.entries(row.by_kind || {})
    .filter(([, count]) => Number(count) > 0)
    .map(([kind, count]) => `${int(count)} ${KIND_TEXT[kind] || 'bildirim'}`)
    .join(', ');
}

function rowText(row) {
  const parts = [`${esc(row.station)} · ${int(row.reports)} bildirim`];
  const breakdown = countText(row);
  if (breakdown) parts.push(`(${breakdown})`);
  if (row.record_text) parts.push(esc(row.record_text));
  if (!Number.isFinite(row.lat) || !Number.isFinite(row.lon)) parts.push('Haritada istasyon noktası bulunamadı');
  if (!row.open_signal_id) parts.push('karar verildi');
  return parts.join(' · ');
}

export function rowMarkup(row) {
  const text = rowText(row);
  const conflict = row.conflict ? '<span class="tag is-warn">Çelişki</span>' : '';
  if (row.open_signal_id) {
    return `<li><button type="button" class="rm-row" data-open="${esc(row.open_signal_id)}">${text} ${conflict}</button></li>`;
  }
  return `<li class="rm-row is-closed">${text} ${conflict}</li>`;
}

export function dotRadius(reports) {
  return Math.min(24, 6 + 4 * Math.sqrt(reports));
}

function loadStylesheet(href) {
  if (stylesheetLoads.has(href)) return stylesheetLoads.get(href);
  const existing = [...document.querySelectorAll('link[rel="stylesheet"]')]
    .find((link) => link.getAttribute('href') === href);
  if (existing?.sheet) {
    const ready = Promise.resolve();
    stylesheetLoads.set(href, ready);
    return ready;
  }
  const loading = new Promise((resolve, reject) => {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = href;
    link.onload = resolve;
    link.onerror = () => reject(new Error('Harita stili yüklenemedi.'));
    document.head.append(link);
  });
  stylesheetLoads.set(href, loading);
  return loading;
}

function loadScript() {
  if (window.L?.version === LEAFLET_VERSION) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = '/vendor/leaflet/leaflet.js';
    script.onload = () => window.L?.version === LEAFLET_VERSION
      ? resolve()
      : reject(new Error('Harita kütüphanesi doğrulanamadı.'));
    script.onerror = () => reject(new Error('Harita kütüphanesi yüklenemedi.'));
    document.head.append(script);
  });
}

function loadLeaflet() {
  leafletLoad = leafletLoad || Promise.all([
    loadStylesheet('/vendor/leaflet/leaflet.css'),
    loadScript(),
  ]);
  return leafletLoad;
}

function tileSource() {
  return window.L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" rel="noopener noreferrer" target="_blank">'
      + 'OpenStreetMap katkıcıları</a>',
    minZoom: 3,
    maxZoom: 19,
    updateWhenIdle: true,
    updateWhenZooming: false,
    keepBuffer: 1,
  });
}

function drawMap(rows) {
  dots.clearLayers();
  const points = [];
  rows.forEach((row) => {
    if (!Number.isFinite(row.lat) || !Number.isFinite(row.lon)) return;
    const point = [row.lat, row.lon];
    points.push(point);
    const circle = window.L.circleMarker(point, {
      radius: dotRadius(row.reports),
      className: row.conflict ? 'rm-dot is-conflict' : 'rm-dot',
    }).addTo(dots);
    circle.bindTooltip(String(row.reports) + (row.conflict ? ' · çelişki' : ''), {
      permanent: true,
      direction: 'right',
      className: 'rm-label',
    });
    circle.on('click', () => openSignal(row.open_signal_id));
  });
  if (points.length) map.fitBounds(points, { padding: [20, 20], maxZoom: 14 });
  else map.setView([41.015, 28.979], 10);
}

function rowSet(data) {
  return [
    ...(Array.isArray(data.stations) ? data.stations : []),
    ...(Array.isArray(data.unplaced) ? data.unplaced : []),
  ];
}

function openSignal(id) {
  const target = id ? document.querySelector('#queue .queue-item[data-id="' + CSS.escape(id) + '"]') : null;
  if (id && target) {
    target.scrollIntoView({ block: 'center' });
    target.click();
  } else {
    setStatus(document.getElementById('rm-status'), 'Bu kart artık onay kuyruğunda değil.');
  }
}

function listMarkup(rows) {
  return rows.length
    ? rows.map(rowMarkup).join('')
    : '<li class="rm-empty">Bu pencerede vatandaş bildirimi yok.</li>';
}

function mount() {
  const host = document.getElementById('report-map');
  if (!host) return;
  if (MOCK) {
    const note = document.createElement('p');
    note.className = 'rm-note';
    note.textContent = 'Örnek veride bildirim haritası yok.';
    host.append(note);
    return;
  }

  host.insertAdjacentHTML('beforeend', `
    <p class="rm-note">Vatandaş bildirimi, doğrulanmamış. Simüle operatör.</p>
    <div class="rm-controls" role="group" aria-label="Zaman penceresi">
      <button type="button" class="btn" data-window="30m" aria-pressed="true">Son 30 dk</button>
      <button type="button" class="btn" data-window="24h" aria-pressed="false">Son 24 saat</button>
      <button type="button" class="btn" id="rm-show-map" aria-expanded="false" aria-controls="rm-canvas">${icon('map')}Haritayı göster</button>
    </div>
    <p class="sr-only" id="rm-status" role="status"></p>
    <div class="rm-canvas" id="rm-canvas" hidden></div>
    <ol class="rm-list" id="rm-list"></ol>
  `);

  const status = host.querySelector('#rm-status');
  const list = host.querySelector('#rm-list');
  const canvas = host.querySelector('#rm-canvas');
  const mapButton = host.querySelector('#rm-show-map');
  const windowButtons = [...host.querySelectorAll('[data-window]')];
  let selectedWindow = '30m';
  let previousMarkup = null;
  let refreshing = false;

  async function showMap(rows) {
    try {
      await loadLeaflet();
      if (!map) {
        map = window.L.map('rm-canvas');
        tileSource().addTo(map);
        dots = window.L.layerGroup().addTo(map);
      }
      drawMap(rows);
      map.invalidateSize();
    } catch {
      setStatus(status, 'Harita yüklenemedi; liste aynı bilgiyi gösterir.');
    }
  }

  async function refresh() {
    if (document.hidden || refreshing) return;
    refreshing = true;
    try {
      const data = await get('/api/console/report-map', { window: selectedWindow });
      const rows = rowSet(data);
      const markup = listMarkup(rows);
      if (markup !== previousMarkup) {
        list.innerHTML = markup;
        previousMarkup = markup;
        const first = rows[0];
        const announcement = first
          ? `${first.station} en çok: ${int(first.reports)} bildirim. Toplam ${int(data.total_reports)} bildirim.`
          : 'Bu pencerede vatandaş bildirimi yok.';
        setStatus(status, announcement);
      }
      if (map) drawMap(data.stations || []);
    } catch (err) {
      setStatus(status, err.message);
    } finally {
      refreshing = false;
    }
  }

  host.addEventListener('click', (event) => {
    const row = event.target.closest('[data-open]');
    if (row) openSignal(row.dataset.open);
  });
  windowButtons.forEach((button) => {
    button.addEventListener('click', () => {
      selectedWindow = button.dataset.window;
      windowButtons.forEach((item) => item.setAttribute('aria-pressed', String(item === button)));
      refresh();
    });
  });
  mapButton.addEventListener('click', async () => {
    const expanded = mapButton.getAttribute('aria-expanded') === 'true';
    canvas.hidden = expanded;
    mapButton.setAttribute('aria-expanded', String(!expanded));
    mapButton.innerHTML = `${icon('map')}${expanded ? 'Haritayı göster' : 'Haritayı gizle'}`;
    if (!expanded) {
      try {
        const data = await get('/api/console/report-map', { window: selectedWindow });
        await showMap(data.stations || []);
      } catch (err) {
        setStatus(status, err.message);
      }
    }
  });
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) refresh();
  });
  window.setInterval(refresh, REFRESH_MS);
  refresh();
}

if (typeof document !== 'undefined') mount();
