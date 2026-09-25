/* Scales drawn with the one pen (spec 12.3): the AQI band scale, the occupancy line and the PM10
 * forecast line. Fixed domains from the source's own scale, colour only through classes and
 * tokens. Pure: sizes, ids and data come in as arguments. */

import { esc, has, int, num, clock } from '../format.js';

/* The server's AQI bands (ibb_mcp.models.AQI_BANDS): upper bounds, and the token each one takes. */
const AQI_BREAKS = [0, 50, 100, 150, 200, 300, 500];
const AQI_KEYS = ['good', 'moderate', 'unhealthy_sensitive', 'unhealthy', 'very_unhealthy', 'hazardous'];

/** 0 to 1 along six equal segments, linear inside the value's band; a band is "up to and
 * including" its upper bound, as on the server. */
function aqiPosition(aqi) {
  const v = Math.min(Math.max(Number(aqi), 0), 500);
  const band = Math.max(0, AQI_BREAKS.findIndex((upper, k) => k > 0 && v <= upper) - 1);
  const [lo, hi] = [AQI_BREAKS[band], AQI_BREAKS[band + 1]];
  return (band + (v - lo) / (hi - lo)) / AQI_KEYS.length;
}

const bandVars = (key) => `--band:var(--aqi-${key});--band-ink:var(--aqi-${key}-ink);--band-text:var(--aqi-${key}-text)`;

/** The band chip beside the number: the band's name on its colour, never the colour as text. */
function aqiChip(key, label) {
  return `<span class="badge badge-aqi"${AQI_KEYS.includes(key) ? ` style="${bandVars(key)}"` : ''}>${esc(label)}</span>`;
}

function aqiScale(aqi, label) {
  const segments = AQI_KEYS.map((key) => `<i class="scale-seg" style="${bandVars(key)}"></i>`).join('');
  const tick = has(aqi) && Number.isFinite(Number(aqi)) ? `<i class="scale-tick" style="--x:${aqiPosition(aqi).toFixed(4)}"></i>` : '';
  const words = tick ? `AQI ${int(aqi)}, ${label} bandı, 0 ile 500 arası ölçekte` : 'AQI bilinmiyor, 0 ile 500 arası ölçek';
  return `<div class="scale" role="img" aria-label="${esc(words)}">${segments}${tick}</div>`
    + `<div class="scale-marks" aria-hidden="true">${AQI_BREAKS.map((b) => `<span>${b}</span>`).join('')}</div>`;
}

/** How full a lot is: a hairline from 0 to 100 % and an ink stroke drawn with scaleX, never width. */
function occupancy(capacity, empty) {
  // has() first: Number(null) is 0, which would draw an unknown lot as full.
  const known = capacity > 0 && has(empty) && Number.isFinite(Number(empty));
  const share = known ? Math.min(Math.max((capacity - empty) / capacity, 0), 1) : null;
  if (share === null) return { share, html: '' };
  return {
    share,
    html: `<div class="scale-occ" style="--share:${share.toFixed(4)}" role="img" `
      + `aria-label="Doluluk %${Math.round(share * 100)}, ${int(capacity)} yerlik otopark"></div>`,
  };
}

const f = (n) => n.toFixed(1);

/**
 * The PM10 forecast as a line: the measured input is a solid disc (the accent only while it is
 * under two hours old, archive ink otherwise), the six forecast hours a dashed line, the cleanest
 * hour ringed. Y runs from 0 to at least 50 µg/m³ so a clean day looks clean. Nothing at width 0.
 */
function forecastSvg(data, { width, height, uid, current }) {
  const start = data.latest && { t: Date.parse(data.latest.at), v: data.latest.pm10 };
  const pts = [start, ...(data.forecast || []).map((p) => ({ t: Date.parse(p.at), v: p.pm10 }))]
    .filter((p) => p && Number.isFinite(p.t) && Number.isFinite(p.v));
  if (!(width > 0 && height > 0) || pts.length < 2 || pts[0] !== start) return '';
  const top = Math.max(50, ...pts.map((p) => p.v));
  const [t0, t1] = [pts[0].t, pts[pts.length - 1].t];
  const x = (t) => 8 + ((t - t0) / (t1 - t0 || 1)) * (width - 16);
  const y = (v) => 8 + (1 - v / top) * (height - 32);
  const best = data.best_window && pts.find((p) => p.t === Date.parse(data.best_window.at));
  const at = (p) => clock(new Date(p.t).toISOString());
  const labels = pts.map((p, i) => `<text class="pulse-axis" x="${f(x(p.t))}" y="${height - 4}" `
    + `text-anchor="${i ? i === pts.length - 1 ? 'end' : 'middle' : 'start'}">${at(p)}</text>`).join('');
  const lo = pts.slice(1).reduce((a, b) => (b.v < a.v ? b : a));
  const hi = pts.slice(1).reduce((a, b) => (b.v > a.v ? b : a));
  const desc = `Ölçülen PM10 ${num(start.v)} µg/m³ (${at(start)}). Tahmin en düşük ${num(lo.v)} (${at(lo)}), `
    + `en yüksek ${num(hi.v)} (${at(hi)}).`;
  return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-labelledby="${uid}-t ${uid}-d" focusable="false">`
    + `<title id="${uid}-t">PM10 tahmini, µg/m³</title><desc id="${uid}-d">${esc(desc)}</desc>`
    + `<line class="pulse-guide" x1="0" x2="${width}" y1="${f(y(0))}" y2="${f(y(0))}"></line>${labels}`
    + `<path class="pulse-forecast" d="M${pts.map((p) => `${f(x(p.t))},${f(y(p.v))}`).join('L')}"></path>`
    + (best ? `<circle class="pulse-best" cx="${f(x(best.t))}" cy="${f(y(best.v))}" r="7"></circle>` : '')
    + `<circle class="pulse-dot${current ? '' : ' is-old'}" cx="${f(x(start.t))}" cy="${f(y(start.v))}" r="4"></circle></svg>`;
}

export { AQI_KEYS, aqiPosition, aqiChip, aqiScale, occupancy, forecastSvg };
