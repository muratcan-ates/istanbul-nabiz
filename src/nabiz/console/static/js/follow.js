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
import { onLang, t } from './i18n_text.js';

const FOLLOWS_KEY = 'nabiz.follows.v1';
const SEEN_KEY = 'nabiz.follows.seen.v1';
const DEVICE_LIMIT = 3;
const CHECK_MS = 5 * 60 * 1000;
const suggestionBoxes = new Set();
const suggestionStates = new WeakMap();

function readJson(key, fallback) {
  try { return JSON.parse(window.localStorage.getItem(key) || 'null') ?? fallback; } catch (err) { return fallback; }
}
function writeJson(key, value) {
  try { window.localStorage.setItem(key, JSON.stringify(value)); return true; } catch (err) { return false; }
}

const deviceFollows = () => readJson(FOLLOWS_KEY, []).filter((follow) => follow && follow.kind && follow.value);
let accountFollows = [];
let lastStates = new Map();
let lastMessage = null;
let unsubscribeState = null;

function topicsNow() {
  return readAccount() ? accountFollows : deviceFollows();
}

function messageHtml(message) {
  const marker = '__nabiz_server_text__';
  let value = '';
  if (message.key === 'ui.follow.added_account') value = t('ui.follow.added_account', 'Takip ediliyor: {server}. Hesabınla sunucuda saklanır; önemli değişiklikte günde en çok bir özet e-posta hazırlanır.', { server: marker });
  if (message.key === 'ui.follow.added_device') value = t('ui.follow.added_device', 'Takip ediliyor: {server}. Yalnız bu cihazda durur; değişiklik bu sayfa açıkken burada gösterilir.', { server: marker });
  if (message.key === 'ui.follow.device_limit') value = t('ui.follow.device_limit', 'Bu cihazda en çok {limit} konu takip edilir. Daha fazlası (10) ve e-posta özeti için hesap bağla.', message.vars);
  if (message.key === 'ui.follow.already') value = t('ui.follow.already', 'Bu konu zaten takip ediliyor.');
  if (message.key === 'ui.follow.changed') value = t('ui.follow.changed', 'Takip ettiğin konularda değişiklik var: {server}.', { server: marker });
  if (message.key === 'ui.follow.removed') value = t('ui.follow.removed', 'Takip bırakıldı.');
  if (message.key === 'ui.follow.moved') value = t('ui.follow.moved', 'Bu cihazdaki {count} takip konusu hesabına taşındı.', message.vars);
  if (!message.server || !value.includes(marker)) return esc(value);
  return value.split(marker).map(esc).join(`<span lang="tr">${esc(message.server)}</span>`);
}

function say(text, serverText = false) {
  const line = document.getElementById('follow-status');
  if (!line) return;
  if (typeof text === 'string') {
    lastMessage = null;
    line.textContent = text;
    if (serverText) line.lang = 'tr'; else line.removeAttribute('lang');
    return;
  }
  line.innerHTML = messageHtml(text);
  line.removeAttribute('lang');
}

async function loadAccountFollows() {
  if (!readAccount()) { accountFollows = []; return; }
  try { accountFollows = (await get('/api/account')).follows || []; } catch (err) { accountFollows = []; }
}

async function addFollow(suggestion) {
  if (readAccount()) {
    const res = await post('/api/account/follows', { kind: suggestion.kind, value: suggestion.value });
    accountFollows = res.follows || accountFollows;
    return { key: 'ui.follow.added_account', server: suggestion.label };
  }
  const list = deviceFollows();
  if (list.some((follow) => follow.kind === suggestion.kind && follow.value === suggestion.value)) return { key: 'ui.follow.already' };
  if (list.length >= DEVICE_LIMIT) return { key: 'ui.follow.device_limit', vars: { limit: DEVICE_LIMIT } };
  list.push({ kind: suggestion.kind, value: suggestion.value, label: suggestion.label, added_at: new Date().toISOString() });
  writeJson(FOLLOWS_KEY, list);
  return { key: 'ui.follow.added_device', server: suggestion.label };
}

function drawSuggestion(box, suggestion, state) {
  const prompt = `<p lang="tr">${esc(suggestion.prompt)}</p>`;
  if (!suggestion.supported) {
    box.innerHTML = prompt;
    return;
  }
  if (state.action === 'no') {
    box.innerHTML = `${prompt}<p>${esc(t('ui.follow.not_added', 'Takip edilmedi.'))}</p>`;
    return;
  }
  if (state.action === 'done') {
    const message = state.message;
    box.innerHTML = `${prompt}<p>${messageHtml(message)}</p>`;
    return;
  }
  if (state.action === 'error') {
    box.innerHTML = `${prompt}<p lang="tr">${esc(state.error)}</p>`;
    return;
  }
  const where = readAccount()
    ? t('ui.follow.where_account', 'Hesabınla sunucuda saklanır.')
    : t('ui.follow.where_device', 'Yalnız bu cihazda saklanır (en çok 3).');
  box.innerHTML = prompt
    + (suggestion.note ? `<p class="field-hint" lang="tr">${esc(suggestion.note)}</p>` : '')
    + `<div class="btn-row"><button type="button" class="btn btn-primary" data-follow="yes">${esc(t('ui.follow.confirm', 'Onayla'))}</button>`
    + `<button type="button" class="btn" data-follow="no">${esc(t('ui.follow.no', 'Hayır'))}</button></div>`
    + `<p class="field-hint">${esc(t('ui.follow.no_consent', 'Onaylamazsan hiçbir şey kaydedilmez.'))} ${esc(where)}</p>`;
}

function suggestionBox(suggestion) {
  const box = document.createElement('div');
  box.className = 'chat-suggest follow-suggest';
  box.setAttribute('role', 'group');
  box.setAttribute('aria-label', t('ui.follow.suggestion_label', 'Takip önerisi'));
  const state = { action: '', suggestion };
  suggestionStates.set(box, state);
  drawSuggestion(box, suggestion, state);
  box.addEventListener('click', async (event) => {
    const button = event.target.closest('button[data-follow]');
    if (!button) return;
    if (button.dataset.follow === 'no') {
      state.action = 'no';
      drawSuggestion(box, suggestion, state);
      return;
    }
    try {
      state.message = await addFollow(suggestion);
      state.action = 'done';
      drawSuggestion(box, suggestion, state);
      await render();
    } catch (err) {
      state.error = err.message;
      state.action = 'error';
      drawSuggestion(box, suggestion, state);
    }
  });
  suggestionBoxes.add(box);
  return box;
}

function topicItem(follow, state) {
  let lines;
  if (!state) lines = [{ text: t('ui.follow.checking', 'Kontrol ediliyor.') }];
  else if (state.unavailable) {
    lines = [{ html: `${esc(t('ui.follow.unavailable', 'Kontrol edilemedi:'))} <span lang="tr">${esc(state.unavailable)}</span>` }];
  } else lines = state.active.length ? state.active.map((line) => ({ html: `<span lang="tr">${esc(line)}</span>` }))
    : [{ text: t('ui.follow.no_alerts', 'Şu an kayıtlı bir aksaklık yok.') }];
  const id = follow.id ? ` data-id="${esc(follow.id)}"` : ` data-kind="${esc(follow.kind)}" data-value="${esc(follow.value)}"`;
  return `<li class="follow-item"><div><b lang="tr">${esc(follow.label)}</b>`
    + `<ul class="follow-lines">${lines.map((line) => `<li>${line.html || esc(line.text)}</li>`).join('')}</ul>`
    + (state && state.note ? `<p class="field-hint" lang="tr">${esc(state.note)}</p>` : '')
    + `</div><button type="button" class="btn" data-unfollow${id}>${esc(t('ui.follow.stop', 'Takibi bırak'))}</button></li>`;
}

function drawList(topics) {
  const list = document.getElementById('follow-list');
  if (!list) return;
  const account = readAccount();
  document.getElementById('follow-where').textContent = account
    ? t('ui.follow.account_storage', 'Hesabınla sunucuda (en çok 10); önemli değişiklikte günde en çok bir e-posta önizlemesi hazırlanır.')
    : t('ui.follow.device_storage', 'Yalnız bu cihazda (en çok 3); değişiklikler bu sayfa açıkken burada gösterilir. E-posta için hesap bağla.');
  document.getElementById('follow-empty').hidden = topics.length > 0;
  list.innerHTML = topics.map((follow) => topicItem(follow, lastStates.get(`${follow.kind}:${follow.value}`))).join('');
}

async function render(notify = false, refresh = true) {
  const list = document.getElementById('follow-list');
  if (!list) return;
  const topics = topicsNow();
  drawList(topics);
  if (!topics.length || !refresh) return;
  try {
    const res = await post('/api/follows/status', { topics: topics.map((follow) => ({ kind: follow.kind, value: follow.value })) });
    lastStates = new Map(res.topics.map((topic) => [`${topic.kind}:${topic.value}`, topic]));
    drawList(topics);
    if (notify) announceChanges(res.topics);
  } catch (err) {
    say(err.message, true);
  }
}

/** A page notice when a topic's alerts differ from what this browser already showed. */
function announceChanges(states) {
  const seen = readJson(SEEN_KEY, {});
  const changed = states.filter((state) => !state.unavailable && seen[state.key] !== undefined && seen[state.key] !== state.fingerprint.join('|'));
  states.forEach((state) => { if (!state.unavailable) seen[state.key] = state.fingerprint.join('|'); });
  writeJson(SEEN_KEY, seen);
  if (changed.length) {
    const labels = changed.map((state) => state.label).join(', ');
    lastMessage = { key: 'ui.follow.changed', server: labels };
    say(lastMessage);
  }
}

async function unfollow(button) {
  if (button.dataset.id) {
    const res = await del(`/api/account/follows/${encodeURIComponent(button.dataset.id)}`);
    accountFollows = res.follows || [];
  } else {
    writeJson(FOLLOWS_KEY, deviceFollows().filter((follow) => !(follow.kind === button.dataset.kind && follow.value === button.dataset.value)));
  }
  lastMessage = { key: 'ui.follow.removed' };
  say(lastMessage);
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
  if (moved) {
    lastMessage = { key: 'ui.follow.moved', vars: { count: moved } };
    say(lastMessage);
  }
}

function drawUnsubscribe(host) {
  if (!unsubscribeState) return;
  host.hidden = false;
  if (unsubscribeState.kind === 'result') {
    host.innerHTML = `<p lang="tr">${esc(unsubscribeState.message)}</p>`;
    return;
  }
  host.innerHTML = `<p>${esc(t('ui.follow.unsubscribe_prompt', 'E-postadaki bağlantıyla bir takibi bırakmak üzeresin.'))}</p>`
    + `<div class="btn-row"><button type="button" class="btn btn-primary" id="follow-unsub-yes">${esc(t('ui.follow.stop', 'Takibi bırak'))}</button></div>`;
}

/** An e-mail's "takibi bırak" link: #takibi-birak=<token>. The token stays in the fragment, never in a log. */
function handleUnsubscribeLink() {
  const match = /^#takibi-birak=([A-Za-z0-9.]{3,120})$/.exec(window.location.hash);
  const host = document.getElementById('follow-unsubscribe');
  if (!match || !host) return;
  unsubscribeState = { kind: 'confirm' };
  drawUnsubscribe(host);
  host.addEventListener('click', async (event) => {
    if (!event.target.closest('#follow-unsub-yes')) return;
    try {
      const res = await post('/api/follow/unsubscribe', { token: match[1] });
      unsubscribeState = { kind: 'result', message: res.message };
    } catch (err) {
      unsubscribeState = { kind: 'result', message: err.message };
    }
    drawUnsubscribe(host);
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
    if (btn) unfollow(btn).catch((err) => say(err.message, true));
  });
  document.addEventListener('nabiz:account-changed', async () => {
    lastStates = new Map();
    await moveDeviceFollows();
    await loadAccountFollows();
    await render();
  });
  // A language switch redraws what is already on the page from memory: no request, nothing stored.
  onLang(() => {
    for (const box of suggestionBoxes) {
      if (box.isConnected) drawSuggestion(box, suggestionStates.get(box).suggestion, suggestionStates.get(box));
      else suggestionBoxes.delete(box);
    }
    drawList(topicsNow());
    if (lastMessage) say(lastMessage);
    const unsubscribe = document.getElementById('follow-unsubscribe');
    if (unsubscribe) drawUnsubscribe(unsubscribe);
  });
  handleUnsubscribeLink();
  await moveDeviceFollows();
  await loadAccountFollows();
  await render(true);
  window.setInterval(() => { if (document.visibilityState === 'visible') render(true); }, CHECK_MS);
}

if (typeof document !== 'undefined') mountFollow();

export { FOLLOWS_KEY, SEEN_KEY, DEVICE_LIMIT, suggestionBox, topicItem, render, mountFollow };
