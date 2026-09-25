/* The pen line's geometry from /api/traffic?window=24h. Pure: the clock is an argument, so the
 * same readings always give the same drawing. Why each rule: docs/design/README.md, "Pen line". */

import { shortAge } from '../format.js';

const HOUR = 3600000;
const WINDOW = 24 * HOUR;
const GAP = 90 * 60000; // a missing hourly reading breaks the line; it is never bridged
// İBB's 1 to 99 scale and the server's band words (ibb_mcp.models.describe_traffic).
const BANDS = [[20, 'akıcı'], [40, 'hafif yoğun'], [60, 'yoğun'], [80, 'çok yoğun'], [99, 'kilitli']];

const valid = (v) => Number.isInteger(v) && v >= 1 && v <= 99; // İBB's 0 means "no reading"
const bandOf = (v) => (valid(v) ? BANDS.find(([max]) => v <= max)[1] : '');
const fmt = (opts) => new Intl.DateTimeFormat('tr-TR', { timeZone: 'Europe/Istanbul', ...opts });
const hourFmt = fmt({ hour: '2-digit', minute: '2-digit' });
const dayFmt = fmt({ day: 'numeric', month: 'long' });
const clockLabel = (t) => hourFmt.format(t);
const dayLabel = (t) => dayFmt.format(t);
const dateLabel = (t) => `${dayLabel(t)} ${clockLabel(t)}`;

function readings(data) {
  const raw = ((data && data.history) || []).map((p) => ({ t: Date.parse(p.at), v: p.index }));
  if (data && data.now) raw.push({ t: Date.parse(data.now.at_utc || data.now.at), v: data.now.index });
  return raw
    .filter((p) => Number.isFinite(p.t) && valid(p.v))
    .sort((a, b) => a.t - b.t)
    .filter((p, i, all) => i === 0 || p.t !== all[i - 1].t);
}

/** An hourly source is current for 2 h; an age nobody knows is archive, never live. */
function stateOf(provenance) {
  const age = provenance ? Number(provenance.age_seconds) : NaN;
  if (!Number.isFinite(age) || age >= 86400) return 'archive';
  return age < 7200 ? 'live' : 'delayed';
}

/** Monotone cubic tangents (d3-shape's curveMonotoneX), so no segment overshoots a reading. */
function tangents(px) {
  const n = px.length;
  const h = [];
  const s = [];
  for (let i = 0; i < n - 1; i += 1) {
    h.push(px[i + 1].x - px[i].x);
    s.push((px[i + 1].y - px[i].y) / (h[i] || 1));
  }
  const m = [0];
  for (let i = 1; i < n - 1; i += 1) {
    const p = (s[i - 1] * h[i] + s[i] * h[i - 1]) / (h[i - 1] + h[i]);
    m.push((Math.sign(s[i - 1]) + Math.sign(s[i])) * Math.min(Math.abs(s[i - 1]), Math.abs(s[i]), 0.5 * Math.abs(p)) || 0);
  }
  m[0] = n > 2 ? (3 * s[0] - m[1]) / 2 : s[0];
  m.push(n > 2 ? (3 * s[n - 2] - m[n - 2]) / 2 : s[0]);
  return m;
}

const f1 = (n) => n.toFixed(1);

function segment(px) {
  let d = `M${f1(px[0].x)},${f1(px[0].y)}`;
  if (px.length < 2) return d;
  const m = tangents(px);
  for (let i = 0; i < px.length - 1; i += 1) {
    const a = px[i];
    const b = px[i + 1];
    const dx = (b.x - a.x) / 3;
    d += `C${f1(a.x + dx)},${f1(a.y + dx * m[i])} ${f1(b.x - dx)},${f1(b.y - dx * m[i + 1])} ${f1(b.x)},${f1(b.y)}`;
  }
  return d;
}

/** The <desc> sentence. It gives the data's age in every state but live; only a live line may
 * say "Son 24 saatte". */
function describe(points, data, st, provenance) {
  const age = provenance && (provenance.age
    || (Number.isFinite(provenance.age_seconds) ? `${shortAge(provenance.age_seconds)} önce` : ''));
  const dated = age ? ` Veri ${age} ölçüldü.` : '';
  if (points.length < 2) return `Çizgi için yeterli ölçüm yok.${st === 'live' ? '' : dated}`;
  const lo = points.reduce((a, b) => (b.v < a.v ? b : a));
  const hi = points.reduce((a, b) => (b.v > a.v ? b : a));
  const last = points[points.length - 1];
  const range = `trafik indeksi en düşük ${lo.v} (${clockLabel(lo.t)}), en yüksek ${hi.v} (${clockLabel(hi.t)}).`
    + ` Son ölçüm ${last.v}, ${bandOf(last.v)}.`;
  const yd = data && data.same_hour_yesterday && valid(data.same_hour_yesterday.index) ? data.same_hour_yesterday.index : null;
  if (st === 'archive') {
    return `Son ölçüm ${dateLabel(last.t)}; çizgi o güne ait, canlı değil. O güne kadarki 24 saatte ${range}`
      + (yd === null ? '' : ` Önceki gün aynı saatte ${yd}.`);
  }
  const ydText = yd === null ? '' : ` Dün aynı saatte ${yd}.`;
  return st === 'live' ? `Son 24 saatte ${range}${ydText}` : `Çizgideki ölçümlerde ${range}${ydText}${dated}`;
}

/**
 * Everything the view draws, in the box's pixels. X is true time: a live or delayed window ends
 * at the clock, so the empty stretch after the last reading is the data's age; an archive window
 * ends at its last reading. Y is İBB's fixed 1 to 99, never auto-scaled.
 */
function pulse(data, provenance, box, clock) {
  const all = readings(data);
  let st = stateOf(provenance);
  const lastT = all.length ? all[all.length - 1].t : clock;
  const t1 = st === 'archive' ? lastT : Math.max(clock, lastT);
  const t0 = t1 - WINDOW;
  const x = (t) => box.left + ((t - t0) / WINDOW) * box.width;
  const y = (v) => box.top + (1 - (v - 1) / 98) * box.height;
  const points = all.filter((p) => p.t >= t0 && p.t <= t1);
  if (points.length < 2) st = 'insufficient';
  const ticks = [];
  // Local 00, 06, 12 and 18; Türkiye has been UTC+3 all year since 2016.
  for (let t = Math.ceil((t0 + 3 * HOUR) / (6 * HOUR)) * 6 * HOUR - 3 * HOUR; t <= t1; t += 6 * HOUR) {
    ticks.push({ x: x(t), label: clockLabel(t) });
  }
  const model = {
    state: st,
    points,
    title: st === 'live' ? 'Trafik indeksi, son 24 saat' : 'Trafik indeksi, 24 saatlik kayıt',
    description: describe(points, data, st, provenance),
    guides: BANDS.slice(0, -1).map(([max]) => y(max)),
    bands: BANDS.map(([max, label], i) => ({ label, y: y(((i ? BANDS[i - 1][0] + 1 : 1) + max) / 2) })),
    ticks,
  };
  if (st === 'insufficient') return model;
  const runs = [];
  points.forEach((p, i) => {
    if (i === 0 || p.t - points[i - 1].t > GAP) runs.push([]);
    runs[runs.length - 1].push({ x: x(p.t), y: y(p.v) });
  });
  const last = points[points.length - 1];
  const hi = points.reduce((a, b) => (b.v > a.v ? b : a));
  const yd = data.same_hour_yesterday;
  const ydT = yd && valid(yd.index) ? Date.parse(yd.at_utc || yd.at) : NaN;
  model.bands.forEach((b) => { b.current = b.label === bandOf(last.v); });
  let yesterday = null;
  if (Number.isFinite(ydT)) {
    // The label goes above the rule if the line leaves room, else below, else nowhere.
    const x1 = Math.max(box.left, x(ydT));
    const ry = y(yd.index);
    const near = runs.flat().filter((p) => p.x >= x1 - 8 && p.x <= x1 + 120);
    const clear = (top, bottom) => near.every((p) => p.y < top || p.y > bottom);
    yesterday = { x1, x2: x(last.t), y: ry, v: yd.index, side: clear(ry - 20, ry) ? 'above' : clear(ry, ry + 20) ? 'below' : '' };
  }
  return Object.assign(model, {
    path: runs.map(segment).join(''),
    subpaths: runs.length,
    ramp: [y(1), y(99)],
    now: { x: x(last.t), y: y(last.v) },
    peak: { x: x(hi.t), y: y(hi.v), v: hi.v, t: hi.t },
    yesterday,
    gap: st === 'archive' ? null : { x1: x(last.t), x2: x(t1), y: y(last.v) },
  });
}

export { bandOf, clockLabel, dateLabel, dayLabel, readings, stateOf, describe, pulse };
