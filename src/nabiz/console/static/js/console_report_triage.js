/* Read-only priority context for the citizen report already open in the operator's card. */

import { MOCK, get } from './api.js';
import { esc } from './format.js';
import { icon } from './icons.js';

let cachedItems = null;
let cachedAt = 0;
let pendingItems = null;

async function reportItems() {
  if (cachedItems && Date.now() - cachedAt < 30000) return cachedItems;
  if (!pendingItems) {
    pendingItems = get('/api/console/report-triage')
      .then((data) => {
        cachedItems = data.items || {};
        cachedAt = Date.now();
        return cachedItems;
      })
      .finally(() => { pendingItems = null; });
  }
  return pendingItems;
}

function safeAgencyUrl(raw) {
  try {
    const url = new URL(raw);
    return url.protocol === 'https:' ? url.href : '';
  } catch (error) {
    return '';
  }
}

export function triageMarkup(t) {
  const priority = t.priority || {};
  const level = ['high', 'medium', 'normal'].includes(priority.level) ? priority.level : 'normal';
  const tagClass = level === 'high' ? ' is-bad' : level === 'medium' ? ' is-warn' : '';
  const reasons = Array.isArray(priority.reasons) ? priority.reasons.map(esc).join(' · ') : '';
  const codes = Array.isArray(priority.codes) ? priority.codes : [];
  const codeText = Array.isArray(priority.code_text) ? priority.code_text : [];
  const escalation = codes.length
    ? `Eskalasyon: ${codes.map((code, index) => `<code>${esc(code)}</code> · ${esc(codeText[index] || '')}`).join(' · ')}`
    : 'Eskalasyon tetiği yok; kart R-10 kuralıyla insana geldi.';
  const agency = t.agency || {};
  const name = agency.name || '153 Çözüm Merkezi';
  const url = safeAgencyUrl(agency.url);
  const link = url
    ? ` · <a href="${esc(url)}" target="_blank" rel="noopener noreferrer">resmî sayfa${icon('external-link')}</a>`
    : '';
  return `<div class="decision-part report-triage" id="report-triage">
    <h4>Önceliklendirme (öneri)</h4>
    <p><span class="tag${tagClass}">${icon('alert-triangle')}Öncelik: ${esc(priority.label || 'Olağan')}</span>${reasons ? ` ${reasons}` : ''}</p>
    <p>${escalation}</p>
    <p>Önerilen kurum: <b>${esc(name)}</b> · neden: ${esc(agency.why || '')}${link}</p>
    <p class="section-note">${esc(t.note || 'Öneri. Nabız hiçbir ekibe iş atamaz; karar ve iletme İBB çalışanınındır.')}</p>
  </div>`;
}

async function attach(host) {
  if (MOCK || !host || host.querySelector('#report-triage')) return;
  const id = host.querySelector('.decision-meta span')?.textContent.trim();
  if (!id) return;
  try {
    const items = await reportItems();
    if (host.querySelector('#report-triage')) return;
    const currentId = host.querySelector('.decision-meta span')?.textContent.trim();
    const item = currentId === id ? items[id] : null;
    const firstPart = host.querySelector('.decision-part');
    if (item && firstPart) firstPart.insertAdjacentHTML('afterend', triageMarkup(item));
  } catch (error) {
    // A missing read-only panel does not block the decision card.
  }
}

function start() {
  const host = document.getElementById('decision-body');
  if (MOCK || !host) return;
  const observer = new MutationObserver(() => { void attach(host); });
  observer.observe(host, { childList: true });
  void attach(host);
}

start();
