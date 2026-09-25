/* The pen line as one SVG string, its readout and its hourly table. Pure: the host passes the
 * plot's measured size, an id unique on the page and the clock. Colour only through classes. */

import { esc } from '../format.js';
import { icon } from '../icons.js';
import { stamp, sourceLink } from '../provenance.js';
import { bandOf, clockLabel, dateLabel, dayLabel, pulse } from './pulse-geometry.js';

const WIDE = 640; // room for the band words, the peak and the yesterday label
const TREND_ICONS = { up: 'trending-up', down: 'trending-down', flat: 'equal' };
const f = (n) => n.toFixed(1);
const line = (cls, x1, x2, y1, y2) => `<line class="${cls}" x1="${f(x1)}" x2="${f(x2)}" y1="${f(y1)}" y2="${f(y2)}"></line>`;
const circle = (cls, p, r) => `<circle class="${cls}" cx="${f(p.x)}" cy="${f(p.y)}" r="${r}"></circle>`;

function label(x, y, words, w) {
  const anchor = x < 48 ? 'start' : x > w - 48 ? 'end' : 'middle';
  return `<text class="pulse-axis" x="${f(x)}" y="${f(y)}" text-anchor="${anchor}">${esc(words)}</text>`;
}

function svg(m, w, h, uid, stale) {
  const wide = w >= WIDE;
  const right = w - (wide ? 104 : 12);
  let out = m.guides.map((y) => line('pulse-guide', 1, right, y, y)).join('')
    + m.ticks.map((t) => line('pulse-tick', t.x, t.x, h - 24, h - 20) + label(t.x, h - 4, t.label, w)).join('');
  if (wide) {
    out += m.bands.map((b) => `<text class="pulse-axis${b.current ? ' is-current' : ''}" x="${right + 12}" y="${f(b.y + 4)}">`
      + `${b.label}</text>`).join('');
  }
  if (m.path) {
    const { now, yesterday: yd, gap, peak } = m;
    out += `<defs><linearGradient id="${uid}-ink" gradientUnits="userSpaceOnUse" x1="0" x2="0" `
      + `y1="${f(m.ramp[0])}" y2="${f(m.ramp[1])}">`
      + '<stop class="pulse-ink-low" offset="0"></stop><stop class="pulse-ink-high" offset="1"></stop></linearGradient></defs>';
    if (yd) {
      out += line('pulse-ref', yd.x1, yd.x2, yd.y, yd.y);
      const words = `${m.state === 'archive' ? 'önceki gün' : 'dün'} bu saat ${yd.v}`;
      if (wide && yd.side) out += label(yd.x1 + 4, yd.side === 'above' ? yd.y - 6 : yd.y + 14, words, w);
    }
    if (gap && gap.x2 - gap.x1 >= 1) out += line('pulse-gap', gap.x1, gap.x2, gap.y, gap.y);
    if (wide) out += label(peak.x, peak.y - 10, `en yoğun ${peak.v}, ${clockLabel(peak.t)}`, w);
    // The accent is for a current reading only, and only a live one fresh from İBB breathes.
    out += `<g class="pulse-paper"><path class="pulse-line" pathLength="1" stroke="url(#${uid}-ink)" d="${m.path}"></path>`
      + `<g class="pulse-now">${circle('pulse-halo', now, 8)}${m.state === 'live' && !stale ? circle('pulse-ring', now, 5) : ''}`
      + `${circle(`pulse-dot${m.state === 'live' ? '' : ' is-old'}`, now, 5)}</g></g>`;
  }
  return `<svg viewBox="0 0 ${w} ${h}" role="img" aria-labelledby="${uid}-t ${uid}-d" focusable="false">`
    + `<title id="${uid}-t">${esc(m.title)}</title><desc id="${uid}-d">${esc(m.description)}</desc>${out}</svg>`;
}

function readout(res, m, failed) {
  const last = m.points[m.points.length - 1];
  const note = (html) => `<span class="pulse-note">${html}</span>`;
  const parts = ['<span class="pulse-label">Trafik indeksi, tüm şehir</span>',
    `<span class="pulse-reading"><span class="pulse-value">${last ? last.v : ''}</span>`
    + `<span class="pulse-band">${last ? bandOf(last.v) : ''}</span></span>`];
  if (!res) {
    if (failed) {
      parts.push(note('Trafik verisi şu an alınamadı.'), '<span><button type="button" class="btn" data-retry>Tekrar dene</button></span>');
    }
    return parts.join('');
  }
  const data = res.data || {};
  const yd = data.same_hour_yesterday;
  if (last && yd && Number.isInteger(yd.index)) {
    const d = Number.isFinite(data.delta) ? data.delta : last.v - yd.index;
    const change = d ? `${Math.abs(d)} puan daha ${d > 0 ? 'yoğun' : 'akıcı'}.` : 'Aynı düzeyde.';
    parts.push(note(`${icon(TREND_ICONS[d > 0 ? 'up' : d < 0 ? 'down' : 'flat'])} `
      + `${m.state === 'archive' ? 'Önceki gün' : 'Dün'} bu saatte ${esc(yd.index)}. ${change}`));
  }
  if (m.state === 'archive') parts.push(note(`Son ölçüm ${dateLabel(last.t)}. Çizgi o güne ait, canlı değil.`));
  if (m.state === 'insufficient') parts.push(note('Çizgi için yeterli ölçüm yok.'));
  return parts.concat(`<span>${stamp(res.provenance)}</span>`, `<span>${sourceLink(res.provenance)}</span>`).join('');
}

/** The line's numbers as rows; the day is written where it changes. */
function hourlyTable(points) {
  let day = '';
  const rows = points.map((p) => {
    const when = dayLabel(p.t) === day ? clockLabel(p.t) : dateLabel(p.t);
    day = dayLabel(p.t);
    return `<tr><td>${when}</td><td class="num">${p.v}</td><td>${bandOf(p.v)}</td></tr>`;
  }).join('');
  const head = '<thead><tr><th scope="col">Saat</th><th scope="col" class="num">İndeks</th><th scope="col">Bant</th></tr></thead>';
  return rows ? `<table>${head}<tbody>${rows}</tbody></table>` : '<p>Henüz ölçüm yok.</p>';
}

/** One render. `res` is the traffic answer, or null while it loads or after it failed. Nothing
 * is drawn at width 0: a plot measured before layout would put the line at its left edge. */
function pulseView(res, { width, height, uid, clock, failed }) {
  // Band words take 104 px at the right from 640 px; ticks take 24 at the bottom, labels 18 at the top.
  const box = { left: 1, top: 18, width: Math.max(0, width - (width >= WIDE ? 105 : 13)), height: Math.max(0, height - 42) };
  const m = pulse(res && res.data, res && res.provenance, box, clock);
  const stale = Boolean(res && res.provenance && res.provenance.stale);
  return {
    state: res ? m.state : failed ? 'error' : 'loading',
    svg: width > 0 && height > 0 ? svg(m, width, height, uid, stale) : '',
    readout: readout(res, m, failed),
    table: hourlyTable(m.points),
  };
}

export { pulseView };
