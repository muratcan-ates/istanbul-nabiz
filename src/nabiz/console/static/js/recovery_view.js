/* Pure state and markup for the source-backed digital access guide. */

import { currentLang, t } from './i18n_text.js';
import { esc } from './format.js';
import { icon } from './icons.js';

const STORAGE_KEY = 'nabiz.erisim.v1';
const KEEP_DAYS = 30;
/* Must match data/agencies.json call; tests keep the two values equal. */
const FALLBACK_CALL = '153';
const DAY_MS = 86_400_000;
const TEXT = {
  title: (vars) => t('ui.erisim.title', 'Uygulamaya ya da hesaba giremiyorum', vars),
  note: (vars) => t('ui.erisim.note', 'Denediğiniz adımları sırayla yazar; her adım kurumun resmî sayfasından. Hesabınıza erişemeyiz ve erişiminizi geri getiremeyiz.', vars),
  no_secrets: (vars) => t('ui.erisim.no_secrets', 'Nabız şifre, doğrulama kodu, kart numarası ya da T.C. kimlik numarası istemez. Bu bölümde bunları yazacağınız bir alan yok.', vars),
  remember: (vars) => t('ui.erisim.remember', 'Adımlarımı bu cihazda hatırla (sunucuya gitmez, 30 gün)', vars),
  trail: (vars) => t('ui.erisim.trail', 'Yanıtlarınız', vars),
  loading: (vars) => t('ui.erisim.loading', 'Adımlar yükleniyor.', vars),
  load_failed: (vars) => t('ui.erisim.load_failed', 'Adımlar şu an yüklenemedi. İnsanla konuşmak için 153\'ü arayabilirsiniz.', vars),
  step_status: (vars) => t('ui.erisim.step_status', 'Adım {n}: {question}', vars),
  tried_failed: (vars) => t('ui.erisim.tried_failed', 'Denedim, sorun sürüyor', vars),
  not_tried: (vars) => t('ui.erisim.not_tried', 'Henüz denemedim', vars),
  solved: (vars) => t('ui.erisim.solved', 'Sorun çözüldü', vars),
  solved_note: (vars) => t('ui.erisim.solved_note', 'Tamam. Bu cihazdaki adımlar silindi.', vars),
  back: (vars) => t('ui.erisim.back', 'Geri', vars),
  restart: (vars) => t('ui.erisim.restart', 'Baştan başla', vars),
  forget: (vars) => t('ui.erisim.forget', 'Bu cihazdan sil', vars),
  forgotten: (vars) => t('ui.erisim.forgotten', 'Bu cihazdaki adımlar silindi.', vars),
  official_says: (vars) => t('ui.erisim.official_says', 'Resmî sayfa ne diyor', vars),
  source_line: (vars) => t('ui.erisim.source_line', 'Kaynak: {source} · {host} · indirildi {date}', vars),
  open_page: (vars) => t('ui.erisim.open_page', 'Sayfayı aç', vars),
  gap_generic: (vars) => t('ui.erisim.gap_generic', 'Bu adım için resmî kaynak henüz yok.', vars),
  alt_title: (vars) => t('ui.erisim.alt_title', 'Uygulama olmadan', vars),
  handoff_ikart: (vars) => t('ui.erisim.handoff_ikart', 'İstanbulkart sorun giderme bölümüne gidin', vars),
  contact_title: (vars) => t('ui.erisim.contact_title', 'Kime başvurabilirsiniz', vars),
  contact_call: (vars) => t('ui.erisim.contact_call', 'Arayın: {call}', vars),
  contact_site: (vars) => t('ui.erisim.contact_site', '{agency} resmî sitesi', vars),
  summary_title: (vars) => t('ui.erisim.summary_title', 'Destek özeti', vars),
  summary_note: (vars) => t('ui.erisim.summary_note', 'Yalnız sizin yanıtlarınızdan oluşur; kurum doğrulaması değildir. Kopyalayıp destek hattına okuyabilir ya da yazabilirsiniz.', vars),
  summary_tr_note: (vars) => t('ui.erisim.summary_tr_note', 'Özet Türkçedir; destek hattı için.', vars),
  copy: (vars) => t('ui.erisim.copy', 'Özeti kopyala', vars),
  copied: (vars) => t('ui.erisim.copied', 'Kopyalandı.', vars),
  copy_failed: (vars) => t('ui.erisim.copy_failed', 'Kopyalanamadı; metin seçildi, kendiniz kopyalayın.', vars),
};

function ui(key, vars = {}) {
  return esc(TEXT[key](vars));
}
function emptyState() {
  return { version: 1, node: null, path: [], checks: {}, at: 0 };
}
function nextAfter(flows, nodeId, answer) {
  const node = flows.nodes[nodeId];
  if (!node) return null;
  if (node.kind === 'choice') return node.options.find((option) => option.id === answer)?.next || null;
  if (node.kind === 'check' && ['failed', 'not_tried', 'solved'].includes(answer)) return node.next;
  return null;
}
function skipNodes(flows, nodeId) {
  let next = nodeId;
  const visited = new Set();
  while (flows.nodes[next] && flows.nodes[next].kind === 'skip' && !visited.has(next)) {
    visited.add(next);
    next = flows.nodes[next].next;
  }
  return next;
}
function choose(flows, state, nodeId, answer, now = Date.now()) {
  if (!state || state.node !== nodeId || !flows.nodes[nodeId]) return state;
  const node = flows.nodes[nodeId];
  const next = nextAfter(flows, nodeId, answer);
  if (!next) return state;
  const path = [...state.path.map((entry) => ({ ...entry })), { node: nodeId, answer }];
  const checks = { ...state.checks };
  if (node.kind === 'check') checks[nodeId] = answer;
  return {
    version: 1,
    node: node.kind === 'check' && answer === 'solved' ? '__solved' : skipNodes(flows, next),
    path,
    checks,
    at: now,
  };
}
function back(flows, state) {
  if (!state || !state.path.length) return state;
  const path = state.path.slice(0, -1).map((entry) => ({ ...entry }));
  let rebuilt = { version: 1, node: flows.start, path: [], checks: {}, at: state.at };
  for (const entry of path) rebuilt = choose(flows, rebuilt, entry.node, entry.answer, state.at);
  return rebuilt;
}
function parseStored(raw, flows, now = Date.now()) {
  let value;
  try { value = JSON.parse(raw || 'null'); } catch { return null; }
  if (!value || value.version !== 1 || !Array.isArray(value.path) || !Number.isFinite(value.at)) return null;
  if (value.at < now - KEEP_DAYS * DAY_MS || !value.checks || typeof value.checks !== 'object' || Array.isArray(value.checks)) return null;
  let rebuilt = { ...emptyState(), node: flows.start, at: value.at };
  for (const entry of value.path) {
    if (!entry || typeof entry.node !== 'string' || typeof entry.answer !== 'string') return null;
    const next = choose(flows, rebuilt, entry.node, entry.answer, value.at);
    if (next === rebuilt) return null;
    rebuilt = next;
  }
  if (rebuilt.node !== value.node || JSON.stringify(rebuilt.checks) !== JSON.stringify(value.checks)) return null;
  return rebuilt;
}

function optionText(node, answer, lang) {
  if (node.kind === 'choice') return node.options.find((option) => option.id === answer)?.text?.[lang] || '';
  return ({
    failed: t('ui.erisim.tried_failed', 'Denedim, sorun sürüyor'),
    not_tried: t('ui.erisim.not_tried', 'Henüz denemedim'),
    solved: t('ui.erisim.solved', 'Sorun çözüldü'),
  })[answer] || '';
}

function trailMarkup(flows, state) {
  return state.path.map((entry) => {
    const node = flows.nodes[entry.node];
    if (!node) return '';
    return `<li><span>${esc(node.text.tr)}: ${esc(optionText(node, entry.answer, 'tr'))}</span></li>`;
  }).join('');
}

function safeHttps(value) {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && !url.username && !url.password ? value : '';
  } catch { return ''; }
}

function sourceDate(source) {
  const date = new Date(source?.fetched_at || '');
  return Number.isNaN(date.getTime()) ? '' : new Intl.DateTimeFormat('tr-TR', {
    timeZone: 'Europe/Istanbul', day: '2-digit', month: '2-digit', year: 'numeric',
  }).format(date);
}

function quoteMarkup(quote, source, lang) {
  if (!quote || !source) return '';
  const url = safeHttps(source.url);
  if (!url) return '';
  const exact = (quote.parts || []).map((part) => esc(part)).join(' … ');
  const name = source.label && source.label[lang] ? source.label[lang] : source.label?.tr || '';
  const sourceLine = ui('source_line', { source: name, host: source.host || '', date: sourceDate(source) });
  const link = `<a href="${esc(url)}" rel="noopener">${ui('open_page')}${icon('external-link')}</a>`;
  const turkish = lang === 'en' ? ` <span>${esc(t('quote.source_is_turkish', 'Kaynak metin Türkçedir.'))}</span>` : '';
  return `<figure class="erisim-quote"><blockquote lang="tr" cite="${esc(url)}"><p>${exact}</p></blockquote>`
    + `<figcaption class="erisim-source">${sourceLine} · ${link}${turkish}</figcaption></figure>`;
}

function quotesMarkup(flows, quoteIds, lang) {
  const figures = quoteIds.map((id) => quoteMarkup(flows.quotes[id], flows.sources[flows.quotes[id]?.source], lang)).filter(Boolean);
  if (!figures.length) return '';
  return `<div class="erisim-quotes"><h4>${ui('official_says')}</h4>${figures.join('')}</div>`;
}

function contactMarkup(contact, agencyId, lang) {
  const agency = contact?.agencies?.[agencyId];
  if (!agency) return '';
  const call = /^\d+$/.test(String(contact.call || '')) ? String(contact.call) : FALLBACK_CALL;
  const url = safeHttps(agency.url);
  const label = ui('contact_site', { agency: '__ERISIM_AGENCY__' }).replace(
    '__ERISIM_AGENCY__', `<span lang="tr">${esc(agency.name)}</span>`,
  );
  return `<div class="erisim-contact-block"><h4>${ui('contact_title')}</h4><ul class="erisim-contact">`
    + `<li><a class="btn" href="tel:${call}">${ui('contact_call', { call })}</a></li>`
    + (url ? `<li><a class="btn btn-quiet" href="${esc(url)}" rel="noopener">${label}${icon('external-link')}</a></li>` : '')
    + '</ul></div>';
}

function summaryText(flows, state, contact, now = Date.now()) {
  const summary = flows.summary;
  const path = state.path || [];
  const firstChoice = path.find((entry) => flows.nodes[entry.node]?.kind === 'choice');
  const firstNode = firstChoice && flows.nodes[firstChoice.node];
  const topic = firstNode ? optionText(firstNode, firstChoice.answer, 'tr') : '';
  const lines = [summary.title, `${summary.topic}: ${topic}`, `${summary.answers}:`];
  const usedQuoteIds = new Set();
  for (const entry of path) {
    const node = flows.nodes[entry.node];
    if (!node) continue;
    if (node.kind === 'choice') lines.push(`- ${node.text.tr}: ${optionText(node, entry.answer, 'tr')}`);
    for (const quoteId of [...(node.quotes || []), ...(node.alt || [])]) usedQuoteIds.add(quoteId);
  }
  lines.push(`${summary.checks}:`);
  const checks = path.filter((entry) => flows.nodes[entry.node]?.kind === 'check' && entry.answer !== 'solved');
  if (checks.length) {
    for (const entry of checks) {
      const node = flows.nodes[entry.node];
      const hosts = [...new Set((node.quotes || []).map((id) => flows.sources[flows.quotes[id]?.source]?.host).filter(Boolean))];
      lines.push(`- ${node.text.tr}: ${optionText(node, entry.answer, 'tr')} (${summary.sources}: ${hosts.join(', ')})`);
    }
  } else lines.push(summary.checks_none);
  const current = flows.nodes[state.node];
  if (current) {
    for (const quoteId of [...(current.quotes || []), ...(current.alt || [])]) usedQuoteIds.add(quoteId);
  }
  lines.push(`${summary.sources}:`);
  for (const quoteId of usedQuoteIds) {
    const sourceId = flows.quotes[quoteId]?.source;
    const url = flows.sources[sourceId]?.url;
    if (url) lines.push(`- ${url}`);
  }
  lines.push(summary.no_secrets, summary.not_verified, `${summary.made_by} · ${new Intl.DateTimeFormat('tr-TR', {
    timeZone: 'Europe/Istanbul', day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
  }).format(new Date(now))}`);
  return maskSummary(lines.join('\n'));
}

function maskSummary(text) {
  const protectedValues = [];
  const protect = (value) => `\uE000${protectedValues.push(value) - 1}\uE001`;
  let result = String(text).replace(/\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/gi, '[gizlendi]');
  result = result.replace(/(?<!\d)(?:\d{1,2}\.\d{1,2}\.\d{4}|\d{1,2}:\d{2})(?!\d)/g, protect);
  result = result.replace(/(?<!\d)(?:\d[\s-]*){9,}\d(?!\d)/g, '[gizlendi]');
  result = result.replace(/(?<!\d)(?:\d[\s-]*){3,7}\d(?!\d)/g, '[gizlendi]');
  return result.replace(/\uE000(\d+)\uE001/g, (_, index) => protectedValues[Number(index)]);
}

function summaryMarkup(text, lang) {
  const rows = Math.max(3, String(text).split('\n').length);
  const turkishNote = lang === 'en' ? `<p class="field-hint">${ui('summary_tr_note')}</p>` : '';
  return `<div class="erisim-summary"><h4>${ui('summary_title')}</h4><p class="field-hint">${ui('summary_note')}</p>${turkishNote}`
    + `<label for="erisim-summary" class="sr-only">${ui('summary_title')}</label>`
    + `<textarea id="erisim-summary" readonly rows="${rows}" lang="tr">${esc(text)}</textarea>`
    + `<button type="button" class="btn" data-erisim="copy">${ui('copy')}</button></div>`;
}

function sectionMarkup(flows, state, remember) {
  const checked = remember ? ' checked' : '';
  return `<details class="more tool-detail erisim" id="erisim-kurtar"><summary>${icon('chevron-right')}`
    + `<h2 id="erisim-title">${ui('title')}</h2></summary><section aria-labelledby="erisim-title">`
    + `<p class="section-note">${ui('note')}</p><p class="erisim-safe">${icon('shield-lock')}${ui('no_secrets')}</p>`
    + `<label class="erisim-remember"><input type="checkbox" id="erisim-remember"${checked}> <span class="erisim-remember-copy">${ui('remember')}</span></label>`
    + `<ol class="erisim-trail" aria-label="${ui('trail')}">${flows ? trailMarkup(flows, state) : ''}</ol>`
    + `<div class="erisim-step"><p class="status-line" role="status" aria-live="polite">${ui('loading')}</p></div>`
    + `<div class="erisim-tools"><button type="button" class="btn btn-quiet" data-erisim="back" hidden>${ui('back')}</button>`
    + `<button type="button" class="btn btn-quiet" data-erisim="restart" hidden>${ui('restart')}</button>`
    + `<button type="button" class="btn btn-quiet" data-erisim="forget"${remember ? '' : ' hidden'}>${ui('forget')}</button></div>`
    + `<p class="erisim-foot">${esc(t('ui.culture.disclaimer', 'Resmî İBB hizmeti değildir.'))}</p></section></details>`;
}

function stepMarkup(flows, state, lang = currentLang(), hasHandoff = false) {
  if (state.node === '__solved') {
    return `<div class="erisim-current"><h3 tabindex="-1" id="erisim-q">${ui('solved_note')}</h3>`
      + `<button type="button" class="btn btn-quiet" data-erisim="restart">${ui('restart')}</button>`
      + '<p class="status-line" role="status" aria-live="polite"></p></div>';
  }
  const node = flows.nodes[state.node];
  if (!node || node.kind === 'skip') return '<p class="status-line" role="status" aria-live="polite"></p>';
  let content = `<h3 tabindex="-1" id="erisim-q">${esc(node.text[lang] || node.text.tr)}</h3>`;
  content += quotesMarkup(flows, node.quotes || [], lang);
  if (node.kind === 'choice') {
    content += `<div class="erisim-options" role="group" aria-labelledby="erisim-q">`
      + node.options.map((option) => `<button type="button" class="btn" data-erisim-answer="${esc(option.id)}">${esc(option.text[lang] || option.text.tr)}</button>`).join('')
      + '</div>';
  } else if (node.kind === 'check') {
    content += '<div class="erisim-options" role="group" aria-labelledby="erisim-q">'
      + `<button type="button" class="btn" data-erisim-answer="failed">${ui('tried_failed')}</button>`
      + `<button type="button" class="btn" data-erisim-answer="not_tried">${ui('not_tried')}</button>`
      + `<button type="button" class="btn" data-erisim-answer="solved">${ui('solved')}</button></div>`;
  } else {
    if (node.gap) content += `<p class="erisim-gap">${esc(node.gap[lang] || node.gap.tr)}</p>`;
    if (node.unverified) content += `<p class="erisim-gap">${ui('gap_generic')}</p>`;
    if (node.alt?.length) {
      content += `<div class="erisim-alt"><h4>${ui('alt_title')}</h4>${quotesMarkup(flows, node.alt, lang)}`
        + `<p class="field-hint">${esc(flows.alt_note[lang] || flows.alt_note.tr)}</p></div>`;
    }
    if (node.handoff && hasHandoff) content += `<a class="btn btn-quiet" href="#kart-sorun">${ui('handoff_ikart')}</a>`;
    content += contactMarkup(flows.contact, node.agency, lang);
    content += summaryMarkup(summaryText(flows, state, flows.contact), lang);
  }
  return `<div class="erisim-current">${content}<p class="status-line" role="status" aria-live="polite"></p></div>`;
}

export {
  STORAGE_KEY, KEEP_DAYS, FALLBACK_CALL, emptyState, choose, back, parseStored,
  sectionMarkup, stepMarkup, quoteMarkup, contactMarkup, summaryText, maskSummary, summaryMarkup,
  trailMarkup,
};
