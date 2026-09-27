/* Source-quoted weekly fare estimate. The browser sends only the closed travel pattern. */

import { MOCK, get, post } from './api.js';
import { currentLang, onLang, t } from './i18n_text.js';
import { esc } from './format.js';
import { icon } from './icons.js';

const STORAGE_KEY = 'nabiz.fare.v1';
const MODES = ['metro', 'ferry', 'bus', 'metrobus', 'marmaray', 'other'];
const TARIFFS = ['tam', 'ogrenci', 'ogrenci30', 'other'];
function sourceDate(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value || '');
  return match ? `${match[3]}.${match[2]}.${match[1]}` : t('ui.fare.no_date', 'sayfada tarih yok');
}

function validStoredPattern(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  if (Object.keys(value).sort().join(',') !== 'days_per_week,legs,personalized,round_trip,tariff,within_window') return false;
  if (!Number.isInteger(value.days_per_week) || value.days_per_week < 1 || value.days_per_week > 7) return false;
  if (typeof value.round_trip !== 'boolean' || !TARIFFS.includes(value.tariff)) return false;
  if (!Array.isArray(value.legs) || value.legs.length < 1 || value.legs.length > 4) return false;
  if (typeof value.within_window !== 'boolean' || typeof value.personalized !== 'boolean') return false;
  return value.legs.every((leg) => leg && typeof leg === 'object' && !Array.isArray(leg)
    && Object.keys(leg).sort().join(',') === (leg.mode === 'ferry' ? 'mode,route' : 'mode')
    && MODES.includes(leg.mode) && (leg.mode === 'ferry'
      ? typeof leg.route === 'string' && leg.route.length > 0 && leg.route.length <= 80 : true));
}

export function readPattern() {
  try {
    const record = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || 'null');
    return record && record.version === 1 && validStoredPattern(record.pattern) ? record.pattern : null;
  } catch (error) { return null; }
}

export function writePattern(pattern, consent = false) {
  if (!consent || !validStoredPattern(pattern)) return false;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ version: 1, pattern, saved_at: new Date().toISOString() }));
    return true;
  } catch (error) { return false; }
}

export function formatKurus(kurus, lang = currentLang()) {
  if (!Number.isSafeInteger(kurus) || kurus < 0) return t('ui.fare.unknown', 'bilinmiyor');
  return new Intl.NumberFormat(lang === 'en' ? 'en-GB' : 'tr-TR', {
    style: 'currency', currency: 'TRY', minimumFractionDigits: 2, maximumFractionDigits: 2,
  }).format(kurus / 100);
}

export function reasonText(code, vars = {}) {
  if (code === 'metro_transfer_rule_missing') return t('ui.fare.metro_transfer_rule_missing', "Metroya aktarmada ücretin nasıl hesaplandığı Nabız'ın kaynaklarında yok.", vars);
  if (code === 'bus_tariff_unavailable') return t('ui.fare.bus_tariff_unavailable', 'İETT tarifesi alınamadı: sayfa ücreti tarayıcıda yüklüyor (kontrol: {date}).', vars);
  if (code === 'marmaray_source_missing') return t('ui.fare.marmaray_source_missing', "Marmaray ücreti için Nabız'ın kaynağı yok.", vars);
  if (code === 'eticket_scope_metro_only') return t('ui.fare.eticket_scope_metro_only', "Elektronik bilet sayfası yalnız Metro İstanbul'undur; bu araçta geçerliliği kaynakta yok.", vars);
  if (code === 'subscription_scope_unknown') return t('ui.fare.subscription_scope_unknown', "Mavi kartın bu araçta geçerliliği Nabız'ın kaynaklarında yok.", vars);
  if (code === 'passes_missing') return t('ui.fare.passes_missing', 'Kaynakta bu tarife için geçiş sayısı yazmıyor; geçiş başı pay hesaplanamadı.', vars);
  return t('ui.fare.unknown_mode', "Bu araç için Nabız'ın kaynağı yok.", vars);
}

function modeLabel(mode) {
  if (mode === 'metro') return t('ui.fare.mode_metro', 'Metro İstanbul raylı hat');
  if (mode === 'ferry') return t('ui.fare.mode_ferry', 'Vapur (Şehir Hatları)');
  if (mode === 'bus') return t('ui.fare.mode_bus', 'Otobüs');
  if (mode === 'metrobus') return t('ui.fare.mode_metrobus', 'Metrobüs');
  if (mode === 'marmaray') return t('ui.fare.mode_marmaray', 'Marmaray');
  return t('ui.fare.mode_other', 'Diğer');
}

function tariffLabel(tariff) {
  if (tariff === 'tam') return t('ui.fare.tariff_full', 'Tam');
  if (tariff === 'ogrenci') return t('ui.fare.tariff_student', 'Öğrenci');
  if (tariff === 'ogrenci30') return t('ui.fare.tariff_student30', '30 yaşından gün almış öğrenci');
  return t('ui.fare.tariff_other', 'Başka bir kart');
}

function otherModeNote() {
  return t('ui.fare.other_mode_note', 'Başka bir kart: sosyal, indirimli, 65 yaş ve üstü, engelli');
}

function checked(node) { return Boolean(node && node.checked); }

function formPattern(root) {
  const legs = [...root.querySelectorAll('[data-fare-leg]')].map((row) => {
    const mode = row.querySelector('[data-leg-mode]').value;
    const route = row.querySelector('[data-leg-route]');
    return mode === 'ferry' ? { mode, route: route.value } : { mode };
  });
  return {
    days_per_week: Number(root.querySelector('#tarife-days').value),
    round_trip: checked(root.querySelector('#tarife-round-trip')),
    tariff: root.querySelector('input[name="tarife-tariff"]:checked')?.value || '',
    legs,
    within_window: checked(root.querySelector('#tarife-window')),
    personalized: checked(root.querySelector('#tarife-personalized')),
  };
}

function makeLink(source, linkText, lang, extraClass = '') {
  if (!source || !source.url) return '';
  return `<a class="fare-source-link ${extraClass}" href="${esc(source.url)}" target="_blank" rel="noopener" lang="${lang}" aria-label="${esc(linkText)}">${icon('external-link')}<span>${esc(linkText)}</span></a>`;
}

function sourceRow(source, date, text, lang) {
  if (!source || !source.url) return '';
  const saved = date ? t('ui.fare.saved_date', 'kaydedildi: {date}', { date: sourceDate(date) }) : t('ui.fare.no_date', 'sayfada tarih yok');
  return `<p class="fare-source"><span lang="tr">${esc(source.institution || '')} · ${esc(source.title || '')}</span> · <span lang="${lang}">${esc(saved)}</span> ${makeLink(source, text, lang)}</p>`;
}

function quoteDetails(quote, label) {
  if (!quote) return '';
  return `<details class="fare-quote"><summary>${esc(label)}</summary><blockquote lang="tr">${esc(quote)}</blockquote></details>`;
}

function noticeNotes(notes, sources, lang) {
  const night = sources.ferry;
  const lines = [
    { label: t('ui.fare.note_night', 'Gece tarifesindeki iki kat hesaba katılmadı.'), source: night, quote: notes.night_not_counted },
    { label: t('ui.fare.note_distance', 'Mesafe bazlı hatlarda iade farkı hesaba katılmadı.'), source: night,
      quote: notes.distance_based_refund_not_counted },
    { label: t('ui.fare.note_validity', 'Mavi kartın geçerlilik süresi kaynakta yok.') },
    { label: t('ui.fare.note_boarding', 'Her biniş bir geçiş sayıldı; aktarmanın geçiş sayılıp sayılmadığı kaynakta yok.') },
    { label: t('ui.fare.note_parking', "Park et devam et ücreti için Nabız'ın kaynağı yok.") },
    { label: t('ui.fare.note_senior', '65 yaş ve üstü için tarife kaynağı yok.') },
  ];
  return `<details class="fare-notes"><summary>${t('ui.fare.notes_title', 'Hesaba katılmayanlar')}</summary>${lines.map((item) => {
    return `<div class="fare-note"><p>${esc(item.label)}</p>${item.quote ? quoteDetails(item.quote, t('ui.fare.quote_summary', 'Kaynaktaki metin'))
      + sourceRow(item.source, item.source.fetched_at, t('ui.fare.source_open', 'Resmî kaynağı aç (yeni sekme)'), lang) : ''}</div>`;
  }).join('')}</details>`;
}

function lineMarkup(line, catalog, lang) {
  const sources = catalog.sources || {};
  const source = sources[line.source_id] || {};
  const checkedAt = line.source_id === 'iett' ? catalog.missing?.bus?.checked_at : null;
  const reasonDate = sourceDate(checkedAt || source.fetched_at);
  const sourceDateValue = source.fetched_at || checkedAt;
  const labelFromReason = Boolean(line.reason && line.reason !== 'passes_missing');
  const displayLabel = labelFromReason ? modeLabel(line.mode) : line.label || modeLabel(line.mode);
  const labelLang = labelFromReason ? lang : 'tr';
  const amount = line.kurus === null ? `${t('ui.fare.unknown', 'bilinmiyor')}: ${esc(reasonText(line.reason, { date: reasonDate }))}`
    : esc(formatKurus(line.kurus, lang));
  const section = line.section ? `<span lang="tr">${esc(line.section)}</span> · ` : '';
  const column = line.column ? ` · ${esc(line.column)}` : '';
  const note = line.note === 'distance_based_refund_not_counted'
    ? `<p class="fare-line-note">${t('ui.fare.note_distance', 'Mesafe bazlı hatlarda iade farkı hesaba katılmadı.')}</p>` : '';
  const extraPasses = line.extra_passes > 0
    ? `<p class="fare-line-note">${t('ui.fare.extra_passes', '{count} kullanılmayan geçiş', { count: line.extra_passes })}</p>` : '';
  const quote = quoteDetails(line.quote, t('ui.fare.quote_summary', 'Kaynaktaki metin'));
  const supporting = (line.supports || []).map((item) => {
    const extra = sources[item.source_id] || {};
    return `${quoteDetails(item.quote, t('ui.fare.supporting_quote', 'Geçerlilik bilgisi'))}${sourceRow(extra, extra.fetched_at,
      t('ui.fare.source_open', 'Resmî kaynağı aç (yeni sekme)'), lang)}`;
  }).join('');
  return `<li class="fare-line" lang="${lang}"><div class="fare-line-value">${section}<strong lang="${labelLang}">${esc(displayLabel)}</strong><span lang="tr">${column}</span><span class="fare-amount" lang="${lang}">${amount}</span></div>${note}${extraPasses}`
    + `${sourceRow(source, sourceDateValue, t('ui.fare.source_open', 'Resmî kaynağı aç (yeni sekme)'), lang)}${quote}${supporting}</li>`;
}

function optionMarkup(option, catalog, estimate, lang) {
  const heading = option.id === 'eticket' ? t('ui.fare.option_eticket', 'Elektronik bilet')
    : option.id === 'subscription' ? t('ui.fare.option_subscription', 'Mavi kart')
      : t('ui.fare.option_single', 'İstanbulkart ile tek tek biniş');
  const isLowest = estimate.lowest === option.id && estimate.lowest !== null;
  let total = '';
  if (!option.computed) {
    total = `<p class="fare-result-total">${esc(reasonText(option.reason))}</p>`;
  } else if (option.unknown.length) {
    total = `<p class="fare-result-total">${esc(t('ui.fare.known_part', 'Haftalık bilinen kısım: {amount}', {
      amount: formatKurus(option.known_weekly_kurus, lang),
    }))}</p><p class="fare-unknown">${icon('info-circle')}<span>${esc(t('ui.fare.unknown_count', '{count} bacağın ücreti bilinmiyor', {
      count: option.unknown.length,
    }))}</span></p>`;
  } else {
    total = `<p class="fare-result-total">${esc(t('ui.fare.weekly', 'Haftalık: {amount}', {
      amount: formatKurus(option.known_weekly_kurus, lang),
    }))}</p>`;
  }
  const badge = isLowest ? `<p class="fare-lowest">${icon('circle-check')}<span>${t('ui.fare.lowest', 'Bu desende bilinen bedeli en düşük')}</span></p>` : '';
  const weeks = option.id === 'subscription' && option.weeks_covered !== null && option.weeks_covered !== undefined
    ? `<p class="fare-option-note">${t('ui.fare.weeks_covered', 'Kaynakta belirtilen geçiş sayısı bu desende {weeks} hafta sürer.', {
      weeks: new Intl.NumberFormat(lang === 'en' ? 'en-GB' : 'tr-TR', { maximumFractionDigits: 1 }).format(option.weeks_covered),
    })}</p>` : '';
  const lines = (option.lines || []).map((line) => lineMarkup(line, catalog, lang)).join('');
  const sample = `<p class="fare-option-note fare-sample">${esc(t('ui.fare.sample', 'Örnek hesaplama; güncel tarife için resmî kaynağa bakın.'))}</p>`;
  return `<article class="fare-option${isLowest ? ' is-lowest' : ''}"><h3>${esc(heading)}</h3>${sample}${total}${weeks}${badge}<ul class="fare-lines">${lines}</ul></article>`;
}

function otherMarkup(result, catalog, lang) {
  const sources = catalog.sources || {};
  const quotes = (result.quotes || []).map((item) => {
    const source = sources[item.source_id] || {};
    const label = `${item.section ? `${item.section} · ` : ''}${item.label ? `${item.label} · ` : ''}${item.column}`;
    return `<article class="fare-other-quote"><h4 lang="tr">${esc(label)}</h4>${sourceRow(source, source.fetched_at,
      t('ui.fare.source_open', 'Resmî kaynağı aç (yeni sekme)'), lang)}${quoteDetails(item.quote, t('ui.fare.quote_summary', 'Kaynaktaki metin'))}</article>`;
  }).join('');
  const channel = catalog.official_contact || {};
  return `<section class="fare-other-result"><h3>${t('ui.fare.other_title', 'Tarife satırları')}</h3>`
    + `<p class="fare-option-note fare-sample">${esc(t('ui.fare.sample', 'Örnek hesaplama; güncel tarife için resmî kaynağa bakın.'))}</p>${quotes}`
    + `<p>${t('ui.fare.other_card_note', "Kartınıza hangisinin uygulandığını Nabız bilmez; İstanbulkart'a ya da 153'e sorun.")}</p>`
    + `<p>${makeLink({ url: channel.url, institution: channel.name }, t('ui.fare.istanbulkart_link', 'İstanbulkart resmî sayfası'), lang)}`
    + ` <a href="tel:${esc(channel.phone || '153')}">${esc(channel.phone || '153')}</a></p></section>`;
}

function resultMarkup(result, catalog, lang) {
  if (!result || !result.computed) return otherMarkup(result || {}, catalog, lang);
  const comparison = result.lowest === null
    ? `<p class="fare-comparison">${t('ui.fare.comparison_missing', 'Bazı bedeller bilinmediği için karşılaştırma sıralaması yapılmadı.')}</p>` : '';
  const cards = result.options.map((option) => optionMarkup(option, catalog, result, lang)).join('');
  return `${comparison}<div class="fare-options">${cards}</div>${noticeNotes(result.notes, catalog.sources || {}, lang)}`;
}

function validateForm(pattern) {
  const errors = [];
  if (!Number.isInteger(pattern.days_per_week) || pattern.days_per_week < 1 || pattern.days_per_week > 7) {
    errors.push({ field: 'days_per_week', code: 'range' });
  }
  if (!TARIFFS.includes(pattern.tariff)) errors.push({ field: 'tariff', code: 'choice' });
  if (pattern.legs.length < 1 || pattern.legs.length > 4) errors.push({ field: 'legs', code: 'count' });
  pattern.legs.forEach((leg, index) => {
    if (leg.mode === 'ferry' && !leg.route) errors.push({ field: `legs.${index}.route`, code: 'choice' });
  });
  return errors;
}

function errorMessage(error) {
  if (error.field === 'days_per_week') return t('ui.fare.error_days', 'Haftada 1 ile 7 gün arasında seçim yapın.');
  if (error.field === 'tariff') return t('ui.fare.error_tariff', 'Bir tarife türü seçin.');
  if (error.field.endsWith('.route')) return t('ui.fare.error_route', 'Vapur hattını seçin.');
  return t('ui.fare.error_legs', 'Bir ile dört bacak arasında seçim yapın.');
}

function formMarkup(catalog, pattern, lang) {
  const routeOptions = (catalog.ferry_routes || []).map((route) => `<option value="${esc(route.id)}" lang="tr">${esc(route.label)}</option>`).join('');
  const tariffs = TARIFFS.map((id) => `<label class="fare-radio" for="tarife-tariff-${id}"><input type="radio" id="tarife-tariff-${id}" name="tarife-tariff" value="${id}"${pattern.tariff === id ? ' checked' : ''}><span>${esc(tariffLabel(id))}</span></label>`).join('');
  return `<form id="tarife-form" autocomplete="off" novalidate>
    <div class="fare-form-grid">
      <div class="fare-field"><label for="tarife-days">${t('ui.fare.days_label', 'Haftada kaç gün?')}</label><select id="tarife-days" aria-describedby="tarife-days-error">${Array.from({ length: 7 }, (_, index) => {
        const value = index + 1;
        return `<option value="${value}"${pattern.days_per_week === value ? ' selected' : ''}>${value} ${t('ui.fare.days_word', 'gün')}</option>`;
      }).join('')}</select><p class="fare-error" id="tarife-days-error" hidden></p></div>
      <label class="fare-check" for="tarife-round-trip"><input id="tarife-round-trip" type="checkbox"${pattern.round_trip ? ' checked' : ''}><span>${t('ui.fare.round_trip', 'Gidiş ve dönüş')}</span></label>
    </div>
    <fieldset class="fare-fieldset" aria-describedby="tarife-tariff-error"><legend>${t('ui.fare.tariff_legend', 'Kartınızda uygulanan tarife türü')}</legend><div class="fare-radio-list">${tariffs}</div>
      <p class="fare-other-hint">${esc(otherModeNote())}</p><p class="fare-error" id="tarife-tariff-error" hidden></p></fieldset>
    <fieldset class="fare-fieldset" aria-describedby="tarife-legs-error"><legend>${t('ui.fare.legs_legend', 'Bir yöndeki yolculuğun bacakları')}</legend>
      <div id="tarife-legs" class="fare-legs"></div><p class="fare-error" id="tarife-legs-error" hidden></p>
      <button class="fare-quiet" type="button" id="tarife-add-leg">${t('ui.fare.add_leg', 'Bacak ekle')}</button></fieldset>
    <div id="tarife-transfers" class="fare-transfer-options"${pattern.legs.length < 2 ? ' hidden' : ''}>
      <label class="fare-check" for="tarife-window"><input id="tarife-window" type="checkbox"${pattern.within_window ? ' checked' : ''}><span>${t('ui.fare.within_window', 'Aktarmalar 120 dakika içinde')}</span></label>
      <label class="fare-check" for="tarife-personalized"><input id="tarife-personalized" type="checkbox"${pattern.personalized ? ' checked' : ''}><span>${t('ui.fare.personalized', 'Adıma kayıtlı (kişiselleştirilmiş) İstanbulkart kullanıyorum')}</span></label>
    </div>
    <button class="btn btn-primary fare-submit" type="submit">${t('ui.fare.calculate', 'Hesapla')}</button>
  </form>`;
}

function legsMarkup(catalog, legs, lang) {
  return legs.map((leg, index) => {
    const routeOptions = (catalog.ferry_routes || []).map((route) => `<option value="${esc(route.id)}"${route.id === leg.route ? ' selected' : ''} lang="tr">${esc(route.label)}</option>`).join('');
    const modes = MODES.map((mode) => `<option value="${mode}"${mode === leg.mode ? ' selected' : ''}>${esc(modeLabel(mode))}</option>`).join('');
    const rowId = `tarife-leg-${index}`;
    const routeVisible = leg.mode === 'ferry';
    const remove = legs.length > 1 ? `<button class="fare-quiet" type="button" data-remove-leg="${index}">${t('ui.fare.remove_leg', 'Kaldır')}</button>` : '';
    return `<div class="fare-leg" data-fare-leg="${index}"><div class="fare-field"><label for="${rowId}-mode">${t('ui.fare.mode_label', 'Bacak türü')}</label><select id="${rowId}-mode" data-leg-mode>${modes}</select></div>
      <div class="fare-field fare-route-field"${routeVisible ? '' : ' hidden'}><label for="${rowId}-route">${t('ui.fare.route_label', 'Vapur hattı')}</label>
        <select id="${rowId}-route" data-leg-route${routeVisible ? ' required' : ''}><option value="">${t('ui.fare.route_pick', 'Hat seçin')}</option>${routeOptions}</select><p class="fare-error" id="tarife-route-error-${index}" hidden></p></div>${remove}</div>`;
  }).join('');
}

function fieldError(root, field, message) {
  const target = field === 'days_per_week' ? root.querySelector('#tarife-days-error')
    : field === 'tariff' ? root.querySelector('#tarife-tariff-error')
      : field === 'legs' ? root.querySelector('#tarife-legs-error')
        : root.querySelector(`#tarife-route-error-${field.split('.')[1]}`);
  if (target) { target.hidden = false; target.textContent = message; }
}

function focusField(root, field) {
  if (field === 'days_per_week') root.querySelector('#tarife-days').focus();
  else if (field === 'tariff') root.querySelector('input[name="tarife-tariff"]')?.focus();
  else if (field === 'legs') root.querySelector('#tarife-add-leg').focus();
  else root.querySelector(`#tarife-leg-${field.split('.')[1]}-route`)?.focus();
}

function hideErrors(root) {
  root.querySelectorAll('.fare-error').forEach((node) => { node.hidden = true; node.textContent = ''; });
}

export function mountFare(doc) {
  const host = doc.getElementById('city-tools');
  if (!host || doc.getElementById('tarife')) return;
  if (!doc.querySelector('link[href="/css/fare.css"]')) {
    const link = doc.createElement('link');
    link.rel = 'stylesheet'; link.href = '/css/fare.css';
    doc.head.appendChild(link);
  }
  const details = doc.createElement('details');
  details.id = 'tarife'; details.className = 'more tool-detail';
  details.innerHTML = `<summary><h2 id="tarife-title">${t('ui.fare.title', 'Haftalık ulaşım maliyetim')}</h2></summary>
    <section class="fare-panel" aria-labelledby="tarife-title"><p class="fare-notice">${t('ui.fare.notice', 'Ücretler resmî sayfalardan kaydedildi; hesap bir tahmindir, resmî ücret değildir. Hangi tarifenin kartınıza uygulandığını İstanbulkart belirler.')}</p>
      <p class="fare-disclaimer">${t('ui.fare.disclaimer', 'Resmî İBB hizmeti değildir.')}</p>
      <p id="tarife-durum" class="fare-status" role="status">${t('ui.fare.open_to_load', 'Kataloğu görmek için bölümü açın.')}</p>
      <div id="tarife-form-host"></div><section id="tarife-sonuc" class="fare-result" hidden></section>
      <section id="tarife-kayit" class="fare-save"></section></section>`;
  host.appendChild(details);

  const state = { catalog: null, loaded: false, loading: false, pattern: readPattern(),
    tariff: 'tam', days: 5, roundTrip: true, legs: [{ mode: 'metro' }],
    withinWindow: false, personalized: false, saved: false, routeFallback: false };
  const status = details.querySelector('#tarife-durum');
  const formHost = details.querySelector('#tarife-form-host');
  const resultHost = details.querySelector('#tarife-sonuc');
  const saveHost = details.querySelector('#tarife-kayit');
  if (state.pattern) {
    state.days = state.pattern.days_per_week; state.roundTrip = state.pattern.round_trip;
    state.tariff = state.pattern.tariff; state.legs = state.pattern.legs.map((leg) => ({ ...leg }));
    state.withinWindow = state.pattern.within_window; state.personalized = state.pattern.personalized; state.saved = true;
  }

  function statusLine(text) {
    status.textContent = text;
    status.setAttribute('lang', currentLang());
  }

  function renderSave() {
    saveHost.innerHTML = `<label class="fare-check" for="tarife-consent"><input type="checkbox" id="tarife-consent"${state.saved ? ' checked' : ''}><span>${t('ui.fare.consent', 'Bu deseni yalnız bu cihazda sakla')}</span></label>
      <div class="fare-save-actions"><button class="fare-quiet" type="button" id="tarife-save"${state.catalog ? '' : ' disabled'}>${t('ui.fare.save', 'Sakla')}</button>
        <button class="fare-quiet" type="button" id="tarife-clear">${t('ui.fare.clear', 'Bu cihazdaki desenimi sil')}</button></div>`;
    saveHost.querySelector('#tarife-save').addEventListener('click', () => {
      const pattern = formPattern(details);
      if (!checked(saveHost.querySelector('#tarife-consent'))) {
        statusLine(t('ui.fare.consent_required', 'Saklamak için önce bu cihazda saklama kutusunu işaretleyin.')); return;
      }
      if (validateForm(pattern).length) {
        statusLine(t('ui.fare.save_invalid', 'Deseni gözden geçirin.')); return;
      }
      const saved = writePattern(pattern, true);
      if (saved) { state.saved = true; renderSave(); statusLine(t('ui.fare.saved', 'Desen bu cihazda saklandı.')); }
      else statusLine(t('ui.fare.storage_unavailable', 'Bu tarayıcıda saklama kapalı; desen sayfa yenilenince silinir.'));
    });
    saveHost.querySelector('#tarife-clear').addEventListener('click', (event) => {
      const button = event.currentTarget;
      if (button.dataset.confirm !== 'yes') {
        button.dataset.confirm = 'yes'; button.textContent = t('ui.fare.clear_confirm', 'Deseni sil');
        statusLine(t('ui.fare.clear_confirm_status', 'Silmek için aynı düğmeye bir kez daha basın.')); return;
      }
      try { window.localStorage.removeItem(STORAGE_KEY); state.saved = false; state.pattern = null;
        button.dataset.confirm = ''; renderSave(); statusLine(t('ui.fare.deleted', 'Bu cihazdaki desen silindi.')); }
      catch (error) { statusLine(t('ui.fare.storage_unavailable', 'Bu tarayıcıda saklama kapalı; desen sayfa yenilenince silinir.')); }
    });
  }

  function updateLegs() {
    const hostLegs = details.querySelector('#tarife-legs');
    hostLegs.innerHTML = legsMarkup(state.catalog, state.legs, currentLang());
    details.querySelector('#tarife-transfers').hidden = state.legs.length < 2;
    details.querySelector('#tarife-add-leg').disabled = state.legs.length >= 4;
    hostLegs.querySelectorAll('[data-leg-mode]').forEach((select, index) => select.addEventListener('change', () => {
      state.legs[index] = select.value === 'ferry' ? { mode: 'ferry', route: state.legs[index].route || '' } : { mode: select.value };
      updateLegs();
    }));
    hostLegs.querySelectorAll('[data-leg-route]').forEach((select, index) => select.addEventListener('change', () => {
      state.legs[index].route = select.value;
    }));
    hostLegs.querySelectorAll('[data-remove-leg]').forEach((button) => button.addEventListener('click', () => {
      state.legs.splice(Number(button.dataset.removeLeg), 1); updateLegs();
    }));
  }

  function drawForm() {
    if (!state.catalog) return;
    formHost.innerHTML = formMarkup(state.catalog, {
      days_per_week: state.days, round_trip: state.roundTrip, tariff: state.tariff,
      legs: state.legs, within_window: state.withinWindow, personalized: state.personalized,
    }, currentLang());
    updateLegs();
    const form = formHost.querySelector('#tarife-form');
    form.querySelector('#tarife-days').addEventListener('change', (event) => { state.days = Number(event.currentTarget.value); });
    form.querySelector('#tarife-round-trip').addEventListener('change', (event) => { state.roundTrip = event.currentTarget.checked; });
    form.querySelectorAll('input[name="tarife-tariff"]').forEach((input) => input.addEventListener('change', (event) => {
      state.tariff = event.currentTarget.value;
      form.querySelector('.fare-other-hint').hidden = state.tariff !== 'other';
    }));
    form.querySelector('.fare-other-hint').hidden = state.tariff !== 'other';
    form.querySelector('#tarife-window').addEventListener('change', (event) => { state.withinWindow = event.currentTarget.checked; });
    form.querySelector('#tarife-personalized').addEventListener('change', (event) => { state.personalized = event.currentTarget.checked; });
    form.querySelector('#tarife-add-leg').addEventListener('click', () => {
      if (state.legs.length < 4) { state.legs.push({ mode: 'metro' }); drawForm(); }
    });
    form.addEventListener('submit', async (event) => {
      event.preventDefault(); hideErrors(form);
      const pattern = formPattern(form);
      const errors = validateForm(pattern);
      if (errors.length) {
        for (const error of errors) fieldError(form, error.field, errorMessage(error));
        focusField(form, errors[0].field);
        return;
      }
      state.pattern = pattern;
      if (MOCK) { statusLine(t('ui.fare.mock', 'Örnek veri kipinde ücret hesabı kapalı.')); return; }
      statusLine(t('ui.fare.estimating', 'Hesaplanıyor.'));
      try {
        const response = await post('/api/fare/estimate', pattern);
        const estimate = response.estimate;
        resultHost.innerHTML = resultMarkup(estimate, state.catalog, currentLang());
        resultHost.hidden = false;
        resultHost.dataset.enter = 'true';
        statusLine(t('ui.fare.calculated', 'Hesaplandı.'));
      } catch (error) {
        const fields = error.fields || [];
        if (fields.length) { for (const item of fields) fieldError(form, item.field, errorMessage(item)); }
        else statusLine(t('ui.fare.estimate_failed', 'Hesaplama yapılamadı. Kurumun resmî sayfasına ya da 153’e bakın.'));
      }
    });
    renderSave();
  }

  async function calculateSaved() {
    if (!state.pattern || !state.catalog || MOCK) return;
    const savedPattern = { ...state.pattern, legs: state.pattern.legs.map((leg) => ({ ...leg })) };
    try {
      const response = await post('/api/fare/estimate', savedPattern);
      resultHost.innerHTML = resultMarkup(response.estimate, state.catalog, currentLang());
      resultHost.hidden = false;
      if (!state.routeFallback) statusLine(t('ui.fare.calculated', 'Hesaplandı.'));
    } catch (error) { statusLine(t('ui.fare.estimate_failed', 'Hesaplama yapılamadı. Kurumun resmî sayfasına ya da 153’e bakın.')); }
  }

  async function loadCatalog(language = currentLang()) {
    if (MOCK) { statusLine(t('ui.fare.mock', 'Örnek veri kipinde ücret hesabı kapalı.')); return; }
    if (state.loading) return;
    state.loading = true;
    statusLine(t('ui.fare.loading', 'Tarife kaynakları yükleniyor.'));
    try {
      const data = await get('/api/fare/catalog', { lang: language });
      state.catalog = data;
      state.loaded = true;
      if (state.pattern) {
        state.routeFallback = false;
        for (const leg of state.pattern.legs) {
          if (leg.mode === 'ferry' && !data.ferry_routes.some((route) => route.id === leg.route)) {
            leg.mode = 'other'; delete leg.route; state.routeFallback = true;
          }
        }
        state.legs = state.pattern.legs.map((leg) => ({ ...leg }));
      }
      drawForm();
      statusLine(state.routeFallback
        ? t('ui.fare.route_missing', 'Saklı desendeki vapur hattı katalogda yok; bu bacak Diğer olarak gösteriliyor.')
        : t('ui.fare.ready', 'Deseni girip Hesapla düğmesine basın.'));
      await calculateSaved();
    } catch (error) {
      state.loaded = false;
      status.innerHTML = `${t('ui.fare.catalog_failed', 'Tarife kataloğu alınamadı.')} <a href="tel:153">153</a>`;
      status.setAttribute('lang', currentLang());
    } finally { state.loading = false; }
  }

  renderSave();
  details.addEventListener('toggle', () => { if (details.open && !state.loaded && !state.loading) void loadCatalog(); });
  onLang((language) => {
    details.querySelector('#tarife-title').textContent = t('ui.fare.title', 'Haftalık ulaşım maliyetim');
    details.querySelector('.fare-notice').textContent = t('ui.fare.notice', 'Ücretler resmî sayfalardan kaydedildi; hesap bir tahmindir, resmî ücret değildir. Hangi tarifenin kartınıza uygulandığını İstanbulkart belirler.');
    details.querySelector('.fare-disclaimer').textContent = t('ui.fare.disclaimer', 'Resmî İBB hizmeti değildir.');
    if (!state.catalog) {
      return;
    }
    state.loaded = false;
    void loadCatalog(language);
  });
}

if (typeof document !== 'undefined') mountFare(document);
