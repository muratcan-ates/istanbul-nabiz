/* Adapted from DOU-Synapse apps/web/components/chat/transcript-parts.tsx (MIT, Copyright (c) 2026 Muratcan Ates). */

import * as prov from './provenance.js';
import { dateTime, esc } from './format.js';
import { icon } from './icons.js';

function quoteBox(hits) {
  const items = (hits || []).filter(Boolean);
  if (!items.length) return '';
  return '<div class="quote-box" role="group" aria-label="Kaynakta geçen ifade">'
    + '<p class="quote-title">Kaynakta geçen ifade</p>'
    + items.map((hit) => `<figure class="quote"><blockquote class="quote-text">${esc(hit.quote)}</blockquote>`
      + `<figcaption class="quote-src"><a href="${esc(hit.url)}" target="_blank" rel="noopener noreferrer">`
      + `${esc(hit.title || 'Kaynak sayfası')}</a> · alındı: ${dateTime(hit.fetched_at)}</figcaption></figure>`).join('')
    + '</div>';
}

function renderPart(part) {
  if (!part || typeof part !== 'object') return '';
  if (part.kind === 'question') return `<p class="chat-who">Siz</p><p class="chat-text">${esc(part.text)}</p>`;
  if (part.kind === 'text') return `<p class="chat-text">${esc(part.text)}</p>`;
  if (part.kind === 'tool') {
    const running = part.status === 'start';
    const toolName = (name) => (prov.TOOL_TR && prov.TOOL_TR[name]) || 'İBB aracı';
    return `<p class="chat-tool ${running ? 'is-running' : 'is-done'}">${icon(running ? 'refresh' : 'circle-check')}`
      + `<span>${running ? 'Araç çalışıyor' : 'Araç tamamlandı'}: ${esc(toolName(part.name))}</span></p>`;
  }
  if (part.kind === 'citations') {
    const items = (part.items || []).filter(Boolean);
    const hits = items.filter((item) => typeof item.quote === 'string');
    const provenance = items.filter((item) => typeof item.quote !== 'string');
    return quoteBox(hits) + (prov.citations ? prov.citations(provenance) : '');
  }
  if (part.kind === 'quote') return quoteBox(part.items);
  if (part.kind === 'author') {
    const author = part.author || part.name || part.value;
    const label = (value) => (prov.AUTHOR_TR && prov.AUTHOR_TR[value]) || value || 'bilinmiyor';
    return `<p class="chat-foot"><span>cevabı yazan: <b>${esc(label(author))}</b></span></p>`;
  }
  if (part.kind === 'notice') {
    const level = ['soft', 'warn', 'bad'].includes(part.level) ? part.level : 'soft';
    const classes = { soft: 'callout', warn: 'callout callout-warn', bad: 'callout callout-error' };
    const role = level === 'bad' ? ' role="alert"' : '';
    const title = part.title ? `<p class="callout-title">${esc(part.title)}</p>` : '';
    return `<div class="${classes[level]}"${role}>${title}<p>${esc(part.text)}</p></div>`;
  }
  return '';
}

function renderParts(list) {
  return (list || []).map(renderPart).join('');
}

export { renderPart, renderParts, quoteBox };
