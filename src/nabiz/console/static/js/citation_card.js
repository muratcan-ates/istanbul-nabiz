import { esc, has, shortAge } from './format.js';
import { ageText, modeOf, sourceLabel } from './provenance.js';
import { currentLang, t } from './i18n_text.js';

const STALE_DAYS = 365;
const DAY_MS = 24 * 60 * 60 * 1000;
const INSTITUTIONS = {
  IBB: 'İBB',
  IBB_OPEN_DATA: 'İBB Açık Veri Portalı',
  IETT: 'İETT',
  IGDAS: 'İGDAŞ',
  ISKI: 'İSKİ',
  ISPARK: 'İSPARK',
  METRO_ISTANBUL: 'Metro İstanbul',
  SEHIR_HATLARI: 'Şehir Hatları',
};

function institutionLabel(code, url, institutions = INSTITUTIONS) {
  if (has(code) && code !== 'DIGER') return institutions[code] || String(code);
  try {
    return new URL(url).hostname || 'Kurum belirtilmemiş';
  } catch {
    return 'Kurum belirtilmemiş';
  }
}

function dayDate(iso) {
  const timestamp = Date.parse(iso || '');
  if (!Number.isFinite(timestamp)) return null;
  try {
    return new Intl.DateTimeFormat('tr-TR', {
      timeZone: 'Europe/Istanbul', day: '2-digit', month: '2-digit', year: 'numeric',
    }).format(timestamp);
  } catch {
    return null;
  }
}

function freshnessMode(citation) {
  const mode = modeOf(citation);
  return mode === 'unknown' && citation && citation.mode === 'old' ? 'old' : mode;
}

function kindView(citation, { beat = false, lang = 'tr', compact = false } = {}) {
  if (citation && citation.source === 'local:knowledge') return node('span', { class: 'ac-kind is-page' }, 'Resmî sayfadan alıntı');
  const mode = freshnessMode(citation);
  let label = 'Veri yaşı bilinmiyor';
  if (mode === 'live') label = `Canlı veri · ${shortAge(citation.age_s)}`;
  if (mode === 'old') label = `Ölçüm · ${ageText(citation)}`;
  if (mode === 'recorded') label = `Kayıtlı veri · ${ageText(citation)}`;
  if (mode === 'schedule') label = 'Tarifeye göre';
  if (compact && mode !== 'live') {
    const key = { old: 'measured', recorded: 'recorded', schedule: 'schedule', unknown: 'unknown_age' }[mode];
    const rawAge = ['old', 'recorded'].includes(mode) ? ageText(citation) : '';
    const englishAge = rawAge === 'veri yaşı bilinmiyor' ? citationText('unknown_age', 'en').toLowerCase()
      : rawAge.split(/(\s+)/).map((word) => ({ sn: 's', dk: 'min', sa: 'h', gün: 'd', önce: 'ago' })[word] || word).join('');
    const age = lang === 'en' ? englishAge : rawAge;
    label = `${citationText(key, lang)}${age ? ` ${age}` : ''}`;
  }
  const state = mode === 'live' ? 'current' : ['recorded', 'old', 'schedule'].includes(mode) ? 'recorded' : 'unverified';
  const dot = mode === 'live' ? [node('span', { class: 'fresh-dot', 'aria-hidden': 'true' })] : [];
  return node('span', { class: `ac-kind fresh is-${state}${beat && mode === 'live' ? ' is-beat' : ''}` }, ...dot, label);
}
function kindTag(citation, options) { return markup(kindView(citation, options)); }

function isStale(citation, now = Date.now()) {
  if (!citation || citation.source !== 'local:knowledge') return false;
  const updated = Date.parse(citation.source_updated_at || '');
  const current = now instanceof Date ? now.getTime() : Number(now);
  return Number.isFinite(updated) && Number.isFinite(current) && current - updated > STALE_DAYS * DAY_MS;
}

const COPY = {
  open: ['Kaynağı aç', 'Open source'], open_name: ['kaynağını aç', 'open source'],
  quote_above: ['Alıntı yukarıda', 'Quote above'], quote_source: ['Alıntının kaynağı', 'Source of quote'],
  more: ['Diğer kaynaklar ({count})', 'Other sources ({count})'], source: ['Kaynak {number}', 'Source {number}'],
  no_source: ['Bu cümle için kaynak henüz yok', 'No source yet for this sentence'],
  conflict: ["İki kaynak farklı değer veriyor; hangisinin geçerli olduğu doğrulanmadı. 153'e sorun.",
    'Two sources give different values; which one applies has not been verified. Ask 153.'],
  no_date: ['Sayfa tarih vermiyor', 'The page gives no date'], page: ['Kaynak sayfası', 'Source page'],
  institution: ['Kurum belirtilmemiş', 'Institution not specified'], recorded: ['Kayıtlı veri', 'Recorded data'],
  unknown_age: ['Veri yaşı bilinmiyor', 'Source age unknown'], updated: ['son güncelleme: {date}', 'last updated: {date}'],
  stale: ['Eski olabilir, 153 ile teyit edin', 'May be outdated; confirm with 153'],
  measured: ['Ölçüm', 'Measurement'], schedule: ['Tarifeye göre', 'Based on the timetable'],
  page_quote: ['Resmî sayfadan alıntı', 'Quoted from the official page'],
};
export function citationText(key, lang = currentLang(), vars = {}) {
  const fallback = COPY[key]?.[lang === 'en' ? 1 : 0] || '';
  return lang === currentLang() ? t(`ui.citation.${key}`, fallback, vars)
    : fallback.replace(/\{(\w+)\}/g, (_, name) => String(vars[name] ?? `{${name}}`));
}
// One inert element tree feeds the DOM API and the existing string-rendering contract.
function node(tag, attrs = {}, ...children) { return { tag, attrs, children }; }
function markup(view) {
  if (typeof view === 'string') return esc(view);
  const attrs = Object.entries(view.attrs).map(([key, value]) => ` ${key}="${esc(value)}"`).join('');
  return `<${view.tag}${attrs}>${view.children.map(markup).join('')}</${view.tag}>`;
}
function dom(view, doc, svg = false) {
  const isSvg = svg || view.tag === 'svg';
  const element = isSvg ? doc.createElementNS('http://www.w3.org/2000/svg', view.tag) : doc.createElement(view.tag);
  for (const [key, value] of Object.entries(view.attrs)) element.setAttribute(key, value);
  if (view.children.every((child) => typeof child === 'string')) element.textContent = view.children.join('');
  else for (const child of view.children) element.append(typeof child === 'string' ? doc.createTextNode(child) : dom(child, doc, isSvg));
  return element;
}
function citationView(item, { index = 0, now = Date.now(), lang = currentLang(), answerId = 0, quoteTarget = '', beat = false, institutions = INSTITUTIONS } = {}) {
  const citation = item && typeof item === 'object' ? item : {};
  const id = `ac-cite-${Number.isSafeInteger(answerId) ? answerId : 0}-${Number.isSafeInteger(index) ? index + 1 : 1}`;
  let institution = institutionLabel(citation.institution, citation.url, institutions);
  if (institution === 'Kurum belirtilmemiş') institution = citationText('institution', lang);
  const title = String(citation.title || (citation.source !== 'local:knowledge' && sourceLabel(citation.source)) || citationText('page', lang));
  const updated = dayDate(citation.source_updated_at);
  const updateText = updated ? citationText('updated', lang, { date: updated }) : '';
  const sourceLine = institution;
  const head = node('header', { class: 'citation-heading' },
    node('svg', { class: 'icon', 'aria-hidden': 'true' }, node('use', { href: '/icons.svg#i-list-details' })),
    node('div', {}, node('p', { class: 'ac-source-line' }, sourceLine), node('h4', { id: `${id}-title` }, title)));
  const children = [head];
  if (updated) children.push(node('time', { class: 'citation-date', datetime: citation.source_updated_at,
    'aria-label': `${institution} · ${updateText}` }, updateText));
  if (citation.source === 'local:knowledge') {
    const date = Date.parse(citation.fetched_at || '');
    const age = Number.isFinite(date) ? `${citationText('recorded', lang)} ${ageText({ mode: 'recorded', observed_at: citation.fetched_at })}` : citationText('unknown_age', lang);
    children.push(node('span', { class: 'sr-only' }, citationText('page_quote', lang)), node('span', { class: `ac-kind fresh ${Number.isFinite(date) ? 'is-recorded' : 'is-unverified'}` }, age));
    if (!updated) children.push(node('p', { class: 'citation-date' }, citationText('no_date', lang)));
  } else children.push(kindView(citation, { beat, lang, compact: true }));
  if (isStale(citation, now)) children.push(node('p', { class: 'ac-stale callout callout-warn' }, citationText('stale', lang)));
  if (/^ac-quote-\d+-\d+$/.test(quoteTarget)) {
    children.push(node('a', { class: 'citation-quote-link', href: `#${quoteTarget}` }, citationText('quote_above', lang)));
  } else if (typeof citation.quote === 'string' && citation.quote.length) {
    children.push(node('blockquote', { class: 'quote-text quote-exact', 'data-er-skip': '' }, citation.quote));
  }
  try {
    const url = new URL(citation.url);
    if (/^https:\/\//i.test(citation.url) && url.protocol === 'https:' && !url.username && !url.password) {
      children.push(node('span', { id: `${id}-institution`, hidden: '' }, `${institution},`),
        node('span', { id: `${id}-open`, hidden: '' }, citationText('open_name', lang)),
        node('a', { class: 'btn btn-quiet citation-open', href: url.href, target: '_blank', rel: 'noopener noreferrer',
          'aria-labelledby': `${id}-institution ${id}-title ${id}-open` }, citationText('open', lang)));
    }
  } catch { /* An absent or unsafe URL is not an action. */ }
  return node('article', { class: 'citation-card', id, tabindex: '-1' }, ...children);
}
export function citationCard(item, options = {}) { return dom(citationView(item, options), document); }
export function citationMarkup(item, options = {}) {
  return typeof document !== 'undefined' && document.createElement ? citationCard(item, options).outerHTML : markup(citationView(item, options));
}
export { kindTag, isStale, institutionLabel, dayDate, STALE_DAYS, freshnessMode };
