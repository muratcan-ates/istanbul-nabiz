import { get } from './api.js';
import { esc } from './format.js';
import { readProfile, answerLanguage } from './profile.js';

const host = document.querySelector('#quick-cards');
let last = null;

function render(payload) {
  if (!host || !payload) return;
  const english = answerLanguage(readProfile()) === 'en';
  const cards = payload.categories.map((category) => {
    const label = english ? category.label_en : category.label_tr;
    const chips = category.chips
      .filter((chip) => !english || chip.text_en)
      .map((chip) => {
        const text = english ? chip.text_en : chip.text_tr;
        const suffix = english ? '(asks now)' : '(dokununca sorulur)';
        return '<button type="button" class="quick-chip" data-quick="' + esc(chip.id)
          + '" aria-label="' + esc(text + ' ' + suffix) + '">' + esc(text) + '</button>';
      })
      .join('');
    if (!chips) return '';
    return '<div class="quick-card" role="group" aria-labelledby="quick-t-' + esc(category.id)
      + '"><p class="quick-card-title" id="quick-t-' + esc(category.id) + '">' + esc(label)
      + '</p><div class="quick-card-chips">' + chips + '</div></div>';
  }).filter(Boolean);
  host.innerHTML = cards.join('');
  host.hidden = cards.length === 0;
}

if (host) {
  get('/api/quick')
    .then((payload) => {
      last = payload;
      render(last);
    })
    .catch(() => {
      if (!host.innerHTML.trim()) host.hidden = true;
    });

  host.addEventListener('click', (event) => {
    const button = event.target.closest('button[data-quick]');
    if (!button) return;
    const input = document.querySelector('#chat-input');
    const form = document.querySelector('#chat-form');
    if (!input || !form) return;
    input.value = button.textContent;
    input.focus();
    form.requestSubmit();
  });

  document.addEventListener('click', (event) => {
    if (event.target.closest('#chat-lang-en')) setTimeout(() => render(last), 0);
  });
  window.addEventListener('storage', () => render(last));
  window.addEventListener('nabiz:lang', () => render(last));
}
