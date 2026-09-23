/* The card skeleton every answer shares: identity on the left, age at the bottom. Pure. */

import { esc, has } from '../format.js';
import { icon } from '../icons.js';
import { cardFoot } from '../provenance.js';

let cardSeq = 0;
function nextCardId() {
  cardSeq += 1;
  return `kart-${cardSeq}`;
}

/**
 * One card skeleton for every answer type: identity on the left, age at the bottom.
 * `id` is what a map marker points at, which is why every caller passes one.
 */
function cardShell(opts) {
  const kind = opts.kind || '';
  return `<article class="card" id="${esc(opts.id)}" tabindex="-1"${opts.aria ? ` aria-label="${esc(opts.aria)}"` : ''}>
    <div class="card-head">
      ${opts.icon ? `<span class="card-kind ${esc(kind)}" aria-hidden="true">${icon(opts.icon)}</span>` : ''}
      <div class="card-title">
        <h3>${opts.titleHtml || esc(opts.title)}</h3>
        ${opts.sub ? `<p class="sub">${esc(opts.sub)}</p>` : ''}
      </div>
    </div>
    <div class="card-body">${opts.body || ''}</div>
    ${cardFoot(opts.prov, opts.footExtra)}
  </article>`;
}

function resultHead(title, count, prov, note) {
  return [
    `<div class="result-head"><h2>${esc(title)}${has(count) ? ` <span class="count">${esc(count)}</span>` : ''}</h2></div>`,
    note ? `<p class="note">${esc(note)}</p>` : '',
  ].join('');
}

function cards(html, wide) {
  return `<div class="cards${wide ? ' two' : ''}">${html}</div>`;
}

function metaList(items) {
  const kept = (items || []).filter(Boolean);
  if (!kept.length) return '';
  return `<ul class="meta">${kept.map((m) => `<li>${esc(m)}</li>`).join('')}</ul>`;
}

function simpleCard(opts) {
  return cardShell({
    id: opts.id, kind: opts.kind || '', icon: opts.icon || 'pin', prov: opts.prov,
    title: opts.title, sub: opts.sub, body: metaList(opts.meta),
  });
}

export { nextCardId, cardShell, resultHead, cards, metaList, simpleCard };
