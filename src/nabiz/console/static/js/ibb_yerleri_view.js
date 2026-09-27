/* Pure rendering and coordinate helpers for the recorded İBB place lists. */

import { esc } from './format.js';
import { t } from './i18n_text.js';

export const CATEGORY_IDS = Object.freeze(['halk_ekmek', 'kent_lokantasi', 'sosyal_tesis', 'wifi']);
export const MAX_POINTS = 60;

const LABELS = {
  halk_ekmek: ['ui.ibbplaces.category.halk_ekmek', 'Halk Ekmek büfeleri'],
  kent_lokantasi: ['ui.ibbplaces.category.kent_lokantasi', 'Kent Lokantaları'],
  sosyal_tesis: ['ui.ibbplaces.category.sosyal_tesis', 'İBB sosyal tesisleri'],
  wifi: ['ui.ibbplaces.category.wifi', 'ibbWiFi noktaları'],
};
const text = (key, fallback, vars) => esc(t(key, fallback, vars));

function searchBox(lat, lon, radiusDeg = 0.02) {
  if (![lat, lon, radiusDeg].every(Number.isFinite) || radiusDeg <= 0
      || lat < 40.7 || lat > 41.7 || lon < 27.9 || lon > 29.95) return null;
  const floor2 = (value) => Math.floor(value * 100 + 1e-8) / 100;
  const ceil2 = (value) => Math.ceil(value * 100 - 1e-8) / 100;
  return {
    minLon: Math.max(27.9, floor2(lon - radiusDeg)),
    minLat: Math.max(40.7, floor2(lat - radiusDeg)),
    maxLon: Math.min(29.95, ceil2(lon + radiusDeg)),
    maxLat: Math.min(41.7, ceil2(lat + radiusDeg)),
  };
}

function distanceM(a, b) {
  const rad = (degrees) => degrees * Math.PI / 180;
  const lat1 = rad(a.lat), lat2 = rad(b.lat), dLat = lat2 - lat1, dLon = rad(b.lon - a.lon);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return Math.round(6371000 * 2 * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h)));
}

function distanceText(m) {
  if (!Number.isFinite(m) || m < 0) return '';
  if (m < 1000) return `${Math.round(m).toLocaleString('tr-TR')} m`;
  return `${(m / 1000).toLocaleString('tr-TR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })} km`;
}

function dateLabel(iso) {
  const timestamp = Date.parse(iso || '');
  return Number.isFinite(timestamp)
    ? new Intl.DateTimeFormat('tr-TR', { timeZone: 'UTC', day: '2-digit', month: '2-digit', year: 'numeric' }).format(timestamp)
    : '';
}

function isStale(iso, nowIso = new Date().toISOString()) {
  const timestamp = Date.parse(iso || ''), now = Date.parse(nowIso || '');
  return Number.isFinite(timestamp) && Number.isFinite(now) && now - timestamp > 365 * 86400000;
}

function categoryLabel(id) {
  const [key, fallback] = LABELS[id] || LABELS.halk_ekmek;
  return t(key, fallback);
}

function sourceLine(source) {
  const title = source && source.title
    ? `<span lang="tr">${esc(source.title)}</span>` : text('ui.ibbplaces.source_title_unknown', 'Veri seti adı kayıtta yok');
  const date = dateLabel(source && source.resource_last_modified);
  const captured = dateLabel(source && source.captured_at);
  const license = source && source.license ? `<span lang="tr">${esc(source.license)}</span>` : '';
  return [
    text('ui.ibbplaces.source_brand', 'İBB Açık Veri'), title,
    `${text('ui.ibbplaces.data_date', 'veri tarihi')} ${esc(date || t('ui.ibbplaces.date_unknown', 'kayıtta yok'))}`,
    `${text('ui.ibbplaces.captured_date', "Nabız'a alındı")} ${esc(captured || t('ui.ibbplaces.date_unknown', 'kayıtta yok'))}`,
    license,
  ].filter(Boolean).join(' · ');
}

function sectionMarkup(info, lang = 'tr') {
  const categories = new Map((info && Array.isArray(info.categories) ? info.categories : []).map((item) => [item.id, item]));
  const options = CATEGORY_IDS.map((id) => {
    const item = categories.get(id), label = categoryLabel(id);
    const meta = item && item.status === 'alindi'
      ? t('ui.ibbplaces.category_count', '{count} kayıt · veri tarihi {date}', {
        count: Number(item.count || 0).toLocaleString('tr-TR'), date: dateLabel(item.resource_last_modified) || t('ui.ibbplaces.date_unknown', 'kayıtta yok'),
      })
      : item ? t('ui.ibbplaces.unavailable_short', 'alınamadı') : t('ui.ibbplaces.loading_short', 'veri okunuyor');
    return `<label class="ibb-yerleri-choice"><input type="radio" name="ibb-yerleri-category" value="${id}"><span>${esc(label)}<small>${esc(meta)}</small></span></label>`;
  }).join('');
  const districts = info && Array.isArray(info.districts) ? info.districts : [];
  const districtOptions = districts.map((district) => `<option value="${esc(district)}" lang="tr">${esc(district)}</option>`).join('');
  const sources = CATEGORY_IDS.map((id) => {
    const item = categories.get(id);
    if (!item) return '';
    const link = item.dataset_url
      ? `<a href="${esc(item.dataset_url)}" target="_blank" rel="noopener">${text('ui.ibbplaces.open_dataset', 'Veri setini aç')}</a>` : '';
    const license = item.license ? `<p>${text('ui.ibbplaces.license', 'Lisans')}: <span lang="tr">${esc(item.license)}</span>
      ${item.license_url ? `<a href="${esc(item.license_url)}" target="_blank" rel="noopener">${text('ui.ibbplaces.open_license', 'Lisansı aç')}</a>` : ''}</p>` : '';
    const dates = `<p>${text('ui.ibbplaces.data_date', 'Veri tarihi')}: ${esc(dateLabel(item.resource_last_modified) || t('ui.ibbplaces.date_unknown', 'kayıtta yok'))}
      · ${text('ui.ibbplaces.captured_date', "Nabız'a alınma tarihi")}: ${esc(dateLabel(item.captured_at) || t('ui.ibbplaces.date_unknown', 'kayıtta yok'))}</p>`;
    const stale = item.stale || isStale(item.resource_last_modified)
      ? `<p>${text('ui.ibbplaces.stale_note', 'Bu kayıt eski; nokta değişmiş olabilir.')}</p>` : '';
    return `<li><strong>${esc(categoryLabel(id))}</strong>${link}${license}${dates}${stale}</li>`;
  }).join('');
  return `<section id="ibb-yerleri" aria-labelledby="ibb-yerleri-title" lang="${lang === 'en' ? 'en' : 'tr'}">
    <div class="section-head"><h2 id="ibb-yerleri-title" tabindex="-1">${text('ui.ibbplaces.title', 'İBB yerleri')}</h2></div>
    <p class="ibb-yerleri-intro">${text('ui.ibbplaces.intro', "Halk Ekmek büfeleri, Kent Lokantaları, İBB sosyal tesisleri ve ibbWiFi noktaları; İBB Açık Veri'den kayıtlı liste.")}</p>
    <p class="ibb-yerleri-disclaimer">${text('ui.ibbplaces.disclaimer', 'Resmî İBB hizmeti değildir.')}</p>
    <fieldset class="ibb-yerleri-categories"><legend>${text('ui.ibbplaces.category_legend', 'Ne görmek istersiniz?')}</legend>
      <label class="ibb-yerleri-choice"><input type="radio" name="ibb-yerleri-category" value="closed" checked><span>${text('ui.ibbplaces.closed', 'Kapalı')}</span></label>${options}
    </fieldset>
    <div class="ibb-yerleri-controls" hidden><label for="ibb-yerleri-where">${text('ui.ibbplaces.where_label', 'Nerede?')}</label>
      <select id="ibb-yerleri-where"><option value="nearby">${text('ui.ibbplaces.nearby', 'Konumuma yakın')}</option>${districtOptions}</select>
      <button type="button" class="btn" id="ibb-yerleri-show">${text('ui.ibbplaces.show', 'Haritada göster')}</button></div>
    <button type="button" class="btn ibb-yerleri-retry" id="ibb-yerleri-retry" hidden>${text('ui.ibbplaces.retry', 'Yeniden dene')}</button>
    <p class="ibb-yerleri-status" id="ibb-yerleri-status" role="status" aria-live="polite"></p>
    <div class="ibb-yerleri-results" id="ibb-yerleri-results" hidden><h3 id="ibb-yerleri-results-title" tabindex="-1">${text('ui.ibbplaces.results_title', 'Haritadaki kayıtlar')}</h3>
      <ol class="ibb-yerleri-list" aria-labelledby="ibb-yerleri-results-title"></ol></div>
    <details class="ibb-yerleri-sources" id="ibb-yerleri-sources" hidden><summary>${text('ui.ibbplaces.sources_summary', 'Bu veri nereden?')}</summary>
      <ul>${sources}</ul><p>${text('ui.ibbplaces.no_live_info', 'Anlık doluluk ve açılış saati bu veride yok.')}</p></details>
    <p class="ibb-yerleri-mock" id="ibb-yerleri-mock" hidden>${text('ui.ibbplaces.mock', 'Örnek: sunucu bağlı değil.')}</p>
  </section>`;
}

function rowsMarkup(result, userPoint) {
  const source = result && result.source ? result.source : {};
  const points = Array.isArray(result && result.points) ? [...result.points] : [];
  if (userPoint) points.sort((a, b) => distanceM(userPoint, a) - distanceM(userPoint, b) || a.name.localeCompare(b.name, 'tr'));
  return points.map((point) => {
    const card = `iy-${point.id}`;
    const parts = [`<span lang="tr">${esc(point.name)}</span>`];
    if (point.district) parts.push(`<span lang="tr">${esc(point.district)}</span>`);
    if (userPoint) parts.push(`<span>${esc(distanceText(distanceM(userPoint, point)))}</span>`);
    const address = point.address
      ? `<p><span lang="tr">${esc(point.address)}</span></p>`
      : `<p>${text('ui.ibbplaces.address_missing', 'Adres kayıtta yok.')}</p>`;
    const stale = source.stale || isStale(source.resource_last_modified)
      ? `<p>${text('ui.ibbplaces.stale_note', 'Bu kayıt eski; nokta değişmiş olabilir.')}</p>` : '';
    return `<li><details id="${esc(card)}"><summary>${parts.join(' · ')}</summary><div class="ibb-yerleri-row-body">${address}<p>${sourceLine(source)}</p>${stale}</div></details></li>`;
  }).join('');
}

function statusText(result, where) {
  if (!result || result.status !== 'alindi') return t('ui.ibbplaces.list_unavailable', 'Bu liste alınamadı.');
  if (!result.total) return t('ui.ibbplaces.empty', 'Bu bölgede kayıt yok. Başka bir ilçe seçebilirsiniz.');
  if (result.truncated) {
    return where === 'nearby'
      ? t('ui.ibbplaces.truncated_nearby', 'Yakınınızda 60 kayıttan fazlası var; en yakın 60 kayıt haritada.')
      : t('ui.ibbplaces.truncated_district', 'Bu ilçede 60’tan fazla kayıt var; ilk 60 kayıt haritada gösteriliyor.');
  }
  const category = categoryLabel(result.category);
  return where === 'nearby'
    ? t('ui.ibbplaces.nearby_result', 'Konumunuza yakın {count} {category} kaydı; haritada {shown} nokta.', { count: result.total, category, shown: result.shown })
    : t('ui.ibbplaces.district_result', "{district}'de {count} {category} kaydı; haritada {shown} nokta.", {
      district: where, count: result.total, category, shown: result.shown,
    });
}

function mapPoints(points, userPoint) {
  const sorted = [...(Array.isArray(points) ? points : [])];
  if (userPoint) sorted.sort((a, b) => distanceM(userPoint, a) - distanceM(userPoint, b) || a.name.localeCompare(b.name, 'tr'));
  return sorted.map((point) => ({
    lat: point.lat, lon: point.lon, label: [point.name, point.district].filter(Boolean).join(' · '),
    kind: 'place', card: `iy-${point.id}`,
  }));
}

export { searchBox, distanceText, dateLabel, isStale, sectionMarkup, rowsMarkup, statusText, mapPoints };
