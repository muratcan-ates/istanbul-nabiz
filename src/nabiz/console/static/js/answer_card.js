import { quoteBox } from './transcript.js';
import { esc, has } from './format.js';
import { currentLang, t } from './i18n_text.js';
import { citationMarkup, citationText, kindTag, isStale, institutionLabel as citationInstitutionLabel, dayDate, STALE_DAYS, freshnessMode } from './citation_card.js';
import { icon } from './icons.js';
import { AUTHOR_TR, howPanel, sourceLink } from './provenance.js';

const REFUSAL_TEXT = "Bu soru hak, ücret, ceza ya da sağlıkla ilgili. Bu konularda cevap üretmiyorum: yanlış bir bilgi sana para, hak ya da sağlık kaybettirebilir. Doğru bilgi için 153 Çözüm Merkezi'ni ara ya da ilgili kurumun resmî sayfasına bak.";
// A page's line-end hyphenation ("ha- vada") is joined for display only; the stored quote stays as captured.
export const unwrapHyphens = (text) => String(text ?? '').replace(/(\p{L})- (\p{Ll})/gu, '$1$2');
const UNKNOWN_TEXT = "Bu konuda doğrulayabildiğim güncel bir İBB kaynağı bulamadım. Tahmin yürütmek istemiyorum. 153'e bağlanabilir veya ilgili resmî sayfaya gidebilirsin.";
const INSTITUTIONS = Object.freeze({
  IBB: 'İBB',
  IBB_OPEN_DATA: 'İBB Açık Veri Portalı',
  IETT: 'İETT',
  IGDAS: 'İGDAŞ',
  ISKI: 'İSKİ',
  ISPARK: 'İSPARK',
  METRO_ISTANBUL: 'Metro İstanbul',
  SEHIR_HATLARI: 'Şehir Hatları',
});

function institutionLabel(code, url) { return citationInstitutionLabel(code, url, INSTITUTIONS); }

const beatenPayloads = new WeakSet();
let citationSequence = 0;

function sourceLine(citation, { inQuoteBox = false } = {}) {
  if (!citation || typeof citation !== 'object') return '<p class="ac-source-line">Kurum belirtilmemiş</p>';
  if (citation.source === 'local:knowledge') {
    const institution = esc(institutionLabel(citation.institution, citation.url));
    const updated = dayDate(citation.source_updated_at);
    if (inQuoteBox) {
      return `<p class="ac-source-line">${institution}${updated ? ` · son güncelleme: ${esc(updated)}` : ''}</p>`;
    }
    const title = citation.title || 'Kaynak sayfası';
    const href = citation.url && /^https:\/\//i.test(citation.url) ? citation.url : null;
    const titleText = href
      ? `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${esc(title)}</a>`
      : esc(title);
    const fetched = dayDate(citation.fetched_at);
    const parts = [institution, titleText];
    if (fetched) parts.push(`alındı: ${esc(fetched)}`);
    if (updated) parts.push(`son güncelleme: ${esc(updated)}`);
    return `<p class="ac-source-line">${parts.join(' · ')}</p>`;
  }
  return `<p class="ac-source-line">${sourceLink(citation)}</p>`;
}

function actionRow(citations) {
  const page = citations.find((item) => item.source === 'local:knowledge'
    && typeof item.url === 'string' && /^https:\/\//i.test(item.url));
  const official = page
    ? `<a class="btn btn-quiet ac-official" href="${esc(page.url)}" target="_blank" rel="noopener noreferrer">Resmî kaynağı aç${icon('external-link')}</a>`
    : '';
  return `<div class="btn-row ac-actions">${official}<button type="button" class="btn btn-quiet ac-copy" data-ac-copy>Kopyala</button>`
    + '<a class="btn btn-quiet ac-call153" href="tel:153">153\'e sor</a></div>';
}

function fixedCard(mode, how, turnId) {
  const text = mode === 'unknown' ? UNKNOWN_TEXT : REFUSAL_TEXT;
  return `<section class="answer-card is-unknown" data-card="${mode}" aria-label="Doğrulanmış kaynak bulunamadı">`
    + `<p class="ac-fixed" data-er-skip>${esc(text)}</p>`
    + '<div class="btn-row ac-actions"><a class="btn btn-primary ac-call153" href="tel:153">153\'e sor</a></div>'
    + `</section><p class="chat-foot"><span>cevabı yazan: <b>kural</b></span></p>${howPanel(how, turnId || mode)}`;
}

function sentenceMarkup(answer, map, citations, answerId, lang) {
  if (!map || !Array.isArray(map.sentences) || !map.sentences.length) return `<p data-er-target>${esc(answer)}</p>`;
  const sentences = map.sentences.filter((sentence) => sentence && typeof sentence.text === 'string');
  if (!sentences.length) return `<p data-er-target>${esc(answer)}</p>`;
  const rows = sentences.map((sentence) => {
    const index = sentence.status === 'supported' ? sentence.support?.[0]?.citation : null;
    let suffix = '';
    if (Number.isSafeInteger(index) && index >= 0 && index < citations.length) {
      suffix = ` <a class="ac-sentence-source" href="#ac-cite-${answerId}-${index + 1}" aria-label="${esc(citationText('source', lang, { number: index + 1 }))}">[${index + 1}]</a>`;
    } else if (sentence.status === 'no_source') {
      suffix = ` <span class="ac-no-source">${esc(map.labels?.no_source || citationText('no_source', lang))}</span>`;
    }
    return `<p data-er-target>${esc(sentence.text)}${suffix}</p>`;
  });
  if (Array.isArray(map.conflicts) && map.conflicts.length) {
    rows.push(`<p class="ac-conflict ac-stale">${esc(map.labels?.conflict || citationText('conflict', lang))}</p>`);
  }
  return rows.join('');
}

// Only recognised presentation metadata moves; the full answer stays available in Details.
function answerPresentation(answer, payload, citations, { preserveMap = true } = {}) {
  const original = { text: answer, raw: '' };
  if (typeof answer !== 'string' || preserveMap && payload.how?.citation_map) return original;
  const tools = Array.isArray(payload.how?.tools) ? payload.how.tools : [payload.how];
  const places = citations.some((item) => item.source === 'gazetteer')
    || tools.some((tool) => (tool?.name || tool?.tool) === 'places_resolve');
  const lines = answer.split('\n').map((line) => {
    if (!places) return line;
    const point = line.match(/^(\s*•\s+.+?)(?:\s+\u2014\s+|,\s+)([+-]?\d{1,3}[.,]\d{3,8}),\s+([+-]?\d{1,3}[.,]\d{3,8})\s*$/);
    if (!point || Math.abs(Number(point[2].replace(',', '.'))) > 90
      || Math.abs(Number(point[3].replace(',', '.'))) > 180) return line;
    return point[1];
  });
  let end = lines.length;
  while (end && !lines[end - 1].trim()) end--;
  if (lines[end - 1] === 'Kaynak: İBB Açık Veri (CC BY 4.0) · resmî bir servis değildir.') {
    lines.splice(end - 1, 1); end--;
    if (/^Veri: kayıtlı · (?:0[1-9]|[12]\d|3[01])\.(?:0[1-9]|1[0-2]) (?:[01]\d|2[0-3]):[0-5]\d\.$/.test(lines[end - 1] || '')) {
      lines.splice(end - 1, 1);
    }
  }
  const text = lines.join('\n');
  return text.trim() && text !== answer ? { text, raw: answer } : original;
}

function renderCitizenAnswerCard(data, { now = Date.now(), lang = currentLang() } = {}) {
  const payload = data && typeof data === 'object' ? data : {};
  const mode = payload.mode || (payload.refused ? 'refused' : 'answer');
  if (payload.emergency === true || !['answer', 'quote_only', 'refused', 'unknown'].includes(mode)) return '';
  const citations = Array.isArray(payload.citations) ? payload.citations.filter(Boolean) : [];
  const quotes = citations.filter((item) => typeof item.quote === 'string' && item.quote.trim());
  const steps = mode === 'answer' && Array.isArray(payload.steps)
    ? payload.steps.filter((step) => typeof step === 'string' && step.trim()) : [];
  const map = payload.how?.citation_map;
  const sentences = Array.isArray(map?.sentences)
    ? map.sentences.filter((sentence) => typeof sentence?.text === 'string' && sentence.text.trim()) : [];
  const answer = payload.answer_text ?? payload.answer ?? '';
  const showAnswer = mode === 'answer' && (String(answer).trim() || sentences.length)
    && (!quotes.length || payload.author !== 'kural');
  const refused = mode === 'refused' || mode === 'quote_only' && !quotes.length;
  const unknown = mode === 'unknown' || !refused && !showAnswer && !quotes.length && !steps.length;
  const label = (key, tr, en) => {
    const fallback = lang === 'en' ? en : tr;
    return lang === currentLang() ? t(key, fallback) : fallback;
  };
  const clean = (text) => answerPresentation(text, payload, citations, { preserveMap: false }).text;
  let primary = '';
  if (refused || unknown) {
    const text = refused ? REFUSAL_TEXT : lang === 'en' ? 'I could not verify this information.' : 'Bu bilgiyi doğrulayamadım.';
    primary = `<p class="ac-fixed" data-er-skip>${esc(text)}</p>`;
  } else if (showAnswer) {
    primary = sentences.length ? sentences.map((sentence) => `<p data-er-target>${esc(clean(sentence.text))}`
      + (sentence.status === 'no_source' ? ` <span class="ac-no-source">${esc(map.labels?.no_source || citationText('no_source', lang))}</span>` : '')
      + '</p>').join('') : `<p data-er-target>${esc(clean(answer))}</p>`;
  } else if (quotes.length) {
    primary = quotes.map((item) => `<blockquote class="quote-text quote-exact" data-er-skip>${esc(unwrapHyphens(item.quote))}</blockquote>`).join('');
  }
  if (!refused && !unknown && steps.length) {
    primary += `<ol class="ac-steps-list">${steps.map((step) => `<li data-er-target>${esc(step)}</li>`).join('')}</ol>`;
  }
  let warnings = '';
  if (!refused && !unknown && citations.some((item) => isStale(item, now))) {
    warnings += `<p class="ac-stale">${esc(citationText('stale', lang))}</p>`;
  }
  if (!refused && !unknown && Array.isArray(map?.conflicts) && map.conflicts.length) {
    warnings += `<p class="ac-conflict ac-stale">${esc(map.labels?.conflict || citationText('conflict', lang))}</p>`;
  }
  // An empty hidden completion marker preserves the existing feedback attachment contract.
  const call = refused || unknown ? `<a class="btn btn-quiet ac-call153" href="tel:153">${lang === 'en' ? 'Ask 153' : "153'e sor"}</a>` : '';
  return `<section class="answer-card${refused || unknown ? ' is-unknown' : ''}" data-citizen-answer="true" data-card="${refused ? 'refused' : unknown ? 'unknown' : mode === 'quote_only' ? 'quote' : 'answer'}">`
    + `<section class="answer-short ac-short">${primary}</section>${warnings}`
    + `<div class="btn-row ac-actions">${call}<button type="button" class="btn btn-quiet ac-copy" data-citizen-copy>${esc(label('dyn.copy', 'Kopyala', 'Copy'))}</button></div>`
    + `<details class="ac-details"><summary>${esc(label('ui.shell.more', 'Daha fazla', 'More'))}</summary><div class="ac-details-content"></div></details><span class="chat-foot" hidden aria-hidden="true"></span></section>`;
}

function renderAnswerCard(data, { turnId = '', now = Date.now(), lang = currentLang(), surface } = {}) {
  if (surface === 'citizen' || surface === undefined && typeof document !== 'undefined'
    && document.body?.classList?.contains('citizen-page')) return renderCitizenAnswerCard(data, { now, lang });
  const payload = data && typeof data === 'object' ? data : {};
  const mode = payload.mode || (payload.refused ? 'refused' : 'answer');
  if (payload.emergency === true) return '';
  if (!['answer', 'quote_only', 'refused', 'unknown'].includes(mode)) return '';
  if (mode === 'refused' || mode === 'unknown') return fixedCard(mode, payload.how, turnId);

  const citations = Array.isArray(payload.citations) ? payload.citations.filter(Boolean) : [];
  const answerId = ++citationSequence;
  const quoted = citations.flatMap((item, index) => typeof item.quote === 'string' && item.quote.trim()
    ? [{ ...item, quote_anchor: `ac-quote-${answerId}-${index + 1}`, citation_anchor: `ac-cite-${answerId}-${index + 1}`,
      citation_label: citationText('quote_source', lang) }] : []);
  if (mode === 'quote_only' && quoted.length === 0) return fixedCard('refused', payload.how, turnId);

  const answer = payload.answer_text ?? payload.answer ?? '';
  const map = payload.how?.citation_map;
  const hasAnswer = String(answer).trim() || (Array.isArray(map?.sentences)
    && map.sentences.some((sentence) => typeof sentence?.text === 'string' && sentence.text.trim()));
  const showShort = mode === 'answer' && hasAnswer && (quoted.length === 0 || payload.author !== 'kural');
  const presentation = showShort ? answerPresentation(answer, payload, citations) : { text: answer, raw: '' };
  const steps = mode === 'answer' && Array.isArray(payload.steps) ? payload.steps : [];
  if (!showShort && !quoted.length && !steps.length) return fixedCard('unknown', payload.how, turnId);
  const cardType = mode === 'quote_only' ? 'quote' : 'answer';
  const beatLive = !beatenPayloads.has(payload) && citations.some((item) => freshnessMode(item) === 'live');
  if (beatLive) beatenPayloads.add(payload);
  let html = `<section class="answer-card" data-card="${cardType}"${beatLive ? ' data-beaten="true"' : ''} aria-label="Kaynaklı cevap">`;
  const quotes = quoted.length ? `<div class="ac-quote" data-er-skip>${quoteBox(quoted)
    .replaceAll('class="quote-text"', 'class="quote-text quote-exact"')}</div>` : '';
  const stepList = steps.length ? '<section class="ac-steps"><h3 class="eyebrow">Nasıl yapılır</h3>'
    + `<ol class="ac-steps-list">${steps.map((step) => `<li>${esc(step)}</li>`).join('')}</ol></section>` : '';
  if (showShort) html += '<section class="answer-short ac-short"><h3 class="eyebrow">Kısa cevap</h3>'
    + `${sentenceMarkup(presentation.text, map, citations, answerId, lang)}</section>`;
  else html += `<div class="ac-primary-answer">${quotes || stepList}</div>`;
  if (citations.some((item) => isStale(item, now))) html += `<p class="ac-stale">${esc(citationText('stale', lang))}</p>`;
  if (!showShort && Array.isArray(map?.conflicts) && map.conflicts.length) {
    html += `<p class="ac-conflict ac-stale">${esc(map.labels?.conflict || citationText('conflict', lang))}</p>`;
  }
  const fallback = lang === 'en' ? 'Details' : 'Ayrıntılar';
  const label = lang === currentLang() ? t('ui.answer.details', fallback) : fallback;
  html += `<details class="ac-details"><summary>${esc(label)}</summary><div class="ac-details-content">`;
  if (presentation.raw) html += `<p class="ac-technical" data-er-skip>${esc(presentation.raw)}</p>`;
  if (showShort) html += quotes;
  if (showShort || quoted.length) html += stepList;
  html += '<section class="ac-sources"><h3 class="eyebrow">Kaynak</h3>';
  let beatUsed = false;
  if (citations.length) {
    const items = citations.map((item, index) => {
      const beat = beatLive && !beatUsed && freshnessMode(item) === 'live';
      if (beat) beatUsed = true;
      const quoteTarget = quoted.find((quote) => quote.citation_anchor === `ac-cite-${answerId}-${index + 1}`)?.quote_anchor;
      return `<li class="ac-source">${citationMarkup(item, { index, now, lang, beat, answerId, quoteTarget, institutions: INSTITUTIONS })}</li>`;
    });
    html += `<ul class="ac-source-list">${items.join('')}</ul>`;
  } else html += '<p>Kaynak yok.</p>';
  html += `</section>${actionRow(citations)}`;
  const author = AUTHOR_TR[payload.author] || payload.author || 'bilinmiyor';
  html += `<p class="chat-foot"><span>cevabı yazan: <b>${esc(author)}</b></span></p>`;
  html += howPanel(payload.how, turnId || 'answer').replace('<details', '<section class="ac-how"')
    .replace('<summary>', '<h3 class="eyebrow">').replace('</summary>', '</h3>').replace('</details>', '</section>');
  html += `</div></details></section><div class="feedback-slot" data-turn-id="${esc(turnId)}"></div>`;
  return html;
}

function ensureStyle() {
  const head = document.head;
  if (!head || head.querySelector('link[href="/css/answer_card.css"]')) return;
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = '/css/answer_card.css';
  head.appendChild(link);
}

if (typeof document !== 'undefined') ensureStyle();

export {
  renderAnswerCard, renderCitizenAnswerCard, sourceLine, kindTag, isStale, institutionLabel, dayDate,
  REFUSAL_TEXT, UNKNOWN_TEXT, STALE_DAYS,
};
