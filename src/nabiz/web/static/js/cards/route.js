/* The travel-mode comparison (spec 8.2): one row per mode with its ribbon on a minute axis the
 * whole answer shares, never navigation. Pure. */

import { esc, num, has } from '../format.js';
import { icon } from '../icons.js';
import { ribbon, ribbonSentence } from '../charts/ribbon.js';
import { nextCardId, callout, head, sheet, row, metric, details, disclaimer, confidence } from './sheet.js';

const MODE_ICONS = { drive: 'car', metro: 'train', bus: 'bus', walk: 'walk' };
const LEG_ICONS = {
  walk: 'walk', wait: 'clock', transfer: 'arrows-exchange', park: 'parking', rail: 'train', ride: 'bus', drive: 'car', delay: 'alert-triangle',
};

function steps(option) {
  const legs = (option.legs || []).map((leg) => `<li>${icon(LEG_ICONS[leg.kind] || 'route')} ${esc(leg.description)}: `
    + `${num(leg.minutes, 0)} dk${leg.kind === 'delay' ? ' (gecikme)' : ''}</li>`).join('');
  const assumed = (option.assumptions || []).map((a) => `<li>${esc(a.detail || a.key)}</li>`).join('');
  return details('Adımlar ve varsayımlar', `<ol>${legs}</ol>${assumed ? `<p>Varsayımlar</p><ul>${assumed}</ul>` : ''}`);
}

function optionRow(option, advice, prov, extra, id, i, longest) {
  const tags = [advice.fastest_mode === option.mode ? `${icon('bolt')} en hızlı` : '',
    advice.most_comfortable_mode === option.mode ? `${icon('armchair')} en konforlu` : ''].filter(Boolean).join(', ');
  const body = metric(num(option.total_minutes, 0), 'dk', tags, 'süre')
    + ribbon(option.legs, longest) + `<p class="sr-only">${esc(ribbonSentence(option.legs, option.total_minutes))}</p>`
    + `<p class="row-facts">Güven: ${confidence(option.confidence)}${option.comfort && has(option.comfort.score)
      ? `, konfor puanı ${num(option.comfort.score, 0)}/100` : ''}</p>`
    // The option's own notes carry what the numbers cannot: a disruption on a line the path rides,
    // an input that could not be read, the traffic against its usual level. Without them an
    // unknown input would look like good news.
    + (option.notes || []).map((n) => `<p class="row-sub">${esc(n)}</p>`).join('')
    + steps(option);
  return row({ id, glyph: MODE_ICONS[option.mode] || 'route', title: option.label, body, prov, extra, i });
}

/** An option the server could not compute: a muted row with its reason, never a hidden one. */
function unavailableRow(option, prov, extra, i) {
  return row({
    id: nextCardId(), glyph: MODE_ICONS[option.mode] || 'route', title: option.label, prov, extra, i,
    body: `<p class="row-muted">${esc(option.reason || 'Hesaplanamadı.')}</p>`,
  });
}

function routeAnswer({ data: d, provenance: prov, note }) {
  const options = (d.options || []).filter((o) => o.available !== false);
  const missing = (d.options || []).filter((o) => o.available === false).concat(d.unavailable_options || []);
  const longest = Math.max(1, ...options.map((o) => o.total_minutes || 0));
  const headId = nextCardId();
  const [from, to] = [d.origin.name, d.destination.name];
  const fastest = options.find((o) => o.mode === d.fastest_mode);
  // Computed on this request from inputs of different ages: the stamp says both.
  const computedNow = prov && { ...prov, age: 'az önce', age_seconds: 0 };
  const extra = prov && prov.age ? `en eski girdi ${prov.age}` : '';
  const rows = options.map((o, i) => optionRow(o, d, computedNow, extra, nextCardId(), i, longest)).join('')
    + missing.map((o, k) => unavailableRow(o, computedNow, extra, options.length + k)).join('');
  return {
    html: head({
      id: headId, prov: computedNow, extra, note,
      titleHtml: `${esc(from)} ${icon('arrow-narrow-right')}<span class="sr-only"> ile </span> ${esc(to)}<span class="sr-only"> arası</span>`,
      count: `${options.length} seçenek`,
    })
      + (rows ? sheet(rows) : callout('Bu iki nokta arasında hiçbir seçenek hesaplanamadı.', { icon: 'search-off' }))
      + disclaimer(options.length ? 'Şeritler aynı dakika ölçeğinde: düz çizgi raylı sistem ve otobüs, kesik çizgi araba, '
        + 'noktalı çizgi yürüyüş, bekleme ve aktarma.' : '')
      + disclaimer(d.disclaimer),
    points: [
      { lat: d.origin.lat, lon: d.origin.lon, kind: 'place', card: headId, label: `Başlangıç: ${from}` },
      { lat: d.destination.lat, lon: d.destination.lon, kind: 'place', card: headId, label: `Varış: ${to}` },
    ],
    say: `${from} ile ${to} arası ${options.length} seçenek hesaplandı`
      + `${fastest ? `; en hızlısı ${fastest.label}, ${num(fastest.total_minutes, 0)} dk` : ''}.`,
    prov: computedNow,
  };
}

export { routeAnswer };
