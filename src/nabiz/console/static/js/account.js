/* Profilim > Hesap bağla (DECISIONS #38): three example sign-ins, the quota table, the consent line,
 * and for a linked account its facts, its e-mail previews and one-tap deletion. No real İBB,
 * İstanbulkart or Google account is contacted; every card says so (js/account_view.js). */

import { del, get, post } from './api.js';
import { clearAll } from './conversations.js';
import { clearAccount, clearDeviceData, readAccount, writeAccount } from './identity.js';
import { consentBlock, outboxList, providerCard, signedInView, tierTable } from './account_view.js';
import { esc } from './format.js';
import { onLang, t } from './i18n_text.js';

const changed = () => document.dispatchEvent(new CustomEvent('nabiz:account-changed'));
const views = new WeakMap();
const statusMessages = new WeakMap();

function renderStatus(root) {
  const line = root.querySelector('#acct-status');
  const message = statusMessages.get(root);
  if (!message) return;
  if (message.kind === 'server') {
    line.textContent = message.text;
    line.lang = 'tr';
  } else if (message.kind === 'connected') {
    const marker = '__nabiz_provider__';
    const value = t('ui.acct.connected', '{provider}: örnek hesap bağlandı. Doğrulama e-postası gönderilmedi.', { provider: marker });
    line.innerHTML = value.split(marker).map(esc).join(`<span lang="tr">${esc(message.provider)}</span>`);
    line.removeAttribute('lang');
  } else {
    line.textContent = t('ui.acct.deleted', 'Hesabın ve verilerin silindi: sunucudaki kayıt, takip konuları, e-posta önizlemeleri ve bu tarayıcıdaki Nabız verileri.');
    line.removeAttribute('lang');
  }
  line.classList.toggle('is-bad', message.kind === 'server');
}

function sayServer(root, text) {
  statusMessages.set(root, { kind: 'server', text });
  renderStatus(root);
}

function sayConnected(root, provider) {
  statusMessages.set(root, { kind: 'connected', provider });
  renderStatus(root);
}

function sayDeleted(root) {
  statusMessages.set(root, { kind: 'deleted' });
  renderStatus(root);
}

function captureFields(body) {
  const fields = [...body.querySelectorAll('input, textarea, select')].map((field) => ({
    id: field.id,
    name: field.name,
    value: field.value,
    checked: field.type === 'checkbox' ? field.checked : undefined,
  }));
  const active = body.contains(document.activeElement) ? document.activeElement : null;
  return { fields, activeId: active && active.id, start: active && active.selectionStart, end: active && active.selectionEnd };
}

function restoreFields(body, snapshot) {
  for (const saved of snapshot.fields) {
    const field = (saved.id && body.querySelector(`#${CSS.escape(saved.id)}`))
      || (saved.name && [...body.querySelectorAll('[name]')].find((item) => item.name === saved.name));
    if (!field) continue;
    if (saved.checked !== undefined) field.checked = saved.checked;
    else field.value = saved.value;
  }
  if (!snapshot.activeId) return;
  const active = body.querySelector(`#${CSS.escape(snapshot.activeId)}`);
  active?.focus();
  if (active && snapshot.start !== null && snapshot.start !== undefined && typeof active.setSelectionRange === 'function') {
    active.setSelectionRange(snapshot.start, snapshot.end);
  }
}

function draw(root, preserve = false) {
  const body = root.querySelector('#acct-body');
  const state = views.get(root);
  if (!body || !state) return;
  const snapshot = preserve ? captureFields(body) : null;
  if (state.kind === 'signed-in') {
    body.innerHTML = `${signedInView(state.view)}<h3>${t('ui.acct.outbox_title', 'Gönderilecek e-posta önizlemesi')}</h3>`
      + `<p class="field-hint">${t('ui.acct.outbox_note', 'E-postalar gönderilmez; bu sunucunun outbox klasörüne yazılır ve burada görünür.')}</p>`
      + outboxList(state.previews);
  } else if (state.kind === 'signed-out') {
    body.innerHTML = tierTable(state.info.tiers, 'cihaz') + consentBlock(state.info.consent)
      + `<div class="acct-cards">${state.info.providers.map((provider) => providerCard(provider, state.info.sms_example_code)).join('')}</div>`;
  } else if (state.kind === 'error') {
    body.innerHTML = '';
  }
  if (snapshot) restoreFields(body, snapshot);
}

async function loadSignedIn(root) {
  try {
    const view = await get('/api/account');
    const outbox = await get('/api/account/outbox');
    views.set(root, { kind: 'signed-in', view, previews: outbox.previews });
    draw(root);
  } catch (err) {
    if (err.status === 401) {
      clearAccount();
      changed();
      return loadSignedOut(root);
    }
    views.set(root, { kind: 'error' });
    draw(root);
    sayServer(root, err.message);
  }
}

async function loadSignedOut(root) {
  try {
    const info = await get('/api/account/providers');
    views.set(root, { kind: 'signed-out', info });
    draw(root);
  } catch (err) {
    views.set(root, { kind: 'error' });
    draw(root);
    sayServer(root, err.message);
  }
}

async function signIn(root, form) {
  const consent = root.querySelector('#acct-consent');
  const error = root.querySelector('#acct-consent-error');
  if (!consent.checked) { error.hidden = false; consent.focus(); return; }
  error.hidden = true;
  const payload = { provider: form.dataset.provider, email: form.email.value.trim(), consent: true };
  if (form.sms_code) payload.sms_code = form.sms_code.value.trim();
  try {
    const res = await post('/api/account/signin', payload);
    writeAccount({ token: res.token, email: res.account.email, provider_label: res.account.provider_label, tier: res.account.tier });
    sayConnected(root, res.account.provider_label);
    changed();
    await loadSignedIn(root);
  } catch (err) {
    sayServer(root, err.message);
  }
}

async function deleteEverything(root) {
  try {
    await del('/api/account');
  } catch (err) {
    if (err.status !== 401) { sayServer(root, err.message); return; }
  }
  clearDeviceData();
  await clearAll().catch(() => {});
  sayDeleted(root);
  changed();
  window.setTimeout(() => window.location.reload(), 1500);
}

function mountAccount() {
  const root = document.getElementById('hesap');
  if (!root) return;
  root.addEventListener('submit', (evt) => {
    const form = evt.target.closest('form.acct-card');
    if (!form) return;
    evt.preventDefault();
    signIn(root, form);
  });
  root.addEventListener('click', (evt) => {
    if (evt.target.closest('#acct-delete')) deleteEverything(root);
  });
  if (readAccount()) loadSignedIn(root); else loadSignedOut(root);
  onLang(() => { draw(root, true); renderStatus(root); });
}

mountAccount();

export { mountAccount };
