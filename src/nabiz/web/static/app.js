/* İstanbul Nabız — single page, vanilla JS, no build step.
 *
 * Four things are deliberate here.
 *
 * 1. There is no language model on this page. The question box is a keyword router: it
 *    picks one of the HTTP endpoints and shows what came back. Saying so in the UI is
 *    cheaper than pretending otherwise and being caught by a user who asks something the
 *    router cannot parse.
 * 2. Every card renders provenance.age. The API computes that string server-side so the
 *    phrasing rules live in one place (ibb_mcp.models.Provenance.describe_age).
 * 3. Nothing on this page requires the map. MapLibre comes from a CDN; when that CDN is
 *    blocked the answer still renders and the map panel degrades to a location list.
 * 4. Endpoints the integrator has not shipped yet (/api/route, /api/alerts,
 *    /api/reliability) are probed, not assumed: a 404 hides the panel silently.
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
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  return Number(value).toLocaleString('tr-TR', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function int(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  return Number(value).toLocaleString('tr-TR');
}

function has(value) {
  return value !== null && value !== undefined && value !== '';
}

function clock(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' });
}

function icon(name, cls) {
  return `<svg class="icon${cls ? ' ' + cls : ''}" aria-hidden="true"><use href="#i-${name}"></use></svg>`;
}

async function api(path, params) {
  const url = new URL(path, window.location.origin);
  Object.entries(params || {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, v);
  });
  let response;
  try {
    response = await fetch(url, { headers: { Accept: 'application/json' } });
  } catch (err) {
    const offline = new Error('Sunucuya ulaşılamadı. Bağlantınızı kontrol edip tekrar deneyin.');
    offline.status = 0;
    throw offline;
  }
  let body = null;
  try { body = await response.json(); } catch (err) { body = null; }
  if (!response.ok) {
    const message = (body && body.message) || `İstek başarısız (HTTP ${response.status}).`;
    const error = new Error(message);
    error.status = response.status;
    error.kind = body && body.error;
    throw error;
  }
  return body;
}

/** For endpoints the integrator may not have wired yet: a 404 is "not here", not a failure. */
async function probe(path, params) {
  try {
    return await api(path, params);
  } catch (err) {
    if (err.status === 404 || err.status === 405 || err.status === 422 || err.status === 0) return null;
    throw err;
  }
}

/* ------------------------------------------------------------- provenance */

const SOURCE_TR = {
  ispark: 'İSPARK otoparkları',
  iett_line: 'İETT hat konumları',
  iett_fleet: 'İETT filo',
  iett_schedule: 'İETT planlanan sefer',
  metro_status: 'Metro duyuruları',
  metro_stations: 'Metro istasyonları',
  aq_stations: 'Hava kalitesi istasyonları',
  aq_readings: 'Hava kalitesi ölçümleri',
  traffic: 'Trafik indeksi',
  gtfs: 'GTFS (İETT)',
  gazetteer: 'Yer sözlüğü',
  nabiz_runtime: 'Nabız çalışma zamanı',
  nabiz_forecast: 'Nabız tahmini',
};

function sourceLabel(name) {
  return SOURCE_TR[name] || name;
}

function freshnessClass(seconds, stale) {
  if (stale) return 'cached';
  if (!Number.isFinite(seconds)) return 'old';
  if (seconds < 180) return 'fresh';
  if (seconds < 3600) return 'aging';
  return 'old';
}

/** The age stamp every single card carries — the core promise of this product. */
function stamp(prov) {
  if (!prov) return '<span class="stamp old"><i class="dot"></i>veri yaşı bilinmiyor</span>';
  const cls = freshnessClass(prov.age_seconds, prov.stale);
  const title = prov.stale
    ? 'İBB servisine ulaşılamadı; önbellekteki son değer gösteriliyor.'
    : `Kaynak: ${sourceLabel(prov.source)} · ölçüm ${prov.age}`;
  const prefix = prov.stale ? 'önbellek · ölçüm ' : 'ölçüm ';
  return `<span class="stamp ${cls}" title="${esc(title)}"><i class="dot" aria-hidden="true"></i>${prefix}<b>${esc(prov.age)}</b></span>`;
}

function sourceLink(prov) {
  if (!prov || !prov.source) return '';
  const label = esc(sourceLabel(prov.source));
  const url = prov.source_url && prov.source_url.startsWith('http') ? prov.source_url : null;
  return url
    ? `<a class="src" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${label} ↗</a>`
    : `<span class="src">${label}</span>`;
}

function cardFoot(prov, extra) {
  return `<footer class="card-foot">${stamp(prov)}${extra || ''}${sourceLink(prov)}</footer>`;
}

/* ------------------------------------------------------------------ shells */

let cardSeq = 0;
function nextCardId() {
  cardSeq += 1;
  return `kart-${cardSeq}`;
}

/**
 * One card skeleton for every answer type: identity on the left, age at the bottom.
 * `id` is what a map marker points at, which is why every caller passes one.
 */
function cardShell(opts) {
  const kind = opts.kind || '';
  return `<article class="card" id="${esc(opts.id)}" tabindex="-1"${opts.aria ? ` aria-label="${esc(opts.aria)}"` : ''}>
    <div class="card-head">
      ${opts.icon ? `<span class="card-kind ${esc(kind)}" aria-hidden="true">${icon(opts.icon)}</span>` : ''}
      <div class="card-title">
        <h3>${opts.titleHtml || esc(opts.title)}</h3>
        ${opts.sub ? `<p class="sub">${esc(opts.sub)}</p>` : ''}
      </div>
    </div>
    <div class="card-body">${opts.body || ''}</div>
    ${cardFoot(opts.prov, opts.footExtra)}
  </article>`;
}

function resultHead(title, count, prov, note) {
  return [
    `<div class="result-head"><h2>${esc(title)}${has(count) ? ` <span class="count">${esc(count)}</span>` : ''}</h2></div>`,
    note ? `<p class="note">${esc(note)}</p>` : '',
  ].join('');
}

function cards(html, wide) {
  return `<div class="cards${wide ? ' two' : ''}">${html}</div>`;
}

function metaList(items) {
  const kept = (items || []).filter(Boolean);
  if (!kept.length) return '';
  return `<ul class="meta">${kept.map((m) => `<li>${esc(m)}</li>`).join('')}</ul>`;
}

/* A cold İSPARK answer costs several detail calls at the gateway's six-second spacing, so
 * "nothing happened" is a real user experience here. Say we are working, and say why. */
function setBusy(on) {
  results.setAttribute('aria-busy', on ? 'true' : 'false');
  const submit = $('#ask-submit');
  if (submit) submit.disabled = !!on;
  if (on) {
    results.innerHTML = `<p class="loading-label">${icon('refresh')} İBB uçlarından okunuyor… ilk sorgu birkaç saniye sürebilir.</p>
      <div class="skeleton"><div class="sk-card"></div><div class="sk-card"></div></div>`;
  }
}

/* ----------------------------------------------------------------- errors */

const ERROR_TITLES = {
  0: 'Sunucuya ulaşılamadı',
  400: 'Bu soruyu yanıtlayamadım',
  404: 'Böyle bir uç yok',
  422: 'İstek eksik ya da hatalı',
  429: 'Kendi istek bütçemiz doldu',
  503: 'İBB servisi şu anda yanıt vermiyor',
};

/**
 * A failure is an answer. A 503 in particular must say how old the last thing we knew is,
 * because "bilmiyorum" and "17 saniye önce biliyordum" are different answers to the user.
 */
async function showError(err) {
  const status = err.status || 0;
  const title = ERROR_TITLES[status] || 'Beklenmeyen bir hata';
  let lastKnown = '';
  if (status === 503 || status === 429 || status === 0) {
    try {
      const fresh = await api('/api/freshness');
      const rows = Object.entries((fresh.data && fresh.data.sources) || {})
        .map(([name, s]) => `<li><span>${esc(sourceLabel(name))}</span><span>${esc(shortAge(s.age_seconds))} önce</span></li>`)
        .join('');
      if (rows) {
        lastKnown = `<div class="last-known"><h4>En son ne zaman veri alabildik</h4><ul class="kv-list">${rows}</ul></div>`;
      }
    } catch (ignored) {
      lastKnown = '';
    }
  }
  results.innerHTML = `<div class="error-card">
    <h3>${icon('alert')}${esc(title)}</h3>
    <p>${esc(err.message || 'Bilinmeyen hata.')}</p>
    ${status === 503 ? '<p>Bu bir Nabız hatası değil: üst kaynak (İBB) yanıt vermedi. Sayı uydurmak yerine boş bırakıyoruz.</p>' : ''}
    ${lastKnown}
  </div>`;
  hideMap();
}

function shortAge(seconds) {
  if (!Number.isFinite(seconds)) return '—';
  if (seconds < 90) return `${Math.round(seconds)} sn`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} dk`;
  if (seconds < 172800) return `${Math.round(seconds / 3600)} sa`;
  return `${Math.round(seconds / 86400)} gün`;
}

/* ---------------------------------------------------------------------- map */

let map = null;
let markers = [];
let mapBroken = false;
let mapForcedOff = false;
let lastPoints = [];

const KIND_TR = { park: 'Otopark', bus: 'Otobüs', station: 'İstasyon / durak', air: 'Hava ölçüm istasyonu', place: 'Yer' };

function mapAvailable() {
  return !mapForcedOff && !window.NABIZ_MAP_BLOCKED && typeof window.maplibregl !== 'undefined' && !mapBroken;
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
      el.setAttribute('aria-label', `${KIND_TR[p.kind] || 'Konum'}: ${p.label || ''}`);
      el.addEventListener('click', () => focusCard(p.card));
      const marker = new window.maplibregl.Marker({ element: el }).setLngLat([p.lon, p.lat]);
      if (p.label) marker.setPopup(new window.maplibregl.Popup({ offset: 14, closeButton: false }).setText(p.label));
      marker.nabizCard = p.card;
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
  el.scrollIntoView({ block: 'center', behavior: 'smooth' });
  el.focus({ preventScroll: true });
}

/** The inverse: clicking a card lifts its marker. */
function highlightMarker(id) {
  markers.forEach((m) => {
    const el = m.getElement && m.getElement();
    if (el) el.classList.toggle('is-active', m.nabizCard === id);
  });
  const point = lastPoints.find((p) => p.card === id);
  if (point && map) map.easeTo({ center: [point.lon, point.lat], duration: 400 });
}

/* ----------------------------------------------------------------- renderers */

function fillBar(pct) {
  if (pct === null || pct === undefined) return '';
  const cls = pct >= 90 ? 'bad' : pct >= 70 ? 'warn' : '';
  return `<div class="bar"><i class="${cls}" style="width:${Math.max(0, Math.min(100, pct))}%"></i></div>`;
}

/** İSPARK ships the tariff as "0-1 Saat : 110,00;1-2 Saat : 140,00" — make it a table. */
function tariffTable(raw) {
  if (!raw) return '';
  const rows = String(raw).split(';').map((part) => part.split(':')).filter((p) => p.length >= 2);
  if (!rows.length) return `<p class="hint">${esc(raw)}</p>`;
  const body = rows.map(([label, value]) => `<tr><td>${esc(label.trim())}</td><td>${esc(value.trim())} ₺</td></tr>`).join('');
  return `<details class="tariff"><summary>Tarife (${rows.length} kademe)</summary><table><tbody>${body}</tbody></table></details>`;
}

function parkingCard(lot, prov, id) {
  const capacity = lot.capacity || 0;
  const empty = has(lot.empty) ? lot.empty : null;
  const occupied = capacity && empty !== null ? Math.max(0, capacity - empty) : null;
  const pct = capacity && occupied !== null ? Math.round((occupied / capacity) * 100) : null;
  const meta = [
    lot.park_type, lot.district, lot.work_hours,
    lot.free_minutes ? `ilk ${int(lot.free_minutes)} dk ücretsiz` : null,
    has(lot.monthly_fee) ? `aylık ${int(lot.monthly_fee)} ₺` : null,
    lot.is_open === false ? 'şu anda kapalı' : null,
  ];
  const body = `
    <div class="metric"><b>${empty === null ? '—' : int(empty)}</b><span class="unit">boş yer</span>
      ${capacity ? `<span class="metric-note">${int(capacity)} kapasite</span>` : ''}</div>
    ${fillBar(pct)}
    ${pct === null ? '' : `<div class="bar-legend"><span>%${int(pct)} dolu</span><span>${has(lot.distance_km) ? `${num(lot.distance_km)} km uzakta` : ''}</span></div>`}
    ${metaList(meta)}
    ${tariffTable(lot.tariff)}`;
  return cardShell({
    id, kind: 'park', icon: 'park', prov, body,
    title: lot.name,
    // The distance already appears under the fill bar; repeating it here read as noise.
    sub: lot.address || '',
  });
}

const METHOD_TR = { stop_sequence: 'durak sırası', distance: 'kuş uçuşu mesafe', schedule: 'ilan edilen sefer' };
const CONFIDENCE_TR = { high: 'yüksek', medium: 'orta', low: 'düşük' };
const METHOD_WHY = {
  stop_sequence: 'Aracın bildirdiği yakın durak, hattın GTFS durak sırasında hedefe göre konumlandırıldı.',
  distance: 'Durak sırası kurulamadı; kuş uçuşu mesafe kıvrımlılık katsayısıyla düzeltilerek kullanıldı.',
  schedule: 'Canlı araç bulunamadı; İETT’nin ilan ettiği sefer saati gösteriliyor.',
};

function arrivalCard(arrival, prov, id) {
  const method = arrival.method || '';
  const conf = arrival.confidence || '';
  const pills = `<div class="pills">
    <span class="pill method" title="${esc(METHOD_WHY[method] || 'Tahmin yöntemi')}">${icon('route')}${esc(METHOD_TR[method] || method || 'yöntem bilinmiyor')}</span>
    <span class="pill conf-${esc(conf)}">güven: ${esc(CONFIDENCE_TR[conf] || conf || '—')}</span>
  </div>`;
  const meta = [
    has(arrival.stops_away) ? `${int(arrival.stops_away)} durak` : null,
    has(arrival.distance_km) ? `${num(arrival.distance_km)} km` : null,
    arrival.direction ? `yön: ${arrival.direction}` : null,
    arrival.door_no ? `kapı no ${arrival.door_no}` : null,
  ];
  const body = `
    <div class="metric"><b>${has(arrival.eta_minutes) ? num(arrival.eta_minutes, 0) : '—'}</b><span class="unit">dakika içinde</span></div>
    ${pills}
    ${metaList(meta)}`;
  return cardShell({
    id, kind: 'bus', icon: 'bus', prov, body,
    title: `${arrival.line_code || ''} → ${arrival.stop_name || arrival.stop_code || ''}`,
    sub: arrival.line_name || '',
  });
}

/* When no estimate can be produced the diagnostics are the answer: they say which rule
 * rejected which bus, instead of leaving the user with an empty screen. */
const DIAG_TR = {
  buses_received: 'İETT’den gelen araç',
  dropped_stale: 'konumu fazla eski olduğu için elenen',
  dropped_unlocatable: 'konumu hatta oturtulamayan',
  dropped_passed_target: 'durağı geçmiş olan',
  unknown_age: 'zaman damgası okunamayan',
  estimated: 'tahmin üretilen',
  returned: 'gösterilen',
};

function noteCodeTr(code) {
  const stale = /^dropped_(\d+)_positions_older_than_(\d+)s$/.exec(code || '');
  if (stale) return `${stale[1]} aracın konumu ${stale[2]} sn’den eskiydi; eski konumdan varış saati üretmiyoruz.`;
  if (code === 'no_schedule_fallback_available') return 'Bu durak için ilan edilmiş sefer saati de bulunamadı.';
  if (code === 'no_sequence_for_route') return 'Bu güzergâh için GTFS durak sırası yüklü değil.';
  return null;
}

function diagnosticsCard(diag, prov, id) {
  if (!diag) return '';
  const counts = Object.keys(DIAG_TR)
    .filter((k) => has(diag[k]))
    .map((k) => `<li><span>${esc(DIAG_TR[k])}</span><span>${int(diag[k])}</span></li>`)
    .join('');
  const notes = (diag.notes || []).map((code) => {
    const tr = noteCodeTr(code);
    return `<li><span>${tr ? esc(tr) : `<code>${esc(code)}</code>`}</span><span></span></li>`;
  }).join('');
  const body = `
    <p class="hint">Tahmin üretilemediğinde sebebini gösteriyoruz — boş ekran da, uydurma dakika da yanıt değildir.</p>
    <ul class="kv-list">${notes}</ul>
    <details class="diag" ${counts ? '' : 'hidden'}><summary>Sayımlar</summary><ul class="kv-list">${counts}</ul></details>`;
  return cardShell({ id, kind: 'bus', icon: 'alert', prov, body, title: 'Neden varış tahmini yok?' });
}

function busCard(bus, prov, id) {
  const meta = [
    bus.direction ? `yön: ${bus.direction}` : null,
    bus.nearest_stop_code ? `yakın durak ${bus.nearest_stop_code}` : null,
    bus.route_code,
  ];
  const body = `${metaList(meta)}`;
  return cardShell({
    id, kind: 'bus', icon: 'bus', prov, body,
    title: `Kapı no ${bus.door_no || '—'}`,
    sub: bus.line_name || bus.line_code || '',
  });
}

function metroCard(line, prov, id) {
  const colour = line.color || '#5a6473';
  const body = `
    <p>${esc(line.description || 'Açıklama yok.')}</p>
    ${metaList([line.updated_at ? `İBB güncellemesi: ${new Date(line.updated_at).toLocaleString('tr-TR')}` : null,
    line.is_active === false ? 'hat kapalı' : null])}`;
  return cardShell({
    id, kind: 'station', icon: 'metro', prov, body,
    titleHtml: `<span class="line-badge" style="background:${esc(colour)}">${esc(line.line_name || '?')}</span>Servis duyurusu`,
  });
}

function metroClearCard(line, prov, id) {
  const body = `
    <p class="status-ok">${icon('check')}${esc(line ? `${line} hattında bildirilmiş aksaklık yok.` : 'Hiçbir hatta bildirilmiş aksaklık yok.')}</p>
    <p class="hint">Metro İstanbul yalnızca <em>duyurusu olan</em> hatları yayımlar; listede olmamak "veri yok" değil,
      "bildirilmiş aksaklık yok" demektir.</p>`;
  return cardShell({ id, kind: 'station', icon: 'metro', prov, body, title: 'Servis durumu' });
}

function stationCard(station, prov, id) {
  const yes = (v) => (v === true ? 'var' : v === false ? 'yok' : 'bilinmiyor');
  const stats = [
    ['Asansör', has(station.lifts) ? int(station.lifts) : '—'],
    ['Yürüyen merdiven', has(station.escalators) ? int(station.escalators) : '—'],
    ['WC', yes(station.wc)],
    ['Bebek odası', yes(station.baby_room)],
    ['Mescit', yes(station.masjid)],
  ];
  const body = `
    <div class="stat-grid">${stats.map(([k, v]) => `<div class="stat"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div></div>`).join('')}</div>
    ${metaList([has(station.order) ? `hat sırası ${int(station.order)}` : null])}`;
  return cardShell({
    id, kind: 'station', icon: 'metro', prov, body,
    titleHtml: `<span class="line-badge">${esc(station.line_name || '?')}</span>${esc(station.name || '')}`,
    sub: 'İstasyon donanımı',
  });
}

const BAND_KEYS = ['good', 'moderate', 'unhealthy_sensitive', 'unhealthy', 'very_unhealthy', 'hazardous'];

function airCard(payload, prov, id) {
  const reading = payload.reading || {};
  const band = payload.band || {};
  const key = BAND_KEYS.includes(band.key) ? band.key : null;
  const colour = reading.color || (key ? `var(--band-${key})` : 'var(--ink-soft)');
  const aqi = has(reading.aqi_index) ? Number(reading.aqi_index) : null;
  const frac = aqi === null ? 0 : Math.max(0, Math.min(1, aqi / 200));
  const circ = 163.4; // 2πr, r = 26
  const stats = [
    ['PM10', has(reading.pm10) ? `${num(reading.pm10)} <small>µg/m³</small>` : '—'],
    ['NO₂', has(reading.no2) ? num(reading.no2) : '—'],
    ['O₃', has(reading.o3) ? num(reading.o3) : '—'],
    ['SO₂', has(reading.so2) ? num(reading.so2) : '—'],
  ];
  const body = `
    <div class="aqi">
      <div class="aqi-dial">
        <svg viewBox="0 0 64 64" aria-hidden="true">
          <circle class="track" cx="32" cy="32" r="26"></circle>
          <circle class="val" cx="32" cy="32" r="26" style="stroke:${esc(colour)};stroke-dasharray:${(frac * circ).toFixed(1)} ${circ}"></circle>
        </svg>
        <div class="num">${aqi === null ? '—' : num(aqi, 0)}</div>
      </div>
      <div>
        <div class="aqi-band" style="color:${esc(colour)}">${esc(band.label || 'Bilinmiyor')}</div>
        <div class="aqi-label">AQI · İBB ölçeği (0–200 gösterildi)</div>
        ${reading.dominant ? `<div class="aqi-label">baskın kirletici: ${esc(reading.dominant)}</div>` : ''}
      </div>
    </div>
    <div class="stat-grid">${stats.map(([k, v]) => `<div class="stat"><div class="k">${k}</div><div class="v">${v}</div></div>`).join('')}</div>
    ${reading.state ? `<p class="hint">${esc(reading.state)}</p>` : ''}
    <p class="hint">İBB’nin yayımladığı AQI, PM10 için <strong>24 saatlik hareketli ortalamadır</strong> ve saatlik değişimi geç
      yansıtır; şu anki hava için saatlik PM10 derişimine bakın. Bu serviste PM2.5 yayımlanmıyor.</p>
    <p class="hint">${esc(payload.disclaimer || 'Sağlık tavsiyesi değildir.')}</p>`;
  return cardShell({
    id, kind: 'air', icon: 'air', prov, body,
    title: payload.place || 'Hava kalitesi',
    sub: payload.station ? `${payload.station.name} istasyonu${has(payload.station.distance_km) ? ` · ${num(payload.station.distance_km)} km` : ''}` : '',
  });
}

function forecastCard(payload, prov, id) {
  const rows = payload.forecast || [];
  if (!rows.length) {
    return cardShell({
      id, kind: 'air', icon: 'clock', prov, title: 'Saatlik tahmin',
      body: `<p class="hint">${esc(payload.note || 'Tahmin üretilemedi.')}</p>`,
    });
  }
  const max = rows.reduce((m, f) => Math.max(m, Number(f.pm10) || 0), 1);
  const best = payload.best_window || payload.best || {};
  const bars = rows.map((f) => {
    const height = Math.max(4, Math.round(((Number(f.pm10) || 0) / max) * 100));
    const isBest = best.at && f.at === best.at;
    return `<div class="col${isBest ? ' best' : ''}" title="${esc(clock(f.at))} · PM10 ${num(f.pm10)} µg/m³">
      <span class="v">${num(f.pm10)}</span><i style="height:${height}%"></i></div>`;
  }).join('');
  const axis = rows.map((f) => `<span>${esc(clock(f.at))}</span>`).join('');
  const method = rows[0].method || '';
  const conf = rows[0].confidence || '';
  const body = `
    <div class="chart">${bars}</div>
    <div class="chart-axis">${axis}</div>
    <div class="pills">
      <span class="pill method">${icon('gauge')}${esc(method === 'seasonal_naive_24h' ? 'mevsimsel-naif (24 sa)' : method || 'yöntem bilinmiyor')}</span>
      <span class="pill conf-${esc(conf)}">güven: ${esc(CONFIDENCE_TR[conf] || conf || '—')}</span>
    </div>
    ${best.at ? `<p class="status-ok">${icon('check')}En temiz saat: ${esc(clock(best.at))} · PM10 ${num(best.pm10)}</p>` : ''}
    ${payload.baseline_only ? '<p class="hint">Bu yalnızca temel (baseline) modeldir; eğitilmiş model devreye girdiğinde iki sonuç da raporlanacak.</p>' : ''}`;
  return cardShell({
    id, kind: 'air', icon: 'clock', prov, body,
    title: `Sonraki ${int(payload.horizon_hours || rows.length)} saat`,
    sub: 'PM10 tahmini',
  });
}

/** A real gauge, because "60" means nothing without the scale it sits on. */
function trafficGauge(index) {
  const idx = has(index) ? Math.max(0, Math.min(100, Number(index))) : null;
  const arc = 144.5; // π × 46
  const frac = idx === null ? 0 : idx / 100;
  const colour = idx === null ? 'var(--ink-faint)' : idx >= 80 ? 'var(--bad)' : idx >= 50 ? 'var(--warn)' : 'var(--ok)';
  const angle = Math.PI * (1 - frac);
  const nx = 60 + 34 * Math.cos(angle);
  const ny = 54 - 34 * Math.sin(angle);
  return `<svg viewBox="0 0 120 64" role="img" aria-label="Trafik indeksi ${idx === null ? 'bilinmiyor' : idx}">
    <path class="g-track" d="M14 54 A46 46 0 0 1 106 54"></path>
    <path class="g-val" d="M14 54 A46 46 0 0 1 106 54" style="stroke:${colour};stroke-dasharray:${(frac * arc).toFixed(1)} ${arc}"></path>
    ${idx === null ? '' : `<line class="g-needle" x1="60" y1="54" x2="${nx.toFixed(1)}" y2="${ny.toFixed(1)}"></line>`}
  </svg>`;
}

function trafficCard(payload, prov, id) {
  const idx = payload.index;
  const history = payload.history || [];
  const max = history.reduce((m, p) => Math.max(m, Number(p.index) || 0), 1);
  const bars = history.map((p, i) => {
    const height = Math.max(3, Math.round(((Number(p.index) || 0) / max) * 100));
    const isNow = i === history.length - 1;
    return `<div class="col${isNow ? ' now' : ''}" title="${esc(clock(p.at))} · ${esc(p.index)}"><i style="height:${height}%"></i></div>`;
  }).join('');
  const axisEvery = Math.max(1, Math.ceil(history.length / 6));
  const axis = history.map((p, i) => `<span>${i % axisEvery === 0 ? esc(clock(p.at)) : ''}</span>`).join('');
  const yday = payload.same_hour_yesterday;
  const delta = has(payload.delta) ? Number(payload.delta) : (yday && has(idx) ? Number(idx) - Number(yday.index) : null);
  const deltaCls = delta === null ? 'flat' : delta > 2 ? 'up' : delta < -2 ? 'down' : 'flat';
  const deltaTxt = delta === null ? '' : `${delta > 0 ? '▲' : delta < 0 ? '▼' : '■'} dün aynı saate göre ${int(Math.abs(delta))} puan ${delta > 0 ? 'daha yoğun' : delta < 0 ? 'daha akıcı' : 'aynı'}`;
  const body = `
    <div class="gauge">
      ${trafficGauge(idx)}
      <div class="gauge-read">
        <b>${has(idx) ? int(idx) : '—'}</b>
        <span>${esc(payload.description || payload.label || '')}</span>
        ${deltaTxt ? `<div class="delta ${deltaCls}">${esc(deltaTxt)}</div>` : ''}
      </div>
    </div>
    ${history.length ? `<div class="chart dense">${bars}</div><div class="chart-axis">${axis}</div>` : ''}
    ${metaList([
    '1 akıcı — 99 kilitli',
    yday ? `dün aynı saat: ${int(yday.index)} (${yday.label || ''})` : null,
    has(payload.at) ? `ölçüm saati ${clock(payload.at)}` : null,
  ])}`;
  return cardShell({ id, kind: 'traffic', icon: 'traffic', prov, body, title: 'İstanbul trafik indeksi', sub: 'tüm şehir ortalaması' });
}

function simpleCard(opts) {
  return cardShell({
    id: opts.id, kind: opts.kind || '', icon: opts.icon || 'pin', prov: opts.prov,
    title: opts.title, sub: opts.sub, body: metaList(opts.meta),
  });
}

/* ------------------------------------------------------------------ journeys */

function render(html, points) {
  results.innerHTML = html;
  showOnMap(points || []);
  bindCards();
}

function bindCards() {
  document.querySelectorAll('#results .card').forEach((el) => {
    el.addEventListener('click', () => highlightMarker(el.id));
  });
}

const JOURNEYS = {
  async parking({ place }) {
    const res = await api('/api/parking', { place, radius_km: 1.5, min_free: 1 });
    const parks = res.data.parks || [];
    const ids = parks.map(() => nextCardId());
    render(
      resultHead(`${res.data.near} çevresinde otopark`, `${res.data.count} sonuç · ${num(res.data.radius_km)} km`, res.provenance, res.note)
      + (parks.length
        ? cards(parks.map((p, i) => parkingCard(p, res.provenance, ids[i])).join(''), true)
        : `<p class="callout">Bu yarıçapta boş yeri olan açık otopark bulunamadı.</p>`),
      parks.map((p, i) => ({ lat: p.lat, lon: p.lon, kind: 'park', card: ids[i], label: `${p.name} · ${has(p.empty) ? p.empty : '—'} boş` })),
    );
  },

  async bus({ line }) {
    const res = await api('/api/buses', { line });
    const buses = res.data.buses || [];
    const shown = buses.slice(0, 12);
    const ids = shown.map(() => nextCardId());
    const hint = 'Varış tahmini için durak adı ekleyin — örnek: “500T Şifa Sondurak”.';
    render(
      resultHead(`${res.data.line_code} hattı canlı araçlar`, `${res.data.count} araç`, res.provenance, res.note ? `${res.note} ${hint}` : hint)
      + `<p class="callout">Plaka hiçbir zaman saklanmaz ve gösterilmez; araçlar yalnızca kapı numarasıyla anılır (KVKK).</p>`
      + cards(shown.map((b, i) => busCard(b, res.provenance, ids[i])).join(''), true),
      shown.map((b, i) => ({ lat: b.lat, lon: b.lon, kind: 'bus', card: ids[i], label: `${b.door_no} → ${b.direction || ''}` })),
    );
  },

  async arrivals({ line, stop }) {
    const res = await api('/api/arrivals', { line, stop, limit: 3 });
    const arrivals = res.data.arrivals || [];
    const stopInfo = res.data.stop || {};
    const ids = arrivals.map(() => nextCardId());
    const stopId = nextCardId();
    const body = arrivals.length
      ? cards(arrivals.map((a, i) => arrivalCard(a, res.provenance, ids[i])).join(''), true)
      : cards(diagnosticsCard(res.data.diagnostics, res.provenance, nextCardId()));
    render(
      resultHead(`${res.data.line_code} · ${stopInfo.name || stop}`, arrivals.length ? `${arrivals.length} yaklaşan araç` : 'yaklaşan araç yok', res.provenance, res.note)
      + body
      + (res.data.disclaimer ? `<p class="hint">${esc(res.data.disclaimer)}</p>` : ''),
      [{ lat: stopInfo.lat, lon: stopInfo.lon, kind: 'station', card: stopId, label: stopInfo.name || stop }],
    );
  },

  async metro({ line }) {
    const res = await api('/api/metro', { line });
    const all = res.data.lines || [];
    const wanted = line ? all.filter((l) => (l.line_name || '').toLocaleUpperCase('tr') === line.toLocaleUpperCase('tr')) : all;
    const list = line ? wanted : all;
    render(
      resultHead(line ? `${line} servis durumu` : 'Metro servis duyuruları', `${list.length} duyuru`, res.provenance, res.note)
      + (list.length
        ? cards(list.map((l) => metroCard(l, res.provenance, nextCardId())).join(''))
        : cards(metroClearCard(line, res.provenance, nextCardId())))
      + (line && !wanted.length && all.length
        ? `<p class="callout">Şu anda duyurusu olan hatlar: ${esc(all.map((l) => l.line_name).join(', '))}.</p>` : ''),
      [],
    );
  },

  async station({ name }) {
    const res = await api('/api/metro/station', { name });
    const stations = res.data.stations || [];
    const ids = stations.map(() => nextCardId());
    render(
      resultHead(`${res.data.query} istasyonu`, `${res.data.count} eşleşme`, res.provenance, res.note)
      + (stations.length
        ? cards(stations.map((s, i) => stationCard(s, res.provenance, ids[i])).join(''), true)
        : '<p class="callout">Bu adla bir metro istasyonu bulunamadı.</p>'),
      stations.map((s, i) => ({ lat: s.lat, lon: s.lon, kind: 'station', card: ids[i], label: `${s.name} (${s.line_name})` })),
    );
  },

  async air({ place }) {
    const now = await api('/api/air', { place });
    const airId = nextCardId();
    let forecastHtml = '';
    try {
      const fc = await api('/api/air/forecast', { place, hours: 6 });
      forecastHtml = forecastCard(fc.data, fc.provenance, nextCardId());
    } catch (err) {
      forecastHtml = `<p class="note">Tahmin alınamadı: ${esc(err.message)}</p>`;
    }
    const st = now.data.station || {};
    render(
      resultHead(`${now.data.place} hava kalitesi`, st.name ? `${st.name} istasyonu` : '', now.provenance, now.note)
      + cards(airCard(now.data, now.provenance, airId) + forecastHtml, true),
      [{ lat: st.lat, lon: st.lon, kind: 'air', card: airId, label: `${st.name} ölçüm istasyonu` }],
    );
  },

  async traffic() {
    const res = await api('/api/traffic', { window: 'now' });
    let extra = {};
    try {
      const hist = await api('/api/traffic', { window: '24h' });
      extra = {
        history: hist.data.history || [],
        same_hour_yesterday: hist.data.same_hour_yesterday,
        delta: hist.data.delta,
        description: res.data.description || hist.data.description,
      };
    } catch (err) {
      extra = {};
    }
    render(
      resultHead('Trafik', 'son 24 saat', res.provenance, res.note)
      + cards(trafficCard({ ...res.data, ...extra }, res.provenance, nextCardId())),
      [],
    );
  },

  async stops({ q }) {
    const res = await api('/api/stops', { q });
    const stops = res.data.stops || [];
    const ids = stops.map(() => nextCardId());
    render(
      resultHead(`“${res.data.query}” durakları`, `${res.data.count} durak`, res.provenance, res.note)
      + (stops.length
        ? cards(stops.map((s, i) => simpleCard({
          id: ids[i], kind: 'station', icon: 'stop', prov: res.provenance,
          title: s.name || s.stop_code, sub: s.description || '',
          meta: [`durak kodu ${s.stop_code}`, s.stop_id ? `stop_id ${s.stop_id}` : null],
        })).join(''), true)
        : '<p class="callout">Bu adla bir durak bulunamadı.</p>')
      + '<p class="hint">Varış tahmini için hat kodu ekleyin — örnek: <em>500T Şifa Sondurak</em>.</p>',
      stops.map((s, i) => ({ lat: s.lat, lon: s.lon, kind: 'station', card: ids[i], label: s.name || s.stop_code })),
    );
  },

  async places({ q }) {
    const res = await api('/api/places', { q });
    const matches = res.data.matches || [];
    const ids = matches.map(() => nextCardId());
    render(
      resultHead(`“${res.data.query}” için yerler`, `${matches.length} eşleşme`, res.provenance,
        res.note || 'Otopark, otobüs, metro veya hava kalitesi sormak için soruya bir anahtar kelime ekleyin.')
      + (matches.length
        ? cards(matches.map((p, i) => simpleCard({
          id: ids[i], kind: 'place', icon: 'pin', prov: res.provenance,
          title: p.label || p.name, sub: p.district || '', meta: [p.kind],
        })).join(''), true)
        : '<p class="callout">Bu adla bir yer bulunamadı. Semt, meydan ya da istasyon adı deneyin.</p>'),
      matches.map((p, i) => ({ lat: p.lat, lon: p.lon, kind: 'place', card: ids[i], label: p.label || p.name })),
    );
  },

  async freshness() {
    const res = await api('/api/freshness');
    const sources = res.data.sources || {};
    const items = Object.entries(sources).map(([name, s]) => simpleCard({
      id: nextCardId(), kind: '', icon: 'clock', prov: res.provenance,
      title: sourceLabel(name), sub: s.healthy ? 'sağlıklı' : 'sorunlu',
      meta: [
        `yaş: ${shortAge(s.age_seconds)}`,
        `önbellek isabeti: ${int(s.hits)}`,
        `ıskalama: ${int(s.misses)}`,
        `bayat servis: ${int(s.stale_served)}`,
        `hata: ${int(s.errors)}`,
        s.last_error ? `son hata: ${s.last_error}` : null,
      ],
    }));
    const budget = res.data.request_budget_remaining || {};
    render(
      resultHead('Veri tazeliği', `${items.length} kaynak`, res.provenance, res.note)
      + (Object.keys(budget).length
        ? `<p class="callout">Kalan istek bütçesi — ${esc(Object.entries(budget).map(([k, v]) => `${k}: ${v}`).join(' · '))}. İETT’nin saatlik 100 sınırının altında, 80’de duruyoruz.</p>`
        : '')
      + (items.length ? cards(items.join(''), true) : '<p class="callout">Henüz hiçbir kaynak sorgulanmadı.</p>'),
      [],
    );
  },

  /* Optional endpoint. Hidden behind a 404 until the integrator ships /api/route. */
  async route({ from, to, q }) {
    const res = await probe('/api/route', { from, to, q, origin: from, destination: to });
    if (!res) {
      render('<p class="callout">Güzergâh önerisi bu sürümde yok. Şimdilik trafik indeksi, metro durumu ve otopark doluluğunu ayrı ayrı sorabilirsiniz.</p>', []);
      return;
    }
    const options = res.data.options || res.data.routes || res.data.legs || (Array.isArray(res.data) ? res.data : []);
    render(
      resultHead('Güzergâh önerisi', `${options.length} seçenek`, res.provenance, res.note)
      + (options.length
        ? cards(options.map((o) => simpleCard({
          id: nextCardId(), kind: '', icon: 'route', prov: res.provenance,
          title: o.title || o.mode || o.summary || 'Seçenek',
          sub: o.description || o.detail || '',
          meta: Object.entries(o).filter(([, v]) => typeof v === 'number' || typeof v === 'string').slice(0, 6).map(([k, v]) => `${k}: ${v}`),
        })).join(''), true)
        : `<pre class="hint">${esc(JSON.stringify(res.data, null, 2).slice(0, 1200))}</pre>`),
      [],
    );
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
  // Explicit wording only: an over-eager "from X to Y" pattern would steal ordinary
  // questions, and the route endpoint may not even exist on this server.
  if (/nasıl giderim|nasil giderim|güzergâh|güzergah|rota öner|rota onar/.test(low)) {
    return { journey: 'route', args: { q: text.trim() } };
  }
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
  if (!handler) { await showError(new Error('Bu soruyu nasıl yanıtlayacağımı bilmiyorum.')); return; }
  setBusy(true);
  try {
    await handler(args || {});
  } catch (err) {
    await showError(err);
  } finally {
    setBusy(false);
  }
}

/* ------------------------------------------------------- freshness strip */

function paintFreshness(sources, budget) {
  const rail = $('#strip-rail');
  const meta = $('#strip-meta');
  const pill = $('#live-pill');
  const pillText = $('#live-pill-text');
  const entries = Object.entries(sources || {});
  if (!rail) return;
  if (!entries.length) {
    rail.innerHTML = '<span class="src-chip"><i class="dot"></i>henüz hiçbir kaynak sorgulanmadı</span>';
    if (meta) meta.textContent = 'boşta';
    if (pill) pill.className = 'live-pill';
    if (pillText) pillText.textContent = 'hazır';
    return;
  }
  rail.innerHTML = entries.map(([name, s]) => {
    const cls = s.errors ? 'err' : freshnessClass(s.age_seconds, false);
    return `<span class="src-chip ${cls}" role="listitem" title="${esc(sourceLabel(name))} · ${s.healthy ? 'sağlıklı' : 'sorunlu'}">
      <i class="dot" aria-hidden="true"></i><b>${esc(sourceLabel(name))}</b>
      <span class="num">${esc(shortAge(s.age_seconds))}</span></span>`;
  }).join('');
  const worst = entries.reduce((acc, [, s]) => (s.errors ? acc + 1 : acc), 0);
  if (meta) {
    const left = budget && Object.keys(budget).length
      ? ` · İETT bütçesi ${Object.values(budget)[0]}`
      : '';
    meta.textContent = `${entries.length} kaynak${left}`;
  }
  if (pill && pillText) {
    pill.className = `live-pill ${worst ? 'warn' : 'ok'}`;
    pillText.textContent = worst ? `${worst} kaynakta hata` : 'veri akıyor';
  }
}

async function refreshFreshness(button) {
  if (button) button.classList.add('spin');
  try {
    const res = await api('/api/freshness');
    paintFreshness(res.data.sources, res.data.request_budget_remaining);
  } catch (err) {
    const meta = $('#strip-meta');
    if (meta) meta.textContent = 'okunamadı';
    const pill = $('#live-pill');
    const pillText = $('#live-pill-text');
    if (pill) pill.className = 'live-pill bad';
    if (pillText) pillText.textContent = 'bağlantı yok';
  } finally {
    if (button) button.classList.remove('spin');
  }
}

/* ----------------------------------------------- optional endpoint probes */

function alertText(item) {
  return item.message || item.title || item.headline || item.summary || item.description || item.text || JSON.stringify(item);
}

async function loadAlerts() {
  let res = null;
  try { res = await probe('/api/alerts'); } catch (err) { res = null; }
  const panel = $('#alerts-panel');
  const body = $('#alerts-body');
  if (!panel || !body) return;
  const data = res && res.data;
  const items = !data ? [] : (data.alerts || data.items || (Array.isArray(data) ? data : []));
  if (!items.length) { panel.hidden = true; return; }
  body.innerHTML = items.slice(0, 5).map((item) => `<div class="alert-card">
    ${icon('alert')}
    <div><p>${esc(alertText(item))}</p>${stamp(res.provenance)}</div>
  </div>`).join('');
  panel.hidden = false;
}

const RELIABILITY_TR = {
  mae: 'ortalama mutlak hata', mae_minutes: 'ortalama mutlak hata (dk)', mape: 'ortalama yüzde hata',
  samples: 'örnek sayısı', n: 'örnek sayısı', predictions: 'tahmin sayısı', window: 'pencere',
  method: 'yöntem', updated_at: 'güncellenme', bias_minutes: 'sapma (dk)',
};

async function loadReliability() {
  let res = null;
  try { res = await probe('/api/reliability'); } catch (err) { res = null; }
  const panel = $('#reliability-panel');
  const body = $('#reliability-body');
  if (!panel || !body) return;
  if (!res || !res.data) { panel.hidden = true; return; }
  const flat = Object.entries(res.data).filter(([, v]) => v === null || ['number', 'string', 'boolean'].includes(typeof v));
  if (!flat.length) { panel.hidden = true; return; }
  body.innerHTML = `<div class="kv-grid">${flat.map(([k, v]) => `<div class="stat">
      <div class="k">${esc(RELIABILITY_TR[k] || k)}</div>
      <div class="v">${esc(typeof v === 'number' ? num(v, Number.isInteger(v) ? 0 : 1) : String(v === null ? '—' : v))}</div>
    </div>`).join('')}</div>
    <div style="margin-top:.6rem">${stamp(res.provenance)}</div>`;
  panel.hidden = false;
}

/* ------------------------------------------------------------------- theme */

const THEME_ORDER = ['system', 'light', 'dark'];
const THEME_TR = { system: 'sistem', light: 'açık', dark: 'koyu' };

function readTheme() {
  try { return window.localStorage.getItem('nabiz-theme') || 'system'; } catch (err) { return 'system'; }
}

function applyTheme(mode) {
  const root = document.documentElement;
  if (mode === 'system') root.removeAttribute('data-theme');
  else root.setAttribute('data-theme', mode);
  const btn = $('#theme-toggle');
  if (btn) btn.title = `Tema: ${THEME_TR[mode] || mode}`;
  try { window.localStorage.setItem('nabiz-theme', mode); } catch (err) { /* private mode */ }
}

/* ---------------------------------------------------------------------- boot */

function chipPressed(target) {
  document.querySelectorAll('.chip').forEach((c) => c.setAttribute('aria-pressed', c === target ? 'true' : 'false'));
}

function runFromElement(el) {
  run(el.dataset.journey, {
    place: el.dataset.place,
    line: el.dataset.line,
    stop: el.dataset.stop,
    name: el.dataset.name,
    q: el.dataset.q,
  });
}

document.addEventListener('DOMContentLoaded', () => {
  const version = $('#version');
  if (version && window.NABIZ_VERSION) version.textContent = `sürüm ${window.NABIZ_VERSION}`;
  if (window.NABIZ_ATTRIBUTION) {
    const attr = $('#attribution');
    if (attr) attr.setAttribute('title', window.NABIZ_ATTRIBUTION);
  }

  // ?nomap=1 exercises the "CDN is blocked" path on purpose, without a broken network.
  try {
    const params = new URLSearchParams(window.location.search || '');
    if (params.get('nomap') === '1') mapForcedOff = true;
  } catch (err) { /* older browser: leave the map on */ }

  applyTheme(readTheme());
  const themeBtn = $('#theme-toggle');
  if (themeBtn) {
    themeBtn.addEventListener('click', () => {
      const next = THEME_ORDER[(THEME_ORDER.indexOf(readTheme()) + 1) % THEME_ORDER.length];
      applyTheme(next);
    });
  }

  document.querySelectorAll('.chip').forEach((chip) => {
    chip.addEventListener('click', () => {
      chipPressed(chip);
      const label = chip.querySelector('.chip-label');
      const input = $('#q');
      if (input) input.value = (label ? label.textContent : chip.textContent).trim();
      runFromElement(chip);
    });
  });

  document.querySelectorAll('.journey-tile').forEach((tile) => {
    tile.addEventListener('click', () => { chipPressed(null); runFromElement(tile); });
  });

  const form = $('#ask-form');
  if (form) {
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      chipPressed(null);
      const input = $('#q');
      const parsed = route((input && input.value) || '');
      if (!parsed) return;
      run(parsed.journey, parsed.args);
    });
  }

  const refreshBtn = $('#freshness-refresh');
  if (refreshBtn) refreshBtn.addEventListener('click', () => refreshFreshness(refreshBtn));

  refreshFreshness(null);
  loadAlerts();
  loadReliability();

  // /api/freshness reads cache statistics only — it never touches İBB — so polling it is
  // free for the upstream. Pause while the tab is hidden anyway; a background tab that
  // keeps a server busy is bad manners.
  window.setInterval(() => {
    if (!document.hidden) refreshFreshness(null);
  }, 60000);
});
