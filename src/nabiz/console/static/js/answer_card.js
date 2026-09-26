import { quoteBox } from './transcript.js';
import { esc, has, int, num, shortAge } from './format.js';
import { AUTHOR_TR, ageText, howPanel, modeOf, sourceLabel, sourceLink } from './provenance.js';

const REFUSAL_TEXT = "Bu soru hak, ücret, ceza ya da sağlıkla ilgili. Bu konularda cevap üretmiyorum: yanlış bir bilgi sana para, hak ya da sağlık kaybettirebilir. Doğru bilgi için 153 Çözüm Merkezi'ni ara ya da ilgili kurumun resmî sayfasına bak. Acil bir durumdaysan 112'yi ara.";
const UNKNOWN_TEXT = "Bu konuda doğrulayabildiğim güncel bir İBB kaynağı bulamadım. Tahmin yürütmek istemiyorum. 153'e bağlanabilir veya ilgili resmî sayfaya gidebilirsin.";
const STALE_DAYS = 365;
const DAY_MS = 24 * 60 * 60 * 1000;
const INSTITUTIONS = {
  IBB: 'İBB',
  IBB_OPEN_DATA: 'İBB Açık Veri Portalı',
  IETT: 'İETT',
  IGDAS: 'İGDAŞ',
  ISKI: 'İSKİ',
  ISPARK: 'İSPARK',
  METRO_ISTANBUL: 'Metro İstanbul',
  SEHIR_HATLARI: 'Şehir Hatları',
};

function institutionLabel(code, url) {
  if (has(code) && code !== 'DIGER') return INSTITUTIONS[code] || String(code);
  try {
    return new URL(url).hostname || 'Kurum belirtilmemiş';
  } catch {
    return 'Kurum belirtilmemiş';
  }
}

function dayDate(iso) {
  const timestamp = Date.parse(iso || '');
  if (!Number.isFinite(timestamp)) return null;
  try {
    return new Intl.DateTimeFormat('tr-TR', {
      timeZone: 'Europe/Istanbul', day: '2-digit', month: '2-digit', year: 'numeric',
    }).format(timestamp);
  } catch {
    return null;
  }
}

function sourceLine(citation, { inQuoteBox = false } = {}) {
  if (!citation || typeof citation !== 'object') return '<p class="ac-source-line">Kurum belirtilmemiş</p>';
  if (citation.source === 'local:knowledge') {
    const institution = esc(institutionLabel(citation.institution, citation.url));
    const updated = dayDate(citation.source_updated_at);
    if (inQuoteBox) {
      return `<p class="ac-source-line">${institution}${updated ? ` · son güncelleme: ${esc(updated)}` : ''}</p>`;
    }
    const title = citation.title || 'Kaynak sayfası';
    const href = citation.url && /^https?:\/\//i.test(citation.url) ? citation.url : null;
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

function kindTag(citation) {
  if (citation && citation.source === 'local:knowledge') {
    return '<span class="ac-kind is-page">Resmî sayfadan alıntı</span>';
  }
  const mode = modeOf(citation);
  let label = 'Veri yaşı bilinmiyor';
  if (mode === 'live') label = `Canlı veri · ${shortAge(citation.age_s)}`;
  if (mode === 'old') label = `Ölçüm · ${ageText(citation)}`;
  if (mode === 'recorded') label = `Kayıtlı veri · ${ageText(citation)}`;
  if (mode === 'schedule') label = 'Tarifeye göre';
  return `<span class="ac-kind is-${mode}">${esc(label)}</span>`;
}

function isStale(citation, now = Date.now()) {
  if (!citation || citation.source !== 'local:knowledge') return false;
  const updated = Date.parse(citation.source_updated_at || '');
  const current = now instanceof Date ? now.getTime() : Number(now);
  return Number.isFinite(updated) && Number.isFinite(current) && current - updated > STALE_DAYS * DAY_MS;
}

function staleNotice(citation, now) {
  return isStale(citation, now)
    ? '<p class="ac-stale callout callout-warn">Eski olabilir, 153 ile teyit edin</p>'
    : '';
}

function sourceItem(citation, now) {
  return `<li class="ac-source">${sourceLine(citation, { inQuoteBox: Boolean(citation.quote) })}`
    + `${kindTag(citation)}${staleNotice(citation, now)}</li>`;
}

function actionRow(citations) {
  const page = citations.find((item) => item.source === 'local:knowledge'
    && typeof item.url === 'string' && /^https?:\/\//i.test(item.url));
  const official = page
    ? `<a class="btn ac-official" href="${esc(page.url)}" target="_blank" rel="noopener noreferrer">Resmî kaynağı aç</a>`
    : '';
  return `<div class="btn-row ac-actions">${official}<a class="btn btn-primary ac-call153" href="tel:153">153'e sor</a></div>`;
}

function fixedCard(mode) {
  const text = mode === 'unknown' ? UNKNOWN_TEXT : REFUSAL_TEXT;
  return `<section class="answer-card is-unknown" data-card="${mode}" aria-label="Doğrulanmış kaynak bulunamadı">`
    + `<p class="ac-fixed" data-er-skip>${esc(text)}</p>`
    + '<div class="btn-row ac-actions"><a class="btn btn-primary ac-call153" href="tel:153">153\'e sor</a></div>'
    + '</section><p class="chat-foot"><span>cevabı yazan: <b>kural</b></span></p>';
}

function renderAnswerCard(data, { turnId = '', now = Date.now() } = {}) {
  const payload = data && typeof data === 'object' ? data : {};
  const mode = payload.mode || (payload.refused ? 'refused' : 'answer');
  if (mode === 'redirect' && payload.emergency === true) return '';
  if (!['answer', 'quote_only', 'refused', 'unknown'].includes(mode)) return '';
  if (mode === 'refused' || mode === 'unknown') return fixedCard(mode);

  const citations = Array.isArray(payload.citations) ? payload.citations.filter(Boolean) : [];
  const quoted = citations.filter((item) => typeof item.quote === 'string' && item.quote.trim());
  if (mode === 'quote_only' && quoted.length === 0) return fixedCard('refused');

  const answer = payload.answer_text ?? payload.answer ?? '';
  const showShort = mode === 'answer' && (quoted.length === 0 || payload.author !== 'kural');
  const steps = mode === 'answer' && Array.isArray(payload.steps) ? payload.steps : [];
  const cardType = mode === 'quote_only' ? 'quote' : 'answer';
  let html = `<section class="answer-card" data-card="${cardType}" aria-label="Kaynaklı cevap">`;
  if (showShort) {
    html += `<section class="answer-short ac-short"><h3>KISA CEVAP</h3><p data-er-target>${esc(answer)}</p></section>`;
  }
  if (quoted.length) {
    const box = quoteBox(quoted).replaceAll('class="quote-text"', 'class="quote-text quote-exact"');
    html += `<div class="ac-quote" data-er-skip>${box}</div>`;
  }
  if (steps.length) {
    html += `<section class="ac-steps"><h3>NASIL YAPILIR</h3><ol>${steps.map((step) => `<li>${esc(step)}</li>`).join('')}</ol></section>`;
  }
  html += '<section class="ac-sources"><h3>KAYNAK</h3>';
  html += citations.length
    ? `<ul class="ac-source-list">${citations.map((item) => sourceItem(item, now)).join('')}</ul>`
    : '<p>Kaynak yok.</p>';
  html += `</section>${actionRow(citations)}</section>`;

  const first = citations[0];
  const author = AUTHOR_TR[payload.author] || payload.author || 'bilinmiyor';
  const source = first ? sourceLabel(first.institution || first.source) : 'kaynak yok';
  const age = first ? ageText(first) : 'veri yaşı bilinmiyor';
  const how = payload.how;
  const calls = how && Number.isFinite(Number(how.tool_calls)) ? int(how.tool_calls) : '0';
  const elapsed = how && has(how.elapsed_s) ? num(how.elapsed_s, 1) : 'bilinmiyor';
  html += `<p class="chat-foot"><span>${esc(source)} · ${esc(age)} · cevabı yazan: <b>${esc(AUTHOR_TR[payload.author] || author)}</b>`
    + ` · ${esc(calls)} araç çağrısı · ${esc(elapsed)} sn</span></p>`;
  html += howPanel(how, turnId || 'answer');
  html += `<div class="feedback-slot" data-turn-id="${esc(turnId)}"></div>`;
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
  renderAnswerCard, sourceLine, kindTag, isStale, institutionLabel, dayDate,
  REFUSAL_TEXT, UNKNOWN_TEXT, STALE_DAYS,
};
