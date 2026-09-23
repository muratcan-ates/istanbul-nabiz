/* A failure is rendered as an answer in the results region, with the age of the last thing we
 * knew when İBB is the one failing. */

import { api } from './api.js';
import { esc, shortAge } from './format.js';
import { icon } from './icons.js';
import { sourceLabel } from './provenance.js';
import { hideMap } from './map.js';

const $ = (sel) => document.querySelector(sel);
const results = $('#results');

const ERROR_TITLES = {
  0: 'Sunucuya ulaşılamadı',
  400: 'Bu soruyu yanıtlayamadım',
  404: 'Böyle bir uç yok',
  422: 'İstek eksik ya da hatalı',
  429: 'Kendi istek bütçemiz doldu',
  503: 'İBB servisi şu anda yanıt vermiyor',
};

/**
 * A failure is an answer. A 503 in particular must say how old the last thing we knew is,
 * because "bilmiyorum" and "17 saniye önce biliyordum" are different answers to the user.
 */
async function showError(err) {
  const status = err.status || 0;
  const title = ERROR_TITLES[status] || 'Beklenmeyen bir hata';
  let lastKnown = '';
  if (status === 503 || status === 429 || status === 0) {
    try {
      const fresh = await api('/api/freshness');
      const rows = Object.entries((fresh.data && fresh.data.sources) || {})
        .map(([name, s]) => {
          const when = Number.isFinite(s.age_seconds) ? `${shortAge(s.age_seconds)} önce` : 'hiç alınamadı';
          return `<li><span>${esc(sourceLabel(name))}</span><span>${esc(when)}</span></li>`;
        })
        .join('');
      if (rows) {
        lastKnown = `<div class="last-known"><h4>En son ne zaman veri alabildik</h4><ul class="kv-list">${rows}</ul></div>`;
      }
    } catch (ignored) {
      lastKnown = '';
    }
  }
  // The server's Turkish message often opens with the same sentence as our heading
  // ("İBB servisi şu anda yanıt vermiyor: …"); saying it twice reads as a stutter.
  let detail = err.message || 'Bilinmeyen hata.';
  if (detail.startsWith(title)) {
    const trimmed = detail.slice(title.length).replace(/^[\s:—-]+/, '');
    if (trimmed) detail = trimmed;
  }
  results.innerHTML = `<div class="error-card">
    <h3>${icon('alert')}${esc(title)}</h3>
    <p>${esc(detail)}</p>
    ${status === 503 ? '<p>Bu bir Nabız hatası değil: üst kaynak (İBB) yanıt vermedi. Sayı uydurmak yerine boş bırakıyoruz.</p>' : ''}
    ${lastKnown}
  </div>`;
  hideMap();
}

export { showError };
