/* Air quality now and over the next hours, and the city-wide traffic index. Pure. */

import { esc, num, int, has, clock, CONFIDENCE_TR } from '../format.js';
import { icon } from '../icons.js';
import { cardShell, metaList } from './shell.js';

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
        <div class="aqi-band" style="border-color:${esc(colour)}">${esc(band.label || 'Bilinmiyor')}</div>
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
  // The bars are a picture; this table is the same 24 numbers for a screen reader.
  const table = `<table class="sr-only"><caption>Saatlik trafik indeksi</caption><tr><th scope="col">Saat</th><th scope="col">İndeks</th></tr>${
    history.map((p) => `<tr><td>${esc(clock(p.at))}</td><td>${esc(p.index)}</td></tr>`).join('')}</table>`;
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
    ${history.length ? `<div class="chart dense" aria-hidden="true">${bars}</div><div class="chart-axis" aria-hidden="true">${axis}</div>${table}` : ''}
    ${metaList([
    '1 akıcı, 99 kilitli',
    // Against the median of the same weekday and hour; says so when there is no norm yet.
    payload.typical && payload.typical.description ? payload.typical.description : null,
    yday ? `dün aynı saat: ${int(yday.index)} (${yday.label || ''})` : null,
    has(payload.at) ? `ölçüm saati ${clock(payload.at)}` : null,
  ])}`;
  return cardShell({ id, kind: 'traffic', icon: 'traffic', prov, body, title: 'İstanbul trafik indeksi', sub: 'tüm şehir ortalaması' });
}

export { airCard, forecastCard, trafficCard };
