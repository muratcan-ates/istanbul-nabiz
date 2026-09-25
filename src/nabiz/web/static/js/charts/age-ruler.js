/* The "Veri tazeliği" ruler: each source's data_age_seconds on one log axis, "şimdi" at the
 * right, 60 days at the left. Pure: the host passes /api/freshness's sources and the track's
 * width. Why each rule: docs/design/README.md, "Age ruler". */

import { esc, shortAge } from '../format.js';
import { icon } from '../icons.js';
import { sourceLabel } from '../provenance.js';

const MAX_AGE = 60 * 86400;
const TICKS = [[0, 'şimdi'], [60, '1 dk'], [600, '10 dk'], [3600, '1 sa'], [86400, '1 gün'], [604800, '1 hafta'],
  [2592000, '30 gün'], [MAX_AGE, '60 gün']];
const NARROW = ['şimdi', '10 dk', '1 sa', '1 gün', '60 gün']; // the labels a phone has room for
const FAMILY = { iett: 'İETT', metro: 'Metro', aq: 'Hava kalitesi', nabiz: 'Nabız' };

/** 0 at "şimdi" (10 s and younger), 1 at 60 days and older. */
const ageFraction = (s) => (Math.log10(Math.min(Math.max(s, 10), MAX_AGE)) - 1) / (Math.log10(MAX_AGE) - 1);
const pct = (s) => `${(100 - 100 * ageFraction(s)).toFixed(2)}%`;

function axisSvg(wide) {
  const ticks = TICKS.map(([s, words], i) => `<line class="ruler-line" x1="${pct(s)}" x2="${pct(s)}" y1="20" y2="28"></line>`
    + (wide || NARROW.includes(words) ? `<text class="ruler-label" x="${pct(s)}" y="12" `
      + `text-anchor="${i ? i === TICKS.length - 1 ? 'start' : 'middle' : 'end'}">${words}</text>` : '')).join('');
  return '<svg class="ruler-axis" aria-hidden="true" focusable="false">'
    + `<line class="ruler-line" x1="0" x2="100%" y1="24" y2="24"></line>${ticks}</svg>`;
}

function ageWords(s) {
  if (!Number.isFinite(s.data_age_seconds)) return 'hiç alınamadı';
  return s.data_age_seconds > MAX_AGE ? '60 gün+' : `${shortAge(s.data_age_seconds)} önce`;
}

function sentence(it) {
  const read = Number.isFinite(it.s.age_seconds) ? `, son okuma ${shortAge(it.s.age_seconds)} önce` : '';
  return `${it.label}: ${ageWords(it.s)}${read}, ${it.s.healthy ? 'sağlıklı' : 'sorunlu'}.`;
}

/**
 * One <li> per mark. Sources closer than 14 px merge ("İETT (3)"); a source never read is not
 * drawn, one that only ever failed sits at the far left as "hiç alınamadı". Labels take the
 * first of three rows where they fit; one that fits none is left to screen readers.
 */
function rulerMarks(sources, width, wide) {
  const items = Object.entries(sources || {})
    .filter(([, s]) => Number.isFinite(s.data_age_seconds) || s.errors > 0)
    .map(([name, s]) => ({
      name, s, label: sourceLabel(name), x: Number.isFinite(s.data_age_seconds) ? 1 - ageFraction(s.data_age_seconds) : 0,
    }))
    .sort((a, b) => a.x - b.x || a.name.localeCompare(b.name));
  const groups = [];
  items.forEach((it) => {
    const open = groups[groups.length - 1];
    // Only the desktop axis carries labels; a phone lists every source on its own line.
    if (open && wide && (it.x - open[0].x) * width < 14) open.push(it);
    else groups.push([it]);
  });
  const rowEnds = [-Infinity, -Infinity, -Infinity];
  return groups.map((group, g) => {
    const x = group.reduce((sum, it) => sum + it.x, 0) / group.length;
    const families = new Set(group.map((it) => it.name.split('_')[0]));
    // Merged marks sit within 14 px on a log axis, so the newest member's age stands for them.
    const words = `${group.length === 1 ? group[0].label : `${(families.size === 1 && FAMILY[[...families][0]]) || 'Kaynak'} `
      + `(${group.length})`}: ${ageWords(group[group.length - 1].s)}`;
    const bad = group.some((it) => !it.s.healthy);
    const px = x * width;
    const w = words.length * 6.5 + (bad ? 20 : 0);
    const place = px + w / 2 > width ? 'is-end' : px - w / 2 < 0 ? 'is-start' : '';
    const left = { 'is-end': px - w, 'is-start': px }[place] ?? px - w / 2;
    const row = rowEnds.findIndex((end) => end + 8 <= left);
    if (row >= 0) rowEnds[row] = left + w;
    // The accent means "current": the newest mark only, and only for healthy data under 2 h old.
    const live = g === groups.length - 1 && group.some((it) => it.s.healthy && it.s.data_age_seconds < 7200);
    const cls = ['ruler-mark', place, bad && 'is-unhealthy', live && 'is-now'].filter(Boolean).join(' ');
    const shown = row >= 0 || !wide ? `<span aria-hidden="true">${bad ? icon('alert-triangle') : ''}${esc(words)}</span>` : '';
    return `<li class="${cls}" style="--x:${x.toFixed(4)};--row:${wide ? Math.max(row, 0) : 0}"><span class="ruler-pin"></span>`
      + `${shown}<span class="sr-only">${esc(group.map(sentence).join(' '))}</span></li>`;
  }).join('');
}

/** The same facts as rows, for anyone who does not read the axis. */
function rulerTable(sources) {
  const rows = Object.entries(sources || {}).map(([name, s]) => `<tr><th scope="row">${esc(sourceLabel(name))}</th>`
    + `<td>${ageWords(s)}</td><td>${Number.isFinite(s.age_seconds) ? `${shortAge(s.age_seconds)} önce` : 'hiç'}</td>`
    + `<td>${s.healthy ? 'sağlıklı' : `sorunlu${s.last_error ? `: ${esc(s.last_error)}` : ''}`}</td></tr>`).join('');
  return rows ? '<table><thead><tr><th scope="col">Kaynak</th><th scope="col">Veri yaşı</th><th scope="col">Son okuma</th>'
    + `<th scope="col">Durum</th></tr></thead><tbody>${rows}</tbody></table>` : '';
}

export { TICKS, ageFraction, axisSvg, rulerMarks, rulerTable };
