/* Profilim > Hesap bağla (DECISIONS #36): three example sign-ins, the quota table, the consent line,
 * and for a linked account its facts, its e-mail previews and one-tap deletion. No real İBB,
 * İstanbulkart or Google account is contacted; every card says so (js/account_view.js). */

import { del, get, post } from './api.js';
import { clearAll } from './conversations.js';
import { clearAccount, clearDeviceData, readAccount, writeAccount } from './identity.js';
import { consentBlock, outboxList, providerCard, signedInView, tierTable } from './account_view.js';

const changed = () => document.dispatchEvent(new CustomEvent('nabiz:account-changed'));

function say(root, text, bad = false) {
  const line = root.querySelector('#acct-status');
  line.textContent = text;
  line.classList.toggle('is-bad', bad);
}

async function renderSignedIn(root) {
  const body = root.querySelector('#acct-body');
  try {
    const view = await get('/api/account');
    const outbox = await get('/api/account/outbox');
    body.innerHTML = `${signedInView(view)}<h3>Gönderilecek e-posta önizlemesi</h3>`
      + '<p class="field-hint">E-postalar gönderilmez; bu sunucunun outbox klasörüne yazılır ve burada görünür.</p>'
      + outboxList(outbox.previews);
  } catch (err) {
    if (err.status === 401) { clearAccount(); changed(); return renderSignedOut(root); }
    body.innerHTML = '';
    say(root, err.message, true);
  }
  return undefined;
}

async function renderSignedOut(root) {
  const body = root.querySelector('#acct-body');
  try {
    const info = await get('/api/account/providers');
    body.innerHTML = tierTable(info.tiers, 'cihaz') + consentBlock(info.consent)
      + `<div class="acct-cards">${info.providers.map((p) => providerCard(p, info.sms_example_code)).join('')}</div>`;
  } catch (err) {
    body.innerHTML = '';
    say(root, err.message, true);
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
    say(root, `${res.account.provider_label}: örnek hesap bağlandı. Doğrulama e-postası gönderilmedi.`);
    changed();
    await renderSignedIn(root);
  } catch (err) {
    say(root, err.message, true);
  }
}

async function deleteEverything(root) {
  try {
    await del('/api/account');
  } catch (err) {
    if (err.status !== 401) { say(root, err.message, true); return; }
  }
  clearDeviceData();
  await clearAll().catch(() => {});
  say(root, 'Hesabın ve verilerin silindi: sunucudaki kayıt, takip konuları, e-posta önizlemeleri ve bu tarayıcıdaki Nabız verileri.');
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
  if (readAccount()) renderSignedIn(root); else renderSignedOut(root);
}

mountAccount();

export { mountAccount };
