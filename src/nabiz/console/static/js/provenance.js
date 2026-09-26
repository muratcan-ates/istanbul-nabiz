/* Every number carries its source and its age. The contract's Provenance is
 * {source, url, observed_at, age_s, mode: live | recorded | schedule | unknown}; the stamp says the
 * mode with its icon and the age the server measured (age_s), never the visitor's clock. Pure. */

import { dateTime, esc, int, shortAge } from './format.js';
import { icon } from './icons.js';

const AUTHOR_TR = { model: 'model', 'yerel model': 'yerel model', kural: 'kural' };
const TOOL_TR = {
  places_resolve: 'yer arama', ispark_find_parking: 'otopark arama', ispark_typical_occupancy: 'otopark doluluk geçmişi',
  iett_stops_search: 'durak arama', iett_line_buses: 'hattaki otobüsler', iett_next_arrivals: 'varış tahmini',
  metro_status: 'Metro duyuruları', metro_station_info: 'istasyon bilgisi', metro_equipment_status: 'Metro arıza kaydı',
  metro_equipment_signals: 'Metro ekipman sinyalleri', check_alerts: 'şehir uyarıları',
  traffic_index: 'trafik indeksi', air_quality_now: 'hava kalitesi', air_quality_forecast: 'hava kalitesi tahmini',
  plan_journey: 'yolculuk karşılaştırması', line_reliability: 'hat güvenilirliği', city_freshness: 'veri tazeliği',
  ibb_datasets_search: 'açık veri kataloğu', citizen_report: 'vatandaş bildirimi',
};

const SOURCE_TR = {
  ispark: 'İSPARK otoparkları',
  iett_line: 'İETT hat konumları',
  iett_fleet: 'İETT filo',
  iett_schedule: 'İETT planlanan sefer',
  iett_arrivals: 'İETT varış tahmini',
  metro_status: 'Metro İstanbul duyuruları',
  metro_stations: 'Metro İstanbul istasyonları',
  metro_equipment: 'Metro İstanbul ekipman kaydı',
  aq_stations: 'Hava kalitesi istasyonları',
  aq_readings: 'Hava kalitesi ölçümleri',
  traffic: 'Trafik indeksi',
  gtfs: 'GTFS (İETT)',
  gazetteer: 'Yer sözlüğü',
  nabiz_runtime: 'Nabız çalışma zamanı',
  nabiz_forecast: 'Nabız tahmini',
  nabiz_routing: 'Nabız ulaşım karşılaştırması',
  nabiz_alerts: 'Nabız uyarıları',
  nexus_ledger: 'Nabız karar defteri',
  nexus_rules: 'Nabız kural kataloğu',
  'local:knowledge': 'Hizmet sayfaları (yerel dizin)',
  ibb_catalog: 'İBB Açık Veri kataloğu',
};

const MODE_TR = { live: 'canlı', old: 'ölçüm', recorded: 'kayıtlı', schedule: 'tarifeye göre', unknown: 'bilinmiyor' };
const MODE_ICON = { live: 'antenna-bars-5', old: 'history', recorded: 'history', schedule: 'clock', unknown: 'clock-question' };
/** A live feed's reading counts as "canlı" only while it is under two hours old (the web page's
 * rule for its live dot); older than that it is a measurement with an age, never "canlı". */
const LIVE_SECONDS = 7200;

function sourceLabel(name) {
  return SOURCE_TR[name] || name || 'kaynak bilinmiyor';
}

/** The mode the stamp shows: the server's mode, except that a stale live reading reads "ölçüm". */
function modeOf(prov) {
  if (!prov || !MODE_TR[prov.mode] || prov.mode === 'old') return 'unknown';
  if (prov.mode === 'live' && !(Number.isFinite(prov.age_s) && prov.age_s < LIVE_SECONDS)) return 'old';
  return prov.mode;
}

/** "2 dk önce" from the server's age; a recorded capture says its date, because "önce" would lie. */
function ageText(prov) {
  if (!prov) return 'veri yaşı bilinmiyor';
  if (modeOf(prov) === 'recorded' && prov.observed_at) return dateTime(prov.observed_at);
  if (Number.isFinite(prov.age_s)) return `${shortAge(prov.age_s)} önce`;
  const sourceTime = prov.source_updated_at || prov.observed_at || prov.fetched_at;
  if (sourceTime) {
    const timestamp = Date.parse(sourceTime);
    if (Number.isFinite(timestamp)) return `${shortAge(Math.max(0, (Date.now() - timestamp) / 1000))} önce`;
  }
  return 'veri yaşı bilinmiyor';
}

/** The stamp: mode icon, mode word, age. Colour is never alone: the icon and the word say it too. */
function stamp(prov) {
  const mode = modeOf(prov);
  return `<span class="stamp is-${mode}">${icon(MODE_ICON[mode])}<span>${MODE_TR[mode]} · <b>${esc(ageText(prov))}</b></span></span>`;
}

/** Age alone, for a card whose metric row already names the mode (the arrival card). */
function ageStamp(prov) {
  const recent = prov && Number.isFinite(prov.age_s) && prov.age_s < 3600;
  return `<span class="stamp">${icon(recent ? 'clock' : 'history')}<b>${esc(ageText(prov))}</b></span>`;
}

/** The same fact as a sentence, for a status region. */
function ageSentence(prov) {
  const mode = modeOf(prov);
  if (mode === 'recorded') return `Kayıtlı veri, ${esc(ageText(prov))}.`;
  if (!Number.isFinite(prov && prov.age_s)) return 'Veri yaşı bilinmiyor.';
  return `Veri ${shortAge(prov.age_s)} önce alındı${mode === 'schedule' ? ', tarifeye göre' : ''}.`;
}

function sourceLink(prov) {
  if (!prov) return '';
  const label = esc(sourceLabel(prov.source));
  const href = prov.url && /^https?:\/\//.test(prov.url) ? prov.url : null;
  return href
    ? `<a class="src" href="${esc(href)}" target="_blank" rel="noopener noreferrer">${label} ${icon('external-link')}</a>`
    : `<span class="src">${label}</span>`;
}

/** One citation chip: source, then the stamp. */
function citation(prov) {
  return `<li class="cite">${sourceLink(prov)}${stamp(prov)}</li>`;
}

function citations(list) {
  const items = (list || []).filter(Boolean);
  if (!items.length) return '';
  return `<ul class="cites" aria-label="Kaynaklar">${items.map(citation).join('')}</ul>`;
}

/* The turn's trace (final.how.chain, final.how.checks): ASCII stage and check names from the
 * server, Turkish words here. An unknown name is shown as sent, escaped. */
const STEP_TR = {
  girdi: 'Girdi', acil: 'Acil', hassas: 'Hassas', maske: 'Maske', katman: 'Katman', dil: 'Dil',
  arac_bilgi: 'Araç/bilgi', cikti: 'Çıktı',
};
const CHECK_TR = { girdi: 'Girdi', hassas: 'Hassas konu', sayi: 'Sayılar', kanit: 'Kanıt', cikti: 'Çıktı' };
const STATUS_TR = {
  gecti: 'geçti', cevapladi: 'cevapladı', hata: 'hata verdi',
  true: 'doğrulandı', false: 'takıldı', null: 'uygulanmadı',
};

function traceRows(how) {
  const rows = [];
  if (Array.isArray(how.chain) && how.chain.length) {
    const steps = how.chain.map((step) => {
      const name = STEP_TR[step.name] || step.name;
      return `${esc(name)} ${esc(STATUS_TR[step.status] || step.status)}`;
    });
    rows.push(`<li class="cite">Adımlar: ${steps.join(' · ')}</li>`);
  }
  if (how.checks && typeof how.checks === 'object' && !Array.isArray(how.checks)) {
    const checks = Object.entries(how.checks).map(([name, value]) => {
      const state = value === true || value === false ? String(value) : 'null';
      return `${esc(CHECK_TR[name] || name)} ${esc(STATUS_TR[state])}`;
    });
    if (checks.length) rows.push(`<li class="cite">Kontroller: ${checks.join(' · ')}</li>`);
  }
  return rows.join('');
}

function howPanel(how, id) {
  if (!how) return '';
  const tools = Array.isArray(how.tools) && how.tools.length ? how.tools : (how.tool ? [how] : []);
  const toolRows = tools.length
    ? tools.map((tool) => {
      const name = tool.name || tool.tool || 'bilinmiyor';
      const label = TOOL_TR[name] || name;
      const result = tool.ok === undefined ? '' : ` · ${tool.ok ? 'başarılı' : 'başarısız'}`;
      return `<li class="cite">Araç: ${esc(label)} (${esc(name)})${result}</li>`;
    })
    : ['<li class="cite">Araç: bilinmiyor</li>'];
  const sourceRows = tools.map((tool) => {
    const url = tool.source_url || tool.url;
    const provenance = { source: tool.source || url, url };
    return `<li class="cite">Kaynak adresi: ${sourceLink(provenance)}</li>`;
  });
  const observed = tools.map((tool) => tool.observed_at).filter(Boolean);
  const observedText = observed.length ? observed.map(dateTime).join(', ') : 'zaman bilinmiyor';
  const rule = how.rule_id || 'kural yok';
  const uncertainty = Array.isArray(how.uncertainty) && how.uncertainty.length ? how.uncertainty.join(', ') : 'yok';
  const latency = Number.isFinite(Number(how.latency_ms)) ? Math.trunc(Number(how.latency_ms)) : null;
  return `<details id="${esc(id)}-how"><summary>${icon('list-details')}Bu nasıl bulundu?</summary><ul class="cites">`
    + `${traceRows(how)}${toolRows.join('')}${sourceRows.join('')}`
    + `<li class="cite">Kayıt zamanı: ${esc(observedText)}</li>`
    + `<li class="cite">Kural: ${esc(rule)}</li>`
    + `<li class="cite">Belirsizlik: ${esc(uncertainty)}</li>`
    + `<li class="cite">Sistem gecikmesi: ${esc(int(latency))} ms</li>`
    + '</ul></details>';
}

export {
  SOURCE_TR, MODE_TR, MODE_ICON, LIVE_SECONDS, AUTHOR_TR, TOOL_TR, sourceLabel, modeOf, ageText, stamp, ageStamp,
  ageSentence, sourceLink, citation, citations, howPanel,
};
