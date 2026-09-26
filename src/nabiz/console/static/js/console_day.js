/* The day's rulings and a deterministic shift handoff from the sealed ledger. */

import { MOCK, get } from './api.js';
import { REFRESH_MS } from './config.js';
import { traceList } from './console-cards.js';
import { errorCard } from './cards.js';
import { clock, esc } from './format.js';

const main = document.querySelector('#main');
let section = document.getElementById('day');
let refresh = null;
let loading = false;
let handoff = '';

function shell() {
  section = section || document.createElement('section');
  section.id = 'day';
  section.className = 'day';
  section.setAttribute('aria-labelledby', 'day-title');
  section.innerHTML = `<h2 id="day-title">Günün kararları</h2>
    <p class="section-note">yalnız insan kararları; kişi bazında metrik yok</p>
    <p id="day-message" class="section-note" hidden></p>
    <div id="day-content">
      <p id="day-yesterday"></p>
      <h3 id="day-open-title">Açık kalan kartlar (0)</h3>
      <ul id="day-open" class="day-open"></ul>
      <div class="day-copy-row"><button type="button" id="day-copy" class="btn" disabled>Vardiya devrini kopyala</button>
        <p id="day-copy-status" class="status-line" role="status"></p></div>
      <textarea id="day-handoff" readonly hidden rows="9" aria-label="Vardiya devri metni"></textarea>
      <div class="day-table-wrap"><table class="day-table">
        <caption class="sr-only">Bugün verilen kararlar, en yenisi üstte</caption>
        <thead><tr><th scope="col">Saat</th><th scope="col">Sinyal</th><th scope="col">Karar</th>
          <th scope="col">Gerekçe</th><th scope="col">Karar süresi</th></tr></thead>
        <tbody id="day-rows"></tbody>
      </table></div>
      <div id="day-trace" class="day-trace" tabindex="-1" aria-live="polite"></div>
    </div>`;
  if (!section.isConnected && main) {
    const anchor = main.querySelector('section[aria-labelledby="stats-title"]');
    if (anchor) anchor.after(section);
    else main.prepend(section);
  }
}

function decisionDuration(seconds) {
  if (seconds === null || seconds === undefined) return 'bilinmiyor';
  return seconds < 60 ? `${Math.round(seconds)} sn` : `${Math.round(seconds / 60)} dk`;
}

function openMarkup(items) {
  if (!items.length) return '<li class="section-note">Açık kart yok.</li>';
  return items.map((item) => `<li><b>${esc(item.title)}</b> <span>(${esc(item.status_label)})</span>
    <p>${esc(item.reason || 'gerekçe yok')}</p></li>`).join('');
}

function decisionMarkup(rows) {
  if (!rows.length) {
    return '<tr><td colspan="5" data-label="" class="section-note">Bugün henüz insan kararı yok.</td></tr>';
  }
  return rows.map((row) => `<tr data-id="${esc(row.signal_id)}">
    <th scope="row" data-label="Saat"><time datetime="${esc(row.at)}">${esc(clock(row.at))}</time></th>
    <td data-label="Sinyal"><button type="button" class="day-row-btn" data-id="${esc(row.signal_id)}"
      aria-controls="day-trace">${esc(row.title)}</button></td>
    <td data-label="Karar">${esc(row.action_label)}</td>
    <td data-label="Gerekçe">${esc(row.reason || 'gerekçe yazılmadı')}</td>
    <td data-label="Karar süresi">${esc(decisionDuration(row.decision_s))}</td>
  </tr>`).join('');
}

function update(host, markup) {
  if (host.innerHTML !== markup) host.innerHTML = markup;
}

function showMessage(markup) {
  const message = section.querySelector('#day-message');
  message.innerHTML = markup;
  message.hidden = false;
  section.querySelector('#day-content').hidden = true;
}

function render(data) {
  const content = section.querySelector('#day-content');
  section.querySelector('#day-message').hidden = true;
  content.hidden = false;
  update(section.querySelector('#day-yesterday'), esc(data.yesterday.sentence));
  update(section.querySelector('#day-open-title'), `Açık kalan kartlar (${data.open.length})`);
  update(section.querySelector('#day-open'), openMarkup(data.open));
  update(section.querySelector('#day-rows'), decisionMarkup(data.decisions));
  section.querySelector('#day-copy').disabled = false;
  if (handoff !== data.handoff) {
    handoff = data.handoff;
    section.querySelector('#day-handoff').value = handoff;
  }
}

async function load() {
  if (MOCK) {
    showMessage(esc('Örnek veri modunda günün kararları gösterilmez.'));
    return;
  }
  if (loading) return;
  loading = true;
  try {
    render(await get('/api/console/day'));
  } catch (err) {
    showMessage(errorCard('Günün kararları okunamadı', err.message));
  } finally {
    loading = false;
  }
}

async function copyHandoff() {
  const status = section.querySelector('#day-copy-status');
  try {
    if (!navigator.clipboard || typeof navigator.clipboard.writeText !== 'function') throw new Error('clipboard unavailable');
    await navigator.clipboard.writeText(handoff);
    status.textContent = 'Vardiya devri kopyalandı.';
  } catch {
    const textarea = section.querySelector('#day-handoff');
    textarea.hidden = false;
    textarea.value = handoff;
    textarea.focus();
    textarea.select();
    status.textContent = 'Pano izni yok; metin seçildi, Ctrl+C ile kopyalayın.';
  }
}

async function showTrace(signalId) {
  const host = section.querySelector('#day-trace');
  try {
    host.innerHTML = traceList(await get(`/api/console/ledger/${encodeURIComponent(signalId)}/trace`));
  } catch (err) {
    host.innerHTML = errorCard('İz alınamadı', err.message);
  }
  host.focus();
}

section = section || document.createElement('section');
shell();
section.addEventListener('click', (event) => {
  if (event.target.closest('#day-copy')) {
    copyHandoff();
    return;
  }
  const row = event.target.closest('tr[data-id]');
  const button = event.target.closest('.day-row-btn');
  const signalId = button?.dataset.id || row?.dataset.id;
  if (signalId) showTrace(signalId);
});

function startRefresh() {
  if (!MOCK && !document.hidden && refresh === null) refresh = setInterval(load, REFRESH_MS);
}

function stopRefresh() {
  if (refresh !== null) clearInterval(refresh);
  refresh = null;
}

load();
startRefresh();
document.addEventListener('visibilitychange', () => {
  if (document.hidden) stopRefresh();
  else {
    load();
    startRefresh();
  }
});
document.addEventListener('nabiz:decided', load);
