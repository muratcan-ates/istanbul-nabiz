/* Operatöre aktar + çeviri, the visitor's side. When the assistant could not answer (unknown, refused or
 * guard card) or the "İnsanla görüş" card asks for it, the visitor may send the question to an İBB
 * operator, after reading one consent sentence. The server masks personal data and answers with a code;
 * the code is kept on this device (nabiz.requests.v1, 30 days) so the card survives a reload, and the
 * card asks /api/requests/{code} every 20 seconds while the page is open. Nothing is pushed.
 *
 * An emergency never waits for an operator: the server answers with the 112 card instead of a request,
 * and this module hands it to js/emergency.js (nabiz:emergency). */

import { get, post } from './api.js';
import { esc } from './format.js';

const STORAGE_KEY = 'nabiz.requests.v1';
const KEEP_DAYS = 30;
const KEEP_MAX = 10;
const POLL_MS = 20_000;
const MAX_CHARS = 1000;
const STYLESHEET = '/css/operator_requests.css';
const OFFER_MODES = /^guard_/;

const TEXT = {
  tr: {
    offer: 'Bu soruyu bir İBB operatörüne sorabilirsiniz. Acil durumlar için 112.',
    offerButton: 'Operatöre sor',
    formTitle: 'Operatöre ilet',
    question: 'Operatöre gidecek soru',
    lang: 'Sorunun dili',
    langs: { auto: 'Otomatik algıla', tr: 'Türkçe', en: 'English' },
    consent: 'Sorunuz ve seçtiğiniz dil İBB operatörüne iletilecek. Kişisel veriler maskelenir.',
    send: 'Operatöre ilet',
    cancel: 'Vazgeç',
    needConsent: 'Göndermek için onay kutusunu işaretleyin.',
    empty: 'Soru boş olamaz.',
    sending: 'Gönderiliyor.',
    emergency: "Bu acil bir durum olabilir. İBB operatörü 112'nin yerine geçmez: lütfen hemen 112'yi arayın.",
    waitingTitle: (code) => `Operatöre iletildi · #${code} · bekleniyor`,
    answeredTitle: 'İBB operatörü yanıtladı',
    yourQuestion: 'Sorunuz (maskeli)',
    turkish: 'Türkçesi',
    noTranslation: 'Çeviri şu an yok: operatör sorunuzu yazdığınız haliyle görecek.',
    remove: 'Kartı bu cihazdan kaldır',
    gone: 'Bu talep bulunamadı ya da 30 günlük süresi doldu.',
  },
  en: {
    offer: 'You can ask an İBB operator this question. For emergencies, call 112.',
    offerButton: 'Ask an operator',
    formTitle: 'Send to an operator',
    question: 'Question for the operator',
    lang: 'Language of the question',
    langs: { auto: 'Detect automatically', tr: 'Türkçe', en: 'English' },
    consent: 'Your question and the language you chose will be sent to an İBB operator. Personal data is masked.',
    send: 'Send to operator',
    cancel: 'Cancel',
    needConsent: 'Tick the consent box to send.',
    empty: 'The question cannot be empty.',
    sending: 'Sending.',
    emergency: 'This may be an emergency. An İBB operator does not replace 112: please call 112 now.',
    waitingTitle: (code) => `Sent to an operator · #${code} · waiting`,
    answeredTitle: 'An İBB operator replied',
    yourQuestion: 'Your question (masked)',
    turkish: 'In Turkish',
    noTranslation: 'No translation right now: the operator will read your question as you wrote it.',
    remove: 'Remove this card from this device',
    gone: 'This request was not found or its 30 days have passed.',
  },
};

const pageLang = (doc) => ((doc && doc.documentElement && doc.documentElement.lang) === 'en' ? 'en' : 'tr');
const words = (doc) => TEXT[pageLang(doc)];

/** Stored codes, newest last, dropping anything malformed or older than 30 days. */
function parseStored(raw, now = Date.now()) {
  let data = null;
  try { data = JSON.parse(raw || 'null'); } catch { data = null; }
  if (!data || data.version !== 1 || !Array.isArray(data.items)) return [];
  const oldest = now - KEEP_DAYS * 86_400_000;
  return data.items
    .filter((item) => item && /^[2-9A-Z]{8}$/.test(item.code) && Number.isFinite(item.at) && item.at > oldest)
    .slice(-KEEP_MAX);
}

function readCodes(storage) {
  try { return parseStored(storage.getItem(STORAGE_KEY)); } catch { return []; }
}

function writeCodes(storage, items) {
  try { storage.setItem(STORAGE_KEY, JSON.stringify({ version: 1, items: items.slice(-KEEP_MAX) })); } catch { /* private mode */ }
}

function offerMarkup(doc) {
  const t = words(doc);
  return `<div class="op-offer" data-op="offer"><p>${esc(t.offer)}</p>`
    + `<button type="button" class="btn" data-op="open">${esc(t.offerButton)}</button></div>`;
}

function formMarkup(question, doc) {
  const t = words(doc);
  const options = Object.entries(t.langs).map(([value, label]) => `<option value="${value}">${esc(label)}</option>`).join('');
  return '<section class="op-card" role="region" aria-labelledby="op-form-title">'
    + `<h3 id="op-form-title">${esc(t.formTitle)}</h3>`
    + `<label for="op-question">${esc(t.question)}</label>`
    + `<textarea id="op-question" maxlength="${MAX_CHARS}" rows="4">${esc(String(question || '').slice(0, MAX_CHARS))}</textarea>`
    + `<label for="op-lang">${esc(t.lang)}</label><select id="op-lang">${options}</select>`
    + `<p class="op-consent"><input type="checkbox" id="op-consent"><label for="op-consent">${esc(t.consent)}</label></p>`
    + '<div class="op-actions">'
    + `<button type="button" class="btn btn-primary" data-op="send">${esc(t.send)}</button>`
    + '<a class="btn btn-danger" href="tel:112">112</a>'
    + `<button type="button" class="btn" data-op="cancel">${esc(t.cancel)}</button></div>`
    + '<p class="op-status" role="status" aria-live="polite"></p></section>';
}

/** The request card: waiting, or the reply in the visitor's language with its Turkish text folded away. */
function cardMarkup(view, doc) {
  const t = words(doc);
  const reply = view && view.reply;
  const code = esc(view.code);
  let body = `<p class="op-meta">${esc(t.yourQuestion)}</p><blockquote class="op-quote">${esc(view.question || '')}</blockquote>`;
  if (!reply) {
    const missing = view.translation_note ? `<p class="op-meta">${esc(t.noTranslation)}</p>` : '';
    return `<section class="op-card" data-code="${code}" aria-labelledby="op-title-${code}">`
      + `<h3 id="op-title-${code}">${esc(t.waitingTitle(view.code))}</h3>${body}${missing}`
      + `<p class="op-meta">${esc(view.note || '')}</p>`
      + `<div class="op-actions"><a class="btn btn-danger" href="tel:112">112</a>`
      + `<button type="button" class="btn" data-op="remove">${esc(t.remove)}</button></div></section>`;
  }
  body = `<p lang="${esc(reply.lang)}">${esc(reply.text)}</p>`;
  if (reply.text_tr) body += `<details><summary>${esc(t.turkish)}</summary><p lang="tr">${esc(reply.text_tr)}</p></details>`;
  return `<section class="op-card is-answered" data-code="${code}" aria-labelledby="op-title-${code}">`
    + `<h3 id="op-title-${code}">${esc(t.answeredTitle)} · #${code}</h3>${body}`
    + `<p class="op-label" lang="tr">${esc(reply.label)}</p><p class="op-meta" lang="tr">${esc(view.simulated || '')}</p>`
    + `<div class="op-actions"><button type="button" class="btn" data-op="remove">${esc(t.remove)}</button></div></section>`;
}

/** Answers the assistant could not give: the unknown and refusal cards (is-refused) and the guard cards. */
function wantsOffer(shell) {
  if (!shell || shell.classList.contains('is-emergency')) return false;
  return shell.classList.contains('is-refused') || OFFER_MODES.test((shell.dataset && shell.dataset.ruleId) || '');
}

function questionBefore(shell) {
  let node = shell.previousElementSibling;
  while (node && !node.classList.contains('is-user')) node = node.previousElementSibling;
  const text = node && node.querySelector('.chat-text');
  return text ? text.textContent.trim() : '';
}

function addStylesheet(doc) {
  if (doc.head.querySelector(`link[href="${STYLESHEET}"]`)) return;
  const sheet = doc.createElement('link');
  sheet.rel = 'stylesheet';
  sheet.href = STYLESHEET;
  doc.head.append(sheet);
}

function mountRequests(doc, storage = globalThis.localStorage) {
  const log = doc && doc.querySelector('#chat-log');
  if (!log) return null;
  addStylesheet(doc);
  const cards = new Map();
  let timer = null;

  const holder = (html) => {
    const li = doc.createElement('li');
    li.className = 'op-request';
    li.innerHTML = html;
    log.appendChild(li);
    return li;
  };

  function show(view) {
    const li = cards.get(view.code) || holder('');
    li.innerHTML = cardMarkup(view, doc);
    li.hidden = false;
    li.dataset.status = view.status;
    cards.set(view.code, li);
    return li;
  }

  function forget(code) {
    writeCodes(storage, readCodes(storage).filter((item) => item.code !== code));
    cards.get(code)?.remove();
    cards.delete(code);
  }

  async function refresh(code) {
    try {
      show(await get(`/api/requests/${encodeURIComponent(code)}`));
    } catch (err) {
      if (err.status === 404) forget(code);
    }
  }

  function poll() {
    clearInterval(timer);
    timer = setInterval(() => {
      if (doc.hidden) return;
      const waiting = [...cards.entries()].filter(([, li]) => li.dataset.status === 'waiting').map(([code]) => code);
      if (!waiting.length) { clearInterval(timer); timer = null; return; }
      waiting.forEach((code) => { void refresh(code); });
    }, POLL_MS);
  }

  async function send(form) {
    const t = words(doc);
    const status = form.querySelector('.op-status');
    const text = form.querySelector('#op-question').value.trim();
    if (!text) { status.textContent = t.empty; return; }
    if (!form.querySelector('#op-consent').checked) { status.textContent = t.needConsent; return; }
    status.textContent = t.sending;
    try {
      const view = await post('/api/requests', { text, lang: form.querySelector('#op-lang').value, consent: true });
      if (view.emergency) {
        form.closest('li').innerHTML = `<p class="callout callout-warn" role="alert">${esc(t.emergency)}</p>`;
        doc.dispatchEvent(new CustomEvent('nabiz:emergency', { detail: { lang: pageLang(doc), hazard: view.hazard } }));
        return;
      }
      writeCodes(storage, [...readCodes(storage), { code: view.code, at: Date.now() }]);
      const li = form.closest('li');
      li.removeAttribute('id'); // no longer the form: a new form must not replace this card
      cards.set(view.code, li);
      show(view);
      poll();
    } catch (err) {
      status.textContent = err.message;
    }
  }

  function openForm(question) {
    doc.querySelector('#op-form')?.remove();
    const li = holder(formMarkup(question, doc));
    li.id = 'op-form';
    li.querySelector('#op-question').focus();
  }

  log.addEventListener('click', (event) => {
    const control = event.target.closest('[data-op]');
    if (!control) return;
    const action = control.dataset.op;
    if (action === 'open') openForm(questionBefore(control.closest('li.chat-msg')));
    if (action === 'send') void send(control.closest('.op-card'));
    if (action === 'cancel') { control.closest('li').remove(); doc.querySelector('#chat-input')?.focus(); }
    if (action === 'remove') forget(control.closest('.op-card').dataset.code);
  });
  doc.addEventListener('nabiz:operator-request', (event) => openForm((event.detail && event.detail.question) || ''));

  const offer = () => {
    log.querySelectorAll('li.chat-msg.is-assistant[aria-busy="false"]:not([data-op-seen])').forEach((shell) => {
      shell.dataset.opSeen = '1';
      const final = shell.querySelector('.chat-final');
      if (final && wantsOffer(shell)) final.insertAdjacentHTML('beforeend', offerMarkup(doc));
    });
  };
  new MutationObserver(offer).observe(log, { childList: true, attributes: true, attributeFilter: ['aria-busy'], subtree: true });

  const stored = readCodes(storage);
  stored.forEach((item) => {
    // Hidden until the server answers, so a failed read leaves no empty box in the conversation.
    const li = holder('');
    li.hidden = true;
    li.dataset.status = 'waiting';
    cards.set(item.code, li);
  });
  Promise.all(stored.map((item) => refresh(item.code))).then(poll);
  return { openForm, refresh };
}

if (typeof document !== 'undefined') mountRequests(document);

export {
  STORAGE_KEY, POLL_MS, TEXT, parseStored, offerMarkup, formMarkup, cardMarkup, wantsOffer, mountRequests,
};
