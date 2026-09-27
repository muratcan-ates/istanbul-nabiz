/* Self-mount the visitor section only when the page language is English. */

import { MOCK, get } from './api.js';
import { currentLang, onLang, t } from './i18n_text.js';
import { esc } from './format.js';
import { FALLBACK, cardPreview, sectionMarkup, venuesMarkup } from './visitor_view.js';

export const ANCHORS = Object.freeze([['#city-cards', 'beforebegin'], ['#asistan', 'afterend']]);
export const STYLESHEET = '/css/visitor.css';
export const SECTION_ID = 'ziyaretci';

let visitorPayloadRequest = null;
const visitorDocuments = new WeakSet();

function visitorAnchor(doc) {
  for (const [selector, position] of ANCHORS) {
    const target = doc.querySelector(selector);
    if (target) return { target, position };
  }
  return null;
}

function visitorStyles(doc) {
  if (doc.querySelector(`link[href="${STYLESHEET}"]`)) return;
  const link = doc.createElement('link');
  link.rel = 'stylesheet';
  link.href = STYLESHEET;
  doc.head.append(link);
}

function visitorSection(doc) {
  return doc.getElementById(SECTION_ID);
}

function visitorRemove(doc) {
  const section = visitorSection(doc);
  if (!section) return;
  if (section.contains(doc.activeElement)) doc.getElementById('main')?.focus();
  section.remove();
}

function visitorPayloadOnce() {
  if (!visitorPayloadRequest) visitorPayloadRequest = get('/api/visitor').catch(() => FALLBACK);
  return visitorPayloadRequest;
}

function visitorEvents(section) {
  let museumRequest = 0;
  section.addEventListener('change', async (event) => {
    if (event.target.matches('#visitor-card-lang')) {
      section.querySelector('.visitor-card-preview').innerHTML = cardPreview(event.target.value);
      return;
    }
    if (!event.target.matches('#visitor-district')) return;
    const district = event.target.value;
    const status = section.querySelector('.status-line');
    const list = section.querySelector('.visitor-venues');
    const mine = ++museumRequest;
    list.hidden = true;
    list.innerHTML = '';
    status.setAttribute('lang', currentLang());
    if (!district) { status.textContent = ''; return; }
    status.textContent = t('ui.culture.loading', 'Kayıtlar yükleniyor.');
    try {
      const data = await get('/api/culture', { district, kinds: 'museum' });
      if (mine !== museumRequest || !section.isConnected) return;
      const venues = Array.isArray(data.venues) ? data.venues : [];
      list.innerHTML = venuesMarkup(data);
      list.hidden = venues.length === 0;
      const counts = data.counts || { total: venues.length, open: venues.filter((venue) => venue.state === 'open').length };
      status.textContent = t('ui.culture.count', '{district}: {total} kayıt; kayda göre şu an açık: {open}.', {
        district, total: counts.total, open: counts.open,
      });
    } catch {
      if (mine !== museumRequest || !section.isConnected) return;
      status.textContent = t('ui.visitor.museums_failed', 'Müze kayıtları şu an alınamadı. Biraz sonra yeniden deneyin.');
    }
  });
  section.addEventListener('click', (event) => {
    const button = event.target.closest('[data-visitor="grow"]');
    if (!button) return;
    const plea = section.querySelector('#visitor-plea');
    const large = button.getAttribute('aria-pressed') !== 'true';
    plea.classList.toggle('is-large', large);
    button.setAttribute('aria-pressed', String(large));
  });
}

function visitorDraw(doc, payload, language) {
  if (language !== 'en' || currentLang() !== 'en') { visitorRemove(doc); return null; }
  const anchor = visitorAnchor(doc);
  if (!anchor) return null;
  const current = visitorSection(doc);
  if (current) current.remove();
  anchor.target.insertAdjacentHTML(anchor.position, sectionMarkup(payload));
  const section = visitorSection(doc);
  if (section) visitorEvents(section);
  return section;
}

function visitorLanguage(doc, language) {
  if (language !== 'en') { visitorRemove(doc); return Promise.resolve(null); }
  visitorStyles(doc);
  if (visitorSection(doc)) return Promise.resolve(visitorSection(doc));
  if (!visitorAnchor(doc)) return Promise.resolve(null);
  return visitorPayloadOnce().then((payload) => visitorDraw(doc, payload, language));
}

export function mountVisitor(doc) {
  if (MOCK || !doc || !visitorAnchor(doc)) return null;
  if (!visitorDocuments.has(doc)) {
    visitorDocuments.add(doc);
    onLang((language) => { void visitorLanguage(doc, language); });
  }
  if (currentLang() !== 'en') return null;
  return visitorLanguage(doc, 'en');
}

if (typeof document !== 'undefined') mountVisitor(document);
