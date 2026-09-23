/* The "Veri tazeliği" strip and the status pill, from /api/freshness (cache statistics, never
 * İBB). Ages are data_age_seconds: a 14-day-old reading read a minute ago is 14 days old.
 * "veri akıyor" needs data under two hours old, the pen line's "live" state. */

import { api } from './api.js';
import { esc, shortAge } from './format.js';
import { sourceLabel, freshnessClass } from './provenance.js';

const $ = (sel) => document.querySelector(sel);
const LIVE_SECONDS = 7200;

function paintPill(cls, text) {
  const pill = $('#live-pill');
  const pillText = $('#live-pill-text');
  if (pill) pill.className = `live-pill${cls ? ' ' + cls : ''}`;
  if (pillText) pillText.textContent = text;
}

function paintFreshness(sources, budget) {
  const rail = $('#strip-rail');
  const meta = $('#strip-meta');
  const entries = Object.entries(sources || {});
  if (!rail) return;
  if (!entries.length) {
    rail.innerHTML = '<span class="src-chip"><i class="dot"></i>henüz hiçbir kaynak sorgulanmadı</span>';
    if (meta) meta.textContent = 'boşta';
    paintPill('', 'hazır');
    return;
  }
  rail.innerHTML = entries.map(([name, s]) => {
    const age = s.data_age_seconds;
    const cls = s.errors ? 'err' : freshnessClass(age, false);
    const read = Number.isFinite(s.age_seconds) ? `son okuma ${shortAge(s.age_seconds)} önce` : 'hiç okunamadı';
    return `<span class="src-chip ${cls}" role="listitem" title="${esc(read)}, ${s.healthy ? 'sağlıklı' : 'sorunlu'}${s.last_error ? '. ' + esc(s.last_error) : ''}">
      <i class="dot" aria-hidden="true"></i><b>${esc(sourceLabel(name))}</b>
      <span class="num">${Number.isFinite(age) ? `veri ${esc(shortAge(age))}` : 'hiç alınamadı'}</span></span>`;
  }).join('');
  const worst = entries.reduce((acc, [, s]) => (s.errors ? acc + 1 : acc), 0);
  if (meta) {
    const left = budget && Object.keys(budget).length ? `, İETT istek hakkı ${Object.values(budget)[0]}` : '';
    meta.textContent = `${entries.length} kaynak${left}`;
  }
  const newest = Math.min(...entries.map(([, s]) => s.data_age_seconds).filter(Number.isFinite));
  if (worst) paintPill('warn', `${worst} kaynakta hata`);
  else if (newest < LIVE_SECONDS) paintPill('ok', 'veri akıyor');
  else paintPill('', Number.isFinite(newest) ? `bağlı, en yeni veri ${shortAge(newest)} önce` : 'bağlı, veri yok');
}

async function refreshFreshness(button) {
  if (button) button.classList.add('spin');
  try {
    const res = await api('/api/freshness');
    paintFreshness(res.data.sources, res.data.request_budget_remaining);
  } catch (err) {
    const meta = $('#strip-meta');
    if (meta) meta.textContent = 'okunamadı';
    paintPill('bad', 'bağlantı yok');
  } finally {
    if (button) button.classList.remove('spin');
  }
}

export { refreshFreshness };
