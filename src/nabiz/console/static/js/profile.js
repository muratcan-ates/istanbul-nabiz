/* Profilim and Hafızam live in this browser only (localStorage). Nothing here is sent as such: the
 * pages derive a `needs` list of functional constraints (step_free, stroller, ...) and send that, and
 * only after the visitor ticked the consent line. No identity, no diagnosis, no score.
 *
 * Keys: nabiz.profile.v1 {consent, needs[], stations[], lines[]}; nabiz.memory.v1 [{key, label, added_at}].
 * A memory key is either a need key (then it joins `needs`) or "station:<name>" / "line:<code>"
 * (then it joins the saved places). Anything else is remembered on the device and never sent. */

const PROFILE_KEY = 'nabiz.profile.v1';
const MEMORY_KEY = 'nabiz.memory.v1';

/** The functional needs the server understands. The label is what the visitor reads. */
const NEEDS = [
  { key: 'step_free', label: 'Adımsız erişim', hint: 'Asansör şart; yürüyen merdiven yetmez.', icon: 'wheelchair' },
  { key: 'stroller', label: 'Bebek arabası', hint: 'Adımsız yol ve geniş geçiş.', icon: 'baby-carriage' },
  { key: 'slow_walk', label: 'Yavaş yürüyorum', hint: 'Kısa yürüme, az aktarma.', icon: 'walk' },
  { key: 'low_vision', label: 'Az görüyorum', hint: 'Büyük yazı, tek sonuç, ekran okuyucu sırası.', icon: 'search' },
  { key: 'hearing', label: 'Az duyuyorum', hint: 'Anonsların yazılı hâli.', icon: 'bell' },
  { key: 'plain_language', label: 'Sade dil', hint: 'Kısa cümle, tek sayı, kod yerine kelime.', icon: 'list-details' },
];
const NEED_KEYS = new Set([...NEEDS.map((n) => n.key), 'answer_en']);

const EMPTY = { consent: false, needs: [], stations: [], lines: [], saved_at: null };

function readJson(key, fallback) {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch (err) {
    return fallback;
  }
}

function writeJson(key, value) {
  try { window.localStorage.setItem(key, JSON.stringify(value)); return true; } catch (err) { return false; }
}

function readProfile() {
  const p = readJson(PROFILE_KEY, null);
  if (!p || typeof p !== 'object') return { ...EMPTY };
  return {
    consent: p.consent === true,
    needs: Array.isArray(p.needs) ? p.needs.filter((k) => NEED_KEYS.has(k)) : [],
    stations: Array.isArray(p.stations) ? p.stations.filter(Boolean) : [],
    lines: Array.isArray(p.lines) ? p.lines.filter(Boolean) : [],
    saved_at: typeof p.saved_at === 'string' ? p.saved_at : null,
  };
}

function writeProfile(profile) {
  return writeJson(PROFILE_KEY, { ...EMPTY, ...profile, saved_at: new Date().toISOString() });
}

/** Whether a saved profile should be reviewed, without reading from or writing to storage. */
function profileReview(profile, nowIso, days = 30) {
  const savedAt = Date.parse(profile?.saved_at || '');
  const now = Date.parse(nowIso || '');
  if (!Number.isFinite(savedAt) || !Number.isFinite(now)) return { due: false, days: 0 };
  const elapsed = Math.max(0, Math.floor((now - savedAt) / 86400000));
  return { due: elapsed >= days, days: elapsed };
}

/** Keep answer-language preference in the existing local functional-needs list. */
function setAnswerLanguage(profile, lang) {
  const needs = Array.isArray(profile?.needs) ? profile.needs.filter((key) => key !== 'answer_en') : [];
  if (lang === 'en') needs.push('answer_en');
  return { ...profile, needs };
}

function answerLanguage(profile) {
  return Array.isArray(profile?.needs) && profile.needs.includes('answer_en') ? 'en' : 'tr';
}

function clearProfile() {
  try { window.localStorage.removeItem(PROFILE_KEY); } catch (err) { /* private mode */ }
}

function readMemory() {
  const m = readJson(MEMORY_KEY, []);
  return Array.isArray(m) ? m.filter((e) => e && typeof e.key === 'string') : [];
}

function addMemory(entry, now) {
  const list = readMemory().filter((e) => e.key !== entry.key);
  list.push({ key: entry.key, label: String(entry.label || entry.key), added_at: now || new Date().toISOString() });
  writeJson(MEMORY_KEY, list);
  return list;
}

function removeMemory(key) {
  const list = readMemory().filter((e) => e.key !== key);
  writeJson(MEMORY_KEY, list);
  return list;
}

function clearMemory() {
  try { window.localStorage.removeItem(MEMORY_KEY); } catch (err) { /* private mode */ }
}

const unique = (list) => [...new Set(list)];

/** What may leave the device: the need keys, and only with consent. */
function effectiveNeeds(profile, memory) {
  if (!profile.consent) return [];
  return unique([...profile.needs, ...memory.map((e) => e.key).filter((k) => NEED_KEYS.has(k))]);
}

/** Saved stations and lines from the profile and the confirmed memory entries. */
function savedPlaces(profile, memory) {
  const stations = [...profile.stations];
  const lines = [...profile.lines];
  memory.forEach((e) => {
    if (e.key.startsWith('station:')) stations.push(e.key.slice(8));
    if (e.key.startsWith('line:')) lines.push(e.key.slice(5));
  });
  return { stations: unique(stations), lines: unique(lines) };
}

export {
  NEEDS, NEED_KEYS, readProfile, writeProfile, clearProfile, readMemory, addMemory, removeMemory, clearMemory,
  effectiveNeeds, savedPlaces, profileReview, setAnswerLanguage, answerLanguage,
};
