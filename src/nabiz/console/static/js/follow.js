/* Takip ettiklerim (DECISIONS #38). The chat offers "Takip edilecek konu: M2 · onayla" after an answer
 * (chat.js fires nabiz:follow-suggestion); only the visitor's yes adds it.
 *
 * Without an account a topic stays in this browser (nabiz.follows.v1, at most three) and changes are
 * shown on this page while it is open (nabiz.follows.seen.v1 remembers what was already shown). With
 * an example account it is kept on the server (at most ten) and an essential change goes into a daily
 * e-mail preview. A topic is a line, a station or a keyword: never a location. */

import { del, get, post } from './api.js';
import { esc } from './format.js';
import { readAccount } from './identity.js';

const FOLLOWS_KEY = 'nabiz.follows.v1';
const SEEN_KEY = 'nabiz.follows.seen.v1';
const DEVICE_LIMIT = 3;
const CHECK_MS = 5 * 60 * 1000;

function readJson(key, fallback) {
  try { return JSON.parse(window.localStorage.getItem(key) || 'null') ?? fallback; } catch (err) { return fallback; }
}
function writeJson(key, value) {
  try { window.localStorage.setItem(key, JSON.stringify(value)); return true; } catch (err) { return false; }
}

const deviceFollows = () => readJson(FOLLOWS_KEY, []).filter((f) => f && f.kind && f.value);
let accountFollows = [];

function topicsNow() {
  return readAccount() ? accountFollows : deviceFollows();
}

function say(text) {
  const line = document.getElementById('follow-status');
  if (line) line.textContent = text;
}

async function loadAccountFollows() {
  if (!readAccount()) { accountFollows = []; return; }
  try { accountFollows = (await get('/api/account')).follows || []; } catch (err) { accountFollows = []; }
}

async function addFollow(suggestion) {
  if (readAccount()) {
    const res = await post('/api/account/follows', { kind: suggestion.kind, value: suggestion.value });
    accountFollows = res.follows || accountFollows;
    return `Takip ediliyor: ${suggestion.label}. Hesabınla sunucuda saklanır; önemli değişiklikte günde en çok bir özet e-posta hazırlanır.`;
  }
  const list = deviceFollows();
  if (list.some((f) => f.kind === suggestion.kind && f.value === suggestion.value)) return 'Bu konu zaten takip ediliyor.';
  if (list.length >= DEVICE_LIMIT) {
    return `Bu cihazda en çok ${DEVICE_LIMIT} konu takip edilir. Daha fazlası (10) ve e-posta özeti için hesap bağla.`;
  }
  list.push({ kind: suggestion.kind, value: suggestion.value, label: suggestion.label, added_at: new Date().toISOString() });
  writeJson(FOLLOWS_KEY, list);
  return `Takip ediliyor: ${suggestion.label}. Yalnız bu cihazda durur; değişiklik bu sayfa açıkken burada gösterilir.`;
}

function suggestionBox(suggestion) {
  const box = document.createElement('div');
  box.className = 'chat-suggest follow-suggest';
  box.setAttribute('role', 'group');
  box.setAttribute('aria-label', 'Takip önerisi');
  if (!suggestion.supported) {
    box.innerHTML = `<p>${esc(suggestion.prompt)}</p>`;
    return box;
  }
  const where = readAccount() ? 'Hesabınla sunucuda saklanır.' : 'Yalnız bu cihazda saklanır (en çok 3).';
  box.innerHTML = `<p>${esc(suggestion.prompt)}</p>`
    + (suggestion.note ? `<p class="field-hint">${esc(suggestion.note)}</p>` : '')
    + '<div class="btn-row"><button type="button" class="btn btn-primary" data-follow="yes">Onayla</button>'
    + '<button type="button" class="btn" data-follow="no">Hayır</button></div>'
    + `<p class="field-hint">Onaylamazsan hiçbir şey kaydedilmez. ${where}</p>`;
  box.addEventListener('click', async (evt) => {
    const btn = evt.target.closest('button[data-follow]');
    if (!btn) return;
    if (btn.dataset.follow === 'no') { box.innerHTML = '<p>Takip edilmedi.</p>'; return; }
    try {
      const said = await addFollow(suggestion);
      box.innerHTML = `<p>${esc(said)}</p>`;
      await render();
    } catch (err) {
      box.innerHTML = `<p>${esc(err.message)}</p>`;
    }
  });
  return box;
}

function topicItem(follow, state) {
  const lines = state
    ? (state.unavailable ? [`Kontrol edilemedi: ${state.unavailable}`] : (state.active.length ? state.active : ['Şu an kayıtlı bir aksaklık yok.']))
    : ['Kontrol ediliyor.'];
  const id = follow.id ? ` data-id="${esc(follow.id)}"` : ` data-kind="${esc(follow.kind)}" data-value="${esc(follow.value)}"`;
  return `<li class="follow-item"><div><b>${esc(follow.label)}</b>`
    + `<ul class="follow-lines">${lines.map((line) => `<li>${esc(line)}</li>`).join('')}</ul>`
    + (state && state.note ? `<p class="field-hint">${esc(state.note)}</p>` : '')
    + `</div><button type="button" class="btn" data-unfollow${id}>Takibi bırak</button></li>`;
}

async function render(notify = false) {
  const list = document.getElementById('follow-list');
  if (!list) return;
  const topics = topicsNow();
  const account = readAccount();
  document.getElementById('follow-where').textContent = account
    ? 'Hesabınla sunucuda (en çok 10); önemli değişiklikte günde en çok bir e-posta önizlemesi hazırlanır.'
    : 'Yalnız bu cihazda (en çok 3); değişiklikler bu sayfa açıkken burada gösterilir. E-posta için hesap bağla.';
  document.getElementById('follow-empty').hidden = topics.length > 0;
  list.innerHTML = topics.map((f) => topicItem(f, null)).join('');
  if (!topics.length) return;
  try {
    const res = await post('/api/follows/status', { topics: topics.map((f) => ({ kind: f.kind, value: f.value })) });
    const byKey = new Map(res.topics.map((t) => [`${t.kind}:${t.value}`, t]));
    list.innerHTML = topics.map((f) => topicItem(f, byKey.get(`${f.kind}:${f.value}`))).join('');
    if (notify) announceChanges(res.topics);
  } catch (err) {
    say(err.message);
  }
}

/** A page notice when a topic's alerts differ from what this browser already showed. */
function announceChanges(states) {
  const seen = readJson(SEEN_KEY, {});
  const changed = states.filter((s) => !s.unavailable && seen[s.key] !== undefined && seen[s.key] !== s.fingerprint.join('|'));
  states.forEach((s) => { if (!s.unavailable) seen[s.key] = s.fingerprint.join('|'); });
  writeJson(SEEN_KEY, seen);
  if (changed.length) say(`Takip ettiğin konularda değişiklik var: ${changed.map((s) => s.label).join(', ')}.`);
}

async function unfollow(btn) {
  if (btn.dataset.id) {
    const res = await del(`/api/account/follows/${encodeURIComponent(btn.dataset.id)}`);
    accountFollows = res.follows || [];
  } else {
    writeJson(FOLLOWS_KEY, deviceFollows().filter((f) => !(f.kind === btn.dataset.kind && f.value === btn.dataset.value)));
  }
  say('Takip bırakıldı.');
  await render();
}

/** After sign-in, the topics kept on this device join the account (its consent text names them). */
async function moveDeviceFollows() {
  const list = deviceFollows();
  if (!readAccount() || !list.length) return;
  let moved = 0;
  for (const follow of list) {
    try { await post('/api/account/follows', { kind: follow.kind, value: follow.value }); moved += 1; } catch (err) { break; }
  }
  if (moved === list.length) writeJson(FOLLOWS_KEY, []);
  if (moved) say(`Bu cihazdaki ${moved} takip konusu hesabına taşındı.`);
}

/** An e-mail's "takibi bırak" link: #takibi-birak=<token>. The token stays in the fragment, never in a log. */
function handleUnsubscribeLink() {
  const match = /^#takibi-birak=([A-Za-z0-9.]{3,120})$/.exec(window.location.hash);
  const host = document.getElementById('follow-unsubscribe');
  if (!match || !host) return;
  host.hidden = false;
  host.innerHTML = '<p>E-postadaki bağlantıyla bir takibi bırakmak üzeresin.</p>'
    + '<div class="btn-row"><button type="button" class="btn btn-primary" id="follow-unsub-yes">Takibi bırak</button></div>';
  host.querySelector('#follow-unsub-yes').addEventListener('click', async () => {
    try {
      const res = await post('/api/follow/unsubscribe', { token: match[1] });
      host.innerHTML = `<p>${esc(res.message)}</p>`;
    } catch (err) {
      host.innerHTML = `<p>${esc(err.message)}</p>`;
    }
    window.history.replaceState(null, '', '#takip');
    await loadAccountFollows();
    await render();
  });
  document.getElementById('takip').scrollIntoView();
}

async function mountFollow() {
  document.addEventListener('nabiz:follow-suggestion', (evt) => {
    const { suggestion, host } = evt.detail || {};
    if (suggestion && host) host.appendChild(suggestionBox(suggestion));
  });
  const section = document.getElementById('takip');
  if (!section) return;
  section.addEventListener('click', (evt) => {
    const btn = evt.target.closest('button[data-unfollow]');
    if (btn) unfollow(btn).catch((err) => say(err.message));
  });
  document.addEventListener('nabiz:account-changed', async () => { await moveDeviceFollows(); await loadAccountFollows(); await render(); });
  handleUnsubscribeLink();
  await moveDeviceFollows();
  await loadAccountFollows();
  await render(true);
  window.setInterval(() => { if (document.visibilityState === 'visible') render(true); }, CHECK_MS);
}

mountFollow();

export { FOLLOWS_KEY, SEEN_KEY, DEVICE_LIMIT };
