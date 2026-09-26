import { esc } from './format.js';
import { icon } from './icons.js';

export const TOOL_LABELS = Object.freeze({
  places_resolve: { started: "Yer adı haritada aranıyor…", ended: "Yer araması bitti" },
  ispark_find_parking: { started: "İSPARK otoparkları soruluyor…", ended: "İSPARK sorgusu bitti" },
  ispark_typical_occupancy: { started: "Otopark doluluk geçmişi okunuyor…", ended: "Doluluk geçmişi okuması bitti" },
  iett_stops_search: { started: "İETT durakları aranıyor…", ended: "Durak araması bitti" },
  iett_line_buses: { started: "İETT'ye hattaki otobüsler soruluyor…", ended: "Otobüs konumu sorgusu bitti" },
  iett_next_arrivals: { started: "İETT'ye soruluyor…", ended: "İETT sorgusu bitti" },
  metro_status: { started: "Metro İstanbul duyuruları okunuyor…", ended: "Metro duyuruları okuması bitti" },
  metro_station_info: { started: "İstasyon bilgisi okunuyor…", ended: "İstasyon bilgisi okuması bitti" },
  metro_equipment_status: { started: "Metro asansör kaydı okunuyor…", ended: "Metro asansör kaydı okuması bitti" },
  traffic_index: { started: "Trafik indeksi okunuyor…", ended: "Trafik indeksi okuması bitti" },
  air_quality_now: { started: "Hava kalitesi ölçümleri okunuyor…", ended: "Hava kalitesi okuması bitti" },
  air_quality_forecast: { started: "Hava kalitesi tahmini okunuyor…", ended: "Hava tahmini okuması bitti" },
  plan_journey: { started: "Yolculuk seçenekleri karşılaştırılıyor…", ended: "Karşılaştırma bitti" },
  line_reliability: { started: "Hattın geçmiş kayıtları okunuyor…", ended: "Hat kayıtları okuması bitti" },
  check_alerts: { started: "Şehir uyarıları taranıyor…", ended: "Uyarı taraması bitti" },
  ibb_services_search: { started: "Resmî sayfalar taranıyor…", ended: "Resmî sayfa taraması bitti" },
  city_freshness: { started: "Verilerin tazeliği kontrol ediliyor…", ended: "Tazelik kontrolü bitti" },
});

export const FALLBACK = Object.freeze({ started: 'İBB kaynağına soruluyor…', ended: 'İBB kaynağı sorgusu bitti' });

function phaseOf(status) {
  if (status === 'start') return 'STARTED';
  if (status === 'end') return 'ENDED';
  return null;
}

function labelFor(name) {
  return typeof name === 'string' && Object.hasOwn(TOOL_LABELS, name) ? TOOL_LABELS[name] : FALLBACK;
}

function progressLine(data) {
  if (!data || typeof data !== 'object') return null;
  const phase = phaseOf(data.status);
  if (!phase) return null;
  const label = labelFor(data.name);
  const started = phase === 'STARTED';
  const sentence = started ? label.started : `${label.ended}.`;
  const glyph = started ? 'refresh' : 'info-circle';
  return {
    phase,
    className: started ? 'chat-tool is-running' : 'chat-tool is-done',
    html: `${icon(glyph)}<span>${esc(sentence)}</span>`,
    sentence,
  };
}

export { phaseOf, labelFor, progressLine };
