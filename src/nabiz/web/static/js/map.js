/* Nothing on this page requires the map. MapLibre comes from a CDN; when that CDN is blocked the
 * answer still renders and the map panel degrades to a location list. */

import { esc } from './format.js';
import { scrollToElement, easeMap } from './motion.js';

const $ = (sel) => document.querySelector(sel);

let map = null;
let markers = [];
let mapBroken = false;
let mapForcedOff = false;
let lastPoints = [];

const KIND_TR = { park: 'Otopark', bus: 'Otobüs', station: 'İstasyon / durak', air: 'Hava ölçüm istasyonu', place: 'Yer' };

/* MapLibre's own names are English; a screen reader on this lang="tr" page reads them as Turkish. */
const MAP_LOCALE = {
  'Map.Title': 'Harita',
  'NavigationControl.ZoomIn': 'Yakınlaştır',
  'NavigationControl.ZoomOut': 'Uzaklaştır',
  'AttributionControl.ToggleAttribution': 'Harita kaynaklarını göster',
};

function mapAvailable() {
  return !mapForcedOff && typeof window.maplibregl !== 'undefined' && !mapBroken;
}

/** OSM raster by default; Azure Maps raster when the server injected a key. */
function mapStyle() {
  const key = window.NABIZ_MAPS_KEY;
  if (key) {
    const tile = 'https://atlas.microsoft.com/map/tile?api-version=2024-04-01'
      + '&tilesetId=microsoft.base.road&zoom={z}&x={x}&y={y}&tileSize=256&language=tr-TR'
      + `&subscription-key=${encodeURIComponent(key)}`;
    return {
      style: { version: 8, sources: { base: { type: 'raster', tiles: [tile], tileSize: 256, attribution: '© Microsoft, © TomTom' } }, layers: [{ id: 'base', type: 'raster', source: 'base' }] },
      label: 'Azure Maps',
    };
  }
  return {
    style: {
      version: 8,
      sources: { base: { type: 'raster', tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'], tileSize: 256, attribution: '© OpenStreetMap katkıcıları' } },
      layers: [{ id: 'base', type: 'raster', source: 'base' }],
    },
    label: 'OpenStreetMap',
  };
}

/** Hide the panel *and* drop the pins, so a later answer never inherits stale markers. */
function hideMap() {
  markers.forEach((m) => m.remove());
  markers = [];
  lastPoints = [];
  const panel = $('#map-panel');
  if (panel) panel.hidden = true;
}

function drawLegend(points) {
  const el = $('#map-legend');
  if (!el) return;
  const kinds = [];
  points.forEach((p) => { const k = p.kind || 'place'; if (!kinds.includes(k)) kinds.push(k); });
  el.innerHTML = kinds
    .map((k) => `<li><span class="swatch" style="background:var(--kind-${esc(k)})"></span>${esc(KIND_TR[k] || k)}</li>`)
    .join('');
}

/** The list view that replaces the map when MapLibre is unavailable. */
function drawFallback(points) {
  const box = $('#map-fallback');
  const list = $('#map-fallback-list');
  const frame = $('#map');
  if (!box || !list || !frame) return;
  box.hidden = false;
  frame.style.display = 'none';
  list.innerHTML = points.map((p) => {
    const url = `https://www.openstreetmap.org/?mlat=${encodeURIComponent(p.lat)}&mlon=${encodeURIComponent(p.lon)}#map=16/${encodeURIComponent(p.lat)}/${encodeURIComponent(p.lon)}`;
    return `<li><span class="swatch" style="background:var(--kind-${esc(p.kind || 'place')})"></span>
      <a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(p.label || 'Konum')}</a></li>`;
  }).join('');
  const src = $('#map-source');
  if (src) src.textContent = 'liste görünümü';
}

function showOnMap(points) {
  const usable = (points || []).filter((p) => Number.isFinite(p.lat) && Number.isFinite(p.lon));
  lastPoints = usable;
  const panel = $('#map-panel');
  if (!panel) return;
  if (!usable.length) { hideMap(); return; }
  panel.hidden = false;
  drawLegend(usable);

  if (!mapAvailable()) { drawFallback(usable); return; }

  try {
    if (!map) {
      const chosen = mapStyle();
      map = new window.maplibregl.Map({
        container: 'map',
        style: chosen.style,
        center: [usable[0].lon, usable[0].lat],
        zoom: 12,
        attributionControl: { compact: true },
        locale: MAP_LOCALE,
      });
      map.addControl(new window.maplibregl.NavigationControl({ showCompass: false }), 'top-right');
      const src = $('#map-source');
      if (src) src.textContent = `${chosen.label} · yalnızca görselleştirme`;
      const foot = $('#map-attribution');
      if (foot) foot.textContent = `harita: ${chosen.label}`;
    }
    markers.forEach((m) => m.remove());
    markers = usable.map((p) => {
      const el = document.createElement('button');
      el.type = 'button';
      el.className = `marker ${p.kind || 'place'}`;
      el.addEventListener('click', () => focusCard(p.card));
      const marker = new window.maplibregl.Marker({ element: el }).setLngLat([p.lon, p.lat]);
      if (p.label) marker.setPopup(new window.maplibregl.Popup({ offset: 14, closeButton: false }).setText(p.label));
      marker.nabizCard = p.card;
      marker.addTo(map);
      // After addTo, or MapLibre 4.7.1 overwrites it with "Map marker".
      el.setAttribute('aria-label', `${KIND_TR[p.kind] || 'Konum'}: ${p.label || ''}`);
      return marker;
    });
    const bounds = usable.reduce(
      (acc, p) => acc.extend([p.lon, p.lat]),
      new window.maplibregl.LngLatBounds([usable[0].lon, usable[0].lat], [usable[0].lon, usable[0].lat]),
    );
    map.fitBounds(bounds, { padding: 48, maxZoom: 15, duration: 0 });
  } catch (err) {
    // A broken map must never take the answer with it.
    mapBroken = true;
    drawFallback(usable);
    console.warn('harita devre dışı:', err);
  }
}

/** Clicking a marker opens the matching card: scroll to it, ring it, focus it. */
function focusCard(id) {
  if (!id) return;
  document.querySelectorAll('.card.is-focused').forEach((c) => c.classList.remove('is-focused'));
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.add('is-focused');
  scrollToElement(el, 'center');
  el.focus({ preventScroll: true });
}

/** The inverse: clicking a card lifts its marker. */
function highlightMarker(id) {
  markers.forEach((m) => {
    const el = m.getElement && m.getElement();
    if (el) el.classList.toggle('is-active', m.nabizCard === id);
  });
  const point = lastPoints.find((p) => p.card === id);
  if (point && map) easeMap(map, { center: [point.lon, point.lat], duration: 400 });
}

/** ?nomap=1 takes the "CDN is blocked" path on purpose; main.js reads the flag at boot. */
function forceMapOff() {
  mapForcedOff = true;
}

export { hideMap, showOnMap, highlightMarker, forceMapOff };
