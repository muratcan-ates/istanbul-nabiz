/* The first-run question box and quick routes. The Türkçe/English buttons belong to js/i18n.js alone:
   it keeps the choice in the URL and on the device and follows the answer-language button (#chat-lang). */

import { esc } from './format.js';

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

function quickCard(label, seedQuestion) {
  return `<button type="button" class="chip" role="button" tabindex="0" data-seed="${esc(seedQuestion)}">${esc(label)}</button>`;
}

export function openTargetDetails() {
  const hash = globalThis.location?.hash || globalThis.window?.location?.hash;
  if (!hash || hash === '#') return;
  let id;
  try { id = decodeURIComponent(hash.slice(1)); } catch (error) { return; }
  const target = document.getElementById(id);
  if (!target) return;
  const details = target.closest('details');
  if (!details) return;
  details.open = true;
  const heading = document.getElementById(target.getAttribute('aria-labelledby')) || target.querySelector('h1, h2, h3') || target;
  if (!heading.hasAttribute('tabindex')) heading.setAttribute('tabindex', '-1');
  heading.focus({ preventScroll: false });
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
    input.focus({ preventScroll: true });
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

function mountHome({ form, input }) {
  const cards = document.querySelector('#quick-cards');
  const more = document.querySelector('#quick-more');
  const moreCards = document.querySelector('#quick-more-cards');
  cards.innerHTML = QUICK_QUESTIONS.slice(0, 3).map(([label, seed]) => quickCard(label, seed)).join('');
  if (more && moreCards) {
    moreCards.innerHTML = QUICK_QUESTIONS.slice(3).map(([label, seed]) => quickCard(label, seed)).join('');
    more.hidden = !moreCards.innerHTML;
  }
  const submitSeed = (event) => {
    const button = event.target.closest('button[data-seed]');
    if (!button) return;
    input.value = button.dataset.seed;
    form.requestSubmit();
  };
  cards.addEventListener('click', submitSeed);
  moreCards?.addEventListener('click', submitSeed);
  openTargetDetails();
  window.addEventListener('hashchange', openTargetDetails);
  document.querySelector('.topbar-nav')?.addEventListener('click', (event) => {
    if (event.target.closest('a[href^="#"]')) setTimeout(openTargetDetails, 0);
  });
  mountPrivacyBand();
  mountAskPill(form, input);
}

export { quickCard, mountHome };
