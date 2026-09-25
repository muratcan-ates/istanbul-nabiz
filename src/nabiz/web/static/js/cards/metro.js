/* Metro İstanbul service notices and station facilities (spec 8.2). Pure. */

import { UNKNOWN, esc, int, has, dateTime } from '../format.js';
import { icon } from '../icons.js';
import { nextCardId, callout, head, sheet, point, row, facts } from './sheet.js';

/* The operator's published line colours live in css/tokens.css as --line-<code>, never tuned; a
 * code outside this list gets the neutral --line-unknown. The code is always written on the badge. */
const LINES = new Set('M1A M1B M2 M3 M4 M5 M6 M7 M8 M9 M11 T1 T3 T4 T5 TF1 TF2 F1 F4'.split(' '));

function badge(code) {
  const key = String(code || '').toLocaleUpperCase('tr');
  const colour = LINES.has(key) ? ` style="--line:var(--line-${key});--line-ink:var(--line-${key}-ink)"` : '';
  return code ? `<span class="badge"${colour}>${esc(code)}</span>` : '';
}

function noticeRow(line, prov, id, i) {
  const body = `<p>${esc(line.description || 'Açıklama yok.')}</p>`
    + facts([line.updated_at ? `İBB güncellemesi: ${dateTime(line.updated_at)}` : '', line.is_active === false ? 'hat kapalı' : '']);
  return row({ id, kind: 'station', glyph: 'train', titleHtml: `${badge(line.line_name)} Servis duyurusu`, body, prov, i });
}

function clearRow(line, prov, id) {
  const body = `<p class="row-ok">${icon('circle-check')} ${esc(line ? `${line} hattında` : 'Hiçbir hatta')} bildirilmiş aksaklık yok.</p>`
    + '<p class="row-sub">Metro İstanbul yalnızca duyurusu olan hatları yayımlar; listede olmamak "veri yok" değil, '
    + '"bildirilmiş aksaklık yok" demektir.</p>';
  return row({ id, kind: 'station', glyph: 'train', title: 'Servis durumu', body, prov });
}

function metroAnswer({ data, provenance: prov, note }, line) {
  const all = data.lines || [];
  const wanted = line ? all.filter((l) => (l.line_name || '').toLocaleUpperCase('tr') === line.toLocaleUpperCase('tr')) : all;
  const others = line && !wanted.length && all.length ? `Şu anda duyurusu olan hatlar: ${all.map((l) => l.line_name).join(', ')}.` : '';
  return {
    html: head({ titleHtml: line ? `${badge(line)} servis durumu` : 'Metro servis duyuruları', count: `${wanted.length} duyuru`, prov, note })
      + sheet(wanted.length ? wanted.map((l, i) => noticeRow(l, prov, nextCardId(), i)).join('') : clearRow(line, prov, nextCardId()))
      + (others ? callout(others) : ''),
    points: [],
    say: wanted.length ? `${line || 'Metro'} için ${wanted.length} servis duyurusu var.`
      : `${line ? `${line} hattında` : 'Hiçbir hatta'} bildirilmiş aksaklık yok.`,
    prov,
  };
}

/* Facilities as words with icons: "yok" is muted, never red, and a value the source left out is
 * "bilinmiyor", not an absence. */
const FACILITIES = [['lifts', 'Asansör'], ['escalators', 'Yürüyen merdiven'], ['wc', 'WC'], ['baby_room', 'Bebek odası'], ['masjid', 'Mescit']];
const FACILITY_ICONS = { lifts: 'elevator', escalators: 'escalator', wc: 'toilet-paper', baby_room: 'baby-carriage', masjid: 'building-mosque' };

function facility(value) {
  if (value === true) return 'var';
  if (value === false) return 'yok';
  return has(value) ? int(value) : UNKNOWN;
}

function stationRow(s, prov, id, i) {
  const items = FACILITIES.map(([key, label]) => {
    const value = facility(s[key]);
    return `<div><dt>${icon(FACILITY_ICONS[key])} ${label}</dt><dd${value === 'yok' || value === UNKNOWN ? ' class="row-muted"' : ''}>${value}</dd></div>`;
  }).join('');
  const body = `<dl class="row-grid">${items}</dl>`
    + (s.lifts === 0 ? `<p class="row-muted">${icon('wheelchair')} Bu istasyon için asansör kaydı yok.</p>` : '');
  return row({
    id, kind: 'station', glyph: 'train', titleHtml: `${badge(s.line_name)} ${esc(s.name)}`, prov, body, map: true, i,
    sub: has(s.order) ? `Hat sırası ${int(s.order)}` : '',
  });
}

function stationAnswer({ data, provenance: prov, note }) {
  const stations = data.stations || [];
  const ids = stations.map(() => nextCardId());
  return {
    html: head({ title: `${data.query} istasyonu`, count: `${int(stations.length)} eşleşme`, prov, note })
      + (stations.length ? sheet(stations.map((s, i) => stationRow(s, prov, ids[i], i)).join(''))
        : callout('Bu adla bir metro istasyonu bulunamadı.', { icon: 'search-off' })),
    points: stations.map((s, i) => point(s, 'station', ids[i], `${s.name} (${s.line_name})`, prov)),
    say: stations.length ? `${stations.map((s) => `${s.name} (${s.line_name})`).join(', ')} bulundu.` : 'Bu adla bir metro istasyonu bulunamadı.',
    prov,
  };
}

export { LINES, badge, metroAnswer, stationAnswer };
