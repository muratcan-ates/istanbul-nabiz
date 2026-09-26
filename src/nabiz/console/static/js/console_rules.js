/* The console's rule registry: every rule NEXUS knows as a card, and the "Geri al" dialog for a
 * learned one. The renderers are pure; mountRules wires the DOM. Nothing here reads window or
 * fetch at import: get and post come in from console.js, so node can import this module. */

import { dateTime, esc, int } from './format.js';
import { icon } from './icons.js';

const PATH_ICON = { reflex: 'bolt', arena: 'arrows-exchange' };
const PATH_TR = { reflex: 'refleks', arena: 'insan onayı' };
const STATUS = {
  active: { icon: 'circle-check', word: 'etkin', cls: 'is-ok' },
  expired: { icon: 'clock-exclamation', word: 'süresi doldu', cls: 'is-bad' },
  revoked: { icon: 'history', word: 'geri alındı', cls: 'is-info' },
  not_started: { icon: 'clock', word: 'henüz başlamadı', cls: 'is-warn' },
};
const MOCK_MISSING = 'Kural sicili örnek veride yok; sunucuya bağlı konsolda görünür.';

/* ---- pure renderers ------------------------------------------------------------------------ */
function countdownText(rule) {
  if (rule.status === 'revoked') return 'geri alındı';
  if (rule.status === 'expired') return 'süresi doldu';
  if (rule.status === 'not_started') return 'henüz başlamadı';
  if (rule.days_left === null || rule.days_left === undefined) return 'süresiz';
  if (Number(rule.days_left) === 0) return 'bugün bitiyor';
  return `${int(rule.days_left)} gün kaldı`;
}

function staleText(rule) {
  return rule.stale ? `bayat: ${int(rule.age_days)} gündür gözden geçirilmedi` : '';
}

function tag(name, text, cls = '') {
  return `<span class="tag${cls ? ' ' + cls : ''}">${icon(name)}${esc(text)}</span>`;
}

function ruleMeta(rule) {
  const lines = [`Bugün: ${int(rule.matched_today)} eşleşme · ${int(rule.reflex_today)} refleks kapanış`];
  if (rule.origin === 'mission') {
    lines.push(`Kaynak: ${rule.mission?.source || 'görev dosyası'}`);
  } else {
    const evidence = rule.evidence_count === null || rule.evidence_count === undefined ? 'bilinmiyor' : int(rule.evidence_count);
    lines.push(`Benimsendi: ${dateTime(rule.reviewed_at)} · Dayanak: ${evidence} onaylı karar · Gerekçe: ${rule.adopted_reason || 'yazılmadı'}`);
    if (rule.revoked_at) lines.push(`Geri alındı: ${dateTime(rule.revoked_at)} · Gerekçe: ${rule.revoke_reason || 'yazılmadı'}`);
  }
  return lines.map((line) => `<p class="rule-meta">${esc(line)}</p>`).join('');
}

function ruleCard(rule) {
  const status = STATUS[rule.status] || STATUS.active;
  const title = rule.origin === 'mission' ? `${rule.rule_id} · ${rule.mission?.title || 'görev kuralı'}` : `${rule.rule_id} · öğrenilmiş kural`;
  const ended = rule.status === 'revoked' || rule.status === 'expired';
  const cls = ['rule-card', rule.stale ? 'is-stale' : '', ended ? 'is-ended' : ''].filter(Boolean).join(' ');
  const tags = [
    tag(PATH_ICON[rule.path] || 'arrows-exchange', rule.path_label || PATH_TR[rule.path] || rule.path),
    tag(status.icon, status.word, status.cls),
    rule.status === 'active' ? tag('clock', countdownText(rule)) : '',
    rule.stale ? tag('alert-triangle', staleText(rule), 'is-warn') : '',
  ].join('');
  const action = rule.revocable === true
    ? `<div class="btn-row"><button type="button" class="btn btn-danger" data-revoke="${esc(rule.rule_id)}">Geri al</button></div>`
    : (rule.origin === 'mission'
      ? '<p class="field-hint">Görev dosyasındaki kural; değişiklik görev dosyası gözden geçirilerek yapılır.</p>' : '');
  return `<li class="${cls}" data-rule-id="${esc(rule.rule_id)}">`
    + `<div class="rule-head"><h3 tabindex="-1">${esc(title)}</h3><div class="rule-tags">${tags}</div></div>`
    + `<p class="rule-sentence">${esc(rule.sentence)}</p>${ruleMeta(rule)}${action}</li>`;
}

function rulesList(payload) {
  const rules = (payload && payload.rules) || [];
  return rules.length ? rules.map(ruleCard).join('') : '<li class="section-note">Kural yok.</li>';
}

function countNote(payload) {
  const counts = (payload && payload.counts) || {};
  const days = payload?.stale_after_days ?? 7;
  return `${int(counts.mission)} görev kuralı · ${int(counts.learned)} öğrenilmiş · ${int(days)} günden uzun gözden geçirilmeyen kural bayat sayılır`;
}

function failureCard(title, message) {
  return `<li><div class="callout callout-error" role="alert">${icon('alert-triangle')}<div>`
    + `<p class="callout-title">${esc(title)}</p><p>${esc(message)}</p></div></div></li>`;
}

/* ---- DOM ------------------------------------------------------------------------------------ */
let deps = null;
let trigger = null;
let pending = null;

const byId = (id) => document.getElementById(id);

async function loadRules() {
  if (!deps) return;
  const host = byId('rules-list');
  try {
    const payload = await deps.get('/api/console/rules');
    const html = rulesList(payload);
    // Unchanged content leaves the DOM alone: a refresh must not move a keyboard user's focus.
    if (host.innerHTML !== html) host.innerHTML = html;
    byId('rules-count').textContent = countNote(payload);
  } catch (err) {
    const message = deps.mock && err.status === 404 ? MOCK_MISSING : err.message;
    host.innerHTML = failureCard('Kural sicili alınamadı', message);
  }
}

function openRevoke(button) {
  trigger = button;
  pending = button.dataset.revoke;
  byId('revoke-rule').textContent = pending;
  byId('revoke-reason').value = '';
  byId('revoke-count').textContent = '0';
  byId('revoke-error').hidden = true;
  byId('revoke-dialog').showModal();
  byId('revoke-reason').focus();
}

function showError(message) {
  const error = byId('revoke-error');
  error.textContent = message;
  error.hidden = false;
  byId('revoke-reason').focus();
}

async function submitRevoke(evt) {
  evt.preventDefault();
  const reason = byId('revoke-reason').value.trim();
  if (!reason) { showError('Gerekçe yazın.'); return; }
  try {
    const res = await deps.post(`/api/console/rules/${encodeURIComponent(pending)}/revoke`, { reason });
    byId('revoke-dialog').close();
    const status = byId('rules-status');
    status.className = 'status-line is-ok';
    status.textContent = `${res.rule_id} geri alındı; deftere kayıt ${res.ledger_entry_id}.`;
    await loadRules();
    deps.onChange();
  } catch (err) {
    showError(err.message);
  }
}

/* Focus goes back where the dialog was opened from; a re-render may have replaced that button. */
function returnFocus() {
  const target = trigger && trigger.isConnected ? trigger
    : document.querySelector(`[data-rule-id="${CSS.escape(pending || '')}"] h3`) || byId('rules-status');
  if (target) target.focus();
}

function mountRules({ get, post, mock = false, onChange = () => {} }) {
  deps = { get, post, mock, onChange };
  const dialog = byId('revoke-dialog');
  byId('rules').addEventListener('click', (evt) => {
    const button = evt.target.closest('button[data-revoke]');
    if (button) openRevoke(button);
  });
  byId('revoke-reason').addEventListener('input', (evt) => {
    byId('revoke-count').textContent = String(evt.target.value.length);
    if (evt.target.value.trim()) byId('revoke-error').hidden = true;
  });
  byId('revoke-form').addEventListener('submit', submitRevoke);
  byId('revoke-cancel').addEventListener('click', () => dialog.close());
  // Esc fires 'cancel'; closing through the same path keeps one focus return for every way out.
  dialog.addEventListener('cancel', (evt) => { evt.preventDefault(); dialog.close(); });
  dialog.addEventListener('close', returnFocus);
  document.addEventListener('nabiz:ledger-changed', loadRules);
  return loadRules();
}

export { countdownText, staleText, ruleCard, rulesList, mountRules, loadRules };
