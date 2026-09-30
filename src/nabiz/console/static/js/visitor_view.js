/* Source-pinned visitor answers. This module builds markup only and never touches the page or network. */

import { currentLang, t } from './i18n_text.js';
import { esc } from './format.js';
import { icon } from './icons.js';
import { CARD_TEXT, REVIEWED_LANGS, RTL_LANGS, TR_BLOCK, UNVERIFIED_LABEL } from './emergency_text.js';

export const QUESTION_KEYS = Object.freeze({
  museums: ['ui.visitor.q_museums', t('ui.visitor.q_museums', 'Hangi müzeler şu an açık?')],
  airport: ['ui.visitor.q_airport', t('ui.visitor.q_airport', 'Havalimanlarına hangi şehir otobüsleri gider?')],
  emergency: ['ui.visitor.q_emergency', t('ui.visitor.q_emergency', 'Acil bir durumda')],
  istanbulkart: ['ui.visitor.q_istanbulkart', t('ui.visitor.q_istanbulkart', "İstanbulkart'ı nereden alırım?")],
  step_free: ['ui.visitor.q_step_free', t('ui.visitor.q_step_free', 'Metro, tramvay ve vapurda basamaksız erişim')],
});

const QUESTION_KINDS = Object.freeze({ museums: 'museums', airport: 'knowledge', emergency: 'emergency', istanbulkart: 'knowledge', step_free: 'knowledge' });
const LANGUAGES = Object.freeze(['tr', 'en', 'ar', 'ru', 'de', 'fa', 'es', 'fr', 'it', 'uk']);
export const FALLBACK = Object.freeze({ questions: Object.freeze([{ id: 'emergency', kind: 'emergency' }]) });

function visitorDayName(index) {
  const names = [
    t('ui.culture.day0', 'Pazartesi'), t('ui.culture.day1', 'Salı'), t('ui.culture.day2', 'Çarşamba'),
    t('ui.culture.day3', 'Perşembe'), t('ui.culture.day4', 'Cuma'), t('ui.culture.day5', 'Cumartesi'),
    t('ui.culture.day6', 'Pazar'),
  ];
  return names[index] || '';
}

function visitorClock(value) {
  return currentLang() === 'en' ? String(value || '').replace('.', ':') : String(value || '');
}

function visitorDate(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value || '');
  return match ? `${match[3]}.${match[2]}.${match[1]}` : t('ui.culture.no_date', 'bilinmiyor');
}

function visitorLink(url) {
  if (typeof url !== 'string' || !url.startsWith('https://')) return '';
  try { return new URL(url).protocol === 'https:' ? url : ''; } catch { return ''; }
}

function questionAnswer(question) {
  if (!question || question.kind !== QUESTION_KINDS[question.id]) return '';
  if (question.kind === 'museums') return museumsMarkup(question);
  if (question.kind === 'emergency') return emergencyMarkup(currentLang());
  return knowledgeMarkup(question);
}

export function sectionMarkup(payload) {
  const questions = Array.isArray(payload && payload.questions) ? payload.questions : [];
  const rows = questions.map((question) => {
    const key = QUESTION_KEYS[question && question.id];
    const answer = questionAnswer(question);
    if (!key || !answer) return '';
    return `<details class="visitor-q" name="ziyaretci-soru" data-visitor="${esc(question.id)}"><summary>${icon('chevron-right')}<span>${esc(t(key[0], key[1]))}</span></summary><div class="visitor-a">${answer}</div></details>`;
  }).join('');
  return `<section id="ziyaretci" class="visitor" aria-labelledby="visitor-title" lang="${esc(currentLang())}">
    <h2 id="visitor-title">${esc(t('ui.visitor.title', "İstanbul'u ziyaret mi ediyorsunuz?"))}</h2>
    <p class="section-note">${esc(t('ui.visitor.note', 'İBB kayıtlarından ve resmî sayfalardan kısa cevaplar. Adlar ve adresler Türkçe kalır.'))}</p>
    <div class="visitor-list">${rows}</div>
    <p class="visitor-foot">${esc(t('ui.culture.disclaimer', 'Resmî İBB hizmeti değildir.'))}</p>
  </section>`;
}

export function museumsMarkup(question) {
  const districts = Array.isArray(question && question.districts) ? question.districts : [];
  const options = districts.map((district) => `<option value="${esc(district.name)}" lang="tr">${esc(district.name)} (${esc(district.count)})</option>`).join('');
  return `<div class="visitor-museums">
    <label for="visitor-district">${esc(t('ui.culture.district', 'İlçe'))}</label>
    <p class="field-hint" id="visitor-district-hint">${esc(t('ui.visitor.district_hint', 'Parantez içinde: kayıttaki müze ve galeri sayısı.'))}</p>
    <select id="visitor-district" aria-describedby="visitor-district-hint"><option value="">${esc(t('ui.culture.pick', 'İlçe seçin'))}</option>${options}</select>
    <p class="status-line" role="status" aria-live="polite"></p>
    <ol class="visitor-venues" hidden></ol>
    <div class="visitor-museum-notes">
      <p>${esc(t('ui.visitor.museums_scope', "Yalnız İBB açık veri kaydındaki müze ve galeriler listelenir; başka müzeler bu kayıtta yok."))}</p>
      <p>${esc(t('ui.visitor.museums_access', 'Kayıtta erişilebilirlik bilgisi yok; gitmeden önce müzeyi arayın.'))}</p>
      <p>${esc(t('ui.culture.note_occupancy', 'Doluluk bilgisi yok: İBB kütüphane ve müze doluluğunu açık veri olarak yayımlamıyor.'))}</p>
      <p>${esc(t('ui.culture.note_holidays', 'Resmî tatil ve özel kapanışlar kayıtta yok; gitmeden önce arayın.'))}</p>
    </div>
  </div>`;
}

export function museumLine(venue) {
  if (venue.state === 'open' && venue.closes_at) {
    return t('ui.culture.open_until', 'Kayda göre şu an açık · kapanış {time}', { time: visitorClock(venue.closes_at) });
  }
  if (venue.state === 'open') return t('ui.culture.open_always', 'Kayda göre 7/24 açık');
  const next = venue.state === 'closed' ? venue.opens_on : null;
  if (next && next.today) {
    return t('ui.culture.closed_today', 'Kayda göre şu an kapalı · açılış bugün {time}', { time: visitorClock(next.time) });
  }
  if (next) {
    return t('ui.culture.closed_until', 'Kayda göre şu an kapalı · açılış {day} {time}', {
      day: visitorDayName(next.weekday), time: visitorClock(next.time),
    });
  }
  return t('ui.culture.no_hours', 'Çalışma saati kayıtta yok');
}

export function venuesMarkup(data) {
  const venues = Array.isArray(data && data.venues) ? data.venues : [];
  const rows = venues.map((venue) => {
    const phones = (venue.phones || []).map((phone) => {
      const dial = String(phone || '').replace(/dahili.*/i, '').replace(/[^\d+]/g, '');
      return dial ? `<a href="tel:${esc(dial)}">${esc(phone)}</a>` : `<span>${esc(phone)}</span>`;
    }).join(' · ');
    const address = venue.address ? `<p class="visitor-address" lang="tr">${esc(venue.address)}</p>` : '';
    return `<li class="visitor-venue" lang="tr"><h3>${esc(venue.name)}</h3>
      <p class="visitor-venue-state" lang="${esc(currentLang())}">${esc(museumLine(venue))}</p>${address}
      ${phones ? `<p class="visitor-phones">${phones}</p>` : ''}</li>`;
  }).join('');
  const provenance = (data && data.provenance_by_kind && data.provenance_by_kind.museum) || {};
  const source = t('ui.culture.source', 'İBB Açık Veri Portalı · kayıt tarihi {recorded} · indirildi {captured} · İBB Açık Veri Lisansı', {
    recorded: visitorDate(provenance.observed_at), captured: visitorDate(provenance.captured_at),
  });
  return `${rows}<li class="visitor-record-source" lang="${esc(currentLang())}">${esc(source)}</li>`;
}

export function knowledgeMarkup(question) {
  const sources = Array.isArray(question && question.sources) ? question.sources : [];
  return sources.map((source) => {
    const url = visitorLink(source.url);
    const quotes = Array.isArray(source.quotes) ? source.quotes : [];
    const translated = quotes.filter((quote) => typeof quote.en === 'string' && quote.en.trim());
    const originalOnly = quotes.filter((quote) => quote.en === null || quote.en === undefined);
    const translatedMarkup = translated.map((quote) => `<figure class="visitor-quote">
      <p class="visitor-en" lang="en">${esc(quote.en)}</p>
      <figcaption class="field-hint">${esc(t('ui.visitor.translation', "Çeviri Nabız'ındır; {source} yapmadı.", { source: source.name }))}</figcaption>
      <details class="visitor-original"><summary>${icon('chevron-right')}<span>${esc(t('ui.visitor.original', 'Özgün metin (Türkçe)'))}</span></summary>
        <blockquote lang="tr" cite="${esc(url)}">${esc(quote.tr)}</blockquote></details>
    </figure>`).join('');
    const originalMarkup = originalOnly.length ? `<p class="visitor-airport-label">${esc(t('ui.visitor.airport_lines', "İETT'nin sayfasında yazdığı gibi havalimanı hatları:"))}</p>
      <ul class="visitor-names" lang="tr">${originalOnly.map((quote) => `<li>${esc(quote.tr)}</li>`).join('')}</ul>` : '';
    const pageDate = source.page_date ? `<p class="visitor-page-date"><span lang="en">${esc(source.page_date.en)}</span> <span lang="tr">(${esc(source.page_date.tr)})</span></p>` : '';
    const date = visitorDate(source.fetched_at);
    const sourceToken = '__VISITOR_SOURCE__';
    const sourceLine = t('ui.visitor.source_line', 'Kaynak: {source} · {host} · indirildi {date}', {
      source: sourceToken, host: source.host, date,
    });
    const sourceIndex = sourceLine.indexOf(sourceToken);
    const sourceMarkup = sourceIndex < 0 ? esc(sourceLine) : `${esc(sourceLine.slice(0, sourceIndex))}`
      + `<span lang="tr">${esc(source.name)}</span>${esc(sourceLine.slice(sourceIndex + sourceToken.length))}`;
    const link = url ? ` · <a href="${esc(url)}" rel="noopener">${esc(t('ui.visitor.open_page', 'Sayfayı aç'))}${icon('external-link')}</a>` : '';
    const airportNote = question.id === 'airport' ? `<p class="visitor-airport-note">${esc(t('ui.visitor.airport_note', "Başka işletmeler bu kaynakta yok. Yola çıkmadan önce saatleri İETT'nin sayfasında kontrol edin."))}</p>` : '';
    return `<div class="visitor-source-block">${translatedMarkup}${originalMarkup}${pageDate}
      <p class="visitor-source">${sourceMarkup}${link}</p>${airportNote}</div>`;
  }).join('');
}

export function languageName(code) {
  try {
    const name = new Intl.DisplayNames([code], { type: 'language' }).of(code);
    return name ? name.charAt(0).toLocaleUpperCase(code) + name.slice(1) : code.toUpperCase();
  } catch {
    return code.toUpperCase();
  }
}

export function cardPreview(code) {
  const card = CARD_TEXT[code];
  if (!card) return '';
  const direction = RTL_LANGS.includes(code) ? 'rtl' : 'ltr';
  const label = REVIEWED_LANGS.includes(code) ? '' : `<p class="field-hint" lang="tr" dir="ltr">${esc(UNVERIFIED_LABEL)}</p>`;
  return `<div lang="${esc(code)}" dir="${direction}"><p class="visitor-card-title">${esc(card.title)}</p>${label}<p>${esc(card.show)}</p></div>`;
}

export function emergencyMarkup(lang) {
  const card = CARD_TEXT[lang] || CARD_TEXT.en;
  const options = LANGUAGES.map((code) => `<option value="${code}" lang="${code}">${esc(languageName(code))}</option>`).join('');
  return `<div class="visitor-emergency">
    <p>${esc(card.live)}</p>
    <ul class="visitor-numbers"><li><a class="btn" href="tel:153">${esc(card.call)}</a></li></ul>
    <p>${esc(card.show)}</p><p class="visitor-plea" id="visitor-plea" lang="tr">${esc(TR_BLOCK.plea)}</p>
    <button type="button" class="btn btn-quiet" data-visitor="grow" aria-pressed="false" aria-controls="visitor-plea">${esc(card.grow)}</button>
    <label for="visitor-card-lang">${esc(t('ui.visitor.card_lang', 'Acil kartı başka bir dilde'))}</label>
    <select id="visitor-card-lang" aria-describedby="visitor-card-note"><option value="">${esc(t('ui.visitor.card_pick', 'Dil seçin'))}</option>${options}</select>
    <p class="field-hint" id="visitor-card-note">${esc(t('ui.visitor.card_note', 'Sohbete bu dillerden birinde acil bir durum yazarsanız asistan acil kartını o dilde açar.'))}</p>
    <div class="visitor-card-preview" aria-live="polite"></div>
  </div>`;
}
