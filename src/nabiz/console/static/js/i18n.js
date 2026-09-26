import { answerLanguage, readProfile } from './profile.js';
import { setCatalogs } from './i18n_text.js';
export const LANGS = Object.freeze(['tr', 'en']);
export const STORAGE_KEY = 'nabiz.lang.v1';
export const BINDINGS = Object.freeze([
  ['title', 'page.title', 'title'],
  ['.skip-link', 'page.skip', 'text'],
  ['.topbar-nav', 'page.nav_label', 'aria'],
  ['.topbar-nav a[href="#asistan"]', 'page.nav_assistant', 'text'],
  ['.topbar-nav a[href="#profilim"]', 'page.nav_profile', 'text'],
  ['.topbar-nav a[href="#takip"]', 'page.nav_follow', 'text'],
  ['.topbar-nav a[href="#hafizam"]', 'page.nav_memory', 'text'],
  ['#simple-toggle', 'page.simple_toggle', 'text'],
  ['.topbar-role span', 'band.not_official', 'text'],
  ['#home-title', 'page.home_title', 'text'],
  ['#home-screen [role="group"][aria-label], .topbar-actions .i18n-switch', 'switch.label', 'aria'],
  ['#chat-form > label', 'page.question_label', 'text'],
  ['#chat-input', 'page.question_placeholder', 'placeholder'],
  ['#chat-submit', 'page.ask', 'lead'],
  ['#chat-form > .field-error', 'page.question_empty', 'text'],
  ['#chat-hint', 'page.chat_hint', 'segments'],
  ['#chat-lang', 'page.answer_lang', 'lead'],
  ['#quick-cards', 'page.quick_label', 'aria'],
  ['#home-screen .band > p', 'band.ai', 'lead'],
  ['#data-mode', 'page.data_mode', 'text'],
  ['#cards-title', 'page.cards_title', 'text'],
  ['#cards-refresh', 'page.cards_refresh', 'aria'],
  ['#arrival-title', 'page.arrival_title', 'text'],
  ['[aria-labelledby="arrival-title"] .section-note', 'page.arrival_note', 'text'],
  ['label[for="arrival-line"]', 'page.line', 'text'],
  ['label[for="arrival-stop"]', 'page.stop', 'text'],
  ['[aria-labelledby="arrival-title"] .arrival-form > button', 'page.show', 'text'],
  ['[aria-labelledby="arrival-title"] .field-hint', 'page.arrival_hint', 'text'],
  ['#alternative-title', 'page.alternative_title', 'text'],
  ['[aria-labelledby="alternative-title"] .section-note, #equipment-history .section-note', 'page.first_station_note', 'text'],
  ['#compare-title', 'page.compare_title', 'text'],
  ['#compare .section-note', 'page.compare_note', 'text'],
  ['label[for="compare-from"]', 'page.compare_from', 'text'],
  ['label[for="compare-to"]', 'page.compare_to', 'text'],
  ['#compare-form > button', 'page.compare', 'text'],
  ['#equipment-history-title', 'page.history_title', 'text'],
  ['#chat-title', 'page.answers_title', 'text'],
  ['#chat-log', 'page.chat_log_label', 'aria'],
  ['#profile-title', 'page.profile_title', 'text'],
  ['#profilim .section-note', 'page.profile_note', 'text'],
  ['#profile-form fieldset:first-of-type legend', 'page.needs_legend', 'text'],
  ['label[for="station-input"]', 'page.station', 'text'],
  ['[data-add]', 'page.add', 'text'],
  ['#stations-list', 'page.stations_list', 'aria'],
  ['label[for="line-input"]', 'page.line_label', 'text'],
  ['#lines-list', 'page.lines_list', 'aria'],
  ['.check-label', 'page.consent', 'text'],
  ['.check .field-hint', 'page.consent_hint', 'text'],
  ['#consent-error', 'page.consent_error', 'text'],
  ['.privacy-list li:first-child', 'page.privacy_not_collected', 'text'],
  ['.privacy-list li:nth-child(2)', 'page.privacy_saved_places', 'text'],
  ['#profile-actions button[type="submit"]', 'page.save', 'text'],
  ['#profile-clear', 'page.profile_clear', 'text'],
  ['#memory-title', 'page.memory_title', 'lead'],
  ['#hafizam .section-note', 'page.memory_note', 'text'],
  ['#hafizam > p', 'page.memory_prompt', 'text'],
  ['#memory-empty', 'page.memory_empty', 'text'],
  ['#memory-clear', 'page.memory_clear', 'text'],
  ['#attribution', 'page.attribution', 'segments'],
  ['#hakkinda', 'page.about', 'segments'],
  ['footer a[href="/console"]', 'page.footer_console', 'text'],
  ['footer a[href="/kvkk.html"]', 'page.footer_kvkk', 'text'],
  ['#privacy-band p', 'privacy.band', 'segments'],
  ['#account-title', 'page.account_title', 'text'],
  ['#hesap .section-note', 'page.account_note', 'text'],
  ['#hesap > p', 'page.account_prompt', 'text'],
  ['#follow-title', 'page.follow_title', 'text'],
  ['#takip .section-note', 'page.follow_note', 'text'],
  ['#takip > .field-hint', 'page.follow_hint', 'text'],
  ['#follow-empty', 'page.follow_empty', 'text'],
  ['#acik-veri-title', 'page.open_data_title', 'text'],
  ['#acik-veri .section-note', 'page.open_data_note', 'text'],
  ['label[for="acik-veri-q"]', 'page.open_data_label', 'text'],
  ['#acik-veri-q', 'page.open_data_placeholder', 'placeholder'],
  ['#acik-veri-form > button', 'page.open_data_search', 'text'],
  ['#acik-veri-chips', 'page.open_data_categories', 'aria'],
]);
const EXCLUDED = '.chat-msg.is-user .chat-text, blockquote.quote-exact, .quote-box blockquote, input, textarea, #cards, #arrival, #alternative, #compare-result, #quick-cards, figcaption.quote-src';
const textOriginals = new Map(), attributeOriginals = new Map(), catalogPromises = new Map();
let activeLanguage = 'tr', activeFallback = {}, activeCatalog = {}, originalTitle = null, mounted = false, syncing = false;
export function sameText(left, right) { return typeof left === 'string' && typeof right === 'string' && left.replace(/\s+/g, ' ').trim() === right.replace(/\s+/g, ' ').trim(); }
const validValue = (value) => typeof value === 'string' ? Boolean(value.trim())
  : Array.isArray(value) && value.length > 0 && value.every((item) => typeof item === 'string' && item.trim());
export function lookup(catalog, fallback, key) {
  const value = catalog?.[key];
  if (validValue(value)) return value;
  const defaultValue = fallback?.[key];
  return validValue(defaultValue) ? defaultValue : null;
}
const validLang = (value) => LANGS.includes(value) ? value : null;
function urlLang(url) {
  try {
    const base = typeof window === 'undefined' ? 'https://nabiz.invalid/' : window.location.href;
    return validLang((url instanceof URLSearchParams ? url : new URL(url || base, base).searchParams).get('lang'));
  } catch (error) { return null; }
}
export function pickLang({ url, stored, profileLang } = {}) { return urlLang(url) || validLang(stored) || (profileLang === 'en' ? 'en' : 'tr'); }
function fetchCatalog(lang) {
  if (!catalogPromises.has(lang)) catalogPromises.set(lang, fetch(`/i18n/${lang}.json`).then((response) => {
    if (!response.ok) throw new Error('catalog unavailable'); return response.json();
  }).catch(() => ({})));
  return catalogPromises.get(lang);
}
function readStoredLang() { try { return window.localStorage.getItem(STORAGE_KEY); } catch (error) { return null; } }
function saveLang(lang) { try { window.localStorage.setItem(STORAGE_KEY, lang); } catch (error) { /* private browsing */ } }
function updateUrl(lang) { const url = new URL(window.location.href); url.searchParams.set('lang', lang); window.history.replaceState(window.history.state, '', `${url.pathname}${url.search}${url.hash}`); }
function writeText(node, value) {
  const raw = node.data;
  const start = raw.match(/^\s*/)?.[0] || '', end = raw.match(/\s*$/)?.[0] || '';
  if (raw.trim() !== value && raw !== `${start}${value}${end}`) {
    if (!textOriginals.has(node)) textOriginals.set(node, raw);
    node.data = `${start}${value}${end}`;
  }
}
function restoreOriginals() {
  for (const [node, value] of textOriginals) node.isConnected ? node.data = value : textOriginals.delete(node);
  for (const [element, attributes] of attributeOriginals) {
    if (!element.isConnected) { attributeOriginals.delete(element); continue; }
    for (const [name, value] of attributes) value === null ? element.removeAttribute(name) : element.setAttribute(name, value);
  }
  if (originalTitle !== null) document.title = originalTitle;
}
function textNodes(element, descendants = false) {
  if (!descendants) return [...element.childNodes].filter((node) => node.nodeType === Node.TEXT_NODE && node.data.trim());
  const found = [];
  const visit = (node) => { for (const child of node.childNodes) child.nodeType === Node.TEXT_NODE && child.data.trim()
    ? found.push(child) : child.nodeType === Node.ELEMENT_NODE && child.tagName.toLowerCase() !== 'svg' && visit(child); };
  visit(element);
  return found;
}
function saveAttribute(element, name, value) {
  if (!attributeOriginals.has(element)) attributeOriginals.set(element, new Map());
  const saved = attributeOriginals.get(element); if (!saved.has(name)) saved.set(name, value);
}
function bindElement(element, fallback, target, mode) {
  if (mode === 'aria' || mode === 'placeholder') {
    const name = mode === 'aria' ? 'aria-label' : 'placeholder';
    let current = element.getAttribute(name);
    if (current === null && typeof fallback === 'string') { saveAttribute(element, name, null); element.setAttribute(name, fallback); current = fallback; }
    if (sameText(current || '', fallback) && typeof target === 'string') { saveAttribute(element, name, current); element.setAttribute(name, target); }
    return;
  }
  if (mode === 'title') { if (sameText(document.title, fallback) && typeof target === 'string') { originalTitle ??= document.title; document.title = target; } return; }
  const nodes = textNodes(element, mode === 'segments');
  if (mode === 'lead') {
    if (nodes[0] && typeof fallback === 'string' && typeof target === 'string' && sameText(nodes[0].data, fallback)) writeText(nodes[0], target);
  } else if (mode === 'segments') {
    if (Array.isArray(fallback) && Array.isArray(target) && nodes.length === fallback.length && target.length === fallback.length
      && nodes.every((node, index) => sameText(node.data, fallback[index]))) nodes.forEach((node, index) => writeText(node, target[index]));
  } else if (nodes.length === 1 && typeof fallback === 'string' && typeof target === 'string' && sameText(nodes[0].data, fallback)) writeText(nodes[0], target);
}
function applyBindings(tr, target) {
  for (const [selector, key, mode] of BINDINGS) {
    const fallback = tr[key], value = lookup(target, tr, key);
    if (value === null) continue;
    const elements = selector === 'title' ? [document.querySelector('title')].filter(Boolean) : document.querySelectorAll(selector);
    elements.forEach((element) => bindElement(element, fallback, value, mode));
  }
}
const excluded = (node) => Boolean(node.parentElement?.closest(EXCLUDED));
function translateNode(node, tr, target) {
  if (!node || excluded(node)) return;
  const text = node.data.replace(/\s+/g, ' ').trim();
  if (!text) return;
  for (const key of Object.keys(tr)) {
    const fallback = tr[key];
    if ((!key.startsWith('dyn.') && !key.startsWith('fixed.')) || typeof fallback !== 'string' || !sameText(text, fallback)) continue;
    const value = lookup(target, tr, key);
    if (typeof value === 'string') writeText(node, value);
    return;
  }
  for (const key of Object.keys(tr)) {
    const prefix = tr[key];
    if (!key.startsWith('dynp.') || typeof prefix !== 'string' || !text.startsWith(`${prefix} `)) continue;
    const value = lookup(target, tr, key);
    if (typeof value === 'string') {
      const leading = node.data.match(/^\s*/)?.[0] || '';
      writeText(node, `${value}${node.data.slice(leading.length + prefix.length)}`);
    }
    return;
  }
}
function visitDynamic(root, tr, target) {
  const walk = (node) => node.nodeType === Node.TEXT_NODE ? translateNode(node, tr, target)
    : node.nodeType === Node.ELEMENT_NODE && !node.matches(EXCLUDED) && [...node.childNodes].forEach(walk);
  walk(root);
}
function quoteNodes(root = document) { const selector = 'blockquote.quote-exact, .quote-box blockquote.quote-text'; return [...(root.nodeType === Node.ELEMENT_NODE && root.matches(selector) ? [root] : []), ...(root.querySelectorAll?.(selector) || [])]; }
function frameQuotes(language, catalog, fallback) {
  for (const quote of quoteNodes()) {
    const previous = quote.previousElementSibling;
    const label = previous?.classList.contains('i18n-source-lang') ? previous : null;
    if (language === 'tr') { quote.removeAttribute('lang'); quote.removeAttribute('dir'); label?.remove(); continue; }
    quote.setAttribute('lang', 'tr'); quote.setAttribute('dir', 'ltr');
    const note = label || document.createElement('p');
    note.className = 'field-hint i18n-source-lang'; note.lang = language; note.dataset.i18n = '1';
    note.textContent = lookup(catalog, fallback, 'quote.source_is_turkish') || '';
    if (!label) quote.before(note);
  }
}
function setDirection(language) {
  const root = document.documentElement;
  root.lang = language; root.dir = 'ltr';
  const input = document.querySelector('#chat-input');
  if (input) language === 'tr' ? input.removeAttribute('dir') : input.setAttribute('dir', 'auto');
  document.querySelectorAll('.answer-short p, .ac-short p, .chat-text').forEach((node) => language === 'tr' ? node.removeAttribute('dir') : node.setAttribute('dir', 'auto'));
  ['#cards', '#arrival', '#alternative', '#compare-result'].forEach((selector) => {
    const node = document.querySelector(selector);
    if (node) language === 'tr' ? node.removeAttribute('lang') : node.setAttribute('lang', 'tr');
  });
  const chips = document.querySelector('#quick-cards');
  if (chips) language === 'tr' ? chips.removeAttribute('lang') : chips.setAttribute('lang', answerLanguage(readProfile()));
}
function setPressed(group, language) { group?.querySelectorAll('[data-language]').forEach((button) => button.setAttribute('aria-pressed', String(button.dataset.language === language))); }
function addLanguageButton(group, lang, text) {
  let button = group.querySelector(`[data-language="${lang}"]`);
  if (!button) { button = document.createElement('button'); button.type = 'button'; button.className = 'btn'; button.dataset.language = lang; button.textContent = text; group.append(button); }
  button.lang = lang;
  return button;
}
function mountLanguageGroup() {
  let group = document.querySelector('#home-screen [role="group"][aria-label]');
  if (!group || !group.querySelector('[data-language]')) {
    const actions = document.querySelector('.topbar-actions');
    if (!actions) return null;
    group = document.createElement('div'); group.className = 'btn-row i18n-switch'; group.setAttribute('role', 'group'); actions.append(group);
  }
  group.classList.add('i18n-switch');
  addLanguageButton(group, 'tr', 'Türkçe');
  const en = addLanguageButton(group, 'en', 'English');
  if (!(en.previousElementSibling?.tagName === 'SPAN' && en.previousElementSibling.getAttribute('aria-hidden') === 'true')) {
    const separator = document.createElement('span'); separator.className = 'i18n-separator'; separator.setAttribute('aria-hidden', 'true'); separator.textContent = '·'; en.before(separator);
  }
  if (!group.dataset.i18nBound) {
    group.addEventListener('click', (event) => {
      const button = event.target.closest?.('[data-language]');
      if (button && group.contains(button)) void setLang(button.dataset.language);
    });
    group.dataset.i18nBound = '1';
  }
  return group;
}
function syncAnswerLanguage(language) {
  if (answerLanguage(readProfile()) === (language === 'tr' ? 'tr' : 'en')) return;
  const button = document.querySelector('#chat-lang-en');
  if (!button) return;
  syncing = true;
  try { button.click(); } finally { syncing = false; }
}
function setAnswerNote(language, catalog, fallback) {
  let note = document.querySelector('#i18n-answer-note');
  if (language === 'tr') { note?.remove(); return; }
  if (!note) {
    note = document.createElement('p'); note.id = 'i18n-answer-note'; note.className = 'field-hint'; note.dataset.i18n = '1';
    document.querySelector('#chat-hint')?.after(note);
  }
  note.lang = language; note.textContent = lookup(catalog, fallback, 'note.answer_lang') || '';
}
async function applyLanguage(language, { sync = false, persist = false, update = false } = {}) {
  if (!validLang(language) || !mounted) return;
  activeLanguage = language; setDirection(language);
  const group = document.querySelector('.i18n-switch'); setPressed(group, language);
  if (persist) { try { window.localStorage.setItem(STORAGE_KEY, language); } catch (error) { /* private browsing */ } }
  if (update) updateUrl(language);
  if (sync) syncAnswerLanguage(language);
  const [fallback, catalog] = await Promise.all([fetchCatalog('tr'), fetchCatalog(language)]);
  if (activeLanguage !== language) return;
  activeFallback = fallback; activeCatalog = catalog; restoreOriginals(); applyBindings(fallback, catalog);
  setCatalogs(language, catalog, fallback);
  visitDynamic(document.body, fallback, catalog); frameQuotes(language, catalog, fallback);
  setAnswerNote(language, catalog, fallback); setPressed(group, language);
  window.dispatchEvent(new CustomEvent('nabiz:lang', { detail: { lang: language } }));
}
export function setLang(language, { sync = true } = {}) {
  return applyLanguage(language, { sync, persist: true, update: true });
}
export function mountI18n() {
  if (mounted || typeof document === 'undefined') return;
  const group = mountLanguageGroup();
  if (!group) return;
  mounted = true;
  const currentUrl = window.location.href, explicit = urlLang(currentUrl);
  document.addEventListener('click', (event) => {
    if (syncing || !event.target.closest?.('#chat-lang-en')) return;
    setTimeout(() => {
      const language = answerLanguage(readProfile());
      if (language !== (activeLanguage === 'tr' ? 'tr' : 'en')) void setLang(language, { sync: false });
    }, 0);
  });
  const observer = new MutationObserver((records) => {
    for (const record of records) for (const node of record.addedNodes) {
      visitDynamic(node, activeFallback, activeCatalog);
      if (quoteNodes(node).length) frameQuotes(activeLanguage, activeCatalog, activeFallback);
      if (node.nodeType === Node.ELEMENT_NODE) {
        if (node.matches('.answer-short p, .ac-short p, .chat-text') && activeLanguage !== 'tr') node.setAttribute('dir', 'auto');
        node.querySelectorAll?.('.answer-short p, .ac-short p, .chat-text').forEach((item) => { if (activeLanguage !== 'tr') item.setAttribute('dir', 'auto'); });
      }
    }
  });
  observer.observe(document.body, { childList: true, subtree: true });
  void applyLanguage(pickLang({ url: currentUrl, stored: readStoredLang(), profileLang: answerLanguage(readProfile()) }), { sync: Boolean(explicit) });
}
if (typeof document !== 'undefined') mountI18n();
