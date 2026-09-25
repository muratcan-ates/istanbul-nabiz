/* Bus stops, places from the gazetteer, and the freshness table (spec 8.2): compact rows and one
 * table, with raw codes kept out of the visible text. Pure. */

import { UNKNOWN, esc, int, shortAge, trName } from '../format.js';
import { icon } from '../icons.js';
import { sourceLabel } from '../provenance.js';
import { nextCardId, callout, empty, head, sheet, point, row, facts, details, table } from './sheet.js';

/** GTFS writes the direction as "direction: HACIKÖY"; the rider reads "yön: Hacıköy". */
const direction = (stop) => trName(String(stop.description || '').replace(/^direction:\s*/i, ''));

function stopsAnswer({ data, provenance: prov, note }) {
  const stops = data.stops || [];
  const ids = stops.map(() => nextCardId());
  const rows = stops.map((s, i) => row({
    id: ids[i], kind: 'station', glyph: 'bus-stop', title: trName(s.name || s.stop_code), prov, map: true, i,
    body: facts([direction(s) ? `yön: ${direction(s)}` : '', `Durak kodu ${s.stop_code}`]),
  })).join('');
  const codes = stops.map((s) => `<tr><td>${esc(trName(s.name))}</td><td>${esc(s.stop_code)}</td><td>${esc(s.stop_id || UNKNOWN)}</td></tr>`);
  return {
    html: head({ title: `“${data.query}” durakları`, count: `${int(stops.length)} durak`, prov, note })
      + (stops.length ? sheet(rows) + details('Kodlar', table([['Durak'], ['Durak kodu'], ['GTFS kimliği']], `<tbody>${codes.join('')}</tbody>`))
        : empty('Bu adla bir durak bulunamadı.'))
      + callout('Varış tahmini için hat kodu ekleyin, örneğin: 500T Şifa Sondurak.'),
    points: stops.map((s, i) => point(s, 'station', ids[i], `${trName(s.name)}, durak kodu ${s.stop_code}`, prov, 'bus-stop')),
    say: `“${data.query}” için ${stops.length} durak bulundu.`,
    prov,
  };
}

const PLACE_KIND_TR = { landmark: 'meydan, simge yer', metro_station: 'metro istasyonu', district: 'ilçe', aq_station: 'hava ölçüm istasyonu' };

function placesAnswer({ data, provenance: prov, note }) {
  const matches = data.matches || [];
  const ids = matches.map(() => nextCardId());
  const rows = matches.map((p, i) => row({
    id: ids[i], kind: 'place', glyph: 'map-pin', title: p.label || p.name, prov, map: true, i,
    body: facts([PLACE_KIND_TR[p.kind] || p.kind, p.district]),
  })).join('');
  return {
    html: head({
      title: `“${data.query}” için yerler`, count: `${int(matches.length)} eşleşme`, prov,
      note: note || 'Otopark, otobüs, metro veya hava kalitesi sormak için soruya bir anahtar kelime ekleyin.',
    })
      + (matches.length ? sheet(rows) : empty('Bu adla bir yer bulunamadı. Semt, meydan ya da istasyon adı deneyin.')),
    points: matches.map((p, i) => point(p, 'place', ids[i], p.label || p.name, prov)),
    say: `“${data.query}” için ${matches.length} yer bulundu.`,
    prov,
  };
}

const ago = (seconds) => (Number.isFinite(seconds) ? `${shortAge(seconds)} önce` : 'hiç alınamadı');

/** Every source in one table: its data's age, the last read, health, and the cache counts. */
function freshnessAnswer({ data, provenance: prov, note }) {
  const sources = Object.entries(data.sources || {});
  const budget = Object.entries(data.request_budget_remaining || {});
  const body = sources.map(([name, s]) => `<tr><td>${esc(sourceLabel(name))}</td><td>${esc(ago(s.data_age_seconds))}</td>`
    + `<td>${esc(ago(s.age_seconds))}</td><td>${s.healthy ? 'sağlıklı' : `${icon('alert-triangle')} sorunlu`}`
    + `${s.last_error ? `: ${esc(s.last_error)}` : ''}</td><td class="num">${int(s.hits)}</td><td class="num">${int(s.errors)}</td></tr>`);
  return {
    html: head({ title: 'Veri tazeliği', count: `${sources.length} kaynak`, prov, note })
      + (budget.length ? callout(`Kalan istek bütçesi: ${budget.map(([k, v]) => `${k} ${v}`).join(', ')}. `
        + 'İETT’nin saatlik 100 sınırının altında, 80’de duruyoruz.') : '')
      + (sources.length ? sheet(table([['Kaynak'], ['Veri yaşı'], ['Son başarılı okuma'], ['Durum'], ['Önbellek isabeti', true], ['Hata', true]],
        `<tbody>${body.join('')}</tbody>`))
        : empty('Henüz hiçbir kaynak sorgulanmadı. İlk soru bu tabloyu doldurur.')),
    points: [],
    say: `${sources.length} kaynağın veri yaşı listelendi.`,
    prov,
  };
}

export { stopsAnswer, placesAnswer, freshnessAnswer };
