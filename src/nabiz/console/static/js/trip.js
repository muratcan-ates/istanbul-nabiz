/* The page entry point for the single citizen trip flow. */

import { LIFT_TR, errorCard, skeleton } from './cards.js';
import { icon } from './icons.js';
import { readProfile } from './profile.js';
import {
  avoidedText, mapPoints, parseTripQuery, shareText, tripCardHtml, tripQuestion,
} from './trip_view.js';

const EXAMPLE = { from: 'Kadıköy', to: 'Levent' };
let activeController = null;
let activeRun = 0;

function revealSection(id, workspaceId) {
  document.dispatchEvent(new CustomEvent('nabiz:reveal', { detail: { id: workspaceId } }));
  const reveal = () => {
    const section = document.getElementById(id), workspace = document.getElementById(workspaceId);
    if (workspace) workspace.open = true;
    let details = section?.closest('details');
    while (details) { details.open = true; details = details.parentElement?.closest('details'); }
    return section;
  };
  reveal();
  // Workspace placement runs in a mutation observer before the next frame.
  requestAnimationFrame(() => reveal()?.scrollIntoView({ block: 'start' }));
}

function profileNeeds() {
  try {
    const profile = readProfile();
    return Array.isArray(profile.needs) ? profile.needs : [];
  } catch (error) {
    return [];
  }
}

function hideLegacyForms() {
  for (const id of ['compare', 'journey-section']) {
    const section = document.getElementById(id);
    if (!section) continue;
    section.hidden = true;
    section.dataset.mergedInto = 'yolculugum';
  }
}

function addStylesheet() {
  if (document.querySelector('link[href="/css/trip.css"]')) return;
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = '/css/trip.css';
  document.head.append(link);
}

function mountTrip() {
  const existing = document.getElementById('yolculugum');
  if (existing) return existing;
  const section = document.createElement('section');
  section.id = 'yolculugum';
  section.setAttribute('aria-labelledby', 'trip-title');
  section.innerHTML = '<div class="section-head"><h2 id="trip-title">Yolculuğum</h2>'
    + '<span class="section-note">metro, otobüs ve adımsız rota tek kartta</span></div>'
    + '<form id="trip-form" class="trip-form" autocomplete="off">'
    + '<div class="field"><label for="trip-from">Nereden</label><input id="trip-from" name="from" type="text" maxlength="120" required placeholder="Kadıköy"></div>'
    + '<div class="field"><label for="trip-to">Nereye</label><input id="trip-to" name="to" type="text" maxlength="120" required placeholder="Levent"></div>'
    + '<div class="trip-form-actions"><button id="trip-submit" class="btn btn-primary" type="submit">Yolculuğu göster</button>'
    + '<button id="trip-example" class="btn" type="button">Örnek: Kadıköy → Levent</button></div>'
    + '<p class="field-hint">Profiliniz bu cihazda kalır. Sunucuya yalnız başlangıç ve varış gider.</p></form>'
    + '<div id="trip-result" aria-live="polite" aria-busy="false"></div>'
    + '<p id="trip-status" class="sr-only" role="status"></p>';
  const main = document.querySelector('.workspace-main');
  if (main) main.prepend(section);
  else document.querySelector('#city-cards')?.after(section);
  addStylesheet();
  hideLegacyForms();
  window.addEventListener('load', hideLegacyForms, { once: true });

  const form = section.querySelector('#trip-form');
  const fromInput = section.querySelector('#trip-from');
  const toInput = section.querySelector('#trip-to');
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    void runTrip(fromInput.value, toInput.value);
  });
  section.querySelector('#trip-example').addEventListener('click', () => {
    fromInput.value = EXAMPLE.from;
    toInput.value = EXAMPLE.to;
    void runTrip(EXAMPLE.from, EXAMPLE.to);
  });
  const query = parseTripQuery(window.location.search);
  if (query) void openTrip(query.from, query.to);
  return section;
}

async function enrichAvoided(detours, fallbackProv, signal, runId, card) {
  const stations = [];
  for (const alt of detours) {
    if (alt.avoided_station && !stations.includes(alt.avoided_station)) stations.push(alt.avoided_station);
    if (stations.length === 3) break;
  }
  let get;
  try {
    ({ get } = await import('./api.js'));
  } catch (error) {
    if (signal.aborted || runId !== activeRun || !card.isConnected) return;
    for (const station of stations) {
      const row = [...card.querySelectorAll('.trip-avoided li[data-station]')]
        .find((item) => item.dataset.station === station);
      const state = row && row.querySelector('.trip-avoided-state');
      if (state) state.textContent = LIFT_TR.unknown;
    }
    return;
  }
  await Promise.all(stations.map(async (station) => {
    try {
      const entry = await get('/api/alternative', { station }, signal);
      if (signal.aborted || runId !== activeRun || !card.isConnected) return;
      const row = [...card.querySelectorAll('.trip-avoided li[data-station]')]
        .find((item) => item.dataset.station === station);
      const state = row && row.querySelector('.trip-avoided-state');
      if (state) state.textContent = avoidedText(entry, fallbackProv);
    } catch (error) {
      if (signal.aborted || runId !== activeRun || !card.isConnected) return;
      const row = [...card.querySelectorAll('.trip-avoided li[data-station]')]
        .find((item) => item.dataset.station === station);
      const state = row && row.querySelector('.trip-avoided-state');
      if (state) state.textContent = LIFT_TR.unknown;
    }
  }));
}

function wireMapAction(result, journey) {
  const button = result.querySelector('#trip-map');
  if (!button) return;
  button.addEventListener('click', async () => {
    const points = mapPoints(journey);
    const workspace = document.getElementById('map-workspace');
    if (workspace) workspace.open = true;
    document.dispatchEvent(new CustomEvent('nabiz:show-on-map', { detail: { points, source: 'trip' } }));
    if (!document.getElementById('harita-katmanlari')) {
      const { showOnMap } = await import('./map.js');
      showOnMap(points);
    }
    revealSection('harita', 'map-workspace');
  });
}

function wireShareAction(result, from, to, compare, journey) {
  const button = result.querySelector('#trip-share');
  const status = result.querySelector('#trip-share-status');
  if (!button || !status) return;
  if (typeof navigator !== 'undefined' && !navigator.share) button.textContent = 'Bağlantıyı kopyala';
  button.addEventListener('click', async () => {
    try {
      const { buildShareUrl } = await import('./share.js');
      const url = buildShareUrl(tripQuestion(from, to), []);
      if (navigator.share) {
        await navigator.share({ title: 'Yolculuğum', text: shareText(compare, journey), url });
        return;
      }
      await navigator.clipboard.writeText(url);
      status.textContent = 'Bağlantı kopyalandı.';
    } catch (error) {
      if (error.name === 'AbortError') return;
      status.textContent = 'Paylaşılamadı.';
    }
  });
}

async function runTrip(from, to) {
  const origin = String(from || '').trim();
  const destination = String(to || '').trim();
  const result = document.getElementById('trip-result');
  const status = document.getElementById('trip-status');
  if (!result || !status) return;
  if (!origin || !destination) {
    status.textContent = 'Başlangıç ve varış yazın.';
    return;
  }
  if (activeController) activeController.abort();
  const controller = new AbortController();
  activeController = controller;
  const runId = ++activeRun;
  result.innerHTML = skeleton(2);
  result.setAttribute('aria-busy', 'true');
  status.textContent = 'Yolculuk hesaplanıyor.';
  try {
    const { get, MOCK } = await import('./api.js');
    const [compareRes, journeyRes] = await Promise.allSettled([
      get('/api/compare', { from: origin, to: destination }, controller.signal),
      get(MOCK ? '/api/journey' : '/api/journey/accessible', { from: origin, to: destination }, controller.signal),
    ]);
    if (controller.signal.aborted || runId !== activeRun) return;
    const compare = compareRes.status === 'fulfilled' ? compareRes.value : null;
    const compareError = compareRes.status === 'rejected' ? (compareRes.reason?.message || 'bağlantı hatası') : null;
    const journey = journeyRes.status === 'fulfilled' ? journeyRes.value : null;
    const journeyError = journeyRes.status === 'rejected' ? (journeyRes.reason?.message || 'bağlantı hatası') : null;
    if (!compare && !journey) {
      result.innerHTML = errorCard('Yolculuk alınamadı', compareError || journeyError || 'Bağlantı hatası.');
      status.textContent = 'Yolculuk doğrulanamadı.';
      return;
    }
    const needs = profileNeeds();
    result.innerHTML = tripCardHtml(compare, journey, { needs, liftByStation: {}, compareError, journeyError });
    result.setAttribute('aria-busy', 'false');
    const card = result.querySelector('#trip-card');
    card?.querySelector('#trip-card-title')?.focus();
    wireMapAction(result, journey);
    wireShareAction(result, origin, destination, compare, journey);
    status.textContent = compare && journey ? 'Yolculuk kartı hazır.' : 'Yolculuk kartı hazır; bazı bilgiler doğrulanamadı.';
    if (journey && journey.available) {
      const detours = journey.alternatives_used || (journey.alternative_used ? [journey.alternative_used] : []);
      if (detours.length) void enrichAvoided(detours, journey.provenance, controller.signal, runId, card);
    }
  } catch (error) {
    if (controller.signal.aborted || runId !== activeRun) return;
    result.innerHTML = errorCard('Yolculuk alınamadı', error.message || 'Bağlantı hatası.');
    status.textContent = 'Yolculuk doğrulanamadı.';
  } finally {
    if (runId === activeRun) result.setAttribute('aria-busy', 'false');
  }
}

function openTrip(from, to) {
  const section = document.getElementById('yolculugum') || mountTrip();
  const fromInput = section.querySelector('#trip-from');
  const toInput = section.querySelector('#trip-to');
  fromInput.value = String(from || '').trim().slice(0, 120);
  toInput.value = String(to || '').trim().slice(0, 120);
  revealSection('yolculugum', 'journey-workspace');
  return runTrip(fromInput.value, toInput.value);
}

if (typeof document !== 'undefined') mountTrip();

export { EXAMPLE, runTrip, openTrip, mountTrip };
