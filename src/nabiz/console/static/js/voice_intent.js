/* Pure, on-device intent rules for the Turkish voice flow. Keep emergency terms in step with policy.py. */

export function foldTr(text) {
  return String(text ?? '')
    .toLocaleLowerCase('tr')
    .replace(/[ı]/g, 'i')
    .normalize('NFKD')
    .replace(/\p{M}/gu, '')
    .replace(/[^\p{L}\p{N}]/gu, ' ')
    .trim()
    .replace(/\s+/g, ' ');
}

export const ACIL_PREFIXES = Object.freeze(['yangin', 'ambulans', 'polis', 'siddet', 'kalp', 'bayildi']);
export const EMERGENCY_WORDS = Object.freeze([
  'kaza', 'kazasi', 'yarali', 'yaralilar', 'kanama', 'kalp krizi', 'intihar', 'saldiri',
]);
export const EMERGENCY_STEMS = Object.freeze([
  'yaraland', 'kaniyor', 'nefes alamiyor', 'boguluyor', 'bilincini kaybet',
  'gaz kacag', 'gaz kaciyor', 'gaz koku', 'gaz sizinti',
  'dogalgaz kacag', 'dogalgaz kaciyor', 'dogalgaz koku', 'dogalgaz sizinti',
]);
export const URGENT_COMPANY = Object.freeze([
  'yardim', 'ambulans', 'dustu', 'kaza', 'kazasi', 'yarali', 'doktor', 'hastane',
]);
export const FALLEN_PERSON = Object.freeze([
  'biri', 'birisi', 'annem', 'babam', 'dedem', 'ninem', 'anneannem', 'babaannem', 'cocuk', 'cocugum',
  'yasli', 'adam', 'kadin', 'teyze', 'amca', 'esim', 'kardesim', 'arkadasim', 'oglum', 'kizim',
  'bebegim', 'yolcu', 'raya', 'raylara', 'kalkamiyor',
]);

export const OUT_CUES = Object.freeze([
  'calismiyor', 'calismadi', 'calismiyo', 'bozuk', 'bozul', 'arizali', 'ariza', 'kapali', 'kapatil',
  'kullanilamiyor', 'durdu', 'durmus', 'gitmiyor', 'hizmet disi',
]);
export const AGENCY_CUES = Object.freeze([
  ...OUT_CUES, 'akmiyor', 'kesildi', 'kesik', 'gelmedi', 'tasti', 'patladi',
]);
const QUESTION_PARTICLES = Object.freeze(['mi', 'mu', 'misin', 'midir', 'mudur', 'miyim']);
const QUESTION_OPENERS = Object.freeze([
  'ne', 'nasil', 'neden', 'nicin', 'hangi', 'hangisi', 'nerede', 'nereden', 'kac', 'kacta',
]);
const LOCATIVE_SUFFIXES = Object.freeze([
  'daki', 'deki', 'taki', 'teki', 'dan', 'den', 'tan', 'ten', 'nda', 'nde', 'nta', 'nte',
  'da', 'de', 'ta', 'te',
]);

export const AGENCY_KEYWORDS = Object.freeze([
  Object.freeze({ agency: 'iski', keyword: 'su', words: Object.freeze(['su', 'suyu', 'suyum', 'sular', 'sulari', 'susuz']), prefixes: Object.freeze(['kanalizasyon', 'rogar', 'logar']) }),
  Object.freeze({ agency: 'igdas', keyword: 'dogalgaz', words: Object.freeze(['dogal gaz']), prefixes: Object.freeze(['dogalgaz']) }),
  Object.freeze({ agency: 'iett', keyword: 'otobus', words: Object.freeze([]), prefixes: Object.freeze(['otobus', 'metrobus']) }),
  Object.freeze({ agency: 'metro', keyword: 'metro', words: Object.freeze([]), prefixes: Object.freeze(['metro', 'tramvay', 'funikuler', 'teleferik']) }),
  Object.freeze({ agency: 'ispark', keyword: 'otopark', words: Object.freeze([]), prefixes: Object.freeze(['otopark', 'parkomat']) }),
  Object.freeze({ agency: 'sehir_hatlari', keyword: 'vapur', words: Object.freeze([]), prefixes: Object.freeze(['vapur']) }),
]);

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function hasPhrase(text, phrase) {
  const escaped = escapeRegExp(phrase).replace(/\s+/g, '\\s+');
  return new RegExp(`(?:^| )${escaped}(?=$| )`).test(text);
}

function hasPrefix(text, prefix) {
  return text.split(' ').some((word) => word.startsWith(prefix));
}

function hasStem(text, stem) {
  const escaped = escapeRegExp(stem).replace(/\s+/g, '\\s+');
  return new RegExp(`(?:^| )${escaped}`).test(text);
}

function hasUrgentCompany(text) {
  const words = text.split(' ');
  return URGENT_COMPANY.some((term) => (
    term === 'kaza' || term === 'kazasi'
      ? words.includes(term)
      : words.some((word) => word.startsWith(term))
  ));
}

function hasFallenPerson(text) {
  const words = text.split(' ');
  return FALLEN_PERSON.some((term) => (
    term === 'kalkamiyor' ? words.some((word) => word.startsWith(term)) : words.includes(term)
  ));
}

export function looksLikeEmergency(transcript) {
  const text = foldTr(transcript);
  const words = text.split(' ');
  if (words.some((word) => ACIL_PREFIXES.some((prefix) => word.startsWith(prefix)))) return true;
  if (EMERGENCY_WORDS.some((phrase) => hasPhrase(text, phrase)) || EMERGENCY_STEMS.some((stem) => hasStem(text, stem))) return true;
  if (hasPhrase(text, 'acil') && hasUrgentCompany(text)) return true;
  return ['dustu', 'dustum', 'dusmus'].some((word) => hasPhrase(text, word)) && hasFallenPerson(text);
}

export function gasHazard(transcript) {
  const text = foldTr(transcript);
  return EMERGENCY_STEMS.some((stem) => stem.includes('gaz ') && hasStem(text, stem)) ? 'gas' : null;
}

function hasCue(text, cues) {
  return cues.some((cue) => {
    if (cue.includes(' ')) return hasPhrase(text, cue);
    return hasPrefix(text, cue);
  });
}

function isQuestion(text) {
  const words = text.split(' ');
  return words.some((word) => QUESTION_PARTICLES.includes(word))
    || QUESTION_OPENERS.some((opener) => words[0] === opener || words[0].startsWith(opener));
}

function stationPattern(name) {
  const parts = name.split(' ').map(escapeRegExp);
  const base = parts.join('\\s+');
  const suffixes = LOCATIVE_SUFFIXES.map(escapeRegExp).join('|');
  return new RegExp(`(?:^| )${base}(?:(?:${suffixes})|\\s+(?:${suffixes}))?(?=$| )`);
}

export function matchStation(folded, stationNames) {
  const text = foldTr(folded);
  const candidates = (stationNames || [])
    .filter((name) => typeof name === 'string' && foldTr(name))
    .map((name) => ({ name, folded: foldTr(name) }))
    .filter((item) => stationPattern(item.folded).test(text))
    .sort((left, right) => right.folded.length - left.folded.length);
  if (!candidates.length) return null;
  const longest = candidates[0].folded.length;
  const tied = candidates.filter((item) => item.folded.length === longest);
  if (new Set(tied.map((item) => item.folded)).size > 1) return null;
  return tied[0].name;
}

function matchesAgencyRule(text, rule) {
  return rule.words.some((word) => (word.includes(' ') ? hasPhrase(text, word) : text.split(' ').includes(word)))
    || rule.prefixes.some((prefix) => hasPrefix(text, prefix));
}

export function readIntent(transcript, stationNames) {
  const text = foldTr(transcript);
  if (looksLikeEmergency(text)) return { type: 'emergency', hazard: gasHazard(text) };
  if (!text || isQuestion(text)) return { type: 'none' };

  const station = matchStation(text, stationNames);
  const lift = hasPrefix(text, 'asansor');
  if (lift && hasCue(text, OUT_CUES) && station) {
    return { type: 'lift_report', station, kind: 'not_working' };
  }

  const escalator = hasPhrase(text, 'yuruyen merdiven') || hasPhrase(text, 'yuruyen bant');
  if (escalator && hasCue(text, OUT_CUES) && station) {
    return { type: 'agency', keyword: 'metro', agency: 'metro' };
  }

  if (!hasCue(text, AGENCY_CUES)) return { type: 'none' };
  const rule = AGENCY_KEYWORDS.find((candidate) => matchesAgencyRule(text, candidate));
  return rule
    ? { type: 'agency', keyword: rule.keyword, agency: rule.agency }
    : { type: 'none' };
}
