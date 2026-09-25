/* Entry for the citizen page (index.html): city cards, the arrival and alternative cards, the
 * assistant, Profilim and Hafızam. Everything personal stays in this browser (js/profile.js). */

import { MOCK, get } from './api.js';
import { alternativeCard, arrivalCard, cardsSentence, cityCard, errorCard, skeleton } from './cards.js';
import { mountChat } from './chat.js';
import { mountHome } from './home.js';
import { DEFAULT_ARRIVAL, DEFAULT_LINES, DEFAULT_STATIONS, REFRESH_MS } from './config.js';
import { dateTime, esc } from './format.js';
import { icon } from './icons.js';
import {
  NEEDS, addMemory, clearMemory, clearProfile, effectiveNeeds, readMemory, readProfile, removeMemory, savedPlaces, writeProfile,
} from './profile.js';
import { mountToggles } from './theme.js';

const $ = (sel) => document.querySelector(sel);

let profile = readProfile();
let memory = readMemory();
const needs = () => effectiveNeeds(profile, memory);
const places = () => savedPlaces(profile, memory);

/* ---- cards ------------------------------------------------------------------------------ */
/* Write new markup without losing a keyboard user's place: the element that had focus (by its
 * card and its tag) gets it back. An automatic refresh that changed nothing touches nothing. */
const rendered = new WeakMap();

function keepFocus(host, html) {
  if (rendered.get(host) === html) return;
  const openDetails = [...host.querySelectorAll('details[open][id]')].map((panel) => panel.id);
  const active = document.activeElement;
  const inside = host.contains(active) && active !== host;
  const card = inside ? active.closest('[id]') : null;
  const tag = inside ? active.tagName.toLowerCase() : null;
  rendered.set(host, html);
  host.innerHTML = html;
  openDetails.forEach((id) => { const panel = document.getElementById(id); if (panel && host.contains(panel)) panel.open = true; });
  const again = card && card.id ? document.getElementById(card.id) : null;
  if (!again) return;
  const target = (tag && again.querySelector(tag)) || again;
  if (target === again && !again.hasAttribute('tabindex')) again.setAttribute('tabindex', '-1');
  target.focus({ preventScroll: true });
}

async function loadBrief(announce) {
  const grid = $('#cards');
  const meta = $('#cards-meta');
  if (announce || !rendered.has(grid)) { grid.innerHTML = skeleton(3); rendered.delete(grid); }
  const saved = places();
  const params = {
    stations: (saved.stations.length ? saved.stations : DEFAULT_STATIONS).join(','),
    lines: (saved.lines.length ? saved.lines : DEFAULT_LINES).join(','),
    needs: needs().join(','),
  };
  try {
    const res = await get('/api/brief', params);
    const cards = res.cards || [];
    keepFocus(grid, cards.length ? cards.map(cityCard).join('') : '<p class="card-empty">Gösterilecek kart yok.</p>');
    meta.textContent = `${cards.length} kart, ${res.generated_at ? dateTime(res.generated_at) : 'zaman bilinmiyor'}`;
    // The live region speaks when the visitor asked or the sentence changed; a quiet minute stays quiet.
    const sentence = cardsSentence(cards);
    if (announce || $('#cards-status').textContent !== sentence) $('#cards-status').textContent = sentence;
  } catch (err) {
    grid.innerHTML = errorCard('Şehir kartları alınamadı', err.message);
    meta.textContent = 'okunamadı';
    $('#cards-status').textContent = 'Şehir kartları alınamadı.';
  }
}

async function loadArrival(line, stop, announce = true) {
  const host = $('#arrival');
  if (announce || !rendered.has(host)) { host.innerHTML = skeleton(1); rendered.delete(host); }
  try {
    const res = await get('/api/arrival', { line, stop });
    keepFocus(host, arrivalCard(res));
  } catch (err) {
    keepFocus(host, errorCard('Varış bilgisi alınamadı', err.message));
  }
}

async function loadAlternative(announce) {
  const host = $('#alternative');
  if (announce || !rendered.has(host)) { host.innerHTML = skeleton(1); rendered.delete(host); }
  const station = places().stations[0] || DEFAULT_STATIONS[0];
  try {
    // The same fixed question for every visitor (step-free access), so it says nothing about who asks.
    const res = await get('/api/alternative', { station, needs: 'step_free' });
    keepFocus(host, alternativeCard(res));
  } catch (err) {
    keepFocus(host, errorCard('Asansör bilgisi alınamadı', err.message));
  }
}

/** ``announce``: a visitor asked (the button, a saved change), so the regions speak and skeletons show. */
function refreshAll(announce = true) {
  loadBrief(announce);
  const form = $('#arrival-form');
  loadArrival(form.line.value.trim() || DEFAULT_ARRIVAL.line, form.stop.value.trim() || DEFAULT_ARRIVAL.stop, announce);
  loadAlternative(announce);
}

/* ---- Profilim ---------------------------------------------------------------------------- */
function renderNeeds() {
  $('#needs').innerHTML = NEEDS.map((n) => `<label class="check">${icon(n.icon)}`
    + `<input type="checkbox" name="needs" value="${n.key}"${profile.needs.includes(n.key) ? ' checked' : ''}>`
    + `<span><span class="check-label">${esc(n.label)}</span><br><span class="field-hint">${esc(n.hint)}</span></span></label>`).join('');
}

function placeChip(kind, value) {
  return `<li class="place"><span>${esc(value)}</span>`
    + `<button type="button" class="icon-btn" data-remove="${kind}" data-value="${esc(value)}" aria-label="${esc(value)} kaydını kaldır">`
    + `${icon('search-off')}</button></li>`;
}

function renderPlaces() {
  $('#stations-list').innerHTML = profile.stations.map((s) => placeChip('stations', s)).join('');
  $('#lines-list').innerHTML = profile.lines.map((l) => placeChip('lines', l)).join('');
}

function renderProfileState() {
  const consent = $('#profile-consent');
  consent.checked = profile.consent;
  const sent = needs();
  const places = ' Kayıtlı durak ve hat adları yalnız kartları istemek için gider, sunucuda saklanmaz;'
    + ' asansör kartı her ziyaretçi için aynı sabit soruyu (adımsız erişim) sorar.';
  $('#profile-sent').textContent = (profile.consent
    ? (sent.length ? `Sunucuya giden kısıt listesi: ${sent.join(', ')}.` : 'Sunucuya giden kısıt listesi boş.')
    : 'Onay verilmedi: sunucuya hiçbir kısıt gitmiyor.') + places;
}

function mountProfile() {
  renderNeeds();
  renderPlaces();
  renderProfileState();
  const form = $('#profile-form');
  const status = $('#profile-status');
  form.addEventListener('submit', (evt) => {
    evt.preventDefault();
    const chosen = [...form.querySelectorAll('input[name="needs"]:checked')].map((el) => el.value);
    const consent = $('#profile-consent').checked;
    if (chosen.length && !consent) {
      $('#consent-error').hidden = false;
      $('#profile-consent').focus();
      return;
    }
    $('#consent-error').hidden = true;
    profile = { ...profile, needs: chosen, consent };
    status.textContent = writeProfile(profile) ? 'Kaydedildi. Yalnız bu tarayıcıda durur.' : 'Kaydedilemedi: tarayıcı depolamaya izin vermiyor.';
    renderProfileState();
    refreshAll();
  });
  $('#profile-clear').addEventListener('click', () => {
    clearProfile();
    profile = readProfile();
    renderNeeds();
    renderPlaces();
    renderProfileState();
    status.textContent = 'Profil silindi.';
    refreshAll();
  });
  form.addEventListener('click', (evt) => {
    const add = evt.target.closest('button[data-add]');
    const remove = evt.target.closest('button[data-remove]');
    if (add) {
      const input = form.querySelector(`#${add.dataset.add}-input`);
      const value = input.value.trim();
      if (!value) { input.focus(); return; }
      const key = add.dataset.add === 'station' ? 'stations' : 'lines';
      if (!profile[key].includes(value)) profile = { ...profile, [key]: [...profile[key], value] };
      writeProfile(profile);
      input.value = '';
      renderPlaces();
      status.textContent = `${value} kaydedildi.`;
      refreshAll();
    } else if (remove) {
      const key = remove.dataset.remove;
      profile = { ...profile, [key]: profile[key].filter((v) => v !== remove.dataset.value) };
      writeProfile(profile);
      renderPlaces();
      status.textContent = `${remove.dataset.value} kaldırıldı.`;
      refreshAll();
    }
  });
}

/* ---- Hafızam ----------------------------------------------------------------------------- */
function renderMemory() {
  const list = $('#memory-list');
  const empty = $('#memory-empty');
  list.innerHTML = memory.map((e) => `<li class="memory-item"><span><b>${esc(e.label)}</b><br>`
    + `<span class="memory-meta">${esc(e.key)} · eklendi ${dateTime(e.added_at)}</span></span>`
    + `<button type="button" class="btn" data-forget="${esc(e.key)}">Sil</button></li>`).join('');
  empty.hidden = memory.length > 0;
  $('#memory-clear').hidden = memory.length === 0;
}

function mountMemory() {
  renderMemory();
  $('#memory-list').addEventListener('click', (evt) => {
    const btn = evt.target.closest('button[data-forget]');
    if (!btn) return;
    memory = removeMemory(btn.dataset.forget);
    renderMemory();
    renderProfileState();
    $('#memory-status').textContent = 'Kayıt silindi.';
    refreshAll();
  });
  $('#memory-clear').addEventListener('click', () => {
    clearMemory();
    memory = readMemory();
    renderMemory();
    renderProfileState();
    $('#memory-status').textContent = 'Hafıza temizlendi.';
    refreshAll();
  });
}

function acceptSuggestion(suggestion) {
  if (!suggestion || !suggestion.key) return false;
  memory = addMemory(suggestion);
  renderMemory();
  renderProfileState();
  refreshAll();
  return profile.consent
    ? 'Eklendi. Hafızam bölümünde görünür; istediğin an silebilirsin.'
    : 'Bu tarayıcıda Hafızam\'a eklendi. Sunucuya gönderilmesi için Profilim\'de onay kutusunu işaretle.';
}

/* ---- boot -------------------------------------------------------------------------------- */
function boot() {
  mountToggles();
  if (MOCK) $('#data-mode').hidden = false;
  mountProfile();
  mountMemory();
  const arrivalForm = $('#arrival-form');
  arrivalForm.line.value = DEFAULT_ARRIVAL.line;
  arrivalForm.stop.value = DEFAULT_ARRIVAL.stop;
  arrivalForm.addEventListener('submit', (evt) => {
    evt.preventDefault();
    loadArrival(arrivalForm.line.value.trim() || DEFAULT_ARRIVAL.line, arrivalForm.stop.value.trim() || DEFAULT_ARRIVAL.stop);
  });
  $('#cards-refresh').addEventListener('click', () => refreshAll(true));
  mountChat({
    log: $('#chat-log'), form: $('#chat-form'), input: $('#chat-input'), submit: $('#chat-submit'), status: $('#chat-status'),
    getNeeds: needs, onMemorySuggestion: acceptSuggestion,
  });
  mountHome({ form: $('#chat-form'), input: $('#chat-input') });
  document.querySelectorAll('.chip[data-ask]').forEach((chip) => {
    chip.addEventListener('click', () => { $('#chat-input').value = chip.dataset.ask; $('#chat-form').requestSubmit(); });
  });
  refreshAll();
  const quietly = () => refreshAll(false);
  let timer = setInterval(quietly, REFRESH_MS);
  document.addEventListener('visibilitychange', () => {
    clearInterval(timer);
    if (document.visibilityState === 'visible') { quietly(); timer = setInterval(quietly, REFRESH_MS); }
  });
}

boot();
