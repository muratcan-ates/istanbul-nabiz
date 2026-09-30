/* E66: the report's processing path, beside its separate publication decision. */

import { MOCK, get, post } from './api.js';
import { esc } from './format.js';

const OUTCOME_KEY = 'nabiz.report-codes.v1';
const CODE_PATTERN = /^[2-9A-Z]{8}$/;
const STAGES = ['recorded', 'reviewing', 'info_needed', 'referred', 'resolution_reported', 'confirmed'];
const TEXT = {
  tr: {
    now: 'Şu an:', waitingLabel: 'Yanıt beklenen:', networkError: 'Sunucuya ulaşılamadı. Yeniden deneyin.',
    title: 'Bildirim zaman çizgisi', stages: ['Kaydedildi', 'İnceleniyor', 'Bilgi bekleniyor', 'Yönlendirildi', 'Çözüm bildirildi', 'Sizin teyidiniz'],
    kindText: { not_working: 'asansör kapalıydı', data_wrong: 'kayıt yanlış görünüyor' },
    status: { recorded: 'Kaydedildi. Simüle operatör incelemesi bekleniyor.', reviewing: 'İnceleniyor. Simüle operatör çalışıyor.', info_needed: 'Bilgi bekleniyor. Yanıtınız gerekli.', referred: 'Kuruma yönlendirildi. Kurum yanıtı bekleniyor.', resolution_reported: 'Çözüm bildirildi. Sizden teyit bekleniyor.', confirmed: 'Siz çözümün düzeldiğini teyit ettiniz.', reopened: 'Yeniden açıldı. Simüle operatör incelemesi bekleniyor.' },
    waiting: { operator: 'Simüle operatör', citizen: 'Siz', agency: 'Kurum', none: 'Kimse' },
    fixed: 'Düzeldi', ongoing: 'Devam ediyor', info: 'Bilgi gönder', send: 'Gönder', note: 'Ne gördünüz?', consent: 'Yazdığım metin kişisel bilgiler maskelenerek 30 gün saklanır.',
    operatorNote: 'Simüle operatör notu:', citizenNote: 'Vatandaş yazdı (maskeli):', reopened: 'Yeniden açıldı', official: 'Resmî kayıt', agencySite: 'Resmî site',
    officialText: 'Nabız resmî başvuru açmaz ve kurumun kaydını görmez. Resmî kayıt için', publication: 'Yayın kararı (E33):',
    publicationLabels: { waiting: 'Onay bekliyor', approved: 'Onaylandı', not_published: 'Yayımlanmadı', expired: 'Süresi doldu' },
    disclaimer: 'Resmî İBB hizmeti değildir.', unavailable: 'Bu bildirim artık bulunamıyor. E33 listesini yenileyin.',
    retry: 'Yeniden dene', loading: 'Zaman çizgisi yükleniyor.', emergency: "Nabız acil durumlarda yardımcı olamaz. İBB'ye 153'ten ulaşabilirsiniz.",
    changed: 'Bu adım güncellendi. Yeniden yükleyip deneyin.', tooMany: 'Bu bildirim için yanıt sınırına ulaştınız.',
    invalid: 'Metni ve rıza kutusunu kontrol edip yeniden deneyin.', serverError: 'Bildirim durumu şu an kullanılamıyor. Yeniden deneyin.',
    noCodes: '',
  },
  en: {
    now: 'Now:', waitingLabel: 'Waiting for:', networkError: 'The server could not be reached. Try again.',
    title: 'Report timeline', stages: ['Recorded', 'In review', 'More information needed', 'Referred', 'Resolution reported', 'Your confirmation'],
    kindText: { not_working: 'elevator was out of service', data_wrong: 'record appears incorrect' },
    status: { recorded: 'Recorded. Waiting for simulated operator review.', reviewing: 'In review by the simulated operator.', info_needed: 'More information needed. Your reply is requested.', referred: 'Referred to an agency. Waiting for its response.', resolution_reported: 'Resolution reported. Waiting for your confirmation.', confirmed: 'You confirmed that it is fixed.', reopened: 'Reopened. Waiting for simulated operator review.' },
    waiting: { operator: 'Simulated operator', citizen: 'You', agency: 'Agency', none: 'No one' },
    fixed: 'It is fixed', ongoing: 'Still happening', info: 'Send information', send: 'Send', note: 'What did you see?', consent: 'My text will be stored for 30 days after personal details are masked.',
    operatorNote: 'Simulated operator note:', citizenNote: 'Citizen wrote (masked):', reopened: 'Reopened', official: 'Official record', agencySite: 'Official site',
    officialText: 'Nabız does not open official applications or see agency records. For an official record, call', publication: 'Publication decision (E33):',
    publicationLabels: { waiting: 'Awaiting approval', approved: 'Approved', not_published: 'Not published', expired: 'Expired' },
    disclaimer: 'Not an official İBB service.', unavailable: 'This report is no longer available. Refresh the E33 list.',
    retry: 'Try again', loading: 'Loading timeline.', emergency: 'Nabız cannot help in an emergency. You can reach İBB on 153.',
    changed: 'This step changed. Reload and try again.', tooMany: 'You have reached the reply limit for this report.',
    invalid: 'Check the text and consent box, then try again.', serverError: 'The report status is unavailable. Try again.',
    noCodes: '',
  },
};

function lang(doc = document) {
  return doc.documentElement.lang.toLowerCase().startsWith('en') ? 'en' : 'tr';
}

function readCodes(storage) {
  try {
    const source = storage || globalThis.localStorage;
    const data = JSON.parse(source.getItem(OUTCOME_KEY) || '{}');
    if (data.version !== 1 || !Array.isArray(data.items)) return [];
    return [...new Set(data.items.map((item) => item?.code).filter((code) => typeof code === 'string' && CODE_PATTERN.test(code)))];
  } catch { return []; }
}

function safeUrl(raw) {
  try {
    const url = new URL(raw);
    return url.protocol === 'https:' ? url.href : '';
  } catch { return ''; }
}

function localTime(raw, locale) {
  const date = new Date(raw);
  if (!Number.isFinite(date.getTime())) return '';
  return new Intl.DateTimeFormat(locale === 'en' ? 'en-GB' : 'tr-TR', { dateStyle: 'short', timeStyle: 'short' }).format(date);
}

function responseError(status, locale) {
  const t = TEXT[locale] || TEXT.tr;
  if (status === 0) return t.networkError;
  if (status === 400 || status === 422) return t.invalid;
  if (status === 409) return t.changed;
  if (status === 429) return t.tooMany;
  return t.serverError;
}

function stepsMarkup(data, locale = 'tr') {
  const t = TEXT[locale] || TEXT.tr;
  return '<ol class="rt-steps">' + data.steps.map((step) => {
    const index = STAGES.indexOf(step.stage);
    const classes = step.current ? ' is-current' : step.reached ? ' is-done' : ' is-todo';
    const current = step.current ? ' aria-current="step"' : '';
    const time = step.reached && step.at ? '<time datetime="' + esc(step.at) + '">' + esc(localTime(step.at, locale)) + '</time>' : '';
    const reopen = step.stage === 'reviewing' && data.reopen_count > 0
      ? '<span class="tag is-warn">' + esc(t.reopened) + ' · ' + esc(data.reopen_count) + '</span>' : '';
    const agency = step.stage === 'referred' && data.agency
      ? '<span class="rt-agency">' + esc(data.agency.name) + '</span>' : '';
    return '<li class="rt-step' + classes + '" data-stage="' + esc(step.stage) + '"' + current + '><span>'
      + esc(t.stages[index] || step.stage) + '</span>' + time + reopen + agency + '</li>';
  }).join('') + '</ol>';
}

function actionMarkup(data, formOpen, locale) {
  const t = TEXT[locale] || TEXT.tr;
  if (data.stage !== 'resolution_reported' && data.stage !== 'info_needed') return '';
  if (data.stage === 'resolution_reported' && !formOpen) {
    return '<div class="rt-actions"><button class="btn btn-primary" type="button" data-action="fixed">' + esc(t.fixed) + '</button>'
      + '<button class="btn" type="button" data-action="ongoing">' + esc(t.ongoing) + '</button></div>';
  }
  const action = data.stage === 'info_needed' ? 'info' : 'ongoing';
  const title = data.stage === 'info_needed' ? t.info : t.ongoing;
  return '<form class="rt-form" data-respond="' + action + '"><label for="rt-text-' + esc(data.code) + '">' + esc(t.note) + '</label>'
    + '<textarea id="rt-text-' + esc(data.code) + '" name="text" minlength="5" maxlength="500" required></textarea>'
    + '<label class="check"><input type="checkbox" name="consent" required><span>' + esc(t.consent) + '</span></label>'
    + '<button class="btn btn-primary" type="submit">' + esc(title === t.info ? t.info : t.send) + '</button></form>';
}

function cardMarkup(data, options = {}) {
  const locale = options.locale || 'tr';
  const t = TEXT[locale] || TEXT.tr;
  if (options.emergency) {
    return '<article class="rt-card" data-code="' + esc(data.code) + '"><p class="rt-emergency" role="status">'
      + esc(t.emergency) + ' <a href="tel:153">153</a></p></article>';
  }
  const publication = t.publicationLabels[data.publication] || data.publication;
  const agency = data.agency || {};
  const agencyLink = safeUrl(agency.url);
  const agencyLine = agency.name
    ? '<p class="rt-agency-info">' + esc(agency.name) + (agencyLink ? ' · <a href="' + esc(agencyLink) + '" target="_blank" rel="noopener noreferrer">' + esc(t.agencySite) + '</a>' : '') + '</p>' : '';
  const historyNote = data.note ? '<p class="rt-note"><b>' + esc(t.operatorNote) + '</b> ' + esc(data.note) + '</p>' : '';
  const citizenNotes = ['info_needed', 'resolution_reported'].includes(data.stage)
    ? (data.history || []).filter((event) => event.by === 'citizen' && event.note_masked)
      .map((event) => '<p class="rt-note"><b>' + esc(t.citizenNote) + '</b> ' + esc(event.note_masked) + '</p>').join('')
    : '';
  const official = data.official || {};
  const office = official.agency || {};
  const officeUrl = safeUrl(office.url);
  const call = String(official.call || '').replace(/[^0-9]/g, '');
  const publicationLine = '<p class="rt-publication"><b>' + esc(t.publication) + '</b> ' + esc(publication) + '</p>';
  const officialLink = officeUrl ? ' · <a href="' + esc(officeUrl) + '" target="_blank" rel="noopener noreferrer">' + esc(office.name || '153') + '</a>' : '';
  const callLink = call ? ' <a href="tel:' + esc(call) + '">' + esc(call) + '</a>' : '';
  const panel = '<div class="rt-official"><h4>' + esc(t.official) + '</h4><p>' + esc(t.officialText)
    + callLink + officialLink + '.</p>' + publicationLine + '</div>';
  const error = options.error ? '<p class="rt-error" role="status">' + esc(options.error) + '</p><button class="btn btn-quiet" type="button" data-action="retry">' + esc(t.retry) + '</button>' : '';
  const kindText = t.kindText[data.kind] || data.kind_text;
  return '<article class="rt-card" data-code="' + esc(data.code) + '"><header><div><h3>' + esc(data.station) + ' · ' + esc(kindText)
    + '</h3><code>' + esc(data.code) + '</code></div><p class="rt-now" role="status" tabindex="-1">' + esc(t.now) + ' '
    + esc(t.status[data.stage] || t.status.recorded) + '</p><p class="rt-waiting">' + esc(t.waitingLabel) + ' '
    + esc(t.waiting[data.waiting_on] || t.waiting.none) + '</p></header>'
    + stepsMarkup(data, locale) + agencyLine + historyNote + citizenNotes + actionMarkup(data, options.formOpen, locale)
    + error + panel + '<p class="rt-disclaimer">' + esc(t.disclaimer) + '</p></article>';
}

function mount(doc) {
  if (!doc || MOCK) return null;
  const alternative = doc.querySelector('#alternative');
  if (!alternative) return null;
  let section = null;
  let listObserver = null;
  const codes = new Set();
  const cards = new Map();
  const errors = new Map();
  const forms = new Set();
  const pending = new Set();
  const inFlight = new Set();
  const host = doc.createElement('section');
  host.className = 'report-timeline';
  host.id = 'report-timeline';
  host.setAttribute('aria-labelledby', 'report-timeline-title');
  host.hidden = true;
  host.innerHTML = '<h2 id="report-timeline-title">' + esc(TEXT[lang(doc)].title) + '</h2><p class="rt-empty" role="status"></p>';

  function render() {
    const locale = lang(doc);
    host.hidden = codes.size === 0;
    const heading = host.querySelector('h2');
    heading.textContent = TEXT[locale].title;
    const visibleCodes = [...codes];
    const cardsHtml = visibleCodes.map((code) => {
      if (errors.get(code) === 404) return '<article class="rt-card" data-code="' + esc(code) + '"><p role="status">' + esc(TEXT[locale].unavailable) + '</p></article>';
      const data = cards.get(code);
      if (!data) return '<article class="rt-card" data-code="' + esc(code) + '" aria-busy="true">' + esc(TEXT[locale].loading) + '</article>';
      const failure = errors.get(code);
      return cardMarkup(data, { locale, error: failure === undefined || failure === 404 || failure === 'emergency'
        ? '' : responseError(failure, locale),
        formOpen: forms.has(code), emergency: errors.get(code) === 'emergency' });
    }).join('');
    host.querySelectorAll('.rt-card').forEach((old) => old.remove());
    host.insertAdjacentHTML('beforeend', cardsHtml);
  }

  async function refresh(code) {
    if (inFlight.has(code) || !codes.has(code)) return;
    inFlight.add(code);
    try {
      const data = await get('/api/report/timeline/' + encodeURIComponent(code));
      if (!codes.has(code)) return;
      cards.set(code, data);
      errors.delete(code);
    } catch (error) {
      errors.set(code, error.status === 404 ? 404 : error.status || 0);
    } finally {
      inFlight.delete(code);
    }
    render();
  }

  function syncCodes() {
    codes.clear();
    readCodes().forEach((code) => codes.add(code));
    [...cards.keys()].forEach((code) => { if (!codes.has(code)) cards.delete(code); });
    [...errors.keys()].forEach((code) => { if (!codes.has(code)) errors.delete(code); });
    [...codes].forEach((code) => { if (!cards.has(code) && errors.get(code) !== 404) void refresh(code); });
    render();
  }

  async function respond(code, action, text = '', consent = false) {
    if (pending.has(code)) return;
    pending.add(code);
    const button = host.querySelector('[data-code="' + code + '"] button[type="submit"], [data-code="' + code + '"] [data-action="fixed"]');
    if (button) { button.setAttribute('aria-busy', 'true'); button.setAttribute('aria-disabled', 'true'); }
    try {
      const result = await post('/api/report/timeline/' + encodeURIComponent(code) + '/respond', { action, text, consent });
      if (result.emergency) { errors.set(code, 'emergency'); forms.delete(code); render(); return; }
      cards.set(code, result);
      errors.delete(code);
      forms.delete(code);
      render();
      const article = host.querySelector('.rt-card[data-code="' + code + '"]');
      article?.querySelector('.rt-now')?.focus({ preventScroll: true });
      const current = article?.querySelector('[aria-current="step"]');
      if (current) current.classList.add('is-new');
    } catch (error) {
      errors.set(code, error.status === 404 ? 404 : error.status || 0);
      render();
    } finally { pending.delete(code); }
  }

  function attach(outcomes) {
    section = outcomes;
    section.after(host);
    const list = section.querySelector('.report-outcome-list');
    if (list) {
      listObserver = new MutationObserver(syncCodes);
      listObserver.observe(list, { childList: true, subtree: true, attributes: true, attributeFilter: ['data-code'] });
    }
    syncCodes();
  }

  const existing = doc.querySelector('#report-outcomes');
  if (existing) attach(existing);
  else {
    const observer = new MutationObserver(() => {
      const outcomes = doc.querySelector('#report-outcomes');
      if (!outcomes) return;
      observer.disconnect();
      attach(outcomes);
    });
    observer.observe(alternative.parentElement, { childList: true, subtree: true });
  }

  host.addEventListener('click', (event) => {
    const button = event.target.closest('button[data-action]');
    if (!button) return;
    const article = button.closest('.rt-card');
    const code = article?.dataset.code;
    if (!code) return;
    if (button.dataset.action === 'retry') { errors.delete(code); void refresh(code); return; }
    if (button.dataset.action === 'fixed') { void respond(code, 'fixed'); return; }
    if (button.dataset.action === 'ongoing') {
      forms.add(code); render();
      host.querySelector('[data-code="' + code + '"] textarea')?.focus({ preventScroll: true });
    }
  });
  host.addEventListener('submit', (event) => {
    const form = event.target.closest('form[data-respond]');
    if (!form) return;
    event.preventDefault();
    const article = form.closest('.rt-card');
    const text = form.elements.text.value.trim();
    const consent = form.elements.consent.checked;
    void respond(article.dataset.code, form.dataset.respond, text, consent);
  });
  doc.addEventListener('nabiz:report-sent', syncCodes);
  doc.addEventListener('nabiz:lang', render);
  doc.addEventListener('visibilitychange', () => {
    if (!doc.hidden) [...codes].forEach((code) => { void refresh(code); });
  });
  return { host, refresh, readCodes, syncCodes };
}

function loadStyles(doc) {
  if (doc.querySelector('link[href="/css/report_timeline.css"]')) return;
  const link = doc.createElement('link');
  link.rel = 'stylesheet';
  link.href = '/css/report_timeline.css';
  doc.head.append(link);
}

if (typeof document !== 'undefined') {
  loadStyles(document);
  const outcomes = document.querySelector('#report-outcomes');
  if (outcomes || document.querySelector('#alternative')) mount(document);
}

export { TEXT, stepsMarkup, cardMarkup, readCodes, responseError, mount };
