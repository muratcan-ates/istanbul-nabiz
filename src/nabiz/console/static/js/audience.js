/* Age and need choices stay in this browser; only an unfiltered, fixed catalog is requested. */
import { MOCK, get } from './api.js';
import { currentLang, onLang, t } from './i18n_text.js';
import { readProfile } from './profile.js';
import { AUDIENCE_KEY, hasSelection, parseSelection, pickSuggestions, resultMarkup, sectionMarkup } from './audience_view.js';
import { esc } from './format.js';

const PERSONA_STATE_KEY = 'nabiz.persona' + '.v1';
function readSelection(win) {
  try { return parseSelection(win.localStorage.getItem(AUDIENCE_KEY)); } catch (error) { return parseSelection(null); }
}

function saveSelection(win, selection) {
  try {
    if (hasSelection(selection)) win.localStorage.setItem(AUDIENCE_KEY, JSON.stringify(selection));
    else win.localStorage.removeItem(AUDIENCE_KEY);
  } catch (error) { /* Private browsing keeps this choice for this visit only. */ }
}

function personaIsUnset(win) {
  try {
    const raw = win.localStorage.getItem(PERSONA_STATE_KEY);
    if (!raw) return true;
    const state = JSON.parse(raw);
    return Boolean(state && state.version === 1 && state.active === null);
  } catch (error) { return false; }
}

function presentTargets(doc, payload) {
  const present = new Set();
  if (doc.getElementById('chat-form') && doc.getElementById('chat-input')) present.add('composer');
  if (doc.getElementById('profilim')) present.add('profilim');
  for (const shortcut of payload?.shortcuts || []) {
    const target = doc.getElementById(shortcut.target);
    if (target && !target.closest('[hidden]')) present.add(shortcut.target);
  }
  const personaOpen = doc.getElementById('persona-open');
  const personaPicker = doc.getElementById('persona-picker');
  if (personaOpen || personaPicker?.querySelector('.persona-btn')) present.add('persona');
  if (doc.querySelector('.i18n-switch [data-language="en"]')) present.add('language-switch');
  return present;
}

function errorMarkup() {
  const message = t('ui.aud.failed', 'Öneriler şu an yüklenemedi.');
  const retry = t('ui.aud.retry', 'Yeniden dene');
  return `<p class="aud-error" aria-hidden="true">${esc(message)}</p><button type="button" class="btn btn-quiet" id="aud-retry">${esc(retry)}</button>`;
}

export async function mountAudience(doc = globalThis.document, win = globalThis.window) {
  if (!doc || !win || MOCK || doc.getElementById('size-gore')) return null;
  // P00 D2a: in Hesabım, a closed disclosure right after "Size uygun görünüm"; the chat's end without it.
  const appearance = doc.getElementById('appearance-options');
  const assistant = doc.getElementById('asistan');
  const anchor = appearance || assistant;
  if (!anchor) return null;
  if (!doc.querySelector('link[rel="stylesheet"][href="/css/audience.css"]')) {
    const link = doc.createElement('link');
    link.rel = 'stylesheet';
    link.href = '/css/audience.css';
    doc.head.appendChild(link);
  }

  let selection = readSelection(win);
  const language = () => currentLang();
  const markup = sectionMarkup(selection, language());
  anchor.insertAdjacentHTML('afterend', appearance
    ? `<details class="more account-detail" id="size-gore-detay"><summary>${esc(t('ui.aud.title', 'Size göre öneriler'))}</summary>${markup}</details>`
    : markup);
  let section = doc.getElementById('size-gore');
  if (!section) return null;
  let payload = null;
  let loadState = 'idle';
  let statusType = '';
  let shownCount = 0;
  function statusMessage() {
    if (statusType === 'cleared') return t('ui.aud.cleared', 'Seçiminiz bu cihazdan silindi.');
    if (statusType === 'failed') return t('ui.aud.failed', 'Öneriler şu an yüklenemedi.');
    if (statusType === 'count') return t('ui.aud.count', '{n} öneri gösteriliyor.', { n: shownCount });
    return '';
  }
  function drawResult() {
    const result = section.querySelector('#aud-result');
    const status = section.querySelector('#aud-status');
    if (!hasSelection(selection)) {
      result.innerHTML = '';
      result.hidden = true;
      result.removeAttribute('aria-busy');
      section.removeAttribute('aria-busy');
      status.textContent = statusMessage();
      return;
    }
    result.hidden = false;
    if (loadState === 'loading' || (loadState === 'idle' && !payload)) {
      result.innerHTML = '';
      result.setAttribute('aria-busy', 'true');
      section.setAttribute('aria-busy', 'true');
      status.textContent = '';
      return;
    }
    result.removeAttribute('aria-busy');
    section.removeAttribute('aria-busy');
    if (loadState === 'failed') {
      result.innerHTML = errorMarkup();
      statusType = 'failed';
      status.textContent = statusMessage();
      return;
    }
    const picked = pickSuggestions(payload, selection, {
      lang: language(), present: presentTargets(doc, payload), profile: readProfile(),
      personaUnset: personaIsUnset(win),
    });
    result.innerHTML = resultMarkup(picked, selection, language());
    statusType = 'count';
    shownCount = picked.chips.length + picked.more.length;
    status.textContent = statusMessage();
  }
  async function loadCatalog() {
    if (loadState === 'loading' || loadState === 'ready') return;
    loadState = 'loading';
    statusType = '';
    drawResult();
    try {
      payload = await get('/api/audience');
      loadState = 'ready';
    } catch (error) {
      loadState = 'failed';
    }
    drawResult();
  }
  function syncFormSummary() {
    const edit = section.querySelector('#aud-edit');
    edit.querySelector('summary').textContent = hasSelection(selection)
      ? t('ui.aud.edit_change', 'Seçimi değiştir')
      : t('ui.aud.edit_start', 'Yaş grubunuzu ve ihtiyacınızı seçin');
    section.querySelector('#aud-clear').hidden = !hasSelection(selection);
  }
  function onChange() {
    const form = section.querySelector('#aud-form');
    const age = form.querySelector('input[name="aud-age"]:checked')?.value || null;
    const needs = [...form.querySelectorAll('input[name="aud-need"]:checked')].map((input) => input.value);
    selection = parseSelection(JSON.stringify({ ...selection, age, needs }));
    saveSelection(win, selection);
    statusType = '';
    syncFormSummary();
    drawResult();
    if (hasSelection(selection)) void loadCatalog();
  }
  function onClick(event) {
    const target = event.target;
    if (!(target instanceof (win.Element || globalThis.Element))) return;
    const clear = target.closest('#aud-clear');
    if (clear) {
      selection = parseSelection(null);
      saveSelection(win, selection);
      statusType = 'cleared';
      syncFormSummary();
      drawResult();
      section.querySelector('#aud-edit > summary').focus();
      return;
    }
    if (target.closest('#aud-kolay-hide')) {
      selection = { ...selection, kolay_hidden: true };
      saveSelection(win, selection);
      statusType = '';
      drawResult();
      section.querySelector('#aud-title').focus();
      return;
    }
    if (target.closest('#aud-persona-open')) {
      const openButton = doc.getElementById('persona-open');
      if (openButton) openButton.click();
      else doc.querySelector('#persona-picker .persona-btn')?.focus();
      return;
    }
    if (target.closest('#aud-switch-english')) {
      doc.querySelector('.i18n-switch [data-language="en"]')?.click();
      return;
    }
    if (target.closest('#aud-retry')) {
      void loadCatalog();
      return;
    }
    const chip = target.closest('button[data-aud]');
    if (!chip || !payload) return;
    const input = doc.getElementById('chat-input');
    const form = doc.getElementById('chat-form');
    const item = payload.suggestions.find((suggestion) => suggestion.id === chip.dataset.aud);
    const text = item && (language() === 'en' ? item.text_en : item.text_tr);
    if (!input || !form || !text) return;
    input.value = text;
    input.focus();
    form.requestSubmit();
  }
  function bindSection(element) {
    element.addEventListener('change', onChange);
    element.addEventListener('click', onClick);
  }
  bindSection(section);
  const edit = section.querySelector('#aud-edit');
  if (win.location.hash === '#size-gore' && !hasSelection(selection)) edit.open = true;
  drawResult();
  onLang((nextLanguage) => {
    const wasOpen = section.querySelector('#aud-edit').open;
    const active = doc.activeElement;
    const focusId = active && section.contains(active) ? active.id : '';
    const holder = doc.createElement('div');
    holder.innerHTML = sectionMarkup(selection, nextLanguage);
    const replacement = holder.firstElementChild;
    section.replaceWith(replacement);
    section = replacement;
    bindSection(section);
    section.querySelector('#aud-edit').open = wasOpen;
    drawResult();
    if (focusId) section.querySelector(`#${focusId}`)?.focus();
  });
  if (hasSelection(selection)) await loadCatalog();
  return section;
}
if (typeof document !== 'undefined') {
  const startAudience = () => { void mountAudience(); };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', startAudience, { once: true });
  else startAudience();
}
