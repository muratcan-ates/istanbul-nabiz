/* The first-run question box and quick routes. The Türkçe/English/عربي buttons belong to js/i18n.js alone:
   it keeps the choice in the URL and on the device and follows the answer-language button (#chat-lang). */

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

function mountHome({ form, input }) {
  const cards = document.querySelector('#quick-cards');
  cards.innerHTML = QUICK_QUESTIONS.map(([label, seed]) => quickCard(label, seed)).join('');
  cards.addEventListener('click', (event) => {
    const button = event.target.closest('button[data-seed]');
    if (!button) return;
    input.value = button.dataset.seed;
    form.requestSubmit();
  });
}

export { quickCard, mountHome };
