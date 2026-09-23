/* There is no language model on this page. The question box is a keyword router: it picks one
 * of the HTTP endpoints and shows what came back. Saying so in the UI is cheaper than pretending
 * otherwise and being caught by a user who asks something the router cannot parse.
 * Pure: tests/test_web.py imports route() in node and checks it against a table of questions. */

const FILLER = new Set([
  'var', 'yok', 'mı', 'mi', 'mu', 'mü', 'nasıl', 'ne', 'zaman', 'gelir', 'geliyor', 'kaç', 'dakika',
  'otopark', 'otoparkı', 'park', 'yer', 'hava', 'kalitesi', 'kirlilik', 'trafik', 'metro', 'arıza',
  'istasyon', 'istasyonu', 'asansör', 'durak', 'durağı', 'durağına', 'otobüs', 'otobüsü', 'hat', 'hattı',
  'bugün', 'şimdi', 'şu', 'an', 'anda', 'için', 'bir', 'yakın', 'yakınında', 'civarında', 'en', 'nerede',
  'nerde', 'koşu', 'koşmak', 'uygun', 'mudur', 'lütfen', 'ile', 've', 'de', 'da',
]);

/* Turkish is agglutinative, so "istasyonunda" and "durakları" are the same words the
 * filler list already knows with case endings glued on. Matching a few stems is enough
 * to pull the place name out of a question without pretending to do morphology. */
/* 'havas'/'havad'/'havay' cover "havası", "havada", "havayı" without touching
 * "havalimanı" — the airport is a place name, not a word about the air. */
const FILLER_STEMS = [
  'istasyon', 'durak', 'durağ', 'otopark', 'otobüs', 'asansör', 'merdiven', 'yürüyen', 'hatt',
  'havas', 'havad', 'havay',
];

const METRO_RE = /^(M\d{1,2}[AB]?|T\d{1,2}|F\d|TF\d)$/i;
const BUS_RE = /^\d{1,3}[A-Za-zÇĞİÖŞÜçğıöşü]{0,2}$/;

function cleanWord(word) {
  return word.replace(/[’'´`].*$/, '').replace(/^[^0-9A-Za-zÇĞİÖŞÜçğıöşü]+|[^0-9A-Za-zÇĞİÖŞÜçğıöşü]+$/g, '');
}

function tokenize(text) {
  return text.split(/[\s,.;:!?()"]+/).map(cleanWord).filter(Boolean);
}

function isFiller(token) {
  const low = token.toLocaleLowerCase('tr');
  return FILLER.has(low) || FILLER_STEMS.some((stem) => low.startsWith(stem));
}

function meaningful(tokens) {
  return tokens.filter((t) => !isFiller(t) && !BUS_RE.test(t) && !METRO_RE.test(t));
}

/* "Kadıköy'den Taksim'e nasıl giderim": the ablative (-dan/-den/-tan/-ten, after an optional
 * buffer n as in "Meydanı'ndan") marks the origin and the dative (-a/-e/-ya/-ye) the
 * destination. Only this one shape is read; anything else asks the user to phrase it so,
 * because guessing which word is which end would be a guessed answer. */
const JOURNEY_RE = /^(.+?)[’']?n?(?:dan|den|tan|ten)\s+(.+?)[’']?n?(?:ya|ye|a|e)?\s+(?:nasıl|nasil)\s+gid/i;

function splitJourney(text) {
  const match = JOURNEY_RE.exec((text || '').trim());
  return match ? { from: match[1].trim(), to: match[2].trim() } : null;
}

/** Map free text onto one journey. Keyword matching, not a model — and the UI says so. */
function route(text) {
  const tokens = tokenize(text);
  if (!tokens.length) return null;
  const low = tokens.map((t) => t.toLocaleLowerCase('tr')).join(' ');
  const metro = tokens.find((t) => METRO_RE.test(t));
  const bus = tokens.find((t) => BUS_RE.test(t) && !METRO_RE.test(t));
  const rest = meaningful(tokens).join(' ');

  if (/tazeli|veri yaş|güncellik/.test(low)) return { journey: 'freshness', args: {} };
  // Explicit wording only: an over-eager "from X to Y" pattern would steal ordinary
  // questions, and the route endpoint may not even exist on this server.
  if (/nas[ıi]l gid(?:erim|ilir|ebilirim)|güzergâh|güzergah|rota öner|rota onar/.test(low)) {
    return { journey: 'route', args: { q: text.trim(), ...(splitJourney(text) || {}) } };
  }
  if (/trafik|yoğunluk/.test(low)) return { journey: 'traffic', args: {} };
  if (/istasyon|asansör|engelli|bebek odası|yürüyen/.test(low) && rest) return { journey: 'station', args: { name: rest } };
  if (metro) return { journey: 'metro', args: { line: metro.toLocaleUpperCase('tr') } };
  // "hava" must not swallow "havalimanı"/"havaalanı": the airport is a place someone asks
  // about parking at, not a question about the air, and İstanbul has two of them.
  if (/hava(?!limanı|alanı|liman|alan)|kirlilik|aqi|pm10|koşu|nefes/.test(low)) return { journey: 'air', args: { place: rest || text } };
  if (/otopark|park/.test(low)) return { journey: 'parking', args: { place: rest || text } };
  if (bus) {
    return rest
      ? { journey: 'arrivals', args: { line: bus.toLocaleUpperCase('tr'), stop: rest } }
      : { journey: 'bus', args: { line: bus.toLocaleUpperCase('tr') } };
  }
  // "durağı"/"durağa"/"durağında": Turkish softens the final k to ğ before a vowel, and
  // "X durağı" is how the question is actually asked. Matching only "durak" sent it to the
  // place gazetteer, which does not hold bus stops, so the honest answer never appeared.
  if (/dura[kğ]/.test(low)) return { journey: 'stops', args: { q: rest || text } };
  return { journey: 'places', args: { q: text.trim() } };
}

export { route };
