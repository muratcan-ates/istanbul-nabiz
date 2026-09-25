/* İstanbul Nabız: single page, vanilla JS, native ES modules, no build step.
 *
 * index.html loads /config.js (a classic deferred script) and then this entry (a module, deferred
 * by definition). Deferred scripts run in document order and before DOMContentLoaded, so the
 * globals /config.js sets exist by the time the handler below runs. The pure modules (format,
 * router, provenance, icons, charts/*, cards/*) never touch the DOM, so node can test them. */

import { applyTheme, readTheme, THEME_ORDER } from './theme.js';
import { initMap, preloadMapLibre } from './map.js';
import { loadAlerts } from './alerts.js';
import { refreshFreshness } from './freshness.js';
import { startHero } from './hero.js';
import { route } from './router.js';
import { run, onResultsClick } from './journeys.js';

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

/** Free text through the keyword router. An empty question says what to type, under the input,
 * and the focus stays where it is. */
function ask(text) {
  const parsed = route(text || '');
  const error = $('#ask-error');
  if (error) error.hidden = Boolean(parsed);
  $('#q').setAttribute('aria-describedby', parsed ? 'ask-hint' : 'ask-hint ask-error');
  if (parsed) run(parsed.journey, parsed.args);
}

document.addEventListener('DOMContentLoaded', () => {
  const version = $('#version');
  if (version && window.NABIZ_VERSION) version.textContent = `sürüm ${window.NABIZ_VERSION}`;

  // ?nomap=1 exercises the "CDN is blocked" path on purpose, without a broken network.
  initMap(new URLSearchParams(window.location.search).get('nomap') === '1');

  applyTheme(readTheme());
  $('#theme-toggle').addEventListener('click', () => {
    applyTheme(THEME_ORDER[(THEME_ORDER.indexOf(readTheme()) + 1) % THEME_ORDER.length]);
  });

  // One delegated listener per region: the chips, and the welcome rows inside #results.
  $('.chips').addEventListener('click', (event) => {
    const chip = event.target.closest('.chip');
    if (!chip) return;
    chipPressed(chip);
    $('#q').value = chip.querySelector('.chip-label').textContent.trim();
    runFromElement(chip);
  });
  $('#results').addEventListener('click', (event) => {
    const tile = event.target.closest('.journey-tile');
    if (!tile) { onResultsClick(event); return; }
    chipPressed(null);
    // A row with an example puts it into the box and asks it, so the reader sees wording that works.
    if (tile.dataset.example) {
      $('#q').value = tile.dataset.example;
      ask(tile.dataset.example);
    } else {
      runFromElement(tile);
    }
  });

  // Intent: someone about to ask will likely get a map, so its files start downloading now.
  $('#q').addEventListener('focus', preloadMapLibre, { once: true });
  $('.chips').addEventListener('pointerover', preloadMapLibre, { once: true });

  $('#ask-form').addEventListener('submit', (event) => {
    event.preventDefault();
    if ($('#ask-submit').getAttribute('aria-disabled') === 'true') return; // an answer is loading
    chipPressed(null);
    ask($('#q').value);
  });

  const refreshBtn = $('#freshness-refresh');
  refreshBtn.addEventListener('click', () => refreshFreshness(refreshBtn));

  refreshFreshness(null);
  loadAlerts();
  startHero(() => refreshFreshness(null));

  // /api/freshness reads cache statistics only; it never touches İBB, so polling it is free for
  // the upstream. Paused while the tab is hidden anyway: a background tab that keeps a server
  // busy is bad manners.
  window.setInterval(() => {
    if (!document.hidden) refreshFreshness(null);
  }, 60000);
});
