/* Every card renders provenance.age. The API computes that string server-side so the phrasing
 * rules live in one place (ibb_mcp.models.Provenance.describe_age). Pure. */

import { esc } from './format.js';

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

function freshnessClass(seconds, stale) {
  if (stale) return 'cached';
  if (!Number.isFinite(seconds)) return 'old';
  if (seconds < 180) return 'fresh';
  if (seconds < 3600) return 'aging';
  return 'old';
}

/** The age stamp every single card carries — the core promise of this product. */
function stamp(prov) {
  if (!prov) return '<span class="stamp old"><i class="dot"></i>veri yaşı bilinmiyor</span>';
  const cls = freshnessClass(prov.age_seconds, prov.stale);
  const title = prov.stale
    ? 'İBB servisine ulaşılamadı; önbellekteki son değer gösteriliyor.'
    : `Kaynak: ${sourceLabel(prov.source)} · ölçüm ${prov.age}`;
  const prefix = prov.stale ? 'önbellek · ölçüm ' : 'ölçüm ';
  return `<span class="stamp ${cls}" title="${esc(title)}"><i class="dot" aria-hidden="true"></i>${prefix}<b>${esc(prov.age)}</b></span>`;
}

function sourceLink(prov) {
  if (!prov || !prov.source) return '';
  const label = esc(sourceLabel(prov.source));
  const url = prov.source_url && prov.source_url.startsWith('http') ? prov.source_url : null;
  return url
    ? `<a class="src" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${label} ↗</a>`
    : `<span class="src">${label}</span>`;
}

function cardFoot(prov, extra) {
  return `<footer class="card-foot">${stamp(prov)}${extra || ''}${sourceLink(prov)}</footer>`;
}

export { SOURCE_TR, sourceLabel, freshnessClass, stamp, sourceLink, cardFoot };
