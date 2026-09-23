/* The travel-mode comparison: one card per mode, never navigation. Pure. */

import { num, CONFIDENCE_TR } from '../format.js';
import { simpleCard } from './shell.js';

const MODE_ICON = { drive: 'traffic', metro: 'metro', bus: 'bus', walk: 'pin' };

function routeCard(option, advice, prov, id) {
  const tags = [];
  if (advice.fastest_mode === option.mode) tags.push('en hızlı');
  if (advice.most_comfortable_mode === option.mode) tags.push('en konforlu');
  return simpleCard({
    id, kind: '', icon: MODE_ICON[option.mode] || 'route', prov,
    title: `${option.label} · ${num(option.total_minutes, 0)} dk`,
    sub: tags.join(' · '),
    meta: (option.legs || []).map((leg) => `${leg.description}: ${num(leg.minutes, 0)} dk`)
      .concat([
        `güven: ${CONFIDENCE_TR[option.confidence] || option.confidence}`,
        option.comfort ? `konfor puanı: ${num(option.comfort.score, 0)}/100` : null,
      ])
      // The option's own notes carry what the numbers cannot: a disruption on a line the
      // path rides, an input that could not be read ("okunamadı … bilinmiyor"), the
      // traffic against its usual level, the other buses that also go there. Without
      // them an unknown input would look like good news.
      .concat(option.notes || []),
  });
}

export { routeCard };
