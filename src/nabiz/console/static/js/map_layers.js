/* Each map marker keeps a matching text row for readers and keyboard users. */
const SHOW_ON_MAP_EVENT = 'nabiz:show-on-map';
const KINDS = new Set(['place', 'station', 'park', 'bus', 'air']);
const DEFAULT_LAYERS = ['stations', 'lifts'];
const UNREAD_NOTE = 'Asansör kaydı yok: Metro İstanbul ekipman kaydı okunamadı, asansör durumu doğrulanamadı.';
function validCoordinate(point) {
  return Boolean(point) && Number.isFinite(point.lat) && point.lat >= -90 && point.lat <= 90
    && Number.isFinite(point.lon) && point.lon >= -180 && point.lon <= 180;
}

function validDetail(detail) {
  const value = detail && typeof detail === 'object' ? detail : {};
  const points = (Array.isArray(value.points) ? value.points : []).slice(0, 20).map((point, index) => {
    if (!validCoordinate(point) || typeof point.label !== 'string') return null;
    return {
      lat: point.lat, lon: point.lon, label: point.label.slice(0, 80) || 'Konum',
      kind: KINDS.has(point.kind) ? point.kind : 'place',
      card: typeof point.card === 'string' && /^[\w-]{1,64}$/.test(point.card) ? point.card : 'ml-point-' + index,
    };
  }).filter(Boolean);
  const requested = Array.isArray(value.layers) ? value.layers.filter((item) => DEFAULT_LAYERS.includes(item)) : [];
  const layers = new Set(requested.length ? requested : DEFAULT_LAYERS);
  const focus = validCoordinate(value.focus) ? { lat: value.focus.lat, lon: value.focus.lon } : null;
  const source = typeof value.source === 'string' && value.source ? value.source.slice(0, 16) : 'event';
  return { points, layers, focus, source };
}

function distanceM(a, b) {
  const rad = (degrees) => degrees * Math.PI / 180;
  const lat1 = rad(a.lat), lat2 = rad(b.lat), dLat = lat2 - lat1, dLon = rad(b.lon - a.lon);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return Math.round(6371000 * 2 * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h)));
}
function nearestFirst(features, focus) {
  if (!validCoordinate(focus)) return [...features];
  return features.map((feature, index) => ({
    feature, index, distance: distanceM(
      { lat: feature.geometry.coordinates[1], lon: feature.geometry.coordinates[0] }, focus,
    ),
  })).sort((a, b) => a.distance - b.distance || a.index - b.index).map((row) => row.feature);
}

function rowText(feature, { ageLabel = '', distance = null } = {}) {
  const p = feature && feature.properties ? feature.properties : {};
  if (p.kind === 'lift') return (p.text || '') + (p.placed === false ? ' · Haritada yeri bulunamadı' : '');
  const parts = [p.name || ''];
  if (Number.isFinite(distance)) {
    const metres = Math.max(0, Math.round(distance));
    parts.push(metres > 1000 ? (metres / 1000).toFixed(1).replace('.', ',') + ' km' : metres + ' m');
  }
  if (p.lift_record !== 'unread') {
    if (p.text) parts.push(p.text);
    if (ageLabel) parts.push(ageLabel);
  }
  return parts.join(' · ');
}

function rowsOf(value) {
  return Array.isArray(value) ? value : value && Array.isArray(value.features) ? value.features : [];
}
function coordinates(feature) {
  const pair = feature && feature.geometry && feature.geometry.coordinates;
  return Array.isArray(pair) && pair.length === 2 && pair.every(Number.isFinite)
    ? { lon: pair[0], lat: pair[1] } : null;
}
function featurePoint(feature, card, p = {}) {
  const position = coordinates(feature);
  return position
    ? { lat: position.lat, lon: position.lon, kind: 'station', label: p.name || p.station || 'İstasyon', card }
    : null;
}

function featuresToPoints(stations, lifts, { layers = DEFAULT_LAYERS, focus = null, near = 8, extra = [] } = {}) {
  const enabled = new Set(layers instanceof Set ? layers : layers || DEFAULT_LAYERS);
  const stationFeatures = rowsOf(stations), liftsByStation = new Map();
  rowsOf(lifts).forEach((feature) => {
    const p = feature.properties || {};
    if (p.placed && !liftsByStation.has(p.station)) liftsByStation.set(p.station, feature);
  });
  let selected = stationFeatures.filter((feature) => {
    const status = (feature.properties || {}).lift_record;
    return enabled.has('stations') || (enabled.has('lifts') && status === 'recorded_fault');
  });
  if (validCoordinate(focus)) selected = nearestFirst(selected, focus).slice(0, Math.max(0, near));
  const points = selected.map((feature) => {
    const p = feature.properties || {};
    const broken = enabled.has('lifts') && p.lift_record === 'recorded_fault';
    const lift = liftsByStation.get(p.name);
    const point = featurePoint(feature, broken && lift ? 'ml-' + lift.id : 'ml-' + feature.id, p);
    if (point && broken) point.broken = true;
    return point;
  }).filter(Boolean);
  return [...extra, ...points];
}

function withCard(points, card, stations, lifts, { layers = DEFAULT_LAYERS, ageLabel = '' } = {}) {
  if (points.some((point) => point.card === card)) return points;
  const station = rowsOf(stations).find((feature) => 'ml-' + feature.id === card);
  if (station) {
    const p = station.properties || {}, point = featurePoint(station, card, p);
    if (!point) return points;
    if (p.lift_record === 'recorded_fault' && new Set(layers).has('lifts')) {
      point.broken = true;
      point.age = ageLabel;
    }
    return [...points, point];
  }
  const lift = rowsOf(lifts).find((feature) => 'ml-' + feature.id === card), p = lift && lift.properties;
  if (!lift || !p || p.placed !== true) return points;
  const point = featurePoint(lift, card, p);
  if (!point) return points;
  point.label = p.station || point.label;
  if (p.status) point.broken = true;
  point.age = ageLabel;
  return [...points, point];
}

function stationRows(features, focus) {
  return validCoordinate(focus) ? nearestFirst(features, focus) : [...features];
}

function mountMapLayers(doc) {
  if (!doc) return;
  const ready = doc.readyState === 'loading'
    ? new Promise((resolve) => doc.addEventListener('DOMContentLoaded', resolve, { once: true }))
    : Promise.resolve();
  ready.then(async () => {
    const [mapApi, api, provenance, icons] = await Promise.all([
      import('./map.js'), import('./api.js'), import('./provenance.js'), import('./icons.js'),
    ]);
    mapApi.initMap();
    const mapSection = doc.getElementById('harita');
    if (!mapSection || doc.getElementById('harita-katmanlari')) return;
    if (!doc.querySelector('link[data-map-layers-styles]')) {
      const link = doc.createElement('link');
      link.rel = 'stylesheet'; link.href = '/css/map_layers.css'; link.dataset.mapLayersStyles = '';
      doc.head.append(link);
    }
    const template = doc.createElement('template');
    template.innerHTML = '<section id="harita-katmanlari" aria-labelledby="map-layers-title">'
      + '<div class="section-head"><h2 id="map-layers-title" tabindex="-1">Raylı sistem istasyonları ve asansör kayıtları</h2></div>'
      + '<p class="map-layers-intro">Metro, tramvay ve füniküler istasyonları. Asansör bilgisi Metro İstanbul\'un arıza kaydından gelir. Kayıtta olmayan bir asansörün kullanılabilir olduğu doğrulanmış değildir.</p>'
      + '<div class="map-layers-actions"><button type="button" class="btn btn-primary" id="map-layers-show"><span>Haritada göster</span></button>'
      + '<fieldset class="map-layers-toggles"><legend>Katmanlar</legend>'
      + '<label><input type="checkbox" id="map-layers-stations-toggle" checked> İstasyonlar</label>'
      + '<label><input type="checkbox" id="map-layers-lifts-toggle" checked> Asansör kayıtları</label></fieldset></div>'
      + '<p class="status-line" id="map-layers-status" role="status"></p><div id="map-layers-lists" hidden>'
      + '<h3 id="map-layers-lifts-title">Asansör kayıtları</h3><ol id="map-layers-lifts" class="map-layers-list" aria-labelledby="map-layers-lifts-title"></ol>'
      + '<h3 id="map-layers-stations-title">İstasyonlar</h3><ol id="map-layers-stations" class="map-layers-list" aria-labelledby="map-layers-stations-title"></ol>'
      + '<details id="map-layers-more"><summary></summary><ol id="map-layers-stations-more" class="map-layers-list" start="21"></ol></details>'
      + '<p class="map-layers-foot"></p></div></section>';
    const section = template.content.firstElementChild;
    section.querySelector('#map-layers-show').insertAdjacentHTML('afterbegin', icons.icon('map-pin'));
    mapSection.after(section);
    const $ = (selector) => section.querySelector(selector);
    const status = $('#map-layers-status'), listWrap = $('#map-layers-lists');
    const liftsList = $('#map-layers-lifts'), stationsList = $('#map-layers-stations');
    const moreDetails = $('#map-layers-more'), moreList = $('#map-layers-stations-more');
    const liftsTitle = $('#map-layers-lifts-title'), stationsTitle = $('#map-layers-stations-title');
    const stationsToggle = $('#map-layers-stations-toggle'), liftsToggle = $('#map-layers-lifts-toggle');
    const foot = $('.map-layers-foot');
    let currentStations = null, currentLifts = null, currentPoints = [];
    let currentDetail = validDetail({ source: 'button' }), cachedAt = 0, cachedValue = null, requestNumber = 0;

    function activeLayers() {
      return [stationsToggle.checked && 'stations', liftsToggle.checked && 'lifts'].filter(Boolean);
    }
    function addEmpty(list, message, className) {
      const item = doc.createElement('li');
      item.className = className; item.textContent = message; list.append(item);
    }
    function addRows(list, features, options, prefix) {
      features.forEach((feature) => {
        const item = doc.createElement('li'), button = doc.createElement('button');
        const card = prefix + feature.id, p = feature.properties || {};
        button.type = 'button'; button.className = 'map-layers-row'; button.dataset.card = card;
        button.textContent = rowText(feature, options(feature));
        item.id = card; item.className = 'map-layers-item';
        if (p.lift_record === 'recorded_fault' || p.status) item.classList.add('is-fault');
        if (p.placed === false) item.classList.add('is-unplaced');
        item.append(button); list.append(item);
      });
    }
    function render() {
      if (!currentStations || !currentLifts) return;
      const layers = activeLayers();
      currentDetail = { ...currentDetail, layers: new Set(layers) };
      const age = currentLifts.lift_record === 'read' ? provenance.ageText(currentLifts.provenance) : '';
      currentPoints = featuresToPoints(currentStations, currentLifts, {
        layers: currentDetail.layers, focus: currentDetail.focus, near: 8, extra: currentDetail.points,
      });
      currentPoints.forEach((point) => { if (point.broken) point.age = age; });
      if (currentPoints.length) mapApi.showOnMap(currentPoints);
      else if (!layers.length) mapApi.showOnMap([]);
      else mapApi.hideMap();
      listWrap.hidden = false;
      liftsTitle.hidden = !layers.includes('lifts'); liftsList.hidden = !layers.includes('lifts');
      stationsTitle.hidden = !layers.includes('stations'); stationsList.hidden = !layers.includes('stations');
      const ordered = stationRows(currentStations.features, currentDetail.focus);
      moreDetails.hidden = !layers.includes('stations') || ordered.length <= 20;
      liftsList.replaceChildren(); stationsList.replaceChildren(); moreList.replaceChildren();
      if (currentLifts.note && currentLifts.features.length) addEmpty(liftsList, currentLifts.note, 'map-layers-note');
      if (currentLifts.features.length) addRows(liftsList, currentLifts.features, () => ({}), 'ml-');
      else addEmpty(liftsList, currentLifts.note || 'Asansör kaydı yok.', 'map-layers-empty');
      const distanceOptions = (feature) => ({
        ageLabel: age,
        distance: validCoordinate(currentDetail.focus) ? distanceM(
          { lat: feature.geometry.coordinates[1], lon: feature.geometry.coordinates[0] }, currentDetail.focus,
        ) : null,
      });
      addRows(stationsList, ordered.slice(0, 20), distanceOptions, 'ml-');
      addRows(moreList, ordered.slice(20), distanceOptions, 'ml-');
      $('summary').textContent = 'Tüm istasyonlar (' + currentStations.count + ')';
      foot.textContent = currentLifts.disclaimer || 'Resmî İBB hizmeti değildir. Konumunuz yalnız bu cihazda kullanılır.';
      const count = currentPoints.filter((point) => point.kind === 'station').length;
      if (currentDetail.focus) {
        status.textContent = 'Size en yakın ' + count + ' istasyon haritada; liste mesafeye göre sıralı.'
          + (currentLifts.lift_record === 'unread' ? ' Asansör kaydı okunamadı; asansör durumu doğrulanamadı.' : '');
      } else if (currentLifts.lift_record === 'unread') {
        status.textContent = count + ' istasyon haritada. Asansör kaydı okunamadı; asansör durumu doğrulanamadı.';
      } else status.textContent = count + ' istasyon haritada. Asansör kaydı: ' + currentLifts.count + ' kayıt · ' + age + '.';
      status.classList.remove('is-bad');
    }
    async function fetchLayers() {
      if (cachedValue && Date.now() - cachedAt < 60000) return cachedValue;
      const stationResult = await api.get('/api/map/stations');
      let liftsResult, liftFailed = false;
      try { liftsResult = await api.get('/api/map/lifts'); }
      catch {
        liftFailed = true;
        liftsResult = {
          count: 0, lift_record: 'unread', features: [], note: UNREAD_NOTE,
          provenance: { source: 'metro_equipment', url: null, observed_at: null, age_s: null, mode: 'unknown' },
          disclaimer: null,
        };
      }
      const stations = liftFailed ? {
        ...stationResult, lift_record: 'unread',
        features: stationResult.features.map((feature) => ({
          ...feature, properties: { ...feature.properties, lift_record: 'unread', text: 'Asansör kaydı okunamadı' },
        })),
      } : stationResult;
      const value = { stations, lifts: liftsResult };
      if (!liftFailed) { cachedAt = Date.now(); cachedValue = value; }
      return value;
    }
    async function show(detail) {
      const sequence = ++requestNumber;
      currentDetail = detail;
      stationsToggle.checked = detail.layers.has('stations'); liftsToggle.checked = detail.layers.has('lifts');
      status.classList.remove('is-bad'); status.textContent = 'Harita katmanları yükleniyor.';
      try {
        const value = await fetchLayers();
        if (sequence !== requestNumber) return;
        currentStations = value.stations; currentLifts = value.lifts; render();
        if (detail.source !== 'button') {
          section.scrollIntoView({ block: 'start' });
          $('#map-layers-title').focus({ preventScroll: true });
        }
      } catch {
        if (sequence !== requestNumber) return;
        mapApi.hideMap(); listWrap.hidden = true; status.classList.add('is-bad');
        status.textContent = 'Harita katmanları yüklenemedi.';
      }
    }
    section.addEventListener('click', (event) => {
      const button = event.target.closest('.map-layers-row');
      if (!button) return;
      const card = button.dataset.card;
      const next = withCard(currentPoints, card, currentStations, currentLifts, {
        layers: currentDetail.layers,
        ageLabel: currentLifts.lift_record === 'read' ? provenance.ageText(currentLifts.provenance) : '',
      });
      if (next !== currentPoints) { currentPoints = next; mapApi.showOnMap(next); }
      mapApi.highlightMarker(card);
    });
    section.addEventListener('keydown', (event) => {
      if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
      const buttons = [...section.querySelectorAll('.map-layers-row')].filter((button) => (
        !button.closest('[hidden]') && (!button.closest('details') || button.closest('details').open)
      ));
      const current = buttons.indexOf(event.target);
      if (current < 0) return;
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1
        : Math.max(0, Math.min(buttons.length - 1, current + (event.key === 'ArrowDown' ? 1 : -1)));
      event.preventDefault(); buttons[next].focus();
    });
    $('#map-layers-show').addEventListener('click', () => show(validDetail({ source: 'button', layers: activeLayers() })));
    [stationsToggle, liftsToggle].forEach((toggle) => toggle.addEventListener('change', () => {
      currentDetail = { ...currentDetail, layers: new Set(activeLayers()) }; render();
    }));
    doc.addEventListener(SHOW_ON_MAP_EVENT, (event) => show(validDetail(event.detail)));
  });
}

if (typeof document !== 'undefined') mountMapLayers(document);
export {
  SHOW_ON_MAP_EVENT, validDetail, distanceM, nearestFirst, rowText,
  featuresToPoints, withCard, mountMapLayers,
};
