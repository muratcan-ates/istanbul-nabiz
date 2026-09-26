import { get } from './api.js';
import { esc } from './format.js';
import { icon } from './icons.js';
import { readProfile, answerLanguage } from './profile.js';

const host = document.querySelector('#quick-cards');
const more = document.querySelector('#quick-more');
const moreHost = document.querySelector('#quick-more-cards');
const CATEGORY_ICONS = { ulasim: 'route', 'sorun-153': 'info-circle' };
let last = null;

function splitChips(categories, limit = 3, english = false) {
  const visible = [];
  const remaining = [];
  let slots = Math.max(0, limit);
  for (const category of categories) {
    const chips = category.chips.filter((chip) => !english || chip.text_en);
    const first = chips.slice(0, slots);
    visible.push(...first.map((chip) => ({ category, chip })));
    slots -= first.length;
    const rest = chips.slice(first.length);
    if (rest.length) remaining.push({ category, chips: rest });
  }
  return { visible, remaining };
}

function chipButton({ category, chip }, english) {
  const text = english ? chip.text_en : chip.text_tr;
  const suffix = english ? '(asks now)' : '(dokununca sorulur)';
  const glyph = CATEGORY_ICONS[category.id] ? icon(CATEGORY_ICONS[category.id]) : '';
  return '<button type="button" class="quick-chip" data-quick="' + esc(chip.id)
    + '" aria-label="' + esc(text + ' ' + suffix) + '">' + glyph + esc(text) + '</button>';
}

function render(payload) {
  if (!host || !payload) return;
  const english = answerLanguage(readProfile()) === 'en';
  const { visible, remaining } = splitChips(payload.categories, 3, english);
  host.lang = english ? 'en' : 'tr';
  host.innerHTML = visible.map((entry) => chipButton(entry, english)).join('');
  host.hidden = visible.length === 0;
  if (!more || !moreHost) return;
  moreHost.lang = host.lang;
  const cards = remaining.map(({ category, chips }) => {
    const label = english ? category.label_en : category.label_tr;
    return '<div class="quick-card" role="group" aria-labelledby="quick-t-' + esc(category.id)
      + '"><p class="quick-card-title" id="quick-t-' + esc(category.id) + '">' + esc(label)
      + '</p><div class="quick-card-chips">'
      + chips.map((chip) => chipButton({ category, chip }, english)).join('') + '</div></div>';
  });
  moreHost.innerHTML = cards.join('');
  more.hidden = cards.length === 0;
  if (more.hidden) more.open = false;
}

if (host) {
  get('/api/quick')
    .then((payload) => {
      last = payload;
      render(last);
    })
    .catch(() => {
      host.hidden = true;
      if (more) more.hidden = true;
    });

  function askFromChip(event) {
    const button = event.target.closest('button[data-quick]');
    if (!button) return;
    const input = document.querySelector('#chat-input');
    const form = document.querySelector('#chat-form');
    if (!input || !form) return;
    input.value = button.textContent;
    input.focus();
    form.requestSubmit();
  }
  host.addEventListener('click', askFromChip);
  if (more) more.addEventListener('click', askFromChip);

  document.addEventListener('click', (event) => {
    if (event.target.closest('#chat-lang-en')) setTimeout(() => render(last), 0);
  });
  window.addEventListener('storage', () => render(last));
  window.addEventListener('nabiz:lang', () => render(last));
}

export { splitChips };
