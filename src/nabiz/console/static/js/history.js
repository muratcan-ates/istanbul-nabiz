/* The station history card only uses a station the visitor saved on this device. */

import { get } from './api.js';
import { esc } from './format.js';
import { icon } from './icons.js';
import { readMemory, readProfile, savedPlaces } from './profile.js';
import { MODE_TR, ageSentence, modeOf, sourceLink, stamp } from './provenance.js';

const $ = (selector) => document.querySelector(selector);
const STATUS_TR = { fault: 'arızalı', revision: 'revizyonda', not_operated: 'hizmet dışı', unknown: 'bilinmiyor' };
let requestId = 0;

function currentStation() {
  return savedPlaces(readProfile(), readMemory()).stations[0] || '';
}

function historyCard(data) {
  const status = data.status || 'unverified';
  const current = STATUS_TR[data.current_status] || 'bilinmiyor';
  const provenance = data.provenance || {};
  const mode = modeOf(provenance);
  const statusIcon = status === 'warning' ? 'alert-triangle' : status === 'ok' ? 'circle-check' : 'clock-question';
  const footSource = sourceLink({ ...provenance, source: 'metro_equipment' });
  return `<article class="card card-in is-${esc(status)}" id="equipment-history-card" aria-labelledby="equipment-history-card-title">`
    + `<span class="card-kind">${icon('elevator')}</span>`
    + '<h3 class="card-title" id="equipment-history-card-title">Arıza geçmişi</h3>'
    + `<p class="card-body">${esc(data.text || '')}</p>`
    + `<p class="card-status">${icon(statusIcon)}<span>Şu an: ${esc(current)}</span></p>`
    + `<p class="card-foot">${stamp(provenance)}${footSource}`
    + `<span class="sr-only">${ageSentence(provenance)} Veri türü: ${esc(MODE_TR[mode])}.</span></p>`
    + '</article>';
}

async function loadHistory() {
  const section = $('#equipment-history');
  const host = $('#equipment-history-body');
  if (!section || !host) return;
  const station = currentStation();
  const turn = ++requestId;
  if (!station) {
    section.hidden = true;
    host.replaceChildren();
    return;
  }
  section.hidden = false;
  try {
    const data = await get('/api/equipment/history', { station });
    if (turn === requestId && currentStation() === station) host.innerHTML = historyCard(data);
  } catch (error) {
    if (turn !== requestId || currentStation() !== station) return;
    host.innerHTML = `<div class="callout callout-error" role="alert">${icon('alert-triangle')}<div>`
      + `<p class="callout-title">Arıza geçmişi alınamadı</p><p>${esc(error.message)}</p></div></div>`;
  }
}

loadHistory();
const placesObserver = new MutationObserver(loadHistory);
['#stations-list', '#memory-list'].forEach((selector) => {
  const list = $(selector);
  if (list) placesObserver.observe(list, { childList: true, subtree: true });
});
window.addEventListener('storage', loadHistory);
