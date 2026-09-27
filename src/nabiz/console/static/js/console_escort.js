/* Operator queue for support files. It reads only on entry, its own actions, and a decision event. */

import { MOCK, get, post } from './api.js';
import { esc } from './format.js';

const STYLESHEET = '/css/console_escort.css';
const LABELS = { received: 'Alındı', seen: 'Görüldü', referred_official: 'Resmî kanala yönlendirildi', closed: 'Kapatıldı', cancelled: 'İptal edildi' };
const NEEDS = { wheelchair: 'Tekerlekli sandalye', walking_difficulty: 'Yürümekte zorlanma', low_vision: 'Az görme', hearing: 'İşitme', cognitive: 'Bilişsel destek', other: 'Diğer' };
const SUPPORT = {
  meet_at_entrance: 'Girişte buluşma', guide_inside_station: 'İstasyon içinde yön bulma', boarding_alighting: 'Araca binme veya inme',
  transfer: 'Aktarma', step_free_route_check: 'Adımsız yolu kontrol etme',
};
const MOVES = {
  received: ['seen'], seen: ['referred_official', 'closed'], referred_official: ['closed'], closed: [], cancelled: [],
};
const DESTINATIONS = {
  seen: { tr: 'Gördüm', en: 'Seen' },
  referred_official: { tr: 'Resmî kanala yönlendir', en: 'Refer to official channel' },
  closed: { tr: 'Kapat', en: 'Close' },
};

const language = (doc) => doc?.documentElement?.lang === 'en' ? 'en' : 'tr';
const moveNames = (status) => [...(MOVES[status] || [])];
export function movesFor(status) { return moveNames(status); }

function safeUrl(value) {
  try { const url = new URL(value); return url.protocol === 'https:' ? url.href : ''; } catch (error) { return ''; }
}

function endTime(start, minutes) {
  const [hour, minute] = String(start || '00:00').split(':').map(Number);
  return `${String(Math.floor((hour * 60 + minute + Number(minutes || 0)) / 60) % 24).padStart(2, '0')}:${String((minute + Number(minutes || 0)) % 60).padStart(2, '0')}`;
}

function statusName(status) { return LABELS[status] || 'Bilinmiyor'; }

function summaryMarkup(row) {
  const values = (row.summary || []).map((line) => `<li>${esc(line)}</li>`).join('');
  const note = row.note_masked ? `<p><b>Vatandaş yazdı (maskeli):</b> ${esc(row.note_masked)}</p>` : '';
  const count = Number(row.masked_count || 0) > 0 ? `<p>${Number(row.masked_count)} öğe maskelendi.</p>` : '';
  const history = (row.history || []).map((item) => `<li><span>${esc(statusName(item.status))}</span><time datetime="${esc(item.at)}">${esc(item.at)}</time>${item.note_masked ? `<p>${esc(item.note_masked)}</p>` : ''}</li>`).join('');
  return `<section class="console-escort-detail"><h3>Talep dosyası</h3><ul class="console-escort-summary">${values}</ul>${note}${count}<h4>Geçmiş</h4><ol class="console-escort-history">${history}</ol></section>`;
}

function moveForm(row, agencies, move, index, lang) {
  const first = index === 0, label = DESTINATIONS[move]?.[lang] || DESTINATIONS[move]?.tr || move;
  if (move === 'referred_official') {
    const options = (agencies || []).map((agency) => `<option value="${esc(agency.id)}" ${agency.id === 'cozum_153' ? 'selected' : ''}>${esc(agency.name)}</option>`).join('');
    return `<div class="console-escort-action"><label for="escort-agency-${esc(row.code)}">Kurum</label><select id="escort-agency-${esc(row.code)}" data-agency>${options}</select><button type="button" class="btn ${first ? 'btn-primary' : ''}" data-action="move" data-to="${move}" data-code="${esc(row.code)}">${esc(label)}</button></div>`;
  }
  if (move === 'closed') {
    return `<div class="console-escort-action"><button type="button" class="btn ${first ? 'btn-primary' : ''}" data-action="show-close" data-code="${esc(row.code)}">${esc(label)}</button><div class="console-escort-close" data-close-fields hidden><label for="escort-close-${esc(row.code)}">Kapatma notu (vatandaş bu notu görür)</label><textarea id="escort-close-${esc(row.code)}" maxlength="200" rows="2" data-close-note></textarea><button type="button" class="btn ${first ? 'btn-primary' : ''}" data-action="move" data-to="closed" data-code="${esc(row.code)}">Kapat</button><p data-inline-error role="alert" hidden></p></div></div>`;
  }
  return `<button type="button" class="btn ${first ? 'btn-primary' : ''}" data-action="move" data-to="${move}" data-code="${esc(row.code)}">${esc(label)}</button>`;
}

/** One expandable table row. The controls exist only for moves allowed from its current state. */
export function rowMarkup(row, agencies = [], expanded = false, lang = 'tr') {
  const start = row.time || '', finish = endTime(start, row.window_min);
  const details = `<tr id="escort-detail-${esc(row.code)}" class="console-escort-expanded" ${expanded ? '' : 'hidden'}><td colspan="5">${expanded ? `${summaryMarkup(row)}<div class="console-escort-moves">${movesFor(row.status).map((move, index) => moveForm(row, agencies, move, index, lang)).join('')}</div>` : ''}</td></tr>`;
  const toggle = `<button type="button" class="console-escort-toggle" aria-expanded="${Boolean(expanded)}" aria-controls="escort-detail-${esc(row.code)}" data-action="toggle" data-code="${esc(row.code)}">${esc(row.code)}</button>`;
  const need = NEEDS[row.need] || row.summary?.[0] || 'Bilinmiyor';
  return `<tr data-code="${esc(row.code)}"><td>${toggle}</td><td>${esc(row.date)} ${esc(start)}-${esc(finish)}</td><td>${esc(row.meet_station)} → ${esc(row.to_station)}</td><td>${esc(need)}</td><td>${esc(statusName(row.status))}</td></tr>${details}`;
}

function tableMarkup(items, agencies, openCode, lang) {
  const rows = items.map((row) => rowMarkup(row, agencies, row.code === openCode, lang)).join('');
  const empty = lang === 'en' ? 'No support requests have been submitted.' : 'Henüz destek talebi gönderilmedi.';
  return `<div class="console-escort-scroll" role="region" tabindex="0" aria-label="Refakat talepleri tablosu"><table><thead><tr><th scope="col">Kod</th><th scope="col">Tarih ve aralık</th><th scope="col">Buluşma ve varış</th><th scope="col">İhtiyaç</th><th scope="col">Durum</th></tr></thead><tbody>${rows || `<tr><td colspan="5" class="console-escort-empty">${esc(empty)}</td></tr>`}</tbody></table></div>`;
}

function addStylesheet(doc) {
  if (doc.head.querySelector(`link[href="${STYLESHEET}"]`)) return;
  const link = doc.createElement('link'); link.rel = 'stylesheet'; link.href = STYLESHEET; doc.head.append(link);
}

function mountConsoleEscort(doc) {
  if (MOCK || doc.querySelector('#escort-console')) return null;
  const grid = doc.querySelector('#escort-mount') || doc.querySelector('.console-grid'), main = doc.querySelector('main');
  const host = doc.createElement('section'); host.className = 'escort-console'; host.id = 'escort-console';
  host.setAttribute('aria-labelledby', 'escort-console-title');
  if (grid?.parentNode) grid.insertAdjacentElement('afterend', host);
  else if (main) main.append(host);
  else return null;
  addStylesheet(doc);
  let data = { items: [], agencies: [] }, openCode = null, status = 'Talep listesi yükleniyor.';
  const lang = () => language(doc);

  function render() {
    const english = lang() === 'en';
    host.innerHTML = `<h2 id="escort-console-title">${english ? 'Support requests' : 'Refakat talepleri'}</h2><p>${english
      ? 'Nabız is not connected to an agency. “Refer to official channel” asks the citizen to call 153; it does not arrange an escort.'
      : 'Nabız hiçbir kuruma bağlı değil. “Resmî kanala yönlendir” vatandaşa 153’ü aramasını söyler; refakat ayarlamaz.'}</p><p class="console-escort-status" role="status" aria-live="polite">${esc(status)}</p>${tableMarkup(data.items, data.agencies, openCode, lang())}`;
  }

  async function load(announce = '') {
    try { data = await get('/api/console/escort'); status = announce; }
    catch (error) { status = error.message || 'Talep listesi şu an okunamıyor.'; }
    render();
  }

  async function move(button) {
    const code = button.dataset.code, to = button.dataset.to;
    const row = data.items.find((item) => item.code === code);
    if (!row || !movesFor(row.status).includes(to)) { status = 'Bu geçişe izin verilmiyor.'; render(); return; }
    const payload = { to };
    if (to === 'referred_official') {
      payload.agency_id = button.parentElement.querySelector('[data-agency]')?.value || '';
      if (!payload.agency_id) { status = 'Listeden bir kurum seçin.'; render(); return; }
    }
    if (to === 'closed') {
      payload.note = button.parentElement.querySelector('[data-close-note]')?.value || '';
      if (payload.note.trim().length < 5 || payload.note.length > 200) {
        const error = button.parentElement.querySelector('[data-inline-error]');
        if (error) { error.textContent = 'Kapatma notu 5 ile 200 karakter arasında olmalı.'; error.hidden = false; }
        return;
      }
    }
    try {
      await post(`/api/console/escort/${encodeURIComponent(code)}/move`, payload);
      const announce = `${code}: ${to === 'referred_official' ? 'resmî kanala yönlendirildi; vatandaş 153’e sorabilir.' : statusName(to)}.`;
      openCode = code;
      await load(announce);
    } catch (error) { status = error.message || 'Geçiş kaydedilemedi.'; render(); }
  }

  host.addEventListener('click', (event) => {
    const button = event.target.closest('[data-action]'); if (!button) return;
    if (button.dataset.action === 'toggle') { openCode = openCode === button.dataset.code ? null : button.dataset.code; render(); }
    if (button.dataset.action === 'show-close') {
      const fields = button.parentElement.querySelector('[data-close-fields]'); if (fields) fields.hidden = false;
      button.hidden = true;
      fields?.querySelector('textarea')?.focus();
    }
    if (button.dataset.action === 'move') void move(button);
  });
  if (doc.defaultView) doc.defaultView.addEventListener('nabiz:decided', () => { void load(); });
  render();
  void load();
  return { load, render, get data() { return data; } };
}

export { MOVES, mountConsoleEscort };
if (typeof document !== 'undefined') mountConsoleEscort(document);
