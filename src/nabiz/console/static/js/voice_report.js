/* The voice report bridge keeps transcripts on the device and reuses E24's report contract. */

import { MOCK, get, post } from './api.js';
import { esc } from './format.js';
import { agencyCard, shouldShow } from './agency.js';
import { EMERGENCY_EVENT } from './emergency.js';
import { readIntent } from './voice_intent.js';

const STORAGE_KEY = 'nabiz.report.v1';
const MARK_WINDOW_MS = 30 * 60 * 1000;
let stationNames = [];
let stationRequest = null;

function reportKey(station, kind) {
  return station.toLocaleLowerCase('tr') + '|' + kind;
}

function readMarks() {
  try {
    const marks = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
    return marks && typeof marks === 'object' && !Array.isArray(marks) ? marks : {};
  } catch {
    return {};
  }
}

function hasRecentMark(station, kind) {
  const stamp = readMarks()[reportKey(station, kind)];
  return typeof stamp === 'number' && stamp >= Date.now() - MARK_WINDOW_MS && stamp <= Date.now();
}

function writeMark(station, kind) {
  try {
    const marks = readMarks();
    marks[reportKey(station, kind)] = Date.now();
    localStorage.setItem(STORAGE_KEY, JSON.stringify(marks));
  } catch {
    // Storage can be disabled; the server response still completes this report.
  }
}

async function ensureStations() {
  if (MOCK || stationRequest) return stationRequest;
  stationRequest = get('/api/map/stations')
    .then((data) => {
      stationNames = Array.isArray(data?.features)
        ? data.features.map((feature) => feature?.properties?.name).filter((name) => typeof name === 'string')
        : [];
    })
    .catch(() => { stationNames = []; });
  return stationRequest;
}

function focusTalk() {
  document.getElementById('voice-talk')?.focus();
}

function closePanel(panel) {
  panel.remove();
  focusTalk();
}

function addAskButton(choices, transcript, panel, prominent = false) {
  const ask = document.createElement('button');
  ask.type = 'button';
  ask.className = prominent ? 'btn btn-primary' : 'btn';
  ask.dataset.vr = 'ask';
  ask.textContent = 'Soru olarak yaz';
  choices.append(ask);
  ask.addEventListener('click', () => {
    const input = document.getElementById('chat-input');
    panel.remove();
    if (input) {
      input.value = transcript;
      input.focus();
      input.setSelectionRange(input.value.length, input.value.length);
    }
  });
  return ask;
}

function reportMarkup(panel, intent, transcript) {
  const block = document.createElement('div');
  block.className = 'report voice-report';
  block.id = 'voice-report';
  block.innerHTML = `
    <p class="report-q" id="voice-report-q">${esc(intent.station)} istasyonunda asansör kapalıydı · ne zaman gördünüz?</p>
    <div class="report-choices" role="group" aria-labelledby="voice-report-q">
      <button type="button" class="btn btn-primary" data-bucket="now">Şimdi</button>
      <button type="button" class="btn" data-bucket="today">Bugün, daha önce</button>
      <button type="button" class="btn" data-vr="cancel">Vazgeç</button>
    </div>
    <p class="report-note">Gönderilen yalnız istasyon, durum ve zaman; söylediğiniz cümle gönderilmez. Resmî İBB başvurusu değildir; resmî kayıt için <a href="tel:153">153</a>.</p>
    <p class="status-line report-status" id="voice-report-status" role="status" aria-live="polite"></p>`;
  const choices = block.querySelector('.report-choices');
  const status = block.querySelector('#voice-report-status');
  const ask = addAskButton(choices, transcript, panel);
  panel.append(block);

  block.addEventListener('click', async (event) => {
    const button = event.target.closest('button');
    if (!button || !block.contains(button)) return;
    if (button.dataset.vr === 'cancel') {
      closePanel(panel);
      return;
    }
    if (button.dataset.bucket !== 'now' && button.dataset.bucket !== 'today') return;

    const station = intent.station;
    const bucket = button.dataset.bucket;
    for (const control of choices.querySelectorAll('button')) control.disabled = true;
    status.textContent = '';
    status.classList.remove('is-bad');
    try {
      const res = await post('/api/report', { station, kind: 'not_working', bucket });
      writeMark(res.station, res.kind);
      status.textContent = `${res.message} ${res.note}`;
      const done = document.createElement('span');
      done.className = 'tag is-info report-done';
      done.textContent = Number.isInteger(res.support_count)
        ? `Zaten bildirildi · ${res.support_count} kişi`
        : 'Zaten bildirildi';
      choices.replaceChildren(done);
      document.dispatchEvent(new CustomEvent('nabiz:report-sent', {
        detail: { station: res.station, kind: res.kind },
      }));
    } catch (err) {
      status.textContent = err.message;
      status.classList.add('is-bad');
      for (const control of choices.querySelectorAll('button')) control.disabled = false;
      if (err.status === 422) {
        ask.classList.add('btn-primary');
        button.classList.remove('btn-primary');
        ask.focus();
      }
    }
  });

  if (hasRecentMark(intent.station, 'not_working')) {
    const done = document.createElement('span');
    done.className = 'tag is-info report-done';
    done.textContent = 'Zaten bildirildi';
    choices.replaceChildren(done, ask);
  }
  return block;
}

async function showAgency(panel, intent, transcript) {
  const block = document.createElement('div');
  block.className = 'report voice-report voice-agency';
  block.id = 'voice-report';
  const choices = document.createElement('div');
  choices.className = 'report-choices';
  choices.setAttribute('role', 'group');
  const status = document.createElement('p');
  status.className = 'status-line report-status';
  status.id = 'voice-report-status';
  status.setAttribute('role', 'status');
  status.setAttribute('aria-live', 'polite');
  block.append(choices, status);
  panel.append(block);
  const ask = addAskButton(choices, transcript, panel);
  try {
    const data = await get('/api/agency', { q: intent.keyword });
    if (shouldShow(data)) {
      const card = document.createElement('div');
      card.innerHTML = agencyCard(data, 'voice', true);
      block.insertBefore(card.firstElementChild, choices);
      const note = document.createElement('p');
      note.className = 'report-note';
      note.textContent = 'Nabız bu iş için bildirim almaz; kayıt açılmadı.';
      block.insertBefore(note, choices);
    }
  } catch (err) {
    status.textContent = err.message;
    status.classList.add('is-bad');
    ask.classList.add('btn-primary');
  }
}

function onTranscript(event) {
  if (MOCK) return;
  const { transcript, panel } = event.detail || {};
  if (typeof transcript !== 'string' || !panel) return;
  const intent = readIntent(transcript, stationNames);
  if (intent.type === 'emergency') {
    document.dispatchEvent(new CustomEvent(EMERGENCY_EVENT, {
      detail: { lang: 'tr', hazard: intent.hazard },
    }));
    return;
  }
  if (intent.type === 'lift_report') {
    event.preventDefault();
    reportMarkup(panel, intent, transcript);
    panel.querySelector('[data-bucket="now"]')?.focus();
    return;
  }
  if (intent.type === 'agency') {
    event.preventDefault();
    void showAgency(panel, intent, transcript);
  }
}

if (typeof document !== 'undefined') {
  document.addEventListener('click', (event) => {
    if (event.target.closest('#voice-optin, #voice-talk')) void ensureStations();
  }, true);
  document.addEventListener('nabiz:voice-transcript', onTranscript);
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    const panel = document.querySelector('#voice-confirm');
    if (panel && panel.querySelector('.voice-report, .voice-agency')) {
      event.preventDefault();
      closePanel(panel);
    }
  });
}
