/* Route ribbons (spec 12.3 rule 3): each option's legs laid end to end on one minute axis shared
 * by the whole answer, so the lengths compare. The dash pattern, not only the colour, says what
 * a leg is. Pure. */

import { num } from '../format.js';

const LEG_CLASS = { walk: 'foot', wait: 'foot', transfer: 'foot', park: 'foot', rail: 'transit', ride: 'transit', drive: 'drive', delay: 'drive' };
const LEG_TR = {
  walk: 'yürüyüş', wait: 'bekleme', transfer: 'aktarma', park: 'otopark arama', rail: 'raylı sistem', ride: 'otobüs',
  drive: 'sürüş', delay: 'gecikme',
};

/** The legs as one line of an SVG whose width is the page's; the stroke keeps its width and dash
 * pattern at every size (non-scaling), so a phone reads the same patterns as a desktop. */
function ribbon(legs, maxMinutes) {
  let at = 0;
  const x = (m) => ((1000 * m) / (maxMinutes || 1)).toFixed(1);
  const lines = (legs || []).filter((leg) => leg.minutes > 0).map((leg) => {
    const from = at;
    at += leg.minutes;
    return `<line class="ribbon-leg ribbon-${LEG_CLASS[leg.kind] || 'foot'}" x1="${x(from)}" x2="${x(at)}" y1="6" y2="6" `
      + 'vector-effect="non-scaling-stroke"></line>';
  }).join('');
  return `<svg viewBox="0 0 1000 12" preserveAspectRatio="none" width="100%" height="12" overflow="visible" aria-hidden="true" `
    + `focusable="false">${lines}</svg>`;
}

/** What the ribbon shows, as words: minutes per kind of leg, in the order they first occur. */
function ribbonSentence(legs, total) {
  const sums = new Map();
  (legs || []).forEach((leg) => sums.set(leg.kind, (sums.get(leg.kind) || 0) + (leg.minutes || 0)));
  const parts = [...sums].map(([kind, minutes]) => `${LEG_TR[kind] || kind} ${num(minutes, 0)} dk`);
  return `Toplam ${num(total, 0)} dk${parts.length ? `: ${parts.join(', ')}` : ''}.`;
}

export { LEG_CLASS, LEG_TR, ribbon, ribbonSentence };
