/* Adapted from DOU-Synapse apps/web/components/chat/transcript-parts.tsx (MIT, Copyright (c) 2026 Muratcan Ates). */

import * as prov from './provenance.js';
import { dateTime, esc } from './format.js';
import { icon } from './icons.js';
import { onLang, t } from './i18n_text.js';

function quoteBox(hits) {
  const items = (hits || []).filter(Boolean);
  if (!items.length) return '';
  return '<div class="quote-box" role="group" aria-label="Kaynakta geçen ifade">'
    + '<p class="quote-title">Kaynakta geçen ifade</p>'
    + items.map((hit) => {
      const quoteId = /^ac-quote-\d+-\d+$/.test(hit.quote_anchor || '') ? hit.quote_anchor : '';
      const citationId = /^ac-cite-\d+-\d+$/.test(hit.citation_anchor || '') ? hit.citation_anchor : '';
      const url = citationId ? `#${citationId}` : hit.url;
      const target = citationId ? '' : ' target="_blank" rel="noopener noreferrer"';
      const label = citationId ? hit.citation_label || 'Alıntının kaynağı' : hit.title || 'Kaynak sayfası';
      return `<figure class="quote"${quoteId ? ` id="${quoteId}"` : ''}><blockquote class="quote-text">${esc(hit.quote)}</blockquote>`
        + `<figcaption class="quote-src"><a href="${esc(url)}"${target}>${esc(label)}</a>`
        + ` · alındı: ${dateTime(hit.fetched_at)}</figcaption></figure>`;
    }).join('')
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

// Entry markers describe one event; they never keep saved conversations animated.
const entering = new WeakMap();
export function markEntry(node, attribute = 'data-enter') {
  if (!node) return;
  entering.get(node)?.();
  node.setAttribute(attribute, '');
  let timer;
  const clear = (event) => {
    if (event && event.target !== node) return;
    clearTimeout(timer);
    node.removeAttribute(attribute);
    node.removeEventListener?.('animationend', clear);
    entering.delete(node);
  };
  entering.set(node, clear);
  node.addEventListener('animationend', clear);
  timer = setTimeout(clear, 400);
}

export function mountTranscript(log, doc) {
  if (log.dataset.transcriptMounted) return;
  log.dataset.transcriptMounted = 'true';
  const seen = new WeakSet();
  const sync = () => {
    const assistants = [...log.querySelectorAll('.chat-msg.is-assistant')];
    const first = assistants[0]?.querySelector('.chat-who');
    for (const label of log.querySelectorAll('.assistant-signature')) {
      if (label !== first) label.classList.remove('assistant-signature');
    }
    if (first) {
      first.classList.add('assistant-signature');
      const name = t('ui.identity.name', doc.documentElement.lang === 'en' ? 'City Assistant' : 'Şehir Asistanı');
      if (first.textContent !== name) first.textContent = name;
    }
    const current = assistants.find((node) => node.getAttribute('aria-busy') === 'true');
    const messages = [...log.querySelectorAll('.chat-msg')];
    const user = messages[messages.indexOf(current) - 1];
    if (user?.classList.contains('is-user') && !seen.has(user)) {
      seen.add(user);
      markEntry(user, 'data-message-enter');
    }
  };
  new MutationObserver(sync).observe(log, { childList: true, subtree: true });
  onLang(sync);
  doc.addEventListener('nabiz:chat-final', (event) => {
    const { host, final } = event.detail || {};
    if (!host || !log.contains(host) || final?.emergency) return;
    markEntry(host, 'data-answer-enter');
    host.querySelectorAll('.chat-card').forEach((card, index) => {
      card.style.setProperty('--i', String(Math.min(index, 2)));
      markEntry(card, 'data-card-enter');
    });
    sync();
  });
  sync();
}
