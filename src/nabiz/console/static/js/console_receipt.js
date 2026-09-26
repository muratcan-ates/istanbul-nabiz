/* Read the service ledger without changing its disclosure state or moving keyboard focus. */

import { MOCK, get } from './api.js';
import { REFRESH_MS } from './config.js';
import { errorCard } from './cards.js';
import { clock, esc, int, num } from './format.js';
import { icon } from './icons.js';

const ICONS = {
  gauge: icon('gauge'),
  alertTriangle: icon('alert-triangle'),
  cloudOff: icon('cloud-off'),
  bolt: icon('bolt'),
  arrowsExchange: icon('arrows-exchange'),
};

function makeSection() {
  const main = document.querySelector('#main');
  if (!main) return null;
  const existing = document.querySelector('#service-receipt');
  if (existing) return existing;
  const section = document.createElement('section');
  section.id = 'service-receipt';
  section.className = 'receipt-strip';
  section.setAttribute('aria-labelledby', 'receipt-title');
  section.innerHTML = `
    <h2 id="receipt-title">Hizmet makbuzu</h2>
    <p class="section-note">Her iş bir makbuz bırakır: sonuç, yol, süre, model çağrısı, maliyet. Kişi bazında metrik yok.</p>
    <p id="receipt-line" class="receipt-line"></p>
    <span id="receipt-badge"></span>
    <p id="receipt-status" class="sr-only" role="status"></p>
    <p id="receipt-price" class="receipt-price"></p>
    <details id="receipt-details">
      <summary>Son makbuzlar (0)</summary>
      <div id="receipt-table-host"></div>
    </details>
    <div id="receipt-message"></div>`;
  const anchor = main.querySelector('section[aria-labelledby="stats-title"]');
  if (anchor) anchor.before(section);
  else main.prepend(section);
  return section;
}

/* The last markup each host received: a browser re-serialises innerHTML (entities, SVG attributes),
   so comparing against it would rewrite unchanged content on every refresh and move focus. */
const drawn = new WeakMap();

function setHTML(host, html) {
  if (!host || drawn.get(host) === html) return;
  host.innerHTML = html;
  drawn.set(host, html);
}

function tableMarkup(rows) {
  if (!rows.length) return '<p class="section-note">Henüz makbuz yok. "Kayıtlı sinyali oynat" ile bir sinyal geçirin.</p>';
  const body = rows.map((row) => {
    const pathIcon = row.path === 'reflex' ? ICONS.bolt : row.path === 'arena' ? ICONS.arrowsExchange : '';
    const cost = row.usd == null ? 'fiyat tanımsız' : `${num(row.usd, 4)} $ (tahmin)`;
    return `<tr>
      <th scope="row">${esc(clock(row.at))}</th>
      <td data-label="Sinyal">${esc(row.title)}</td>
      <td data-label="Sonuç">${esc(row.result_label)}</td>
      <td data-label="Yol">${pathIcon} ${esc(row.path_label)}</td>
      <td data-label="Süre">${esc(num(row.wall_ms, 1))} ms</td>
      <td data-label="Model çağrısı">${esc(int(row.llm_calls))}</td>
      <td data-label="Maliyet">${esc(cost)}</td>
    </tr>`;
  }).join('');
  return `<table class="receipt-table">
    <caption class="sr-only">Son hizmet makbuzları, en yenisi üstte</caption>
    <thead><tr><th scope="col">Saat</th><th scope="col">Sinyal</th><th scope="col">Sonuç</th><th scope="col">Yol</th><th scope="col">Süre</th><th scope="col">Model çağrısı</th><th scope="col">Maliyet</th></tr></thead>
    <tbody>${body}</tbody>
  </table>`;
}

function renderSpend(section, result) {
  const line = section.querySelector('#receipt-line');
  const badgeHost = section.querySelector('#receipt-badge');
  const live = section.querySelector('#receipt-status');
  const price = section.querySelector('#receipt-price');
  const message = section.querySelector('#receipt-message');
  if (result.status === 'rejected') {
    setHTML(line, '');
    setHTML(badgeHost, '');
    setHTML(price, '');
    setHTML(message, errorCard('Hizmet makbuzu okunamadı', result.reason.message));
    if (live.textContent !== '') live.textContent = '';
    return;
  }
  setHTML(message, '');
  const spend = result.value;
  setHTML(line, `${ICONS.gauge} ${esc(spend.line)}`);
  const badge = spend.badge;
  const badgeIcon = badge && badge.level === 'warn' ? ICONS.alertTriangle : ICONS.cloudOff;
  const badgeClass = badge && badge.level === 'warn' ? 'is-warn' : 'is-bad';
  setHTML(badgeHost, badge ? `<span class="tag ${badgeClass}">${badgeIcon} ${esc(badge.text)}</span>` : '');
  const sentence = badge ? badge.text : 'Model tavanı içinde.';
  if (live.textContent !== sentence) live.textContent = sentence;
  const authors = spend.authors
    ? `Cevabı yazan bugün: model ${int(spend.authors.model)} · yerel model ${int(spend.authors['yerel model'])} · kural ${int(spend.authors.kural)}`
    : `Cevabı yazan dağılımı: ${esc(spend.authors_note || 'bağlanmadı')}`;
  setHTML(price, `${esc(spend.price_note)}. ${authors}`);
}

function renderReceipts(section, result) {
  const details = section.querySelector('#receipt-details');
  const summary = details.querySelector('summary');
  const host = section.querySelector('#receipt-table-host');
  if (result.status === 'rejected') {
    summary.textContent = 'Son makbuzlar (0)';
    setHTML(host, result.reason.status === 503
      ? '<p class="section-note">Karar çekirdeği bağlı değil; makbuz yok.</p>'
      : errorCard('Makbuzlar okunamadı', result.reason.message));
    return;
  }
  const rows = result.value.receipts || [];
  const label = `Son makbuzlar (${rows.length})`;
  if (summary.textContent !== label) summary.textContent = label;
  setHTML(host, tableMarkup(rows));
}

async function load(section) {
  const message = section.querySelector('#receipt-message');
  if (MOCK) {
    setHTML(message, '<p class="section-note">Örnek veri modunda hizmet makbuzu gösterilmez.</p>');
    return;
  }
  setHTML(message, '');
  const results = await Promise.allSettled([
    get('/api/console/spend'),
    get('/api/console/receipts', { limit: 20 }),
  ]);
  renderSpend(section, results[0]);
  renderReceipts(section, results[1]);
}

const section = makeSection();
let timer = null;

if (section) {
  const stop = () => { clearInterval(timer); timer = null; };
  const start = () => {
    stop();
    if (document.visibilityState === 'hidden') return;
    load(section);
    timer = setInterval(() => load(section), REFRESH_MS);
  };
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') stop();
    else start();
  });
  document.addEventListener('nabiz:decided', () => load(section));
  start();
}
