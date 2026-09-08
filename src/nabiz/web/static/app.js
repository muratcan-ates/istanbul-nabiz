/* İstanbul Nabız — single page, vanilla JS, no build step.
 *
 * Two things are deliberate here.
 *
 * 1. There is no language model on this page. The question box is a keyword router: it
 *    picks one of the twelve HTTP endpoints and shows what came back. Saying so in the UI
 *    is cheaper than pretending otherwise and being caught by a user who asks something
 *    the router cannot parse.
 * 2. Every card renders provenance.age. The API computes that string server-side so the
 *    phrasing rules live in one place (ibb_mcp.models.Provenance.describe_age).
 */
'use strict';

const $ = (sel) => document.querySelector(sel);
const results = $('#results');

/* ---------------------------------------------------------------- utilities */

function esc(value) {
  if (value === null || value === undefined) return '';
  return String(value).replace(/[&<>"']/g, (ch) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
  ));
}

/** Turkish decimal comma, because "1.9 km" reads as nineteen to a Turkish speaker. */
function num(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return Number(value).toLocaleString('tr-TR', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function int(value) {
  if (value === null || value === undefined) return '—';
  return Number(value).toLocaleString('tr-TR');
}

async function api(path, params) {
  const url = new URL(path, window.location.origin);
  Object.entries(params || {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, v);
  });
  const response = await fetch(url, { headers: { Accept: 'application/json' } });
  let body = null;
  try { body = await response.json(); } catch (err) { body = null; }
  if (!response.ok) {
    const message = (body && body.message) || `İstek başarısız (HTTP ${response.status}).`;
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  return body;
}

/** The age stamp every card carries. */
function ageTag(prov) {
  if (!prov) return '';
  const cls = prov.stale ? 'age stale' : 'age';
  const title = prov.stale
    ? 'İBB servisine ulaşılamadı; önbellekteki son değer gösteriliyor.'
    : `Kaynak: ${prov.source}`;
  return `<span class="${cls}" title="${esc(title)}">${esc(prov.age)}</span>`;
}

function sourceLine(prov) {
  if (!prov || !prov.source_url) return '';
  const url = prov.source_url.startsWith('http') ? prov.source_url : null;
  const text = esc(prov.source);
  return url
    ? `<span class="source"><a href="${esc(url)}" target="_blank" rel="noopener noreferrer">kaynak: ${text}</a></span>`
    : `<span class="source">kaynak: ${text}</span>`;
}

function shell(title, prov, inner, note) {
  return [
    `<div class="result-head"><h2>${esc(title)}</h2>${sourceLine(prov)}</div>`,
    note ? `<p class="note">${esc(note)}</p>` : '',
    inner,
  ].join('');
}

/* A cold parking answer costs three İSPARK detail calls at the gateway's six-second
 * spacing, so "nothing happened" is a real user experience here. Say we are working. */
function setBusy(on) {
  results.setAttribute('aria-busy', on ? 'true' : 'false');
  if (on) results.innerHTML = '<p class="empty">İBB uçlarından okunuyor… ilk sorgu birkaç saniye sürebilir.</p>';
}

function showError(message) {
  results.innerHTML = `<p class="error">${esc(message)}</p>`;
  hideMap();
}

/* ---------------------------------------------------------------------- map */

let map = null;
let markers = [];
let mapBroken = false;

function mapAvailable() {
  return !window.NABIZ_MAP_BLOCKED && typeof window.maplibregl !== 'undefined' && !mapBroken;
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
  $('#map-panel').hidden = true;
}

function showOnMap(points) {
  const usable = (points || []).filter((p) => Number.isFinite(p.lat) && Number.isFinite(p.lon));
  if (!usable.length || !mapAvailable()) { hideMap(); return; }
  const panel = $('#map-panel');
  panel.hidden = false;
  try {
    if (!map) {
      const chosen = mapStyle();
      map = new window.maplibregl.Map({
        container: 'map',
        style: chosen.style,
        center: [usable[0].lon, usable[0].lat],
        zoom: 12,
        attributionControl: { compact: true },
      });
      map.addControl(new window.maplibregl.NavigationControl({ showCompass: false }), 'top-right');
      $('#map-source').textContent = `${chosen.label} · yalnızca görselleştirme`;
    }
    markers.forEach((m) => m.remove());
    markers = usable.map((p) => {
      const el = document.createElement('div');
      el.className = `pin ${p.kind || ''}`;
      el.title = p.label || '';
      const marker = new window.maplibregl.Marker({ element: el }).setLngLat([p.lon, p.lat]);
      if (p.label) marker.setPopup(new window.maplibregl.Popup({ offset: 12 }).setText(p.label));
      return marker.addTo(map);
    });
    const bounds = usable.reduce(
      (acc, p) => acc.extend([p.lon, p.lat]),
      new window.maplibregl.LngLatBounds([usable[0].lon, usable[0].lat], [usable[0].lon, usable[0].lat]),
    );
    map.fitBounds(bounds, { padding: 48, maxZoom: 15, duration: 0 });
  } catch (err) {
    // A broken map must never take the answer with it.
    mapBroken = true;
    hideMap();
    console.warn('harita devre dışı:', err);
  }
}

/* ----------------------------------------------------------------- renderers */

function parkingCard(lot, prov) {
  const capacity = lot.capacity || 0;
  const empty = lot.empty === null || lot.empty === undefined ? null : lot.empty;
  const occupied = capacity && empty !== null ? Math.max(0, capacity - empty) : null;
  const pct = capacity && occupied !== null ? Math.round((occupied / capacity) * 100) : null;
  const cls = pct === null ? '' : pct >= 90 ? 'bad' : pct >= 70 ? 'warn' : '';
  const meta = [
    lot.distance_km !== null && lot.distance_km !== undefined ? `${num(lot.distance_km)} km` : null,
    lot.park_type, lot.district, lot.work_hours,
    lot.free_minutes ? `ilk ${int(lot.free_minutes)} dk ücretsiz` : null,
    lot.monthly_fee ? `aylık ${int(lot.monthly_fee)} ₺` : null,
  ].filter(Boolean);
  return `<article class="card">
    <header><div><h3>${esc(lot.name)}</h3>${lot.address ? `<p class="sub">${esc(lot.address)}</p>` : ''}</div>${ageTag(prov)}</header>
    <p class="metric"><strong>${empty === null ? '—' : int(empty)}</strong> boş${capacity ? ` / ${int(capacity)} kapasite` : ''}</p>
    ${pct === null ? '' : `<div class="bar"><i class="${cls}" style="width:${pct}%"></i></div>`}
    <ul class="meta">${meta.map((m) => `<li>${esc(m)}</li>`).join('')}</ul>
    ${lot.tariff ? `<p class="tariff">${esc(lot.tariff)}</p>` : ''}
  </article>`;
}

const METHOD_TR = { stop_sequence: 'durak sırası', distance: 'kuş uçuşu mesafe', schedule: 'ilan edilen sefer' };
const CONFIDENCE_TR = { high: 'yüksek', medium: 'orta', low: 'düşük' };

function arrivalCard(arrival, prov) {
  const meta = [
    arrival.stops_away !== null && arrival.stops_away !== undefined ? `${int(arrival.stops_away)} durak` : null,
    arrival.distance_km !== null && arrival.distance_km !== undefined ? `${num(arrival.distance_km)} km` : null,
    `yöntem: ${METHOD_TR[arrival.method] || arrival.method}`,
    `güven: ${CONFIDENCE_TR[arrival.confidence] || arrival.confidence}`,
    arrival.direction,
  ].filter(Boolean);
  return `<article class="card">
    <header>
      <div><h3>${esc(arrival.line_code)} · ${esc(arrival.door_no)}</h3>
      <p class="sub">${esc(arrival.stop_name || arrival.stop_code)}</p></div>
      ${ageTag(prov)}
    </header>
    <p class="metric"><strong>${arrival.eta_minutes === null || arrival.eta_minutes === undefined ? '—' : num(arrival.eta_minutes, 0)}</strong> dakika</p>
    <ul class="meta">${meta.map((m) => `<li>${esc(m)}</li>`).join('')}</ul>
  </article>`;
}

function busCard(bus, prov) {
  // Entries go through esc() in the <li> map below, so they must arrive unescaped here.
  const meta = [bus.direction, bus.nearest_stop_code ? `yakın durak ${bus.nearest_stop_code}` : null, bus.route_code].filter(Boolean);
  return `<article class="card">
    <header><div><h3>${esc(bus.door_no)}</h3><p class="sub">${esc(bus.line_name || bus.line_code || '')}</p></div>${ageTag(prov)}</header>
    <ul class="meta">${meta.map((m) => `<li>${esc(m)}</li>`).join('')}</ul>
  </article>`;
}

function metroCard(line, prov) {
  const colour = line.color || '#5a6473';
  return `<article class="card">
    <header>
      <div><h3><span class="line-badge" style="background:${esc(colour)}">${esc(line.line_name || '?')}</span>Servis duyurusu</h3></div>
      ${ageTag(prov)}
    </header>
    <p class="sub">${esc(line.description || 'Açıklama yok.')}</p>
    <ul class="meta">${line.updated_at ? `<li>İBB güncellemesi: ${esc(new Date(line.updated_at).toLocaleString('tr-TR'))}</li>` : ''}</ul>
  </article>`;
}

function stationCard(station, prov) {
  const yes = (v) => (v === true ? 'var' : v === false ? 'yok' : 'bilinmiyor');
  const meta = [
    `asansör: ${station.lifts === null || station.lifts === undefined ? 'bilinmiyor' : int(station.lifts)}`,
    `yürüyen merdiven: ${station.escalators === null || station.escalators === undefined ? 'bilinmiyor' : int(station.escalators)}`,
    `WC: ${yes(station.wc)}`, `bebek odası: ${yes(station.baby_room)}`, `mescit: ${yes(station.masjid)}`,
    station.order ? `sıra ${int(station.order)}` : null,
  ].filter(Boolean);
  return `<article class="card">
    <header>
      <div><h3><span class="line-badge">${esc(station.line_name || '?')}</span>${esc(station.name || '')}</h3></div>
      ${ageTag(prov)}
    </header>
    <ul class="meta">${meta.map((m) => `<li>${esc(m)}</li>`).join('')}</ul>
  </article>`;
}

const BAND_KEYS = ['good', 'moderate', 'unhealthy_sensitive', 'unhealthy', 'very_unhealthy', 'hazardous'];

function airCard(payload, prov) {
  const reading = payload.reading || {};
  const band = payload.band || {};
  const key = BAND_KEYS.includes(band.key) ? band.key : 'good';
  const colour = reading.color || `var(--band-${key})`;
  const meta = [
    reading.pm10 !== null && reading.pm10 !== undefined ? `PM10 (saatlik) ${num(reading.pm10)} µg/m³` : null,
    reading.no2 !== null && reading.no2 !== undefined ? `NO₂ ${num(reading.no2)}` : null,
    reading.o3 !== null && reading.o3 !== undefined ? `O₃ ${num(reading.o3)}` : null,
    reading.so2 !== null && reading.so2 !== undefined ? `SO₂ ${num(reading.so2)}` : null,
    reading.dominant ? `baskın: ${reading.dominant}` : null,
    payload.station && payload.station.distance_km !== null && payload.station.distance_km !== undefined
      ? `${num(payload.station.distance_km)} km uzakta` : null,
  ].filter(Boolean);
  return `<article class="card">
    <header>
      <div><h3>${esc(payload.place || '')}</h3><p class="sub">${esc((payload.station || {}).name || '')} istasyonu</p></div>
      ${ageTag(prov)}
    </header>
    <div class="aqi">
      <div class="aqi-dot" style="background:${esc(colour)}">${reading.aqi_index === null || reading.aqi_index === undefined ? '—' : num(reading.aqi_index, 0)}</div>
      <div><div class="aqi-band">${esc(band.label || 'Bilinmiyor')}</div><div class="sub">AQI (İBB)</div></div>
    </div>
    <ul class="meta">${meta.map((m) => `<li>${esc(m)}</li>`).join('')}</ul>
    ${reading.state ? `<p class="aqi-state">${esc(reading.state)}</p>` : ''}
    <p class="hint">İBB'nin yayımladığı AQI, PM10 için 24 saatlik hareketli ortalamadır ve saatlik
      değişimi geç yansıtır; şu anki hava için saatlik PM10 derişimine bakın. PM2.5 bu serviste yayımlanmıyor.</p>
    <p class="tariff">${esc(payload.disclaimer || 'Sağlık tavsiyesi değildir.')}</p>
  </article>`;
}

function forecastCard(payload, prov) {
  const rows = (payload.forecast || []).map((f) => {
    const hour = f.at ? new Date(f.at).toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' }) : '—';
    return `<li>${esc(hour)} · PM10 ${num(f.pm10)}</li>`;
  });
  const best = payload.best_window || payload.best;
  return `<article class="card">
    <header><div><h3>Sonraki ${int(payload.horizon_hours || rows.length)} saat</h3><p class="sub">PM10 tahmini (mevsimsel-naif)</p></div>${ageTag(prov)}</header>
    <ul class="meta">${rows.join('')}</ul>
    ${best && best.at ? `<p class="aqi-state">En temiz saat: ${esc(new Date(best.at).toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' }))} · PM10 ${num(best.pm10)}</p>` : ''}
  </article>`;
}

function trafficCard(payload, prov) {
  const idx = payload.index;
  const cls = idx === null || idx === undefined ? '' : idx >= 80 ? 'bad' : idx >= 50 ? 'warn' : '';
  const history = payload.history || [];
  const max = history.reduce((m, p) => Math.max(m, p.index || 0), 1);
  const spark = history.map((p, i) => `<span class="${i === history.length - 1 ? 'now' : ''}" style="height:${Math.round(((p.index || 0) / max) * 100)}%" title="${esc(p.at || '')}: ${esc(p.index)}"></span>`).join('');
  return `<article class="card">
    <header><div><h3>İstanbul trafik indeksi</h3><p class="sub">1 akıcı — 99 kilitli</p></div>${ageTag(prov)}</header>
    ${idx === null || idx === undefined ? '' : `<p class="metric"><strong>${int(idx)}</strong> ${esc(payload.description || '')}</p>
    <div class="bar"><i class="${cls}" style="width:${Math.min(100, idx)}%"></i></div>`}
    ${spark ? `<div class="spark">${spark}</div>` : ''}
    ${payload.same_hour_yesterday ? `<ul class="meta"><li>dün aynı saat: ${int(payload.same_hour_yesterday.index)} (${esc(payload.same_hour_yesterday.label || '')})</li></ul>` : ''}
    ${payload.comparison ? `<p class="aqi-state">${esc(payload.comparison)}</p>` : ''}
  </article>`;
}

function simpleCard(title, sub, meta, prov) {
  return `<article class="card">
    <header><div><h3>${esc(title)}</h3>${sub ? `<p class="sub">${esc(sub)}</p>` : ''}</div>${ageTag(prov)}</header>
    <ul class="meta">${(meta || []).filter(Boolean).map((m) => `<li>${esc(m)}</li>`).join('')}</ul>
  </article>`;
}

function cards(html) { return `<div class="cards">${html}</div>`; }

/* ------------------------------------------------------------------ journeys */

const JOURNEYS = {
  async parking({ place }) {
    const res = await api('/api/parking', { place, radius_km: 1.5, min_free: 1 });
    const parks = res.data.parks || [];
    results.innerHTML = shell(
      `${res.data.near} çevresinde ${res.data.count} otopark`,
      res.provenance,
      cards(parks.map((p) => parkingCard(p, res.provenance)).join('')),
      res.note,
    );
    showOnMap(parks.map((p) => ({ lat: p.lat, lon: p.lon, kind: 'park', label: `${p.name} · ${p.empty ?? '—'} boş` })));
  },

  async bus({ line }) {
    const res = await api('/api/buses', { line });
    const buses = res.data.buses || [];
    const hint = 'Varış tahmini için durak adı ekleyin — örnek: “500T Şifa Sondurak”.';
    results.innerHTML = shell(
      `${res.data.line_code} hattında ${res.data.count} araç`,
      res.provenance,
      cards(buses.slice(0, 8).map((b) => busCard(b, res.provenance)).join('')),
      res.note ? `${res.note} ${hint}` : hint,
    );
    showOnMap(buses.map((b) => ({ lat: b.lat, lon: b.lon, kind: 'bus', label: `${b.door_no} → ${b.direction || ''}` })));
  },

  async arrivals({ line, stop }) {
    const res = await api('/api/arrivals', { line, stop, limit: 3 });
    const arrivals = res.data.arrivals || [];
    const stopInfo = res.data.stop || {};
    results.innerHTML = shell(
      `${res.data.line_code} · ${stopInfo.name || stop}`,
      res.provenance,
      cards(arrivals.map((a) => arrivalCard(a, res.provenance)).join('')) + `<p class="hint">${esc(res.data.disclaimer || '')}</p>`,
      res.note,
    );
    showOnMap([{ lat: stopInfo.lat, lon: stopInfo.lon, kind: 'station', label: stopInfo.name || stop }]);
  },

  async metro({ line }) {
    const res = await api('/api/metro', { line });
    const lines = res.data.lines || [];
    results.innerHTML = shell(
      line ? `${line} servis durumu` : 'Metro servis duyuruları',
      res.provenance,
      lines.length ? cards(lines.map((l) => metroCard(l, res.provenance)).join(''))
        : cards(simpleCard(line ? `${line}: bildirilmiş arıza yok` : 'Bildirilmiş arıza yok', 'Metro İstanbul canlı duyuru akışı', [], res.provenance)),
      res.note,
    );
    hideMap();
  },

  async station({ name }) {
    const res = await api('/api/metro/station', { name });
    const stations = res.data.stations || [];
    results.innerHTML = shell(`${res.data.query} istasyonu`, res.provenance, cards(stations.map((s) => stationCard(s, res.provenance)).join('')), res.note);
    showOnMap(stations.map((s) => ({ lat: s.lat, lon: s.lon, kind: 'station', label: `${s.name} (${s.line_name})` })));
  },

  async air({ place }) {
    const now = await api('/api/air', { place });
    let forecastHtml = '';
    try {
      const fc = await api('/api/air/forecast', { place, hours: 6 });
      forecastHtml = forecastCard(fc.data, fc.provenance);
      if (fc.note) forecastHtml += `<p class="note">${esc(fc.note)}</p>`;
    } catch (err) {
      forecastHtml = `<p class="note">Tahmin alınamadı: ${esc(err.message)}</p>`;
    }
    results.innerHTML = shell(
      `${now.data.place} hava kalitesi`,
      now.provenance,
      cards(airCard(now.data, now.provenance) + forecastHtml),
      now.note,
    );
    const st = now.data.station || {};
    showOnMap([{ lat: st.lat, lon: st.lon, kind: 'air', label: `${st.name} ölçüm istasyonu` }]);
  },

  async traffic() {
    const res = await api('/api/traffic', { window: 'now' });
    let extra = {};
    try {
      const hist = await api('/api/traffic', { window: '24h' });
      extra = {
        history: hist.data.history || [],
        same_hour_yesterday: hist.data.same_hour_yesterday,
        comparison: hist.data.description,
      };
    } catch (err) {
      extra = {};
    }
    results.innerHTML = shell('Trafik', res.provenance, cards(trafficCard({ ...res.data, ...extra }, res.provenance)), res.note);
    hideMap();
  },

  async stops({ q }) {
    const res = await api('/api/stops', { q });
    const stops = res.data.stops || [];
    results.innerHTML = shell(`“${res.data.query}” için ${res.data.count} durak`, res.provenance,
      cards(stops.map((s) => simpleCard(s.name || s.stop_code, s.description || '', [`durak kodu ${s.stop_code}`], res.provenance)).join('')), res.note);
    showOnMap(stops.map((s) => ({ lat: s.lat, lon: s.lon, kind: 'station', label: s.name || s.stop_code })));
  },

  async places({ q }) {
    const res = await api('/api/places', { q });
    const matches = res.data.matches || [];
    results.innerHTML = shell(`“${res.data.query}” için ${matches.length} yer`, res.provenance,
      cards(matches.map((p) => simpleCard(p.label || p.name, p.district || '', [p.kind], res.provenance)).join('')),
      res.note || 'Otopark, otobüs, metro veya hava kalitesi sormak için soruya bir anahtar kelime ekleyin.');
    showOnMap(matches.map((p) => ({ lat: p.lat, lon: p.lon, label: p.label || p.name })));
  },

  async freshness() {
    const res = await api('/api/freshness');
    const sources = res.data.sources || {};
    const items = Object.entries(sources).map(([name, s]) => simpleCard(
      name, s.healthy ? 'sağlıklı' : 'sorunlu',
      [`yaş: ${num(s.age_seconds, 0)} sn`, `isabet: ${int(s.hits)}`, `hata: ${int(s.errors)}`], res.provenance,
    ));
    results.innerHTML = shell('Veri tazeliği', res.provenance,
      items.length ? cards(items.join('')) : '<p class="empty">Henüz hiçbir kaynak sorgulanmadı.</p>', res.note);
    hideMap();
  },
};

/* -------------------------------------------------------------- text routing */

const FILLER = new Set([
  'var', 'yok', 'mı', 'mi', 'mu', 'mü', 'nasıl', 'ne', 'zaman', 'gelir', 'geliyor', 'kaç', 'dakika',
  'otopark', 'otoparkı', 'park', 'yer', 'hava', 'kalitesi', 'kirlilik', 'trafik', 'metro', 'arıza',
  'istasyon', 'istasyonu', 'asansör', 'durak', 'durağı', 'durağına', 'otobüs', 'otobüsü', 'hat', 'hattı',
  'bugün', 'şimdi', 'şu', 'an', 'anda', 'için', 'bir', 'yakın', 'yakınında', 'civarında', 'en', 'nerede',
  'nerde', 'koşu', 'koşmak', 'uygun', 'mudur', 'lütfen', 'ile', 've', 'de', 'da',
]);

/* Turkish is agglutinative, so "istasyonunda" and "durakları" are the same words the
 * filler list already knows with case endings glued on. Matching a few stems is enough
 * to pull the place name out of a question without pretending to do morphology. */
/* 'havas'/'havad'/'havay' cover "havası", "havada", "havayı" without touching
 * "havalimanı" — the airport is a place name, not a word about the air. */
const FILLER_STEMS = [
  'istasyon', 'durak', 'durağ', 'otopark', 'otobüs', 'asansör', 'merdiven', 'yürüyen', 'hatt',
  'havas', 'havad', 'havay',
];

const METRO_RE = /^(M\d{1,2}[AB]?|T\d{1,2}|F\d|TF\d)$/i;
const BUS_RE = /^\d{1,3}[A-Za-zÇĞİÖŞÜçğıöşü]{0,2}$/;

function cleanWord(word) {
  return word.replace(/[’'´`].*$/, '').replace(/^[^0-9A-Za-zÇĞİÖŞÜçğıöşü]+|[^0-9A-Za-zÇĞİÖŞÜçğıöşü]+$/g, '');
}

function tokenize(text) {
  return text.split(/[\s,.;:!?()"]+/).map(cleanWord).filter(Boolean);
}

function isFiller(token) {
  const low = token.toLocaleLowerCase('tr');
  return FILLER.has(low) || FILLER_STEMS.some((stem) => low.startsWith(stem));
}

function meaningful(tokens) {
  return tokens.filter((t) => !isFiller(t) && !BUS_RE.test(t) && !METRO_RE.test(t));
}

/** Map free text onto one journey. Keyword matching, not a model — and the UI says so. */
function route(text) {
  const tokens = tokenize(text);
  if (!tokens.length) return null;
  const low = tokens.map((t) => t.toLocaleLowerCase('tr')).join(' ');
  const metro = tokens.find((t) => METRO_RE.test(t));
  const bus = tokens.find((t) => BUS_RE.test(t) && !METRO_RE.test(t));
  const rest = meaningful(tokens).join(' ');

  if (/tazeli|veri yaş|güncellik/.test(low)) return { journey: 'freshness', args: {} };
  if (/trafik|yoğunluk/.test(low)) return { journey: 'traffic', args: {} };
  if (/istasyon|asansör|engelli|bebek odası|yürüyen/.test(low) && rest) return { journey: 'station', args: { name: rest } };
  if (metro) return { journey: 'metro', args: { line: metro.toLocaleUpperCase('tr') } };
  // "hava" must not swallow "havalimanı"/"havaalanı": the airport is a place someone asks
  // about parking at, not a question about the air, and İstanbul has two of them.
  if (/hava(?!limanı|alanı|liman|alan)|kirlilik|aqi|pm10|koşu|nefes/.test(low)) return { journey: 'air', args: { place: rest || text } };
  if (/otopark|park/.test(low)) return { journey: 'parking', args: { place: rest || text } };
  if (bus) {
    return rest
      ? { journey: 'arrivals', args: { line: bus.toLocaleUpperCase('tr'), stop: rest } }
      : { journey: 'bus', args: { line: bus.toLocaleUpperCase('tr') } };
  }
  // "durağı"/"durağa"/"durağında": Turkish softens the final k to ğ before a vowel, and
  // "X durağı" is how the question is actually asked. Matching only "durak" sent it to the
  // place gazetteer, which does not hold bus stops, so the honest answer never appeared.
  if (/dura[kğ]/.test(low)) return { journey: 'stops', args: { q: rest || text } };
  return { journey: 'places', args: { q: text.trim() } };
}

async function run(journey, args) {
  const handler = JOURNEYS[journey];
  if (!handler) { showError('Bu soruyu nasıl yanıtlayacağımı bilmiyorum.'); return; }
  setBusy(true);
  try {
    await handler(args || {});
  } catch (err) {
    showError(err.message || 'Beklenmeyen bir hata oluştu.');
  } finally {
    setBusy(false);
  }
}

/* ---------------------------------------------------------------------- boot */

document.addEventListener('DOMContentLoaded', () => {
  const version = $('#version');
  if (version && window.NABIZ_VERSION) version.textContent = `sürüm ${window.NABIZ_VERSION}`;
  if (window.NABIZ_ATTRIBUTION) $('#attribution').setAttribute('title', window.NABIZ_ATTRIBUTION);

  document.querySelectorAll('.chip').forEach((chip) => {
    chip.addEventListener('click', () => {
      document.querySelectorAll('.chip').forEach((c) => c.setAttribute('aria-pressed', 'false'));
      chip.setAttribute('aria-pressed', 'true');
      $('#q').value = chip.textContent.trim();
      run(chip.dataset.journey, { place: chip.dataset.place, line: chip.dataset.line });
    });
  });

  $('#ask-form').addEventListener('submit', (event) => {
    event.preventDefault();
    document.querySelectorAll('.chip').forEach((c) => c.setAttribute('aria-pressed', 'false'));
    const parsed = route($('#q').value || '');
    if (!parsed) return;
    run(parsed.journey, parsed.args);
  });

  api('/api/freshness')
    .then((res) => {
      const sources = Object.entries(res.data.sources || {});
      const el = $('#freshness');
      if (!sources.length) { el.textContent = 'Veri tazeliği: henüz sorgu yapılmadı.'; return; }
      el.textContent = 'Veri tazeliği — ' + sources
        .map(([name, s]) => `${name}: ${num(s.age_seconds, 0)} sn`)
        .join(' · ');
    })
    .catch(() => { $('#freshness').textContent = 'Veri tazeliği okunamadı.'; });
});
