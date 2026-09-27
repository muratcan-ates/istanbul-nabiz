/* Small, dependency-free helpers for route detection, step paging and explicit speech. */

const PLACE = String.raw`(?:\d+\.\s*)?[\p{Lu}][\p{L}\d]*(?:-[\p{Lu}][\p{L}\d]*)?(?:\s+(?:(?:\d+\.\s*)?[\p{Lu}][\p{L}\d]*(?:-[\p{Lu}][\p{L}\d]*)?)){0,2}`;
const TR_FROM = new RegExp(`(${PLACE})['’](?:n)?[dt][ae]n`, 'gu');
const TR_TO = new RegExp(`(${PLACE})['’](?:y|n)?[ae](?=$|[\\s.,!?;:])`, 'gu');
const TR_STATION = new RegExp(`(${PLACE})\\s+istasyon(?:u|da|de|ta|te|una|üne|unda|ünde|dan|den|tan|ten|undan|ünden)?\\b`, 'giu');
const EN_PLACE = String.raw`[\p{Lu}][\p{L}\d]*(?:\s+[\p{Lu}][\p{L}\d]*){0,2}`;
const EN_FROM_TO = new RegExp(`\\bfrom\\s+(${EN_PLACE})\\s+to\\s+(${EN_PLACE})(?=$|[\\s.,!?;:])`, 'u');
const EN_TO = new RegExp(`\\bto\\s+(${EN_PLACE})(?:\\s+station)?(?=$|[\\s.,!?;:])`, 'u');
const EN_STATION = new RegExp(`(${EN_PLACE})\\s+station\\b`, 'u');
const TRANSPORT_TOOLS = new Set([
  'plan_journey', 'metro_station_info', 'metro_equipment_status', 'iett_stops_search', 'places_resolve',
]);
const TR_OPENERS = new Set(['bugün', 'yarın', 'peki', 'acaba', 'şimdi', 'merhaba']);
const TR_TRAVEL = /nasıl\s+gid|gider|gidil|gidebil|ulaş|yol\s+tarif|yön\s+tarif|aktarma|adımsız|asansör/iu;
const EN_TRAVEL = /how\s+do\s+i\s+get|how\s+to\s+get|directions|route|step-free|lift|elevator/iu;

function cleanPlace(value) {
  const words = String(value || '').trim().split(/\s+/u);
  while (words.length && TR_OPENERS.has(words[0].toLocaleLowerCase('tr-TR'))) words.shift();
  return words.join(' ') || null;
}

function firstPlace(pattern, text) {
  pattern.lastIndex = 0;
  const match = pattern.exec(text);
  return match ? cleanPlace(match[1]) : null;
}

function routeHint({ question, tools = [], emergency = false, refused = false, lang = 'tr' } = {}) {
  if (emergency || refused) return null;
  const text = String(question || '');
  const names = Array.isArray(tools) ? tools.map((tool) => String(tool || '').trim()) : [];
  const hasTool = names.some((tool) => TRANSPORT_TOOLS.has(tool));
  let from = null;
  let to = null;
  let station = null;
  if (lang === 'en') {
    const pair = EN_FROM_TO.exec(text);
    if (pair) { from = cleanPlace(pair[1]); to = cleanPlace(pair[2]); }
    else to = firstPlace(EN_TO, text);
    station = firstPlace(EN_STATION, text);
  } else {
    from = firstPlace(TR_FROM, text);
    to = firstPlace(TR_TO, text);
    station = firstPlace(TR_STATION, text);
    if (!to) to = station;
  }
  const travelIntent = (lang === 'en' ? EN_TRAVEL : TR_TRAVEL).test(text);
  if (!to || (!travelIntent && !hasTool)) return null;
  return { from, to };
}

function pickVoiceFor(voices, lang = 'tr') {
  if (lang !== 'tr' && lang !== 'en') return null;
  const prefix = lang === 'en' ? 'en' : 'tr';
  const available = (Array.isArray(voices) ? voices : []).filter((voice) => (
    voice && typeof voice.lang === 'string'
      && (voice.lang.toLowerCase() === prefix || voice.lang.toLowerCase().startsWith(`${prefix}-`))
  ));
  if (!available.length) return null;
  if (prefix === 'tr') {
    const exact = available.filter((voice) => voice.lang.toLowerCase() === 'tr-tr');
    const localExact = exact.find((voice) => voice.localService === true);
    if (localExact) return localExact;
    const local = available.find((voice) => voice.localService === true);
    return local || exact[0] || available[0];
  }
  return available.find((voice) => voice.localService === true) || available[0];
}

function voiceNote(voice) {
  if (!voice) return null;
  return voice.localService === true ? 'none' : 'online';
}

function stepPosition(index, total) {
  const count = Math.max(0, Math.trunc(Number(total) || 0));
  const position = count ? Math.min(count - 1, Math.max(0, Math.trunc(Number(index) || 0))) : 0;
  return { index: position, n: count ? position + 1 : 0, total: count, first: position === 0, last: count === 0 || position === count - 1 };
}

function createSpeaker({ synth, Utterance, onState = () => {} } = {}) {
  let generation = 0;
  let active = false;

  function stop() {
    generation += 1;
    const wasActive = active;
    active = false;
    if (synth && typeof synth.cancel === 'function') synth.cancel();
    if (wasActive) onState(false);
  }

  function say(text, voice, lang = 'tr') {
    const wasActive = active;
    generation += 1;
    active = false;
    if (synth && typeof synth.cancel === 'function') synth.cancel();
    if (!synth || typeof synth.speak !== 'function' || typeof Utterance !== 'function' || !String(text || '').trim()) {
      if (wasActive) onState(false);
      return false;
    }
    const token = generation;
    const utterance = new Utterance(String(text));
    utterance.voice = voice || null;
    utterance.lang = (voice && voice.lang) || (lang === 'en' ? 'en-GB' : 'tr-TR');
    const finish = () => {
      if (token !== generation) return;
      active = false;
      onState(false);
    };
    utterance.onend = finish;
    utterance.onerror = finish;
    active = true;
    onState(true);
    try {
      synth.speak(utterance);
      return true;
    } catch {
      finish();
      return false;
    }
  }

  return { say, stop, get speaking() { return active; } };
}

export { routeHint, pickVoiceFor, voiceNote, stepPosition, createSpeaker };
