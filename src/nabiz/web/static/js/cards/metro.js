/* Metro İstanbul service notices and station facilities. Pure. */

import { esc, int, has } from '../format.js';
import { icon } from '../icons.js';
import { cardShell, metaList } from './shell.js';

const NEUTRAL_LINE = '#5a6473';

/* White on a pale line colour (M7's pink) reads at 2:1. Past a relative luminance of about
 * 0.19 the dark ink of .ink-dark in style.css contrasts more than white (WCAG 2.2). */
function inkClass(hex) {
  const m = /^#(..)(..)(..)$/.exec(hex);
  const [r, g, b] = m ? m.slice(1).map((c) => (parseInt(c, 16) / 255) ** 2.2) : [0, 0, 0];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.19 ? ' ink-dark' : '';
}

function metroCard(line, prov, id) {
  const colour = line.color || NEUTRAL_LINE;
  const body = `
    <p>${esc(line.description || 'Açıklama yok.')}</p>
    ${metaList([line.updated_at ? `İBB güncellemesi: ${new Date(line.updated_at).toLocaleString('tr-TR')}` : null,
    line.is_active === false ? 'hat kapalı' : null])}`;
  return cardShell({
    id, kind: 'station', icon: 'metro', prov, body,
    titleHtml: `<span class="line-badge${inkClass(colour)}" style="background:${esc(colour)}">${esc(line.line_name || '?')}</span>Servis duyurusu`,
  });
}

function metroClearCard(line, prov, id) {
  const body = `
    <p class="status-ok">${icon('check')}${esc(line ? `${line} hattında bildirilmiş aksaklık yok.` : 'Hiçbir hatta bildirilmiş aksaklık yok.')}</p>
    <p class="hint">Metro İstanbul yalnızca <em>duyurusu olan</em> hatları yayımlar; listede olmamak "veri yok" değil,
      "bildirilmiş aksaklık yok" demektir.</p>`;
  return cardShell({ id, kind: 'station', icon: 'metro', prov, body, title: 'Servis durumu' });
}

function stationCard(station, prov, id) {
  const yes = (v) => (v === true ? 'var' : v === false ? 'yok' : 'bilinmiyor');
  const stats = [
    ['Asansör', has(station.lifts) ? int(station.lifts) : '—'],
    ['Yürüyen merdiven', has(station.escalators) ? int(station.escalators) : '—'],
    ['WC', yes(station.wc)],
    ['Bebek odası', yes(station.baby_room)],
    ['Mescit', yes(station.masjid)],
  ];
  const body = `
    <div class="stat-grid">${stats.map(([k, v]) => `<div class="stat"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div></div>`).join('')}</div>
    ${metaList([has(station.order) ? `hat sırası ${int(station.order)}` : null])}`;
  return cardShell({
    id, kind: 'station', icon: 'metro', prov, body,
    titleHtml: `<span class="line-badge" style="background:${NEUTRAL_LINE}">${esc(station.line_name || '?')}</span>${esc(station.name || '')}`,
    sub: 'İstasyon donanımı',
  });
}

export { metroCard, metroClearCard, stationCard };
