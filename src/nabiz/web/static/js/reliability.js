/* Measured headway regularity, shown after a bus question for the lines the collector watches. */

import { probe } from './api.js';
import { UNKNOWN, esc, num, int } from './format.js';
import { stamp } from './provenance.js';

const $ = (sel) => document.querySelector(sel);
let asked = 0; // a probe answered after the next question started must not show its panel

/** Measured headway regularity for the line just asked about; hidden for lines never watched,
 * and hidden again (line null) when the next question starts. */
async function loadReliability(line) {
  const panel = $('#reliability-panel');
  const body = $('#reliability-body');
  if (!panel || !body) return;
  const mine = ++asked;
  if (!line) { panel.hidden = true; return; }
  let res = null;
  try { res = await probe('/api/reliability', { line }); } catch (err) { res = null; }
  if (mine !== asked) return;
  const d = res && res.data;
  if (!d || !(d.observed_lines || []).includes(d.line_code)) { panel.hidden = true; return; }
  const stats = d.available
    ? [
      ['Ortanca sefer aralığı', `${num(d.median_headway_min)} dk`],
      ['Düzenlilik', d.bunching_label || UNKNOWN],
      ['Aralık değişim katsayısı', num(d.headway_cv, 2)],
      ['Aralık gözlemi', int(d.samples)],
      ['Gözlenen araç', int(d.vehicles_seen)],
    ]
    : [];
  body.innerHTML = `<p><b>${esc(d.line_code)}</b>, saat ${esc(String(d.hour).padStart(2, '0'))}:00</p>`
    + (stats.length ? `<dl class="row-grid">${stats.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('')}</dl>` : '')
    + (res.note ? `<p class="panel-note">${esc(res.note)}</p>` : '')
    + `<p>${stamp(res.provenance)}</p>`;
  panel.hidden = false;
}

export { loadReliability };
