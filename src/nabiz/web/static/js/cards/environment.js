/* Air quality now and over the next hours, and the city-wide traffic index (spec 8.2). Pure: the
 * drawings that need a measured width are returned as functions the host calls with it. */

import { UNKNOWN, esc, num, int, has, clock } from '../format.js';
import { icon } from '../icons.js';
import { ageAt, secondsAt } from '../provenance.js';
import { aqiChip, aqiScale, forecastSvg } from '../charts/scale.js';
import { pulseView } from '../charts/pulse-view.js';
import { nextCardId, callout, head, sheet, point, row, facts, details, table, disclaimer, confidence } from './sheet.js';

const POLLUTANTS = [['pm10', 'PM10'], ['no2', 'NO₂'], ['o3', 'O₃'], ['so2', 'SO₂']];
const FORMULA = { PM10: 'PM10', NO2: 'NO₂', O3: 'O₃', SO2: 'SO₂', CO: 'CO' };
const METHOD_TR = { seasonal_naive_24h: 'mevsimsel-naif (24 sa)' };
const LIVE_SECONDS = 7200; // an hourly reading is current for two hours, as on the pen line

function airRow(data, prov, id) {
  const r = data.reading || {};
  const band = data.band || {};
  const aqi = has(r.aqi_index) ? int(r.aqi_index) : null;
  const dl = POLLUTANTS.map(([key, label]) => `<div><dt>${label}</dt><dd>${has(r[key]) ? `${num(r[key])} µg/m³` : UNKNOWN}</dd></div>`);
  const body = `<p class="row-metric"><span>${aqi ? `<span class="row-unit">AQI</span> <span class="row-value">${aqi}</span>`
    : `<span class="row-unit">AQI ${UNKNOWN}</span>`}</span>${band.label ? aqiChip(band.key, band.label) : ''}</p>`
    + aqiScale(r.aqi_index, band.label || UNKNOWN)
    + facts(['AQI, İBB ölçeği (0-500)', r.dominant ? `baskın kirletici ${FORMULA[r.dominant] || r.dominant}` : ''])
    + `<dl class="row-grid">${dl.join('')}</dl>`
    + (r.state ? `<p class="row-sub">${esc(r.state)}</p>` : '')
    + details('AQI nasıl okunur?', '<p>İBB’nin yayımladığı AQI, PM10 için 24 saatlik hareketli ortalamadır ve saatlik değişimi geç '
      + 'yansıtır; şu anki hava için saatlik PM10 derişimine bakın. Bu serviste PM2.5 yayımlanmıyor.</p>');
  const st = data.station || {};
  return row({
    id, kind: 'air', glyph: 'wind', prov, body, map: true,
    title: st.name ? `${st.name} ölçüm istasyonu` : 'Hava kalitesi', sub: has(st.distance_km) ? `${num(st.distance_km)} km uzakta` : '',
  });
}

/** The forecast row; its line is drawn by `draw` once the host knows its width. */
function forecastRow(res, error, id) {
  const base = { id, kind: 'air', glyph: 'clock', title: 'Sonraki saatler', sub: 'PM10 tahmini', i: 1 };
  if (!res) return { html: row({ ...base, body: callout(`Tahmin alınamadı: ${error && error.message ? error.message : UNKNOWN}`) }) };
  const { data, provenance: prov } = res;
  const rows = data.forecast || [];
  if (!data.available || !rows.length) return { html: row({ ...base, prov, body: `<p class="row-sub">${esc(data.note || 'Tahmin üretilemedi.')}</p>` }) };
  const best = data.best_window;
  const input = data.latest && data.latest.at;
  const body = `<figure class="pulse pulse-short"><div class="pulse-plot" data-draw="${id}"></div></figure>`
    + `<p class="row-facts">Yöntem: ${esc(METHOD_TR[rows[0].method] || rows[0].method || UNKNOWN)}. Güven: ${confidence(rows[0].confidence)}</p>`
    + (best ? `<p class="row-ok">${icon('circle-check')} En temiz saat ${esc(clock(best.at))}, PM10 ${num(best.pm10)} µg/m³</p>` : '')
    + (data.note ? `<p class="row-sub">${esc(data.note)}</p>` : '')
    + details('Saatlik tahmin', table([['Saat'], ['PM10, µg/m³', true]],
      `<tbody>${rows.map((f) => `<tr><td>${esc(clock(f.at))}</td><td class="num">${num(f.pm10)}</td></tr>`).join('')}</tbody>`));
  return {
    html: row({ ...base, title: `Sonraki ${int(data.horizon_hours || rows.length)} saat`, prov, body, extra: input ? `girdi ölçümü ${ageAt(prov, input)}` : '' }),
    draw: (width, height) => forecastSvg(data, { width, height, uid: `np-${id}`, current: secondsAt(prov, input) < LIVE_SECONDS }),
  };
}

/** Air now and the forecast, fetched in parallel; the forecast may fail without the reading. */
function airAnswer({ data, provenance: prov, note }, forecast, error) {
  const airId = nextCardId();
  const fcId = nextCardId();
  const fc = forecastRow(forecast, error, fcId);
  const st = data.station || {};
  const band = data.band || {};
  const aqi = data.reading && data.reading.aqi_index;
  return {
    html: head({ title: `${data.place} hava kalitesi`, prov, note }) + sheet(airRow(data, prov, airId) + fc.html)
      + disclaimer(data.disclaimer || 'Sağlık tavsiyesi değildir.'),
    points: [point(st, 'air', airId, `${st.name} ölçüm istasyonu: AQI ${has(aqi) ? int(aqi) : UNKNOWN}`, prov)],
    draw: fc.draw ? { [fcId]: fc.draw } : {},
    say: `${data.place} için AQI ${has(aqi) ? `${int(aqi)}, ${band.label || 'bant bilinmiyor'}` : UNKNOWN}.`,
    prov,
  };
}

/**
 * The traffic answer: the pen line at card size, the same module as the hero, over the 24-hour
 * payload (the hero's own when it is under a minute old). Without it, the "now" reading alone,
 * which the view states as too few readings for a line. `clock` is the time of the render.
 */
function trafficAnswer(now, day, clockMs) {
  const id = nextCardId();
  const res = day || { data: { history: [], now: { index: now.data.index, at: now.data.at } }, provenance: now.provenance };
  const view = pulseView(res, { width: 0, height: 0, uid: `np-${id}`, clock: clockMs });
  const typical = now.data.typical && now.data.typical.description;
  return {
    html: head({ title: 'Trafik', count: '24 saatlik kayıt', prov: now.provenance, note: now.note })
      + sheet(`<article class="card" id="${id}" tabindex="-1"><figure class="pulse pulse-card is-${view.state}">`
        + `<figcaption class="pulse-readout">${view.readout}</figcaption><div class="pulse-plot" data-draw="${id}"></div>`
        + `${details('Saatlik değerler', `<div class="sheet-table">${view.table}</div>`)}</figure>`
        + `${facts(['1 akıcı, 99 kilitli'])}${typical ? `<p class="row-sub">${esc(typical)}</p>` : ''}</article>`),
    points: [],
    draw: { [id]: (width, height, t) => pulseView(res, { width, height, uid: `np-${id}`, clock: t }).svg },
    say: `Trafik indeksi ${[has(now.data.index) ? int(now.data.index) : UNKNOWN, now.data.description].filter(Boolean).join(', ')}.`,
    prov: now.provenance,
  };
}

export { airAnswer, trafficAnswer };
