/* İSPARK lots (spec 8.2): free spaces, how full on a fixed 0 to 100 % scale, and the tariff as a
 * table. The first three lots in full, the rest compact under one disclosure. Pure. */

import { esc, num, int, has, trName } from '../format.js';
import { icon } from '../icons.js';
import { occupancy } from '../charts/scale.js';
import { nextCardId, head, sheet, point, row, metric, facts, details, table, empty } from './sheet.js';

const FULL_ROWS = 3;

/** İSPARK ships the tariff as "0-1 Saat : 110,00;1-2 Saat : 140,00": a table, lira right aligned. */
function tariff(raw) {
  if (!raw) return '';
  const rows = String(raw).split(';').map((part) => part.split(':')).filter((p) => p.length >= 2);
  if (!rows.length) return `<p class="row-facts">${esc(raw)}</p>`;
  const body = rows.map(([label, value]) => `<tr><td>${esc(label.trim())}</td><td class="num">${esc(value.trim())} ₺</td></tr>`);
  return details(`Tarife (${rows.length} kademe)`, table([['Süre'], ['Ücret', true]], `<tbody>${body.join('')}</tbody>`));
}

const freeSpaces = (lot) => (has(lot.empty) ? `${int(lot.empty)} boş yer` : 'boş yer bilinmiyor');
const distance = (lot) => (has(lot.distance_km) ? `${num(lot.distance_km)} km uzakta` : '');

function lotRow(lot, prov, id, i) {
  const occ = occupancy(lot.capacity, lot.empty);
  const closed = lot.is_open === false;
  // From 90 % a word and an icon say it too: the stroke's length alone speaks only to the sighted.
  const state = closed ? `<p class="row-muted">${icon('clock-pause')} Şu anda kapalı</p>`
    : occ.share >= 0.9 ? `<p class="row-warn">${icon('alert-triangle')} Neredeyse dolu</p>` : '';
  const filled = occ.share === null ? '' : `, %${Math.round(occ.share * 100)} dolu`;
  const body = metric(has(lot.empty) ? int(lot.empty) : null, 'boş yer', lot.capacity ? `${int(lot.capacity)} yerden${filled}` : '')
    + (closed ? '' : occ.html) + state
    + facts([distance(lot), trName(lot.district), trName(lot.park_type), lot.work_hours,
      lot.free_minutes ? `ilk ${int(lot.free_minutes)} dk ücretsiz` : '', has(lot.monthly_fee) ? `aylık ${int(lot.monthly_fee)} ₺` : ''])
    + tariff(lot.tariff);
  return row({ id, kind: 'park', glyph: 'parking', title: lot.name, sub: lot.address, body, prov, map: true, i });
}

function compactRow(lot, prov, id) {
  return row({ id, kind: 'park', glyph: 'parking', title: lot.name, body: facts([freeSpaces(lot), distance(lot)]), prov, map: true, i: 5 });
}

/** The whole answer. The map plots every lot and the searched place, which points at the head. */
function parkingAnswer({ data, provenance: prov, note }) {
  const parks = data.parks || [];
  const ids = parks.map(() => nextCardId());
  const placeId = nextCardId();
  const rest = parks.slice(FULL_ROWS).map((lot, k) => compactRow(lot, prov, ids[FULL_ROWS + k])).join('');
  const rows = parks.slice(0, FULL_ROWS).map((lot, i) => lotRow(lot, prov, ids[i], i)).join('')
    + (rest ? `<details class="sheet-more"><summary>${icon('chevron-right')}Diğer ${parks.length - FULL_ROWS} otopark</summary>${rest}</details>` : '');
  return {
    html: head({ id: placeId, title: `${data.near} çevresinde otopark`, count: `${int(parks.length)} otopark, ${num(data.radius_km)} km içinde`, prov, note })
      + (parks.length ? sheet(rows) : empty('Bu yarıçapta boş yeri olan açık otopark bulunamadı.')),
    points: parks.map((lot, i) => point(lot, 'park', ids[i], `${lot.name}: ${freeSpaces(lot)}`, prov))
      .concat({ lat: data.lat, lon: data.lon, kind: 'place', card: placeId, label: `Aranan yer: ${data.near}` }),
    say: `${data.near} çevresinde ${parks.length} otopark bulundu.`,
    prov,
  };
}

export { parkingAnswer };
