/* Entry for the operator page (console.html). The operator is a simulated one; the only real effect
 * of a decision is a ledger entry and the text the citizen page shows. */

import { MOCK, get, post } from './api.js';
import { FRESHNESS_WARN_S, REFRESH_MS } from './config.js';
import {
  composeReason, decisionCard, draftItem, gatedAction, queueLists, statsStrip, traceList, verifyBadge,
} from './console-cards.js';
import { errorCard, skeleton } from './cards.js';
import { mountNav } from './console_desk.js';
import { mountRules } from './console_rules.js';
import { esc, shortAge } from './format.js';
import { mountToggles } from './theme.js';

const $ = (sel) => document.querySelector(sel);
let currentId = null;
let queueRetry = null;
let decisionWaitTimer = null;
/* How soon the queue is read again while the server is still reading its sources. */
const SOURCES_RETRY_MS = 5_000;
const DECISION_WAIT_MS = 60_000;
/* Other panels listen on document: a decision (E17, E23) and any new ledger entry (the badge, rules, E20). */
const ledgerChanged = () => document.dispatchEvent(new CustomEvent('nabiz:ledger-changed'));
const decided = () => { document.dispatchEvent(new CustomEvent('nabiz:decided')); ledgerChanged(); };

/* ---- strip, ledger badge, queue, drafts -------------------------------------------------- */
async function loadStats() {
  try {
    $('#stats').innerHTML = statsStrip(await get('/api/console/stats'));
  } catch (err) {
    $('#stats').innerHTML = `<li class="stat"><span class="stat-value is-word">okunamadı</span><span class="stat-label">${esc(err.message)}</span></li>`;
  }
}

function updateSystemSummary() {
  const host = $('#system-summary');
  if (!host) return;
  const toggle = $('#chat-pause-switch');
  const badge = $('#chat-pause-badge');
  const checked = toggle && toggle.getAttribute('aria-checked');
  const chat = toggle
    ? (toggle.getAttribute('aria-disabled') === 'true' || checked === null
      ? 'Vatandaş sohbeti durumu okunamadı'
      : checked === 'false' ? 'Vatandaş sohbeti durduruldu' : 'Vatandaş sohbeti açık')
    : (badge && !badge.hidden ? badge.textContent.trim() : 'Vatandaş sohbeti durumu okunamadı');
  const ledgerText = $('#ledger-badge')?.textContent.trim() || '';
  const ledger = ledgerText.includes('doğrulanamadı') ? 'defter doğrulanamadı'
    : ledgerText.includes('doğrulandı') ? 'defter doğrulandı' : 'defter henüz okunmadı';
  const count = ledgerText.match(/\d+ kayıt/);
  const summary = [chat, ledger, count && count[0]].filter(Boolean).join(' · ');
  if (host.textContent !== summary) host.textContent = summary;
}

async function loadVerify() {
  try {
    $('#ledger-badge').innerHTML = verifyBadge(await get('/api/console/ledger/verify'));
  } catch (err) {
    $('#ledger-badge').innerHTML = verifyBadge(null);
  }
  updateSystemSummary();
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
    const emptyQueue = '<li class="queue-empty">Onay bekleyen kart yok. Yeni sinyal gelince burada görünür.</li>';
    renderList($('#queue-arena'), lists.awaiting ? lists.arena : emptyQueue);
    renderList($('#queue-reflex'), lists.reflex || '<li class="queue-empty">Bugün refleksle kapanan sinyal yok.</li>');
    $('#queue-arena-count').textContent = `(${lists.arenaCount}, ${lists.awaiting} karar bekliyor)`;
    $('#queue-reflex-count').textContent = `(${lists.reflexCount})`;
    const reading = res.reading_sources === true;
    const sentence = `${lists.awaiting} sinyal karar bekliyor, ${lists.reflexCount} sinyal refleksle kapandı.`
      + (reading ? ' Kaynaklar okunuyor; yeni sinyaller birazdan gelir.' : '');
    const status = $('#queue-status');
    // The live region speaks when a person asked, or when something changed; a quiet refresh stays quiet.
    if (announce || status.textContent !== sentence) status.textContent = sentence;
    if (!lists.awaiting) {
      currentId = null;
      $('#decision-body').innerHTML = '<p class="decision-empty">Onay bekleyen kart yok. Yeni sinyal gelince burada görünür.</p>';
    }
    updateSystemSummary();
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

async function settleQueueRow(id) {
  const row = [...document.querySelectorAll('#queue .queue-item')].find((item) => item.dataset.id === id);
  const root = document.documentElement;
  const canMove = window.matchMedia('(prefers-reduced-motion: no-preference)').matches
    && root.dataset.motion !== 'reduce' && root.dataset.simple !== 'on';
  if (!row || !canMove) return;
  row.classList.add('is-leaving');
  await new Promise((resolve) => {
    const finish = () => {
      clearTimeout(fallback);
      row.removeEventListener('transitionend', ended);
      resolve();
    };
    const ended = (event) => {
      if (event.target === row && event.propertyName === 'opacity') finish();
    };
    const fallback = setTimeout(finish, 350);
    row.addEventListener('transitionend', ended);
  });
}

async function decide(action, button) {
  const previousMarkup = button.innerHTML;
  const previousDisabled = button.getAttribute('aria-disabled');
  button.setAttribute('aria-busy', 'true');
  button.setAttribute('aria-disabled', 'true');
  button.textContent = ({ approve: 'Onaylanıyor', edit: 'Onaylanıyor', reject: 'Reddediliyor', defer: 'Erteleniyor' })[action];
  const status = $('#console-status');
  const reason = $('#decision-reason');
  const selected = document.querySelector('input[name="reason-code"]:checked');
  const code = selected && !selected.closest('label').hidden ? selected.value : null;
  const composed = composeReason(code, reason.value.trim()) || '';
  const edited = action === 'edit' ? $('#decision-edit').value.trim() : null;
  const decidedId = currentId;
  status.className = 'status-line';
  status.textContent = 'Deftere yazılıyor.';
  try {
    await post(`/api/console/decisions/${encodeURIComponent(decidedId)}`, { action, reason: composed, edited_text: edited });
    await settleQueueRow(decidedId);
    await loadDecision(decidedId, { focus: false });
    await loadQueue();
    loadStats();
    decided();
    status.className = 'status-line is-ok';
    status.setAttribute('tabindex', '-1');
    status.textContent = 'Karar deftere yazıldı.';
    status.focus();
  } catch (err) {
    button.innerHTML = previousMarkup;
    button.removeAttribute('aria-busy');
    if (previousDisabled === null) button.removeAttribute('aria-disabled');
    else button.setAttribute('aria-disabled', previousDisabled);
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
      $('.reason-more').open = true;
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
    submitDecision('edit', btn);
    return;
  }
  if (act === 'approve' || act === 'reject' || act === 'defer') submitDecision(act, btn);
}

function submitDecision(action, button) {
  filterReasonCodes(action);
  const reason = $('#decision-reason');
  const selected = document.querySelector('input[name="reason-code"]:checked');
  const code = selected && !selected.closest('label').hidden ? selected.value : null;
  if ((action === 'reject' || action === 'defer') && !code) {
    showReasonError('Ret ve erteleme için gerekçe kodu seçin.');
    return;
  }
  if (reason.value.trim() && !code) {
    showReasonError('Ayrıntı için gerekçe kodu seçin.');
    return;
  }
  decide(action, button);
}

function showReasonError(message) {
  const more = $('.reason-more');
  if (more) more.open = true;
  const error = $('#reason-error');
  error.textContent = message;
  error.hidden = false;
  document.querySelector('.reason-code:not([hidden]) input[name="reason-code"]')?.focus();
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
    await loadQueue(); loadStats(); loadVerify();
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
    decided();
  } catch (err) {
    status.className = 'status-line is-bad';
    status.textContent = `Kural benimsenemedi: ${err.message}`;
  }
}

/* ---- boot -------------------------------------------------------------------------------- */
function boot() {
  mountToggles();
  mountNav(updateSystemSummary);
  updateSystemSummary();
  document.addEventListener('nabiz:ledger-changed', loadVerify);
  mountRules({ get, post, mock: MOCK, onChange: ledgerChanged });
  if (MOCK) $('#data-mode').hidden = false;
  $('#queue').addEventListener('click', (evt) => {
    const item = evt.target.closest('.queue-item');
    if (item) loadDecision(item.dataset.id);
  });
  $('#decision-body').addEventListener('click', onDecisionClick);
  $('#decision-body').addEventListener('change', (event) => {
    if (event.target.matches('input[name="reason-code"]') && event.target.checked) $('#reason-error').hidden = true;
  });
  document.addEventListener('nabiz:open-decision', (event) => {
    const id = event.detail && event.detail.id;
    const item = id && [...document.querySelectorAll('#queue .queue-item')].find((row) => row.dataset.id === id);
    if (item) {
      item.scrollIntoView({ block: 'center' });
      item.click();
    } else if (id) {
      const message = $('#brief-action-status');
      if (message) message.textContent = 'Bu kart artık kuyrukta değil.';
    }
  });
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
