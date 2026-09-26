import { cityCard } from './cards.js';
import { isMock } from './config.js';
import { icon } from './icons.js';

const STRINGS = {
  savedPrefix: 'cihaza kaydedildi · ',
  unknownTime: 'cihaza kaydedildi · zaman bilinmiyor',
  offlineUnknown: 'Çevrimdışısınız.',
  serverTitle: 'Sunucuya ulaşılamıyor.',
  cardsSaved: 'Kartlar bu cihaza kaydedildi: ',
  noSavedCards: 'Bu cihazda kayıtlı kart yok.',
  chatOffline: 'Çevrimdışıyken asistan cevap vermez ve tahmin yazmaz.',
  install: 'Ana ekrana ekle',
  installed: 'Nabız ana ekrana eklendi.',
  iosHint: 'iPhone ve iPad\'de: Paylaş düğmesine, sonra "Ana Ekrana Ekle"ye dokunun.',
  dismiss: 'Tamam',
  backOnline: 'Bağlantı geri geldi. ',
  backOnlineMiddle: ' dk çevrimdışıydınız. Kartlar yenileniyor.',
};

function timeLabel(iso) {
  const time = Date.parse(iso);
  if (!Number.isFinite(time)) return null;
  const parts = new Intl.DateTimeFormat('tr-TR', {
    timeZone: 'Europe/Istanbul', day: '2-digit', month: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(new Date(time));
  const value = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${value.day}.${value.month} ${value.hour}:${value.minute}`;
}

function savedLabel(iso) {
  const time = timeLabel(iso);
  return time ? `${STRINGS.savedPrefix}${time}` : STRINGS.unknownTime;
}

function offlineText(ms) { return Number.isFinite(ms) ? `${Math.max(1, Math.floor(ms / 60000))} dk çevrimdışısınız.` : STRINGS.offlineUnknown; }

function backOnlineText(ms) { return `${STRINGS.backOnline}${Number.isFinite(ms) ? Math.max(1, Math.floor(ms / 60000)) : 1}${STRINGS.backOnlineMiddle}`; }

function isIos(userAgent, maxTouchPoints) { return /iPhone|iPad|iPod/i.test(userAgent) || (/Macintosh/i.test(userAgent) && Number(maxTouchPoints) > 1); }

const byId = (id) => document.getElementById(id);

function ensureBar() {
  let bar = byId('pwa-bar');
  if (bar) return bar;
  const header = document.querySelector('header.topbar');
  if (!header) return null;
  bar = document.createElement('div');
  bar.className = 'wrap';
  bar.id = 'pwa-bar';
  bar.innerHTML = `<div class="callout callout-warn" id="pwa-offline-band" role="status" hidden>${icon('wifi-off')}<div><p class="callout-title"></p><p></p></div></div><p class="status-line" id="pwa-status" role="status" hidden></p>`;
  header.insertAdjacentElement('afterend', bar);
  return bar;
}

let offlineSince = null;
let savedAt = null;
let savedMode = false;
let backOnline = false;
let recoveryTimer = null;

function setBand(title, detail, visible) {
  const band = byId('pwa-offline-band');
  if (!band) return;
  const titleNode = band.querySelector('.callout-title');
  const detailNode = band.querySelector('.callout-title + p');
  if (titleNode) titleNode.textContent = title;
  if (detailNode) detailNode.textContent = detail;
  band.hidden = !visible;
}

function updateBand() {
  if (backOnline) return;
  if (!navigator.onLine) {
    const title = offlineSince === null ? STRINGS.offlineUnknown : offlineText(Date.now() - offlineSince);
    const time = savedAt && timeLabel(savedAt);
    const detail = time ? `${STRINGS.cardsSaved}${time}.` : STRINGS.noSavedCards;
    setBand(title, detail, true);
    return;
  }
  if (savedMode && savedAt) {
    const time = timeLabel(savedAt);
    setBand(STRINGS.serverTitle, time ? `${STRINGS.cardsSaved}${time}.` : STRINGS.noSavedCards, true);
    return;
  }
  setBand('', '', false);
}

function setChatOffline() { const note = byId('pwa-chat-offline'); if (note) note.hidden = navigator.onLine; }

function labelCard(article, iso) {
  if (article.querySelector('.pwa-saved')) return;
  const foot = document.createElement('p');
  foot.className = 'card-foot pwa-saved';
  const tag = document.createElement('span');
  tag.className = 'tag is-warn';
  tag.innerHTML = icon('history');
  const text = document.createElement('span');
  text.textContent = savedLabel(iso);
  tag.append(text);
  foot.append(tag);
  article.append(foot);
}

function labelCards(root, iso) { if (root) root.querySelectorAll('article.card').forEach((article) => labelCard(article, iso)); }

function removeLabels(root) { if (root) root.querySelectorAll('.pwa-saved').forEach((node) => node.remove()); }

function showSaved(iso) {
  savedAt = iso || null;
  savedMode = true;
  labelCards(byId('cards'), savedAt);
  labelCards(byId('offline-cards'), savedAt);
  updateBand();
}

function clearSavedLabels() {
  savedMode = false;
  savedAt = null;
  removeLabels(byId('cards'));
  removeLabels(byId('offline-cards'));
  updateBand();
}

function saveOfflineStart() {
  if (recoveryTimer) window.clearTimeout(recoveryTimer);
  recoveryTimer = null;
  offlineSince = Date.now();
  backOnline = false;
  try { localStorage.setItem('nabiz.pwa.offlineSince', String(offlineSince)); } catch (_) { /* Private browsing can disable storage. */ }
  updateBand();
  setChatOffline();
}

function recoverConnection() {
  if (offlineSince === null || backOnline) return;
  backOnline = true;
  setBand(backOnlineText(Date.now() - offlineSince), '', true);
  setChatOffline();
  recoveryTimer = window.setTimeout(() => {
    offlineSince = null;
    backOnline = false;
    recoveryTimer = null;
    try { localStorage.removeItem('nabiz.pwa.offlineSince'); } catch (_) { /* Private browsing can disable storage. */ }
    setBand('', '', false);
    byId('cards-refresh')?.click();
  }, 8000);
}

function handleBriefMessage(message) {
  if (!message || message.type !== 'nabiz:brief') return;
  if (message.source === 'saved') showSaved(message.saved_at);
  else if (message.source === 'network') { clearSavedLabels(); recoverConnection(); }
}

async function renderOfflineCards() {
  const host = byId('offline-cards');
  if (!host) return;
  try {
    const response = await fetch('/api/brief');
    if (!response.ok) throw new Error('brief unavailable');
    const body = await response.json();
    if (!Array.isArray(body.cards) || !body.cards.length) throw new Error('no cards');
    host.innerHTML = body.cards.map((card, index) => cityCard(card, index)).join('');
    if (body.from_device === true) showSaved(body.saved_at || response.headers.get('X-Nabiz-Saved-At'));
  } catch (_) {
    host.innerHTML = `<p class="card-empty">${STRINGS.noSavedCards}</p>`;
  }
}

function attachCardObserver() {
  const cards = byId('cards');
  if (!cards || typeof MutationObserver === 'undefined') return;
  new MutationObserver(() => savedMode && savedAt && labelCards(cards, savedAt))
    .observe(cards, { childList: true, subtree: true });
}

function addChatNote() {
  const form = byId('chat-form');
  if (!form || byId('pwa-chat-offline')) return;
  const note = document.createElement('p');
  note.className = 'chat-hint';
  note.id = 'pwa-chat-offline';
  note.setAttribute('role', 'status');
  note.textContent = STRINGS.chatOffline;
  note.hidden = true;
  form.insertAdjacentElement('beforebegin', note);
}

function addIosHint(bar) {
  if (!bar || !isIos(navigator.userAgent, navigator.maxTouchPoints)) return;
  const standalone = navigator.standalone === true
    || Boolean(window.matchMedia && window.matchMedia('(display-mode: standalone)').matches);
  if (standalone) return;
  try { if (localStorage.getItem('nabiz.pwa.iosHintClosed') === '1') return; } catch (_) { /* Show the hint when storage is unavailable. */ }
  if (byId('pwa-ios-hint')) return;
  const hint = document.createElement('p');
  hint.className = 'chat-hint';
  hint.id = 'pwa-ios-hint';
  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'btn';
  close.id = 'pwa-ios-close';
  close.textContent = STRINGS.dismiss;
  close.addEventListener('click', () => {
    try { localStorage.setItem('nabiz.pwa.iosHintClosed', '1'); } catch (_) { /* The current page can still dismiss it. */ }
    hint.remove();
  });
  hint.append(document.createTextNode(`${STRINGS.iosHint} `), close);
  bar.append(hint);
}

function setupInstall(bar) {
  let installEvent = null;
  window.addEventListener('beforeinstallprompt', (event) => {
    event.preventDefault();
    installEvent = event;
    if (byId('pwa-install')) return;
    const actions = document.querySelector('.topbar-actions');
    if (!actions) return;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn';
    button.id = 'pwa-install';
    button.textContent = STRINGS.install;
    button.addEventListener('click', async () => {
      if (!installEvent) return;
      const pending = installEvent;
      installEvent = null;
      button.remove();
      await pending.prompt();
      await pending.userChoice;
    });
    actions.insertBefore(button, actions.firstChild);
  });
  window.addEventListener('appinstalled', () => {
    byId('pwa-install')?.remove();
    let status = byId('pwa-status');
    if (!status && bar) {
      status = document.createElement('p');
      status.className = 'status-line';
      status.id = 'pwa-status';
      status.setAttribute('role', 'status');
      bar.append(status);
    }
    if (status) {
      status.textContent = STRINGS.installed;
      status.hidden = false;
    }
  });
}

function clearBriefCaches() {
  if (!('caches' in window)) return;
  caches.keys().then((keys) => Promise.all(keys
    .filter((key) => key.startsWith('nabiz-brief-'))
    .map((key) => caches.delete(key))))
    .then(() => clearSavedLabels())
    .catch(() => clearSavedLabels());
}

function registerWorker() {
  if ('serviceWorker' in navigator && window.isSecureContext && !isMock(location.search)) navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => {});
}

function boot() {
  const bar = ensureBar();
  addChatNote();
  attachCardObserver();
  addIosHint(bar);
  setupInstall(bar);
  setChatOffline();

  if (!navigator.onLine) {
    try {
      const stored = Number(localStorage.getItem('nabiz.pwa.offlineSince'));
      offlineSince = Number.isFinite(stored) && stored > 0 ? stored : null;
    } catch (_) { offlineSince = null; }
  }
  updateBand();

  navigator.serviceWorker?.addEventListener('message', (event) => handleBriefMessage(event.data));
  window.addEventListener('offline', saveOfflineStart);
  window.addEventListener('online', recoverConnection);
  window.setInterval(() => updateBand(), 30000);

  const cards = byId('cards');
  if (savedMode && savedAt) labelCards(cards, savedAt);
  renderOfflineCards();
  byId('profile-clear')?.addEventListener('click', clearBriefCaches);
  registerWorker();
}

if (typeof window !== 'undefined' && typeof document !== 'undefined') boot();

export { STRINGS, savedLabel, offlineText, backOnlineText, isIos };
