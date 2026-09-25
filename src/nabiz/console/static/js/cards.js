/* The citizen cards: city cards from /api/brief, the one-minute arrival, the step-free alternative.
 * Every card carries the source, its age and who wrote the answer; a missing value is a word, never an
 * invented number. Pure (no DOM): the entry script writes the strings. */

import { UNKNOWN, esc, has, trName } from './format.js';
import { icon } from './icons.js';
import { AUTHOR_TR, MODE_ICON, MODE_TR, ageSentence, ageStamp, howPanel, modeOf, sourceLink, stamp } from './provenance.js';

const KIND_ICON = {
  metro_equipment: 'elevator', metro_status: 'train', arrival: 'bus', traffic: 'traffic-lights', air: 'wind',
  parking: 'parking', alternative: 'route',
};
const STATUS_TR = { ok: 'güncel', warning: 'dikkat', stale: 'bayat veri', unverified: 'doğrulanamadı' };
const STATUS_ICON = { ok: 'circle-check', warning: 'alert-triangle', stale: 'history', unverified: 'clock-question' };
const LIFT_TR = {
  working: 'İBB kaydında arıza yok',
  out_of_service: 'asansör arızalı (İBB kaydı)',
  unknown: 'asansör durumu doğrulanamadı',
};
const LIFT_STATUS = { working: 'ok', out_of_service: 'warning', unknown: 'unverified' };
const METRO_LINE = /^(?:M\d+[AB]?|T\d|TF\d|F\d)$/;

function statusOf(value) {
  return STATUS_TR[value] ? value : 'unverified';
}

function authorLine(author) {
  return `<span class="card-author">cevabı yazan: ${esc(AUTHOR_TR[author] || author || UNKNOWN)}</span>`;
}

/** A line badge in the operator's colour token; anything else (a bus line) in the bus badge. */
function lineBadge(code) {
  const c = String(code || '').toLocaleUpperCase('tr');
  if (METRO_LINE.test(c)) {
    return `<span class="badge" style="--line:var(--line-${c});--line-ink:var(--line-${c}-ink)">${esc(c)}</span>`;
  }
  return `<span class="badge badge-bus">${esc(c || UNKNOWN)}</span>`;
}

function statusLine(status) {
  return `<p class="card-status">${icon(STATUS_ICON[status])}<span>${STATUS_TR[status]}</span></p>`;
}

function foot(prov, author) {
  return `<p class="card-foot">${stamp(prov)}${sourceLink(prov)}${author ? authorLine(author) : ''}</p>`;
}

/** One city card, the shape of a weather card: title, one sentence, status, source and age. */
function cityCard(card, i) {
  const status = statusOf(card.status);
  const id = esc(card.id || `card-${i}`);
  return `<article class="card card-in is-${status}" style="--i:${Number(i) || 0}" id="card-${id}" aria-labelledby="card-${id}-t">`
    + `<span class="card-kind">${icon(KIND_ICON[card.kind] || 'info-circle')}</span>`
    + `<h3 class="card-title" id="card-${id}-t">${esc(card.title)}</h3>`
    + `<p class="card-body">${esc(card.body)}</p>`
    + statusLine(status)
    + foot(card.provenance, card.author)
    + howPanel(card.how, id)
    + '</article>';
}

/** The one-minute rule: the server phrases `display` ("7 dk", "1 dk", "tarifeye göre", "doğrulanamadı")
 * and the page never rounds. The fallback only covers a reply without `display`. */
function arrivalDisplay(data) {
  if (data.display) return String(data.display);
  if (!has(data.minutes) || !Number.isFinite(Number(data.minutes))) return 'doğrulanamadı';
  return `${Math.max(1, Number(data.minutes))} dk`;
}

function arrivalCard(data) {
  const display = arrivalDisplay(data);
  const isWord = !/^\d+ dk$/.test(display);
  const mode = modeOf(data.provenance);
  const status = display === 'doğrulanamadı' ? 'unverified' : mode === 'unknown' || mode === 'old' ? 'stale' : 'ok';
  // "tarifeye göre" is both the value and the mode's word: say it once, keep the icon.
  const unit = MODE_TR[mode] === display ? icon(MODE_ICON[mode]) : `${icon(MODE_ICON[mode])} ${MODE_TR[mode]}`;
  return `<article class="card card-in is-${status}" id="arrival-card" aria-labelledby="arrival-t">`
    + `<span class="card-kind">${icon('bus')}</span>`
    + `<h3 class="card-title" id="arrival-t">${lineBadge(data.line)}<span class="sr-only"> hattı, durak:</span> `
    + `${icon('arrow-narrow-right')} <span>${esc(trName(data.stop))}</span></h3>`
    + '<p class="card-body">Tahmini varış</p>'
    + `<p class="card-metric"><span class="card-value${isWord ? ' is-word' : ''}">${esc(display)}</span>`
    + `<span class="card-unit">${unit}</span></p>`
    + `<p class="card-foot">${ageStamp(data.provenance)}${sourceLink(data.provenance)}${authorLine('kural')}</p>`
    + '</article>';
}

/** Step-free alternative. The lift line never says "çalışıyor": the best it says is "arıza kaydı yok". */
function alternativeCard(data) {
  const lift = LIFT_TR[data.lift_status] ? data.lift_status : 'unknown';
  const alt = data.alternative;
  // A record served stale is the last known state, said as such, never a current one.
  const known = data.stale ? 'son bilinen durum: ' : '';
  let body = `<p class="card-body"><b>${esc(trName(data.station))}</b>: ${known}${LIFT_TR[lift]}.</p>`;
  let status = data.stale ? 'stale' : LIFT_STATUS[lift];
  if (alt) {
    const extra = has(alt.extra_minutes)
      ? `istasyonlar arası tahminen ${Number(alt.extra_minutes)} dk (dönüş dahil değil)`
      : 'süre bilinmiyor';
    const approval = data.operator_approved
      ? `<span class="tag is-ok">${icon('circle-check')}Operatör onaylı (simüle)</span>`
      : `<span class="tag is-warn">${icon('clock-question')}Operatör onayı yok</span>`;
    body += `<p class="card-metric"><span class="card-value is-word">Adımsız alternatif: ${esc(trName(alt.station))}</span>`
      + `${lineBadge(alt.line)}<span class="card-unit">${esc(extra)}</span></p>`
      + `<p class="card-body">${esc(alt.reason || '')}</p><p>${approval}</p>`;
  } else if (lift === 'out_of_service') {
    body += '<p class="card-body">İBB kaydında asansör arızası görünmeyen yakın bir istasyon bulunamadı. '
      + '<a href="tel:153">153</a> ile teyit edin.</p>';
    status = data.stale ? 'stale' : 'warning';
  }
  return `<article class="card card-in is-${status}" id="alternative-card" aria-labelledby="alternative-t">`
    + `<span class="card-kind">${icon('elevator')}</span>`
    + '<h3 class="card-title" id="alternative-t">Asansör ve adımsız yol</h3>'
    + body
    + statusLine(status)
    + foot(data.provenance, data.operator_approved ? 'kural, simüle operatör onayladı' : 'kural')
    + '</article>';
}

function errorCard(title, message) {
  return `<div class="callout callout-error" role="alert">${icon('alert-triangle')}<div>`
    + `<p class="callout-title">${esc(title)}</p><p>${esc(message)}</p></div></div>`;
}

function skeleton(n) {
  const one = '<div class="skeleton" aria-hidden="true"><div class="skeleton-line"></div><div class="skeleton-line"></div>'
    + '<div class="skeleton-line"></div></div>';
  return new Array(Math.max(1, n)).fill(one).join('');
}

/** One sentence for the status region after the cards render. */
function cardsSentence(cards) {
  if (!cards || !cards.length) return 'Gösterilecek şehir kartı yok.';
  const ages = cards.map((c) => c.provenance && c.provenance.age_s).filter(Number.isFinite);
  const newest = ages.length ? Math.min(...ages) : null;
  const provNewest = cards.find((c) => c.provenance && c.provenance.age_s === newest);
  const stale = cards.filter((c) => c.status === 'stale').length;
  const unverified = cards.filter((c) => c.status === 'unverified').length;
  const caveats = [stale ? `${stale} kart bayat veri, son bilinen durum` : '', unverified ? `${unverified} kart doğrulanamadı` : '']
    .filter(Boolean).join('; ');
  return `${cards.length} şehir kartı gösteriliyor${caveats ? ` (${caveats})` : ''}. `
    + `${provNewest ? ageSentence(provNewest.provenance) : 'Veri yaşı bilinmiyor.'}`;
}

export { KIND_ICON, STATUS_TR, LIFT_TR, lineBadge, cityCard, arrivalDisplay, arrivalCard, alternativeCard, errorCard, skeleton, cardsSentence };
