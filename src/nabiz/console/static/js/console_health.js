/* The small E18 view: first-decision times and coded approval or rejection reasons. */

import { esc, num, shortAge } from './format.js';
import { REFRESH_MS } from './config.js';

function formatPercent(rate) {
  return Number.isFinite(rate) ? `%${num(rate * 100, 0)}` : 'henüz yok';
}

function durationList(durations, median) {
  const largest = Math.max(0, ...durations.map((item) => Number(item.count) || 0));
  const rows = durations.map((item) => {
    const count = Number(item.count) || 0;
    const width = largest ? Math.round(count / largest * 100) : 0;
    return `<li><span class="health-hist-label">${esc(item.label)}</span>`
      + `<span class="health-meter"><span class="health-bar" style="--w: ${width}%"></span></span>`
      + `<span class="health-hist-count">${num(count, 0)}</span></li>`;
  }).join('');
  const medianText = Number.isFinite(median) ? shortAge(median) : 'henüz yok';
  return `<ul class="health-hist">${rows}</ul><p class="health-median">Medyan karar süresi: ${esc(medianText)}</p>`;
}

function reasonList(reasons) {
  const actions = reasons.by_action || {};
  const rows = reasons.codes.map((item) => `<li><span>${esc(item.label)}</span>`
    + `<span class="health-reason-count">${num(item.count, 0)}</span></li>`).join('');
  return `<p class="health-actions">Onay ${num(actions.approve || 0, 0)} · Düzenleyerek onay ${num(actions.edit || 0, 0)}`
    + ` · Ret ${num(actions.reject || 0, 0)}</p><ul class="health-reasons">${rows}`
    + `<li><span>Kodsuz gerekçe</span><span class="health-reason-count">${num(reasons.without_code || 0, 0)}</span></li></ul>`;
}

function healthSection(payload) {
  if (!payload) {
    return '<section id="approval-health" class="health" aria-labelledby="health-title">'
      + '<div class="section-head"><h2 id="health-title">Onay sağlığı</h2></div>'
      + '<p class="status-line">Onay sağlığı yükleniyor.</p></section>';
  }
  const count = payload.window.rulings_counted;
  const rate = payload.approval_rate;
  const rateText = Number.isFinite(rate) ? `Onay oranı ${formatPercent(rate)}`
    + (payload.sufficient ? '' : ' · yetersiz örnek') : 'Onay oranı henüz yok';
  const sampleNote = payload.sufficient ? ''
    : `<p class="section-note">Yetersiz örnek: ${num(count, 0)} karar var. Yeterli değerlendirme için en az ${num(payload.window.min_rulings, 0)} karar gerekir.</p>`;
  return '<section id="approval-health" class="health" aria-labelledby="health-title">'
    + `<div class="section-head"><h2 id="health-title">Onay sağlığı</h2>`
    + `<span class="section-note">Oran ve gerekçe: son ${num(payload.window.size, 0)} onay/ret · süre: her kartın ilk kararı · simüle operatör · kişi bazında metrik yok</span></div>`
    + `<div class="health-grid"><section class="health-part" aria-labelledby="health-rate-title">`
    + `<h3 id="health-rate-title">Onay oranı</h3><p class="health-value">${esc(rateText)}</p>${sampleNote}</section>`
    + `<section class="health-part" aria-labelledby="health-duration-title"><h3 id="health-duration-title">İlk karar süresi</h3>`
    + `${durationList(payload.durations, payload.median_decision_s)}</section>`
    + `<section class="health-part" aria-labelledby="health-reason-title"><h3 id="health-reason-title">Gerekçe dağılımı</h3>`
    + `${reasonList(payload.reasons)}</section></div></section>`;
}

function placeSection(section) {
  const day = document.getElementById('day');
  if (day) {
    day.after(section);
    return;
  }
  const stats = document.getElementById('stats')?.closest('section');
  if (stats) {
    stats.after(section);
    return;
  }
  document.querySelector('main#main')?.append(section);
}

function mount() {
  let section = document.getElementById('approval-health');
  const render = (payload) => {
    const template = document.createElement('template');
    template.innerHTML = healthSection(payload);
    const replacement = template.content.firstElementChild;
    if (section?.isConnected) section.replaceWith(replacement);
    else placeSection(replacement);
    section = replacement;
  };
  if (!section) render(null);

  const load = async () => {
    try {
      const { MOCK, get } = await import('./api.js');
      if (MOCK) {
        section.innerHTML = '<div class="section-head"><h2 id="health-title">Onay sağlığı</h2></div>'
          + '<p class="section-note">Örnek veri modunda onay sağlığı gösterilmez.</p>';
        return;
      }
      render(await get('/api/console/approval-health'));
    } catch (error) {
      section.innerHTML = '<div class="section-head"><h2 id="health-title">Onay sağlığı</h2></div>'
        + `<p class="status-line">Onay sağlığı okunamadı: ${esc(error.message)}</p>`;
    }
  };

  let timer = null;
  const start = () => {
    if (timer === null) timer = setInterval(load, REFRESH_MS);
  };
  const stop = () => {
    if (timer !== null) clearInterval(timer);
    timer = null;
  };
  document.addEventListener('visibilitychange', () => {
    stop();
    if (document.visibilityState === 'visible') start();
  });
  load();
  start();
}

if (typeof document !== 'undefined') mount();

export { durationList, formatPercent, healthSection, mount, reasonList };
