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
const citizenTurns = new WeakMap();
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

function memoryDisclosureText(root, doc) {
  const english = doc.documentElement.lang === 'en';
  const health = root.dataset.memoryHealth === 'true';
  const hint = root.querySelector('.memory-card-hint');
  const status = root.querySelector('.memory-card-status')?.textContent.trim();
  const choose = t('ui.memory.choose', english ? 'Select the items you want me to remember.' : 'Hatırlamamı istediğiniz satırları seçin.');
  const initialHints = [choose, 'Select the items you want me to remember.', 'Hatırlamamı istediğiniz satırları seçin.'];
  const failure = !health && hint && !hint.hidden && !initialHints.includes(hint.textContent.trim()) ? hint.textContent.trim() : '';
  const title = health ? t('ui.memory.healthAdd', english ? 'Add a health statement' : 'Sağlık beyanı ekle')
    : t('ui.memory.title', english ? 'Should I remember this?' : 'Hatırlayayım mı?');
  return { label: status || failure || title, note: health && hint ? hint.textContent.trim() : '',
    state: status ? 'result' : failure ? 'error' : health ? 'health' : 'pending' };
}

// Move existing consent controls as one unit; opening this disclosure performs no action.
export function syncMemoryDisclosures(log, doc) {
  for (const root of log.querySelectorAll('.memory-card')) {
    const target = root.closest('.chat-card[data-card-type="memory"]') || root;
    let details = target.closest('details.memory-disclosure');
    if (!details) {
      const focused = target.contains(doc.activeElement) ? doc.activeElement : null;
      details = doc.createElement('details'); details.className = 'memory-disclosure'; details.open = Boolean(focused);
      const summary = doc.createElement('summary'); summary.className = 'memory-disclosure-summary';
      const label = doc.createElement('span'); label.className = 'memory-disclosure-label';
      const note = doc.createElement('span'); note.className = 'memory-disclosure-note'; note.hidden = true;
      summary.append(label, note); target.before(details); details.append(summary, target);
      if (focused && doc.activeElement !== focused) focused.focus({ preventScroll: true });
    }
    const text = memoryDisclosureText(root, doc);
    const label = details.querySelector('.memory-disclosure-label');
    const note = details.querySelector('.memory-disclosure-note');
    if (label.textContent !== text.label) label.textContent = text.label;
    const noteText = text.note ? ` ${text.note}` : '';
    if (note.textContent !== noteText) note.textContent = noteText;
    if (note.hidden !== !text.note) note.hidden = !text.note;
    if (details.dataset.memoryState !== text.state) details.dataset.memoryState = text.state;
  }
}

// Completed-answer utilities keep their existing listeners and consent state.
export function syncAnswerDetails(log, doc) {
  const citizen = doc.body?.classList.contains('citizen-page');
  for (const shell of log.querySelectorAll('.chat-msg.is-assistant')) {
    if (shell.getAttribute('aria-busy') === 'true'
      || ['is-emergency', 'is-error'].some((name) => shell.classList.contains(name))
      || !citizen && shell.classList.contains('is-refused')) continue;
    const final = [...shell.children].find((node) => node.classList.contains('chat-final'));
    const answer = final && [...final.children].find((node) => node.matches(citizen ? '[data-citizen-answer]' : '.answer-card[data-card="answer"]'));
    const content = answer?.querySelector('.ac-details-content');
    const details = content?.closest('details.ac-details');
    if (!details || details.closest('.answer-card') !== answer) continue;
    const utilities = [...shell.children, ...final.children].filter((node) =>
      ['er-bar', 'feedback-slot', 'feedback', 'ac-next'].some((name) => node.classList.contains(name))
      || node.classList.contains('chat-tool') && node.classList.contains('is-done'));
    for (const node of utilities) {
      const focused = node.contains(doc.activeElement) ? doc.activeElement : null;
      if (focused) details.open = true;
      content.append(node);
      if (focused && doc.activeElement !== focused) focused.focus({ preventScroll: true });
    }
  }
}

// Clean display text only; saved history and the original evidence remain unchanged.
export function citizenText(value, { route = false, lang = 'tr', places = false } = {}) {
  const text = String(value ?? '');
  const footer = 'Kaynak: İBB Açık Veri (CC BY 4.0) · resmî bir servis değildir.';
  const rows = text.trim().split('\n');
  const legacyPlaces = rows.length > 2 && rows.at(-1) === footer && rows.at(-2).startsWith('Veri: kayıtlı · ')
    && rows.slice(0, -2).every((line) => /^• .+ \(.+\)(?:, | \u2014 )/.test(line));
  let points = false;
  const lines = text.split('\n').map((line) => {
    if (!places && !legacyPlaces) return line;
    const point = line.match(/^(\s*•\s+.+?)(?:\s+\u2014\s+|,\s+)([+-]?\d{1,3}[.,]\d{3,8}),\s+([+-]?\d{1,3}[.,]\d{3,8})\s*$/);
    if (!point || Math.abs(Number(point[2].replace(',', '.'))) > 90
      || Math.abs(Number(point[3].replace(',', '.'))) > 180) return line;
    points = true;
    return route ? '' : point[1];
  }).filter((line) => line !== 'Kaynak: İBB Açık Veri (CC BY 4.0) · resmî bir servis değildir.'
    && !/^Veri: kayıtlı · (?:0[1-9]|[12]\d|3[01])\.(?:0[1-9]|1[0-2]) (?:[01]\d|2[0-3]):[0-5]\d\.$/.test(line));
  if (route && points) lines.unshift(lang === 'en'
    ? 'I could not verify the directions for this journey.' : 'Bu yolculuğun güzergâhını henüz doğrulayamadım.');
  return lines.join('\n').trim();
}

function syncCitizenAnswers(log, doc) {
  if (!doc.body?.classList.contains('citizen-page')) return;
  const messages = [...log.querySelectorAll('.chat-msg')];
  for (const shell of messages) {
    if (!shell.classList.contains('is-assistant') || shell.getAttribute('aria-busy') === 'true'
      || ['is-emergency', 'is-refused', 'is-error'].some((name) => shell.classList.contains(name))) continue;
    const host = [...shell.children].find((node) => node.classList.contains('chat-final'));
    const turn = host && citizenTurns.get(host);
    const question = turn?.question || messages[messages.indexOf(shell) - 1]?.querySelector('.chat-text')?.textContent || '';
    const route = /nasıl\s+(?:giderim|gidebilirim|ulaşırım)|yol\s+tarifi|how (?:do i|can i) get/i.test(question);
    const paragraph = [...(host?.querySelector('[data-citizen-answer] .ac-short')?.children || [])]
      .find((node) => node.matches('p[data-er-target]'))
      || (!host && [...shell.children].find((node) => node.classList.contains('chat-text')));
    if (!paragraph) continue;
    const original = turn ? turn.final?.answer_text ?? turn.final?.answer : paragraph.textContent;
    // Structured steps and exact quotations belong to their original renderer.
    if (turn && (turn.final?.how?.citation_map || turn.final?.citations?.some((item) => item?.quote))) continue;
    const tools = turn?.final?.how?.tools || [turn?.final?.how];
    const places = turn?.final?.citations?.some((item) => item?.source === 'gazetteer')
      || Array.isArray(tools) && tools.some((tool) => (tool?.name || tool?.tool) === 'places_resolve');
    const clean = citizenText(original, { route, lang: doc.documentElement.lang, places });
    if (clean && clean !== paragraph.textContent) paragraph.textContent = clean;
  }
}

async function copyCitizenAnswer(button, doc) {
  const card = button.closest('[data-citizen-answer]');
  if (!card) return;
  const parts = [...card.querySelectorAll('.ac-short [data-er-target], .ac-short .quote-exact, .ac-short .ac-fixed, .ac-stale')];
  const text = parts.map((node) => node.textContent.trim()).filter(Boolean).join('\n');
  if (!text) return;
  const label = button.textContent;
  button.setAttribute('aria-busy', 'true');
  const english = doc.documentElement.lang === 'en';
  try {
    const clipboard = doc.defaultView?.navigator?.clipboard;
    if (!clipboard?.writeText) throw new Error('clipboard unavailable');
    await clipboard.writeText(text);
    button.textContent = t('dyn.copied', english ? 'Copied.' : 'Kopyalandı.');
  } catch {
    const status = doc.getElementById('chat-status');
    if (status) status.textContent = t('dyn.copy_failed', english
      ? 'Could not copy; select and copy the text.' : 'Kopyalanamadı; metni seçip kopyalayabilirsiniz.');
  } finally {
    button.removeAttribute('aria-busy');
    setTimeout(() => { if (button.isConnected) button.textContent = label; }, 2000);
  }
}

export function mountTranscript(log, doc) {
  if (log.dataset.transcriptMounted) return;
  log.dataset.transcriptMounted = 'true';
  const seen = new WeakSet();
  const sync = () => {
    syncCitizenAnswers(log, doc);
    syncMemoryDisclosures(log, doc);
    syncAnswerDetails(log, doc);
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
  new MutationObserver(sync).observe(log, { childList: true, subtree: true, characterData: true,
    attributes: true, attributeFilter: ['hidden', 'aria-busy'] });
  onLang(sync);
  log.addEventListener('click', (event) => {
    const button = event.target.closest?.('[data-citizen-copy]');
    if (button && doc.body?.classList.contains('citizen-page')) void copyCitizenAnswer(button, doc);
  });
  doc.addEventListener('nabiz:chat-final', (event) => {
    const { host, final } = event.detail || {};
    if (!host || !log.contains(host) || final?.emergency) return;
    citizenTurns.set(host, event.detail);
    markEntry(host, 'data-answer-enter');
    host.querySelectorAll('.chat-card').forEach((card, index) => {
      card.style.setProperty('--i', String(Math.min(index, 2)));
      markEntry(card, 'data-card-enter');
    });
    sync();
  });
  sync();
}
