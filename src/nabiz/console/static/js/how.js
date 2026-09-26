/* "Nasıl çalışır?" (/nasil.html): the five steps of a question, filled with this server's own numbers
 * from GET /api/how. No number is written here: every one comes from the answer, and when the answer
 * does not come (the route unbound, a 404, the network) every live slot says "durum doğrulanamadı".
 * Every server string goes through esc() or textContent. */

import { get } from './api.js';
import { esc } from './format.js';
import { AI_NOTICE } from './disclosure.js';

const LOADING = 'yükleniyor';
const UNVERIFIED = 'durum doğrulanamadı';
const ZONE = 'Europe/Istanbul';
const DAY = new Intl.DateTimeFormat('tr-TR', { day: 'numeric', month: 'long', year: 'numeric', timeZone: ZONE });
const DAY_ONLY = new Intl.DateTimeFormat('tr-TR', { day: 'numeric', timeZone: ZONE });
const MONTH_YEAR = new Intl.DateTimeFormat('tr-TR', { month: 'long', year: 'numeric', timeZone: ZONE });
const CLOCK = new Intl.DateTimeFormat('tr-TR', { hour: '2-digit', minute: '2-digit', timeZone: ZONE });

/* ---- formatting ------------------------------------------------------------------------ */

/* A bare date (2026-09-08) is read at noon UTC, so the Istanbul calendar day is the file's day. */
function toDate(iso) {
  if (!iso) return null;
  const date = new Date(/^\d{4}-\d{2}-\d{2}$/.test(iso) ? `${iso}T12:00:00Z` : iso);
  return Number.isNaN(date.getTime()) ? null : date;
}

function day(iso) {
  const date = toDate(iso);
  return date ? DAY.format(date) : null;
}

/* "8 ile 22 Eylül 2026 arası"; the month and year are written once when both days share them. */
function span(window) {
  const from = toDate(window && window.from);
  const to = toDate(window && window.to);
  if (!from || !to) return null;
  const head = MONTH_YEAR.format(from) === MONTH_YEAR.format(to) ? DAY_ONLY.format(from) : DAY.format(from);
  return `${head} ile ${DAY.format(to)} arası`;
}

function modeSuffix(mode) {
  return mode ? ` (${mode} koşu)` : '';
}

function metric(payload, key) {
  return (payload.metrics || []).find((row) => row.key === key) || null;
}

/* ---- step sentences -------------------------------------------------------------------- */

function rulesSentence(p) {
  const count = p.rules && p.rules.count;
  const defined = count === null || count === undefined
    ? `Şehir sinyalleri için NEXUS kural dosyalarındaki kural sayısı: ${UNVERIFIED}.`
    : `Şehir sinyalleri için NEXUS kural dosyalarında ${count} kural tanımlı.`;
  const engine = p.ledger && p.ledger.state === 'unverified' ? ' Karar çekirdeği bu süreçte bağlı değil.' : '';
  return `Acil durum, hak/ücret/ceza/sağlık sorusu ve fiyat cümlesi önce kuralla ayrılır. ${defined}${engine}`;
}

function indexText(index) {
  if (!index) return UNVERIFIED;
  if (!index.built) return index.label || UNVERIFIED;
  const built = day(index.built_at);
  return `${index.documents} belge, ${index.chunks} parça${built ? `, son kurulum ${built}` : ''}`;
}

function toolsSentence(p) {
  const count = p.tools && p.tools.count;
  const tools = count === null || count === undefined ? `Araç sayısı: ${UNVERIFIED}.` : `${count} araç İBB açık verisini okur;`;
  return `${tools} hizmet sorusu sayfa dizininden alıntıyla cevaplanır: ${indexText(p.index)}.`;
}

function verifySentence(p) {
  const row = metric(p, 'faithfulness');
  const head = 'Cevaptaki her sayı araç sonucunda aranır; bulunamayan sayı gösterilmez.';
  if (!row || row.status !== 'ölçüldü') return `${head} Son ölçüm: ölçülmedi.`;
  const when = day(row.measured_on);
  return `${head} Son ölçüm${modeSuffix(row.mode)}: ${row.display}${when ? `, ${when}` : ''}.`;
}

function ledgerText(ledger) {
  if (!ledger) return UNVERIFIED;
  if (ledger.state === 'ok') return `${ledger.entries} kayıt, zincir sağlam`;
  if (ledger.state === 'broken') return `zincir kayıt ${ledger.first_bad_id}'de bozuk`;
  return ledger.label || UNVERIFIED;
}

function cardSentence(p) {
  const author = (p.model && p.model.author_now) || UNVERIFIED;
  return `Cevap kaynağı, veri yaşı ve cevabı yazanla gelir. Şu an cevabı yazan: ${author}. Karar defteri: ${ledgerText(p.ledger)}.`;
}

/* ---- sections -------------------------------------------------------------------------- */

function organsMarkup(p) {
  if (!p.organs) return `<p>${esc(p.organs_label || UNVERIFIED)}</p>`;
  const organs = (p.organs.organs || []).map((o) => (
    `<li><b>${esc(o.name)}</b> <span class="tag">${esc(o.state_label)}</span> `
    + `<span class="how-muted">bugün ${esc(o.today_count)}</span></li>`
  )).join('');
  const loop = (p.organs.loop || []).map((l) => `<li>${esc(l.label)}: ${esc(l.count)}</li>`).join('');
  return `<ul class="how-list">${organs}</ul>${loop ? `<h3>Döngü</h3><ul class="how-list">${loop}</ul>` : ''}`;
}

function todayMarkup(items) {
  if (!items.length) return '<p>Bugün çalıştığı doğrulanan parça yok.</p>';
  return `<ul class="how-list">${items.map((item) => (
    `<li><b>${esc(item.label)}</b><br>${item.warn ? `<span class="tag is-warn">${esc(item.evidence)}</span>` : esc(item.evidence)}</li>`
  )).join('')}</ul>`;
}

function plannedMarkup(items) {
  if (!items.length) return '<p>Bu sunucuda bekleyen parça yok.</p>';
  return `<ul class="how-list">${items.map((item) => `<li><b>${esc(item.label)}</b><br>${esc(item.reason)}</li>`).join('')}</ul>`;
}

function metricDate(row) {
  const when = day(row.measured_on);
  const window = span(row.window);
  if (when && window) return `${when}; veri ${window}`;
  return when || '';
}

function metricRow(row) {
  const measured = row.status === 'ölçüldü';
  const status = measured
    ? '<span class="tag is-ok">ölçüldü</span>'
    : `<span class="tag is-warn">ölçülmedi</span> <span class="how-muted">${esc(row.reason)}</span>`;
  return `<tr><th scope="row">${esc(row.label)}${esc(modeSuffix(row.mode))}</th>`
    + `<td>${esc(measured ? row.display : '')}</td><td>${esc(row.n_display || '')}</td>`
    + `<td>${esc(metricDate(row))}</td><td>${esc(row.source_label)}</td><td>${status}</td></tr>`;
}

function metricsMarkup(p) {
  const rows = p.metrics || [];
  if (!rows.length) return `<tr><td colspan="6">${UNVERIFIED}</td></tr>`;
  return rows.map(metricRow).join('');
}

function openSourceMarkup(p) {
  const rows = p.open_source && p.open_source.rows;
  if (!rows) return `<tr><td colspan="2">${UNVERIFIED}</td></tr>`;
  return rows.map((row) => `<tr><td>${esc(row.component)}</td><td>${esc(row.license)}</td></tr>`).join('');
}

/* ---- slots ----------------------------------------------------------------------------- */

const TEXT_SLOTS = {
  rules: rulesSentence,
  tools: toolsSentence,
  verify: verifySentence,
  card: cardSentence,
};

const HTML_SLOTS = {
  organs: organsMarkup,
  today: (p) => todayMarkup((p.capabilities && p.capabilities.today) || []),
  planned: (p) => plannedMarkup((p.capabilities && p.capabilities.planned) || []),
  metrics: metricsMarkup,
  'open-source': openSourceMarkup,
};

function slot(name) {
  return document.querySelector(`[data-how="${name}"]`);
}

function checkedText(p) {
  const when = toDate(p.checked_at);
  return when ? `Son kontrol: ${DAY.format(when)} ${CLOCK.format(when)}.` : '';
}

/* One word for every slot: while loading, and again when the answer does not come. */
function fillAll(word) {
  for (const name of [...Object.keys(TEXT_SLOTS), 'checked']) {
    const el = slot(name);
    if (el) el.textContent = word;
  }
  for (const name of Object.keys(HTML_SLOTS)) {
    const el = slot(name);
    if (!el) continue;
    if (el.tagName === 'TBODY') el.innerHTML = `<tr><td colspan="${name === 'metrics' ? 6 : 2}">${esc(word)}</td></tr>`;
    else el.innerHTML = `<p>${esc(word)}</p>`;
  }
}

function render(p) {
  for (const [name, build] of Object.entries(TEXT_SLOTS)) {
    const el = slot(name);
    if (el) el.textContent = build(p);
  }
  for (const [name, build] of Object.entries(HTML_SLOTS)) {
    const el = slot(name);
    if (el) el.innerHTML = build(p);
  }
  const checked = slot('checked');
  if (checked) checked.textContent = checkedText(p);
}

function announce(text) {
  const status = document.querySelector('#how-status');
  if (status) status.textContent = text;
}

async function load() {
  fillAll(LOADING);
  announce('Sayılar yükleniyor.');
  try {
    const payload = await get('/api/how');
    render(payload || {});
    announce('Sayılar güncellendi.');
  } catch (err) {
    fillAll(UNVERIFIED);
    announce(`Sayılar alınamadı: ${UNVERIFIED}.`);
  }
}

function start() {
  const notice = document.querySelector('#how-ai-notice');
  if (notice) notice.textContent = AI_NOTICE;
  const refresh = document.querySelector('#how-refresh');
  if (refresh) refresh.addEventListener('click', load);
  load();
}

if (typeof document !== 'undefined') start();

export { rulesSentence, toolsSentence, verifySentence, cardSentence, metricRow, span, modeSuffix };
