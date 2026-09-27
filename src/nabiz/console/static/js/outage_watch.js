/* The household setting stays on this device. The only report POST is explicit and consented. */
import { get, post, MOCK } from './api.js';
import { clock, dateTime, esc, trName } from './format.js';
import { currentLang, onLang, t } from './i18n_text.js';
const STORAGE_KEY = 'nabiz.outage.v1';
const STYLESHEET = '/css/outage_watch.css';
const KEEP_REPORTS = 5;
const CODE = /^[2-9A-HJ-KM-NP-Z]{8}$/;
const emptyStore = () => ({ home: null, reports: [] });
function cleanStore(value) {
  const home = value && value.home && typeof value.home === 'object' ? value.home : null;
  const reports = value && Array.isArray(value.reports) ? value.reports : [];
  return { home: home && typeof home.district === 'string' && typeof home.neighbourhood === 'string'
    ? { district: home.district.slice(0, 80), neighbourhood: home.neighbourhood.slice(0, 40), saved_at: String(home.saved_at || '') } : null,
    reports: reports.filter((item) => item && CODE.test(String(item.code || ''))).map((item) => ({ code: item.code, created_at: String(item.created_at || '') })).slice(-KEEP_REPORTS) };
}
export function readStore(storage) {
  try {
    const target = storage || globalThis.localStorage;
    return cleanStore(JSON.parse(target.getItem(STORAGE_KEY) || 'null'));
  } catch { return emptyStore(); }
}
export function writeStore(value, storage) {
  try {
    const target = storage || globalThis.localStorage;
    target.setItem(STORAGE_KEY, JSON.stringify(cleanStore(value)));
    return true;
  } catch { return false; }
}
function areaKey(value) {
  return String(value || '').replace(/[İIı]/g, 'i').normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('tr').replace(/[^\p{L}\p{N}]+/gu, ' ').trim();
}
export function boxesFor(info, store) {
  const home = store && store.home;
  const history = info && info.history;
  const wantedDistrict = areaKey(home && home.district);
  const wantedNeighbourhood = areaKey(home && home.neighbourhood);
  const area = home && history && Array.isArray(history.areas) ? history.areas.find((item) => areaKey(item.district) === wantedDistrict && areaKey(item.neighbourhood) === wantedNeighbourhood) || null : null;
  return {
    showHome: Boolean(home), showOfficial: Boolean(home && info && info.official),
    showConfirmation: Boolean(home && !(store.reports || []).length), showReports: Boolean(home && (store.reports || []).length), history: area,
    neighbourhoods: home && history && Array.isArray(history.areas) ? [...new Set(history.areas.filter((item) => areaKey(item.district) === wantedDistrict).map((item) => item.neighbourhood))] : [],
  };
}
export function primaryFor(state) {
  if (state.emergency) return 'call_112';
  if (state.error) return 'retry';
  if (state.formOpen) return 'send';
  if (state.homeFormOpen || !state.home) return 'save_home';
  return state.hasReports ? null : 'confirm';
}
function addStylesheet(doc) {
  if (doc.head.querySelector(`link[href="${STYLESHEET}"]`)) return;
  const sheet = doc.createElement('link'); sheet.rel = 'stylesheet'; sheet.href = STYLESHEET; doc.head.append(sheet);
}
function dateOnly(iso) {
  const value = dateTime(iso);
  return value === 'bilinmiyor' ? value : value.slice(0, 10);
}
const timeLabel = clock;
const formError = (errorId, text) => `<p class="field-error" id="${errorId}" role="alert">${esc(text || '')}</p>`;
function officialMarkup(info, history) {
  const official = info.official || {};
  const quotes = (official.quotes || []).map((quote) => {
    const label = quote.id === 'alo_185' ? t('ui.outage.quote_185', 'Alo 185') : quote.id === 'pressure_note' ? t('ui.outage.quote_pressure', 'İSKİ notu') : t('ui.outage.quote_page', 'İSKİ sayfası');
    const source = quote.source_url ? `<a class="ow-source" href="${esc(quote.source_url)}" target="_blank" rel="noopener">${esc(t('ui.outage.open_quote_source', 'Alıntının kaynağını aç'))}</a>` : '';
    return `<div class="ow-quote"><p>${esc(label)}</p><blockquote lang="tr">${esc(quote.text)}</blockquote>${source}</div>`;
  }).join('');
  const link = official.page_url ? `<a class="ow-source" href="${esc(official.page_url)}" target="_blank" rel="noopener">${esc(t('ui.outage.open_iski', 'İSKİ Arıza Kesinti sayfasını aç'))}</a>` : '';
  const captured = official.captured_at ? `<p class="ow-recorded">${esc(t('ui.outage.recorded_source', 'kayıtlı · {date} · iski.istanbul', { date: dateOnly(official.captured_at) }))}</p>` : '';
  const historyMarkup = history ? `<section class="ow-history" aria-labelledby="ow-history-title">     <h4 id="ow-history-title">${esc(t('ui.outage.history_title', 'Geçmiş (kayıtlı, 2023-2024)'))}</h4>     <p>${esc(t('ui.outage.history_count', 'Bu mahallede {count} kesinti kaydı.', { count: Number(history.count).toLocaleString(currentLang() === 'en' ? 'en' : 'tr-TR') }))}</p>     <ul>${(history.causes || []).map((item) => `<li lang="tr">${esc(item.text)} · ${esc(String(item.count))}</li>`).join('')}</ul>     <p class="ow-recorded">${esc(t('ui.outage.history_source', 'Kaynak: İBB Açık Veri, İSKİ'))} · <a class="ow-source" href="${esc(info.history.dataset)}" target="_blank" rel="noopener">${esc(t('ui.outage.history_dataset', '2023-2024 veri seti'))}</a></p>   </section>` : '';
  return `<section class="ow-box" aria-labelledby="ow-official-title"><h3 id="ow-official-title">${esc(t('ui.outage.official_title', 'İSKİ’nin resmî bilgisi'))}</h3>     <p>${esc(t('ui.outage.list_unavailable', 'Planlı kesinti listesi henüz bağlı değil. İSKİ’nin Arıza Kesinti sayfasında mahalle/ilçe filtresiyle sorgulayabilirsiniz.'))}</p>     ${quotes}${link}${captured}${historyMarkup}</section>`;
}
function gasMarkup(info) {
  const emergency = (info.gas && info.gas.lines || []).find((line) => line.id === 'gas_emergency');
  const quote = emergency && (emergency.quotes || []).find((item) => item.text === '187 Doğal Gaz Acil Hattı');
  const source = quote ? `<div class="ow-quote"><blockquote lang="tr">${esc(quote.text)}</blockquote>     <a class="ow-source" href="${esc(quote.source_url)}" target="_blank" rel="noopener">${esc(t('ui.outage.gas_source', 'İBB Faaliyet Raporu 2025'))}</a>     <p class="ow-recorded">${esc(t('ui.outage.gas_recorded', 'kayıtlı · {date} · ibb.istanbul', { date: dateOnly(emergency.captured_at) }))}</p></div>` : '';
  return `<section class="ow-box" aria-labelledby="ow-gas-title"><h3 id="ow-gas-title">${esc(t('ui.outage.gas_title', 'Doğal gaz'))}</h3>     <p>${esc(t('ui.outage.gas_no_source', "Doğal gaz kesintisi için Nabız’da kaynak yok."))}</p>     <p><a class="ow-source" href="tel:153">${esc(t('ui.outage.call_153', '153’ü arayın'))}</a></p>     <p class="is-emergency">${esc(t('ui.outage.gas_emergency_prefix', 'Gaz kokusu alıyorsanız bu acildir:'))}       <a href="tel:112">${esc(t('ui.outage.call_112', '112’yi arayın'))}</a> ${esc(t('ui.outage.or', 've'))}       <a href="tel:187">${esc(t('ui.outage.gas_187', 'İGDAŞ 187 Doğal Gaz Acil Hattı'))}</a></p>${source}</section>`;
}
function homeFormMarkup(info, home, editing) {
  const districts = Array.isArray(info.districts) ? info.districts : [];
  const selected = home ? home.district : '';
  const suggestions = home ? boxesFor(info, { home, reports: [] }).neighbourhoods : [];
  const options = `<option value="">${esc(t('ui.outage.choose_district', 'İlçe seçin'))}</option>` + districts.map((district) => `<option value="${esc(district)}"${district === selected ? ' selected' : ''}>${esc(district)}</option>`).join('');
  const dataList = `<datalist id="ow-neighbourhoods">${suggestions.map((name) => `<option value="${esc(trName(name))}"></option>`).join('')}</datalist>`;
  return `<form class="ow-form" data-form="home" aria-labelledby="ow-home-form-title">     <h3 id="ow-home-form-title">${esc(editing ? t('ui.outage.edit_home_title', 'Evimi değiştir') : t('ui.outage.home_form_title', 'Evimi kaydet'))}</h3>     <label for="ow-district">${esc(t('ui.outage.district_label', 'İlçe'))}</label>     <select id="ow-district" aria-describedby="ow-district-error">${options}</select>${formError('ow-district-error', '')}     <label for="ow-neighbourhood">${esc(t('ui.outage.neighbourhood_label', 'Mahalle'))}</label>     <input id="ow-neighbourhood" name="neighbourhood" autocomplete="off" maxlength="40" list="ow-neighbourhoods" value="${esc(home ? trName(home.neighbourhood) : '')}" aria-describedby="ow-neighbourhood-hint ow-neighbourhood-error">     ${dataList}<p class="field-hint" id="ow-neighbourhood-hint">${esc(t('ui.outage.neighbourhood_hint', 'Yalnız mahalle adı; sokak ve kapı numarası yazmayın.'))}</p>     ${formError('ow-neighbourhood-error', '')}     <div class="ow-actions"><button type="submit" class="btn btn-primary">${esc(t('ui.outage.save_home', 'Evimi kaydet'))}</button>       ${editing ? `<button type="button" class="btn btn-quiet" data-action="cancel-home">${esc(t('ui.outage.cancel', 'Vazgeç'))}</button>` : ''}</div>     <p class="field-hint">${esc(t('ui.outage.local_only', 'Yalnız bu cihazda saklanır. Kaydetmek sunucuya istek göndermez.'))}</p>   </form>`;
}
const confirmationMarkup = (home, repeatCode, retrying, draft) => `<form class="ow-form" data-form="confirmation" aria-labelledby="ow-confirm-title">     <h3 id="ow-confirm-title">${esc(t('ui.outage.confirm_title', 'Suyum hâlâ gelmedi'))}</h3>     <p>${esc(t('ui.outage.send_notice', 'İlçe, mahalle ve isteğe bağlı not Nabız operatörüne gider; İSKİ’ye iletilmez.'))}</p>     <label class="ow-consent"><input type="checkbox" name="consent" aria-describedby="ow-consent-error"${draft.consent ? ' checked' : ''}>       <span>${esc(t('ui.outage.consent', "Mahallemi, ilçemi ve isteğe bağlı notumu Nabız operatörüne (prototip, simüle) göndermeyi kabul ediyorum. İSKİ’ye iletilmez; 7 gün sonra silinir."))}</span></label>     ${formError('ow-consent-error', '')}     <details class="more"><summary>${esc(t('ui.outage.announced_summary', 'Duyurulan bitiş saati'))}</summary>       <label for="ow-announced-end">${esc(t('ui.outage.announced_label', 'Siz eklediniz: bitiş saati'))}</label>       <input id="ow-announced-end" name="announced_end" type="time" autocomplete="off" value="${esc(draft.time)}"></details>     <details class="more"><summary>${esc(t('ui.outage.note_summary', 'Not'))}</summary>       <label for="ow-note">${esc(t('ui.outage.note_label', 'İsteğe bağlı not'))}</label>       <textarea id="ow-note" name="note" maxlength="280" rows="3">${esc(draft.note)}</textarea>       <p class="field-hint">${esc(t('ui.outage.note_hint', 'Sokak, kapı numarası, ad veya telefon yazmayın.'))}</p></details>     <div class="ow-actions"><button type="submit" class="btn btn-primary" data-primary="send">${esc(retrying ? t('ui.outage.retry', 'Yeniden dene') : t('ui.outage.send', 'Teyidi gönder'))}</button>       <button type="button" class="btn btn-quiet" data-action="cancel-confirm">${esc(t('ui.outage.cancel', 'Vazgeç'))}</button></div>     <input type="hidden" name="repeat_code" value="${esc(repeatCode || '')}">     <p class="ow-report-area">${esc(home.district)} · ${esc(trName(home.neighbourhood))}</p>   </form>`;
function reportMarkup(view, code, actions = true) {
  if (!view) return `<section class="ow-box" aria-busy="true"><p>${esc(t('ui.outage.loading_report', 'Talep yükleniyor.'))}</p></section>`;
  const seen = view.status === 'seen';
  const confirms = (view.confirmations || []).map((item) => {
    const end = item.announced_end ? ` · ${esc(t('ui.outage.announced_by_user', 'Siz eklediniz: {time}', { time: item.announced_end }))}` : '';
    return `<li>${esc(t('ui.outage.reported_by_user', 'Siz bildirdiniz · {time}', { time: timeLabel(item.at) }))}${end}</li>`;
  }).join('');
  const status = seen ? t('ui.outage.status_seen', 'Operatör gördü (prototip)') : t('ui.outage.status_waiting', 'bekliyor');
  const note = view.note_masked ? `<blockquote lang="${esc(view.lang || 'tr')}">${esc(view.note_masked)}</blockquote>` : '';
  const buttons = actions ? `<div class="ow-actions"><button type="button" class="btn" data-action="again" data-code="${esc(code)}">${esc(t('ui.outage.again', 'Hâlâ gelmedi, yeniden bildir'))}</button>       <button type="button" class="btn btn-quiet" data-action="forget-code" data-code="${esc(code)}">${esc(t('ui.outage.forget_code', 'Talebi cihazdan unut'))}</button></div>` : '';
  return `<section class="ow-box ow-report" aria-labelledby="ow-report-title-${esc(code)}">     <h3 id="ow-report-title-${esc(code)}">#${esc(code)} · ${esc(status)}</h3>     <ul>${confirms}</ul>${note}<p class="field-hint">${view.simulated_note ? esc(t('ui.outage.simulated', 'Örnek: bu teyit İSKİ’ye iletilmez.')) : ''}</p>     ${buttons}   </section>`;
}
function mountCitizen(doc) {
  const cityTools = doc.getElementById('hesabim');
  if (!cityTools) return null;
  const last = cityTools.querySelectorAll('details.more.tool-detail');
  const details = doc.createElement('details');
  details.className = 'more tool-detail';
  details.id = 'evim-kesinti';
  if ((doc.defaultView && doc.defaultView.location.hash) === '#evim-kesinti') details.open = true;
  details.innerHTML = `<summary><span>${esc(t('ui.outage.title', 'Evimin suyu ve gazı'))}</span><small>${esc(t('ui.outage.subtitle', 'Yalnız bu cihazda; resmî bilgi İSKİ’den'))}</small></summary>     <div class="ow-content" data-outage-content></div>`;
  if (last.length) last[last.length - 1].after(details); else cityTools.append(details);
  addStylesheet(doc);
  const root = details.querySelector('[data-outage-content]');
  const storage = (() => { try { return doc.defaultView.localStorage; } catch { return null; } })();
  let store = readStore(storage);
  let info = null, infoError = false, homeFormOpen = !store.home, editingHome = false;
  let formOpen = false, repeatCode = '', error = false, emergency = false, busy = false;
  let formDraft = { time: '', note: '', consent: false }, notice = null;
  const views = new Map();
  const expired = new Set();
  function noticeText() {
    if (!notice) return '';
    const messages = { expired: () => t('ui.outage.expired', 'Talebin saklama süresi doldu.'), home_saved: () => t('ui.outage.home_saved', 'Eviniz bu cihaza kaydedildi.'), storage_error: () => t('ui.outage.storage_error', 'Kaydedilemedi: tarayıcı depolamaya izin vermiyor.'), consent_error: () => t('ui.outage.consent_error', 'Göndermek için onay kutusunu işaretleyin.'), mock_not_sent: () => t('ui.outage.mock_not_sent', 'Örnek: sunucu bağlı değil, teyit gönderilmedi.'),
      emergency_note: () => t('ui.outage.emergency_note', 'Bu acil bir durum olabilir. Operatör kuyruğunda beklemeyin.'), report_saved: () => t('ui.outage.report_saved', 'Teyidiniz kaydedildi.'), send_error: () => t('ui.outage.send_error', 'Teyit gönderilemedi. Yeniden deneyin.'), home_deleted_note: () => t('ui.outage.home_deleted_note', 'Evim ve talep kodlarım bu cihazdan silindi. Sunucudaki teyitler 7 gün saklanır.'), code_forgotten: () => t('ui.outage.code_forgotten', 'Talep kartı bu cihazdan kaldırıldı.') };
    return messages[notice.key] ? messages[notice.key]() : '';
  }
  const statusMarkup = () => `<p class="ow-status" role="status" aria-live="polite">${esc(noticeText())}</p>`;
  const say = (key) => { notice = { key }; render(); };
  function render() {
    if (infoError) {
      root.innerHTML = `<div class="ow-error"><p>${esc(t('ui.outage.info_error', 'Kesinti bilgisi açılamadı. Yeniden deneyin.'))}</p>         <button type="button" class="btn btn-primary" data-action="retry-info">${esc(t('ui.outage.retry', 'Yeniden dene'))}</button>${statusMarkup()}</div>`;
      return;
    }
    if (!info) {
      root.innerHTML = `<p class="ow-status" role="status" aria-live="polite" aria-busy="true">${esc(t('ui.outage.loading', 'Kesinti bilgisi yükleniyor.'))}</p>`;
      return;
    }
    const boxes = boxesFor(info, store);
    const primary = primaryFor({ home: store.home, homeFormOpen, formOpen, hasReports: boxes.showReports, error, emergency });
    let head = '';
    if (emergency) {
      head = `<section class="ow-box is-emergency" aria-labelledby="ow-emergency-title"><h3 id="ow-emergency-title">${esc(t('ui.outage.emergency_title', 'Acil yardım'))}</h3>         <p>${esc(t('ui.outage.emergency_note', 'Bu acil bir durum olabilir. Operatör kuyruğunda beklemeyin.'))}</p>         <a class="btn btn-primary" href="tel:112">${esc(t('ui.outage.call_112', '112’yi arayın'))}</a>         <button type="button" class="btn btn-quiet" data-action="close-emergency">${esc(t('ui.outage.close_emergency', 'Kartı kapat'))}</button></section>`;
    } else if (!store.home || homeFormOpen) {
      head = homeFormMarkup(info, store.home, editingHome);
    } else if (formOpen) {
      head = confirmationMarkup(store.home, repeatCode, error, formDraft);
    } else if (boxes.showReports) {
      head = store.reports.map((item) => reportMarkup(views.get(item.code), item.code)).join('');
    } else if (primary === 'confirm') {
      head = `<div class="ow-actions ow-primary-row"><button type="button" class="btn btn-primary" data-action="open-confirm">${esc(t('ui.outage.open_confirm', 'Suyum hâlâ gelmedi'))}</button></div>`;
    }
    const homeSummary = store.home && !homeFormOpen
      ? `<p class="ow-home">${esc(t('ui.outage.home_label', 'Kaydedilen ev'))}: ${esc(store.home.district)} · ${esc(trName(store.home.neighbourhood))}</p>`
        + `<div class="ow-actions"><button type="button" class="btn btn-quiet" data-action="edit-home">${esc(t('ui.outage.edit_home', 'Evimi değiştir'))}</button></div>`
        + `<details class="more"><summary>${esc(t('ui.outage.delete_home_summary', 'Evimi cihazdan sil'))}</summary>           <p>${esc(t('ui.outage.delete_home_note', 'Bu cihazdaki ev ve talep kodları silinir. Sunucudaki teyitler 7 gün saklanır.'))}</p>           <button type="button" class="btn btn-quiet" data-action="forget-home">${esc(t('ui.outage.delete_home', 'Evimi cihazdan sil'))}</button></details>` : '';
    const ownBox = store.home && !homeFormOpen ? `<section class="ow-box" aria-labelledby="ow-own-title"><h3 id="ow-own-title">${esc(t('ui.outage.own_title', 'Sizin bildiriminiz'))}</h3>       <p>${esc(t('ui.outage.own_note', 'Duyurulan süre geçti ama suyunuz hâlâ gelmediyse bildirin. Bu bildirim İSKİ’ye gitmez; Nabız operatörüne (prototip, simüle) düşer. Acil durumda 112.'))}</p>       <p class="field-hint">${esc(t('ui.outage.not_iski', 'Resmî kesinti bilgisinden ayrıdır; İSKİ’ye iletilmez.'))}</p></section>` : '';
    const how = `<details class="more ow-how"><summary>${esc(t('ui.outage.how_summary', 'Bu nasıl çalışır?'))}</summary>       <p>${esc(t('ui.outage.how_text', 'Ev seçiminiz yalnız bu cihazda kalır. İsteğe bağlı teyit, açık rızanızdan sonra Nabız’ın simüle operatör kuyruğuna gider ve 7 gün sonra silinir.'))}</p>       <p>${esc(t('ui.outage.not_official', 'Resmî İBB hizmeti değildir.'))}</p></details>`;
    const sourceBoxes = store.home && !homeFormOpen ? officialMarkup(info, boxes.history) + ownBox + gasMarkup(info) : '';
    const activeReports = boxes.showReports && formOpen
      ? store.reports.map((item) => reportMarkup(views.get(item.code), item.code, false)).join('') : '';
    root.innerHTML = `${head}${homeSummary}${statusMarkup()}${sourceBoxes}${activeReports}${how}`;
    const primaryButton = root.querySelector('.btn-primary');
    if (primaryButton && primary !== 'call_112') primaryButton.dataset.primary = primary || '';
    if (busy) root.querySelector('[data-primary]')?.setAttribute('aria-busy', 'true');
  }
  async function loadInfo() {
    infoError = false;
    info = null;
    render();
    try {
      info = await get('/api/outage-watch/info');
      infoError = false;
      render();
      if (store.home) await Promise.all(store.reports.map((item) => refresh(item.code)));
    } catch {
      infoError = true;
      render();
    }
  }
  async function refresh(code) {
    try {
      views.set(code, await get(`/api/outage-watch/reports/${encodeURIComponent(code)}`));
      render();
    } catch (err) {
      if (err.status === 404) {
        views.delete(code);
        store = { ...store, reports: store.reports.filter((item) => item.code !== code) };
        writeStore(store, storage);
        if (!expired.has(code)) {
          expired.add(code);
          notice = { key: 'expired' };
        }
        render();
      }
    }
  }
  function fieldError(id, message) {
    const input = root.querySelector(`#${id}`);
    if (!input) return;
    input.setAttribute('aria-invalid', 'true');
    const errorId = `${id}-error`;
    const errorNode = root.querySelector(`#${errorId}`);
    if (errorNode) errorNode.textContent = message;
    const described = new Set((input.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean));
    described.add(errorId);
    input.setAttribute('aria-describedby', [...described].join(' '));
    input.focus();
  }
  async function saveHome(form) {
    const district = form.querySelector('#ow-district').value;
    const neighbourhood = form.querySelector('#ow-neighbourhood').value.trim();
    if (!district) { fieldError('ow-district', t('ui.outage.choose_district_error', 'İlçeyi seçin.')); return; }
    if (!neighbourhood || neighbourhood.length > 40 || !/^[\p{L}\p{N} .’']+$/u.test(neighbourhood)
        || /\b(?:sokak|sok|cadde|cad|bulvar|apartman|daire|kapı|bina|adres)\b|\bno\s*\.?\s*\d/i.test(neighbourhood)) {
      fieldError('ow-neighbourhood', t('ui.outage.neighbourhood_error', 'Yalnız mahalle adını yazın.')); return;
    }
    store = { ...store, home: { district, neighbourhood, saved_at: new Date().toISOString() } };
    homeFormOpen = false;
    editingHome = false;
    error = false;
    const saved = writeStore(store, storage);
    notice = { key: saved ? 'home_saved' : 'storage_error' };
    render();
  }
  async function sendReport(form) {
    const consent = form.querySelector('[name="consent"]');
    if (!consent || !consent.checked) {
      const errorNode = root.querySelector('#ow-consent-error');
      if (errorNode) errorNode.textContent = t('ui.outage.consent_error', 'Göndermek için onay kutusunu işaretleyin.');
      consent?.setAttribute('aria-invalid', 'true');
      consent?.focus();
      return;
    }
    formDraft = {
      time: form.querySelector('[name="announced_end"]')?.value || '',
      note: form.querySelector('[name="note"]')?.value || '',
      consent: true,
    };
    if (MOCK) { say('mock_not_sent'); return; }
    if (busy) return;
    busy = true;
    error = false;
    render();
    const time = formDraft.time || null;
    const note = formDraft.note;
    const code = repeatCode;
    try {
      const view = code
        ? await post(`/api/outage-watch/reports/${encodeURIComponent(code)}/again`, { consent: true, announced_end: time, note })
        : await post('/api/outage-watch/reports', { district: store.home.district, neighbourhood: store.home.neighbourhood,
          consent: true, announced_end: time, note, lang: currentLang() });
      if (view && view.emergency) {
        emergency = true;
        formOpen = false;
        notice = { key: 'emergency_note' };
      } else {
        if (!code) store = { ...store, reports: [...store.reports, { code: view.code, created_at: view.created_at }].slice(-KEEP_REPORTS) };
        views.set(view.code, view);
        formOpen = false;
        repeatCode = '';
        notice = { key: 'report_saved' };
        writeStore(store, storage);
      }
    } catch {
      error = true;
      notice = { key: 'send_error' };
    } finally {
      busy = false;
      render();
    }
  }
  root.addEventListener('submit', (event) => {
    event.preventDefault();
    const form = event.target;
    if (form.dataset.form === 'home') void saveHome(form);
    if (form.dataset.form === 'confirmation') void sendReport(form);
  });
  root.addEventListener('change', (event) => {
    if (event.target.id === 'ow-district' && info) {
      const selected = event.target.value;
      const names = (info.history && info.history.areas || []).filter((item) => areaKey(item.district) === areaKey(selected))
        .map((item) => item.neighbourhood);
      const list = root.querySelector('#ow-neighbourhoods');
      if (list) list.innerHTML = [...new Set(names)].map((name) => `<option value="${esc(trName(name))}"></option>`).join('');
    }
  });
  root.addEventListener('click', (event) => {
    const button = event.target.closest('[data-action]');
    if (!button) return;
    const action = button.dataset.action;
    if (action === 'retry-info') void loadInfo();
    if (action === 'open-confirm') { formOpen = true; repeatCode = ''; formDraft = { time: '', note: '', consent: false }; error = false; notice = null; render(); }
    if (action === 'cancel-confirm') { formOpen = false; repeatCode = ''; error = false; render(); }
    if (action === 'close-emergency') { emergency = false; notice = null; render(); }
    if (action === 'edit-home') { homeFormOpen = true; editingHome = true; render(); }
    if (action === 'cancel-home') { homeFormOpen = false; editingHome = false; render(); }
    if (action === 'forget-home') {
      store = emptyStore(); views.clear(); homeFormOpen = true; editingHome = false;
      writeStore(store, storage);
      notice = { key: 'home_deleted_note' };
      render();
    }
    if (action === 'again') { repeatCode = button.dataset.code; formOpen = true; formDraft = { time: '', note: '', consent: false }; error = false; notice = null; render(); }
    if (action === 'forget-code') {
      const code = button.dataset.code;
      store = { ...store, reports: store.reports.filter((item) => item.code !== code) };
      views.delete(code); writeStore(store, storage);
      say('code_forgotten');
    }
  });
  doc.addEventListener('visibilitychange', () => {
    if (doc.visibilityState === 'visible' && store.home) store.reports.forEach((item) => { void refresh(item.code); });
  });
  onLang(() => {
    const homeValues = homeFormOpen ? {
      district: root.querySelector('#ow-district')?.value || '',
      neighbourhood: root.querySelector('#ow-neighbourhood')?.value || '',
    } : null;
    const reportValues = formOpen ? {
      time: root.querySelector('[name="announced_end"]')?.value || '',
      note: root.querySelector('[name="note"]')?.value || '',
      consent: Boolean(root.querySelector('[name="consent"]')?.checked),
    } : null;
    render();
    if (homeValues) {
      if (root.querySelector('#ow-district')) root.querySelector('#ow-district').value = homeValues.district;
      if (root.querySelector('#ow-neighbourhood')) root.querySelector('#ow-neighbourhood').value = homeValues.neighbourhood;
    }
    if (reportValues) {
      if (root.querySelector('[name="announced_end"]')) root.querySelector('[name="announced_end"]').value = reportValues.time;
      if (root.querySelector('[name="note"]')) root.querySelector('[name="note"]').value = reportValues.note;
      if (root.querySelector('[name="consent"]')) root.querySelector('[name="consent"]').checked = reportValues.consent;
    }
  });
  render();
  void loadInfo();
  return { details, read: () => store };
}
if (typeof document !== 'undefined') {
  const mount = () => mountCitizen(document);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, { once: true });
  else mount();
}
