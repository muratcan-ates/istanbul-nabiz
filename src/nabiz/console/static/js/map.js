/* The map stays dormant until a visitor asks for their location. Location data remains in this
 * browser, and every map point keeps a matching text row for readers and for offline use. */

import { icon } from './icons.js';

const $ = (selector) => document.querySelector(selector);
const KINDS = new Set(['place', 'station', 'park', 'bus', 'air']);
const KIND_LABELS = {
  place: 'Yer',
  station: 'İstasyon, durak',
  park: 'Otopark',
  bus: 'Otobüs',
  air: 'Hava ölçüm istasyonu',
};
const MERGE_PX = 24;
const CLOSE_ZOOM = 16;
const LEAFLET_VERSION = '1.9.4';

let section = null;
let mapElement = null;
let listElement = null;
let statusElement = null;
let locateButton = null;
let leafletLoad = null;
let map = null;
let baseModule = null;
let markers = [];
let points = [];
let themeObserver = null;
let darkModeQuery = null;
const stylesheetLoads = new Map();

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

/* The base map is drawn in this browser (js/map_base.js), imported only once a map opens. */
function loadLeaflet() {
  leafletLoad = leafletLoad || Promise.all([
    loadStylesheet('/vendor/leaflet/leaflet.css'),
    loadStylesheet('/css/map.css'),
    loadStylesheet('/css/map_base.css'),
    loadScript(),
    import('./map_base.js').then((module) => { baseModule = module; }),
  ]);
  return leafletLoad;
}

/* One adapter owns the base layer so a later source change stays in one place. Nothing is fetched. */
function baseSource() {
  return baseModule.mockBase(window.L, map);
}

function description(point) {
  const kind = KIND_LABELS[point.kind] || KIND_LABELS.place;
  const age = typeof point.age === 'string' && point.age ? `, ${point.age}` : '';
  const broken = point.broken ? ', arıza bildirimi var' : '';
  return `${kind}: ${point.label}${age}${broken}`;
}

function pointIcon(kind) {
  if (kind === 'park') return icon('parking');
  if (kind === 'bus') return icon('bus');
  if (kind === 'station') return icon('train');
  if (kind === 'air') return icon('wind');
  return icon('map-pin');
}

function makeListRow(point) {
  const row = document.createElement('li');
  row.className = 'map-point-row';
  if (point.broken) row.classList.add('is-broken');
  const label = document.createElement('span');
  label.textContent = description(point);
  row.append(label);
  return row;
}

function drawPointList(failureText = '') {
  listElement.replaceChildren();
  if (points.length) {
    points.forEach((point) => listElement.append(makeListRow(point)));
  } else if (failureText) {
    const row = document.createElement('li');
    row.className = 'map-point-row';
    row.textContent = failureText;
    listElement.append(row);
  }
}

function removeMap() {
  if (themeObserver) themeObserver.disconnect();
  themeObserver = null;
  if (darkModeQuery) darkModeQuery.removeEventListener?.('change', applyTheme);
  darkModeQuery = null;
  if (map) map.remove();
  map = null;
  markers = [];
}

function showFallback(message, failureText = '') {
  removeMap();
  mapElement.hidden = true;
  listElement.hidden = false;
  listElement.classList.remove('sr-only');
  drawPointList(failureText);
  statusElement.textContent = message;
  statusElement.classList.add('is-bad');
}

function applyTheme() {
  if (!mapElement) return;
  const chosen = document.documentElement.dataset.theme;
  const dark = chosen ? chosen === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches;
  mapElement.classList.toggle('is-dark', dark);
}

function watchTheme() {
  applyTheme();
  themeObserver = new MutationObserver(applyTheme);
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
  darkModeQuery = window.matchMedia('(prefers-color-scheme: dark)');
  darkModeQuery.addEventListener?.('change', applyTheme);
}

function groupedPoints() {
  const groups = [];
  points.forEach((point) => {
    const position = map.latLngToContainerPoint([point.lat, point.lon]);
    const nearby = groups.find((group) => Math.hypot(group.position.x - position.x, group.position.y - position.y) < MERGE_PX);
    if (nearby) nearby.points.push(point);
    else groups.push({ position, points: [point] });
  });
  return groups;
}

function popupContent(group) {
  const list = document.createElement('ul');
  group.forEach((point) => {
    const row = document.createElement('li');
    row.textContent = description(point);
    list.append(row);
  });
  return list;
}

function focusPoint(point) {
  const card = point.card && document.getElementById(point.card);
  if (!card) return;
  const disclosure = card.closest('details');
  if (disclosure) disclosure.open = true;
  if (!card.hasAttribute('tabindex')) card.setAttribute('tabindex', '-1');
  card.focus({ preventScroll: true });
}

function activateGroup(group) {
  if (group.length > 1 && map.getZoom() < CLOSE_ZOOM) {
    map.fitBounds(group.map((point) => [point.lat, point.lon]), { padding: [48, 48], maxZoom: CLOSE_ZOOM + 2 });
    return;
  }
  focusPoint(group[0]);
}

function makeMarker(group) {
  const first = group[0];
  const ids = group.map((point) => point.card);
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'map-marker-button';
  button.dataset.kind = first.kind;
  button.dataset.cards = ids.join(' ');
  button.setAttribute('aria-label', group.map(description).join('; '));
  if (group.length > 1) {
    button.classList.add('is-group');
    button.textContent = String(group.length);
  } else {
    button.innerHTML = pointIcon(first.kind);
  }
  if (group.some((point) => point.broken)) button.classList.add('is-broken');
  button.addEventListener('click', () => activateGroup(group));
  const markerIcon = window.L.divIcon({
    className: 'map-marker-wrap',
    html: button,
    iconSize: [44, 44],
    iconAnchor: [22, 22],
  });
  const marker = window.L.marker([first.lat, first.lon], { icon: markerIcon, keyboard: false, riseOnHover: true });
  marker.bindPopup(popupContent(group));
  marker.addTo(map);
  marker._nabizCards = ids;
  marker._nabizButton = button;
  return marker;
}

function drawMarkers() {
  markers.forEach((marker) => marker.remove());
  markers = groupedPoints().map(({ points: group }) => makeMarker(group));
}

/* One point opens close; several open framed together, so a first look shows the city, not one street.
 * The base is vector, not tiles, so the quarter-step zoom (zoomSnap) that frames them tightly stays sharp. */
function fitPoints() {
  if (points.length === 1) map.setView([points[0].lat, points[0].lon], 15);
  else map.fitBounds(points.map((point) => [point.lat, point.lon]), { padding: [48, 48], maxZoom: 15 });
}

function createMap() {
  map = window.L.map(mapElement, { zoomControl: true, attributionControl: true, keyboard: true, zoomSnap: 0.25 });
  fitPoints();
  baseSource().addTo(map);
  map.on('zoomend moveend', drawMarkers);
  watchTheme();
  drawMarkers();
}

function validPoint(point) {
  return point && typeof point.lat === 'number' && Number.isFinite(point.lat) && point.lat >= -90 && point.lat <= 90
    && typeof point.lon === 'number' && Number.isFinite(point.lon) && point.lon >= -180 && point.lon <= 180
    && typeof point.label === 'string' && typeof point.card === 'string';
}

function showOnMap(list) {
  if (!section) initMap();
  if (!section) return;
  points = Array.isArray(list)
    ? list.filter(validPoint).map((point) => ({
      ...point,
      kind: KINDS.has(point.kind) ? point.kind : 'place',
      label: point.label || 'Konum',
    }))
    : [];
  if (!points.length) {
    hideMap();
    return;
  }
  section.hidden = false;
  mapElement.hidden = false;
  listElement.hidden = false;
  listElement.classList.add('sr-only');
  statusElement.classList.remove('is-bad');
  statusElement.textContent = 'Konumlar haritada gösteriliyor.';
  drawPointList();
  if (map) {
    fitPoints();
    drawMarkers();
    return;
  }
  const requestedPoints = points;
  loadLeaflet().then(() => {
    if (points !== requestedPoints) return;
    createMap();
  }).catch(() => {
    if (points === requestedPoints) showFallback('Harita açılamadı. Konumlar listede gösteriliyor.');
  });
}

function hideMap() {
  points = [];
  removeMap();
  if (!section) return;
  section.hidden = true;
  listElement.replaceChildren();
  listElement.classList.add('sr-only');
  statusElement.textContent = '';
}

function highlightMarker(cardId) {
  const marker = markers.find((item) => item._nabizCards.includes(cardId));
  markers.forEach((item) => {
    item._nabizButton.classList.toggle('is-selected', item === marker);
    item.setZIndexOffset(item === marker ? 1000 : 0);
  });
  const point = points.find((item) => item.card === cardId);
  if (point && map) map.panTo([point.lat, point.lon]);
}

function showFailure() {
  points = [];
  showFallback('Konumunuz alınamadı.', 'Konumunuz alınamadı.');
}

function locate() {
  if (!navigator.geolocation) {
    showFailure();
    return;
  }
  locateButton.disabled = true;
  statusElement.classList.remove('is-bad');
  statusElement.textContent = 'Tarayıcı konum izni bekleniyor.';
  const received = (position) => {
    locateButton.disabled = false;
    showOnMap([{
      lat: position.coords.latitude,
      lon: position.coords.longitude,
      kind: 'place',
      label: 'Konumum',
      card: 'me',
    }]);
  };
  const failed = () => {
    locateButton.disabled = false;
    showFailure();
  };
  try {
    navigator.geolocation.getCurrentPosition(received, failed, {
      enableHighAccuracy: false,
      maximumAge: 60000,
      timeout: 10000,
    });
  } catch {
    failed();
  }
}

function initMap() {
  if (section) return;
  const cards = $('#cards');
  if (!cards) return;
  section = document.createElement('section');
  section.id = 'harita';
  section.setAttribute('aria-labelledby', 'map-title');
  section.innerHTML = `<div class="section-head"><h2 id="map-title">${icon('map')} Harita</h2>
    <span class="section-note">İzin isteğe bağlıdır.</span></div>
    <p class="map-intro">Konumunuz tarayıcıda işlenir. Harita örnek bir altlıktır ve cihazınızda çizilir; dış harita sunucusuna istek gitmez.</p>
    <div class="map-actions">
      <button type="button" class="btn btn-primary" id="map-locate">
        ${icon('map-pin')}<span>Haritada konumum</span>
      </button>
    </div>
    <p class="status-line" id="map-status" role="status"></p>
    <div id="map" class="map-frame" role="region" aria-label="Konum haritası"
      aria-describedby="map-status" tabindex="0" hidden></div>
    <ul id="map-fallback-list" class="map-point-list sr-only" aria-label="Haritadaki konumlar"></ul>`;
  const cardsSection = cards.closest('section');
  cardsSection.after(section);
  mapElement = $('#map');
  listElement = $('#map-fallback-list');
  statusElement = $('#map-status');
  locateButton = $('#map-locate');
  locateButton.addEventListener('click', locate);
  loadStylesheet('/css/map.css').catch(() => {});
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initMap, { once: true });
else initMap();

export { initMap, showOnMap, highlightMarker, hideMap };
