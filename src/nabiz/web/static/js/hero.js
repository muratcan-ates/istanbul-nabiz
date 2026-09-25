/* The hero's pen line. /api/traffic?window=24h once the page is idle, then every 10 minutes
 * (30 while the reading is a day old) and only while the tab is visible; the server caches it
 * for 300 s, so İBB sees at most 12 calls an hour, none from the İETT budget. */

import { api } from './api.js';
import { shortAge } from './format.js';
import { stateOf } from './charts/pulse-geometry.js';
import { pulseView } from './charts/pulse-view.js';

const $ = (sel) => document.querySelector(sel);
const MINUTE = 60000;
let last = null; // { res, at }
let failed = false;
let drawn = false;
let textDirty = true;
let size = { width: 0, height: 0 };
let timer = 0;
let due = 0;
let onRead = () => {};

/** A payload kept past a failed poll grows older on screen, never younger. */
function aged(entry) {
  const late = (Date.now() - entry.at) / 1000;
  const prov = entry.res.provenance;
  if (!prov || late < 60 || !Number.isFinite(prov.age_seconds)) return entry.res;
  const age = prov.age_seconds + late;
  return { ...entry.res, provenance: { ...prov, age_seconds: age, age: `${shortAge(age)} önce` } };
}

function paint() {
  const fig = $('#hero-pulse');
  const view = pulseView(last && aged(last), { ...size, uid: 'np-hero', clock: Date.now(), failed });
  // Text changes with the data, not the width: rewriting it on a resize would drop focus.
  if (textDirty) {
    $('#hero-readout').innerHTML = view.readout;
    fig.querySelector('.sheet-table').innerHTML = view.table;
    textDirty = false;
  }
  if (!view.svg) return;
  const lined = ['live', 'delayed', 'archive'].includes(view.state);
  // Drawn on once per page load, left to right, so the line reads as time.
  fig.className = `pulse hero-pulse is-${view.state}${lined && !drawn ? ' is-drawing' : ''}`
    + `${document.hidden ? ' is-paused' : ''}`;
  drawn = drawn || lined;
  fig.querySelector('.pulse-plot').innerHTML = view.svg;
}

function schedule(ms) {
  clearTimeout(timer);
  due = Date.now() + ms;
  if (!document.hidden) timer = setTimeout(load, ms);
}

async function load() {
  clearTimeout(timer);
  try {
    last = { res: await api('/api/traffic', { window: '24h' }), at: Date.now() };
    failed = false;
    onRead(); // the ruler shows this read at once, not at its next poll
  } catch (err) {
    failed = true; // keep the last payload, if any
  }
  textDirty = true;
  paint();
  schedule((last && stateOf(last.res.provenance) !== 'archive' ? 10 : 30) * MINUTE);
}

/** The traffic answer's 24-hour half, when the hero read it less than a minute ago. */
function recentTraffic() {
  return last && Date.now() - last.at < MINUTE ? last.res : null;
}

function startHero(afterRead) {
  const fig = $('#hero-pulse');
  onRead = afterRead;
  let settle = 0;
  // Drawn at the measured width only, and again after a resize (debounced, not animated).
  new ResizeObserver(([entry]) => {
    clearTimeout(settle);
    settle = setTimeout(() => {
      const width = Math.round(entry.contentRect.width);
      const height = Math.round(entry.contentRect.height);
      if (width === size.width && height === size.height) return;
      size = { width, height };
      paint();
    }, 100);
  }).observe(fig.querySelector('.pulse-plot'));
  fig.addEventListener('click', (event) => { if (event.target.closest('[data-retry]')) load(); });
  // A hidden tab neither polls nor breathes.
  document.addEventListener('visibilitychange', () => {
    fig.classList.toggle('is-paused', document.hidden);
    if (document.hidden) clearTimeout(timer);
    else if (due) schedule(Math.max(0, due - Date.now()));
  });
  if ('requestIdleCallback' in window) window.requestIdleCallback(load, { timeout: 1000 });
  else setTimeout(load, 1);
}

export { startHero, recentTraffic };
