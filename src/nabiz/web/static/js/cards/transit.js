/* Bus answers (spec 8.2): arrival estimates with their method, the diagnostics when there is none,
 * and live vehicles by door number, never by plate. Pure. */

import { UNKNOWN, esc, num, int, has, trName } from '../format.js';
import { icon } from '../icons.js';
import { ageAt } from '../provenance.js';
import { nextCardId, callout, head, sheet, point, row, metric, facts, details, table, disclaimer, confidence } from './sheet.js';

const METHOD_TR = { stop_sequence: 'durak sırası', distance: 'kuş uçuşu mesafe', schedule: 'ilan edilen sefer' };
const METHOD_WHY = {
  stop_sequence: 'Aracın bildirdiği yakın durak, hattın GTFS durak sırasında hedefe göre konumlandırıldı.',
  distance: 'Durak sırası kurulamadı; kuş uçuşu mesafe kıvrımlılık katsayısıyla düzeltilerek kullanıldı.',
  schedule: 'Tarifedeki ilk durak kalkışı; bu durağa varış değil.',
};
const BUS_ROWS = 12;

/** "500T, Şifa Sondurak" with the line as a badge; the arrow is an icon, the words are for screen readers. */
function lineTitle(line, stop) {
  return `<span class="badge badge-bus">${esc(line)}</span>`
    + (stop ? `<span class="sr-only"> hattı, durak:</span> ${icon('arrow-narrow-right')} ${esc(trName(stop))}` : ' hattı');
}

function arrivalRow(a, prov, id, i) {
  const method = METHOD_TR[a.method] || a.method || UNKNOWN;
  const plan = a.method === 'schedule';
  const body = metric(plan ? 'tarifeye göre' : has(a.eta_minutes) ? num(a.eta_minutes, 0) : null, plan ? '' : 'dk', '', 'süre')
    + facts([has(a.stops_away) ? `${int(a.stops_away)} durak ötede` : '', has(a.distance_km) ? `${num(a.distance_km)} km` : ''])
    + `<p class="row-facts">Yöntem: ${esc(method)}. Güven: ${confidence(a.confidence)}</p>`
    + (METHOD_WHY[a.method] ? details('Bu tahmin nasıl yapıldı?', `<p>${METHOD_WHY[a.method]}</p>`) : '');
  return row({
    id, kind: 'bus', glyph: 'bus', prov, body, i,
    title: `Kapı no ${a.door_no || UNKNOWN}${a.direction ? `, ${trName(a.direction)} yönü` : ''}`,
    extra: a.reported_at ? `konum ${ageAt(prov, a.reported_at)}` : '',
  });
}

/* No estimate: the diagnostics (which rule dropped which bus) are the answer. */
const DIAG_TR = {
  buses_received: 'İETT’den gelen araç',
  dropped_stale: 'konumu fazla eski olduğu için elenen',
  dropped_unlocatable: 'konumu hatta oturtulamayan',
  dropped_passed_target: 'durağı geçmiş olan',
  unknown_age: 'zaman damgası okunamayan',
  estimated: 'tahmin üretilen',
  returned: 'gösterilen',
};

function noteCodeTr(code) {
  const stale = /^dropped_(\d+)_positions_older_than_(\d+)s$/.exec(code || '');
  if (stale) return `${stale[1]} aracın konumu ${stale[2]} sn’den eskiydi; eski konumdan varış saati üretmiyoruz.`;
  if (code === 'no_schedule_fallback_available') return 'Bu durak için ilan edilmiş sefer saati de bulunamadı.';
  if (code === 'no_sequence_for_route') return 'Bu güzergâh için GTFS durak sırası yüklü değil.';
  return null;
}

function diagnostics(diag) {
  if (!diag) return '';
  // An unknown code keeps its raw value in data-code for whoever debugs it, not in the visible text.
  const notes = (diag.notes || []).map((code) => (noteCodeTr(code)
    ? `<li>${esc(noteCodeTr(code))}</li>` : `<li data-code="${esc(code)}">Açıklaması olmayan bir not var.</li>`)).join('');
  const counts = Object.keys(DIAG_TR).filter((k) => has(diag[k]))
    .map((k) => `<tr><td>${esc(DIAG_TR[k])}</td><td class="num">${int(diag[k])}</td></tr>`).join('');
  return callout('Tahmin üretilemediğinde sebebini gösteriyoruz. Boş ekran da, uydurma dakika da yanıt değildir.', {
    title: 'Neden varış tahmini yok?',
    html: (notes ? `<ul>${notes}</ul>` : '') + (counts ? details('Sayımlar', `<table><tbody>${counts}</tbody></table>`) : ''),
  });
}

/** The stop has no row; its marker aims at the head. */
function arrivalsAnswer({ data, provenance: prov, note }, asked) {
  const arrivals = data.arrivals || [];
  const stop = data.stop || {};
  const headId = nextCardId();
  const first = arrivals.find((a) => has(a.eta_minutes) && a.method !== 'schedule');
  return {
    html: head({
      id: headId, titleHtml: lineTitle(data.line_code, stop.name || asked), prov, note,
      count: arrivals.length ? `${arrivals.length} yaklaşan araç` : 'yaklaşan araç yok',
    })
      + (arrivals.length ? sheet(arrivals.map((a, i) => arrivalRow(a, prov, nextCardId(), i)).join('')) : diagnostics(data.diagnostics))
      + disclaimer(data.disclaimer),
    points: [point(stop, 'station', headId, `Durak: ${trName(stop.name || asked)}`, prov, 'bus-stop')],
    say: `${data.line_code}, ${trName(stop.name || asked)}: ${arrivals.length
      ? `${arrivals.length} yaklaşan araç${first ? `, ilki ${num(first.eta_minutes, 0)} dk içinde` : ''}.` : 'yaklaşan araç yok.'}`,
    prov,
  };
}

/** Vehicles as a table grouped by direction: the first twelve, the rest behind one disclosure. */
function busTable(buses, ids, prov) {
  const groups = new Map();
  buses.forEach((b, k) => groups.set(b.direction || '', [...(groups.get(b.direction || '') || []), [b, ids[k]]]));
  const body = [...groups].map(([dir, list]) => `<tbody><tr><th scope="rowgroup" colspan="4">`
    + `${dir ? `${esc(trName(dir))} yönü` : 'Yönü bilinmeyen'} (${list.length})</th></tr>`
    + list.map(([b, id]) => `<tr class="card" id="${id}" tabindex="-1"><td>${esc(b.door_no || UNKNOWN)}</td>`
      + `<td>${esc(b.nearest_stop_code || UNKNOWN)}</td><td>${esc(ageAt(prov, b.reported_at) || UNKNOWN)}</td>`
      + `<td><button type="button" class="btn row-map" data-map="${id}">${icon('map')}<span class="sr-only">Haritada göster</span></button></td></tr>`)
      .join('') + '</tbody>').join('');
  return table([['Kapı no'], ['Yakın durak'], ['Konum yaşı'], ['Harita']], body);
}

function busAnswer({ data, provenance: prov, note }) {
  const buses = [...(data.buses || [])].sort((a, b) => String(a.direction).localeCompare(String(b.direction), 'tr'));
  const ids = buses.map(() => nextCardId());
  const hint = 'Varış tahmini için durak adı ekleyin, örneğin: 500T Şifa Sondurak.';
  const more = buses.length > BUS_ROWS
    ? details(`Tümünü göster (${buses.length})`, busTable(buses.slice(BUS_ROWS), ids.slice(BUS_ROWS), prov)) : '';
  return {
    html: head({ titleHtml: `${lineTitle(data.line_code)}, canlı araçlar`, count: `${int(buses.length)} araç`, prov, note: note ? `${note} ${hint}` : hint, source: true })
      + callout('Plaka hiçbir zaman saklanmaz ve gösterilmez; araçlar yalnızca kapı numarasıyla anılır (KVKK).', { icon: 'shield-lock' })
      + (buses.length ? sheet(busTable(buses.slice(0, BUS_ROWS), ids, prov) + (more ? `<div class="sheet-more">${more}</div>` : '')) : ''),
    points: buses.map((b, k) => ({
      ...point(b, 'bus', ids[k], `Kapı no ${b.door_no}${b.direction ? `, ${trName(b.direction)} yönü` : ''}`, prov),
      age: `konum ${ageAt(prov, b.reported_at) || 'yaşı bilinmiyor'}`,
    })),
    say: `${data.line_code} hattında ${buses.length} araç bulundu.`,
    prov,
  };
}

export { arrivalsAnswer, busAnswer };
