/* The first-run question box and quick routes. The Türkçe/English buttons belong to js/i18n.js alone:
   it keeps the choice in the URL and on the device and follows the answer-language button (#chat-lang). */

import { esc } from './format.js';
import { mountWorkspace, revealTarget } from './workspace_nav.js';

// The first paint and the fallback: js/quick_chips.js replaces these with /api/quick's chips when it answers
// (DECISIONS #43). The İSKİ question lives on there as an agency chip (data/knowledge/quick_questions.json).
const QUICK_QUESTIONS = [
  ['Ulaşım', 'İstanbul ulaşımı için resmî bilgi nerede?'],
  ['İstanbulkart', 'İstanbulkart işlemleri için resmî bilgi nerede?'],
  ['İSKİ/Fatura', 'İSKİ ve fatura işlemleri için nereye başvurabilirim?'],
  ['Sosyal Destek', 'Sosyal destek başvuruları için resmî bilgi nerede?'],
  ['Etkinlikler', 'İstanbul etkinliklerini nereden öğrenebilirim?'],
  ['Sorun Bildir / 153', 'İBB’ye bir sorunu nasıl bildirebilirim?'],
];
const QUICK_QUESTIONS_EN = [
  ['Transport', 'Where can I find official information about transport in Istanbul?'],
  ['İstanbulkart', 'Where can I find official information about İstanbulkart services?'],
  ['İSKİ / Bills', 'Where can I get help with İSKİ services and bills?'],
  ['Social Support', 'Where can I find official information about social support applications?'],
  ['Events', 'Where can I find out about events in Istanbul?'],
  ['Report a Problem / 153', 'How can I report a problem to İBB?'],
];

function quickCard(label, seedQuestion) {
  return `<button type="button" class="chip" role="button" tabindex="0" data-seed="${esc(seedQuestion)}">${esc(label)}</button>`;
}

export function openTargetDetails() {
  const hash = globalThis.location?.hash || globalThis.window?.location?.hash;
  if (!hash || hash === '#') return true;
  let id;
  try { id = decodeURIComponent(hash.slice(1)); } catch (error) { return true; }
  const target = revealTarget(id);
  if (!target) return false;
  if (!target.closest('details')) return true;
  const heading = document.getElementById(target.getAttribute('aria-labelledby')) || target.querySelector('h1, h2, h3') || target;
  if (!heading.hasAttribute('tabindex')) heading.setAttribute('tabindex', '-1');
  heading.focus({ preventScroll: false });
  return true;
}

function mountAskPill(form, input) {
  const pill = document.getElementById('ask-pill');
  if (!pill || !('IntersectionObserver' in window)) return;
  const mobile = window.matchMedia('(max-width: 640px)');
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  let formVisible = true;
  const visiblePrimaries = new Set();
  const update = () => {
    for (const button of visiblePrimaries) if (!button.isConnected) visiblePrimaries.delete(button);
    pill.hidden = !mobile.matches || formVisible || visiblePrimaries.size > 0;
  };
  const observer = new IntersectionObserver(([entry]) => { formVisible = entry.isIntersecting; update(); });
  observer.observe(form);
  const otherObserver = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (entry.isIntersecting) visiblePrimaries.add(entry.target);
      else visiblePrimaries.delete(entry.target);
    }
    update();
  });
  const seen = new WeakSet();
  const scan = () => {
    document.querySelectorAll('.btn-primary:not(#chat-submit):not(#ask-pill)').forEach((button) => {
      if (!seen.has(button)) { seen.add(button); otherObserver.observe(button); }
    });
    update();
  };
  new MutationObserver(scan).observe(document.getElementById('main'), { childList: true, subtree: true });
  scan();
  mobile.addEventListener('change', update);
  pill.addEventListener('click', () => {
    revealTarget('chat-input', { focus: true });
    form.scrollIntoView({ block: 'center', behavior: reduced.matches || document.documentElement.dataset.motion === 'reduce' ? 'instant' : 'smooth' });
  });
}

function mountPrivacyBand() {
  const chat = document.getElementById('asistan');
  const tips = document.getElementById('composer-more');
  if (!chat || !tips) return;
  const move = () => {
    const band = chat.querySelector('#privacy-band');
    if (!band) return false;
    tips.querySelector('summary')?.after(band);
    return true;
  };
  if (move()) return;
  const observer = new MutationObserver(() => { if (move()) observer.disconnect(); });
  observer.observe(chat, { childList: true });
}

function mountWorkspaces(afterMove) {
  const main = document.getElementById('main');
  if (!main || !document.getElementById('map-space')) return;
  const move = () => {
    for (const [id, slotId] of [['harita', 'map-space'], ['harita-katmanlari', 'map-space'], ['kultur', 'explore-workspace'], ['yolculugum', 'city-tools']]) {
      const node = document.getElementById(id), slot = document.getElementById(slotId);
      if (node && slot && node.parentElement !== slot) slot.appendChild(node);
    }
    afterMove();
  };
  move();
  new MutationObserver(move).observe(main, { childList: true, subtree: true });
}

function mountHome({ form, input }) {
  const cards = document.querySelector('#quick-cards');
  const more = document.querySelector('#quick-more');
  const moreCards = document.querySelector('#quick-more-cards');
  const renderFallback = (language) => {
    if (cards.querySelector('[data-quick]') || moreCards?.querySelector('[data-quick]')) return;
    const english = language === 'en';
    const questions = english ? QUICK_QUESTIONS_EN : QUICK_QUESTIONS;
    cards.lang = english ? 'en' : 'tr';
    cards.innerHTML = questions.slice(0, 3).map(([label, seed]) => quickCard(label, seed)).join('');
    cards.hidden = false;
    if (more && moreCards) {
      moreCards.lang = cards.lang;
      moreCards.innerHTML = questions.slice(3).map(([label, seed]) => quickCard(label, seed)).join('');
      more.hidden = !moreCards.innerHTML;
    }
  };
  renderFallback(document.documentElement.lang);
  window.addEventListener('nabiz:lang', (event) => {
    if (cards.querySelector('button[data-seed]') || moreCards?.querySelector('button[data-seed]')) renderFallback(event.detail?.lang);
  });
  const submitSeed = (event) => {
    const button = event.target.closest('button[data-seed]');
    if (!button) return;
    input.value = button.dataset.seed;
    form.requestSubmit();
  };
  cards.addEventListener('click', submitSeed);
  moreCards?.addEventListener('click', submitSeed);
  let pendingTarget = true;
  const revealPendingTarget = () => {
    if (pendingTarget && openTargetDetails()) pendingTarget = false;
  };
  const followHash = () => { pendingTarget = true; revealPendingTarget(); };
  window.addEventListener('hashchange', followHash);
  document.querySelector('.topbar-nav')?.addEventListener('click', (event) => {
    const link = event.target.closest('a[href^="#"]');
    if (!link) return;
    document.querySelectorAll('.topbar-nav a').forEach((node) => node.removeAttribute('aria-current'));
    link.setAttribute('aria-current', 'location');
    if (link.getAttribute('href') === '#asistan') {
      event.preventDefault();
      pendingTarget = false;
      if (window.location.hash !== '#asistan') window.history.pushState(null, '', '#asistan');
      revealTarget('chat-input', { focus: true, block: 'center' });
    } else setTimeout(followHash, 0);
  });
  document.querySelector('.topbar-nav a[href="#asistan"]')?.setAttribute('aria-current', 'location');
  mountWorkspace({ form, input });
  mountWorkspaces(revealPendingTarget);
  revealPendingTarget();
  mountPrivacyBand();
  mountAskPill(form, input);
}

export { quickCard, mountHome };
