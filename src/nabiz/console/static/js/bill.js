/* Bill explainer (E61). Only the public catalogue is fetched. User-entered values and drafts stay in this tab;
 * saving requires an explicit checkbox and writes only to this device's localStorage. */

import { MOCK, get } from './api.js';
import { currentLang, onLang, t } from './i18n_text.js';
import { esc } from './format.js';
import { icon } from './icons.js';

const STORAGE_KEY = 'nabiz.bill.v1';
const CATALOG_PATH = '/api/bill/catalog';
let storageUnavailable = false;


export function parseAmount(raw) {
  if (typeof raw === 'number') return Number.isFinite(raw) ? raw : null;
  let value = String(raw ?? '').trim().replace(/\s/g, '');
  if (!value) return null;
  if (value.includes(',')) {
    if (!/^\d{1,3}(?:\.\d{3})*(?:,\d{1,2})?$/.test(value) && !/^\d+(?:,\d{1,2})?$/.test(value)) return null;
    value = value.replace(/\./g, '').replace(',', '.');
  } else if (!/^\d+(?:\.\d{1,2})?$/.test(value)) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function utcDay(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(value || ''))) return NaN;
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value ? date.getTime() : NaN;
}

export function periodDays(entry) {
  const start = utcDay(entry?.start);
  const end = utcDay(entry?.end);
  return Number.isFinite(start) && Number.isFinite(end) && end > start ? Math.round((end - start) / 86400000) : 0;
}

function amountWithin(value, max) {
  const parsed = parseAmount(value);
  return parsed !== null && parsed >= 0 && parsed <= max && Math.round(parsed * 100) === parsed * 100;
}

export function checkEntry(entry) {
  const errors = [];
  if (!['iski', 'igdas'].includes(entry?.agency)) errors.push({ field: 'agency', code: 'required' });
  const days = periodDays(entry);
  if (!Number.isFinite(utcDay(entry?.start))) errors.push({ field: 'start', code: 'date' });
  if (!Number.isFinite(utcDay(entry?.end))) errors.push({ field: 'end', code: 'date' });
  if (!days) errors.push({ field: 'end', code: 'order' });
  else if (days < 1 || days > 100) errors.push({ field: 'end', code: 'length' });
  const consumption = parseAmount(entry?.consumption);
  if (consumption === null || consumption < 0 || consumption > 100000) errors.push({ field: 'consumption', code: 'range' });
  if (!Array.isArray(entry?.items) || entry.items.length === 0) errors.push({ field: 'items', code: 'required' });
  for (const [index, item] of (entry?.items || []).entries()) {
    const itemId = String(item?.id || '');
    if (!itemId) errors.push({ field: `item-${index}`, code: 'required' });
    if (!amountWithin(item?.amount, 1000000)) errors.push({ field: `amount-${index}`, code: 'amount' });
    const label = String(item?.label || '');
    if ((itemId === 'diger' || itemId === 'igdas_diger') && !label.trim()) errors.push({ field: `name-${index}`, code: 'required' });
    if (label.length > 60) errors.push({ field: `name-${index}`, code: 'length' });
    if (/\p{N}{6,}/u.test(label)) errors.push({ field: `name-${index}`, code: 'digits' });
  }
  if (entry?.total !== undefined && entry.total !== '' && !amountWithin(entry.total, 1000000)) {
    errors.push({ field: 'total', code: 'amount' });
  }
  return { ok: errors.length === 0, errors };
}

export function dailyAverage(entry) {
  const days = periodDays(entry);
  const value = parseAmount(entry?.consumption);
  return days && value !== null ? Math.round((value / days + Number.EPSILON) * 100) / 100 : 0;
}

export function monthlyEquivalent(entry) {
  const days = periodDays(entry);
  const consumption = parseAmount(entry?.consumption);
  if (!days || consumption === null) return 0;
  return Math.round((consumption / days * 30 + Number.EPSILON) * 10) / 10;
}

export function tierFor(value, rows = []) {
  const amount = Number(value);
  if (!Number.isFinite(amount) || amount < 0 || !Array.isArray(rows) || rows.length !== 3) return null;
  if (amount <= 15) return rows[0].tier;
  if (amount <= 30) return rows[1].tier;
  return rows[2].tier;
}

function itemAmountMap(entry) {
  const totals = new Map();
  for (const item of entry?.items || []) {
    const key = item.id === 'diger' || item.id === 'igdas_diger' ? `label:${item.label || ''}` : `id:${item.id}`;
    totals.set(key, (totals.get(key) || 0) + (parseAmount(item.amount) || 0));
  }
  return totals;
}

function direction(delta) {
  if (Math.abs(delta) < 0.01) return 'same';
  return delta > 0 ? 'up' : 'down';
}

export function compare(current, previous) {
  const daysA = periodDays(current);
  const daysB = periodDays(previous);
  const consumptionA = parseAmount(current?.consumption) || 0;
  const consumptionB = parseAmount(previous?.consumption) || 0;
  const dailyA = dailyAverage(current);
  const dailyB = dailyAverage(previous);
  const aItems = itemAmountMap(current);
  const bItems = itemAmountMap(previous);
  const items = [];
  for (const [key, a] of aItems) {
    if (!bItems.has(key)) continue;
    const b = bItems.get(key);
    const delta = Math.round((a - b + Number.EPSILON) * 100) / 100;
    const value = current.items.find((item) => (
      (item.id === 'diger' || item.id === 'igdas_diger' ? `label:${item.label || ''}` : `id:${item.id}`) === key
    ));
    items.push({ id: value?.id, label: value?.label, a, b, delta, direction: direction(delta) });
  }
  const dailyRatio = dailyB > 0 ? dailyA / dailyB : null;
  return {
    days: { a: daysA, b: daysB, delta: daysA - daysB },
    consumption: { a: consumptionA, b: consumptionB, delta: consumptionA - consumptionB },
    daily: { a: dailyA, b: dailyB, delta: Math.round((dailyA - dailyB + Number.EPSILON) * 100) / 100, ratio: dailyRatio },
    items,
  };
}

function catalogItem(catalog, agency, id) {
  return (catalog?.items || []).find((item) => item.agency === agency && item.id === id) || null;
}

function concept(catalog, id) {
  return (catalog?.concepts || []).find((value) => value.id === id) || null;
}

export function pointsToAsk(current, previous, catalog) {
  const points = [];
  const unknown = (current?.items || []).some((item) => {
    const found = catalogItem(catalog, current.agency, item.id);
    return !found?.source || item.id === 'diger' || item.id === 'igdas_diger';
  });
  if (unknown) points.push({ id: 'unknown_item', text_key: 'ui.bill.pointUnknown', source: null });
  const itemTotal = (current?.items || []).reduce((sum, item) => sum + (parseAmount(item.amount) || 0), 0);
  const total = parseAmount(current?.total);
  if (total !== null && Math.abs(total - itemTotal) > 1) {
    points.push({ id: 'sum_mismatch', text_key: 'ui.bill.pointSum', source: null });
  }
  if (previous && Math.abs(periodDays(current) - periodDays(previous)) > 5) {
    points.push({
      id: 'period_length',
      text_key: 'ui.bill.pointPeriod',
      source: current.agency === 'iski' ? concept(catalog, 'donem_ortalamasi')?.source || null : null,
    });
  }
  if (previous) {
    const ratio = dailyAverage(previous) > 0 ? dailyAverage(current) / dailyAverage(previous) : null;
    if (ratio !== null && ratio >= 1.5) {
      points.push({
        id: 'daily_up',
        text_key: current.agency === 'iski' ? 'ui.bill.pointDaily' : 'ui.bill.pointDailyGas',
        source: current.agency === 'iski' ? concept(catalog, 'sayac_olcum')?.source || null : null,
      });
    }
  }
  if (current?.agency === 'iski' && current.leak === true) {
    points.push({ id: 'hidden_leak', text_key: 'ui.bill.pointLeak', source: concept(catalog, 'gizli_kacak')?.source || null });
  }
  return points.slice(0, 5);
}

export function draftText(current, points, lang = currentLang()) {
  const pointLines = (points || []).map((point) => {
    if (point.id === 'unknown_item') return t('ui.bill.draftPointUnknown', 'Bu kalemin ne olduğunu kurumunuza sorabilir misiniz?');
    if (point.id === 'sum_mismatch') return t('ui.bill.draftPointSum', 'Girdiğim kalemlerin toplamı faturadaki toplamla uyuşmuyor; atlanan bir satır olup olmadığını açıklar mısınız?');
    if (point.id === 'period_length') return t('ui.bill.draftPointPeriod', 'Dönemlerin farklı uzunlukta olduğunu dikkate alarak günlük ortalama tüketimi açıklayabilir misiniz?');
    if (point.id === 'daily_up') return t('ui.bill.draftPointDaily', 'Sayaç okuma tarihini ve endeksini açıklayabilir misiniz?');
    if (point.id === 'hidden_leak') return t('ui.bill.draftPointLeak', 'İç tesisattaki gizli su kaçağı düzenlemesinin koşullarını ve uygulanıp uygulanmayacağını açıklayabilir misiniz?');
    return t('ui.bill.draftPointOther', 'Bu kalem hakkında bilgi rica ederim.');
  });
  const unit = current?.unit || (current?.agency === 'igdas' ? 'm³' : 'm³');
  const consumption = formatNumber(current?.consumption, lang === 'en' ? 'en' : 'tr', 2);
  const period = `${current?.start || ''} ${t('ui.bill.draftTo', 'ile')} ${current?.end || ''}`;
  const opening = t('ui.bill.draftHello', 'Merhaba,');
  const intro = t('ui.bill.draftIntro', 'Faturamda, [abone numaranız] için {period} dönem tüketimi {amount} {unit} görünüyor.', {
    period, amount: consumption, unit,
  });
  const closing = t('ui.bill.draftClose', 'Bilgi rica ederim.');
  return [opening, intro, ...pointLines, closing].join('\n\n');
}

function formatNumber(value, lang = currentLang(), digits = 2) {
  const number = typeof value === 'number' ? value : parseAmount(value);
  if (number === null || !Number.isFinite(number)) return '';
  return number.toLocaleString(lang === 'en' ? 'en-GB' : 'tr-TR', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function sourceDate(value, lang) {
  const date = new Date(value || '');
  return Number.isFinite(date.getTime()) ? date.toLocaleDateString(lang === 'en' ? 'en-GB' : 'tr-TR') : '';
}

function sourceMarkup(source, agencyName, lang) {
  if (!source) return `<p class="bill-no-source" lang="${lang}">${esc(t('ui.bill.noSource', 'Kaynak henüz yok.'))}</p>`;
  const title = `<span lang="tr">${esc(agencyName)} · ${esc(source.title)}</span>`;
  const page = source.page ? ` · ${esc(t('ui.bill.page', 's. {page}', { page: source.page }))}` : '';
  const captured = esc(t('ui.bill.recorded', 'kaydedildi: {date}', { date: sourceDate(source.fetched_at, lang) }));
  const external = icon('external-link');
  return `<details class="bill-source"><summary>${esc(t('ui.bill.sourceLine', 'Kaynak'))}</summary>
    <p class="bill-source-line" lang="${lang}">${title}${page} · ${captured} · <a href="${esc(source.url)}" target="_blank" rel="noopener">${external}<span>${esc(t('ui.bill.openSource', 'Kaynağı aç'))}</span><span class="sr-only">${esc(t('ui.bill.newTab', 'yeni sekmede açılır'))}</span></a></p>
    <details class="bill-quote"><summary>${esc(t('ui.bill.sourceQuote', 'Kaynaktaki metin'))}</summary><blockquote lang="tr">${esc(source.quote)}</blockquote></details>
  </details>`;
}

function pointSourceMarkup(point, catalog, agencyName, lang) {
  const source = point.source;
  if (!source) return '';
  return sourceMarkup(source, agencyName, lang);
}

function moveIcon(directionValue) {
  const names = { up: 'trending-up', down: 'trending-down', same: 'equal' };
  return icon(names[directionValue] || 'equal');
}

export function readBills() {
  try {
    const value = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || 'null');
    storageUnavailable = false;
    if (!value || value.version !== 1 || !Array.isArray(value.bills)) return [];
    return value.bills
      .filter((item) => item && typeof item === 'object' && typeof item.id === 'string' && typeof item.agency === 'string')
      .slice(0, 12);
  } catch {
    storageUnavailable = true;
    return [];
  }
}

export function writeBills(bills) {
  try {
    if (bills.length) window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ version: 1, bills: bills.slice(0, 12) }));
    else window.localStorage.removeItem(STORAGE_KEY);
    storageUnavailable = false;
    return true;
  } catch {
    storageUnavailable = true;
    return false;
  }
}

function priorBill(current, bills) {
  const currentStart = utcDay(current.start);
  return bills
    .filter((bill) => bill.id !== current.id && bill.agency === current.agency && utcDay(bill.end) <= currentStart)
    .sort((a, b) => utcDay(b.end) - utcDay(a.end))[0] || null;
}

function directionText(value) {
  if (value === 'up') return t('ui.bill.increased', 'arttı');
  if (value === 'down') return t('ui.bill.decreased', 'azaldı');
  return t('ui.bill.same', 'aynı');
}

export function mountBill(doc) {
  const host = doc.getElementById('hesabim');
  if (!host || doc.getElementById('fatura')) return;

  const link = doc.createElement('link');
  if (!doc.querySelector('link[data-bill-style], link[href="/css/bill.css"]')) {
    link.rel = 'stylesheet';
    link.href = '/css/bill.css';
    link.dataset.billStyle = 'true';
    (doc.head || doc.documentElement).append(link);
  }

  const section = doc.createElement('details');
  section.id = 'fatura';
  section.className = 'more tool-detail bill-tool';
  section.innerHTML = `<summary><h2 id="fatura-title">${esc(t('ui.bill.title', 'Faturamı anla'))}</h2></summary>
    <section class="bill-inner" aria-labelledby="fatura-title">
      <p class="bill-notice" data-bill-notice></p>
      <p class="bill-status" role="status" aria-live="polite" data-bill-status></p>
      <form id="fatura-form" autocomplete="off" novalidate hidden></form>
      <section id="fatura-sonuc" aria-labelledby="bill-result-title" hidden></section>
      <section id="fatura-kayitlar" aria-labelledby="bill-saved-title"></section>
    </section>`;
  host.append(section);

  const form = section.querySelector('#fatura-form');
  const result = section.querySelector('#fatura-sonuc');
  const status = section.querySelector('[data-bill-status]');
  let catalog = null;
  let catalogError = null;
  let catalogRequest = 0;
  let formData = { agency: '', start: '', end: '', consumption: '', unit: 'm³', total: '', items: [], leak: false, singleHome: false };
  let current = null;
  let previous = null;
  let points = [];
  let resultVisible = false;
  let entered = false;
  let draftValue = '';
  let draftEdited = false;
  let clearing = false;

  function agencyLabel(agency) {
    return catalog?.agencies?.[agency]?.name || (agency === 'iski' ? t('ui.bill.iski', 'İSKİ') : t('ui.bill.igdas', 'İGDAŞ'));
  }

  function readForm() {
    const selectedAgency = form.querySelector('input[name="agency"]:checked')?.value || formData.agency;
    const lineNodes = [...form.querySelectorAll('.bill-line')];
    const lines = lineNodes.map((node) => ({
      id: node.querySelector('.bill-item-select')?.value || '',
      label: node.querySelector('.bill-item-name')?.value || '',
      amount: node.querySelector('.bill-amount')?.value || '',
    }));
    return {
      agency: selectedAgency || '',
      start: form.querySelector('#bill-start')?.value || '',
      end: form.querySelector('#bill-end')?.value || '',
      consumption: form.querySelector('#bill-consumption')?.value || '',
      unit: selectedAgency === 'iski' ? 'm³' : form.querySelector('#bill-unit')?.value || formData.unit || 'm³',
      items: lines.length ? lines : formData.items,
      total: form.querySelector('#bill-total')?.value || '',
      leak: Boolean(form.querySelector('#bill-leak')?.checked),
      singleHome: Boolean(form.querySelector('#bill-single-home')?.checked),
    };
  }

  function translatedForm() {
    const agency = formData.agency;
    const itemOptions = agency ? (catalog?.items || []).filter((item) => item.agency === agency) : [];
    const lines = agency ? Math.max(1, formData.items.length) : 0;
    const lineMarkup = Array.from({ length: lines }, (_, index) => {
      const value = formData.items[index] || { id: '', label: '', amount: '' };
      const options = itemOptions.map((item) => `<option value="${esc(item.id)}"${value.id === item.id ? ' selected' : ''}>${esc(item.label)}</option>`).join('');
      const other = value.id === 'diger' || value.id === 'igdas_diger';
      const nameField = other ? `<label class="bill-field bill-item-name-wrap" for="bill-item-name-${index}"><span>${esc(t('ui.bill.itemName', 'Kalem adı'))}</span><input id="bill-item-name-${index}" class="bill-item-name" maxlength="60" value="${esc(value.label)}" aria-describedby="bill-error-name-${index}"><span class="bill-error" id="bill-error-name-${index}" data-error="name-${index}"></span></label>` : '';
      return `<fieldset class="bill-line" data-index="${index}"><legend>${esc(t('ui.bill.itemNumber', 'Kalem {number}', { number: index + 1 }))}</legend>
        <label class="bill-field" for="bill-item-${index}"><span>${esc(t('ui.bill.billItem', 'Fatura kalemi'))}</span><select id="bill-item-${index}" class="bill-item-select" aria-describedby="bill-error-item-${index}"><option value="">${esc(t('ui.bill.chooseItem', 'Kalem seçin'))}</option>${options}</select><span class="bill-error" id="bill-error-item-${index}" data-error="item-${index}"></span></label>
        ${nameField}
        <label class="bill-field" for="bill-amount-${index}"><span>${esc(t('ui.bill.amount', 'Tutar (TL)'))}</span><input id="bill-amount-${index}" class="bill-amount" inputmode="decimal" value="${esc(value.amount)}" aria-describedby="bill-error-amount-${index}"><span class="bill-error" id="bill-error-amount-${index}" data-error="amount-${index}"></span></label>
        ${lines > 1 ? `<button class="btn btn-quiet bill-remove" type="button" data-remove-line="${index}">${esc(t('ui.bill.removeLine', 'Kalemi sil'))}</button>` : ''}
      </fieldset>`;
    }).join('');
    const agencyField = `<fieldset class="bill-agencies"><legend>${esc(t('ui.bill.agencyLabel', 'Kurum'))}</legend>
      <label class="bill-choice"><input type="radio" name="agency" value="iski" aria-describedby="bill-error-agency"${agency === 'iski' ? ' checked' : ''}><span>${esc(agencyLabel('iski'))}</span></label>
      <label class="bill-choice"><input type="radio" name="agency" value="igdas" aria-describedby="bill-error-agency"${agency === 'igdas' ? ' checked' : ''}><span>${esc(agencyLabel('igdas'))}</span></label>
      <span class="bill-error" id="bill-error-agency" data-error="agency"></span></fieldset>`;
    const unitField = agency === 'igdas' ? `<label class="bill-field" for="bill-unit"><span>${esc(t('ui.bill.unitLabel', 'Tüketim birimi'))}</span><select id="bill-unit"><option value="m³"${formData.unit === 'm³' ? ' selected' : ''}>m³</option><option value="kWh"${formData.unit === 'kWh' ? ' selected' : ''}>kWh</option></select></label>` : '';
    const sourceUnavailable = catalogError ? `<p class="bill-status" role="status">${esc(catalogError)}</p>` : '';
    return `<div class="bill-form-grid">
      ${agencyField}
      <label class="bill-field" for="bill-start"><span>${esc(t('ui.bill.periodStart', 'Dönem başlangıcı'))}</span><input id="bill-start" type="date" value="${esc(formData.start)}" aria-describedby="bill-error-start"><span class="bill-error" id="bill-error-start" data-error="start"></span></label>
      <label class="bill-field" for="bill-end"><span>${esc(t('ui.bill.periodEnd', 'Dönem bitişi'))}</span><input id="bill-end" type="date" value="${esc(formData.end)}" aria-describedby="bill-error-end"><span class="bill-error" id="bill-error-end" data-error="end"></span></label>
      <label class="bill-field" for="bill-consumption"><span>${esc(t('ui.bill.consumption', 'Tüketim'))}</span><span class="bill-consumption-row"><input id="bill-consumption" inputmode="decimal" value="${esc(formData.consumption)}" aria-describedby="bill-error-consumption"><span data-unit-label>${esc(agency === 'igdas' ? formData.unit : 'm³')}</span></span><span class="bill-error" id="bill-error-consumption" data-error="consumption"></span></label>
      ${unitField}
      <div class="bill-lines" data-bill-lines>${lines ? lineMarkup : `<p class="bill-hint">${esc(t('ui.bill.chooseAgency', 'Kalemleri görmek için önce kurum seçin.'))}</p>`}</div>
      ${agency ? `<button class="btn btn-quiet bill-add" type="button" data-add-line>${esc(t('ui.bill.addLine', 'Kalem ekle'))}</button>` : ''}
      <label class="bill-field" for="bill-total"><span>${esc(t('ui.bill.optionalTotal', 'İsteğe bağlı fatura toplamı (TL)'))}</span><input id="bill-total" inputmode="decimal" value="${esc(formData.total)}" aria-describedby="bill-error-total"><span class="bill-error" id="bill-error-total" data-error="total"></span></label>
      ${agency === 'iski' ? `<label class="bill-choice bill-leak"><input id="bill-leak" type="checkbox"${formData.leak ? ' checked' : ''}><span>${esc(t('ui.bill.leakCheck', 'Tesisatta kaçak ya da arıza fark ettim'))}</span></label>` : ''}
      ${agency === 'iski' ? `<label class="bill-choice bill-single-home"><input id="bill-single-home" type="checkbox"${formData.singleHome ? ' checked' : ''}><span>${esc(t('ui.bill.singleHome', 'Konut aboneliği, tek konut'))}</span></label>` : ''}
    </div>
    ${sourceUnavailable}
    <div class="bill-actions"><button class="btn btn-primary" type="submit">${esc(t('ui.bill.explain', 'Açıkla'))}</button></div>`;
  }

  function renderForm() {
    form.innerHTML = translatedForm();
    form.hidden = !catalog || resultVisible;
    form.setAttribute('aria-labelledby', 'fatura-title');
  }

  function renderPoint(point) {
    const text = point.id === 'unknown_item' ? t('ui.bill.pointUnknown', 'Bu kalemin ne olduğunu kurumunuza sorabilirsiniz.')
      : point.id === 'sum_mismatch' ? t('ui.bill.pointSum', 'Girdiğiniz kalemlerin toplamı faturadaki toplamla tutmuyor; atlanan bir satır olabilir.')
        : point.id === 'period_length' ? t('ui.bill.pointPeriod', 'Dönemler farklı uzunlukta; karşılaştırmada günlük ortalamaya bakın.')
          : point.text_key === 'ui.bill.pointDailyGas' ? t('ui.bill.pointDailyGas', 'Günlük ortalama tüketim belirgin arttı; sayaç okuma tarihini ve endeksini sorabilirsiniz.')
            : point.id === 'daily_up' ? t('ui.bill.pointDaily', 'Günlük ortalama tüketim belirgin arttı; sayaç okuma tarihini ve endeksini sorabilirsiniz. Sayacın ölçüme gönderilmesini isteyebilirsiniz; yönetmeliğe göre sayaç doğru çıkarsa ölçüm bedelleri size tahakkuk ettirilir.')
              : t('ui.bill.pointLeak', 'Yönetmelikte iç tesisattaki gizli su kaçağı için bir düzenleme var; koşullarını ve uygulanıp uygulanmayacağını İSKİ belirler.');
    const designNote = point.id === 'daily_up'
      ? `<p class="bill-hint">${esc(t('ui.bill.designThreshold', '1,5 oranı Nabız tasarım eşiğidir; İSKİ ölçütü değildir.'))}</p>` : '';
    return `<li><p>${esc(text)}</p>${designNote}${pointSourceMarkup(point, catalog, agencyLabel(current.agency), lang)}</li>`;
  }

  function renderItemExplanation(item, lang) {
    const stored = catalogItem(catalog, current.agency, item.id);
    const custom = item.id === 'diger' || item.id === 'igdas_diger';
    const label = custom ? item.label : stored?.label || item.id;
    const explanation = stored?.explain || t('ui.bill.noSourceText', 'Bu kalemin açıklaması Nabız kaynaklarında yok; kurumunuza sorun.');
    const source = stored?.source || null;
    return `<article class="bill-explanation"><h4>${esc(label)}</h4><p>${esc(explanation)}</p>${sourceMarkup(source, agencyLabel(current.agency), lang)}</article>`;
  }

  function tariffMarkup(lang) {
    if (!catalog?.tariff || current.agency !== 'iski') return '';
    const monthly = current.singleHome ? monthlyEquivalent(current) : null;
    const selectedTier = monthly === null ? null : tierFor(monthly, catalog.tariff.rows);
    const rows = catalog.tariff.rows.map((row) => {
      const range = row.tier === 3 ? t('ui.bill.rangeLast', '31 ve üzeri') : row.range;
      const currentTier = row.tier === selectedTier;
      const marker = currentTier ? `<span class="bill-tier-current">${esc(t('ui.bill.tierCurrent', 'Girdiğiniz tüketim bu aralıkta'))}</span>` : '';
      return `<tr${currentTier ? ' aria-current="true"' : ''}><th scope="row">${esc(t('ui.bill.tierRange', 'Kademe {tier}: {range} m³/ay', { tier: row.tier, range }))}${marker}</th><td>${formatNumber(row.water, lang)}</td><td>${formatNumber(row.wastewater, lang)}</td><td>${formatNumber(row.total, lang)}</td></tr>`;
    }).join('');
    const mobileRows = catalog.tariff.rows.map((row) => {
      const range = row.tier === 3 ? t('ui.bill.rangeLast', '31 ve üzeri') : row.range;
      const currentTier = row.tier === selectedTier;
      const marker = currentTier ? `<dd>${esc(t('ui.bill.tierCurrent', 'Girdiğiniz tüketim bu aralıkta'))}</dd>` : '';
      return `<div${currentTier ? ' aria-current="true"' : ''}><dt>${esc(t('ui.bill.tierRange', 'Kademe {tier}: {range} m³/ay', { tier: row.tier, range }))}</dt>${marker}<dd>${esc(t('ui.bill.waterRate', 'Su birim fiyatı'))}: ${formatNumber(row.water, lang)} TL/m³</dd><dd>${esc(t('ui.bill.wastewaterRate', 'Atık su birim fiyatı'))}: ${formatNumber(row.wastewater, lang)} TL/m³</dd><dd>${esc(t('ui.bill.totalRate', 'Toplam birim fiyat'))}: ${formatNumber(row.total, lang)} TL/m³</dd></div>`;
    }).join('');
    const currentNote = selectedTier ? `<p class="bill-hint">${esc(t('ui.bill.monthlyEquivalent', 'Girdiğiniz tüketimin 30 güne karşılığı: {value} m³.', { value: formatNumber(monthly, lang, 1) }))} ${esc(t('ui.bill.tierNotice', 'Bu bir hesap değildir; faturadaki kademe İSKİ’nin okuma dönemine göre belirlenir.'))}</p>` : '';
    return `<details class="bill-tariff"><summary>${esc(t('ui.bill.tariffTitle', '2026 konut su tarifesi (KDV hariç, TL/m³)'))}</summary>
      ${currentNote}<div class="bill-table-wrap"><table><caption>${esc(t('ui.bill.tariffTitle', '2026 konut su tarifesi (KDV hariç, TL/m³)'))}</caption><thead><tr><th scope="col">${esc(t('ui.bill.tier', 'Kademe'))}</th><th scope="col">${esc(t('ui.bill.waterRate', 'Su birim fiyatı'))}</th><th scope="col">${esc(t('ui.bill.wastewaterRate', 'Atık su birim fiyatı'))}</th><th scope="col">${esc(t('ui.bill.totalRate', 'Toplam birim fiyat'))}</th></tr></thead><tbody>${rows}</tbody></table></div>
      <dl class="bill-tariff-narrow">${mobileRows}</dl><p>${esc(catalog.tariff.note_human_right)}</p>${sourceMarkup(catalog.tariff.source, agencyLabel('iski'), lang)}
      <p class="bill-hint">${esc(t('ui.bill.tariffCaveat', 'Bu tablo bir hesap değildir; faturadaki tutar KDV, düşümler ve abone türüne göre değişir.'))}</p></details>`;
  }

  function renderComparison(lang) {
    if (!previous) return '';
    const values = compare(current, previous);
    const unit = current.unit || 'm³';
    const trend = (delta, valueUnit) => {
      const trendDirection = direction(delta);
      return `<span class="bill-trend">${moveIcon(trendDirection)} ${esc(directionText(trendDirection))} · ${esc(formatNumber(Math.abs(delta), lang))} ${esc(valueUnit)}</span>`;
    };
    const itemRows = values.items.map((row) => `<tr><th scope="row">${esc(row.label || catalogItem(catalog, current.agency, row.id)?.label || row.id)}</th><td>${formatNumber(row.a, lang)} TL</td><td>${formatNumber(row.b, lang)} TL</td><td>${trend(row.delta, 'TL')}</td></tr>`).join('');
    const itemList = values.items.map((row) => `<div><dt>${esc(row.label || catalogItem(catalog, current.agency, row.id)?.label || row.id)}</dt><dd>${formatNumber(row.a, lang)} TL · ${esc(t('ui.bill.versus', 'önceki'))} ${formatNumber(row.b, lang)} TL · ${trend(row.delta, 'TL')}</dd></div>`).join('');
    const sections = [
      [t('ui.bill.days', 'Dönem gün sayısı'), values.days.a, values.days.b, trend(values.days.delta, t('ui.bill.daysUnit', 'gün'))],
      [t('ui.bill.consumption', 'Tüketim'), formatNumber(values.consumption.a, lang), formatNumber(values.consumption.b, lang), trend(values.consumption.delta, unit)],
      [t('ui.bill.dailyAverage', 'Günlük ortalama'), formatNumber(values.daily.a, lang), formatNumber(values.daily.b, lang), trend(values.daily.delta, `${unit}/${t('ui.bill.daysUnit', 'gün')}`)],
    ];
    const tableRows = sections.map(([label, a, b, change]) => `<tr><th scope="row">${esc(label)}</th><td>${a}</td><td>${b}</td><td>${change}</td></tr>`).join('') + itemRows;
    const definitionRows = sections.map(([label, a, b, change]) => `<div><dt>${esc(label)}</dt><dd>${a} · ${esc(t('ui.bill.versus', 'önceki'))} ${b} · ${change}</dd></div>`).join('') + itemList;
    return `<section class="bill-compare" aria-labelledby="bill-compare-title"><h3 id="bill-compare-title">${esc(t('ui.bill.compareTitle', 'Önceki kayıtla kıyas'))}</h3>
      <p class="bill-hint">${esc(t('ui.bill.compareContext', 'Kıyas, bu cihazdaki aynı kurumun önceki kaydıyla yapılır.'))}</p>
      <div class="bill-compare-wide"><table><caption>${esc(t('ui.bill.compareTitle', 'Önceki kayıtla kıyas'))}</caption><thead><tr><th scope="col">${esc(t('ui.bill.measure', 'Ölçü'))}</th><th scope="col">${esc(t('ui.bill.currentBill', 'Bu fatura'))}</th><th scope="col">${esc(t('ui.bill.previousBill', 'Önceki fatura'))}</th><th scope="col">${esc(t('ui.bill.difference', 'Fark'))}</th></tr></thead><tbody>${tableRows}</tbody></table></div>
      <dl class="bill-compare-narrow">${definitionRows}</dl></section>`;
  }

  function renderChannels(lang) {
    const agency = catalog?.agencies?.[current.agency];
    const official = agency?.url || '';
    const channel = agency?.channel || '153';
    const links = [];
    if (current.agency === 'iski' && agency?.channel_url) {
      links.push(`<a href="${esc(agency.channel_url)}" target="_blank" rel="noopener">${esc(t('ui.bill.alo185', 'İSKİ Alo 185'))}<span class="sr-only">${esc(t('ui.bill.newTab', 'yeni sekmede açılır'))}</span></a>`);
      links.push(`<a href="tel:185">${esc(t('ui.bill.call185', '185’i ara'))}</a>`);
    } else if (official) {
      links.push(`<a href="${esc(official)}" target="_blank" rel="noopener">${esc(agency?.name || current.agency)}<span class="sr-only">${esc(t('ui.bill.newTab', 'yeni sekmede açılır'))}</span></a>`);
    }
    links.push(`<a href="tel:${esc(channel)}">${esc(t('ui.bill.call153', '153’ü ara'))}</a>`);
    return `<section class="bill-channels" aria-labelledby="bill-channels-title"><h3 id="bill-channels-title">${esc(t('ui.bill.officialChannels', 'Resmî kanallar'))}</h3><p>${links.join(' · ')}</p></section>`;
  }

  function renderResult() {
    if (!current || !resultVisible) {
      result.hidden = true;
      result.innerHTML = '';
      return;
    }
    const lang = currentLang();
    const agencyName = agencyLabel(current.agency);
    const dayCount = periodDays(current);
    const average = dailyAverage(current);
    const explanations = current.items.map((item) => renderItemExplanation(item, lang)).join('');
    const pointBlock = points.length ? `<section class="bill-points" aria-labelledby="bill-points-title"><h3 id="bill-points-title">${esc(t('ui.bill.pointsTitle', 'Sorulabilecek noktalar'))}</h3><ol>${points.map((point) => renderPoint(point, lang)).join('')}</ol></section>` : '';
    const draft = draftValue || draftText(current, points, lang);
    const igdasNote = current.agency === 'igdas' ? `<p class="bill-hint">${esc(t('ui.bill.igdasNotice', 'İGDAŞ faturası için Nabız kaynaklarında açıklama yok.'))}</p>` : '';
    const savedLabel = t('ui.bill.savedBill', 'Bu faturayı yalnız bu cihazda sakla');
    result.innerHTML = `<h3 id="bill-result-title" tabindex="-1">${esc(t('ui.bill.resultTitle', 'Açıklama'))}</h3>
      <p class="bill-disclaimer">${esc(catalog.disclaimer)}</p>
      <p class="bill-summary">${esc(t('ui.bill.periodSummary', '{days} gün; günlük ortalama {average} {unit}/gün.', { days: dayCount, average: formatNumber(average, lang), unit: current.unit || 'm³' }))}</p>
      <div class="bill-explanations">${explanations}</div>
      ${igdasNote}${renderComparison(lang)}${pointBlock}${tariffMarkup(lang)}
      <section class="bill-draft" aria-labelledby="bill-draft-title"><h3 id="bill-draft-title">${esc(t('ui.bill.draftTitle', 'Soru taslağı'))} <span>${esc(t('ui.bill.draftUnsent', 'Taslak: gönderilmedi'))}</span></h3>
        <label class="bill-field" for="fatura-taslak"><span>${esc(t('ui.bill.draftLabel', 'Düzenlenebilir taslak'))}</span><textarea id="fatura-taslak" rows="7">${esc(draft)}</textarea></label>
        <p class="bill-status" role="status" aria-live="polite" data-copy-status></p>
        <div class="bill-actions"><button class="btn btn-primary" type="button" data-copy>${esc(t('ui.bill.copyDraft', 'Taslağı kopyala'))}</button>
          <label class="bill-choice"><input type="checkbox" data-save-consent><span>${esc(savedLabel)}</span></label>
          <button class="btn btn-quiet" type="button" data-save>${esc(t('ui.bill.saveBill', 'Sakla'))}</button>
          <button class="btn btn-quiet" type="button" data-edit>${esc(t('ui.bill.editBill', 'Bilgileri düzenle'))}</button>
        </div>
      </section>
      ${renderChannels(lang)}`;
    result.hidden = false;
    if (!entered) {
      result.classList.add('bill-enter');
      entered = true;
    }
  }

  function savedListMarkup(bills, lang) {
    if (!bills.length) return `<p class="bill-hint">${esc(t('ui.bill.noSavedBills', 'Kayıt yok.'))}</p>`;
    return `<ul class="bill-saved-list">${bills.map((bill) => `<li><button type="button" class="btn btn-quiet" data-load-bill="${esc(bill.id)}">${esc(agencyLabel(bill.agency))} · ${esc(bill.start)} ile ${esc(bill.end)}</button></li>`).join('')}</ul>`;
  }

  function renderSaved() {
    const sectionSaved = section.querySelector('#fatura-kayitlar');
    const bills = readBills();
    const lang = currentLang();
    sectionSaved.innerHTML = `<h3 id="bill-saved-title">${esc(t('ui.bill.savedTitle', 'Kayıtlı faturalarım (bu cihazda)'))}</h3>
      <p class="bill-status" role="status" aria-live="polite" data-storage-status>${esc(storageUnavailable ? t('ui.bill.storageUnavailable', 'Bu tarayıcıda saklama kapalı; bilgiler sayfa yenilenince silinir.') : '')}</p>
      ${savedListMarkup(bills, lang)}
      <div class="bill-actions"><button class="btn btn-quiet" type="button" data-clear${bills.length ? '' : ' hidden'}>${esc(clearing ? t('ui.bill.confirmClear', 'Onayla ve sil') : t('ui.bill.clearBills', 'Bu cihazdaki fatura kayıtlarını sil'))}</button>
        ${clearing ? `<button class="btn btn-quiet" type="button" data-cancel-clear>${esc(t('ui.bill.cancel', 'Vazgeç'))}</button>` : ''}</div>`;
  }

  function renderChrome() {
    section.querySelector('#fatura-title').textContent = t('ui.bill.title', 'Faturamı anla');
    section.querySelector('[data-bill-notice]').textContent = catalog?.notice || t('ui.bill.notice', 'Faturanızdaki bilgileri kendiniz girersiniz; bilgiler bu cihazdan çıkmaz. Resmî İBB hizmeti değildir.');
    status.textContent = catalogError || (MOCK ? t('ui.bill.mock', 'Örnek veri kipinde fatura açıklaması kapalı.') : catalog ? '' : t('ui.bill.loading', 'Kaynaklı açıklama yükleniyor.'));
    status.setAttribute('lang', currentLang());
    if (catalogError || MOCK) {
      const links = `<a href="tel:153">${esc(t('ui.bill.call153', '153’ü ara'))}</a>`;
      status.insertAdjacentHTML('beforeend', ` ${links}`);
    }
    renderForm();
    renderResult();
    renderSaved();
  }

  function readErrors(entry) {
    const checked = checkEntry(entry);
    for (const output of form.querySelectorAll('[data-error]')) output.textContent = '';
    for (const input of form.querySelectorAll('[aria-invalid]')) input.removeAttribute('aria-invalid');
    const textFor = (error) => {
      if (error.code === 'date') return t('ui.bill.errorDate', 'Tarih girin.');
      if (error.code === 'order') return t('ui.bill.errorOrder', 'Bitiş tarihi başlangıç tarihinden sonra olmalı.');
      if (error.field.startsWith('name-') && error.code === 'length') return t('ui.bill.errorNameLength', 'Kalem adı en çok 60 karakter olabilir.');
      if (error.code === 'length') return t('ui.bill.errorPeriod', 'Dönem 1 ile 100 gün arasında olmalı.');
      if (error.code === 'range') return t('ui.bill.errorRange', 'Tüketim 0 ile 100000 arasında olmalı.');
      if (error.code === 'amount') return t('ui.bill.errorAmount', 'Tutarı en çok iki ondalık basamakla girin.');
      if (error.code === 'digits') return t('ui.bill.errorDigits', 'Bu alana numara yazmayın; abone ya da kimlik numarası gerekmez.');
      return t('ui.bill.errorRequired', 'Bu alanı doldurun.');
    };
    for (const error of checked.errors) {
      const output = form.querySelector(`[data-error="${CSS.escape(error.field)}"]`);
      if (output) output.textContent = textFor(error);
      const inputId = error.field.startsWith('name-') ? `bill-item-name-${error.field.slice(5)}` : `bill-${error.field}`;
      const input = error.field === 'agency' ? form.querySelector('input[name="agency"]')
        : form.querySelector(`#${CSS.escape(inputId)}`)
        || form.querySelector(`#bill-${CSS.escape(error.field)}`);
      if (input) input.setAttribute('aria-invalid', 'true');
    }
    return checked;
  }

  async function loadCatalog() {
    if (MOCK) { renderChrome(); return; }
    const mine = ++catalogRequest;
    catalogError = null;
    status.setAttribute('aria-busy', 'true');
    status.textContent = t('ui.bill.loading', 'Kaynaklı açıklama yükleniyor.');
    try {
      const response = await get(CATALOG_PATH, { lang: currentLang() });
      if (mine !== catalogRequest) return;
      catalog = response;
    } catch {
      if (mine !== catalogRequest) return;
      catalogError = t('ui.bill.loadError', 'Katalog alınamadı. Kurumunuzun resmî kanalına ya da 153’e başvurun.');
      catalog = null;
    }
    status.removeAttribute('aria-busy');
    renderChrome();
  }

  section.addEventListener('toggle', () => {
    if (section.open && !catalog && !catalogError && !MOCK) loadCatalog();
  });
  form.addEventListener('input', () => { formData = readForm(); });
  form.addEventListener('change', (event) => {
    if (event.target.matches('input[name="agency"]')) {
      const previousAgency = formData.agency;
      formData = readForm();
      if (previousAgency !== event.target.value) {
        formData.items = [];
        formData.id = '';
        formData.saved_at = undefined;
      }
      formData.agency = event.target.value;
      formData.items = formData.items.length ? formData.items : [{ id: '', label: '', amount: '' }];
      if (formData.agency === 'iski') formData.unit = 'm³';
      renderForm();
      form.querySelector('input[name="agency"]:checked')?.focus();
    } else if (event.target.matches('.bill-item-select')) {
      const activeIndex = Number(event.target.closest('.bill-line').dataset.index);
      const previousItem = formData.items[activeIndex]?.id;
      formData = readForm();
      const selected = event.target.value;
      formData.items[activeIndex] = { ...formData.items[activeIndex], id: selected };
      if (selected === 'diger' || selected === 'igdas_diger' || previousItem === 'diger' || previousItem === 'igdas_diger') {
        renderForm();
        (form.querySelector(`#bill-item-name-${activeIndex}`) || form.querySelector(`#bill-item-${activeIndex}`))?.focus();
      }
    } else if (event.target.matches('#bill-unit')) {
      formData = readForm();
      formData.unit = event.target.value;
      const label = form.querySelector('[data-unit-label]');
      if (label) label.textContent = event.target.value;
    } else formData = readForm();
  });
  form.addEventListener('click', (event) => {
    const add = event.target.closest('[data-add-line]');
    if (add) {
      event.preventDefault();
      formData = readForm();
      formData.items.push({ id: '', label: '', amount: '' });
      renderForm();
      form.querySelector(`[data-index="${formData.items.length - 1}"] .bill-item-select`)?.focus();
      return;
    }
    const remove = event.target.closest('[data-remove-line]');
    if (remove) {
      event.preventDefault();
      formData = readForm();
      formData.items.splice(Number(remove.dataset.removeLine), 1);
      renderForm();
      form.querySelector('.bill-item-select')?.focus();
    }
  });
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    formData = readForm();
    const checked = readErrors(formData);
    if (!checked.ok) {
      const firstField = checked.errors[0].field;
      const targetId = firstField === 'agency' ? 'bill-agency' : firstField.startsWith('item-') ? `bill-item-${firstField.slice(5)}`
        : firstField.startsWith('amount-') ? `bill-amount-${firstField.slice(7)}`
          : firstField.startsWith('name-') ? `bill-item-name-${firstField.slice(5)}` : `bill-${firstField}`;
      if (targetId === 'bill-agency') form.querySelector('input[name="agency"]')?.focus();
      else form.querySelector(`#${CSS.escape(targetId)}`)?.focus();
      return;
    }
    current = {
      ...formData,
      items: formData.items.map((item) => ({ ...item, amount: parseAmount(item.amount) })),
      consumption: parseAmount(formData.consumption),
      total: formData.total === '' ? undefined : parseAmount(formData.total),
    };
    current.id = current.id || '';
    previous = priorBill(current, readBills());
    points = pointsToAsk(current, previous, catalog);
    resultVisible = true;
    draftValue = draftText(current, points, currentLang());
    draftEdited = false;
    status.textContent = t('ui.bill.ready', 'Açıklama hazır. Kararı kurumunuz verir.');
    renderForm();
    renderResult();
    result.querySelector('#bill-result-title')?.focus?.();
  });

  result.addEventListener('input', (event) => {
    if (event.target.matches('#fatura-taslak')) {
      draftValue = event.target.value;
      draftEdited = true;
    }
  });
  section.addEventListener('click', async (event) => {
    const copy = event.target.closest('[data-copy]');
    if (copy) {
      const textarea = result.querySelector('#fatura-taslak');
      const copyStatus = result.querySelector('[data-copy-status]');
      try {
        await navigator.clipboard.writeText(textarea.value);
        copyStatus.textContent = t('ui.bill.copied', 'Taslak panoya kopyalandı.');
      } catch {
        textarea.focus();
        textarea.select();
        copyStatus.textContent = t('ui.bill.copyFallback', 'Kopyalamak için Ctrl+C / Cmd+C tuşlarına basın.');
      }
      return;
    }
    if (event.target.closest('[data-save]')) {
      const consent = result.querySelector('[data-save-consent]');
      const saveStatus = section.querySelector('[data-storage-status]');
      if (!consent.checked) {
        saveStatus.textContent = t('ui.bill.consentNeeded', 'Saklamak için önce yalnız bu cihazda saklama kutusunu işaretleyin.');
        return;
      }
      const saved = readBills();
      const entry = { ...current, saved_at: new Date().toISOString(), id: current.id || `bill-${Date.now()}` };
      const updated = [entry, ...saved.filter((bill) => bill.id !== entry.id)].slice(0, 12);
      if (!writeBills(updated)) saveStatus.textContent = t('ui.bill.storageUnavailable', 'Bu tarayıcıda saklama kapalı; bilgiler sayfa yenilenince silinir.');
      else {
        current = entry;
        previous = priorBill(current, updated);
        points = pointsToAsk(current, previous, catalog);
        renderResult();
      }
      renderSaved();
      if (!storageUnavailable) section.querySelector('[data-storage-status]').textContent = t('ui.bill.savedOk', 'Fatura bu cihazda saklandı.');
      return;
    }
    if (event.target.closest('[data-edit]')) {
      if (result.querySelector('#fatura-taslak')) draftValue = result.querySelector('#fatura-taslak').value;
      resultVisible = false;
      renderResult();
      renderForm();
      form.querySelector('#bill-start')?.focus();
      return;
    }
    const load = event.target.closest('[data-load-bill]');
    if (load) {
      const record = readBills().find((bill) => bill.id === load.dataset.loadBill);
      if (!record) return;
      current = { ...record };
      formData = { ...record, items: record.items.map((item) => ({ ...item, amount: String(item.amount) })) };
      previous = priorBill(current, readBills());
      points = pointsToAsk(current, previous, catalog);
      resultVisible = true;
      draftValue = draftText(current, points, currentLang());
      draftEdited = false;
      renderForm();
      renderResult();
      result.querySelector('#bill-result-title')?.focus?.();
      return;
    }
    if (event.target.closest('[data-clear]')) {
      if (!clearing) {
        clearing = true;
        renderSaved();
        section.querySelector('[data-clear]')?.focus();
        return;
      }
      if (writeBills([])) {
        clearing = false;
        current = null;
        previous = null;
        points = [];
        draftValue = '';
        draftEdited = false;
        resultVisible = false;
        formData = { agency: '', start: '', end: '', consumption: '', unit: 'm³', total: '', items: [], leak: false, singleHome: false };
        renderResult();
        renderForm();
        renderSaved();
        section.querySelector('[data-storage-status]').textContent = t('ui.bill.cleared', 'Bu cihazdaki kayıtlar silindi.');
      } else {
        section.querySelector('[data-storage-status]').textContent = t('ui.bill.storageUnavailable', 'Bu tarayıcıda saklama kapalı; bilgiler sayfa yenilenince silinir.');
      }
      return;
    }
    if (event.target.closest('[data-cancel-clear]')) {
      clearing = false;
      renderSaved();
    }
  });

  const unsubscribe = onLang(async () => {
    if (form.isConnected) formData = readForm();
    if (resultVisible && result.querySelector('#fatura-taslak') && !draftEdited) draftValue = '';
    renderChrome();
    if (section.open && !MOCK) await loadCatalog();
  });
  void unsubscribe;

  let hashFocused = false;
  const focusFromHash = () => {
    if (window.location.hash !== '#fatura' || hashFocused) return;
    hashFocused = true;
    section.open = true;
    const title = section.querySelector('#fatura-title');
    title.setAttribute('tabindex', '-1');
    window.requestAnimationFrame(() => title.focus());
  };
  window.addEventListener('hashchange', focusFromHash);
  focusFromHash();

  if (MOCK) {
    renderChrome();
    return;
  }
  renderChrome();
  if (section.open) loadCatalog();
}

if (typeof document !== 'undefined') mountBill(document);
