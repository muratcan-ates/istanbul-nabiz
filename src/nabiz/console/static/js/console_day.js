/* The day's rulings and a deterministic shift handoff from the sealed ledger. */

import { MOCK, get } from './api.js';
import { REFRESH_MS } from './config.js';
import { traceList } from './console-cards.js';
import { errorCard } from './cards.js';
import { clock, esc, int } from './format.js';
import { icon } from './icons.js';

const main = document.querySelector('#main');
let section = document.getElementById('day');
let refresh = null;
let loading = false;
let handoff = '';
let displayedDecisionCount = null;

function shell() {
  section = section || document.createElement('section');
  section.id = 'day';
  section.className = 'day';
  section.setAttribute('aria-labelledby', 'day-title');
  section.innerHTML = `<div class="brief" aria-labelledby="day-title">
      <p class="eyebrow">Vardiya özeti</p><h2 id="day-title" class="sr-only">Vardiya özeti</h2>
      <div class="brief-lead"><div id="brief-value" class="brief-value is-empty">Yükleniyor</div><p class="brief-context">bugün verilen insan kararı</p></div>
      <dl class="brief-metrics" id="brief-metrics"></dl>
      <div class="brief-effects"><h3>Neyi etkiliyor</h3><div id="brief-impact"></div></div>
      <div class="brief-action" id="brief-action"></div>
      <p class="brief-foot" id="brief-foot"></p>
    </div>
    <div class="day-details" aria-labelledby="day-decisions-title">
    <p class="section-note">yalnız insan kararları; kişi bazında metrik yok</p>
    <p id="day-message" class="section-note" hidden></p>
    <div id="day-content">
      <p id="day-yesterday"></p>
      <h3 id="day-open-title">Açık kalan kartlar (0)</h3>
      <ul id="day-open" class="day-open"></ul>
      <textarea id="day-handoff" readonly hidden rows="9" aria-label="Vardiya devri metni"></textarea>
      <h3 id="day-decisions-title">Günün kararları</h3>
      <div class="day-table-wrap"><table class="day-table">
        <caption class="sr-only">Bugün verilen kararlar, en yenisi üstte</caption>
        <thead><tr><th scope="col">Saat</th><th scope="col">Sinyal</th><th scope="col">Karar</th>
          <th scope="col">Gerekçe</th><th scope="col">Karar süresi</th></tr></thead>
        <tbody id="day-rows"></tbody>
      </table></div>
      <div id="day-trace" class="day-trace" tabindex="-1" aria-live="polite"></div>
    </div></div>`;
  if (!section.isConnected && main) {
    const anchor = main.querySelector('.desk');
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
  const value = section.querySelector('#brief-value');
  value.classList.add('is-empty');
  value.classList.remove('is-number-entering');
  value.textContent = 'Vardiya özeti gösterilemiyor.';
  displayedDecisionCount = null;
  section.querySelector('#day-content').hidden = true;
}

function render(data) {
  const content = section.querySelector('#day-content');
  section.querySelector('#day-message').hidden = true;
  content.hidden = false;
  const humanDecisions = (Number(data.today.approved) || 0)
    + (Number(data.today.rejected) || 0) + (Number(data.today.deferred) || 0);
  const value = section.querySelector('#brief-value');
  const enterNumber = humanDecisions > 0
    && (displayedDecisionCount === null || displayedDecisionCount !== humanDecisions);
  displayedDecisionCount = humanDecisions;
  if (humanDecisions === 0) {
    value.classList.add('is-empty');
    value.classList.remove('is-number-entering');
    value.textContent = 'Bugün henüz insan kararı yok.';
  } else {
    value.classList.remove('is-empty');
    value.textContent = int(humanDecisions);
    if (enterNumber && numberMotionAllowed()) {
      value.classList.remove('is-number-entering');
      void value.offsetWidth;
      value.classList.add('is-number-entering');
    } else {
      value.classList.remove('is-number-entering');
    }
  }
  const metric = (label, count, yesterday) => `<div><dt>${label}</dt><dd>${Number.isFinite(count) ? int(count) : 'henüz yok'}</dd>`
    + `${Number.isFinite(yesterday) ? `<span>dün ${int(yesterday)}</span>` : ''}</div>`;
  update(section.querySelector('#brief-metrics'), metric('Onay', data.today.approved, data.yesterday?.approved)
    + metric('Red', data.today.rejected, data.yesterday?.rejected)
    + metric('Erteleme', data.today.deferred, data.yesterday?.deferred));
  const expiringCount = Array.isArray(data.expiring_rules) ? data.expiring_rules.length : 0;
  const impact = `<div class="brief-impact is-up">${icon('circle-check')}<p>Vatandaş yüzünde yayımlanan: ${int(data.today.approved)}</p></div>`
    + `<div class="brief-impact is-risk">${icon('alert-triangle')}<p>Açık kalan kart: ${data.open.length}`
    + `${expiringCount ? `<br>3 gün içinde süresi dolan kural: ${expiringCount}` : ''}</p></div>`;
  update(section.querySelector('#brief-impact'), impact);
  const oldest = data.open[0];
  const oldestId = oldest && oldest.signal_id;
  const openAction = oldestId
    ? `<button type="button" class="btn btn-primary" data-open-oldest="${esc(oldestId)}">En eski açık kartı aç</button>` : '';
  const copyClass = oldestId ? 'btn btn-quiet' : 'btn btn-primary';
  update(section.querySelector('#brief-action'), `${openAction}<div class="day-copy-row">`
    + `<button type="button" id="day-copy" class="${copyClass}">Vardiya devrini kopyala</button>`
    + '<p id="day-copy-status" class="status-line" role="status"></p></div>'
    + '<p id="brief-action-status" class="status-line" role="status"></p>');
  section.querySelector('#day-copy').disabled = false;
  const verified = data.verify?.ok === true ? 'mühür doğrulandı' : 'mühür DOĞRULANAMADI';
  const generatedAt = data.generated_at ? new Date(data.generated_at) : null;
  const time = generatedAt && Number.isFinite(generatedAt.getTime())
    ? new Intl.DateTimeFormat('tr-TR', { timeZone: 'Europe/Istanbul', hour: '2-digit', minute: '2-digit' }).format(generatedAt)
    : 'saat bilinmiyor';
  update(section.querySelector('#brief-foot'), `Kaynak: karar defteri, ${verified} · ${time}. Kişi bazında metrik yok.`);
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

function numberMotionAllowed() {
  return !window.matchMedia('(prefers-reduced-motion: reduce)').matches
    && document.documentElement.dataset.motion !== 'reduce'
    && document.documentElement.dataset.simple !== 'on';
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
  const oldest = event.target.closest('[data-open-oldest]');
  if (oldest) {
    const id = oldest.dataset.openOldest;
    const row = [...document.querySelectorAll('#queue .queue-item')].find((item) => item.dataset.id === id);
    const status = section.querySelector('#brief-action-status');
    if (row) {
      status.textContent = '';
      row.scrollIntoView({ block: 'center' });
      row.click();
    } else {
      status.textContent = 'Bu kart artık kuyrukta değil.';
    }
    return;
  }
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
