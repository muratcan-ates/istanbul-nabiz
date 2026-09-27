/* Pure rendering and flow state for the İstanbulkart helper. */

import { currentLang, t } from './i18n_text.js';
import { esc } from './format.js';
import { icon } from './icons.js';

const STORAGE_KEY = 'nabiz.ikart.v1';
const KEEP_DAYS = 30;
/** Keep this fallback equal to data/agencies.json's shared call value. */
const FALLBACK_CALL = '153';
const ANSWERS = ['failed', 'not_tried', 'solved'];
const STORED_KEYS = ['version', 'node', 'path', 'when', 'checks', 'at'];

function emptyState() {
  return { version: 1, node: null, path: [], when: null, checks: {}, at: 0 };
}

function resolveSkips(flows, nodeId) {
  let next = nodeId;
  let count = 0;
  while (flows.nodes[next] && flows.nodes[next].kind === 'skip' && count < 7) {
    next = flows.nodes[next].next;
    count += 1;
  }
  return next;
}

function choose(flows, state, nodeId, answer, now = Date.now()) {
  const node = flows.nodes[nodeId];
  if (!node || state.node && state.node !== nodeId) return state;
  let next;
  let checks = state.checks;
  let when = state.when;
  if (node.kind === 'choice' && node.options.some((option) => option.id === answer)) {
    next = node.options.find((option) => option.id === answer).next;
  } else if (node.kind === 'check' && ANSWERS.includes(answer)) {
    next = answer === 'solved' ? '__solved' : node.next;
    checks = { ...state.checks, [nodeId]: answer };
  } else if (node.kind === 'when' && validWhen(answer)) {
    next = node.next;
    when = answer;
  } else {
    return state;
  }
  return {
    ...state, node: next === '__solved' ? next : resolveSkips(flows, next), when, checks,
    path: [...state.path, { node: nodeId, answer }], at: now,
  };
}

function back(flows, state) {
  if (!state.path.length) return state;
  const path = state.path.slice(0, -1);
  let restored = { ...emptyState(), node: flows.start, at: state.at };
  for (const item of path) restored = choose(flows, restored, item.node, item.answer, state.at);
  return { ...restored, at: state.at };
}

function validWhen(value) {
  if (value === null) return true;
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)) return false;
  const [year, month, day, hour, minute] = value.split(/[-T:]/).map(Number);
  const date = new Date(0);
  date.setUTCFullYear(year, month - 1, day);
  date.setUTCHours(hour, minute, 0, 0);
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1
    && date.getUTCDate() === day && date.getUTCHours() === hour && date.getUTCMinutes() === minute;
}

function parseStored(raw, flows, now = Date.now()) {
  let value;
  try { value = JSON.parse(raw || 'null'); } catch { return null; }
  if (!value || typeof value !== 'object' || Array.isArray(value)
    || Object.keys(value).sort().join('|') !== [...STORED_KEYS].sort().join('|')
    || value.version !== 1 || !Number.isFinite(value.at) || value.at > now
    || now - value.at >= KEEP_DAYS * 86_400_000 || !Array.isArray(value.path)
    || !validWhen(value.when) || !value.checks || typeof value.checks !== 'object' || Array.isArray(value.checks)) return null;
  let rebuilt = { ...emptyState(), node: flows.start, at: value.at };
  for (const item of value.path) {
    if (!item || Object.keys(item).sort().join('|') !== 'answer|node' || rebuilt.node !== item.node) return null;
    const next = choose(flows, rebuilt, item.node, item.answer, value.at);
    if (next === rebuilt) return null;
    rebuilt = next;
  }
  if (rebuilt.node !== value.node || rebuilt.when !== value.when
    || JSON.stringify(rebuilt.checks) !== JSON.stringify(value.checks)) return null;
  return { ...rebuilt, at: value.at };
}

function dateLabel(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value || '');
  return match ? `${match[3]}.${match[2]}.${match[1]}` : '';
}

function inputNow() {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Europe/Istanbul', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(new Date());
  const part = (name) => parts.find((item) => item.type === name)?.value || '00';
  return `${part('year')}-${part('month')}-${part('day')}T${part('hour')}:${part('minute')}`;
}

function quoteMarkup(quote, source, lang) {
  if (!quote || !source || !/^https:\/\//.test(source.url || '')) return '';
  const pageDate = source.page_date ? dateLabel(source.page_date) : t('ui.ikart.date_unknown', 'duyuru tarihi dizinde yok');
  const fetchedDate = dateLabel(source.fetched_at);
  const text = quote.parts.map((part) => esc(part)).join(' … ');
  const foreignNote = lang === 'en' ? ` <span>${esc(t('quote.source_is_turkish', 'Kaynak metin Türkçedir.'))}</span>` : '';
  const line = t('ui.ikart.source_line', 'Kaynak: {source} · {host} · duyuru {page_date} · indirildi {date}', {
    source: '{source}', host: '{host}', page_date: '{page_date}', date: '{date}',
  });
  const sourceLine = line.split('{source}');
  const lineTail = sourceLine[1].replace('{host}', esc(source.host || ''))
    .replace('{page_date}', esc(pageDate)).replace('{date}', esc(fetchedDate));
  return `<figure class="ikart-quote"><h4>${esc(t('ui.ikart.official_says', 'Resmî duyuru ne diyor'))}</h4>`
    + `<blockquote lang="tr" cite="${esc(source.url)}"><p>${text}</p></blockquote>`
    + `<figcaption class="ikart-source">${esc(sourceLine[0])}<span lang="tr">${esc(source.name)}</span>${lineTail} · `
    + `<a href="${esc(source.url)}" rel="noopener">${esc(t('ui.ikart.open_page', 'Duyuruyu aç'))}${icon('external-link')}</a>${foreignNote}</figcaption></figure>`;
}

function usedQuoteMarkup(flows, node, lang) {
  return (node.quotes || []).map((id) => quoteMarkup(flows.quotes[id], flows.sources[flows.quotes[id]?.source], lang)).join('');
}

function contactMarkup(contact, lang) {
  const call = String(contact?.call || FALLBACK_CALL).replace(/\D/g, '');
  const url = /^https:\/\//.test(contact?.agency?.url || '') ? contact.agency.url : '';
  const sitePhrase = t('ui.ikart.contact_site', '{agency} resmî sitesi', { agency: '{agency}' }).split('{agency}');
  const agencyText = `${esc(sitePhrase[0])}<span lang="tr">${esc(contact?.agency?.name || '')}</span>${esc(sitePhrase[1] || '')}`;
  const site = url ? `<li><a class="btn btn-quiet" href="${esc(url)}" rel="noopener">${agencyText}${icon('external-link')}</a></li>` : '';
  return `<section class="ikart-contact-block" lang="${lang}" aria-labelledby="ikart-contact-title"><h4 id="ikart-contact-title">${esc(t('ui.ikart.contact_title', 'Kime başvurabilirsiniz'))}</h4>`
    + `<ul class="ikart-contact"><li><a class="btn" href="tel:${call}">${esc(t('ui.ikart.contact_call', 'Arayın: {call}', { call }))}</a></li>${site}</ul></section>`;
}

function nodeAnswerText(flows, item) {
  const node = flows.nodes[item.node];
  if (!node) return '';
  if (node.kind === 'choice') return node.options.find((option) => option.id === item.answer)?.text.tr || '';
  if (node.kind === 'check') return item.answer === 'failed'
    ? flows.summary.failed : item.answer === 'not_tried' ? flows.summary.not_tried : '';
  if (node.kind === 'when') return item.answer ? item.answer.replace('T', ' ') : flows.summary.when_none;
  return '';
}

function summaryText(flows, state, contact, now = Date.now()) {
  const lines = [flows.summary.title];
  const topic = state.path.find((item) => item.node === flows.start);
  const topicNode = flows.nodes[flows.start];
  const topicText = topicNode?.options?.find((item) => item.id === topic?.answer)?.text.tr || flows.summary.when_none;
  lines.push(`${flows.summary.topic}: ${topicText}`, `${flows.summary.answers}:`);
  for (const item of state.path.filter((entry) => flows.nodes[entry.node]?.kind === 'choice')) {
    lines.push(`- ${flows.nodes[item.node].text.tr}: ${nodeAnswerText(flows, item)}`);
  }
  const entered = state.when ? `${dateLabel(state.when.slice(0, 10))} ${state.when.slice(11)}` : flows.summary.when_none;
  lines.push(`${flows.summary.when}: ${entered}`, `${flows.summary.checks}:`);
  const sourceIds = new Set();
  const checkRows = state.path.filter((item) => flows.nodes[item.node]?.kind === 'check' && item.answer !== 'solved');
  for (const item of checkRows) {
    const node = flows.nodes[item.node];
    const quote = (node.quotes || []).map((id) => flows.quotes[id]).find(Boolean);
    const sourceId = quote?.source;
    const source = sourceId ? flows.sources[sourceId] : null;
    if (sourceId) sourceIds.add(sourceId);
    const provenance = source ? ` (${source.host}, duyuru ${dateLabel(source.page_date) || flows.summary.when_none})` : '';
    lines.push(`- ${node.text.tr}: ${nodeAnswerText(flows, item)}${provenance}`);
  }
  if (!checkRows.length) lines.push(flows.summary.checks_none);
  lines.push(`${flows.summary.sources}:`);
  for (const sourceId of sourceIds) lines.push(flows.sources[sourceId].url);
  lines.push(flows.summary.no_secrets, flows.summary.not_verified);
  const date = new Intl.DateTimeFormat('tr-TR', { timeZone: 'Europe/Istanbul', dateStyle: 'short', timeStyle: 'short' }).format(now);
  lines.push(`${flows.summary.made_by} · ${date}`);
  return maskSummary(lines.join('\n'));
}

function maskSummary(text) {
  return String(text)
    .replace(/\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/gi, '[gizlendi]')
    .replace(/(?<!\d)(?:\d[ -]?){9,}\d(?!\d)/g, '[gizlendi]');
}

function summaryMarkup(text, lang) {
  const note = esc(t('ui.ikart.summary_note', 'Yalnız sizin yanıtlarınızdan oluşur; kurum doğrulaması değildir. Kopyalayıp destek hattına okuyabilir ya da yazabilirsiniz.'));
  const languageNote = lang === 'en' ? `<p class="field-hint">${esc(t('ui.ikart.summary_tr_note', 'Özet Türkçedir; destek hattı için.'))}</p>` : '';
  return `<section class="ikart-summary" aria-labelledby="ikart-summary-title"><h4 id="ikart-summary-title">${esc(t('ui.ikart.summary_title', 'Destek özeti'))}</h4>`
    + `<p class="field-hint">${note}</p>${languageNote}<label class="sr-only" for="ikart-summary">${esc(t('ui.ikart.summary_title', 'Destek özeti'))}</label>`
    + `<textarea id="ikart-summary" readonly rows="${Math.max(4, String(text).split('\n').length)}" lang="tr">${esc(text)}</textarea>`
    + `<button type="button" class="btn" data-ikart="copy">${esc(t('ui.ikart.copy', 'Özeti kopyala'))}</button></section>`;
}

function stepMarkup(flows, state, lang = currentLang()) {
  if (state.node === '__solved') return `<h3 tabindex="-1" id="ikart-q">${esc(t('ui.ikart.solved_note', 'Tamam. Bu cihazdaki adımlar silindi.'))}</h3>`;
  const node = flows.nodes[state.node];
  if (!node) return `<p>${esc(t('ui.ikart.loading', 'Adımlar yükleniyor.'))}</p>`;
  const question = esc(node.text[lang] || node.text.tr);
  let content = `<h3 tabindex="-1" id="ikart-q">${question}</h3>${usedQuoteMarkup(flows, node, lang)}`;
  if (node.kind === 'choice') {
    content += '<div class="ikart-options" role="group" aria-labelledby="ikart-q">'
      + node.options.map((option) => `<button type="button" class="btn" data-ikart-answer="${esc(option.id)}">${esc(option.text[lang] || option.text.tr)}</button>`).join('') + '</div>';
  } else if (node.kind === 'check') {
    content += '<div class="ikart-options" role="group" aria-labelledby="ikart-q">'
      + `<button type="button" class="btn" data-ikart-answer="failed">${esc(t('ui.ikart.tried_failed', 'Denedim, sorun sürüyor'))}</button>`
      + `<button type="button" class="btn" data-ikart-answer="not_tried">${esc(t('ui.ikart.not_tried', 'Henüz denemedim'))}</button>`
      + `<button type="button" class="btn" data-ikart-answer="solved">${esc(t('ui.ikart.solved', 'Sorun çözüldü'))}</button></div>`;
  } else if (node.kind === 'when') {
    content += `<input type="datetime-local" id="ikart-when" aria-labelledby="ikart-q" max="${inputNow()}" value="${esc(state.when || '')}">`
      + `<p class="field-hint">${esc(t('ui.ikart.when_hint', 'İsteğe bağlı. Özette "kullanıcı girdi" diye yazılır.'))}</p>`
      + `<div class="ikart-options"><button type="button" class="btn" data-ikart="next">${esc(t('ui.ikart.next', 'Devam'))}</button>`
      + `<button type="button" class="btn btn-quiet" data-ikart="skip">${esc(t('ui.ikart.skip', 'Atla'))}</button></div>`;
  } else if (node.kind === 'end') {
    if (node.gap) content += `<p class="ikart-gap">${esc(node.gap[lang] || node.gap.tr)}</p>`;
    if (node.unverified) content += `<p class="ikart-gap">${esc(t('ui.ikart.gap_generic', 'Bu adım için resmî kaynak henüz yok.'))}</p>`;
    content += contactMarkup(flows.contact, lang) + summaryMarkup(summaryText(flows, state, flows.contact), lang);
  }
  return content;
}

function trailMarkup(flows, state, lang) {
  return state.path.map((item) => {
    const node = flows.nodes[item.node];
    return `<li><span>${esc(node?.text[lang] || node?.text.tr || '')}</span>: ${esc(nodeAnswerText(flows, item))}</li>`;
  }).join('');
}

function sectionMarkup(flows, state, remember, phase = 'ready') {
  const lang = currentLang();
  let step;
  if (phase === 'loading') step = `<p>${esc(t('ui.ikart.loading', 'Adımlar yükleniyor.'))}</p>`;
  else if (phase === 'failed') step = `<p>${esc(t('ui.ikart.load_failed', 'Adımlar şu an yüklenemedi. İnsanla konuşmak için 153\'ü arayabilirsiniz.'))}</p>`
    + `<a class="btn" href="tel:${FALLBACK_CALL}">${esc(t('ui.ikart.contact_call', 'Arayın: {call}', { call: FALLBACK_CALL }))}</a>`;
  else step = stepMarkup(flows, state, lang);
  const trail = flows ? trailMarkup(flows, state, lang) : '';
  const backButton = state.path.length ? `<button type="button" class="btn btn-quiet" data-ikart="back">${esc(t('ui.ikart.back', 'Geri'))}</button>` : '';
  const forgetButton = remember ? `<button type="button" class="btn btn-quiet" data-ikart="forget">${esc(t('ui.ikart.forget', 'Bu cihazdan sil'))}</button>` : '';
  return `<details class="more tool-detail ikart" id="kart-sorun"><summary>${icon('chevron-right')}<h2 id="ikart-title">${esc(t('ui.ikart.title', 'İstanbulkart sorun giderme'))}</h2></summary>`
    + `<section aria-labelledby="ikart-title"><p class="section-note">${esc(t('ui.ikart.note', 'Sorununuzu birkaç soruyla daraltır; adımlar İstanbulkart\'ın resmî duyurularından. Kartınızın bakiyesini ve hareketlerini göremeyiz.'))}</p>`
    + `<p class="ikart-safe">${icon('shield-lock')}${esc(t('ui.ikart.no_secrets', 'Nabız şifre, doğrulama kodu ya da kart numarası istemez.'))}</p>`
    + `<label class="ikart-remember"><input type="checkbox" id="ikart-remember"${remember ? ' checked' : ''}> ${esc(t('ui.ikart.remember', 'Adımlarımı bu cihazda hatırla (sunucuya gitmez, 30 gün)'))}</label>`
    + `<ol class="ikart-trail" aria-label="${esc(t('ui.ikart.trail', 'Yanıtlarınız'))}">${trail}</ol><div class="ikart-step"${phase === 'loading' ? ' aria-busy="true"' : ''}>${step}</div>`
    + '<p class="status-line" role="status" aria-live="polite" aria-atomic="true"></p>'
    + `<div class="ikart-actions">${backButton}<button type="button" class="btn btn-quiet" data-ikart="restart">${esc(t('ui.ikart.restart', 'Baştan başla'))}</button>${forgetButton}</div>`
    + `<p class="ikart-foot">${esc(t('ui.culture.disclaimer', 'Resmî İBB hizmeti değildir.'))}</p></section></details>`;
}

export {
  STORAGE_KEY, KEEP_DAYS, FALLBACK_CALL, emptyState, choose, back, parseStored,
  sectionMarkup, stepMarkup, quoteMarkup, contactMarkup, summaryText, maskSummary, summaryMarkup,
};
