/* Measured headway regularity, shown after a bus question for the lines the collector watches. */

import { probe } from './api.js';
import { esc, num, int } from './format.js';
import { stamp } from './provenance.js';

const $ = (sel) => document.querySelector(sel);

/** Measured headway regularity for the line just asked about; hidden for lines never watched. */
async function loadReliability(line) {
  const panel = $('#reliability-panel');
  const body = $('#reliability-body');
  if (!panel || !body || !line) return;
  let res = null;
  try { res = await probe('/api/reliability', { line }); } catch (err) { res = null; }
  const d = res && res.data;
  if (!d || !(d.observed_lines || []).includes(d.line_code)) { panel.hidden = true; return; }
  const stats = d.available
    ? [
      ['ortanca sefer aralığı', `${num(d.median_headway_min)} dk`],
      ['düzenlilik', d.bunching_label || '—'],
      ['aralık değişim katsayısı (cv)', num(d.headway_cv, 2)],
      ['aralık gözlemi', int(d.samples)],
      ['gözlenen araç', int(d.vehicles_seen)],
    ]
    : [];
  body.innerHTML = `<p class="sub"><b>${esc(d.line_code)}</b> · saat ${esc(String(d.hour).padStart(2, '0'))}:00</p>`
    + (stats.length ? `<div class="kv-grid">${stats.map(([k, v]) => `<div class="stat">
      <div class="k">${esc(k)}</div><div class="v">${esc(v)}</div>
    </div>`).join('')}</div>` : '')
    + (res.note ? `<p class="note">${esc(res.note)}</p>` : '')
    + `<div style="margin-top:.6rem">${stamp(res.provenance)}</div>`;
  panel.hidden = false;
}

export { loadReliability };
