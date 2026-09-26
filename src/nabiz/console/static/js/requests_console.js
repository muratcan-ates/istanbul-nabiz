/* Vatandaş talepleri: the operator's queue for "Operatöre aktar + çeviri" (console.html #citizen-requests).
 * The operator reads the masked original and its Turkish text, writes a Turkish reply, previews the
 * translation into the visitor's language, may correct it, and only then sends. Sending seals an
 * operator_reply line in the ledger; the visitor's card picks the reply up on its next read.
 * Nothing here decides for the operator: the model only translates. */

import { get, post } from './api.js';
import { clock, esc } from './format.js';
import { currentLang, loadCatalogs, t } from './i18n_text.js';

const LIST_PATH = '/api/console/requests';
const POLL_MS = 20_000;
const MAX_CHARS = 1000;
const STYLESHEET = '/css/operator_requests.css';

const guardCopy = (guard) => {
  if (guard === 'injection') return t('ui.opq.guard_injection', 'Soru girdi korumasına takıldı (talimat değişikliği). Modele gönderilmedi; metni yalnız siz görüyorsunuz.');
  if (guard === 'hidden_text') return t('ui.opq.guard_hidden_text', 'Soruda gizli karakterler vardı; temizlendi. Modele gönderilmedi.');
  return guard;
};

function sectionMarkup() {
  return `<div class="section-head"><h2 id="citizen-requests-title">${esc(t('ui.opq.title', 'Vatandaş talepleri'))}</h2>`
    + '<span class="section-note" id="op-count"></span></div>'
    + `<p class="section-note">${esc(t('ui.opq.description', 'Asistanın çözemediği, acil olmayan sorular. Acil durumlar buraya gelmez, vatandaşa 112 gösterilir. Kişisel veriler maskelenmiş gelir; 30 gün sonra silinir.'))}</p>`
    + '<p class="status-line" id="op-queue-status" role="status" aria-live="polite"></p>'
    + `<div class="op-grid op-queue"><ol class="op-list" id="op-list" aria-label="${esc(t('ui.opq.list_label', 'Talepler'))}"><li class="section-note">${esc(t('ui.opq.loading', 'yükleniyor'))}</li></ol>`
    + `<div id="op-detail" tabindex="-1"><p class="section-note">${esc(t('ui.opq.select_request', 'Listeden bir talep seçin.'))}</p></div></div>`;
}

function listItem(item, current) {
  const pressed = item.code === current ? ' aria-current="true"' : '';
  const status = item.status === 'waiting' ? t('ui.opq.waiting', 'bekliyor')
    : item.status === 'answered' ? t('ui.opq.answered', 'yanıtlandı') : item.status;
  return `<li><button type="button" class="op-item" data-code="${esc(item.code)}"${pressed}>`
    + `<b>#${esc(item.code)} · ${esc(status)}</b>`
    + `<span class="op-meta"><span lang="tr">${esc(item.category)}</span> · ${esc(t('ui.opq.language_tag', 'dil {lang}', { lang: item.lang }))} · ${esc(clock(item.created_at))}</span></button></li>`;
}

function textBlock(title, text, lang, titleLang = currentLang()) {
  const titleAttribute = titleLang ? ` lang="${esc(titleLang)}"` : '';
  return `<div><p class="op-meta"${titleAttribute}>${title}</p><blockquote class="op-quote" lang="${esc(lang)}">${esc(text)}</blockquote></div>`;
}

function replyKind(translation) {
  if (translation === 'model') return t('ui.opq.reply_kind.model', 'model çevirisi, değiştirilmeden');
  if (translation === 'edited') return t('ui.opq.reply_kind.edited', 'model çevirisi, operatör düzeltti');
  if (translation === 'operator') return t('ui.opq.reply_kind.operator', 'çeviriyi operatör yazdı');
  if (translation === 'not_needed') return t('ui.opq.reply_kind.not_needed', 'çeviri gerekmedi');
  if (translation === 'none') return t('ui.opq.reply_kind.none', 'çeviri yok, Türkçe gönderildi');
  return translation;
}

function replyForm(item) {
  return '<div class="op-card" id="op-reply">'
    + `<label for="op-reply-tr">${esc(t('ui.opq.reply_label', 'Türkçe cevabınız'))}</label><textarea id="op-reply-tr" maxlength="${MAX_CHARS}" rows="4"></textarea>`
    + `<div class="op-actions"><button type="button" class="btn" data-op="preview">${esc(t('ui.opq.preview', 'Çeviriyi önizle'))}</button></div>`
    + '<div id="op-preview" hidden><p class="op-meta" id="op-preview-label" lang="tr"></p>'
    // A Turkish request needs no translation: the box stays hidden and the Turkish reply goes as written.
    + `<div id="op-translated-box"${item.lang === 'tr' ? ' hidden' : ''}>`
    + `<label for="op-reply-translated">${esc(t('ui.opq.translated_label', 'Vatandaşın dilinde ({lang}): gönderilecek metin', { lang: item.lang }))}</label>`
    + `<textarea id="op-reply-translated" rows="4" lang="${esc(item.lang)}"></textarea>`
    + `<p class="field-hint">${esc(t('ui.opq.preview_hint', 'Çeviriyi okuyun; gerekirse düzeltin. Boş bırakırsanız cevap Türkçe gider.'))}</p></div>`
    + `<div class="op-actions"><button type="button" class="btn btn-primary" data-op="send">${esc(t('ui.opq.send', 'Gönder'))}</button></div></div>`
    + '<p class="op-status" id="op-reply-status" role="status" aria-live="polite"></p></div>';
}

function answeredBlock(reply) {
  const translated = reply.lang !== 'tr'
    ? textBlock(`${esc(t('ui.opq.sent', 'Gönderilen ({lang})', { lang: reply.lang }))}`, reply.text, reply.lang) : '';
  const note = t('ui.opq.answered_meta', 'Yanıtlandı · {time} · {kind} · defter kaydı {entry}', {
    time: clock(reply.answered_at), kind: replyKind(reply.translation), entry: reply.ledger_entry_id,
  });
  return '<div class="op-card is-answered">'
    + `<p class="op-meta" lang="${currentLang()}">${esc(note)}</p>`
    + `<div class="op-pair">${textBlock(esc(t('ui.opq.turkish_answer', 'Türkçe cevap')), reply.text_tr, 'tr')}${translated}</div></div>`;
}

function detailMarkup(item) {
  const masked = item.masked_count
    ? ` · ${esc(t('ui.opq.masked', '{count} kişisel veri maskelendi', { count: item.masked_count }))} <span lang="tr">(${esc(item.masked_kinds.join(', '))})</span>` : '';
  const languageMarkup = `<p class="op-meta" lang="${currentLang()}">${esc(t('ui.opq.language_label', 'Dil: {lang}', { lang: item.lang }))}`
    + ` <span lang="tr">(${esc(item.lang_source)})</span>${masked} · ${esc(clock(item.created_at))}</p>`;
  const guard = item.guard ? `<p class="callout callout-warn" lang="${currentLang()}">${esc(guardCopy(item.guard))}</p>` : '';
  const turkish = item.turkish
    ? textBlock(`${esc(t('ui.opq.turkish_label', 'Türkçesi'))} · <span lang="tr">${esc(item.translation.label)}</span>`, item.turkish, 'tr')
    : `<div><p class="op-meta">${esc(t('ui.opq.turkish_label', 'Türkçesi'))}</p><p class="op-label" lang="tr">${esc(item.translation.label)}</p></div>`;
  const request = `<h3>#${esc(item.code)} · <span lang="tr">${esc(item.category)}</span></h3>${languageMarkup}${guard}`
    + `<div class="op-pair">${textBlock(esc(t('ui.opq.original', 'Orijinal (maskeli)')), item.original, item.lang)}${turkish}</div>`;
  return request + (item.reply ? answeredBlock(item.reply) : replyForm(item));
}

function addStylesheet(doc) {
  if (doc.head.querySelector(`link[href="${STYLESHEET}"]`)) return;
  const sheet = doc.createElement('link');
  sheet.rel = 'stylesheet';
  sheet.href = STYLESHEET;
  doc.head.append(sheet);
}

async function mountRequestsConsole(doc) {
  const section = doc.getElementById('citizen-requests');
  if (!section) return null;
  const location = (doc.defaultView && doc.defaultView.location) || globalThis.location || { search: '' };
  // The console has no language switch: only /console?lang=en reads the catalogue, and then only for this section.
  if (new URLSearchParams(location.search).get('lang') === 'en') await loadCatalogs('en');
  addStylesheet(doc);
  section.innerHTML = sectionMarkup();
  const $ = (selector) => section.querySelector(selector);
  let items = [];
  let current = null;
  let previewed = null;
  let previewResult = null;

  function showStatus(node, text, serverText = false) {
    node.textContent = text;
    if (serverText) node.lang = 'tr'; else node.lang = currentLang();
  }

  function showLoadError(node, error) {
    node.innerHTML = `<span lang="${currentLang()}">${esc(t('ui.opq.load_error', 'Talepler alınamadı:'))}</span> `
      + `<span lang="tr">${esc(error)}</span>`;
  }

  function renderDetail(preserve = false) {
    const old = preserve ? $('#op-detail') : null;
    const oldReply = old && old.querySelector('#op-reply-tr');
    const replyValue = oldReply && oldReply.value;
    const translatedValue = old && old.querySelector('#op-reply-translated')?.value;
    const previewVisible = old && old.querySelector('#op-preview') && !old.querySelector('#op-preview').hidden;
    const focused = old && old.contains(doc.activeElement) ? doc.activeElement.id : '';
    const item = items.find((entry) => entry.code === current);
    $('#op-detail').innerHTML = item ? detailMarkup(item) : `<p class="section-note">${esc(t('ui.opq.select_request', 'Listeden bir talep seçin.'))}</p>`;
    previewed = preserve ? previewed : null;
    if (oldReply && $('#op-reply-tr')) $('#op-reply-tr').value = replyValue;
    if (translatedValue !== undefined && $('#op-reply-translated')) $('#op-reply-translated').value = translatedValue;
    if (previewVisible && previewResult && $('#op-preview')) {
      $('#op-preview').hidden = false;
      $('#op-preview-label').textContent = previewResult.label;
      $('#op-preview-label').lang = 'tr';
    }
    if (focused) $(`#${focused}`)?.focus();
  }

  async function load({ announce = false } = {}) {
    try {
      const res = await get(LIST_PATH);
      items = res.items || [];
      const html = items.length ? items.map((item) => listItem(item, current)).join('')
        : `<li class="section-note">${esc(t('ui.opq.none', 'Talep yok.'))}</li>`;
      if ($('#op-list').innerHTML !== html) $('#op-list').innerHTML = html;
      let sentence = t('ui.opq.queue_status', '{waiting} talep bekliyor, {answered} yanıtlandı.', {
        waiting: res.counts.waiting, answered: res.counts.answered,
      });
      if (!(res.model && res.model.available)) sentence += ` ${t('ui.opq.model_unavailable', 'Model tanımlı değil: yalnız Türkçe ve İngilizce talepler okunur, çeviri yok.')}`;
      $('#op-count').textContent = t('ui.opq.waiting_count', '({count} bekliyor)', { count: res.counts.waiting });
      $('#op-count').lang = currentLang();
      if (announce || $('#op-queue-status').textContent !== sentence) showStatus($('#op-queue-status'), sentence);
    } catch (err) {
      showLoadError($('#op-queue-status'), err.message);
    }
  }

  async function preview() {
    const text = $('#op-reply-tr').value.trim();
    const status = $('#op-reply-status');
    if (!text) { showStatus(status, t('ui.opq.write_first', 'Önce Türkçe cevabı yazın.')); return; }
    showStatus(status, t('ui.opq.translating', 'Çeviri hazırlanıyor.'));
    try {
      const res = await post(`${LIST_PATH}/${encodeURIComponent(current)}/preview`, { text_tr: text });
      previewed = text;
      previewResult = { label: res.translation.label, text: res.lang === 'tr' ? '' : (res.translation.text || ''), lang: res.lang, note: res.note };
      $('#op-preview').hidden = false;
      $('#op-preview-label').textContent = res.translation.label;
      $('#op-preview-label').lang = 'tr';
      $('#op-reply-translated').value = previewResult.text;
      $('#op-reply-translated').lang = res.lang;
      (res.lang === 'tr' ? section.querySelector('[data-op="send"]') : $('#op-reply-translated')).focus();
      showStatus(status, res.note, true);
    } catch (err) {
      showStatus(status, err.message, true);
    }
  }

  async function send() {
    const text = $('#op-reply-tr').value.trim();
    const status = $('#op-reply-status');
    if (previewed !== text) { showStatus(status, t('ui.opq.preview_again', 'Cevap değişti: göndermeden önce çeviriyi yeniden önizleyin.')); return; }
    try {
      const res = await post(`${LIST_PATH}/${encodeURIComponent(current)}/reply`, {
        text_tr: text, text_translated: $('#op-reply-translated').value,
      });
      await load();
      renderDetail();
      showStatus($('#op-queue-status'), res.message, true);
      doc.dispatchEvent(new CustomEvent('nabiz:ledger-changed'));
    } catch (err) {
      showStatus(status, err.message, true);
    }
  }

  section.addEventListener('click', (event) => {
    const item = event.target.closest('.op-item');
    if (item) {
      current = item.dataset.code;
      section.querySelectorAll('.op-item[aria-current]').forEach((button) => button.removeAttribute('aria-current'));
      item.setAttribute('aria-current', 'true');
      renderDetail();
      $('#op-detail').focus();
      return;
    }
    const control = event.target.closest('[data-op]');
    if (control && control.dataset.op === 'preview') void preview();
    if (control && control.dataset.op === 'send') void send();
  });
  section.addEventListener('input', (event) => {
    if (event.target.id === 'op-reply-tr' && previewed !== null && event.target.value.trim() !== previewed) {
      $('#op-preview').hidden = true;
      previewed = null;
      previewResult = null;
    }
  });
  void load();
  setInterval(() => { if (!doc.hidden) void load(); }, POLL_MS);
  return { load };
}

if (typeof document !== 'undefined') void mountRequestsConsole(document);

export { guardCopy, listItem, replyForm, answeredBlock, detailMarkup, mountRequestsConsole };
