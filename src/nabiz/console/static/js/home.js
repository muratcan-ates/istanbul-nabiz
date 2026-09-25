/* The first-run question box, quick routes and per-page language choice. Language stays in the URL. */

import { esc } from './format.js';

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

function setLanguage(lang) {
  const url = new URL(window.location.href);
  url.searchParams.set('lang', lang);
  window.history.replaceState(window.history.state, '', `${url.pathname}${url.search}${url.hash}`);
}

function mountHome({ form, input }) {
  const cards = document.querySelector('#quick-cards');
  cards.innerHTML = QUICK_QUESTIONS.map(([label, seed]) => quickCard(label, seed)).join('');
  cards.addEventListener('click', (event) => {
    const button = event.target.closest('button[data-seed]');
    if (!button) return;
    input.value = button.dataset.seed;
    form.requestSubmit();
  });

  const current = new URL(window.location.href).searchParams.get('lang') === 'en' ? 'en' : 'tr';
  document.querySelectorAll('[data-language]').forEach((button) => {
    button.setAttribute('aria-pressed', String(button.dataset.language === current));
    button.addEventListener('click', () => {
      const selected = button.dataset.language;
      setLanguage(selected);
      document.querySelectorAll('[data-language]').forEach((choice) => {
        choice.setAttribute('aria-pressed', String(choice.dataset.language === selected));
      });
    });
  });
}

export { quickCard, mountHome };
