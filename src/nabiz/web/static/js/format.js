/* Formatting shared by every renderer: escaping, Turkish numbers, clock times, ages and the
 * confidence labels. Pure (no DOM, no network, no clock), so node can import it in tests. */

/* A missing value is the word, never a dash glyph that reads as a number or a minus (spec 14.1). */
const UNKNOWN = 'bilinmiyor';

function esc(value) {
  if (value === null || value === undefined) return '';
  return String(value).replace(/[&<>"']/g, (ch) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
  ));
}

function has(value) {
  return value !== null && value !== undefined && value !== '';
}

const isNum = (value) => has(value) && Number.isFinite(Number(value));

/** Turkish decimal comma, because "1.9 km" reads as nineteen to a Turkish speaker. */
function num(value, digits = 1) {
  if (!isNum(value)) return UNKNOWN;
  return Number(value).toLocaleString('tr-TR', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function int(value) {
  return isNum(value) ? Number(value).toLocaleString('tr-TR') : UNKNOWN;
}

/* İstanbul time whatever the visitor's machine says: the data is about İstanbul, and the same
 * answer must read the same in every browser (and in the node tests). */
const zoned = (opts) => new Intl.DateTimeFormat('tr-TR', { timeZone: 'Europe/Istanbul', ...opts });
const clockFmt = zoned({ hour: '2-digit', minute: '2-digit' });
const dateFmt = zoned({ day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });

function when(fmt, iso) {
  const t = Date.parse(iso || '');
  return Number.isFinite(t) ? fmt.format(t) : UNKNOWN;
}

const clock = (iso) => when(clockFmt, iso);
/** "27.07.2026 09:27", for a notice whose day matters. */
const dateTime = (iso) => when(dateFmt, iso);

/** Rounded down, like the server's provenance.age, so a mark and its answer agree. */
function shortAge(seconds) {
  if (!Number.isFinite(seconds)) return UNKNOWN;
  if (seconds < 90) return `${Math.floor(seconds)} sn`;
  if (seconds < 5400) return `${Math.floor(seconds / 60)} dk`;
  if (seconds < 172800) return `${Math.floor(seconds / 3600)} sa`;
  return `${Math.floor(seconds / 86400)} gün`;
}

/** İETT and İSPARK send names in capitals ("HACIKÖY", "4.LEVENT METRO"); Turkish casing keeps
 * İ and ı apart, which a plain title-case would not (the repo's tr_title rule). */
function trName(raw) {
  return String(raw || '').toLocaleLowerCase('tr')
    .replace(/(^|[\s.(/-])(\p{L})/gu, (_, before, letter) => before + letter.toLocaleUpperCase('tr'));
}

const CONFIDENCE_TR = { high: 'yüksek', medium: 'orta', low: 'düşük' };

export { UNKNOWN, esc, has, num, int, clock, dateTime, shortAge, trName, CONFIDENCE_TR };
