/* Entry for the operator page (console.html). The operator is a simulated one; the only real effect
 * of a decision is a ledger entry and the text the citizen page shows. */

import { MOCK, get, post } from './api.js';
import { FRESHNESS_WARN_S, REFRESH_MS } from './config.js';
import {
  STATUS_TR, composeReason, decisionCard, draftItem, gatedAction, queueLists, statsStrip, traceList, verifyBadge,
} from './console-cards.js';
import { errorCard, skeleton } from './cards.js';
import { esc, shortAge } from './format.js';
import { mountToggles } from './theme.js';

const $ = (sel) => document.querySelector(sel);
let currentId = null;
let queueRetry = null;
let decisionWaitTimer = null;
/* How soon the queue is read again while the server is still reading its sources. */
const SOURCES_RETRY_MS = 5_000;
const DECISION_WAIT_MS = 60_000;

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
  clearInterval(decisionWaitTimer);
  decisionWaitTimer = null;
  currentId = id;
  const host = $('#decision-body');
  host.innerHTML = skeleton(2);
  document.querySelectorAll('.queue-item').forEach((b) => b.setAttribute('aria-current', b.dataset.id === id ? 'true' : 'false'));
  try {
    const d = await get(`/api/console/decisions/${encodeURIComponent(id)}`);
    host.innerHTML = decisionCard(d, { freshnessWarnS: FRESHNESS_WARN_S });
    filterReasonCodes('approve');
    const evidence = $('#evidence');
    const approve = host.querySelector('[data-act="approve"]');
    const edit = host.querySelector('[data-act="edit"]');
    const updateEvidenceGate = () => {
      const ready = Boolean(evidence && evidence.open && (d.evidence || []).length > 0);
      if (approve) {
        if (ready) approve.removeAttribute('aria-disabled');
        else approve.setAttribute('aria-disabled', 'true');
      }
      if (edit && edit.dataset.confirm === 'true') {
        if (ready) edit.removeAttribute('aria-disabled');
        else edit.setAttribute('aria-disabled', 'true');
      }
      const gate = $('#evidence-gate');
      if (gate) gate.hidden = ready || ['approved', 'rejected', 'closed_by_reflex', 'expired', 'executed'].includes(d.signal?.status);
    };
    if (evidence) {
      evidence.addEventListener('toggle', updateEvidenceGate);
      updateEvidenceGate();
    }
    const wait = $('#decision-wait');
    if (wait) {
      const updateWait = () => {
        const created = Date.parse(wait.dataset.createdAt || '');
        if (Number.isFinite(created)) wait.textContent = `Kuyrukta: ${shortAge(Math.max(0, (Date.now() - created) / 1000))}`;
      };
      updateWait();
      decisionWaitTimer = setInterval(updateWait, DECISION_WAIT_MS);
    }
    if (focus) $('#decision').focus({ preventScroll: false });
  } catch (err) {
    host.innerHTML = errorCard('Karar kartı alınamadı', err.message);
  }
}

async function decide(action) {
  const status = $('#console-status');
  const reason = $('#decision-reason');
  const error = $('#reason-error');
  const text = reason.value.trim();
  const selected = document.querySelector('input[name="reason-code"]:checked');
  const code = selected && !selected.closest('label').hidden ? selected.value : null;
  if ((action === 'reject' || action === 'defer') && !code) {
    error.textContent = 'Ret ve erteleme için gerekçe kodu seçin.';
    error.hidden = false;
    document.querySelector('.reason-code:not([hidden]) input[name="reason-code"]')?.focus();
    return;
  }
  if (text && !code) {
    error.textContent = 'Ayrıntı için gerekçe kodu seçin.';
    error.hidden = false;
    document.querySelector('.reason-code:not([hidden]) input[name="reason-code"]')?.focus();
    return;
  }
  error.hidden = true;
  const composed = composeReason(code, text) || '';
  const edited = action === 'edit' ? $('#decision-edit').value.trim() : null;
  status.className = 'status-line';
  status.textContent = 'Deftere yazılıyor.';
  try {
    const res = await post(`/api/console/decisions/${encodeURIComponent(currentId)}`, { action, reason: composed, edited_text: edited });
    const said = `Karar deftere yazıldı: ${STATUS_TR[res.status] || 'kaydedildi'}, kayıt ${res.ledger_entry_id || 'bilinmiyor'}.`;
    // Keep the one status region outside the card that is replaced after a decision.
    await loadDecision(currentId, { focus: false });
    status.className = 'status-line is-ok';
    status.setAttribute('tabindex', '-1');
    status.textContent = said;
    status.focus();
    loadQueue();
    loadStats();
    loadVerify();
    // The day's decisions panel (console_day.js) refreshes at once instead of on its minute.
    document.dispatchEvent(new CustomEvent('nabiz:decided'));
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
  const field = $('#edit-field');
  if (gatedAction(act) && btn.getAttribute('aria-disabled') === 'true'
    && (act !== 'edit' || field.dataset.confirm === 'true')) {
    $('#evidence').querySelector('summary').focus();
    $('#console-status').textContent = 'Onaylamadan önce kanıtı açın.';
    return;
  }
  if (act === 'edit') {
    if (field.hidden) {
      field.hidden = false;
      field.dataset.confirm = 'true';
      btn.textContent = 'Düzenleyerek onayla';
      btn.setAttribute('aria-describedby', 'evidence-gate');
      if ($('#evidence').open && $('#evidence').querySelector('.evidence-item')) btn.removeAttribute('aria-disabled');
      else btn.setAttribute('aria-disabled', 'true');
      filterReasonCodes('approve');
      $('#decision-edit').focus();
      return;
    }
    decide('edit');
    return;
  }
  if (act === 'approve' || act === 'reject' || act === 'defer') filterReasonCodes(act);
  decide(act);
}

function filterReasonCodes(action) {
  const codeAction = action === 'edit' ? 'approve' : action;
  const group = document.querySelector('.reason-codes');
  if (group) group.dataset.action = codeAction;
  document.querySelectorAll('.reason-code').forEach((label) => {
    label.hidden = label.dataset.for !== codeAction;
  });
  const selected = document.querySelector('input[name="reason-code"]:checked');
  if (selected && selected.closest('label').hidden) selected.checked = false;
  const error = $('#reason-error');
  if (error) error.hidden = true;
}

/* ---- simulate and adopt ------------------------------------------------------------------ */
async function simulate() {
  const btn = $('#simulate');
  const status = $('#console-status');
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
    document.dispatchEvent(new CustomEvent('nabiz:decided'));
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
