/* A read-only queue for household confirmations, acknowledged by a person. */

import { get, post } from './api.js';
import { clock, esc, int } from './format.js';
import { onLang, t, loadCatalogs } from './i18n_text.js';

const STYLESHEET = '/css/console_outage_watch.css';
const LIST_PATH = '/api/console/outage-watch';

function addStylesheet(doc) {
  if (doc.head.querySelector(`link[href="${STYLESHEET}"]`)) return;
  const link = doc.createElement('link'); link.rel = 'stylesheet'; link.href = STYLESHEET; doc.head.append(link);
}

function areaMarkup(area) {
  return `<li class="ow-console-area"><b>${esc(area.district)} / ${esc(area.neighbourhood)}</b><span>${esc(t('ui.outage.area_summary', '{files} dosya · {reports} teyit · son {time}', {
    files: int(area.waiting), reports: int(area.confirmations), time: area.last_confirmation ? clock(area.last_confirmation) : t('ui.outage.unknown_time', 'saat yok'),
  }))}</span></li>`;
}

function itemMarkup(item) {
  const seen = item.status === 'seen';
  const status = seen ? t('ui.outage.status_seen', 'Operatör gördü (prototip)') : t('ui.outage.status_waiting', 'bekliyor');
  const confirms = (item.confirmations || []).map((entry) => `<li>${esc(t('ui.outage.reported_by_user', 'Siz bildirdiniz · {time}', { time: clock(entry.at) }))}${entry.announced_end ? ` · ${esc(t('ui.outage.announced_by_user', 'Siz eklediniz: {time}', { time: entry.announced_end }))}` : ''}</li>`).join('');
  const note = item.note_masked ? `<blockquote lang="${esc(item.lang || 'tr')}">${esc(item.note_masked)}</blockquote>` : '';
  const action = seen ? '' : `<button type="button" class="btn" data-action="seen" data-code="${esc(item.code)}">${esc(t('ui.outage.seen', 'Gördüm'))}</button>`;
  return `<li class="ow-console-item"><div><b>#${esc(item.code)} · ${esc(status)}</b><span>${esc(item.district)} / ${esc(item.neighbourhood)} · ${esc(t('ui.outage.report_count', '{count} teyit', { count: int((item.confirmations || []).length) }))}</span>${confirms ? `<ul>${confirms}</ul>` : ''}${note}</div>${action}</li>`;
}

function addStylesheetPanel(section, res) {
  const waiting = res.counts ? int(res.counts.waiting) : '0';
  const seen = res.counts ? int(res.counts.seen) : '0';
  const areas = (res.areas || []).map(areaMarkup).join('') || `<li>${esc(t('ui.outage.no_areas', 'Bölge teyidi yok.'))}</li>`;
  const items = (res.items || []).map(itemMarkup).join('') || `<li>${esc(t('ui.outage.no_reports', 'Teyit dosyası yok.'))}</li>`;
  section.innerHTML = `<header class="ow-console-head"><h2 id="outage-watch-title">${esc(t('ui.outage.console_title', 'Hane kesinti teyitleri'))}</h2><p>${esc(t('ui.outage.console_counts', '{waiting} bekliyor · {seen} görüldü', { waiting, seen }))}</p></header>
    <p class="ow-console-note">${esc(t('ui.outage.console_disclaimer', 'Vatandaşın “suyum hâlâ gelmedi” teyitleri. İSKİ’ye iletilmez; resmî kesinti bilgisi değildir. Kişisel veriler maskelenir; 7 gün sonra silinir.'))}</p>
    <h3>${esc(t('ui.outage.area_heading', 'Bölgeler'))}</h3><ul class="ow-console-areas">${areas}</ul>
    <h3>${esc(t('ui.outage.queue_heading', 'Dosyalar'))}</h3><ul class="ow-console-list">${items}</ul>
    <p class="ow-console-status" role="status" aria-live="polite"></p>`;
}

function mountConsole(doc) {
  const anchor = doc.getElementById('outage-watch-mount') || doc.getElementById('citizen-requests');
  if (!anchor) return null;
  const section = doc.getElementById('outage-watch') || doc.createElement('section');
  section.id = 'outage-watch'; section.setAttribute('aria-labelledby', 'outage-watch-title');
  if (!section.isConnected) anchor.after(section);
  addStylesheet(doc);
  let visible = false;
  let loading = false;
  const location = (doc.defaultView && doc.defaultView.location) || globalThis.location || { search: '' };
  if (new URLSearchParams(location.search).get('lang') === 'en') void loadCatalogs('en');

  async function refresh() {
    if (loading) return;
    loading = true;
    section.setAttribute('aria-busy', 'true');
    try {
      const res = await get(LIST_PATH);
      addStylesheetPanel(section, res);
    } catch {
      section.innerHTML = `<h2 id="outage-watch-title">${esc(t('ui.outage.console_title', 'Hane kesinti teyitleri'))}</h2><p class="ow-console-status" role="status" aria-live="polite">${esc(t('ui.outage.console_error', 'Teyit kuyruğu açılamadı. Bölüm görünürken yeniden deneyin.'))}</p>`;
    } finally {
      loading = false;
      section.removeAttribute('aria-busy');
    }
  }

  section.addEventListener('click', async (event) => {
    const button = event.target.closest('[data-action="seen"]');
    if (!button || button.getAttribute('aria-busy') === 'true') return;
    const code = button.dataset.code;
    button.setAttribute('aria-busy', 'true');
    try {
      await post(`${LIST_PATH}/${encodeURIComponent(code)}/seen`, {});
      await refresh();
      doc.dispatchEvent(new CustomEvent('nabiz:ledger-changed'));
    } catch {
      const status = section.querySelector('.ow-console-status');
      if (status) status.textContent = t('ui.outage.seen_error', 'Görüldü bilgisi kaydedilemedi. Yeniden deneyin.');
      button.removeAttribute('aria-busy');
    }
  });
  doc.addEventListener('nabiz:ledger-changed', () => { void refresh(); });
  doc.addEventListener('visibilitychange', () => {
    if (doc.visibilityState === 'visible' && visible) void refresh();
  });
  const Observer = doc.defaultView && doc.defaultView.IntersectionObserver;
  if (Observer) {
    const observer = new Observer((entries) => {
      visible = entries.some((entry) => entry.isIntersecting);
      if (visible) void refresh();
    });
    observer.observe(section);
  } else {
    visible = true;
    void refresh();
  }
  onLang(() => { if (visible) void refresh(); });
  return section;
}

if (typeof document !== 'undefined') {
  const mount = () => mountConsole(document);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, { once: true });
  else mount();
}
