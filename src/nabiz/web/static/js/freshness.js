/* The "Veri tazeliği" ruler and the status pill, from /api/freshness (cache statistics, never
 * İBB). Both read data_age_seconds: a 14-day-old reading read a minute ago is 14 days old, so
 * "veri akıyor" needs some source's data under two hours old, the pen line's "live". */

import { api } from './api.js';
import { axisSvg, rulerMarks, rulerTable } from './charts/age-ruler.js';
import { shortAge } from './format.js';

const $ = (sel) => document.querySelector(sel);
const LIVE_SECONDS = 7200;
const wideQuery = window.matchMedia('(min-width: 768px)');
let lastPainted = 0;

function paintPill(cls, text) {
  const pill = $('#live-pill');
  const pillText = $('#live-pill-text');
  if (pill) {
    pill.className = cls;
    // The live dot rings once per successful check; only a live dot, because the accent means "current".
    if (cls === 'ok') { pill.classList.remove('is-pinged'); void pill.offsetWidth; pill.classList.add('is-pinged'); }
  }
  if (pillText) pillText.textContent = text;
}

function paintRuler(sources, budget) {
  const track = $('#freshness-strip .ruler-track');
  const rail = $('#strip-rail');
  const meta = $('#strip-meta');
  const entries = Object.entries(sources || {});
  if (!track || !rail) return;
  rail.style.opacity = '';
  rail.innerHTML = entries.length
    ? rulerMarks(sources, track.clientWidth, wideQuery.matches)
    : '<li>Henüz hiçbir kaynak sorgulanmadı. İlk soru bu cetveli doldurur.</li>';
  const table = $('#ruler-table .sheet-table');
  if (table) table.innerHTML = rulerTable(sources);
  const count = $('#ruler-table summary span');
  if (count) count.textContent = `(${entries.length})`;
  if (meta) {
    const left = budget && Object.keys(budget).length ? `, İETT istek hakkı ${Object.values(budget)[0]}` : '';
    meta.textContent = `${entries.length} kaynak${left}`;
  }
  lastPainted = Date.now();
  if (!entries.length) { paintPill('', 'hazır'); return; }
  const failing = entries.filter(([, s]) => s.errors && !s.healthy).length;
  const newest = Math.min(...entries.map(([, s]) => s.data_age_seconds).filter(Number.isFinite));
  if (failing) paintPill('warn', `${failing} kaynakta hata`);
  else if (newest < LIVE_SECONDS) paintPill('ok', 'veri akıyor');
  else paintPill('', Number.isFinite(newest) ? `bağlı, en yeni veri ${shortAge(newest)} önce` : 'bağlı, veri yok');
}

/** Called at boot, every 60 s while visible, after every answer and by the refresh button. */
async function refreshFreshness(button) {
  // The axis first, so the loading state already shows the ticks; redrawn every time because
  // the phone and desktop label sets differ.
  const axis = $('#freshness-strip .ruler-axis');
  if (axis) axis.outerHTML = axisSvg(wideQuery.matches);
  if (button) { button.classList.add('spin'); button.setAttribute('aria-busy', 'true'); }
  try {
    const res = await api('/api/freshness');
    paintRuler(res.data.sources, res.data.request_budget_remaining);
  } catch (err) {
    // Keep the last marks, dimmed, and say how old they are rather than wiping them.
    const rail = $('#strip-rail');
    const meta = $('#strip-meta');
    if (rail) rail.style.opacity = '.5';
    if (meta) {
      meta.textContent = err.status === 0 ? 'bağlantı yok'
        : `okunamadı${lastPainted ? `, son güncelleme ${shortAge((Date.now() - lastPainted) / 1000)} önce` : ''}`;
    }
    paintPill('bad', 'bağlantı yok');
  } finally {
    if (button) { button.classList.remove('spin'); button.removeAttribute('aria-busy'); }
  }
}

export { refreshFreshness };
