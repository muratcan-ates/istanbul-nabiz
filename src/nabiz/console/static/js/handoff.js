/* İnsanla görüş: when the assistant cannot help twice in a row, or the visitor asks for a person, a card
 * under the last answer prepares a five-line summary to read to 153. The summary is built on the device,
 * lives only in memory and the textarea, and never leaves the page: the visitor makes the call.
 *
 * Personal data is masked by E14's maskPii (js/pii_badge.js), loaded with a dynamic import so this module
 * works before that file lands. Without the masker the question text stays out (fail closed). */

import { esc } from './format.js';

// Kaynak: [BOŞLUK: Murat, 39 ilçe listesinin resmî kaynak URL'si]
const ILCELER = Object.freeze([
  'Adalar', 'Arnavutköy', 'Ataşehir', 'Avcılar', 'Bağcılar', 'Bahçelievler', 'Bakırköy', 'Başakşehir',
  'Bayrampaşa', 'Beşiktaş', 'Beykoz', 'Beylikdüzü', 'Beyoğlu', 'Büyükçekmece', 'Çatalca', 'Çekmeköy',
  'Esenler', 'Esenyurt', 'Eyüpsultan', 'Fatih', 'Gaziosmanpaşa', 'Güngören', 'Kadıköy', 'Kağıthane',
  'Kartal', 'Küçükçekmece', 'Maltepe', 'Pendik', 'Sancaktepe', 'Sarıyer', 'Silivri', 'Sultanbeyli',
  'Sultangazi', 'Şile', 'Şişli', 'Tuzla', 'Ümraniye', 'Üsküdar', 'Zeytinburnu',
]);
// places.csv still carries the old name.
const DISTRICT_ALIASES = Object.freeze({ eyüp: 'Eyüpsultan' });

// Order matters: the first label whose keyword appears wins.
const TOPICS = Object.freeze([
  ['Asansör ve adımsız erişim', ['asansör', 'yürüyen merdiven', 'adımsız', 'tekerlekli', 'engelli']],
  ['İstanbulkart', ['istanbulkart', 'kart dolum', 'bakiye']],
  ['Toplu ulaşım', ['metro', 'otobüs', 'tramvay', 'vapur', 'marmaray', 'metrobüs', 'durak', 'hat', 'sefer']],
  ['Otopark', ['otopark', 'ispark']],
  ['Su ve fatura', ['iski', 'su kesintisi', 'fatura']],
  ['Hava kalitesi', ['hava kalitesi', 'kirlilik']],
  ['Sosyal destek', ['sosyal destek', 'yardım', 'burs']],
]);
const DEFAULT_TOPIC = 'Genel bilgi';

// "kişi" and "temsilci" are recognised only in the case forms listed, so "bir insanın" or
// "muhtar temsilcisi" does not read as a request for a person.
const PERSON_PHRASES = Object.freeze([
  'insanla', 'bir insan', 'gerçek kişi', 'gerçek kişiyle', 'gerçek bir kişi', 'gerçek bir kişiyle',
  'canlı destek', 'temsilci', 'temsilciye', 'temsilciyle', 'temsilciden', 'yetkiliyle', 'operatörle',
  'talk to a human', 'talk to a person', 'real person', 'representative',
]);
// A bare "153" is not a request ("153'ü aradım"); "153'e bağla" is.
const CONNECT_153 = /153\S*\s+(ile\s+)?(bağla|bağlan|görüş|konuş|aktar)/u;

const SUMMARY_WANT = 'İstenen: Bu konuda bir 153 görevlisinden bilgi almak istiyorum.';
const SUMMARY_NO_MASK = 'Soru: (kişisel veri denetimi yüklenemedi; sorunuzu kendiniz yazın)';
const QUESTION_MAX = 240;
const READY_TEXT = 'İnsanla görüşme kartı hazır: özet, 153 ve 112 düğmeleri.';
const COPIED_TEXT = "Özet kopyalandı. 153'ü aradığınızda okuyabilirsiniz.";
const COPY_FAILED_TEXT = 'Kopyalama bu tarayıcıda açılamadı. Metni seçtim; basılı tutup kopyalayın.';
const STYLESHEET = '/css/handoff.css';

const fold = (text) => String(text || '').toLocaleLowerCase('tr');

/** A whole-word test on Turkish text: `\b` treats ç, ğ, ı, ö, ş, ü as non-word characters. */
function wordPattern(phrase) {
  const escaped = phrase.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return new RegExp(`(?<!\\p{L})${escaped}(?!\\p{L})`, 'u');
}

const PERSON_PATTERNS = PERSON_PHRASES.map(wordPattern);
const TOPIC_PATTERNS = TOPICS.map(([label, words]) => [label, words.map(wordPattern)]);

function asksForPerson(text) {
  // English text folded the Turkish way turns "I" into "ı"; the plain fold covers that.
  const variants = [fold(text), String(text || '').toLowerCase()];
  return variants.some((t) => PERSON_PATTERNS.some((re) => re.test(t)) || CONNECT_153.test(t));
}

function topicOf(text) {
  const folded = fold(text);
  const hit = TOPIC_PATTERNS.find(([, patterns]) => patterns.some((re) => re.test(folded)));
  return hit ? hit[0] : DEFAULT_TOPIC;
}

const DISTRICT_BY_KEY = new Map([
  ...ILCELER.map((name) => [fold(name), name]),
  ...Object.entries(DISTRICT_ALIASES),
]);

/** The first district named, suffixes after an apostrophe ignored ("Kadıköy'de", "Üsküdar’dan"). */
function districtOf(text) {
  for (const token of String(text || '').match(/[\p{L}'’]+/gu) || []) {
    const name = DISTRICT_BY_KEY.get(fold(token.split(/['’]/u)[0]));
    if (name) return name;
  }
  return null;
}

function offerReason(turns) {
  const last = turns[turns.length - 1];
  if (!last || last.role !== 'assistant' || last.emergency) return null;
  if (last.ruleId === 'layer:handoff') return 'layer';
  const lastUser = [...turns].reverse().find((t) => t.role === 'user');
  if (lastUser && asksForPerson(lastUser.text)) return 'asked';
  const assistants = turns.filter((t) => t.role === 'assistant');
  const [before, latest] = assistants.slice(-2);
  if (assistants.length >= 2 && before.unresolved && latest.unresolved) return 'unresolved';
  return null;
}

function questionLine(users, mask) {
  if (!mask) return SUMMARY_NO_MASK;
  const asked = [...users].reverse().find((t) => !asksForPerson(t.text));
  if (!asked) return 'Soru: (yazılmadı)';
  // Mask before cutting, so a number is never shortened past what the masker recognises.
  let question = String(mask(String(asked.text).replace(/\s*[\r\n]+\s*/g, ' ').trim()));
  if (question.length > QUESTION_MAX) question = `${question.slice(0, QUESTION_MAX - 3)}...`;
  return `Soru: ${question}`;
}

/** Five lines, always in this order. Konu and İlçe are dictionary labels; only Soru carries free text. */
function buildSummary(turns, mask) {
  const users = turns.filter((t) => t.role === 'user');
  const joined = users.map((t) => t.text).join('\n');
  const topic = topicOf(mask ? mask(joined) : joined);
  const district = districtOf(joined) || 'belirtilmedi';
  const unresolved = turns.filter((t) => t.role === 'assistant' && t.unresolved).length;
  const tried = `Denenen: İstanbul Nabız asistanına ${users.length} soru soruldu`
    + (unresolved ? `; ${unresolved} cevapta asistan doğrulanmış bir cevap veremedi.` : '.');
  return [`Konu: ${topic}`, questionLine(users, mask), `İlçe: ${district}`, tried, SUMMARY_WANT].join('\n');
}

function cardMarkup(summary, { tid } = {}) {
  const tidButton = tid
    ? `<a class="btn" href="${esc(tid)}" target="_blank" rel="noopener noreferrer" data-handoff="tid">TİD görüntülü görüşme</a>`
    : '';
  return '<section class="handoff-card callout" id="handoff-card" role="region" aria-labelledby="handoff-title" aria-live="off">'
    + '<div class="handoff-body">'
    + '<h3 id="handoff-title">İnsanla görüş</h3>'
    + "<p>153'ü ararken bu özeti okuyabilirsiniz. Özet yalnız bu ekranda durur; hiçbir yere gönderilmez ve saklanmaz.</p>"
    + "<label for=\"handoff-summary\">153'e okuyacağınız özet (düzenleyebilirsiniz)</label>"
    + `<textarea id="handoff-summary" rows="5" spellcheck="false">${esc(summary)}</textarea>`
    + '<div class="handoff-actions">'
    + '<button type="button" class="btn btn-primary" data-handoff="copy">Özeti kopyala</button>'
    + "<a class=\"btn btn-primary\" href=\"tel:153\" data-handoff=\"call\">153'ü ara</a>"
    + tidButton
    + '<a class="btn btn-danger" href="tel:112" data-handoff="emergency">Acil durum: 112</a>'
    + '<button type="button" class="btn" data-handoff="close">Kapat</button>'
    + '</div>'
    + '<p class="handoff-status" role="status" aria-live="polite"></p>'
    + '</div></section>';
}

/** The TİD link counts only once index.html shows it with a real https address. */
function tidHref(doc) {
  const link = doc && doc.querySelector('[data-pending="tid"]:not([hidden]) a[data-pending-url="tid-istanbul-senin"]');
  const href = link ? link.getAttribute('href') : null;
  return href && /^https:\/\//.test(href) ? href : null;
}

function ruleIdOf(shell) {
  if (shell.dataset && shell.dataset.ruleId) return shell.dataset.ruleId;
  const cite = [...shell.querySelectorAll('.chat-final li.cite')]
    .map((li) => li.textContent.trim()).find((text) => text.startsWith('Kural: '));
  return cite ? cite.slice('Kural: '.length).trim() : '';
}

function readTurns(log) {
  return [...log.querySelectorAll('li.chat-msg')].map((li) => (li.classList.contains('is-user')
    ? { role: 'user', text: (li.querySelector('.chat-text') || li).textContent.trim() }
    : {
      role: 'assistant',
      ruleId: ruleIdOf(li),
      unresolved: li.classList.contains('is-refused'),
      emergency: li.classList.contains('is-emergency'),
    }));
}

let maskerPromise = null;
function loadMasker() {
  if (!maskerPromise) {
    maskerPromise = import('./pii_badge.js')
      .then((mod) => (typeof mod.maskPii === 'function' ? (t) => mod.maskPii(t).masked : null))
      .catch(() => null);
  }
  return maskerPromise;
}

function addStylesheet(doc) {
  if (doc.head.querySelector(`link[href="${STYLESHEET}"]`)) return;
  const sheet = doc.createElement('link');
  sheet.rel = 'stylesheet';
  sheet.href = STYLESHEET;
  doc.head.append(sheet);
}

function copySummary(card) {
  const area = card.querySelector('#handoff-summary');
  const status = card.querySelector('.handoff-status');
  const fallback = () => { area.select(); status.textContent = COPY_FAILED_TEXT; };
  if (!navigator.clipboard || typeof navigator.clipboard.writeText !== 'function') {
    fallback();
    return;
  }
  navigator.clipboard.writeText(area.value)
    .then(() => { status.textContent = COPIED_TEXT; }, fallback);
}

function mountHandoff(log) {
  if (!log) return;
  const doc = log.ownerDocument;
  addStylesheet(doc);
  void loadMasker();

  async function open(shell) {
    const final = shell.querySelector('.chat-final');
    if (!final) return;
    const mask = await loadMasker();
    // A later answer may have arrived while the masker loaded; the card belongs under the newest one.
    const shells = log.querySelectorAll('li.chat-msg.is-assistant');
    if (shells[shells.length - 1] !== shell) return;
    doc.querySelector('#handoff-card')?.remove();
    const template = doc.createElement('template');
    template.innerHTML = cardMarkup(buildSummary(readTurns(log), mask), { tid: tidHref(doc) });
    const card = template.content.firstElementChild;
    final.appendChild(card);
    // Focus stays where it is; the status line is announced once the card is in the page.
    setTimeout(() => { card.querySelector('.handoff-status').textContent = READY_TEXT; }, 100);
  }

  const evaluate = () => {
    const fresh = [...log.querySelectorAll('li.chat-msg.is-assistant[aria-busy="false"]:not([data-handoff-seen])')];
    if (!fresh.length) return;
    fresh.forEach((shell) => { shell.dataset.handoffSeen = '1'; });
    const shells = log.querySelectorAll('li.chat-msg.is-assistant');
    const latest = shells[shells.length - 1];
    if (!fresh.includes(latest)) return;
    if (offerReason(readTurns(log))) void open(latest);
  };

  log.addEventListener('click', (event) => {
    const control = event.target.closest('#handoff-card [data-handoff]');
    if (!control) return;
    const card = control.closest('#handoff-card');
    if (control.dataset.handoff === 'copy') copySummary(card);
    if (control.dataset.handoff === 'close') {
      card.remove();
      doc.querySelector('#chat-input')?.focus();
    }
  });

  const observer = new MutationObserver(evaluate);
  observer.observe(log, { childList: true, attributes: true, attributeFilter: ['aria-busy'], subtree: true });
  evaluate();
}

if (typeof document !== 'undefined') mountHandoff(document.querySelector('#chat-log'));

export {
  ILCELER, TOPICS, asksForPerson, topicOf, districtOf, offerReason,
  buildSummary, cardMarkup, tidHref, readTurns, loadMasker, mountHandoff,
};
