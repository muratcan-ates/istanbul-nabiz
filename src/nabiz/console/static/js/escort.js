/* Prepare an accessible-support file on this device; send it only after explicit consent. */

import { MOCK, get, post } from './api.js';
import { esc } from './format.js';

export const STORAGE_KEY = 'nabiz.escort.v1';
const KEEP_MAX = 5;
const DAY_MS = 86_400_000;
const ALPHABET = '23456789ABCDEFGHJKMNPQRSTUVWXYZ';
const STYLESHEET = '/css/escort.css';
const NEEDS = ['wheelchair', 'walking_difficulty', 'low_vision', 'hearing', 'cognitive', 'other'];
const SUPPORT = ['meet_at_entrance', 'guide_inside_station', 'boarding_alighting', 'transfer', 'step_free_route_check'];
const WINDOWS = [30, 60, 120];
const MONTHS = {
  tr: ['Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık'],
  en: ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'],
};
const LABELS = {
  need: {
    tr: ['Tekerlekli sandalye', 'Yürümekte zorlanma', 'Az görme', 'İşitme', 'Bilişsel destek', 'Diğer'],
    en: ['Wheelchair', 'Walking difficulty', 'Low vision', 'Hearing', 'Cognitive support', 'Other'],
  },
  support: {
    tr: ['Girişte buluşma', 'İstasyon içinde yön bulma', 'Araca binme veya inme', 'Aktarma', 'Adımsız yolu kontrol etme'],
    en: ['Meet at the entrance', 'Find the way inside the station', 'Boarding or alighting', 'Transfer', 'Check a step-free route'],
  },
};
const STATUS_TEXT = {
  tr: {
    received: 'Alındı. Nabız örnek operatörü henüz görmedi. Bu kayıt bir refakat düzenlemesi anlamına gelmez.',
    seen: 'Nabız örnek operatörü dosyanızı gördü. Refakat olanağını 153\'e sorabilirsiniz.',
    referred_official: (agency) => `Resmî kanala yönlendirildi: ${agency || '153 Çözüm Merkezi'}. Nabız kurumdan teyit almadı; 153'e sorabilirsiniz.`,
    closed: 'Kapatıldı.', cancelled: 'Siz iptal ettiniz.',
  },
  en: {
    received: 'Received. The Nabız example operator has not seen this file yet. This record does not mean an escort has been arranged.',
    seen: 'The Nabız example operator has seen your file. You can ask 153 whether an escort option is available.',
    referred_official: (agency) => `Referred to the official channel: ${agency || '153 Solution Centre'}. Nabız has not received confirmation from the agency; you can ask 153.`,
    closed: 'Closed.', cancelled: 'You cancelled this request.',
  },
};
const TEXT = {
  tr: {
    title: 'Refakat ya da destek talebi', intro: 'Resmî destek için ihtiyacınızı, zamanı ve buluşma yerini düzenli bir dosyaya dönüştürür. Nabız refakat ayarlamaz.',
    open: 'Talep hazırla', prepare: 'Dosyayı hazırla', edit: 'Düzenle', send: 'Nabız operatör kuyruğuna gönder', local: 'Yalnız bu cihazda kalsın',
    call: "153'ü ara", closed: 'Talep hazırla', form: 'Talep bilgileri', need: 'İhtiyaç türü', support: 'İstenen destek', date: 'Tarih', time: 'Saat', window: 'Zaman aralığı',
    meet: 'Buluşma istasyonu', to: 'Varış istasyonu', return: 'Dönüş', returnTime: 'Dönüş saati', companion: 'Refakatçim var', note: 'Kısa not (isteğe bağlı)',
    noteHint: 'Ad, telefon ya da kimlik numarası yazmayın.', stationHint: 'Şimdilik yalnız raylı sistem istasyonları listeleniyor.',
    returnNone: 'Dönüş yok', returnSame: 'Aynı gün saat', returnLater: 'Daha sonra bildireceğim',
    summaryIntro: "Destek olanaklarını 153'e sorabilirsiniz; ararken bu dosyayı okuyabilirsiniz.",
    noEscortSource: "Nabız'ın kaynak dizininde ayrı bir refakat hizmeti sayfası yok; böyle bir olanak olup olmadığını 153'e sorabilirsiniz.",
    consent: 'İhtiyacım sağlıkla ilgili özel nitelikli kişisel veridir. Bu dosyanın Nabız’ın simüle operatörüne gitmesine ve en çok 30 gün ya da istediğim tarihten bir gün sonrasına kadar saklanmasına açıkça rıza veriyorum.',
    consentHint: 'Rıza vermeden dosya gönderilmez.', deviceLine: 'Dosyadaki bilgiler sizin eklediğiniz bilgilerdir. Nabız kurumdan teyit almadı.',
    disclaimer: 'Resmî İBB hizmeti değildir.', onlyHere: 'Bu dosya yalnız bu cihazda. 153’ü aradığınızda okuyabilirsiniz.',
    delete: 'Bu cihazdan sil', cancel: 'Talebi iptal et', received: 'Talebiniz', noStored: 'Talep bulunamadı ya da saklama süresi doldu.',
    saveError: 'Bu tarayıcı dosyayı saklayamadı. Sayfa açıkken kullanabilirsiniz.', optionsError: 'İstasyon listesi şu an alınamıyor. 153’ü arayabilirsiniz.',
    loading: 'İstasyon listesi yükleniyor', sources: 'Kaynaklar', unverified: 'Adımsız yol doğrulanamadı. Resmî destek için bir talep dosyası hazırlayabilirsiniz.',
    sourcesNote: 'Kaynak sayfalar genel bilgi verir; talep sonucunu doğrulamaz.', codeLabel: 'Kod', emergency: "Nabız acil durumlarda yardımcı olamaz. İBB'ye 153'ten ulaşabilirsiniz.",
    badNeed: 'Bir ihtiyaç türü seçin.', badSupport: 'En az bir destek seçin.', badDate: 'Geçerli bir tarih seçin.', badRange: 'Tarih bugün ile 30 gün sonrası arasında olmalı.',
    badTime: 'Saat 05:00 ile 23:59 arasında olmalı.', badWindow: 'Bir zaman aralığı seçin.', badMeet: 'Listeden bir buluşma istasyonu seçin.',
    badTo: 'Listeden bir varış istasyonu seçin.', badSame: 'Buluşma ve varış istasyonları farklı olmalı.', badReturn: 'Dönüş seçeneğini belirleyin.',
    badReturnTime: 'Dönüş saati yolculuk saatinden sonra olmalı.', badCompanion: 'Refakatçiniz olup olmadığını belirtin.', badNote: 'Not en fazla 200 karakter olabilir.',
    trReturnSame: 'aynı gün', yes: 'Evet', no: 'Hayır', dateTitle: 'Tarih', tripMeet: 'Buluşma', tripTo: 'Varış', tripReturn: 'Dönüş',
    needLine: 'İhtiyaç', supportLine: 'İstenen destek', companionLine: 'Refakatçim var', noteLine: 'Not', station: 'istasyonu',
    fileSection: 'Talep dosyanız', requests: 'Taleplerim', localFiles: 'Bu cihazdaki dosyalar', sourceLink: 'Kaynağı aç', operatorNote: 'Simüle operatör notu',
  },
  en: {
    title: 'Escort or support request', intro: 'Prepare a clear file with your support needs, time, and meeting point. Nabız does not arrange an escort.',
    open: 'Prepare a request', prepare: 'Prepare file', edit: 'Edit', send: 'Send to the Nabız example operator queue', local: 'Keep on this device only',
    call: 'Call 153', closed: 'Prepare a request', form: 'Request details', need: 'Type of need', support: 'Support requested', date: 'Date', time: 'Time', window: 'Time range',
    meet: 'Meeting station', to: 'Destination station', return: 'Return', returnTime: 'Return time', companion: 'I have a companion', note: 'Short note (optional)',
    noteHint: 'Do not enter a name, phone number, or identity number.', stationHint: 'For now, only rail stations are listed.',
    returnNone: 'No return', returnSame: 'Same day at', returnLater: 'I will say later',
    summaryIntro: 'You can ask 153 about support options; you can read this file during the call.',
    noEscortSource: 'The Nabız source list has no separate page for escort service; you can ask 153 whether an option is available.',
    consent: 'My support need is health related special-category personal data. I explicitly consent to sending this file to the simulated Nabız operator and keeping it for up to 30 days or until one day after my requested date, whichever comes first.',
    consentHint: 'The file is not sent without consent.', deviceLine: 'The file contains information you added. Nabız has not received confirmation from an agency.',
    disclaimer: 'This is not an official İBB service.', onlyHere: 'This file is only on this device. You can read it when you call 153.',
    delete: 'Remove from this device', cancel: 'Cancel request', received: 'Your request', noStored: 'The request was not found or its storage period ended.',
    saveError: 'This browser could not keep the file. You can use it while this page stays open.', optionsError: 'The station list is unavailable. You can call 153.',
    loading: 'Loading station list', sources: 'Sources', unverified: 'A step-free route could not be verified. You can prepare a file for official support.',
    sourcesNote: 'These source pages give general information; they do not confirm the outcome of a request.', disclaimer: 'This is not an official İBB service.',
    codeLabel: 'Code', emergency: 'Nabız cannot help in an emergency. You can reach İBB on 153.', badNeed: 'Choose a type of need.', badSupport: 'Choose at least one kind of support.',
    badDate: 'Choose a valid date.', badRange: 'The date must be between today and 30 days from now.', badTime: 'Time must be between 05:00 and 23:59.',
    badWindow: 'Choose a time range.', badMeet: 'Choose a meeting station from the list.', badTo: 'Choose a destination station from the list.',
    badSame: 'Meeting and destination stations must be different.', badReturn: 'Choose a return option.', badReturnTime: 'Return time must be after the trip time.',
    badCompanion: 'Say whether you have a companion.', badNote: 'The note can be up to 200 characters.', trReturnSame: 'same day at', yes: 'Yes', no: 'No',
    needLine: 'Need', supportLine: 'Support requested', dateTitle: 'Date', tripMeet: 'Meeting point', tripTo: 'Destination', tripReturn: 'Return',
    companionLine: 'Companion with me', noteLine: 'Note', station: 'station', fileSection: 'Your request file', requests: 'My requests',
    localFiles: 'Files on this device', sourceLink: 'Open source', operatorNote: 'Example operator note',
  },
};

const language = (value) => value === 'en' ? 'en' : 'tr';
const TURKISH_FOLD = { 'İ': 'i', I: 'i', 'ı': 'i', 'Ş': 's', 'ş': 's', 'Ğ': 'g', 'ğ': 'g', 'Ü': 'u', 'ü': 'u', 'Ö': 'o', 'ö': 'o', 'Ç': 'c', 'ç': 'c', 'Â': 'a', 'â': 'a', 'Î': 'i', 'î': 'i', 'Û': 'u', 'û': 'u' };
const fold = (value) => [...String(value || '')].map((ch) => TURKISH_FOLD[ch] || ch).join('').normalize('NFD').replace(/\p{M}/gu, '').toLowerCase().replace(/\s+/g, ' ').trim();
const t = (key, lang = 'tr') => TEXT[language(lang)][key] || TEXT.tr[key] || key;

/** Canonical station spelling for an exact accent- and case-insensitive match. */
export function matchStation(value, stations) {
  const wanted = fold(value);
  return wanted ? (stations || []).find((name) => fold(name) === wanted) || '' : '';
}

function parseDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(value || ''))) return null;
  const parts = value.split('-').map(Number);
  const date = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
  return date.toISOString().slice(0, 10) === value ? date : null;
}

function addMinutes(value, minutes) {
  const [hour, minute] = String(value).split(':').map(Number);
  return `${String(Math.floor((hour * 60 + minute + minutes) / 60) % 24).padStart(2, '0')}:${String((minute + minutes) % 60).padStart(2, '0')}`;
}

function endsNextDay(value, minutes) {
  const [hour, minute] = String(value).split(':').map(Number);
  return hour * 60 + minute + minutes >= 1440;
}

/** Same field errors and validation order as escort_request.validate. */
export function validateDraft(draft, stations, today = new Date()) {
  if (!NEEDS.includes(draft.need)) return t('badNeed');
  if (!Array.isArray(draft.assistance) || draft.assistance.length < 1 || draft.assistance.length > SUPPORT.length || draft.assistance.some((item) => !SUPPORT.includes(item))) return t('badSupport');
  const date = parseDate(draft.date);
  if (!date) return t('badDate');
  const base = today instanceof Date ? new Date(Date.UTC(today.getFullYear(), today.getMonth(), today.getDate())) : parseDate(String(today));
  const requestedDay = Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate());
  const baseDay = base ? Date.UTC(base.getUTCFullYear(), base.getUTCMonth(), base.getUTCDate()) : NaN;
  if (requestedDay < baseDay || requestedDay > baseDay + 30 * DAY_MS) return t('badRange');
  if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(draft.time || '') || draft.time < '05:00') return t('badTime');
  if (!WINDOWS.includes(Number(draft.window_min)) || String(draft.window_min) === 'true') return t('badWindow');
  const meet = matchStation(draft.meet_station, stations), destination = matchStation(draft.to_station, stations);
  if (!meet) return t('badMeet');
  if (!destination) return t('badTo');
  if (fold(meet) === fold(destination)) return t('badSame');
  if (!['none', 'same_day', 'later'].includes(draft.return_kind)) return t('badReturn');
  if (draft.return_kind === 'same_day' && (!/^([01]\d|2[0-3]):[0-5]\d$/.test(draft.return_time || '') || draft.return_time <= draft.time)) return t('badReturnTime');
  if (typeof draft.companion !== 'boolean') return t('badCompanion');
  if (typeof (draft.note || '') !== 'string' || String(draft.note || '').length > 200) return t('badNote');
  draft.meet_station = meet;
  draft.to_station = destination;
  draft.window_min = Number(draft.window_min);
  draft.note = String(draft.note || '').trim();
  return null;
}

/** Readable request copy, kept in line with the server renderer. */
export function summaryLines(draft, lang = 'tr') {
  const code = language(lang), date = parseDate(draft.date);
  if (!date) return [];
  const month = MONTHS[code][date.getUTCMonth()], day = date.getUTCDate(), year = date.getUTCFullYear();
  const need = NEEDS.indexOf(draft.need), support = (draft.assistance || []).map((item) => LABELS.support[code][SUPPORT.indexOf(item)]);
  const same = draft.return_kind === 'same_day';
  const returnText = same ? `${t('trReturnSame', code)} ${draft.return_time}` : draft.return_kind === 'later' ? (code === 'tr' ? 'Daha sonra bildireceğim' : "I'll say later") : (code === 'tr' ? 'Yok' : 'None');
  const end = addMinutes(draft.time, Number(draft.window_min));
  const nextDay = endsNextDay(draft.time, Number(draft.window_min));
  const endLabel = nextDay ? `${end} (${code === 'tr' ? 'ertesi gün' : 'next day'})` : end;
  const lines = code === 'en'
    ? [`Need: ${LABELS.need.en[need]}`, `Requested support: ${support.join(', ')}`, `Date: ${day} ${month} ${year}, between ${draft.time} and ${endLabel}`,
      `Meeting point: ${draft.meet_station} station`, `Destination: ${draft.to_station} station`, `Return: ${returnText}`, `Companion with me: ${draft.companion ? 'Yes' : 'No'}`]
    : [`İhtiyaç: ${LABELS.need.tr[need]}`, `İstenen destek: ${support.join(', ')}`, `Tarih: ${day} ${month} ${year}, ${draft.time} ile ${endLabel} arası`,
      `Buluşma: ${draft.meet_station} istasyonu`, `Varış: ${draft.to_station} istasyonu`, `Dönüş: ${returnText}`, `Refakatçim var: ${draft.companion ? 'Evet' : 'Hayır'}`];
  if (draft.note) lines.push(`${code === 'tr' ? 'Not' : 'Note'}: ${String(draft.note).trim()}`);
  return lines;
}

function expiry(draft) {
  const date = parseDate(draft && draft.date);
  return date ? Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate() + 1) - 3 * 60 * 60 * 1000 : 0;
}

/** Parse the five newest local files; malformed entries and files past the requested date are dropped. */
export function readStore(storage, now = Date.now()) {
  try {
    const value = JSON.parse(storage.getItem(STORAGE_KEY) || 'null');
    if (!value || value.version !== 1 || !Array.isArray(value.items)) return [];
    const kept = value.items.filter((item) => item && (item.code === null || (typeof item.code === 'string' && new RegExp(`^[${ALPHABET}]{8}$`).test(item.code)))
      && item.draft && Array.isArray(item.summary) && Number.isFinite(item.at) && Number.isFinite(expiry(item.draft)) && expiry(item.draft) > now)
      .slice(-KEEP_MAX);
    if (kept.length !== value.items.length) storage.setItem(STORAGE_KEY, JSON.stringify({ version: 1, items: kept }));
    return kept;
  } catch (error) { return []; }
}

/** Persist only the request code, draft, summary, and creation time on this device. */
export function writeStore(storage, items, now = Date.now()) {
  try {
    const kept = (items || []).filter((item) => item && Number.isFinite(expiry(item.draft)) && expiry(item.draft) > now).slice(-KEEP_MAX);
    storage.setItem(STORAGE_KEY, JSON.stringify({ version: 1, items: kept }));
    return true;
  } catch (error) { return false; }
}

function addStylesheet(doc) {
  if (doc.head.querySelector(`link[href="${STYLESHEET}"]`)) return;
  const link = doc.createElement('link'); link.rel = 'stylesheet'; link.href = STYLESHEET; doc.head.append(link);
}

const optionSources = [
  { id: 'cozum_153', title: 'Çözüm Merkezi Alo 153', agency_id: 'cozum_153', url: 'https://cozummerkezi.ibb.istanbul/', summary_tr: "İBB'nin resmî başvuru ve iletişim kanalı. Destek ya da refakat olanağı olup olmadığını buradan sorabilirsiniz.", summary_en: "İBB's official contact channel. You can ask whether support or an escort option is available." },
  { id: 'metro_access', title: 'Metro İstanbul: Erişilebilirlik Hizmetleri', agency_id: 'metro', url: 'https://www.metro.istanbul/icerik/eri%C5%9Filebilirlik-hizmetleri', summary_tr: 'İstasyonlardaki asansör, rampa, hissedilebilir zemin ve yönlendirme düzenini anlatır.', summary_en: 'Describes station lifts, ramps, tactile paving, and wayfinding.' },
  { id: 'metro_contact', title: 'Metro İstanbul: Bize Ulaşın', agency_id: 'metro', url: 'https://www.metro.istanbul/BizeUlasin/Index', summary_tr: "Metro İstanbul'un iletişim sayfası.", summary_en: "Metro İstanbul's contact page." },
  { id: 'ibb_disability_centers', title: 'İBB Sosyal Hizmetler: Engelli Merkezleri', agency_id: 'ibb', url: 'https://sosyalhizmetler.ibb.gov.tr/engellimerkezleri.aspx', summary_tr: "İBB'nin engelli merkezlerinin listesi; adres ve telefonlar resmî sayfada.", summary_en: 'A list of İBB disability centres; addresses and phone numbers are on the official page.' },
  { id: 'ferry_disabled', title: 'Şehir Hatları: Engelli Yolcularımız İçin', agency_id: 'sehir_hatlari', url: 'https://sehirhatlari.istanbul/tr/bilgiler/engelli-yolcularimiz-icin-186', summary_tr: 'Vapur ve deniz otobüslerindeki erişim olanaklarını anlatır; koşulları sefer öncesi teyit edin.', summary_en: 'Describes access on ferries and sea buses; check conditions before your trip.' },
];
const mockOptions = { stations: ['Kadıköy', 'Levent', 'Kartal'], sources: optionSources,
  official: { call: '153', agency: { id: 'cozum_153', name: '153 Çözüm Merkezi', url: 'https://cozummerkezi.ibb.istanbul/' } } };

function safeUrl(raw) {
  try { const url = new URL(raw); return url.protocol === 'https:' ? url.href : ''; } catch (error) { return ''; }
}

function sourcesMarkup(sources, lang) {
  const cards = (sources || []).map((source) => {
    const url = safeUrl(source.url), summary = lang === 'en' ? source.summary_en : source.summary_tr;
    return `<li><a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(source.title)}</a><span>${esc(summary)}</span></li>`;
  }).join('');
  return `<section class="escort-sources" aria-labelledby="escort-sources-title"><h3 id="escort-sources-title">${esc(t('sources', lang))}</h3><ul>${cards}</ul><p>${esc(t('sourcesNote', lang))}</p></section>`;
}

function renderSummaryMarkup(lines) {
  const rows = (lines || []).map((line) => {
    const split = String(line).indexOf(': ');
    const label = split < 0 ? '' : line.slice(0, split), value = split < 0 ? line : line.slice(split + 2);
    return `<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`;
  }).join('');
  return `<dl class="escort-summary">${rows}</dl>`;
}

/** Status card renderer shared by server-backed and device-only files. */
export function cardMarkup(view, lang = 'tr', localOnly = false) {
  const code = localOnly ? '' : `<p>${esc(t('codeLabel', lang))}: <code>${esc(view.code || '')}</code></p>`;
  const statusCopy = STATUS_TEXT[language(lang)][view.status];
  const status = localOnly ? t('onlyHere', lang) : (typeof statusCopy === 'function' ? statusCopy(view.agency?.name) : statusCopy || view.status_text || t('noStored', lang));
  const history = localOnly ? '' : `<ol class="escort-history">${(view.history || []).map((item) => `<li><span>${esc(item.status)}</span><time datetime="${esc(item.at)}">${esc(item.at)}</time></li>`).join('')}</ol>`;
  const agency = view.agency && safeUrl(view.agency.url)
    ? `<p>${esc(view.agency.name)} <a href="${esc(safeUrl(view.agency.url))}" target="_blank" rel="noopener noreferrer">${esc(t('sourceLink', lang))}</a></p>` : '';
  const summary = renderSummaryMarkup(view.draft ? summaryLines(view.draft, lang) : view.summary || []);
  const cancel = !localOnly && ['received', 'seen', 'referred_official'].includes(view.status)
    ? `<button type="button" class="btn" data-action="cancel" data-code="${esc(view.code)}">${esc(t('cancel', lang))}</button>` : '';
  const remove = `<button type="button" class="btn" data-action="${localOnly ? 'delete-local' : 'remove'}" data-code="${esc(view.code || '')}" data-at="${esc(view.at ?? '')}">${esc(t('delete', lang))}</button>`;
  const operatorNote = view.operator_note ? `<p><b>${esc(t('operatorNote', lang))}:</b> ${esc(view.operator_note)}</p>` : '';
  return `<article class="escort-card escort-step" data-status="${esc(view.status || 'local')}"><h3 id="escort-status-title" tabindex="-1">${esc(t('received', lang))}</h3>${code}<p class="escort-now" role="status" aria-live="polite">${esc(status)}</p><p>${esc(t('deviceLine', lang))}</p>${agency}${operatorNote}${history}<details><summary>${esc(t('fileSection', lang))}</summary>${summary}</details><a class="escort-phone" href="tel:153">${esc(t('call', lang))}</a><p>${esc(t('disclaimer', lang))}</p><div class="escort-actions">${cancel}${remove}</div></article>`;
}

function emergencyMarkup(message, lang) {
  return `<article class="escort-card escort-step escort-emergency" role="alert"><h3 id="escort-status-title" tabindex="-1">${esc(message || t('emergency', lang))}</h3><a class="btn btn-primary" href="tel:153">${esc(t('call', lang))}</a></article>`;
}

function fieldError(id, message) { return `<p class="escort-error" id="${id}-error" role="alert" hidden>${esc(message)}</p>`; }

function formMarkup(options, lang, draft = {}) {
  const needOptions = NEEDS.map((value, index) => `<label class="escort-choice"><input type="radio" name="need" value="${value}" ${draft.need === value ? 'checked' : ''} required><span>${esc(LABELS.need[lang][index])}</span></label>`).join('');
  const supportOptions = SUPPORT.map((value, index) => `<label class="escort-choice"><input type="checkbox" name="assistance" value="${value}" ${(draft.assistance || []).includes(value) ? 'checked' : ''}><span>${esc(LABELS.support[lang][index])}</span></label>`).join('');
  const stations = options?.stations || [];
  const stationOptions = stations.map((value) => `<option value="${esc(value)}"></option>`).join('');
  const today = new Date(), localToday = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
  const limitDate = new Date(today.getFullYear(), today.getMonth(), today.getDate() + 30);
  const maxDate = `${limitDate.getFullYear()}-${String(limitDate.getMonth() + 1).padStart(2, '0')}-${String(limitDate.getDate()).padStart(2, '0')}`;
  return `<form class="escort-form escort-step" data-escort-form novalidate>
    <fieldset aria-describedby="need-error"><legend>${esc(t('need', lang))}</legend>${needOptions}${fieldError('need', t('badNeed', lang))}</fieldset>
    <fieldset aria-describedby="assistance-error"><legend>${esc(t('support', lang))}</legend>${supportOptions}${fieldError('assistance', t('badSupport', lang))}</fieldset>
    <div class="escort-fields"><div class="field"><label for="escort-date">${esc(t('date', lang))}</label><input id="escort-date" name="date" type="date" min="${localToday}" max="${maxDate}" value="${esc(draft.date || '')}" required>${fieldError('date', t('badDate', lang))}</div>
    <div class="field"><label for="escort-time">${esc(t('time', lang))}</label><input id="escort-time" name="time" type="time" min="05:00" max="23:59" value="${esc(draft.time || '')}" required>${fieldError('time', t('badTime', lang))}</div>
    <div class="field"><label for="escort-window">${esc(t('window', lang))}</label><select id="escort-window" name="window_min" required><option value="">${esc(t('window', lang))}</option>${WINDOWS.map((n) => `<option value="${n}" ${Number(draft.window_min) === n ? 'selected' : ''}>${n} ${lang === 'tr' ? 'dakika' : 'minutes'}</option>`).join('')}</select>${fieldError('window', t('badWindow', lang))}</div>
    <div class="field"><label for="escort-meet">${esc(t('meet', lang))}</label><input id="escort-meet" name="meet_station" list="escort-stations" value="${esc(draft.meet_station || '')}" autocomplete="off" required>${fieldError('meet', t('badMeet', lang))}</div>
    <div class="field"><label for="escort-to">${esc(t('to', lang))}</label><input id="escort-to" name="to_station" list="escort-stations" value="${esc(draft.to_station || '')}" autocomplete="off" required>${fieldError('to', t('badTo', lang))}</div></div>
    <datalist id="escort-stations">${stationOptions}</datalist><p class="escort-hint">${esc(t('stationHint', lang))}</p>
    <fieldset><legend>${esc(t('return', lang))}</legend><label class="escort-choice"><input type="radio" name="return_kind" value="none" ${!draft.return_kind || draft.return_kind === 'none' ? 'checked' : ''}><span>${esc(t('returnNone', lang))}</span></label><label class="escort-choice"><input type="radio" name="return_kind" value="same_day" ${draft.return_kind === 'same_day' ? 'checked' : ''}><span>${esc(t('returnSame', lang))}</span></label><label class="escort-choice"><input type="radio" name="return_kind" value="later" ${draft.return_kind === 'later' ? 'checked' : ''}><span>${esc(t('returnLater', lang))}</span></label><div class="field escort-return-time" ${draft.return_kind === 'same_day' ? '' : 'hidden'}><label for="escort-return-time">${esc(t('returnTime', lang))}</label><input id="escort-return-time" name="return_time" type="time" min="05:00" max="23:59" value="${esc(draft.return_time || '')}"></div>${fieldError('return', t('badReturn', lang))}${fieldError('return_time', t('badReturnTime', lang))}</fieldset>
    <label class="escort-choice"><input type="checkbox" name="companion" ${draft.companion ? 'checked' : ''}><span>${esc(t('companion', lang))}</span></label>
    <div class="field"><label for="escort-note">${esc(t('note', lang))}</label><textarea id="escort-note" name="note" maxlength="200" rows="3">${esc(draft.note || '')}</textarea><p class="escort-hint">${esc(t('noteHint', lang))}</p>${fieldError('note', t('badNote', lang))}</div>
    <p class="escort-error" data-form-error role="alert" hidden></p><p class="escort-status" role="status" aria-live="polite">${stations.length ? '' : esc(t('loading', lang))}</p>
    <button class="btn btn-primary" type="submit">${esc(t('prepare', lang))}</button></form>`;
}

function summaryMarkup(draft, options, lang, mock = false) {
  return `<section class="escort-summary-screen escort-step" aria-labelledby="escort-summary-title"><h3 id="escort-summary-title" tabindex="-1">${esc(t('fileSection', lang))}</h3><p>${esc(t('summaryIntro', lang))}</p><a class="escort-phone" href="tel:153">${esc(t('call', lang))}</a>${renderSummaryMarkup(summaryLines(draft, lang))}${sourcesMarkup(options?.sources || [], lang)}<p>${esc(t('noEscortSource', lang))}</p><p class="escort-disclosure">${esc(t('deviceLine', lang))}</p><p>${esc(t('disclaimer', lang))}</p>
    ${mock ? `<p class="escort-example">Örnek dosya; gönderim kapalı.</p><div class="escort-actions"><button class="btn" type="button" data-action="edit">${esc(t('edit', lang))}</button></div>`
      : `<label class="escort-consent"><input type="checkbox" data-consent><span>${esc(t('consent', lang))}</span></label><p class="escort-hint">${esc(t('consentHint', lang))}</p>
    <div class="escort-actions"><button class="btn btn-primary" type="button" data-action="send" aria-disabled="true">${esc(t('send', lang))}</button><button class="btn" type="button" data-action="local">${esc(t('local', lang))}</button><button class="btn" type="button" data-action="edit">${esc(t('edit', lang))}</button></div>`}</section>`;
}

function storedMarkup(items, views, lang) {
  const coded = items.filter((item) => item.code);
  const local = items.filter((item) => !item.code);
  const requests = coded.length ? `<details class="escort-requests"><summary>${esc(t('requests', lang))}</summary>${coded.map((item) => cardMarkup({ ...views.get(item.code), code: item.code, draft: item.draft, status_text: views.get(item.code)?.status_text || t('loading', lang), summary: item.summary, history: views.get(item.code)?.history || [] }, lang)).join('')}</details>` : '';
  const locals = local.length ? `<section class="escort-local-files"><h3>${esc(t('localFiles', lang))}</h3>${local.map((item) => cardMarkup({ ...item, summary: item.summary }, lang, true)).join('')}</section>` : '';
  return requests + locals;
}

export function validationTarget(message) {
  const mapping = [['badNeed', 'need'], ['badSupport', 'assistance'], ['badDate', 'date'], ['badRange', 'date'],
    ['badTime', 'time'], ['badWindow', 'window'], ['badMeet', 'meet'], ['badTo', 'to'], ['badSame', 'to'],
    ['badReturn', 'return'], ['badReturnTime', 'return_time'], ['badCompanion', 'companion'], ['badNote', 'note']];
  return mapping.find(([key]) => t(key, 'tr') === message) || null;
}

function mountEscort(doc, storage = null) {
  const localStorage = storage || (() => { try { return doc.defaultView.localStorage; } catch (error) { return null; } })();
  let state = { lang: language(doc.documentElement.lang), options: MOCK ? mockOptions : null, screen: 'closed', draft: null,
    pendingDraft: null, view: null, records: readStore(localStorage), views: new Map(), unverified: false, error: '', mounted: null };
  if (MOCK) state.records = [];
  let optionsPromise = null;
  let lastScreen = null;

  function render({ focus = false } = {}) {
    const host = state.mounted;
    if (!host) return;
    const lang = state.lang;
    let content = `<h2 id="escort-title" tabindex="-1">${esc(t('title', lang))}</h2><p class="escort-intro">${esc(t('intro', lang))}</p><p class="escort-disclosure">${esc(t('deviceLine', lang))}</p><a class="escort-phone" href="tel:153">${esc(t('call', lang))}</a>`;
    if (MOCK) content += '<p class="escort-example">Örnek</p>';
    if (state.unverified) content += `<p class="escort-unverified" role="status">${esc(t('unverified', lang))}</p>`;
    if (state.screen === 'closed') content += `<div class="escort-step"><button class="btn" type="button" data-action="open">${esc(t('open', lang))}</button></div>`;
    if (state.screen === 'form') content += `<h3 id="escort-form-title" tabindex="-1">${esc(t('form', lang))}</h3>${formMarkup(state.options, lang, state.draft || {})}`;
    if (state.screen === 'summary') content += summaryMarkup(state.draft, state.options, lang, MOCK);
    if (state.screen === 'status' && state.view?.emergency) content += emergencyMarkup(state.view.message, lang);
    else if (state.screen === 'status' && state.view) content += cardMarkup(state.view, lang, !state.view.code);
    if (state.error) content += `<p role="status" class="escort-status">${esc(state.error)}</p>`;
    content += storedMarkup(state.records, state.views, lang);
    host.innerHTML = content;
    if (lastScreen !== state.screen) {
      host.querySelector('.escort-step')?.classList.add('is-entering');
      lastScreen = state.screen;
    }
    if (focus) {
      const target = state.screen === 'form' ? '#escort-form-title' : state.screen === 'summary' ? '#escort-summary-title'
        : state.screen === 'status' ? '#escort-status-title' : '#escort-title';
      host.querySelector(target)?.focus();
    }
  }

  async function optionsOnce() {
    if (state.options) return state.options;
    if (!optionsPromise) optionsPromise = get('/api/escort/options').then((value) => { state.options = value; return value; })
      .catch(() => { state.error = t('optionsError', state.lang); return null; });
    return optionsPromise;
  }

  function syncStationOptions(options) {
    if (!options) return;
    const list = state.mounted?.querySelector('#escort-stations');
    if (list) list.innerHTML = options.stations.map((name) => `<option value="${esc(name)}"></option>`).join('');
    const status = state.mounted?.querySelector('.escort-status');
    if (status) status.textContent = '';
    const from = doc.querySelector('#journey-from'), to = doc.querySelector('#journey-to');
    const meet = state.mounted?.querySelector('#escort-meet'), destination = state.mounted?.querySelector('#escort-to');
    if (meet && !meet.value && from) meet.value = matchStation(from.value, options.stations);
    if (destination && !destination.value && to) destination.value = matchStation(to.value, options.stations);
  }

  async function refresh(code) {
    try {
      const view = await get(`/api/escort/requests/${encodeURIComponent(code)}`);
      state.views.set(code, view);
      if (state.view?.code === code) state.view = view;
      render();
    } catch (error) {
      if (error.status === 404) state.views.set(code, { code, status_text: t('noStored', state.lang), summary: state.records.find((item) => item.code === code)?.summary || [], history: [] });
      render();
    }
  }

  function storeRecords() {
    if (!writeStore(localStorage, state.records)) state.error = t('saveError', state.lang);
  }

function showForm() {
    state.screen = 'form'; state.error = ''; render({ focus: true });
    void optionsOnce().then(syncStationOptions);
  }

  function readForm(form) {
    const getValue = (name) => form.elements.namedItem(name)?.value || '';
    return { need: form.querySelector('input[name="need"]:checked')?.value || '',
      assistance: [...form.querySelectorAll('input[name="assistance"]:checked')].map((input) => input.value),
      date: getValue('date'), time: getValue('time'), window_min: getValue('window_min'),
      meet_station: getValue('meet_station'), to_station: getValue('to_station'),
      return_kind: form.querySelector('input[name="return_kind"]:checked')?.value || '', return_time: getValue('return_time'),
      companion: Boolean(form.querySelector('input[name="companion"]')?.checked), note: getValue('note') };
  }

  function showValidation(form, message) {
    form.querySelectorAll('.escort-error').forEach((item) => { item.hidden = true; });
    form.querySelectorAll('[aria-invalid="true"]').forEach((item) => item.removeAttribute('aria-invalid'));
    const match = validationTarget(message);
    if (match) {
      const [key, target] = match;
      const node = form.querySelector(`#${target}-error`);
      if (node) { node.textContent = t(key, state.lang); node.hidden = false; }
      const control = target === 'need' ? form.querySelector('input[name="need"]')
        : target === 'assistance' ? form.querySelector('input[name="assistance"]')
          : target === 'meet' ? form.querySelector('#escort-meet') : target === 'to' ? form.querySelector('#escort-to')
            : target === 'return' ? form.querySelector('input[name="return_kind"]') : form.querySelector(`[name="${target}"]`);
      if (control) {
        control.setAttribute('aria-invalid', 'true');
        if (target !== 'need' && target !== 'assistance' && target !== 'return') control.setAttribute('aria-describedby', `${target}-error`);
        control.focus();
      }
    } else {
      const banner = form.querySelector('[data-form-error]'); if (banner) { banner.textContent = message; banner.hidden = false; }
    }
  }

  function addRecord(code, draft, summary) {
    const item = { code, draft: { ...draft }, summary, at: Date.now() };
    state.records = [...(code ? state.records.filter((current) => current.code !== code) : state.records), item].slice(-KEEP_MAX);
    storeRecords();
    return item;
  }

  async function sendDraft() {
    if (!state.draft) return;
    const checkbox = state.mounted.querySelector('[data-consent]');
    if (!checkbox?.checked) { state.error = t('consentHint', state.lang); render(); return; }
    const draft = { ...state.draft };
    try {
      let view;
      if (MOCK) {
        view = { code: 'K7M2QX9P', status: 'received', status_text: 'Örnek: alındı. Nabız kurumdan teyit almadı.',
          summary: summaryLines(draft, state.lang), history: [], official: mockOptions.official, sources: mockOptions.sources, disclaimer: t('disclaimer', state.lang) };
      } else {
        view = await post('/api/escort/requests', { ...draft, consent: true });
      }
      if (view.emergency) {
        state.view = { emergency: true, message: view.message, hazard: view.hazard };
        const CustomEventType = doc.defaultView.CustomEvent;
        if (CustomEventType) doc.dispatchEvent(new CustomEventType('nabiz:emergency', { detail: { lang: state.lang, hazard: view.hazard } }));
      } else {
        state.view = view;
        addRecord(view.code, draft, summaryLines(draft, state.lang));
        state.views.set(view.code, view);
      }
      state.screen = 'status'; state.error = ''; render({ focus: true });
    } catch (error) { state.error = error.message || t('optionsError', state.lang); render(); }
  }

  function saveLocal() {
    if (!state.draft) return;
    const record = addRecord(null, state.draft, summaryLines(state.draft, state.lang));
    state.view = { code: null, at: record.at, status: 'local', status_text: t('onlyHere', state.lang), summary: record.summary, history: [] };
    state.screen = 'status'; render({ focus: true });
  }

  function removeRecord(code, localOnly = false, at = null) {
    state.records = state.records.filter((item) => localOnly ? !(item.code === null && (at === null || item.at === at)) : item.code !== code);
    if (code) state.views.delete(code);
    storeRecords();
    if (state.view && ((localOnly && state.view.code === null && (at === null || state.view.at === at)) || state.view.code === code)) { state.view = null; state.screen = 'closed'; }
    render();
  }

  async function cancel(code) {
    try {
      const view = MOCK ? { ...state.views.get(code), status: 'cancelled', status_text: 'Örnek: iptal edildi.' }
        : await post(`/api/escort/requests/${encodeURIComponent(code)}/cancel`, {});
      state.views.set(code, view); state.view = view; render();
    } catch (error) { state.error = error.message || t('noStored', state.lang); render(); }
  }

  function insertAfterJourney() {
    const journey = doc.querySelector('#journey-section');
    if (journey?.parentNode) { journey.insertAdjacentElement('afterend', createHost()); return true; }
    return false;
  }

  function createHost() {
    const host = doc.createElement('section'); host.className = 'escort'; host.id = 'escort-section'; host.setAttribute('aria-labelledby', 'escort-title');
    state.mounted = host; render();
    host.addEventListener('click', (event) => {
      const button = event.target.closest('[data-action]'); if (!button) return;
      const action = button.dataset.action;
      if (action === 'open') showForm();
      if (action === 'edit') showForm();
      if (action === 'send') void sendDraft();
      if (action === 'local') saveLocal();
      if (action === 'cancel') void cancel(button.dataset.code);
      if (action === 'remove') removeRecord(button.dataset.code);
      if (action === 'delete-local') removeRecord('', true, Number(button.dataset.at) || null);
    });
    host.addEventListener('change', (event) => {
      const target = event.target;
      if (target.matches('[data-consent]')) host.querySelector('[data-action="send"]')?.setAttribute('aria-disabled', String(!target.checked));
      if (target.matches('input[name="return_kind"]')) {
        const field = host.querySelector('.escort-return-time'); if (field) field.hidden = target.value !== 'same_day';
      }
    });
    host.addEventListener('submit', (event) => {
      const form = event.target.closest('[data-escort-form]'); if (!form) return;
      event.preventDefault();
      const draft = readForm(form), error = validateDraft(draft, state.options?.stations || [], new Date());
      if (error) { showValidation(form, error); return; }
      state.draft = draft; state.screen = 'summary'; state.error = ''; render({ focus: true });
    });
    return host;
  }

  function start() {
    if (doc.querySelector('#escort-section')) { addStylesheet(doc); return; }
    if (!doc.querySelector('#journey-section') && !doc.querySelector('#alternative')) return;
    addStylesheet(doc);
    if (!insertAfterJourney()) {
      const alternative = doc.querySelector('#alternative');
      if (!alternative) return;
      const section = alternative.closest('section');
      const watchRoot = section?.parentElement?.parentElement;
      if (!watchRoot) return;
      const observer = new MutationObserver(() => { if (insertAfterJourney()) observer.disconnect(); });
      observer.observe(watchRoot, { childList: true, subtree: true });
    }
    const result = doc.querySelector('#journey-result');
    if (result) {
      const observer = new MutationObserver(() => {
        if (!state.unverified && result.querySelector('.card.is-unverified')) { state.unverified = true; render(); }
      });
      observer.observe(result, { childList: true, subtree: true });
      if (result.querySelector('.card.is-unverified')) { state.unverified = true; render(); }
    }
    const from = doc.querySelector('#journey-from'), to = doc.querySelector('#journey-to');
    from?.addEventListener('change', () => { const meet = doc.querySelector('#escort-meet'); if (state.screen === 'form' && meet && !meet.value && state.options) meet.value = matchStation(from.value, state.options.stations); });
    to?.addEventListener('change', () => { const destination = doc.querySelector('#escort-to'); if (state.screen === 'form' && destination && !destination.value && state.options) destination.value = matchStation(to.value, state.options.stations); });
    void optionsOnce().then(syncStationOptions);
    if (!MOCK) {
      state.records.filter((item) => item.code).forEach((item) => { void refresh(item.code); });
      doc.addEventListener('visibilitychange', () => { if (!doc.hidden) state.records.filter((item) => item.code).forEach((item) => { void refresh(item.code); }); });
    }
    if (doc.defaultView) doc.defaultView.addEventListener('nabiz:lang', (event) => { state.lang = language(event.detail?.lang); render(); });
    render();
  }

  start();
  return { state, refresh, render, openForm: showForm };
}

export { TEXT, sourcesMarkup, mountEscort };
if (typeof document !== 'undefined') mountEscort(document);
