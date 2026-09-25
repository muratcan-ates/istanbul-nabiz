/* Every answer renders provenance.age. The API computes that string server-side so the phrasing
 * rules live in one place (ibb_mcp.models.Provenance.describe_age). Pure. */

import { esc, shortAge } from './format.js';
import { icon } from './icons.js';

const SOURCE_TR = {
  ispark: 'İSPARK otoparkları',
  iett_line: 'İETT hat konumları',
  iett_fleet: 'İETT filo',
  iett_schedule: 'İETT planlanan sefer',
  metro_status: 'Metro duyuruları',
  metro_stations: 'Metro istasyonları',
  aq_stations: 'Hava kalitesi istasyonları',
  aq_readings: 'Hava kalitesi ölçümleri',
  traffic: 'Trafik indeksi',
  gtfs: 'GTFS (İETT)',
  gazetteer: 'Yer sözlüğü',
  nabiz_runtime: 'Nabız çalışma zamanı',
  nabiz_forecast: 'Nabız tahmini',
  nabiz_history: 'Nabız doluluk geçmişi',
  nabiz_routing: 'Nabız ulaşım karşılaştırması',
  nabiz_reliability: 'Nabız hat düzenliliği ölçümü',
  nabiz_alerts: 'Nabız uyarıları',
};

function sourceLabel(name) {
  return SOURCE_TR[name] || name;
}

/** İBB measured it ("ölçüm") or Nabız computed it ("hesaplama"); a computation under a minute
 * old is "az önce", because "0 sn önce" reads as a measurement too. */
const computed = (prov) => String(prov.source || '').startsWith('nabiz_');
const ageOf = (prov) => (computed(prov) && prov.age_seconds < 60 ? 'az önce' : prov.age);

/**
 * The age stamp every answer carries, the core promise of this product. The icon says under or
 * over an hour. Warn colour only when İBB failed and a cached value is shown; never for age
 * alone, because a day-old station record is normal. `extra` is a second age from the same
 * answer ("konum 1 dk önce", "girdi ölçümü 14 gün önce").
 */
const STAMP_ICONS = { cached: 'clock-exclamation', recent: 'clock', old: 'history' };

function stamp(prov, extra) {
  if (!prov || !prov.age) return `<span class="stamp">${icon('clock-question')}veri yaşı bilinmiyor</span>`;
  const glyph = STAMP_ICONS[prov.stale ? 'cached' : prov.age_seconds < 3600 ? 'recent' : 'old'];
  // One text span beside the icon: the stamp's flex gap would otherwise open before a comma.
  return `<span class="stamp${prov.stale ? ' is-cached' : ''}">${icon(glyph)}<span>${prov.stale ? 'önbellekten, ' : ''}`
    + `${computed(prov) ? 'hesaplama' : 'ölçüm'} <b>${esc(ageOf(prov))}</b>${extra ? `, ${esc(extra)}` : ''}</span></span>`;
}

/** The stamp's words without markup, for a map popup and the location list. */
function stampText(prov) {
  if (!prov || !prov.age) return 'veri yaşı bilinmiyor';
  return `${prov.stale ? 'önbellekten, ' : ''}${computed(prov) ? 'hesaplama' : 'ölçüm'} ${ageOf(prov)}`;
}

/** The same fact as one sentence, for #answer-status. */
function ageSentence(prov) {
  if (!prov || !prov.age) return 'Veri yaşı bilinmiyor.';
  return computed(prov) ? `Hesaplama ${ageOf(prov)} yapıldı.` : `Veri ${prov.age} ölçüldü.`;
}

/** Seconds between another timestamp of the same answer (a bus position, a forecast's input) and
 * the server's clock, which is the reference time plus age_seconds; the visitor's clock may be wrong. */
function secondsAt(prov, iso) {
  const now = prov ? Date.parse(prov.reported_at || prov.observed_at || '') + prov.age_seconds * 1000 : NaN;
  return Math.max(0, (now - Date.parse(iso || '')) / 1000);
}

function ageAt(prov, iso) {
  const seconds = secondsAt(prov, iso);
  return Number.isFinite(seconds) ? `${shortAge(seconds)} önce` : '';
}

function sourceLink(prov) {
  if (!prov || !prov.source) return '';
  const label = esc(sourceLabel(prov.source));
  const url = prov.source_url && prov.source_url.startsWith('http') ? prov.source_url : null;
  return url
    ? `<a class="src" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${label} ${icon('external-link')}</a>`
    : `<span class="src">${label}</span>`;
}

export { SOURCE_TR, sourceLabel, stamp, stampText, ageSentence, secondsAt, ageAt, sourceLink };
