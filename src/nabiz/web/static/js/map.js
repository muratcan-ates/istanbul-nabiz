/* The map (spec step 8). Nothing on this page requires it: MapLibre comes from a CDN only when an
 * answer has points (on a phone only when "Haritada göster" is pressed), and when it is blocked,
 * turned off (?nomap=1) or broken, the panel lists the places with their values and ages. */

import { esc } from './format.js';
import { icon } from './icons.js';
import { scrollToElement, easeMap } from './motion.js';

const $ = (sel) => document.querySelector(sel);
const wide = window.matchMedia('(min-width: 1024px)');

/* MapLibre (about 790 KB) pinned to the exact 4.7.1 files by these hashes; a blocked or changed
 * file sets NABIZ_MAP_BLOCKED and the list stays. How the hashes were made: docs/design/README.md,
 * "Lazy map". */
const MAPLIBRE = 'https://cdnjs.cloudflare.com/ajax/libs/maplibre-gl/4.7.1/maplibre-gl.min';
const MAPLIBRE_SRI = {
  css: 'sha384-K282sW/zFjTkrjR/+yr1H+gCukuy4OEYrkXRybV88g7pk+kZZYpNV6SAV59NcgFg',
  js: 'sha384-KKgyz2mG25bKJ1O2PyqTJPlAF8Kw2BpDmsLTNBXslICOBvhTAyF5F0XhLWF2ZovY',
};
const KIND_TR = { park: 'Otopark', bus: 'Otobüs', station: 'İstasyon, durak', air: 'Hava ölçüm istasyonu', place: 'Yer' };
const KIND_ICONS = { park: 'parking', bus: 'bus', station: 'train', air: 'wind', place: 'map-pin' };
/* MapLibre's own names are English; a screen reader on this lang="tr" page reads them as Turkish. */
const MAP_LOCALE = {
  'Map.Title': 'Harita',
  'NavigationControl.ZoomIn': 'Yakınlaştır',
  'NavigationControl.ZoomOut': 'Uzaklaştır',
  'AttributionControl.ToggleAttribution': 'Harita kaynaklarını göster',
};
/* Markers closer than this merge into one that names them all: WCAG 2.5.8 wants 24 px between
 * targets, and the rows' "Haritada göster" buttons are the full-size equivalent for each. */
const MERGE_PX = 24;
const CLOSE_ZOOM = 16;

let map = null;
let markers = [];
let points = [];
let off = false;
let opened = false;
let active = null; // the row whose marker is lifted, kept when markers merge or split again
let loading = null;
let preloaded = false;

const asset = (tag, props) => document.head.appendChild(Object.assign(document.createElement(tag), props,
  { crossOrigin: 'anonymous', referrerPolicy: 'no-referrer' }));

function loadMapLibre() {
  loading = loading || new Promise((resolve) => {
    asset('link', { rel: 'stylesheet', href: `${MAPLIBRE}.css`, integrity: MAPLIBRE_SRI.css });
    const script = asset('script', { src: `${MAPLIBRE}.js`, integrity: MAPLIBRE_SRI.js });
    script.onload = resolve;
    script.onerror = () => { window.NABIZ_MAP_BLOCKED = true; resolve(); };
  });
  return loading;
}

/** Intent (the first focus of the question box, a pointer over a chip) fetches the two files
 * without running them, on a wide screen only and never when the visitor asked to save data. */
function preloadMapLibre() {
  if (preloaded || off || !wide.matches || (navigator.connection && navigator.connection.saveData)) return;
  preloaded = true;
  asset('link', { rel: 'preload', as: 'style', href: `${MAPLIBRE}.css`, integrity: MAPLIBRE_SRI.css });
  asset('link', { rel: 'preload', as: 'script', href: `${MAPLIBRE}.js`, integrity: MAPLIBRE_SRI.js });
}

const available = () => !off && !window.NABIZ_MAP_BLOCKED;
const token = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const isDark = () => {
  const theme = document.documentElement.dataset.theme;
  return theme ? theme === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches;
};

/* Calm tiles: desaturated and a little transparent over the page's map wash, a token read at run
 * time. Dark mode inverts the raster (spec 9), an approximation to judge on real tiles. */
function rasterPaint() {
  return isDark()
    ? { 'raster-brightness-min': 1, 'raster-brightness-max': 0, 'raster-hue-rotate': 180, 'raster-saturation': -0.7, 'raster-opacity': 0.85 }
    : { 'raster-brightness-min': 0, 'raster-brightness-max': 1, 'raster-hue-rotate': 0, 'raster-saturation': -0.6, 'raster-opacity': 0.85 };
}

function repaint() {
  if (!map || !map.isStyleLoaded()) return;
  map.setPaintProperty('wash', 'background-color', token('--map-wash'));
  Object.entries(rasterPaint()).forEach(([key, value]) => map.setPaintProperty('base', key, value));
}

/** OSM raster by default; Azure Maps raster when the server injected a key. */
function mapStyle() {
  const key = window.NABIZ_MAPS_KEY;
  const tiles = key
    ? 'https://atlas.microsoft.com/map/tile?api-version=2024-04-01&tilesetId=microsoft.base.road&zoom={z}&x={x}&y={y}'
      + `&tileSize=256&language=tr-TR&subscription-key=${encodeURIComponent(key)}`
    : 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
  const attribution = key ? '© Microsoft, © TomTom' : '© OpenStreetMap katkıcıları';
  return {
    label: key ? 'Azure Maps' : 'OpenStreetMap',
    style: {
      version: 8,
      sources: { base: { type: 'raster', tiles: [tiles], tileSize: 256, attribution } },
      layers: [{ id: 'wash', type: 'background', paint: { 'background-color': token('--map-wash') } },
        { id: 'base', type: 'raster', source: 'base', paint: rasterPaint() }],
    },
  };
}

const describe = (p) => `${KIND_TR[p.kind] || 'Konum'}: ${p.label || 'Konum'}${p.age ? `, ${p.age}` : ''}`;

/** Hide the panel *and* drop the pins, so a later answer never inherits stale markers. */
function hideMap() {
  markers.forEach((m) => m.remove());
  markers = [];
  points = [];
  $('#map-panel').hidden = true;
}

function drawLegend() {
  const kinds = [...new Set(points.map((p) => p.kind || 'place'))];
  $('#map-legend').innerHTML = kinds.map((k) => `<li><span class="map-swatch" data-kind="${esc(k)}"></span>${esc(KIND_TR[k] || k)}</li>`).join('');
}

/** The list that replaces the map; every row keeps its value and its age. */
function drawFallback() {
  $('#map').hidden = true;
  $('#map-fallback').hidden = false;
  $('#map-fallback p').innerHTML = off
    ? `${icon('list-details')} Harita kapalı. Konumlar liste olarak gösteriliyor.`
    : `${icon('map-off')} Harita yüklenemedi. Konumlar liste olarak gösteriliyor.`;
  $('#map-fallback-list').innerHTML = points.map((p) => {
    const url = `https://www.openstreetmap.org/?mlat=${p.lat}&mlon=${p.lon}#map=16/${p.lat}/${p.lon}`;
    return `<li><span class="map-swatch" data-kind="${esc(p.kind || 'place')}"></span> `
      + `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(describe(p))}</a></li>`;
  }).join('');
  $('#map-source').textContent = 'liste görünümü';
  document.body.dataset.map = 'off'; // the rows' "Haritada göster" has nothing to show
}

/** Points within MERGE_PX of each other on screen become one marker. */
function groups() {
  const found = [];
  points.forEach((p) => {
    const at = map.project([p.lon, p.lat]);
    const near = found.find((g) => Math.hypot(g.at.x - at.x, g.at.y - at.y) < MERGE_PX);
    if (near) near.points.push(p);
    else found.push({ at, points: [p] });
  });
  return found;
}

function placeMarkers() {
  markers.forEach((m) => m.remove());
  markers = groups().map(({ points: group }) => {
    const [first] = group;
    const el = document.createElement('button');
    el.type = 'button';
    el.className = 'marker';
    el.dataset.kind = first.kind || 'place';
    el.dataset.cards = group.map((p) => p.card).join(' ');
    el.classList.toggle('is-active', group.some((p) => p.card === active));
    el.innerHTML = group.length > 1 ? `<b>${group.length}</b>` : icon(first.icon || KIND_ICONS[first.kind] || 'map-pin');
    const text = group.length > 1 ? `${group.length} konum: ${group.map(describe).join('; ')}` : describe(first);
    const marker = new window.maplibregl.Marker({ element: el }).setLngLat([first.lon, first.lat])
      .setPopup(new window.maplibregl.Popup({ offset: 18, closeButton: false }).setText(text))
      .addTo(map);
    el.setAttribute('aria-label', text); // after addTo, or MapLibre 4.7.1 writes "Map marker"
    return marker;
  });
}

function bounds(list) {
  return list.reduce((b, p) => b.extend([p.lon, p.lat]), new window.maplibregl.LngLatBounds([list[0].lon, list[0].lat], [list[0].lon, list[0].lat]));
}

/** A marker press focuses its row; a merged one zooms in until its places separate. */
function onMarker(event) {
  const el = event.target.closest('.marker');
  if (!el) return;
  const ids = el.dataset.cards.split(' ');
  if (ids.length === 1 || map.getZoom() >= CLOSE_ZOOM) { focusCard(ids[0]); return; }
  map.fitBounds(bounds(points.filter((p) => ids.includes(p.card))), { padding: 64, maxZoom: CLOSE_ZOOM + 2, duration: 0 });
}

function create() {
  const chosen = mapStyle();
  map = new window.maplibregl.Map({
    container: 'map', style: chosen.style, center: [points[0].lon, points[0].lat], zoom: 12,
    attributionControl: { compact: true }, locale: MAP_LOCALE,
  });
  map.addControl(new window.maplibregl.NavigationControl({ showCompass: false }), 'top-right');
  map.on('zoomend', placeMarkers);
  map.on('error', (event) => {
    if (event.sourceId === 'base') $('#map-source').textContent = 'Harita karoları yüklenemedi.';
  });
  $('#map').addEventListener('click', onMarker);
  new MutationObserver(repaint).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', repaint);
  $('#map-source').textContent = `${chosen.label}, yalnızca görselleştirme`;
  $('#map-attribution').textContent = `Harita: ${chosen.label}`;
}

function draw() {
  try {
    if (!map) create();
    map.fitBounds(bounds(points), { padding: 48, maxZoom: 15, duration: 0 });
    placeMarkers();
  } catch (err) {
    // A broken map must never take the answer with it.
    window.NABIZ_MAP_BLOCKED = true;
    drawFallback();
    console.warn('harita devre dışı:', err);
  }
}

function showOnMap(list) {
  points = (list || []).filter((p) => Number.isFinite(p.lat) && Number.isFinite(p.lon));
  active = null;
  if (points.length) refresh();
  else hideMap();
}

/** The panel for the current points: collapsed on a phone, the list, or the map. */
function refresh() {
  const mine = points;
  const panel = $('#map-panel');
  panel.hidden = false;
  drawLegend();
  // On a phone the map waits behind one button; MapLibre loads only when it is pressed.
  const collapsed = available() && !wide.matches && !opened;
  $('#map-open').hidden = !collapsed;
  panel.querySelector('.map-frame').hidden = collapsed;
  $('#map-legend').hidden = collapsed;
  if (collapsed) { $('#map-open span').textContent = `Haritada göster (${points.length} konum)`; return; }
  if (!available()) { drawFallback(); return; }
  if (!window.maplibregl) {
    // The frame shows its flat wash meanwhile; a newer answer's points win over these.
    loadMapLibre().then(() => {
      if (!window.maplibregl) window.NABIZ_MAP_BLOCKED = true;
      if (points === mine) refresh();
    });
    return;
  }
  draw();
}

/** A press on a marker opens the matching row: open its disclosure, ring it, focus it. */
function focusCard(id) {
  document.querySelectorAll('.card.is-focused').forEach((c) => c.classList.remove('is-focused'));
  const el = document.getElementById(id);
  if (!el) return;
  const fold = el.closest('details');
  if (fold) fold.open = true;
  el.classList.add('is-focused');
  scrollToElement(el, 'center');
  el.focus({ preventScroll: true });
}

/** The inverse: a row lifts its marker (merged or not) and the map moves to it. */
function highlightMarker(id) {
  active = id;
  markers.forEach((m) => m.getElement().classList.toggle('is-active', m.getElement().dataset.cards.split(' ').includes(id)));
  const p = points.find((q) => q.card === id);
  if (p && map) easeMap(map, { center: [p.lon, p.lat], duration: 400 });
}

/** "Haritada göster": on a phone it opens the map first and brings it into view. */
function showMarker(id) {
  active = id;
  if (!wide.matches) {
    opened = true;
    refresh();
    scrollToElement($('#map-panel'), 'start');
  }
  if (map) highlightMarker(id);
}

/** ?nomap=1 takes the "CDN is blocked" path on purpose, with its own sentence. */
function initMap(forcedOff) {
  off = forcedOff;
  if (off) document.body.dataset.map = 'off';
  $('#map-open').addEventListener('click', () => { opened = true; refresh(); });
}

export { initMap, preloadMapLibre, hideMap, showOnMap, highlightMarker, showMarker };
