/* Vatandaş talepleri: the operator's queue for "Operatöre aktar + çeviri" (console.html #citizen-requests).
 * The operator reads the masked original and its Turkish text, writes a Turkish reply, previews the
 * translation into the visitor's language, may correct it, and only then sends. Sending seals an
 * operator_reply line in the ledger; the visitor's card picks the reply up on its next read.
 * Nothing here decides for the operator: the model only translates. */

import { get, post } from './api.js';
import { clock, esc } from './format.js';

const LIST_PATH = '/api/console/requests';
const POLL_MS = 20_000;
const MAX_CHARS = 1000;
const STYLESHEET = '/css/operator_requests.css';
const STATUS_TR = { waiting: 'bekliyor', answered: 'yanıtlandı' };
const REPLY_KIND_TR = {
  model: 'model çevirisi, değiştirilmeden', edited: 'model çevirisi, operatör düzeltti', operator: 'çeviriyi operatör yazdı',
  not_needed: 'çeviri gerekmedi', none: 'çeviri yok, Türkçe gönderildi',
};
const GUARD_TR = {
  injection: 'Soru girdi korumasına takıldı (talimat değişikliği). Modele gönderilmedi; metni yalnız siz görüyorsunuz.',
  hidden_text: 'Soruda gizli karakterler vardı; temizlendi. Modele gönderilmedi.',
};

function sectionMarkup() {
  return '<div class="section-head"><h2 id="citizen-requests-title">Vatandaş talepleri</h2>'
    + '<span class="section-note" id="op-count"></span></div>'
    + '<p class="section-note">Asistanın çözemediği, acil olmayan sorular. Acil durumlar buraya gelmez, vatandaşa 112 gösterilir. '
    + 'Kişisel veriler maskelenmiş gelir; 30 gün sonra silinir.</p>'
    + '<p class="status-line" id="op-queue-status" role="status" aria-live="polite"></p>'
    + '<div class="op-grid op-queue"><ol class="op-list" id="op-list" aria-label="Talepler"><li class="section-note">yükleniyor</li></ol>'
    + '<div id="op-detail" tabindex="-1"><p class="section-note">Listeden bir talep seçin.</p></div></div>';
}

function listItem(item, current) {
  const pressed = item.code === current ? ' aria-current="true"' : '';
  return `<li><button type="button" class="op-item" data-code="${esc(item.code)}"${pressed}>`
    + `<b>#${esc(item.code)} · ${esc(STATUS_TR[item.status] || item.status)}</b>`
    + `<span class="op-meta">${esc(item.category)} · dil ${esc(item.lang)} · ${esc(clock(item.created_at))}</span></button></li>`;
}

function textBlock(title, text, lang) {
  return `<div><p class="op-meta">${esc(title)}</p><blockquote class="op-quote" lang="${esc(lang)}">${esc(text)}</blockquote></div>`;
}

function requestBlock(item) {
  const turkish = item.turkish
    ? textBlock(`Türkçesi · ${item.translation.label}`, item.turkish, 'tr')
    : `<div><p class="op-meta">Türkçesi</p><p class="op-label">${esc(item.translation.label)}</p></div>`;
  const guard = item.guard ? `<p class="callout callout-warn">${esc(GUARD_TR[item.guard] || item.guard)}</p>` : '';
  const masked = item.masked_count ? ` · ${item.masked_count} kişisel veri maskelendi (${esc(item.masked_kinds.join(', '))})` : '';
  return `<h3>#${esc(item.code)} · ${esc(item.category)}</h3>`
    + `<p class="op-meta">Dil: ${esc(item.lang)} (${esc(item.lang_source)})${masked} · ${esc(clock(item.created_at))}</p>${guard}`
    + `<div class="op-pair">${textBlock('Orijinal (maskeli)', item.original, item.lang)}${turkish}</div>`;
}

function replyForm(item) {
  return '<div class="op-card" id="op-reply">'
    + `<label for="op-reply-tr">Türkçe cevabınız</label><textarea id="op-reply-tr" maxlength="${MAX_CHARS}" rows="4"></textarea>`
    + '<div class="op-actions"><button type="button" class="btn" data-op="preview">Çeviriyi önizle</button></div>'
    + '<div id="op-preview" hidden><p class="op-meta" id="op-preview-label"></p>'
    // A Turkish request needs no translation: the box stays hidden and the Turkish reply goes as written.
    + `<div id="op-translated-box"${item.lang === 'tr' ? ' hidden' : ''}>`
    + `<label for="op-reply-translated">Vatandaşın dilinde (${esc(item.lang)}): gönderilecek metin</label>`
    + `<textarea id="op-reply-translated" rows="4" lang="${esc(item.lang)}"></textarea>`
    + '<p class="field-hint">Çeviriyi okuyun; gerekirse düzeltin. Boş bırakırsanız cevap Türkçe gider.</p></div>'
    + '<div class="op-actions"><button type="button" class="btn btn-primary" data-op="send">Gönder</button></div></div>'
    + '<p class="op-status" id="op-reply-status" role="status" aria-live="polite"></p></div>';
}

function answeredBlock(reply) {
  const translated = reply.lang !== 'tr' ? textBlock(`Gönderilen (${reply.lang})`, reply.text, reply.lang) : '';
  return '<div class="op-card is-answered">'
    + `<p class="op-meta">Yanıtlandı · ${esc(clock(reply.answered_at))} · ${esc(REPLY_KIND_TR[reply.translation] || reply.translation)}`
    + ` · defter kaydı ${esc(reply.ledger_entry_id)}</p>`
    + `<div class="op-pair">${textBlock('Türkçe cevap', reply.text_tr, 'tr')}${translated}</div></div>`;
}

function detailMarkup(item) {
  return requestBlock(item) + (item.reply ? answeredBlock(item.reply) : replyForm(item));
}

function addStylesheet(doc) {
  if (doc.head.querySelector(`link[href="${STYLESHEET}"]`)) return;
  const sheet = doc.createElement('link');
  sheet.rel = 'stylesheet';
  sheet.href = STYLESHEET;
  doc.head.append(sheet);
}

function mountRequestsConsole(doc) {
  const section = doc.getElementById('citizen-requests');
  if (!section) return null;
  addStylesheet(doc);
  section.innerHTML = sectionMarkup();
  const $ = (sel) => section.querySelector(sel);
  let items = [];
  let current = null;
  let previewed = null;

  function renderDetail() {
    const item = items.find((entry) => entry.code === current);
    $('#op-detail').innerHTML = item ? detailMarkup(item) : '<p class="section-note">Listeden bir talep seçin.</p>';
    previewed = null;
  }

  async function load({ announce = false } = {}) {
    try {
      const res = await get(LIST_PATH);
      items = res.items || [];
      const html = items.length ? items.map((item) => listItem(item, current)).join('') : '<li class="section-note">Talep yok.</li>';
      if ($('#op-list').innerHTML !== html) $('#op-list').innerHTML = html;
      const sentence = `${res.counts.waiting} talep bekliyor, ${res.counts.answered} yanıtlandı.`
        + (res.model && res.model.available ? '' : ' Model tanımlı değil: yalnız Türkçe ve İngilizce talepler okunur, çeviri yok.');
      $('#op-count').textContent = `(${res.counts.waiting} bekliyor)`;
      if (announce || $('#op-queue-status').textContent !== sentence) $('#op-queue-status').textContent = sentence;
    } catch (err) {
      $('#op-queue-status').textContent = `Talepler alınamadı: ${err.message}`;
    }
  }

  async function preview() {
    const text = $('#op-reply-tr').value.trim();
    const status = $('#op-reply-status');
    if (!text) { status.textContent = 'Önce Türkçe cevabı yazın.'; return; }
    status.textContent = 'Çeviri hazırlanıyor.';
    try {
      const res = await post(`${LIST_PATH}/${encodeURIComponent(current)}/preview`, { text_tr: text });
      previewed = text;
      $('#op-preview').hidden = false;
      $('#op-preview-label').textContent = res.translation.label;
      $('#op-reply-translated').value = res.lang === 'tr' ? '' : (res.translation.text || '');
      (res.lang === 'tr' ? section.querySelector('[data-op="send"]') : $('#op-reply-translated')).focus();
      status.textContent = res.note;
    } catch (err) {
      status.textContent = err.message;
    }
  }

  async function send() {
    const text = $('#op-reply-tr').value.trim();
    const status = $('#op-reply-status');
    if (previewed !== text) { status.textContent = 'Cevap değişti: göndermeden önce çeviriyi yeniden önizleyin.'; return; }
    try {
      const res = await post(`${LIST_PATH}/${encodeURIComponent(current)}/reply`, {
        text_tr: text, text_translated: $('#op-reply-translated').value,
      });
      await load();
      renderDetail();
      $('#op-queue-status').textContent = res.message;
      doc.dispatchEvent(new CustomEvent('nabiz:ledger-changed'));
    } catch (err) {
      status.textContent = err.message;
    }
  }

  section.addEventListener('click', (event) => {
    const item = event.target.closest('.op-item');
    if (item) {
      current = item.dataset.code;
      section.querySelectorAll('.op-item[aria-current]').forEach((b) => b.removeAttribute('aria-current'));
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
    }
  });

  void load();
  setInterval(() => { if (!doc.hidden) void load(); }, POLL_MS);
  return { load };
}

if (typeof document !== 'undefined') mountRequestsConsole(document);

export { REPLY_KIND_TR, listItem, requestBlock, replyForm, answeredBlock, detailMarkup, mountRequestsConsole };
