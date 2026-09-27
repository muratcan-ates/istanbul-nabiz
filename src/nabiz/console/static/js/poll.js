/* A self-mounting citizen poll. It makes no request until a named page anchor exists. */

import { MOCK, get } from './api.js';
import { deviceId } from './identity.js';
import { currentLang, onLang, t } from './i18n_text.js';
import { cardMarkup } from './poll_view.js';

const ANCHORS = [['#hesabim', 'beforeend']];
const STORAGE_KEY = 'nabiz.poll.v1';
const STYLESHEET = '/css/poll.css';
const REFRESH_MS = 600_000;

function readPollState(doc) {
  try {
    const raw = doc.defaultView.localStorage.getItem(STORAGE_KEY);
    const value = JSON.parse(raw || 'null');
    if (!value || value.v !== 1) return { v: 1, voted: [], dismissed: [] };
    return {
      v: 1,
      voted: Array.isArray(value.voted) ? value.voted.filter((id) => typeof id === 'string').slice(-20) : [],
      dismissed: Array.isArray(value.dismissed) ? value.dismissed.filter((id) => typeof id === 'string').slice(-20) : [],
    };
  } catch { return { v: 1, voted: [], dismissed: [] }; }
}

function rememberPoll(doc, key, id) {
  try {
    const state = readPollState(doc);
    state[key] = [...state[key].filter((item) => item !== id), id].slice(-20);
    doc.defaultView.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch { /* blocked storage must not prevent the poll from working */ }
}

function findPollAnchor(doc) {
  for (const [selector, position] of ANCHORS) {
    const element = doc.querySelector(selector);
    if (element) return { element, position };
  }
  return null;
}

function addPollStyles(doc) {
  if (doc.head.querySelector(`link[href="${STYLESHEET}"]`)) return;
  const link = doc.createElement('link');
  link.rel = 'stylesheet';
  link.href = STYLESHEET;
  link.id = 'poll-stylesheet';
  doc.head.append(link);
}

function removePollCard(doc) {
  const card = doc.getElementById('istanbula-sor');
  if (card) card.remove();
  const link = doc.getElementById('poll-stylesheet');
  if (link) link.remove();
}

function focusedPollControl(doc, card) {
  const active = doc.activeElement;
  if (!card || !active || !card.contains(active)) return null;
  if (active.matches('[data-poll-vote]')) return '[data-poll-vote]';
  if (active.matches('[data-poll-dismiss]')) return '[data-poll-dismiss]';
  if (active.matches('input[type="radio"]')) return `input[name="poll-choice"][value="${active.value}"]`;
  return null;
}

function focusNext(doc, anchor) {
  const next = anchor.position === 'afterend' ? anchor.element.nextElementSibling : anchor.element;
  const heading = next.matches('h1,h2,h3,h4') ? next : next.querySelector('h1,h2,h3,h4');
  const target = heading || doc.querySelector('#main');
  if (target && typeof target.focus === 'function') {
    if (!target.hasAttribute('tabindex')) target.setAttribute('tabindex', '-1');
    target.focus();
  }
}

export async function mountPoll(doc) {
  const anchor = findPollAnchor(doc);
  if (!anchor || MOCK) return null;
  let poll = null;
  let completion = null;
  let lastRead = 0;
  let emergency = false;
  let card = null;
  let entered = false;

  const render = () => {
    const state = readPollState(doc);
    if (!poll || emergency || (!completion && (state.voted.includes(poll.id) || state.dismissed.includes(poll.id)))) {
      removePollCard(doc);
      card = null;
      return null;
    }
    const focusSelector = focusedPollControl(doc, card);
    addPollStyles(doc);
    const markup = cardMarkup(poll);
    const existing = doc.getElementById('istanbula-sor');
    if (existing) existing.remove();
    anchor.element.insertAdjacentHTML(anchor.position, markup);
    card = doc.getElementById('istanbula-sor');
    if (card && !entered) {
      card.classList.add('is-entering');
      entered = true;
    }
    if (completion && card) {
      const form = card.querySelector('.poll-form');
      if (form) form.remove();
      const status = card.querySelector('[data-poll-status]');
      status.textContent = completion.kind === 'thanks'
        ? t('ui.poll.thanks', 'Oyunuz alındı. Teşekkürler.')
        : t('ui.poll.already', 'Bu cihazdan bu ankete zaten oy verildi.');
      status.tabIndex = -1;
    }
    if (!card) return null;
    const form = card.querySelector('.poll-form');
    if (form) form.addEventListener('submit', submitVote);
    const dismiss = card.querySelector('[data-poll-dismiss]');
    if (dismiss) dismiss.addEventListener('click', () => {
      rememberPoll(doc, 'dismissed', poll.id);
      removePollCard(doc);
      card = null;
      focusNext(doc, anchor);
    });
    if (completion) card.querySelector('[data-poll-status]').focus();
    else if (focusSelector) card.querySelector(focusSelector)?.focus({ preventScroll: true });
    return card;
  };

  async function refresh(force = false) {
    if (emergency || (!force && Date.now() - lastRead < REFRESH_MS)) return card;
    lastRead = Date.now();
    try {
      const answer = await get('/api/polls/active');
      poll = answer && answer.poll ? answer.poll : null;
      if (!poll || (completion && completion.id !== poll.id)) completion = null;
      return render();
    } catch {
      if (!card) removePollCard(doc);
      return card;
    }
  }

  async function submitVote(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const chosen = form.querySelector('input[name="poll-choice"]:checked');
    const error = form.querySelector('[data-poll-error]');
    const status = card.querySelector('[data-poll-status]');
    const button = form.querySelector('[data-poll-vote]');
    error.hidden = true;
    if (!chosen) {
      error.textContent = t('ui.poll.choose', 'Bir seçenek işaretleyin.');
      error.hidden = false;
      form.querySelector('input[type="radio"]')?.focus();
      return;
    }
    const label = button.textContent;
    button.textContent = t('ui.poll.sending', 'Gönderiliyor');
    button.setAttribute('aria-busy', 'true');
    button.setAttribute('aria-disabled', 'true');
    status.textContent = '';
    try {
      const response = await fetch(`/api/polls/${encodeURIComponent(poll.id)}/vote`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Nabiz-Device': deviceId() },
        body: JSON.stringify({ choice: chosen.value }),
      });
      if (response.ok || response.status === 409) {
        rememberPoll(doc, 'voted', poll.id);
        completion = { id: poll.id, kind: response.ok ? 'thanks' : 'already' };
        render();
        return;
      }
      let body = {};
      try { body = await response.json(); } catch { body = {}; }
      status.textContent = body.message || t('ui.poll.offline', 'Sunucuya ulaşılamadı. Bağlantınızı kontrol edip tekrar deneyin.');
    } catch {
      status.textContent = t('ui.poll.offline', 'Sunucuya ulaşılamadı. Bağlantınızı kontrol edip tekrar deneyin.');
    }
    button.textContent = label || t('ui.poll.vote', 'Oy ver');
    button.removeAttribute('aria-busy');
    button.removeAttribute('aria-disabled');
  }

  const view = doc.defaultView || globalThis.window;
  if (view && view.addEventListener) {
    view.addEventListener('nabiz:emergency', () => {
      emergency = true;
      if (card) card.hidden = true;
    });
  }
  if (doc.addEventListener) doc.addEventListener('visibilitychange', () => {
    if (!doc.hidden) void refresh(false);
  });
  onLang(() => render());
  await refresh(true);
  return card;
}

if (typeof document !== 'undefined') void mountPoll(document);
