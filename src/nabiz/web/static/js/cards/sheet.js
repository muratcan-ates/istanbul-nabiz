/* The parts every answer shares (spec 8.1): a head with the answer's stamp and the server's note,
 * one raised sheet of rows separated by hairlines, callouts, disclosures and the error card.
 * Pure: strings in, strings out, and every string from the API goes through esc(). */

import { UNKNOWN, esc, has, shortAge, CONFIDENCE_TR } from '../format.js';
import { icon } from '../icons.js';
import { stamp, stampText, sourceLink, sourceLabel } from '../provenance.js';

let seq = 0;
/** The id a map marker and a "Haritada göster" button point at. */
function nextCardId() {
  seq += 1;
  return `kart-${seq}`;
}

function callout(text, { tone = '', icon: glyph = 'info-circle', title = '', html = '' } = {}) {
  return `<div class="callout${tone ? ` callout-${tone}` : ''}">${icon(glyph)}<div>`
    + `${title ? `<p class="callout-title">${esc(title)}</p>` : ''}${text ? `<p>${esc(text)}</p>` : ''}${html}</div></div>`;
}

/** Nothing matched: the server's own sentence and, where there is one, what to try instead. */
const empty = (text) => callout(text, { icon: 'search-off' });

/**
 * The answer's head: h2 with a count of the rows below it (the one number without a stamp), the
 * answer's stamp, and the server's note as a callout. `id` makes it a marker's target, as the
 * searched place or an arrivals stop has no row of its own. `source` adds the source link, for
 * answers whose rows are table rows without a foot.
 */
function head({ id, title, titleHtml, count, prov, extra, note, source }) {
  return `<header class="sheet-head sheet-in"${id ? ` id="${esc(id)}" tabindex="-1"` : ''}>`
    + `<h2 class="sheet-title">${titleHtml || esc(title)}${has(count) ? ` <span class="sheet-count">${esc(count)}</span>` : ''}</h2>`
    + `<p class="row-foot">${stamp(prov, extra)}${source ? sourceLink(prov) : ''}</p>`
    + (prov && prov.stale
      ? callout('İBB servisine ulaşılamadı; önbellekteki son değer gösteriliyor.', { tone: 'warn', icon: 'clock-exclamation' }) : '')
    + (note ? callout(note) : '')
    + '</header>';
}

/** One raised surface; rows inside it are separated by hairlines only (one elevation). */
const sheet = (rows) => `<div class="sheet">${rows}</div>`;

/** A map point: the id of its row, and the value and age its popup and the location list say. */
function point(place, kind, card, label, prov, glyph) {
  return { lat: place && place.lat, lon: place && place.lon, kind, card, label, age: stampText(prov), icon: glyph };
}

/**
 * One row: kind icon, title, "Haritada göster" when it has a place, then the caller's metric,
 * drawing and facts, and the stamp with the source link. `i` staggers the entry (motion 8).
 */
function row({ id, kind, glyph, title, titleHtml, sub, body, prov, extra, map, i = 0 }) {
  const button = map
    ? `<button type="button" class="btn row-map" data-map="${esc(id)}">${icon('map')}<span class="row-map-word">Haritada göster</span></button>`
    : '';
  return `<article class="card row sheet-in" id="${esc(id)}" tabindex="-1" data-kind="${esc(kind || 'place')}" style="--i:${Math.min(i, 5) + 1}">`
    + `${icon(glyph || 'map-pin', 'row-kind')}<div class="row-head"><h3>${titleHtml || esc(title)}</h3>${button}</div>`
    + `${sub ? `<p class="row-sub">${esc(sub)}</p>` : ''}${body || ''}`
    + `<footer class="row-foot">${stamp(prov, extra)}${sourceLink(prov)}</footer></article>`;
}

/** The row's one number at 28/700 with its unit; a missing value is the word, at body size.
 * `noteHtml`, the secondary fact beside it, is already escaped by the caller; `what` names the
 * value when it is missing ("süre bilinmiyor"). */
function metric(value, unit, noteHtml, what = unit) {
  const shown = has(value) && value !== UNKNOWN
    ? `<span class="row-value">${esc(value)}</span> <span class="row-unit">${esc(unit)}</span>`
    : `<span class="row-unit">${esc(what)} ${UNKNOWN}</span>`;
  return `<p class="row-metric"><span>${shown}</span>${noteHtml ? `<span>${noteHtml}</span>` : ''}</p>`;
}

/** Facts as one comma-separated line: no middle dots, no pills. */
function facts(items) {
  const kept = items.filter(Boolean);
  return kept.length ? `<p class="row-facts">${esc(kept.join(', '))}</p>` : '';
}

function details(summary, html) {
  return `<details><summary>${icon('chevron-right')}${esc(summary)}</summary>${html}</details>`;
}

/** A real table: [label, numeric] headers, rows already built with esc(). */
function table(headers, body) {
  const cols = headers.map(([label, numeric]) => `<th scope="col"${numeric ? ' class="num"' : ''}>${esc(label)}</th>`).join('');
  return `<div class="sheet-table"><table><thead><tr>${cols}</tr></thead>${body}</table></div>`;
}

const disclaimer = (text) => (text ? `<p class="sheet-disclaimer">${esc(text)}</p>` : '');

/* Confidence is an icon and a word, never a colour alone. */
const CONFIDENCE_ICONS = { high: 'antenna-bars-5', medium: 'antenna-bars-3', low: 'antenna-bars-1' };

function confidence(key) {
  return CONFIDENCE_ICONS[key] ? `${icon(CONFIDENCE_ICONS[key])} ${CONFIDENCE_TR[key]}` : esc(key || UNKNOWN);
}

const ERROR_TITLES = {
  0: 'Sunucuya ulaşılamadı',
  400: 'Bu soruyu yanıtlayamadım',
  404: 'Bu özellik bu sunucuda henüz yok',
  422: 'İstek eksik ya da hatalı',
  429: 'Kendi istek bütçemiz doldu',
  503: 'İBB servisi şu anda yanıt vermiyor',
};
const ERROR_ICONS = { 0: 'wifi-off', 503: 'cloud-off' };

/**
 * A failure is an answer. When İBB or the network is the one failing, it says how old the last
 * thing we knew is (from /api/freshness), because "bilmiyorum" and "17 saniye önce biliyordum"
 * are different answers. A question the server refused (400, 422) gets no retry: it would fail
 * the same way.
 */
const errorTitle = (err) => ERROR_TITLES[err.status || 0] || 'Beklenmeyen bir hata';

function errorCard(err, sources) {
  const status = err.status || 0;
  const title = errorTitle(err);
  // The server's message often opens with the same sentence as our heading; twice reads as a stutter.
  let detail = err.message || 'Bilinmeyen hata.';
  if (detail.startsWith(title)) detail = detail.slice(title.length).replace(/^[\s:.,;-]+/, '') || detail;
  const known = Object.entries(sources || {}).map(([name, s]) => `<tr><td>${esc(sourceLabel(name))}</td>`
    + `<td>${Number.isFinite(s.age_seconds) ? `${shortAge(s.age_seconds)} önce` : 'hiç alınamadı'}</td></tr>`).join('');
  return `<div class="callout callout-error sheet-in">${icon(ERROR_ICONS[status] || 'alert-triangle')}<div>`
    + `<h2 class="callout-title">${esc(title)}</h2><p>${esc(detail)}</p>`
    + (status === 503 ? '<p>Bu bir Nabız hatası değil: üst kaynak (İBB) yanıt vermedi. Sayı uydurmak yerine boş bırakıyoruz.</p>' : '')
    + (known ? `<h3>En son ne zaman veri alabildik</h3>${table([['Kaynak'], ['Son okuma']], `<tbody>${known}</tbody>`)}` : '')
    + (status === 400 || status === 422 ? '' : '<p><button type="button" class="btn" data-retry>Tekrar dene</button></p>')
    + '</div></div>';
}

export {
  nextCardId, callout, empty, head, sheet, point, row, metric, facts, details, table, disclaimer, confidence, errorTitle, errorCard,
};
