/* The alert subscription never leaves this browser except inside one POST body to
 * /api/alerts/check: it lives in localStorage, the server evaluates it and forgets it
 * (docs/privacy.md). No subscription stored here means no request at all. This is the only
 * module that reads or writes the stored subscription, so its privacy review is one file. */

import { apiPost } from './api.js';
import { esc } from './format.js';
import { stamp } from './provenance.js';
import { callout } from './cards/sheet.js';

const $ = (sel) => document.querySelector(sel);

const SEVERITY = {
  critical: { tone: 'error', icon: 'alert-triangle', title: 'Kritik' },
  warning: { tone: 'warn', icon: 'alert-triangle', title: 'Uyarı' },
  info: { tone: '', icon: 'info-circle', title: 'Bilgi' },
};
const ALERT_SUBSCRIPTION_KEY = 'nabiz.alerts.subscription.v1';
const ALERT_COOLDOWNS_KEY = 'nabiz.alerts.cooldowns.v1';

function readStored(key) {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? JSON.parse(raw) : null;
  } catch (err) {
    return null; // private mode or a hand-edited value: behave as if nothing is stored
  }
}

function writeStored(key, value) {
  try { window.localStorage.setItem(key, JSON.stringify(value)); } catch (err) { /* private mode */ }
}

/** Keys still inside their cooldown. The server gets them as muted_keys and forgets them. */
function mutedKeys(cooldowns, now) {
  return Object.entries(cooldowns || {})
    .filter(([, seen]) => seen && Number.isFinite(seen.at) && now - seen.at < (seen.cooldown_seconds || 0) * 1000)
    .map(([key]) => key);
}

function resetAlerts() {
  try {
    window.localStorage.removeItem(ALERT_SUBSCRIPTION_KEY);
    window.localStorage.removeItem(ALERT_COOLDOWNS_KEY);
  } catch (err) { /* nothing stored, nothing to clear */ }
  const panel = $('#alerts-panel');
  if (panel) panel.hidden = true;
}

/**
 * Evaluate the subscription this browser holds, if any. The cooldown is enforced here, not
 * on the server: remembering "already shown" server-side would be a per-user history.
 */
async function loadAlerts() {
  const panel = $('#alerts-panel');
  const body = $('#alerts-body');
  if (!panel || !body) return;
  const subscription = readStored(ALERT_SUBSCRIPTION_KEY);
  if (!subscription || !Array.isArray(subscription.rules) || !subscription.rules.length) { panel.hidden = true; return; }
  const cooldowns = readStored(ALERT_COOLDOWNS_KEY) || {};
  const now = Date.now();
  let res;
  try {
    res = await apiPost('/api/alerts/check', { ...subscription, muted_keys: mutedKeys(cooldowns, now) });
  } catch (err) {
    body.innerHTML = callout(err.message, { tone: 'warn', icon: 'alert-triangle', title: 'Uyarılar kontrol edilemedi.' });
    panel.hidden = false;
    return;
  }
  const alerts = (res.data && res.data.alerts) || [];
  alerts.forEach((alert) => { cooldowns[alert.dedupe_key] = { at: now, cooldown_seconds: alert.cooldown_seconds }; });
  writeStored(ALERT_COOLDOWNS_KEY, cooldowns);
  // Severity is a word and an icon in its status colour, never the colour alone.
  body.innerHTML = alerts.slice(0, 5).map((alert) => callout(alert.message_tr, {
    ...SEVERITY[alert.severity] || SEVERITY.warning, html: `<p>${stamp(res.provenance)}</p>`,
  })).join('')
    + (res.note ? `<p class="panel-note">${esc(res.note)}</p>` : '')
    + '<p class="panel-note">Aboneliğiniz yalnızca bu tarayıcıda saklanır; sunucu değerlendirir ve unutur. '
    + '<button type="button" class="link-btn" id="alerts-reset">Uyarıları sıfırla</button></p>';
  const reset = $('#alerts-reset');
  if (reset) reset.addEventListener('click', resetAlerts);
  panel.hidden = false;
}

export { loadAlerts };
