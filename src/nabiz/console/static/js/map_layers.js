/* Each map marker keeps a matching text row for readers and keyboard users. */
const SHOW_ON_MAP_EVENT = 'nabiz:show-on-map';
const KINDS = new Set(['place', 'station', 'park', 'bus', 'air']);
const DEFAULT_LAYERS = ['stations', 'lifts'];
const UNREAD_NOTE = 'Asansör kaydı yok: Metro İstanbul ekipman kaydı okunamadı, asansör durumu doğrulanamadı.';
const EQUIPMENT_TYPES = { escalators: 'escalator', walkways: 'moving_walkway' };
const EQUIPMENT_LABELS = { escalator: 'yürüyen merdiven', moving_walkway: 'yürüyen bant' };
let mapEquipment = null;
function validCoordinate(point) {
  return Boolean(point) && Number.isFinite(point.lat) && point.lat >= -90 && point.lat <= 90 && Number.isFinite(point.lon)
    && point.lon >= -180 && point.lon <= 180;
}

function validDetail(detail) {
  const value = detail && typeof detail === 'object' ? detail : {};
  const points = (Array.isArray(value.points) ? value.points : []).slice(0, 20).map((point, index) => (
    !validCoordinate(point) || typeof point.label !== 'string' ? null : {
      lat: point.lat, lon: point.lon, label: point.label.slice(0, 80) || 'Konum', kind: KINDS.has(point.kind) ? point.kind : 'place',
      card: typeof point.card === 'string' && /^[\w-]{1,64}$/.test(point.card) ? point.card : 'ml-point-' + index,
    }
  )).filter(Boolean);
  const allLayers = [...DEFAULT_LAYERS, 'escalators', 'walkways'];
  const requested = Array.isArray(value.layers) ? value.layers.filter((item) => allLayers.includes(item)) : [];
  const layers = new Set(requested.length ? requested : DEFAULT_LAYERS);
  return { points, layers, focus: validCoordinate(value.focus) ? { lat: value.focus.lat, lon: value.focus.lon } : null,
    source: typeof value.source === 'string' && value.source ? value.source.slice(0, 16) : 'event' };
}

function distanceM(a, b) {
  const rad = (degrees) => degrees * Math.PI / 180, lat1 = rad(a.lat), lat2 = rad(b.lat);
  const dLat = lat2 - lat1, dLon = rad(b.lon - a.lon), h = Math.sin(dLat / 2) ** 2
    + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return Math.round(6371000 * 2 * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h)));
}
function nearestFirst(features, focus) {
  if (!validCoordinate(focus)) return [...features];
  return features.map((feature, index) => ({ feature, index,
    distance: distanceM({ lat: feature.geometry.coordinates[1], lon: feature.geometry.coordinates[0] }, focus),
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
    if (p.text) parts.push(p.text); if (ageLabel) parts.push(ageLabel);
  }
  return parts.join(' · ');
}

function rowsOf(value) { return Array.isArray(value) ? value : value && Array.isArray(value.features) ? value.features : []; }
function coordinates(feature) {
  const pair = feature && feature.geometry && feature.geometry.coordinates;
  return Array.isArray(pair) && pair.length === 2 && pair.every(Number.isFinite) ? { lon: pair[0], lat: pair[1] } : null;
}
function featurePoint(feature, card, p = {}) {
  const position = coordinates(feature);
  return position ? { lat: position.lat, lon: position.lon, kind: 'station', label: p.name || p.station || 'İstasyon', card } : null;
}

function featuresToPoints(
  stations, lifts, { layers = DEFAULT_LAYERS, focus = null, near = 8, extra = [], equipment = null } = {},
) {
  const enabled = new Set(layers instanceof Set ? layers : layers || DEFAULT_LAYERS);
  const stationFeatures = rowsOf(stations), typesByStation = new Map(), equipmentByStation = new Map();
  rowsOf(equipment).forEach((feature) => {
    const p = feature.properties || {}, layer = Object.keys(EQUIPMENT_TYPES).find((key) => EQUIPMENT_TYPES[key] === p.equipment_type);
    if (!layer || !enabled.has(layer) || p.placed !== true || !p.station) return;
    if (!typesByStation.has(p.station)) typesByStation.set(p.station, new Set());
    typesByStation.get(p.station).add(p.equipment_type);
    if (!equipmentByStation.has(p.station)) equipmentByStation.set(p.station, feature);
  });
  const liftsByStation = rowsOf(lifts).reduce((map, feature) => {
    const { station, placed } = feature.properties || {};
    if (placed && !map.has(station)) map.set(station, feature);
    return map;
  }, new Map());
  let selected = stationFeatures.filter((feature) => {
    const status = (feature.properties || {}).lift_record;
    const name = (feature.properties || {}).name;
    return enabled.has('stations') || (enabled.has('lifts') && status === 'recorded_fault') || typesByStation.has(name);
  });
  if (validCoordinate(focus)) selected = nearestFirst(selected, focus).slice(0, Math.max(0, near));
  return [...extra, ...selected.map((feature) => {
    const p = feature.properties || {}, name = p.name;
    const broken = enabled.has('lifts') && p.lift_record === 'recorded_fault';
    const lift = liftsByStation.get(name), equipmentFeature = equipmentByStation.get(name);
    const card = broken && lift ? 'ml-' + lift.id
      : !broken && equipmentFeature ? 'ml-' + equipmentFeature.id : 'ml-' + feature.id;
    const point = featurePoint(feature, card, p);
    const types = typesByStation.get(name);
    if (point && !broken && types && types.size) {
      const label = types.size > 1 ? 'yürüyen merdiven ve bant' : EQUIPMENT_LABELS[types.values().next().value];
      point.label += ' · ' + label + ' kaydı';
    }
    if (point && broken) point.broken = true;
    return point;
  }).filter(Boolean)];
}

function withCard(points, card, stations, lifts, { layers = DEFAULT_LAYERS, ageLabel = '', equipment = null } = {}) {
  if (points.some((point) => point.card === card)) return points;
  const station = rowsOf(stations).find((feature) => 'ml-' + feature.id === card);
  if (station) {
    const p = station.properties || {}, point = featurePoint(station, card, p);
    if (!point) return points;
    if (p.lift_record === 'recorded_fault' && new Set(layers).has('lifts')) { point.broken = true; point.age = ageLabel; }
    return [...points, point];
  }
  const lift = rowsOf(lifts).find((feature) => 'ml-' + feature.id === card);
  const feature = lift || rowsOf(equipment).find((row) => 'ml-' + row.id === card), p = feature && feature.properties;
  if (!feature || !p || p.placed !== true) return points;
  const point = featurePoint(feature, card, p);
  if (!point) return points;
  point.label = p.station || point.label;
  if (lift && p.status) point.broken = true;
  point.age = ageLabel;
  return [...points, point];
}

function stationRows(features, focus) { return validCoordinate(focus) ? nearestFirst(features, focus) : [...features]; }
function mountMapLayers(doc) {
  if (!doc) return;
  const ready = doc.readyState === 'loading' ? new Promise((resolve) => doc.addEventListener('DOMContentLoaded', resolve, { once: true })) : Promise.resolve();
  ready.then(async () => {
    const [mapApi, api, provenance, icons, equipment] = await Promise.all([
      import('./map.js'), import('./api.js'), import('./provenance.js'), import('./icons.js'), import('./map_equipment.js'),
    ]);
    mapEquipment = equipment;
    mapApi.initMap();
    const mapSection = doc.getElementById('harita');
    if (!mapSection || doc.getElementById('harita-katmanlari')) return;
    if (!doc.querySelector('link[data-map-layers-styles]')) {
      const link = doc.createElement('link');
      link.rel = 'stylesheet'; link.href = '/css/map_layers.css'; link.dataset.mapLayersStyles = '';
      doc.head.append(link);
    }
    const template = doc.createElement('template');
    template.innerHTML = mapEquipment.layersTemplate();
    const section = template.content.firstElementChild;
    section.querySelector('#map-layers-show').insertAdjacentHTML('afterbegin', icons.icon('map-pin'));
    mapSection.after(section);
    const $ = (selector) => section.querySelector(selector);
    const status = $('#map-layers-status'), listWrap = $('#map-layers-lists');
    const liftsList = $('#map-layers-lifts'), stationsList = $('#map-layers-stations'), equipmentList = $('#map-layers-equipment');
    const equipmentOffList = $('#map-layers-equipment-off'), moreDetails = $('#map-layers-more'), moreList = $('#map-layers-stations-more');
    const liftsTitle = $('#map-layers-lifts-title'), stationsTitle = $('#map-layers-stations-title');
    const equipmentTitle = $('#map-layers-equipment-title'), equipmentOffTitle = $('#map-layers-equipment-off-title');
    const stationsToggle = $('#map-layers-stations-toggle'), liftsToggle = $('#map-layers-lifts-toggle');
    const escalatorsToggle = $('#map-layers-escalators-toggle'), walkwaysToggle = $('#map-layers-walkways-toggle');
    const foot = $('.map-layers-foot');
    let currentStations = null, currentLifts = null, currentEquipment = null, currentPoints = [];
    let currentDetail = validDetail({ source: 'button' }), cachedAt = 0, cachedValue = null, requestNumber = 0;
    function activeLayers() { return [stationsToggle.checked && 'stations', liftsToggle.checked && 'lifts', escalatorsToggle.checked && 'escalators', walkwaysToggle.checked && 'walkways'].filter(Boolean); }
    function addEmpty(list, message, className) {
      const item = doc.createElement('li');
      item.className = className; item.textContent = message; list.append(item);
    }
    function addRows(list, features, options, prefix) {
      features.forEach((feature) => {
        const item = doc.createElement('li'), button = doc.createElement('button');
        const card = prefix + feature.id, p = feature.properties || {};
        button.type = 'button'; button.className = 'map-layers-row'; button.dataset.card = card;
        button.textContent = p.kind === 'equipment' ? mapEquipment.equipmentRowText(feature) : rowText(feature, options(feature));
        item.id = card; item.className = 'map-layers-item';
        if (p.lift_record === 'recorded_fault' || p.status) item.classList.add('is-fault');
        if (p.placed === false) item.classList.add('is-unplaced');
        item.append(button); list.append(item);
      });
    }
    function render() {
      if (!currentStations || !currentLifts || !currentEquipment) return;
      const layers = activeLayers();
      currentDetail = { ...currentDetail, layers: new Set(layers) };
      const age = currentLifts.lift_record === 'read' ? provenance.ageText(currentLifts.provenance) : '';
      const equipmentRows = mapEquipment.splitNotOperated(mapEquipment.equipmentFeatures(currentEquipment, layers));
      const equipmentActive = layers.includes('escalators') || layers.includes('walkways');
      currentPoints = featuresToPoints(currentStations, currentLifts, {
        layers: currentDetail.layers, focus: currentDetail.focus, near: 8, extra: currentDetail.points, equipment: currentEquipment,
      });
      currentPoints.forEach((point) => { if (point.broken) point.age = age; });
      if (currentPoints.length || !layers.length) mapApi.showOnMap(currentPoints);
      else mapApi.hideMap();
      listWrap.hidden = false;
      liftsTitle.hidden = liftsList.hidden = !layers.includes('lifts');
      stationsTitle.hidden = stationsList.hidden = !layers.includes('stations');
      equipmentTitle.hidden = !equipmentActive; equipmentList.hidden = !equipmentActive;
      equipmentOffTitle.hidden = !equipmentActive || !equipmentRows.notOperated.length;
      equipmentOffList.hidden = !equipmentActive || !equipmentRows.notOperated.length;
      const ordered = stationRows(currentStations.features, currentDetail.focus);
      moreDetails.hidden = !layers.includes('stations') || ordered.length <= 20;
      [liftsList, equipmentList, equipmentOffList, stationsList, moreList].forEach((list) => list.replaceChildren());
      if (currentLifts.note && currentLifts.features.length) addEmpty(liftsList, currentLifts.note, 'map-layers-note');
      if (currentLifts.features.length) addRows(liftsList, currentLifts.features, () => ({}), 'ml-');
      else addEmpty(liftsList, currentLifts.note || 'Asansör kaydı yok.', 'map-layers-empty');
      if (currentEquipment.note && currentEquipment.features.length) addEmpty(equipmentList, currentEquipment.note, 'map-layers-note');
      if (equipmentRows.active.length) addRows(equipmentList, equipmentRows.active, () => ({}), 'ml-');
      else if (!equipmentRows.notOperated.length) addEmpty(equipmentList, currentEquipment.note || 'Bu başlık altında kayıt yok.', 'map-layers-empty');
      if (equipmentRows.notOperated.length) addRows(equipmentOffList, equipmentRows.notOperated, () => ({}), 'ml-');
      const distanceOptions = (feature) => ({ ageLabel: age, distance: validCoordinate(currentDetail.focus)
        ? distanceM({ lat: feature.geometry.coordinates[1], lon: feature.geometry.coordinates[0] }, currentDetail.focus) : null });
      addRows(stationsList, ordered.slice(0, 20), distanceOptions, 'ml-');
      addRows(moreList, ordered.slice(20), distanceOptions, 'ml-');
      $('summary').textContent = 'Tüm istasyonlar (' + currentStations.count + ')';
      foot.textContent = currentLifts.disclaimer || 'Resmî İBB hizmeti değildir. Konumunuz yalnız bu cihazda kullanılır.';
      const count = currentPoints.filter((point) => point.kind === 'station').length;
      const heading = currentDetail.focus ? 'Size en yakın istasyonlar gösteriliyor; liste mesafeye göre sıralı. ' : '';
      const liftCount = currentLifts.lift_record === 'read' ? 'Asansör kaydı: ' + currentLifts.count
        : 'Asansör kaydı okunamadı; asansör durumu doğrulanamadı';
      status.textContent = currentEquipment.equipment_record === 'unread'
        ? heading + count + ' istasyon haritada. ' + liftCount + ' · ' + currentEquipment.note
        : heading + count + ' istasyon haritada. ' + liftCount
          + ' · Yürüyen merdiven: ' + currentEquipment.counts.escalator + ' · Yürüyen bant: '
          + currentEquipment.counts.moving_walkway + ' · ' + (age || provenance.ageText(currentEquipment.provenance)) + '.';
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
      let equipmentResult, equipmentFailed = false;
      try { equipmentResult = await api.get('/api/map/equipment'); }
      catch { equipmentFailed = true; equipmentResult = mapEquipment.unreadEquipment(); }
      const stations = liftFailed ? {
        ...stationResult, lift_record: 'unread',
        features: stationResult.features.map((feature) => ({
          ...feature, properties: { ...feature.properties, lift_record: 'unread', text: 'Asansör kaydı okunamadı' },
        })),
      } : stationResult;
      const value = { stations, lifts: liftsResult, equipment: equipmentResult };
      if (!liftFailed && !equipmentFailed) { cachedAt = Date.now(); cachedValue = value; }
      return value;
    }
    async function show(detail) {
      const sequence = ++requestNumber;
      currentDetail = detail;
      stationsToggle.checked = detail.layers.has('stations'); liftsToggle.checked = detail.layers.has('lifts');
      escalatorsToggle.checked = detail.layers.has('escalators'); walkwaysToggle.checked = detail.layers.has('walkways');
      status.classList.remove('is-bad'); status.textContent = 'Harita katmanları yükleniyor.';
      try {
        const value = await fetchLayers();
        if (sequence !== requestNumber) return;
        currentStations = value.stations; currentLifts = value.lifts; currentEquipment = value.equipment; render();
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
        equipment: currentEquipment.features,
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
    [stationsToggle, liftsToggle, escalatorsToggle, walkwaysToggle].forEach((toggle) => toggle.addEventListener('change', () => {
      currentDetail = { ...currentDetail, layers: new Set(activeLayers()) }; render();
    }));
    doc.addEventListener(SHOW_ON_MAP_EVENT, (event) => show(validDetail(event.detail)));
  });
}

if (typeof document !== 'undefined') mountMapLayers(document);
export { SHOW_ON_MAP_EVENT, validDetail, distanceM, nearestFirst, rowText, featuresToPoints, withCard, mountMapLayers };
