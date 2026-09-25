/* The paired metro and bus card; route numbers keep the shared source and age stamp. */

import { get, MOCK } from './api.js';
import { LIFT_TR, errorCard, lineBadge, skeleton } from './cards.js';
import { esc, num, trName } from './format.js';
import { sourceLink, stamp } from './provenance.js';

const result = document.getElementById('compare-result');
const form = document.getElementById('compare-form');
const fromInput = document.getElementById('compare-from');
const toInput = document.getElementById('compare-to');
const needsInput = document.getElementById('compare-needs');

/* One whole minute, never "41,5 dk": a citizen reads a clock in minutes, and a decimal suggests a
 * precision the estimate does not have (the product's single-minute rule). */
function wholeMinutes(value) {
  return `${Math.round(Number(value))} dk`;
}

function foot(prov) {
  return `<p class="card-foot">${stamp(prov)}${sourceLink(prov)}</p>`;
}

function optionBody(option) {
  if (!option.available) {
    return `<p class="card-body">${esc(option.reason || 'Bu seçenek hesaplanamadı.')}</p>`;
  }
  const minutes = option.minutes !== null && option.minutes !== undefined && Number.isFinite(Number(option.minutes))
    ? wholeMinutes(option.minutes) : 'süre doğrulanamadı';
  const transfers = option.transfers !== null && option.transfers !== undefined && Number.isFinite(Number(option.transfers))
    ? `${num(option.transfers, 0)} aktarma`
    : 'aktarma bilgisi doğrulanamadı';
  let details = `<p class="card-metric"><span class="card-value">${esc(minutes)}</span>`
    + `<span class="card-unit">${esc(transfers)}</span></p>`;
  if (option.mode === 'metro') {
    const status = option.accessibility && option.accessibility.lift_status;
    details += `<p class="card-body">${esc((status && LIFT_TR[status]) || option.accessibility_note || LIFT_TR.unknown)}</p>`;
  }
  if (option.mode === 'bus') {
    const reliability = option.reliability;
    let note = option.reliability_note || 'Hat düzenliliği doğrulanamadı.';
    if (reliability && reliability.available) {
      const headway = reliability.median_headway_min !== null && reliability.median_headway_min !== undefined
        && Number.isFinite(Number(reliability.median_headway_min))
        ? `${wholeMinutes(reliability.median_headway_min)} ortanca sefer aralığı`
        : 'ortanca sefer aralığı bilinmiyor';
      note = `${headway}${reliability.bunching_label ? `, düzenlilik: ${reliability.bunching_label}` : ''}`;
    } else if (reliability && reliability.note) {
      note = reliability.note;
    }
    details += `<p class="card-body">${esc(note)}</p>`;
  }
  return details;
}

function optionCard(option, index) {
  const unavailable = !option.available;
  const warning = option.accessibility?.lift_status === 'out_of_service' || option.reliability?.available === false;
  const status = unavailable ? 'unverified' : warning ? 'warning' : 'ok';
  const title = option.mode === 'bus' && option.line_code
    ? `Otobüs ${lineBadge(option.line_code)}`
    : esc(option.label);
  return `<article class="card card-in is-${status}" style="--i:${index}" aria-label="${esc(option.label)} seçeneği">`
    + `<h3 class="card-title">${title}</h3>${optionBody(option)}${foot(option.provenance)}</article>`;
}

function render(data) {
  const options = (data.options || []).filter((option) => option.mode === 'metro' || option.mode === 'bus');
  result.innerHTML = `<p class="compare-route"><b>${esc(trName(data.from))}</b> ${esc('→')} <b>${esc(trName(data.to))}</b></p>`
    + `<div class="compare-options">${options.map(optionCard).join('')}</div>`
    + `<p class="field-hint">${esc(data.disclaimer || '')}</p>`;
}

async function load(params) {
  result.innerHTML = skeleton(2);
  try {
    render(await get('/api/compare', params));
  } catch (error) {
    result.innerHTML = errorCard('Karşılaştırma alınamadı', error.message);
  }
}

if (form && result) {
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const params = { from: fromInput.value.trim(), to: toInput.value.trim() };
    if (needsInput && needsInput.value.trim()) params.needs = needsInput.value.trim();
    void load(params);
  });
  if (MOCK) void load();
}
