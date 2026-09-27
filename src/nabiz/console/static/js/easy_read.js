import { RATES, collectBlocks, listenPlan, chooseVoice, createListener, splitSentences } from './easy_read_listen.js';
import { currentLang, onLang, t } from './i18n_text.js';
export const EASY_PREFS_KEY = 'nabiz.easyread.v1';
export const DEFAULT_EASY_PREFS = Object.freeze({ version: 1, on: false, rate: 1 });
export const TARGET_SELECTOR = '.chat-msg.is-assistant .answer-short p, .chat-msg.is-assistant .chat-final ol > li, .answer-card .ac-short p, .answer-card .ac-steps li, .answer-card .ac-fixed, [data-er-target]';
export const PROTECTED_SELECTOR = '.quote-exact, .quote-box, .quote-text, figure.quote, blockquote, .cites, .chat-foot, .is-refused .answer-short, .is-refused .ac-fixed, [data-er-skip]';
export const TEXT = Object.freeze({
  toggle: 'Kolay okunur', listen: 'Dinle', pause: 'Duraklat', resume: 'Sürdür', stop: 'Durdur',
  rates: ['Yavaş 0,8', 'Normal 1', 'Hızlı 1,2'], tools: 'Okuma araçları', speed: 'Okuma hızı',
  on: 'Kolay okunur açık.', off: 'Kolay okunur kapalı.', glossaryError: 'Terim açıklamaları yüklenemedi.',
  localOnly: 'Bu tarayıcının Türkçe sesi çevrim içi; okunan metin tarayıcının ses sağlayıcısına gidebilir. Nabız sunucusuna gitmez.',
  noVoice: 'Bu tarayıcıda Türkçe ses yok; Dinle kapalı.', wrongLanguage: 'Dinle yalnız Türkçe cevapta çalışır.',
  glossaryNote: 'Genel anlam; resmî tanım değildir.', colon: ': ', restoreError: 'Metin görünümü korunamadı; özgün metin geri yüklendi.',
});

export { splitSentences };
export function parseEasyPrefs(raw) {
  try { const value = JSON.parse(raw); if (!value || value.version !== 1 || typeof value.on !== 'boolean' || !RATES.includes(value.rate)) throw new Error('prefs'); return { version: 1, on: value.on, rate: value.rate }; }
  catch (error) { return { ...DEFAULT_EASY_PREFS }; }
}

export function buildTermIndex(glossary) {
  const index = [];
  for (const item of Array.isArray(glossary?.terms) ? glossary.terms : []) {
    if (!item || typeof item.id !== 'string' || typeof item.term !== 'string' || typeof item.plain !== 'string') continue;
    for (const raw of Array.isArray(item.forms) ? item.forms : []) {
      if (typeof raw !== 'string' || !raw) continue;
      const form = raw.toLocaleLowerCase('tr-TR');
      if (Array.from(form).length === Array.from(raw).length) index.push({ id: item.id, term: item.term, plain: item.plain, form });
    }
  }
  return index.sort((a, b) => b.form.length - a.form.length || a.form.localeCompare(b.form, 'tr-TR'));
}

export function markTerms(sentence, index, seen = new Set()) {
  const source = String(sentence ?? ''), lower = source.toLocaleLowerCase('tr-TR');
  if (Array.from(lower).length !== Array.from(source).length || !Array.isArray(index) || !index.length) return [{ text: source, id: null }];
  const parts = [];
  let cursor = 0;
  while (cursor < source.length && seen.size < 6) {
    let best = null;
    for (const entry of index) {
      if (seen.has(entry.id)) continue;
      let at = lower.indexOf(entry.form, cursor);
      while (at !== -1) {
        const before = Array.from(lower.slice(0, at)).at(-1) || '', after = Array.from(lower.slice(at + entry.form.length))[0] || '';
        if (!/[\p{L}\p{N}]/u.test(before) && !/[\p{L}\p{N}]/u.test(after)) {
          if (!best || at < best.at || (at === best.at && entry.form.length > best.entry.form.length)) best = { at, entry };
          break;
        }
        at = lower.indexOf(entry.form, at + 1);
      }
    }
    if (!best) break;
    parts.push({ text: source.slice(cursor, best.at), id: null });
    const end = best.at + best.entry.form.length;
    parts.push({ text: source.slice(best.at, end), id: best.entry.id, term: best.entry.term, plain: best.entry.plain });
    seen.add(best.entry.id); cursor = end;
  }
  if (!parts.length) return [{ text: source, id: null }];
  if (cursor < source.length) parts.push({ text: source.slice(cursor), id: null });
  return parts.filter((part) => part.text.length || part.id);
}

export function shouldTouch(el) { if (!el || typeof el.closest !== 'function' || el.closest('.chat-msg.is-assistant.is-refused')) return false; return !el.closest(PROTECTED_SELECTOR) && el.childElementCount === 0; }
const originals = new WeakMap(), seenTerms = new WeakMap(), processed = new WeakSet(), wrapped = new Set();
let termIndex = [], termsById = new Map(), glossaryPromise = null, enabled = false;
let preferences = { ...DEFAULT_EASY_PREFS }, listener = null, activeBar = null, tip = null, status = null;
function say(message) { if (status) status.textContent = message; }
function savePreferences() { try { window.localStorage.setItem(EASY_PREFS_KEY, JSON.stringify(preferences)); } catch (error) { /* Private mode keeps this session only. */ } }
function makeElement(tag, className, text) {
  const element = document.createElement(tag); if (className) element.className = className;
  if (text !== undefined) element.textContent = text; return element;
}
function makeButton(className, label, pressed = false) {
  const button = makeElement('button', 'btn ' + className, label); button.type = 'button';
  if (className !== 'er-stop') button.setAttribute('aria-pressed', String(pressed));
  return button;
}
function makeTooltip() {
  let element = document.getElementById('er-tip'); if (element) return element;
  element = makeElement('div', 'er-tip'); element.id = 'er-tip'; element.setAttribute('role', 'tooltip');
  element.hidden = true; document.body.appendChild(element); return element;
}
function closeTip() { if (tip) tip.hidden = true; }
function showTip(button) {
  const item = termsById.get(button.dataset.term); if (!item || !tip) return;
  tip.textContent = ''; tip.appendChild(makeElement('b', '', item.term)); tip.appendChild(document.createTextNode(TEXT.colon + item.plain));
  tip.appendChild(document.createElement('br')); tip.appendChild(makeElement('small', '', TEXT.glossaryNote)); tip.hidden = false;
  button.setAttribute('aria-describedby', 'er-tip');
  const rect = button.getBoundingClientRect();
  tip.style.left = Math.max(8, Math.min(window.scrollX + rect.left, window.scrollX + window.innerWidth - tip.offsetWidth - 8)) + 'px';
  tip.style.top = (window.scrollY + rect.bottom + 6) + 'px';
}
function cardFor(el) { return el.closest('li.chat-msg.is-assistant') || el.closest('.answer-card') || el; }

function wrapElement(el) {
  if (!shouldTouch(el)) return;
  if (!enabled) return;
  const original = originals.has(el) ? originals.get(el) : el.textContent;
  if (el.querySelector('.er-sentence')) return;
  originals.set(el, original);
  const card = cardFor(el), seen = seenTerms.get(card) || new Set();
  seenTerms.set(card, seen);
  const fragment = document.createDocumentFragment();
  for (const sentence of splitSentences(original)) {
    const line = makeElement('span', 'er-sentence');
    for (const part of markTerms(sentence, termIndex, seen)) {
      if (!part.id || !termsById.has(part.id)) line.appendChild(document.createTextNode(part.text));
      else {
        const button = makeElement('button', 'er-term', part.text); button.type = 'button'; button.dataset.term = part.id;
        button.setAttribute('aria-describedby', 'er-tip'); line.appendChild(button);
      }
    }
    fragment.appendChild(line);
  }
  el.replaceChildren(fragment);
  if (el.textContent !== original) { el.textContent = original; originals.delete(el); say(TEXT.restoreError); return; }
  wrapped.add(el);
}
function unwrapElement(el) { if (originals.has(el)) { el.textContent = originals.get(el); originals.delete(el); wrapped.delete(el); } }
function updateToggleButtons() { document.querySelectorAll('.er-toggle').forEach((button) => button.setAttribute('aria-pressed', String(enabled))); }
function updateRateButtons() { document.querySelectorAll('.er-rate').forEach((button) => button.setAttribute('aria-pressed', String(Number(button.dataset.rate) === preferences.rate))); }
function readingOptionsLabel() { return t('dyn.reading_options', currentLang() === 'en' ? 'Reading options' : 'Okuma seçenekleri'); }
function updateReadingOptions() { document.querySelectorAll('.er-options > summary').forEach((summary) => { summary.textContent = readingOptionsLabel(); }); }
function loadGlossary() {
  if (!glossaryPromise) glossaryPromise = fetch('/data/glossary_tr.json')
    .then((response) => { if (!response.ok) throw new Error('glossary'); return response.json(); })
    .then((glossary) => { termIndex = buildTermIndex(glossary); termsById = new Map((glossary.terms || []).map((item) => [item.id, item])); return termIndex; })
    .catch(() => { say(TEXT.glossaryError); return []; });
  return glossaryPromise;
}

function markBubble(bubble) {
  if (!bubble || processed.has(bubble) || bubble.getAttribute('aria-busy') !== 'false'
      || bubble.classList.contains('is-error') || bubble.classList.contains('is-emergency')) return;
  const final = bubble.querySelector('.chat-final');
  if (!final || !final.textContent.trim()) return;
  processed.add(bubble);
  const bar = makeElement('div', 'er-bar');
  bar.setAttribute('role', 'group'); bar.setAttribute('aria-label', TEXT.tools); bar.setAttribute('aria-live', 'off');
  const toggle = makeButton('er-toggle', TEXT.toggle, enabled), speak = makeButton('er-listen', TEXT.listen);
  const stop = makeButton('er-stop', TEXT.stop); stop.hidden = true;
  const rates = makeElement('span', 'er-rates'); rates.setAttribute('role', 'group'); rates.setAttribute('aria-label', TEXT.speed);
  RATES.forEach((rate, index) => {
    const button = makeButton('er-rate', TEXT.rates[index], rate === preferences.rate);
    button.dataset.rate = String(rate); rates.appendChild(button);
  });
  const options = makeElement('details', 'er-options');
  options.appendChild(makeElement('summary', '', readingOptionsLabel()));
  options.appendChild(rates);
  const progress = makeElement('span', 'er-progress'); progress.setAttribute('aria-hidden', 'true');
  const note = makeElement('p', 'er-note'); note.hidden = true;
  [toggle, speak, stop, progress, options, note].forEach((item) => bar.appendChild(item));
  final.insertBefore(bar, final.firstChild);
  toggle.addEventListener('click', () => {
    preferences = { ...preferences, on: !enabled }; savePreferences(); applyEnabled(preferences.on); say(enabled ? TEXT.on : TEXT.off);
  });
  bar.addEventListener('click', (event) => {
    const rateButton = event.target.closest('.er-rate');
    if (rateButton) {
      preferences = { ...preferences, rate: Number(rateButton.dataset.rate) }; savePreferences(); updateRateButtons();
      if (listener) listener.setRate(preferences.rate);
    } else if (event.target.closest('.er-stop')) { if (listener) listener.stop(); }
    else if (event.target.closest('.er-listen') && !speak.disabled && listener) {
      if (activeBar !== bar) { if (listener.state !== 'idle') listener.stop(); activeBar = bar; }
      if (listener.state === 'speaking') listener.pause();
      else if (listener.state === 'paused') listener.resume();
      else listener.start(bubble, listenPlan(collectBlocks(bubble)), preferences.rate);
    }
  });
  refreshAudio();
  if (enabled) loadGlossary().then(() => bubble.querySelectorAll(TARGET_SELECTOR).forEach(wrapElement));
}
function renderTargets(root = document) {
  root.querySelectorAll('li.chat-msg.is-assistant').forEach((bubble) => {
    if (!bubble.classList.contains('is-error') && !bubble.classList.contains('is-emergency')) bubble.querySelectorAll(TARGET_SELECTOR).forEach(wrapElement);
  });
}
function applyEnabled(on) {
  enabled = Boolean(on);
  if (enabled) { document.documentElement.dataset.easyRead = 'on'; loadGlossary().then(() => renderTargets()); }
  else {
    delete document.documentElement.dataset.easyRead;
    for (const el of Array.from(wrapped)) { seenTerms.delete(cardFor(el)); unwrapElement(el); }
    closeTip();
  }
  updateToggleButtons();
}

function updateListeningUI(state, index, total) {
  if (!activeBar) return;
  const button = activeBar.querySelector('.er-listen'), stop = activeBar.querySelector('.er-stop'), progress = activeBar.querySelector('.er-progress');
  if (state === 'speaking') {
    button.textContent = TEXT.pause; button.setAttribute('aria-pressed', 'true'); stop.hidden = false; progress.textContent = (index + 1) + '/' + total;
  } else if (state === 'paused') {
    button.textContent = TEXT.resume; button.setAttribute('aria-pressed', 'true'); stop.hidden = false;
  } else {
    button.textContent = TEXT.listen; button.setAttribute('aria-pressed', 'false'); stop.hidden = true; progress.textContent = '';
  }
}
function textRange(root, start, end) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let node, offset = 0, first = null, last = null;
  while ((node = walker.nextNode())) {
    const next = offset + node.textContent.length;
    if (!first && start >= offset && start <= next) first = { node, offset: start - offset };
    if (end >= offset && end <= next) { last = { node, offset: end - offset }; break; }
    offset = next;
  }
  if (!first || !last) return null;
  const range = document.createRange(); range.setStart(first.node, first.offset); range.setEnd(last.node, last.offset); return range;
}
function clearHighlight() { if (globalThis.CSS && CSS.highlights) CSS.highlights.delete('er-now'); document.querySelectorAll('.er-sentence.is-speaking').forEach((span) => span.classList.remove('is-speaking')); }
function highlightSentence(item) {
  clearHighlight();
  if (!item || !item.block || !item.block.nodeType) return;
  const range = textRange(item.block, item.start, item.end);
  if (!range) return;
  if (globalThis.CSS && CSS.highlights && typeof Highlight === 'function') CSS.highlights.set('er-now', new Highlight(range));
  else if (enabled) {
    const span = range.startContainer.parentElement.closest('.er-sentence');
    if (span) span.classList.add('is-speaking');
  }
}
function refreshAudio() {
  const voice = listener && window.speechSynthesis ? chooseVoice(window.speechSynthesis.getVoices()) : null;
  document.querySelectorAll('.er-bar').forEach((bar) => {
    const bubble = bar.closest('li.chat-msg.is-assistant'), button = bar.querySelector('.er-listen'), note = bar.querySelector('.er-note');
    const langNode = bubble && bubble.closest('[lang]');
    const lang = (langNode ? langNode.getAttribute('lang') : document.documentElement.lang || 'tr').toLowerCase();
    const turkish = lang === 'tr' || lang.startsWith('tr-');
    button.disabled = !listener || !voice || !turkish; note.hidden = false;
    if (!turkish) note.textContent = TEXT.wrongLanguage;
    else if (!voice) note.textContent = TEXT.noVoice;
    else if (voice.localService !== true) note.textContent = TEXT.localOnly;
    else note.hidden = true;
  });
}
function addStatus() {
  let node = document.getElementById('er-status'); if (node) return node;
  node = makeElement('p', 'sr-only'); node.id = 'er-status'; node.setAttribute('role', 'status');
  const chatStatus = document.getElementById('chat-status');
  if (chatStatus && chatStatus.parentNode) chatStatus.parentNode.insertBefore(node, chatStatus.nextSibling);
  else document.body.appendChild(node);
  return node;
}

export function mountEasyRead() {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  if (root.dataset.easyReadMounted === 'true') return;
  root.dataset.easyReadMounted = 'true';
  if (!document.head.querySelector('link[href="/css/easy_read.css"]')) {
    const link = document.createElement('link'); link.rel = 'stylesheet'; link.href = '/css/easy_read.css'; document.head.appendChild(link);
  }
  status = addStatus(); tip = makeTooltip();
  onLang(updateReadingOptions);
  try { preferences = parseEasyPrefs(window.localStorage.getItem(EASY_PREFS_KEY)); } catch (error) { preferences = { ...DEFAULT_EASY_PREFS }; }
  enabled = preferences.on;
  if (enabled) root.dataset.easyRead = 'on';
  const synth = window.speechSynthesis;
  if (synth && typeof window.SpeechSynthesisUtterance === 'function') {
    listener = createListener({
      synth, getVoice: () => chooseVoice(synth.getVoices()),
      onState: ({ state, index, total }) => updateListeningUI(state, index, total),
      onSentence: (item) => item ? highlightSentence(item) : clearHighlight(),
    });
    if (typeof synth.addEventListener === 'function') synth.addEventListener('voiceschanged', refreshAudio);
  }
  const form = document.getElementById('chat-form');
  if (form) form.addEventListener('submit', () => listener && listener.stop());
  document.addEventListener('visibilitychange', () => { if (document.hidden && listener && listener.state === 'speaking') listener.pause(); });
  document.addEventListener('focusin', (event) => {
    const button = event.target.closest && event.target.closest('.er-term');
    if (button) showTip(button);
  });
  document.addEventListener('focusout', (event) => {
    if (!event.relatedTarget || !event.relatedTarget.closest || !event.relatedTarget.closest('.er-term')) closeTip();
  });
  document.addEventListener('click', (event) => {
    const button = event.target.closest && event.target.closest('.er-term');
    if (button) showTip(button);
    else if (!event.target.closest || !event.target.closest('.er-tip')) closeTip();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && tip && !tip.hidden) { event.preventDefault(); closeTip(); return; }
    if (!event.altKey || !event.shiftKey || event.isComposing) return;
    if (event.code === 'KeyO') { event.preventDefault(); document.querySelector('.er-toggle')?.click(); }
    else if (event.code === 'KeyD') {
      event.preventDefault();
      const buttons = document.querySelectorAll('.er-listen:not(:disabled)');
      buttons[buttons.length - 1]?.click();
    }
  });
  const log = document.getElementById('chat-log');
  if (log) {
    log.querySelectorAll('li.chat-msg.is-assistant').forEach(markBubble);
    const observer = new MutationObserver((records) => records.forEach((record) => {
      if (record.type === 'attributes' && record.target.matches('li.chat-msg.is-assistant')) markBubble(record.target);
    }));
    observer.observe(log, { attributes: true, attributeFilter: ['aria-busy'], subtree: true });
  }
  if (enabled) loadGlossary().then(() => renderTargets());
  updateToggleButtons(); updateRateButtons(); refreshAudio();
}
if (typeof document !== 'undefined') mountEasyRead();
