/* Formatting shared by every renderer: escaping, Turkish numbers, clock times, ages and the
 * confidence labels. Pure (no DOM, no network, no clock), so node can import it in tests. */

function esc(value) {
  if (value === null || value === undefined) return '';
  return String(value).replace(/[&<>"']/g, (ch) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
  ));
}

/** Turkish decimal comma, because "1.9 km" reads as nineteen to a Turkish speaker. */
function num(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  return Number(value).toLocaleString('tr-TR', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function int(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  return Number(value).toLocaleString('tr-TR');
}

function has(value) {
  return value !== null && value !== undefined && value !== '';
}

function clock(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' });
}

/** Rounded down, like the server's provenance.age, so a chip and its card agree. */
function shortAge(seconds) {
  if (!Number.isFinite(seconds)) return '—';
  if (seconds < 90) return `${Math.floor(seconds)} sn`;
  if (seconds < 5400) return `${Math.floor(seconds / 60)} dk`;
  if (seconds < 172800) return `${Math.floor(seconds / 3600)} sa`;
  return `${Math.floor(seconds / 86400)} gün`;
}

const CONFIDENCE_TR = { high: 'yüksek', medium: 'orta', low: 'düşük' };

export { esc, num, int, has, clock, shortAge, CONFIDENCE_TR };
