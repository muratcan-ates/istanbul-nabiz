/* Copy and share the visible cards, plus keep a small list on this device. */

import { releaseCardAction } from './chat_card_actions.js';
import { NEEDS, readProfile } from './profile.js';

const SAVED_KEY = 'nabiz.saved-cards.v1';
const NEED_KEYS = new Set(NEEDS.map((need) => need.key));
const CARD_HOSTS = [
  { id: 'cards', kind: 'city' },
  { id: 'arrival', kind: 'arrival' },
  { id: 'alternative', kind: 'alternative' },
];
const savedSnapshots = new Map();
let selectedCard = null;

function normalText(value) {
  return String(value || '').replace(/\s+/g, ' ').trim();
}

function savedCards() {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(SAVED_KEY) || '[]');
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((entry) => entry && typeof entry.id === 'string' && typeof entry.kind === 'string'
      && typeof entry.title === 'string' && typeof entry.added_at === 'string').slice(0, 12);
  } catch (err) {
    return [];
  }
}

function writeSavedCards(entries) {
  try {
    window.localStorage.setItem(SAVED_KEY, JSON.stringify(entries.slice(0, 12)));
    return true;
  } catch (err) {
    return false;
  }
}

function allowedNeeds(values) {
  const list = Array.isArray(values) ? values : String(values || '').split(',');
  return [...new Set(list.map((value) => String(value).trim()).filter((value) => NEED_KEYS.has(value)))];
}

function buildShareUrl(question, needs) {
  const query = [];
  const cleanQuestion = normalText(question);
  const cleanNeeds = allowedNeeds(needs);
  if (cleanQuestion) query.push(`q=${encodeURIComponent(cleanQuestion)}`);
  if (cleanNeeds.length) query.push(`needs=${encodeURIComponent(cleanNeeds.join(','))}`);
  return `${location.origin}/${query.length ? `?${query.join('&')}` : ''}`;
}

function profilePlaces() {
  try {
    const profile = readProfile();
    return [...new Set([...(profile.stations || []), ...(profile.lines || [])]
      .map((value) => normalText(value)).filter(Boolean))].sort((a, b) => b.length - a.length);
  } catch (err) {
    return [];
  }
}

function safeForCopy(value) {
  let text = normalText(value);
  for (const place of profilePlaces()) {
    const escaped = place.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    text = text.replace(new RegExp(escaped, 'giu'), '[kayıtlı yer]');
  }
  return text;
}

function cardTitle(article) {
  return safeForCopy(article.querySelector('.card-title')?.textContent || '');
}

function cardDetails(article) {
  return [...article.querySelectorAll('.card-body, .card-metric, .card-status')]
    .map((node) => safeForCopy(node.textContent)).filter(Boolean);
}

function cardCopyText(article) {
  const title = cardTitle(article);
  const details = cardDetails(article);
  const footer = article.querySelector('.card-foot');
  let footText = '';
  let sourceUrls = [];
  if (footer) {
    const cleanFooter = footer.cloneNode(true);
    cleanFooter.querySelectorAll('.card-author').forEach((node) => node.remove());
    footText = safeForCopy(cleanFooter.textContent);
    sourceUrls = [...footer.querySelectorAll('a[href]')]
      .map((link) => link.href)
      .filter((href) => /^https?:\/\//i.test(href));
  }
  const lines = [title, ...details, footText, ...[...new Set(sourceUrls)].map((url) => `Kaynak URL: ${url}`)];
  return lines.filter(Boolean).join('\n');
}

function articleKind(article) {
  if (article.closest('#arrival')) return 'arrival';
  if (article.closest('#alternative')) return 'alternative';
  return 'city';
}

function currentQuestion() {
  const queryQuestion = new URLSearchParams(location.search).get('q');
  const input = document.getElementById('chat-input');
  return queryQuestion || input?.value || '';
}

function currentNeeds() {
  const queryNeeds = new URLSearchParams(location.search).get('needs') || '';
  let consentedNeeds = [];
  try {
    const profile = readProfile();
    if (profile.consent) consentedNeeds = profile.needs || [];
  } catch (err) {
    consentedNeeds = [];
  }
  return allowedNeeds([...queryNeeds.split(','), ...consentedNeeds]);
}

function setStatus(node, message, failed = false) {
  node.textContent = message;
  node.classList.toggle('is-bad', failed);
}

async function copyToClipboard(value, status) {
  try {
    if (!navigator.clipboard?.writeText) throw new Error('clipboard unavailable');
    await navigator.clipboard.writeText(value);
    setStatus(status, 'Kopyalandı.');
  } catch (err) {
    setStatus(status, 'Kopyalanamadı.', true);
  }
}

function createShareControls(article) {
  const group = document.createElement('div');
  group.className = 'card-share';

  const copyButton = document.createElement('button');
  copyButton.type = 'button';
  copyButton.className = 'btn';
  copyButton.dataset.cardAction = 'copy';
  copyButton.textContent = 'Kartı kopyala';

  const shareButton = document.createElement('button');
  shareButton.type = 'button';
  shareButton.className = 'btn';
  shareButton.dataset.cardAction = 'share';
  shareButton.textContent = typeof navigator.share === 'function' ? 'Paylaş' : 'Bağlantıyı kopyala';

  const status = document.createElement('p');
  status.className = 'share-status';
  status.setAttribute('role', 'status');
  status.setAttribute('aria-live', 'polite');

  group.append(copyButton, shareButton, status);
  group.addEventListener('click', async (event) => {
    const button = event.target.closest('button[data-card-action]');
    if (!button) return;
    if (button.dataset.cardAction === 'copy') {
      await copyToClipboard(cardCopyText(article), status);
      return;
    }
    const title = cardTitle(article);
    const text = cardCopyText(article);
    const url = buildShareUrl(currentQuestion(), currentNeeds());
    if (typeof navigator.share !== 'function') {
      await copyToClipboard(url, status);
      return;
    }
    try {
      await navigator.share({ title, text, url });
      setStatus(status, 'Paylaşıldı.');
    } catch (err) {
      if (err?.name !== 'AbortError') setStatus(status, 'Paylaşılamadı.', true);
    }
  });
  article.append(group);
}

// P00 D2a: a chat card's "Paylaş" (P01 ChatCard action "share"). Only the card's title and its first https
// source leave the page: no answer text, no question, no place, no code, no memory. A memory card or a card
// with no https source is not shared; the event stays unhandled and the card says the action is not ready.
function chatCardArticle(cardId) {
  return [...document.querySelectorAll('article.chat-card')].find((article) => article.dataset.cardId === cardId) || null;
}

function chatCardShare(article) {
  const link = [...article.querySelectorAll('.chat-card-sources a[href]')]
    .find((anchor) => /^https:\/\//.test(anchor.getAttribute('href') || ''));
  const title = normalText(article.querySelector('h4')?.textContent);
  return link && title ? { title, url: link.getAttribute('href') } : null;
}

async function shareChatCard(detail, shared) {
  const status = document.createElement('p');
  status.className = 'share-status';
  status.setAttribute('role', 'status');
  try {
    if (typeof navigator.share === 'function') {
      await navigator.share(shared);
      setStatus(status, 'Paylaşıldı.');
    } else await copyToClipboard(shared.url, status);
  } catch (err) {
    if (err?.name !== 'AbortError') setStatus(status, 'Paylaşılamadı.', true);
  } finally {
    chatCardArticle(detail.card_id)?.querySelector('.chat-card-actions')?.append(status);
    releaseCardAction(detail.card_id, detail.action);
  }
}

document.addEventListener('nabiz:card-action', (event) => {
  const detail = event.detail || {};
  if (detail.action !== 'share' || detail.type === 'memory') return;
  const article = chatCardArticle(detail.card_id);
  const shared = article && chatCardShare(article);
  if (!shared) return;
  event.preventDefault();
  shareChatCard(detail, shared);
});

function makeSavedSection() {
  const cards = document.getElementById('cards');
  const section = document.createElement('section');
  section.className = 'saved-cards';
  section.setAttribute('aria-labelledby', 'saved-cards-title');
  section.hidden = true;

  const heading = document.createElement('div');
  heading.className = 'section-head';
  const title = document.createElement('h3');
  title.id = 'saved-cards-title';
  title.textContent = 'Bugün listem';
  heading.append(title);

  const list = document.createElement('ul');
  list.className = 'saved-cards-list';
  section.append(heading, list);
  cards.before(section);
  return { section, list };
}

function renderSaved(savedUi) {
  const entries = savedCards();
  savedUi.section.hidden = entries.length === 0;
  savedUi.list.replaceChildren();
  entries.forEach((entry) => {
    const row = document.createElement('li');
    row.className = 'saved-card';
    row.dataset.savedId = entry.id;

    const content = document.createElement('div');
    content.className = 'saved-card-content';
    const title = document.createElement('strong');
    title.textContent = entry.title;
    const status = document.createElement('p');
    status.className = 'saved-card-status';
    content.append(title, status);

    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'btn';
    remove.dataset.removeSaved = entry.id;
    remove.textContent = 'Kaldır';
    row.append(content, remove);
    savedUi.list.append(row);
  });
  updateSavedSummaries(savedUi);
}

function updateSavedSummaries(savedUi) {
  savedCards().forEach((entry) => {
    const article = document.getElementById(entry.id);
    if (article) {
      const summary = cardDetails(article).join(' ');
      if (summary) savedSnapshots.set(entry.id, summary);
    }
    const status = savedUi.list.querySelector(`[data-saved-id="${CSS.escape(entry.id)}"] .saved-card-status`);
    if (!status) return;
    const summary = savedSnapshots.get(entry.id) || 'Kart açık olmadığından yeni durum burada gösterilemiyor.';
    const message = `Son bilinen durum: ${summary}`;
    if (status.textContent !== message) status.textContent = message;
  });
}

function selectCard(article, selectionStatus) {
  if (!article) return;
  if (selectedCard?.isConnected) selectedCard.removeAttribute('data-save-target');
  selectedCard = article;
  selectedCard.setAttribute('data-save-target', 'true');
  const title = cardTitle(article) || 'Kart';
  selectionStatus.textContent = `${title} seçildi. Bugün listeme ekle düğmesi bu kartı kaydeder.`;
}

function saveSelectedCard(savedUi, selectionStatus) {
  const article = selectedCard?.isConnected ? selectedCard : document.querySelector('#cards article.card, #arrival article.card, #alternative article.card');
  if (!article?.id) {
    setStatus(selectionStatus, 'Önce kaydetmek istediğiniz kartı seçin.', true);
    return;
  }
  const entries = savedCards().filter((entry) => entry.id !== article.id);
  const entry = {
    id: article.id,
    kind: articleKind(article),
    title: cardTitle(article) || 'Şehir kartı',
    added_at: new Date().toISOString(),
  };
  if (!writeSavedCards([entry, ...entries])) {
    setStatus(selectionStatus, 'Kaydedilemedi. Tarayıcı depolamaya izin vermiyor.', true);
    return;
  }
  const summary = cardDetails(article).join(' ');
  if (summary) savedSnapshots.set(article.id, summary);
  renderSaved(savedUi);
  setStatus(selectionStatus, 'Kart Bugün listeme eklendi.');
}

function removeSavedCard(id, savedUi, selectionStatus) {
  const entries = savedCards().filter((entry) => entry.id !== id);
  if (!writeSavedCards(entries)) {
    setStatus(selectionStatus, 'Kart kaldırılamadı.', true);
    return;
  }
  savedSnapshots.delete(id);
  renderSaved(savedUi);
  setStatus(selectionStatus, 'Kart listeden kaldırıldı.');
}

function mountSaveButton(savedUi) {
  const refresh = document.getElementById('cards-refresh');
  const header = refresh?.parentElement;
  if (!header || document.getElementById('share-save-card')) return null;

  const actions = document.createElement('div');
  actions.className = 'share-header-actions';
  const button = document.createElement('button');
  button.type = 'button';
  button.id = 'share-save-card';
  button.className = 'btn';
  button.textContent = 'Bugün listeme ekle';
  button.setAttribute('aria-describedby', 'share-selection-status');
  button.addEventListener('click', () => saveSelectedCard(savedUi, selectionStatus));
  actions.append(button);
  refresh.insertAdjacentElement('afterend', actions);

  const selectionStatus = document.createElement('p');
  selectionStatus.id = 'share-selection-status';
  selectionStatus.className = 'sr-only share-status';
  selectionStatus.setAttribute('role', 'status');
  selectionStatus.setAttribute('aria-live', 'polite');
  header.append(selectionStatus);
  return selectionStatus;
}

function addSelectionHandlers(host, selectionStatus) {
  const selectFromEvent = (event) => {
    const article = event.target.closest('article.card');
    if (article) selectCard(article, selectionStatus);
  };
  host.addEventListener('click', selectFromEvent);
  host.addEventListener('focusin', selectFromEvent);
}

function enhanceCards(host, kind, savedUi, selectionStatus) {
  host.querySelectorAll('article.card').forEach((article) => {
    if (!article.hasAttribute('tabindex')) article.tabIndex = 0;
    if (article.dataset.kind === undefined) article.dataset.kind = kind;
    if (!article.querySelector('.card-share')) createShareControls(article);
    if (!selectedCard?.isConnected && kind === 'city') selectCard(article, selectionStatus);
  });
  updateSavedSummaries(savedUi);
}

function showNeedsNote() {
  const rawNeeds = new URLSearchParams(location.search).get('needs') || '';
  const keys = allowedNeeds(rawNeeds);
  if (!keys.length) return;
  const form = document.getElementById('chat-form');
  if (!form || document.getElementById('share-needs-note')) return;
  const labels = NEEDS.filter((need) => keys.includes(need.key)).map((need) => need.label);
  const note = document.createElement('p');
  note.id = 'share-needs-note';
  note.className = 'share-status';
  note.setAttribute('role', 'status');
  note.setAttribute('aria-live', 'polite');
  note.textContent = `Bu bağlantıdaki ihtiyaç notu: ${labels.join(', ')}. Profilinize kaydedilmedi.`;
  form.before(note);
}

function askFromUrl() {
  const question = new URLSearchParams(location.search).get('q');
  const input = document.getElementById('chat-input');
  const form = document.getElementById('chat-form');
  if (!question?.trim() || !input || !form) return;
  // A shared trip link opens the Yolculuğum card (trip.js), not a chat answer that could name another minute.
  if (/^Yolculuk:/u.test(question.trim())) return;
  input.value = question;
  form.requestSubmit();
}

function addStylesheet() {
  if (document.querySelector('link[data-share-styles]')) return;
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = '/css/share.css';
  link.dataset.shareStyles = 'true';
  document.head.append(link);
}

function boot() {
  const savedUi = makeSavedSection();
  const selectionStatus = mountSaveButton(savedUi);
  if (!selectionStatus) return;
  addStylesheet();
  renderSaved(savedUi);
  CARD_HOSTS.forEach(({ id, kind }) => {
    const host = document.getElementById(id);
    if (!host) return;
    addSelectionHandlers(host, selectionStatus);
    const observer = new MutationObserver(() => enhanceCards(host, kind, savedUi, selectionStatus));
    observer.observe(host, { childList: true, subtree: true });
    enhanceCards(host, kind, savedUi, selectionStatus);
  });
  savedUi.list.addEventListener('click', (event) => {
    const button = event.target.closest('button[data-remove-saved]');
    if (button) removeSavedCard(button.dataset.removeSaved, savedUi, selectionStatus);
  });
  showNeedsNote();
  askFromUrl();
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true });
else boot();

export { buildShareUrl };
