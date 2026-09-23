/* İstanbul Nabız: single page, vanilla JS, native ES modules, no build step.
 *
 * index.html loads /config.js (a classic deferred script) and then this entry (a module, deferred
 * by definition). Deferred scripts run in document order and before DOMContentLoaded, so the
 * globals /config.js sets exist by the time the handler below runs. The pure modules (format,
 * router, provenance, icons, cards/*) never touch the DOM, so node can test them without one.
 */

import { applyTheme, readTheme, THEME_ORDER } from './theme.js';
import { forceMapOff } from './map.js';
import { loadAlerts } from './alerts.js';
import { refreshFreshness } from './freshness.js';
import { route } from './router.js';
import { run } from './journeys.js';

const $ = (sel) => document.querySelector(sel);

function chipPressed(target) {
  document.querySelectorAll('.chip').forEach((c) => c.setAttribute('aria-pressed', c === target ? 'true' : 'false'));
}

function runFromElement(el) {
  run(el.dataset.journey, {
    place: el.dataset.place,
    line: el.dataset.line,
    stop: el.dataset.stop,
    name: el.dataset.name,
    q: el.dataset.q,
  });
}

document.addEventListener('DOMContentLoaded', () => {
  const version = $('#version');
  if (version && window.NABIZ_VERSION) version.textContent = `sürüm ${window.NABIZ_VERSION}`;
  if (window.NABIZ_ATTRIBUTION) {
    const attr = $('#attribution');
    if (attr) attr.setAttribute('title', window.NABIZ_ATTRIBUTION);
  }

  // ?nomap=1 exercises the "CDN is blocked" path on purpose, without a broken network.
  try {
    const params = new URLSearchParams(window.location.search || '');
    if (params.get('nomap') === '1') forceMapOff();
  } catch (err) { /* older browser: leave the map on */ }

  applyTheme(readTheme());
  const themeBtn = $('#theme-toggle');
  if (themeBtn) {
    themeBtn.addEventListener('click', () => {
      const next = THEME_ORDER[(THEME_ORDER.indexOf(readTheme()) + 1) % THEME_ORDER.length];
      applyTheme(next);
    });
  }

  document.querySelectorAll('.chip').forEach((chip) => {
    chip.addEventListener('click', () => {
      chipPressed(chip);
      const label = chip.querySelector('.chip-label');
      const input = $('#q');
      if (input) input.value = (label ? label.textContent : chip.textContent).trim();
      runFromElement(chip);
    });
  });

  document.querySelectorAll('.journey-tile').forEach((tile) => {
    tile.addEventListener('click', () => { chipPressed(null); runFromElement(tile); });
  });

  const form = $('#ask-form');
  if (form) {
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      if ($('#ask-submit').getAttribute('aria-disabled') === 'true') return; // an answer is loading
      chipPressed(null);
      const input = $('#q');
      const parsed = route((input && input.value) || '');
      if (!parsed) return;
      run(parsed.journey, parsed.args);
    });
  }

  const refreshBtn = $('#freshness-refresh');
  if (refreshBtn) refreshBtn.addEventListener('click', () => refreshFreshness(refreshBtn));

  refreshFreshness(null);
  loadAlerts();

  // /api/freshness reads cache statistics only — it never touches İBB — so polling it is
  // free for the upstream. Pause while the tab is hidden anyway; a background tab that
  // keeps a server busy is bad manners.
  window.setInterval(() => {
    if (!document.hidden) refreshFreshness(null);
  }, 60000);
});
