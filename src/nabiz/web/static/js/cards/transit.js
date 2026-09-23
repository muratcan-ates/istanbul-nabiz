/* Bus answers: arrival estimates with their method, the diagnostics when there is none, and live
 * vehicles by door number, never by plate. Pure. */

import { esc, num, int, has, CONFIDENCE_TR } from '../format.js';
import { icon } from '../icons.js';
import { cardShell, metaList } from './shell.js';

const METHOD_TR = { stop_sequence: 'durak sırası', distance: 'kuş uçuşu mesafe', schedule: 'ilan edilen sefer' };
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

export { arrivalCard, diagnosticsCard, busCard };
