import { esc } from './format.js';
import { icon } from './icons.js';
import { PII_WARNING } from './disclosure.js';

const PII_KINDS = [
  { id: 'iban', label: 'IBAN' },
  { id: 'kart', label: 'KART NO' },
  { id: 'tckn', label: 'TC KİMLİK' },
  { id: 'telefon', label: 'TELEFON' },
  { id: 'eposta', label: 'E-POSTA' },
  { id: 'arac', label: 'PLAKA' },
];
const PII_BADGE_TEXT = (count) => `${count} kişisel veri gizlendi`;
const PII_NOTE_DEVICE = "Bu bilgiler Nabız'a gönderilmedi.";
const PII_NOTE_SERVER = 'Bu bilgiler yapay zekâ modeline gönderilmedi.';
const SPACE = /[\t\n\v\f\r\x1c-\x1f \x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]/u;
const PATTERNS = [
  ['iban', /(?<![0-9a-z])tr[0-9]{2}(?: ?[0-9]{4}){5} ?[0-9]{2}(?![0-9a-z])/gu],
  ['kart', /(?<![0-9])(?:[0-9]{4}(?:[ -]?[0-9]{4}){3}|[0-9]{4}[ -]?[0-9]{6}[ -]?[0-9]{5}|[0-9]{13,19})(?![0-9])/gu],
  ['tckn', /(?<![0-9])[1-9][0-9]{10}(?![0-9])/gu],
  ['telefon', /(?<![0-9+(])\(?(?:(?:\+|00)90[ -]?|0[ -]?)?\(?5[0-9]{2}\)?[ -]?[0-9]{3}[ -]?[0-9]{2}[ -]?[0-9]{2}(?![0-9])/gu],
  ['eposta', /(?<![a-z0-9._%+-])[a-z0-9._%+-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}/gu],
  ['arac', /(?<![0-9a-z])(0[1-9]|[1-7][0-9]|8[01])[ -]?([a-z]{1,3})[ -]?([0-9]{2,5})(?![0-9a-z])/gu],
];
const ARAC_WORDS = new Set('dk sn km m cm mm kg gr tl lt no ve ile ya da de mi mu ki bu su ne cok az en her bir iki uc ay yil gun hat'.split(' '));
const ARAC_AFTER = / (?:dk|dakika|durak|sefer|km|metre|m|tl|lira|kisi|kez|saat|sn|saniye)(?![a-z])/u;
const mountedDocuments = new WeakSet();

function foldUnit(ch) {
  if (SPACE.test(ch)) return ' ';
  const turkish = { 'İ': 'i', I: 'i', ı: 'i', Ş: 's', ş: 's', Ğ: 'g', ğ: 'g', Ü: 'u', ü: 'u', Ö: 'o', ö: 'o', Ç: 'c', ç: 'c', Â: 'a', â: 'a', Î: 'i', î: 'i', Û: 'u', û: 'u' };
  if (Object.hasOwn(turkish, ch)) return turkish[ch];
  const code = ch.codePointAt(0);
  if (code >= 0x0660 && code <= 0x0669) return String(code - 0x0660);
  if (code >= 0x06f0 && code <= 0x06f9) return String(code - 0x06f0);
  const folded = ch.toLowerCase().normalize('NFKD').replace(/\p{M}/gu, '');
  if (folded.length === 1) return folded;
  const lowered = ch.toLowerCase();
  return lowered.length === 1 ? lowered : ch;
}

function foldKeepLength(text) {
  let folded = '';
  for (let index = 0; index < text.length; index += 1) folded += foldUnit(text[index]);
  return folded;
}

function tcknValid(digits) {
  if (digits.length !== 11 || !/^[0-9]+$/u.test(digits) || digits[0] === '0') return false;
  const values = [...digits].map(Number);
  const odd = values[0] + values[2] + values[4] + values[6] + values[8];
  const even = values[1] + values[3] + values[5] + values[7];
  return (odd * 7 - even) % 10 === values[9] && values.slice(0, 10).reduce((sum, value) => sum + value, 0) % 10 === values[10];
}

function luhnValid(digits) {
  if (digits.length < 13 || digits.length > 19 || !/^[0-9]+$/u.test(digits)) return false;
  let total = 0;
  [...digits].reverse().forEach((ch, index) => {
    let value = Number(ch);
    if (index % 2) value = value * 2 > 9 ? value * 2 - 9 : value * 2;
    total += value;
  });
  return total % 10 === 0;
}

function ibanValid(compact) {
  if (compact.length !== 26 || compact.slice(0, 2).toLowerCase() !== 'tr' || !/^[0-9]+$/u.test(compact.slice(2))) return false;
  const rearranged = compact.slice(4) + compact.slice(0, 4).toUpperCase();
  let remainder = 0;
  for (const ch of rearranged) {
    const digits = /[A-Z]/u.test(ch) ? String(ch.charCodeAt(0) - 55) : ch;
    for (const digit of digits) remainder = (remainder * 10 + Number(digit)) % 97;
  }
  return remainder === 1;
}

function validCandidate(kind, candidate, folded) {
  if (kind === 'iban') return ibanValid(candidate[0].replaceAll(' ', ''));
  if (kind === 'kart') return luhnValid(candidate[0].replace(/[ -]/gu, ''));
  if (kind === 'tckn') return tcknValid(candidate[0]);
  if (kind === 'telefon' || kind === 'eposta') return true;
  const letters = candidate[2];
  const digitCount = candidate[3].length;
  const allowed = letters.length === 1 ? digitCount >= 4 && digitCount <= 5
    : letters.length === 2 ? digitCount >= 3 && digitCount <= 4 : digitCount >= 2 && digitCount <= 3;
  return allowed && !ARAC_WORDS.has(letters) && !ARAC_AFTER.test(folded.slice(candidate.index + candidate[0].length));
}

function overlaps(start, end, hits) {
  return hits.some((hit) => start < hit.end && end > hit.start);
}

function scanPii(text) {
  const folded = foldKeepLength(text);
  const hits = [];
  for (const [kind, pattern] of PATTERNS) {
    let position = 0;
    while (true) {
      pattern.lastIndex = position;
      const candidate = pattern.exec(folded);
      if (!candidate) break;
      const start = candidate.index;
      const end = start + candidate[0].length;
      if (validCandidate(kind, candidate, folded) && !overlaps(start, end, hits)) {
        hits.push({ kind, start, end });
        position = end;
      } else {
        position = start + 1;
      }
    }
  }
  return hits.sort((left, right) => left.start - right.start);
}

function maskPii(text) {
  const hits = scanPii(text);
  if (!hits.length) return { masked: text, count: 0, kinds: [] };
  let masked = '';
  let cursor = 0;
  const kinds = [];
  for (const hit of hits) {
    const label = PII_KINDS.find((item) => item.id === hit.kind).label;
    masked += `${text.slice(cursor, hit.start)}[${label}]`;
    cursor = hit.end;
    if (!kinds.includes(label)) kinds.push(label);
  }
  masked += text.slice(cursor);
  return { masked, count: hits.length, kinds };
}

function badgeMarkup(count, kinds, where = 'device') {
  if (!Number.isFinite(count) || count <= 0) return '';
  const labels = kinds.filter((kind) => PII_KINDS.some((item) => item.label === kind));
  const note = where === 'server' ? PII_NOTE_SERVER : PII_NOTE_DEVICE;
  return `<p class="pii-badge" role="note" data-pii-count="${count}">${icon('shield-lock')}<span class="tag is-info">${esc(PII_BADGE_TEXT(count))}</span>${labels.map((label) => ` <span class="tag">${esc(label)}</span>`).join('')} <span class="field-hint">${esc(note)}</span></p>`;
}

function warningMarkup() {
  return `<p class="chat-hint pii-warning" id="pii-warning">${esc(PII_WARNING)}</p>`;
}

function mountPiiBadge(doc, win) {
  const form = doc.getElementById('chat-form');
  const input = doc.getElementById('chat-input');
  if (!form || !input || mountedDocuments.has(doc)) return;
  mountedDocuments.add(doc);
  if (!doc.getElementById('pii-warning')) {
    const hint = doc.getElementById('chat-hint');
    if (hint) hint.insertAdjacentHTML('beforebegin', warningMarkup());
    else form.insertAdjacentHTML('beforeend', warningMarkup());
  }
  const describedBy = (input.getAttribute('aria-describedby') || '').split(/\s+/u).filter(Boolean);
  if (!describedBy.includes('pii-warning')) {
    input.setAttribute('aria-describedby', [...describedBy, 'pii-warning'].join(' '));
  }
  let pending = null;
  function onSubmit(event) {
    if (event.target.id !== 'chat-form') return;
    pending = null;
    const result = maskPii(input.value);
    if (result.count > 0) {
      input.value = result.masked;
      pending = { count: result.count, kinds: result.kinds };
    }
  }
  win.addEventListener('submit', onSubmit, true);
  const log = doc.getElementById('chat-log');
  if (!log || !win.MutationObserver) return;
  function inspect(shell) {
    if (!shell || shell.nodeType !== 1) return;
    if (shell.matches('li.chat-msg.is-assistant')) attachBadge(shell);
    shell.querySelectorAll('li.chat-msg.is-assistant').forEach(attachBadge);
  }
  function attachBadge(shell) {
    if (shell.getAttribute('data-pii-seen') !== '1') {
      shell.setAttribute('data-pii-seen', '1');
      if (pending) {
        const who = shell.querySelector('.chat-who');
        const markup = badgeMarkup(pending.count, pending.kinds, 'device');
        if (who) who.insertAdjacentHTML('afterend', markup);
        else shell.insertAdjacentHTML('afterbegin', markup);
        pending = null;
      }
    }
    if (!shell.querySelector('.pii-badge')) {
      const count = Number(shell.getAttribute('data-masked-count'));
      if (count > 0) {
        const kinds = (shell.getAttribute('data-masked-kinds') || '').split('|').filter(Boolean);
        const who = shell.querySelector('.chat-who');
        const markup = badgeMarkup(count, kinds, 'server');
        if (who) who.insertAdjacentHTML('afterend', markup);
        else shell.insertAdjacentHTML('afterbegin', markup);
      }
    }
  }
  const observer = new win.MutationObserver((records) => {
    for (const record of records) {
      if (record.type === 'attributes') inspect(record.target);
      for (const node of record.addedNodes || []) inspect(node);
    }
  });
  observer.observe(log, { childList: true, subtree: true, attributes: true, attributeFilter: ['data-masked-count'] });
}

if (typeof document !== 'undefined') mountPiiBadge(document, window);

export {
  PII_KINDS, foldKeepLength, tcknValid, luhnValid, ibanValid, scanPii, maskPii,
  badgeMarkup, warningMarkup, mountPiiBadge, PII_BADGE_TEXT, PII_NOTE_DEVICE, PII_NOTE_SERVER,
};
