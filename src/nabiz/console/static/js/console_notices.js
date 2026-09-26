/* The Metro notice history view for the simulated operator console. */

import { MOCK, get } from './api.js';
import { esc, num } from './format.js';
import { REFRESH_MS } from './config.js';

function dateTime(value) {
  if (!value) return 'arşivde yok';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'arşivde yok';
  const parts = new Intl.DateTimeFormat('tr-TR', {
    timeZone: 'Europe/Istanbul', day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(date);
  const part = (type) => parts.find((item) => item.type === type)?.value || '';
  return `${part('day')}.${part('month')}.${part('year')} ${part('hour')}.${part('minute')}`;
}

function statusText(payload) {
  if (!payload.current_readable) return 'Metro bildirimleri okunamadı';
  const count = payload.notices.length;
  return count ? `${num(count, 0)} bildirim okundu` : 'Bildirim yok';
}

function noticeItem(item) {
  return '<article class="notices-item">'
    + `<h3 class="notices-line">${esc(item.line || 'Hat bilgisi yok')}</h3>`
    + `<p class="notices-description">${esc(item.description || '')}</p>`
    + `<p class="notices-since">${esc(item.since_text || '')}</p>`
    + (item.first_seen
      ? `<p class="notices-reads">Nabız ilk: ${esc(dateTime(item.first_seen))} · son: ${esc(dateTime(item.last_seen))}</p>`
      : '<p class="notices-reads">Nabız\'ın arşivinde bu bildirim yok.</p>')
    + (item.total_reads
      ? `<p class="notices-count">${num(item.total_reads, 0)} okumadan ${num(item.seen_reads, 0)} tanesinde</p>` : '')
    + '</article>';
}

function goneItem(item) {
  return '<li class="notices-gone-item">'
    + `<strong>${esc(item.line || 'Hat bilgisi yok')}</strong> ${esc(item.description || '')}`
    + `<span class="notices-gone-last">Son görüldüğü an: ${esc(dateTime(item.last_seen))}</span></li>`;
}

function liftItem(item) {
  return '<li class="notices-lift-item">'
    + `<strong>${esc(item.station)}</strong> · ${esc(item.ibb_date_raw)}`
    + `<span class="notices-lift-reads">Nabız ilk: ${esc(dateTime(item.first_seen))} · son: ${esc(dateTime(item.last_seen))}</span>`
    + '</li>';
}

function content(payload) {
  const notices = payload.notices.map(noticeItem).join('');
  const gone = payload.gone.length
    ? `<section class="notices-subsection" aria-labelledby="notices-gone-title"><h3 id="notices-gone-title">Son okumada görünmeyenler</h3>`
      + `<ul class="notices-gone-list">${payload.gone.map(goneItem).join('')}</ul></section>` : '';
  const lifts = payload.lifts.length
    ? `<section class="notices-subsection" aria-labelledby="notices-lifts-title"><h3 id="notices-lifts-title">Asansör arşivi</h3>`
      + `<ul class="notices-lift-list">${payload.lifts.map(liftItem).join('')}</ul></section>` : '';
  const archive = payload.archive || {};
  const note = payload.note ? `<p class="notices-note">${esc(payload.note)}</p>` : '';
  return `<p class="notices-status" role="status">${esc(statusText(payload))}</p>`
    + `<div class="notices-list">${notices}</div>${gone}${lifts}`
    + `<p class="notices-archive">Metro arşivi: ${num(archive.metro_reads, 0)} okuma, ${num(archive.metro_days, 0)} gün. `
    + `Ekipman arşivi: ${num(archive.equipment_rows, 0)} satırın ${num(archive.equipment_readable_rows, 0)} tanesi okunabilir.</p>${note}`;
}

function mount() {
  const approval = document.getElementById('approval-health');
  if (!approval) return;
  let section = document.getElementById('metro-notices');
  if (!section) {
    section = document.createElement('section');
    section.id = 'metro-notices';
    section.className = 'notices notices-section';
    section.setAttribute('aria-labelledby', 'notices-title');
    section.innerHTML = '<div class="notices-head"><h2 class="notices-heading" id="notices-title">Metro bildirimleri ne zamandır yayında</h2></div>';
    approval.after(section);
  }
  if (!document.querySelector('link[data-notices-styles]')) {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = '/css/console_notices.css';
    link.dataset.noticesStyles = '';
    document.head.append(link);
  }

  let pending = null;
  const apply = (html) => {
    if (section.innerHTML === html) return;
    if (section.contains(document.activeElement)) {
      pending = html;
      return;
    }
    section.innerHTML = html;
    pending = null;
  };
  section.addEventListener('focusout', (event) => {
    if (pending !== null && !section.contains(event.relatedTarget)) {
      section.innerHTML = pending;
      pending = null;
    }
  });

  const load = async () => {
    if (MOCK) {
      apply('<div class="notices-head"><h2 class="notices-heading" id="notices-title">Metro bildirimleri ne zamandır yayında</h2></div>'
        + '<p class="notices-status" role="status">Örnek veri modunda bu bölüm gösterilmez.</p>');
      return;
    }
    try {
      const payload = await get('/api/console/metro-notices');
      apply('<div class="notices-head"><h2 class="notices-heading" id="notices-title">Metro bildirimleri ne zamandır yayında</h2></div>'
        + content(payload));
    } catch (err) {
      apply('<div class="notices-head"><h2 class="notices-heading" id="notices-title">Metro bildirimleri ne zamandır yayında</h2></div>'
        + `<p class="notices-status is-bad" role="status">${esc(err.message)}</p>`);
    }
  };

  let timer = null;
  const start = () => { if (timer === null) timer = setInterval(load, REFRESH_MS); };
  const stop = () => { if (timer !== null) clearInterval(timer); timer = null; };
  document.addEventListener('visibilitychange', () => {
    stop();
    if (document.visibilityState === 'visible') start();
  });
  load();
  start();
}

if (typeof document !== 'undefined') mount();

export { content, dateTime, goneItem, liftItem, mount, noticeItem, statusText };
