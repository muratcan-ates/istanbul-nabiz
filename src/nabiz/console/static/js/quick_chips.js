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

// Short category pills first (Hick: three to six words, not three long questions); a pill opens
// "Daha fazla soru" filtered to its own questions, and one tap on a question asks it.
function categoryPill(category, english) {
  const label = english ? category.label_en : category.label_tr;
  return '<button type="button" class="chip quick-cat" data-cat="' + esc(category.id)
    + '" aria-expanded="false" aria-controls="quick-more">' + esc(label) + '</button>';
}

function render(payload) {
  if (!host || !payload) return;
  const english = answerLanguage(readProfile()) === 'en';
  const categories = payload.categories
    .map((category) => ({ category, chips: category.chips.filter((chip) => !english || chip.text_en) }))
    .filter((entry) => entry.chips.length);
  host.lang = english ? 'en' : 'tr';
  host.innerHTML = categories.map(({ category }) => categoryPill(category, english)).join('');
  host.hidden = categories.length === 0;
  if (!more || !moreHost) return;
  moreHost.lang = host.lang;
  moreHost.innerHTML = categories.map(({ category, chips }) => {
    const label = english ? category.label_en : category.label_tr;
    return '<div class="quick-card" data-cat="' + esc(category.id) + '" role="group" aria-labelledby="quick-t-'
      + esc(category.id) + '"><p class="quick-card-title" id="quick-t-' + esc(category.id) + '">' + esc(label)
      + '</p><div class="quick-card-chips">'
      + chips.map((chip) => chipButton({ category, chip }, english)).join('') + '</div></div>';
  }).join('');
  more.hidden = categories.length === 0;
  if (more.hidden) more.open = false;
}

function showCategory(id) {
  if (!more || !moreHost) return;
  const same = more.open && host.querySelector('.quick-cat[aria-expanded="true"]')?.dataset.cat === id;
  for (const pill of host.querySelectorAll('.quick-cat')) pill.setAttribute('aria-expanded', String(!same && pill.dataset.cat === id));
  for (const card of moreHost.querySelectorAll('.quick-card')) card.hidden = !same && card.dataset.cat !== id;
  more.open = !same;
}

if (host) {
  get('/api/quick')
    .then((payload) => {
      last = payload;
      render(last);
    })
    .catch(() => {
      // Keep the working, local question suggestions when the catalogue is unavailable.
      host.hidden = host.childElementCount === 0;
      if (more) more.hidden = !moreHost?.childElementCount;
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
  host.addEventListener('click', (event) => {
    const pill = event.target.closest('button.quick-cat');
    if (pill) showCategory(pill.dataset.cat);
    else askFromChip(event);
  });
  more?.querySelector('summary')?.addEventListener('click', () => {
    // The summary itself always means "every question": clear a pill's filter.
    for (const card of moreHost?.querySelectorAll('.quick-card') || []) card.hidden = false;
    for (const pill of host.querySelectorAll('.quick-cat')) pill.setAttribute('aria-expanded', 'false');
  });
  if (more) more.addEventListener('click', askFromChip);

  document.addEventListener('click', (event) => {
    if (event.target.closest('#chat-lang-en')) setTimeout(() => render(last), 0);
  });
  window.addEventListener('storage', () => render(last));
  window.addEventListener('nabiz:lang', () => render(last));
}

export { splitChips };
