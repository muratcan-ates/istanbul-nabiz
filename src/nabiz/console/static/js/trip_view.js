/* Pure rendering and URL helpers for the citizen's trip card. */

import { LIFT_TR } from './cards.js';
import { ageText, sourceLink, stamp } from './provenance.js';
import { esc, num, trName } from './format.js';
import { icon } from './icons.js';

const COMPARE_READS = ['from', 'to', 'options', 'disclaimer'];
const OPTION_READS = ['mode', 'label', 'available', 'minutes', 'transfers', 'line_code', 'accessibility', 'accessibility_note', 'reliability', 'reliability_note', 'provenance', 'reason'];
const JOURNEY_READS = ['available', 'from', 'to', 'steps', 'extra_minutes', 'alternative_used', 'alternatives_used', 'provenance', 'uncertainty', 'disclaimer', 'reason'];
const STEP_READS = ['kind', 'description', 'minutes', 'map_links', 'line', 'from_station', 'to_station', 'lift_status', 'stations', 'at_station', 'note'];
const DETOUR_READS = ['station', 'line', 'avoided_station', 'reason'];
const ALTERNATIVE_READS = ['station', 'lift_status', 'provenance', 'text'];

function wantsStepFree(needs) {
  return Array.isArray(needs) && (needs.includes('step_free') || needs.includes('stroller'));
}

function sectionOrder(needs) {
  return wantsStepFree(needs) ? ['stepfree', 'compare'] : ['compare', 'stepfree'];
}

function transferText(option) {
  if (option.transfers === null || option.transfers === undefined || !Number.isFinite(Number(option.transfers))) {
    return 'aktarma bilgisi doğrulanamadı';
  }
  const count = Number(option.transfers);
  return count === 0 ? 'aktarmasız' : `${num(count, 0)} aktarma`;
}

function minutesText(option) {
  if (option.minutes !== null && option.minutes !== undefined && Number.isFinite(Number(option.minutes))) {
    return `${num(option.minutes, 0)} dk`;
  }
  return option.reason || 'süre doğrulanamadı';
}

function reliabilityText(option) {
  const reliability = option.reliability;
  let note = option.reliability_note || 'Hat düzenliliği doğrulanamadı.';
  if (reliability && reliability.available) {
    const headway = reliability.median_headway_min !== null && reliability.median_headway_min !== undefined
      && Number.isFinite(Number(reliability.median_headway_min))
      ? `${num(reliability.median_headway_min, 0)} dk ortanca sefer aralığı`
      : 'ortanca sefer aralığı bilinmiyor';
    note = `${headway}${reliability.bunching_label ? `, düzenlilik: ${reliability.bunching_label}` : ''}`;
  } else if (reliability && reliability.note) {
    note = reliability.note;
  }
  return note;
}

function optionDetails(option) {
  const minutes = minutesText(option);
  const transfer = transferText(option);
  let details = `<p class="trip-metric"><b>${esc(minutes)}</b><span>${esc(transfer)}</span></p>`;
  if (option.mode === 'metro') {
    const status = option.accessibility && option.accessibility.lift_status;
    details += `<p class="trip-detail">${esc((status && LIFT_TR[status]) || option.accessibility_note || LIFT_TR.unknown)}</p>`;
  }
  if (option.mode === 'bus') details += `<p class="trip-detail">${esc(reliabilityText(option))}</p>`;
  return details;
}

function optionCard(option, shorter) {
  const title = option.mode === 'bus' && option.line_code
    ? `Otobüs ${esc(option.line_code)}` : esc(option.label || 'Metro / raylı sistem');
  const unavailable = !option.available;
  const body = unavailable
    ? `<p class="trip-detail">${esc(option.reason || 'Bu seçenek hesaplanamadı.')}</p>`
    : optionDetails(option);
  const tag = shorter ? '<span class="tag is-info">daha kısa</span>' : '';
  return `<section class="trip-option${unavailable ? ' is-unavailable' : ''}" data-mode="${esc(option.mode)}" aria-label="${title} seçeneği">`
    + `<h4>${title}${tag}</h4>${body}<p class="card-foot">${stamp(option.provenance)}${sourceLink(option.provenance)}</p></section>`;
}

function comparisonRow(compare) {
  const options = Array.isArray(compare.options)
    ? compare.options.filter((option) => option.mode === 'metro' || option.mode === 'bus') : [];
  const metro = options.find((option) => option.mode === 'metro');
  const bus = options.find((option) => option.mode === 'bus');
  const metroMinutes = metro && metro.available && metro.minutes !== null && metro.minutes !== undefined
    && Number.isFinite(Number(metro.minutes)) ? Number(metro.minutes) : null;
  const busMinutes = bus && bus.available && bus.minutes !== null && bus.minutes !== undefined
    && Number.isFinite(Number(bus.minutes)) ? Number(bus.minutes) : null;
  const metroShorter = metroMinutes !== null && busMinutes !== null && metroMinutes < busMinutes;
  const busShorter = metroMinutes !== null && busMinutes !== null && busMinutes < metroMinutes;
  return '<div class="trip-compare" aria-label="Metro ve otobüs karşılaştırması">'
    + options.map((option) => optionCard(option, option.mode === 'metro' ? metroShorter : busShorter)).join('')
    + '</div>'
    + (compare.disclaimer ? `<p class="field-hint">${esc(compare.disclaimer)}</p>` : '');
}

function avoidedText(entry, fallbackProv) {
  if (!entry) return 'asansör kaydı okunuyor';
  const provenance = entry.provenance || fallbackProv;
  const age = provenance ? ageText(provenance) : '';
  if (entry.lift_status === 'out_of_service') {
    return `asansör kaydında arıza · ${age || 'veri yaşı bilinmiyor'}`;
  }
  if (typeof entry.text === 'string' && entry.text.trim()) {
    return `kayıt: ${entry.text}${age ? ` · ${age}` : ''}`;
  }
  return `${LIFT_TR.unknown}${age ? ` · ${age}` : ''}`;
}

function coordsFromLinks(links) {
  if (!links || typeof links !== 'object') return null;
  for (const service of ['apple', 'google']) {
    const value = links[service];
    if (typeof value !== 'string') continue;
    try {
      const url = new URL(value);
      if (url.protocol !== 'https:') continue;
      if (service === 'apple' && url.hostname !== 'maps.apple.com') continue;
      if (service === 'google' && url.hostname !== 'www.google.com') continue;
      const raw = service === 'apple' ? url.searchParams.get('daddr') : url.searchParams.get('destination');
      if (!raw) continue;
      const values = raw.split(',');
      if (values.length !== 2) continue;
      const lat = Number(values[0]);
      const lon = Number(values[1]);
      if (!Number.isFinite(lat) || !Number.isFinite(lon) || lat < -90 || lat > 90 || lon < -180 || lon > 180) continue;
      return { lat, lon, label: (service === 'apple' && url.searchParams.get('q')) || 'Konum' };
    } catch (error) {
      continue;
    }
  }
  return null;
}

function mapPoints(journey) {
  if (!journey || journey.available !== true || !Array.isArray(journey.steps)) return [];
  const points = [];
  for (let index = 0; index < journey.steps.length && points.length < 20; index += 1) {
    const step = journey.steps[index];
    if (!step.map_links) continue;
    const point = coordsFromLinks({ apple: step.map_links.apple }) || coordsFromLinks({ google: step.map_links.google });
    if (!point) continue;
    points.push({ ...point, label: point.label === 'Konum' ? (step.description || point.label) : point.label,
      card: `trip-step-${index + 1}`, kind: 'station' });
  }
  if (points.length) points[points.length - 1].kind = 'place';
  return points;
}

function geoUri(point) {
  const lat = Number(point.lat).toFixed(6);
  const lon = Number(point.lon).toFixed(6);
  return `geo:${lat},${lon}?q=${lat},${lon}(${encodeURIComponent(point.label || 'Konum')})`;
}

function tripQuestion(from, to) {
  return `Yolculuk: ${String(from || '').trim().replace(/\s+/gu, ' ')} → ${String(to || '').trim().replace(/\s+/gu, ' ')}`;
}

function parseTripQuery(search) {
  const value = new URLSearchParams(String(search || '').replace(/^\?/u, '')).get('q') || '';
  const match = /^Yolculuk:\s*(.+?)\s*→\s*(.+)$/u.exec(value);
  if (!match) return null;
  const from = match[1].trim();
  const to = match[2].trim();
  return from.length && to.length && from.length <= 120 && to.length <= 120 ? { from, to } : null;
}

function optionFor(compare, mode) {
  return compare && Array.isArray(compare.options)
    ? compare.options.find((option) => option.mode === mode) || null : null;
}

function shareText(compare, journey) {
  const origin = (compare && compare.from) || (journey && journey.from) || '';
  const destination = (compare && compare.to) || (journey && journey.to) || '';
  const metro = optionFor(compare, 'metro');
  const bus = optionFor(compare, 'bus');
  const metroText = metro && metro.available ? `Metro ${minutesText(metro)}` : 'Metro: doğrulanamadı';
  const busText = bus && bus.available
    ? `Otobüs ${bus.line_code || ''} ${minutesText(bus)}`.trim() : 'Otobüs: doğrulanamadı';
  let routeText = 'Adımsız rota: doğrulanamadı.';
  if (journey && journey.available && Array.isArray(journey.steps) && journey.steps.length) {
    routeText = `Adımsız rota: bulundu${Number(journey.extra_minutes) > 0 ? `, tahmini ek süre ${num(journey.extra_minutes, 0)} dk` : ''}.`;
  }
  return `${trName(origin)} → ${trName(destination)}. ${metroText}, ${busText}. ${routeText} Resmî İBB hizmeti değildir.`;
}

function stepMinutes(step) {
  return step.minutes !== null && step.minutes !== undefined && Number.isFinite(Number(step.minutes))
    ? ` · ${num(step.minutes, 0)} dk tahmini` : '';
}

function stepState(status) {
  return LIFT_TR[status] || LIFT_TR.unknown;
}

function safeMapLink(value, label) {
  const point = coordsFromLinks({ apple: value }) || coordsFromLinks({ google: value });
  if (!point) return '';
  return `<a href="${esc(value)}" target="_blank" rel="noopener noreferrer">${label}</a>`;
}

function walkLinks(links) {
  if (!links) return '';
  const point = coordsFromLinks({ apple: links.apple }) || coordsFromLinks({ google: links.google });
  if (!point) return '';
  const services = [safeMapLink(links.apple, 'Apple Haritalar'), safeMapLink(links.google, 'Google Haritalar')].filter(Boolean);
  return `<p class="trip-map-links"><a class="trip-geo-step" href="${geoUri(point)}">Yürüyüşü harita uygulamasında aç</a>${services.length ? ` · ${services.join(' · ')}` : ''}</p>`;
}

function stepHtml(step, index) {
  let body = '';
  if (step.kind === 'walk') {
    body = `<p>Yürüyüş: ${esc(step.description || 'Yürüyüş')}${stepMinutes(step)}</p>${walkLinks(step.map_links)}`;
  } else if (step.kind === 'ride') {
    body = `<p>${esc(step.line || 'Raylı sistem')}: ${esc(step.from_station)} → ${esc(step.to_station)}${stepMinutes(step)}</p>`;
    const stations = Array.isArray(step.stations) ? step.stations : [];
    if (stations.length) {
      body += `<ul class="trip-station-lifts">${stations.map((station) => `<li>${esc(station.name)}: ${esc(stepState(station.lift_status))}</li>`).join('')}</ul>`;
    } else if (step.lift_status) {
      body += `<p>${esc(stepState(step.lift_status))}</p>`;
    }
  } else if (step.kind === 'transfer') {
    body = `<p>${esc(step.at_station)} istasyonunda aktarma${stepMinutes(step)}</p>`
      + `<p>${esc(stepState(step.lift_status))}</p>${step.note ? `<p>${esc(step.note)}</p>` : ''}`;
  } else {
    body = `<p>${esc(step.description || 'Rota adımı')}${stepMinutes(step)}</p>`;
  }
  return `<li id="trip-step-${index + 1}">${body}</li>`;
}

function stepFreeBlock(journey, liftByStation) {
  if (!journey) return '<p>Adımsız rota alınamadı.</p>';
  if (journey.available === false) {
    const reason = journey.reason || 'Yolculuk hesaplanamadı.';
    const uncertainty = Array.isArray(journey.uncertainty) && journey.uncertainty.length
      ? `<p>Belirsizlik: ${esc(journey.uncertainty.join(', '))}</p>` : '';
    return `<p>Doğrulanamadı: ${esc(reason)}</p>${uncertainty}`
      + (journey.provenance ? `<p class="card-foot">${stamp(journey.provenance)}${sourceLink(journey.provenance)}</p>` : '');
  }
  const steps = Array.isArray(journey.steps) ? journey.steps : [];
  const detours = journey.alternatives_used || (journey.alternative_used ? [journey.alternative_used] : []);
  const stepList = steps.length ? `<ol class="trip-steps">${steps.map(stepHtml).join('')}</ol>` : '<p>Adımsız yol adımları doğrulanamadı.</p>';
  const avoided = detours.length
    ? `<ul class="trip-avoided">${detours.map((alt) => `<li data-station="${esc(alt.avoided_station)}">`
      + `<b>Rotadan çıkarıldı: ${esc(alt.avoided_station)}</b> · <span class="trip-avoided-state">${esc(avoidedText(liftByStation[alt.avoided_station], journey.provenance))}</span>`
      + `<p>Yerine ${esc(alt.station)} (${esc(alt.line)}) kullanıldı.</p></li>`).join('')}</ul>` : '';
  const extra = Number(journey.extra_minutes) > 0
    ? `<p>Tahmini ek süre: ${num(journey.extra_minutes, 0)} dk.</p>` : '';
  const uncertainty = Array.isArray(journey.uncertainty) && journey.uncertainty.length
    ? `<p>Belirsizlik: ${esc(journey.uncertainty.join(', '))}</p>` : '';
  return `${stepList}${avoided}${extra}${uncertainty}`
    + (journey.disclaimer ? `<p class="field-hint">${esc(journey.disclaimer)}</p>` : '')
    + (journey.provenance ? `<p class="card-foot">${stamp(journey.provenance)}${sourceLink(journey.provenance)}</p>` : '');
}

function tripCardHtml(compare, journey, { needs = [], liftByStation = {}, compareError = null, journeyError = null } = {}) {
  const origin = (compare && compare.from) || (journey && journey.from) || '';
  const destination = (compare && compare.to) || (journey && journey.to) || '';
  const points = mapPoints(journey);
  const ordered = sectionOrder(needs).map((part) => {
    if (part === 'compare') {
      const content = compare ? comparisonRow(compare) : `<p>Karşılaştırma alınamadı: ${esc(compareError || 'bağlantı hatası')}</p>`;
      return `<section class="trip-card-section">${content}</section>`;
    }
    const content = journey
      ? stepFreeBlock(journey, liftByStation)
      : `<p>Adımsız rota alınamadı: ${esc(journeyError || 'bağlantı hatası')}</p>`;
    return `<details id="trip-stepfree" class="trip-stepfree"${wantsStepFree(needs) ? ' open' : ''}>`
      + `<summary>${wantsStepFree(needs) ? 'Adımsız rota (profilinize göre üstte)' : 'Adımsız rota'}</summary>${content}</details>`;
  }).join('');
  const pointList = points.length
    ? `<ul id="trip-points" class="trip-points" aria-label="Rotadaki konumlar">${points.map((point) => `<li>${point.kind === 'place' ? 'Varış' : 'İstasyon'}: ${esc(point.label)}</li>`).join('')}</ul>` : '';
  const mapAction = points.length ? `<button id="trip-map" class="btn" type="button">${icon('map')}Haritada göster</button>`
    + `<a id="trip-geo" class="btn" href="${geoUri(points[points.length - 1])}">${icon('map-pin')}Harita uygulamasında aç</a>` : '';
  return `<article id="trip-card" class="card trip-card" aria-labelledby="trip-card-title">`
    + `<h3 id="trip-card-title" class="card-title" tabindex="-1">${esc(trName(origin))} → ${esc(trName(destination))}</h3>`
    + ordered + pointList
    + `<div class="trip-actions">${mapAction}<button id="trip-share" class="btn" type="button">Paylaş</button></div>`
    + '<p id="trip-share-status" class="share-status" role="status" aria-live="polite"></p></article>';
}

export {
  COMPARE_READS, OPTION_READS, JOURNEY_READS, STEP_READS, DETOUR_READS, ALTERNATIVE_READS,
  wantsStepFree, sectionOrder, comparisonRow, stepFreeBlock, avoidedText, coordsFromLinks,
  mapPoints, geoUri, tripQuestion, parseTripQuery, shareText, tripCardHtml,
};
