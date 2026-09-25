/* Entry for the operator page (console.html). The operator is a simulated one; the only real effect
 * of a decision is a ledger entry and the text the citizen page shows. */

import { MOCK, get, post } from './api.js';
import { FRESHNESS_WARN_S, REFRESH_MS } from './config.js';
import { STATUS_TR, decisionCard, draftItem, queueLists, statsStrip, traceList, verifyBadge } from './console-cards.js';
import { errorCard, skeleton } from './cards.js';
import { esc } from './format.js';
import { mountToggles } from './theme.js';

const $ = (sel) => document.querySelector(sel);
let currentId = null;
let queueRetry = null;
/* How soon the queue is read again while the server is still reading its sources. */
const SOURCES_RETRY_MS = 5_000;

/* ---- strip, ledger badge, queue, drafts -------------------------------------------------- */
async function loadStats() {
  try {
    $('#stats').innerHTML = statsStrip(await get('/api/console/stats'));
  } catch (err) {
    $('#stats').innerHTML = `<li class="stat"><span class="stat-value is-word">okunamadı</span><span class="stat-label">${esc(err.message)}</span></li>`;
  }
}

async function loadVerify() {
  try {
    $('#ledger-badge').innerHTML = verifyBadge(await get('/api/console/ledger/verify'));
  } catch (err) {
    $('#ledger-badge').innerHTML = verifyBadge(null);
  }
}

/* Re-render only when the rows changed, and put focus back on the row that had it: a refresh must
 * not throw a keyboard user back to the top of the page. */
function renderList(host, html) {
  if (host.innerHTML === html) return;
  const focused = host.contains(document.activeElement) ? document.activeElement.dataset.id : null;
  host.innerHTML = html;
  if (focused) {
    const again = [...host.querySelectorAll('.queue-item')].find((b) => b.dataset.id === focused);
    if (again) again.focus({ preventScroll: true });
  }
}

async function loadQueue({ announce = false } = {}) {
  clearTimeout(queueRetry);
  try {
    const res = await get('/api/console/queue');
    const lists = queueLists(res.items || [], currentId);
    renderList($('#queue-arena'), lists.arena || '<li class="queue-empty">Onay bekleyen sinyal yok.</li>');
    renderList($('#queue-reflex'), lists.reflex || '<li class="queue-empty">Bugün refleksle kapanan sinyal yok.</li>');
    $('#queue-arena-count').textContent = `(${lists.arenaCount}, ${lists.awaiting} karar bekliyor)`;
    $('#queue-reflex-count').textContent = `(${lists.reflexCount})`;
    const reading = res.reading_sources === true;
    const sentence = `${lists.awaiting} sinyal karar bekliyor, ${lists.reflexCount} sinyal refleksle kapandı.`
      + (reading ? ' Kaynaklar okunuyor; yeni sinyaller birazdan gelir.' : '');
    const status = $('#queue-status');
    // The live region speaks when a person asked, or when something changed; a quiet refresh stays quiet.
    if (announce || status.textContent !== sentence) status.textContent = sentence;
    if (reading) queueRetry = setTimeout(() => { loadQueue(); loadStats(); loadVerify(); }, SOURCES_RETRY_MS);
  } catch (err) {
    $('#queue-arena').innerHTML = `<li>${errorCard('Sinyal kutusu alınamadı', err.message)}</li>`;
  }
}

async function loadDrafts() {
  const host = $('#drafts');
  try {
    const res = await get('/api/console/rule-drafts');
    const drafts = res.drafts || [];
    host.innerHTML = drafts.length ? drafts.map(draftItem).join('') : '<li class="section-note">Kural taslağı yok. Aynı desende 30 günde en az 3 onay gerekir.</li>';
  } catch (err) {
    host.innerHTML = `<li>${errorCard('Kural taslakları alınamadı', err.message)}</li>`;
  }
}

/* ---- the decision card ------------------------------------------------------------------- */
async function loadDecision(id, { focus = true } = {}) {
  currentId = id;
  const host = $('#decision-body');
  host.innerHTML = skeleton(2);
  document.querySelectorAll('.queue-item').forEach((b) => b.setAttribute('aria-current', b.dataset.id === id ? 'true' : 'false'));
  try {
    const d = await get(`/api/console/decisions/${encodeURIComponent(id)}`);
    host.innerHTML = decisionCard(d, { freshnessWarnS: FRESHNESS_WARN_S });
    const evidence = $('#evidence');
    const approve = host.querySelector('[data-act="approve"]');
    if (evidence && approve) {
      evidence.addEventListener('toggle', () => {
        if (evidence.open) { approve.removeAttribute('aria-disabled'); $('#evidence-gate').hidden = true; }
      });
    }
    if (focus) $('#decision').focus({ preventScroll: false });
  } catch (err) {
    host.innerHTML = errorCard('Karar kartı alınamadı', err.message);
  }
}

async function decide(action) {
  const status = $('#decision-status');
  const reason = $('#decision-reason');
  const error = $('#reason-error');
  const text = reason.value.trim();
  if ((action === 'reject' || action === 'defer') && !text) {
    error.hidden = false;
    reason.focus();
    return;
  }
  error.hidden = true;
  const edited = action === 'edit' ? $('#decision-edit').value.trim() : null;
  status.className = 'status-line';
  status.textContent = 'Deftere yazılıyor.';
  try {
    const res = await post(`/api/console/decisions/${encodeURIComponent(currentId)}`, { action, reason: text, edited_text: edited });
    const said = `Karar deftere yazıldı: ${STATUS_TR[res.status] || 'kaydedildi'}, kayıt ${res.ledger_entry_id || 'bilinmiyor'}.`;
    // Redraw the card so its status label is the new one, then say the result where the focus lands.
    await loadDecision(currentId, { focus: false });
    const after = $('#decision-status');
    after.className = 'status-line is-ok';
    after.setAttribute('tabindex', '-1');
    after.textContent = said;
    after.focus();
    loadQueue();
    loadStats();
    loadVerify();
  } catch (err) {
    status.className = 'status-line is-bad';
    status.textContent = `Karar yazılamadı: ${err.message}`;
  }
}

async function showTrace() {
  const host = $('#trace');
  host.innerHTML = skeleton(1);
  try {
    host.innerHTML = traceList(await get(`/api/console/ledger/${encodeURIComponent(currentId)}/trace`));
  } catch (err) {
    host.innerHTML = errorCard('İz alınamadı', err.message);
  }
}

function onDecisionClick(evt) {
  const btn = evt.target.closest('button[data-act]');
  if (!btn) return;
  const act = btn.dataset.act;
  if (act === 'trace') { showTrace(); return; }
  if (btn.getAttribute('aria-disabled') === 'true') { $('#evidence').querySelector('summary').focus(); return; }
  if (act === 'edit') {
    const field = $('#edit-field');
    if (field.hidden) {
      field.hidden = false;
      btn.textContent = 'Düzenleyerek onayla';
      $('#decision-edit').focus();
      return;
    }
    decide('edit');
    return;
  }
  decide(act);
}

/* ---- simulate and adopt ------------------------------------------------------------------ */
async function simulate() {
  const btn = $('#simulate');
  const status = $('#simulate-status');
  btn.setAttribute('aria-disabled', 'true');
  try {
    const res = await post('/api/console/simulate', { fixture: btn.dataset.fixture || 'metro_faulty_kartal' });
    await loadQueue();
    loadStats();
    loadVerify();
    if (res.signal_id) loadDecision(res.signal_id);
    status.className = 'status-line is-ok';
    status.textContent = res.duplicate
      ? 'Bu kayıtlı sinyal daha önce oynatılmış; kartı açıldı.'
      : 'Kayıtlı sinyal oynatıldı; kartı açıldı.';
  } catch (err) {
    status.className = 'status-line is-bad';
    status.textContent = `Sinyal oynatılamadı: ${err.message}`;
  } finally {
    btn.removeAttribute('aria-disabled');
  }
}

async function adopt(form) {
  const status = $('#drafts-status');
  const reason = form.reason.value.trim();
  if (!reason) { form.reason.focus(); return; }
  try {
    const res = await post(`/api/console/rule-drafts/${encodeURIComponent(form.dataset.id)}/adopt`,
      { reason, expires_days: Number(form.days.value) || undefined });
    status.className = 'status-line is-ok';
    status.textContent = `Kural benimsendi: ${res.rule_id || form.dataset.id}, son geçerlilik ${res.expires_at || 'bilinmiyor'}.`;
    loadDrafts();
    loadVerify();
  } catch (err) {
    status.className = 'status-line is-bad';
    status.textContent = `Kural benimsenemedi: ${err.message}`;
  }
}

/* ---- boot -------------------------------------------------------------------------------- */
function boot() {
  mountToggles();
  if (MOCK) $('#data-mode').hidden = false;
  $('#queue').addEventListener('click', (evt) => {
    const item = evt.target.closest('.queue-item');
    if (item) loadDecision(item.dataset.id);
  });
  $('#decision-body').addEventListener('click', onDecisionClick);
  $('#simulate').addEventListener('click', simulate);
  $('#drafts').addEventListener('submit', (evt) => {
    const form = evt.target.closest('form.draft-form');
    if (!form) return;
    evt.preventDefault();
    adopt(form);
  });
  // The queue read is what feeds the core from the sources: the stats and the ledger badge
  // are read after it, so the first screen does not show counts from before the feed.
  const refresh = async () => { await loadQueue(); loadStats(); loadVerify(); };
  loadDrafts();
  loadQueue({ announce: true }).then(() => { loadStats(); loadVerify(); });
  let timer = setInterval(refresh, REFRESH_MS);
  document.addEventListener('visibilitychange', () => {
    clearInterval(timer);
    if (document.visibilityState === 'visible') timer = setInterval(refresh, REFRESH_MS);
  });
}

boot();
