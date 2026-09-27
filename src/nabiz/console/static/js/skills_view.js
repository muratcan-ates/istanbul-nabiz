/* Pure course-discovery markup and device-state helpers. No browser globals or side effects. */

import { currentLang, t } from './i18n_text.js';
import { esc } from './format.js';
import { icon } from './icons.js';

const STORAGE_KEY = 'nabiz.skills.v1';
const KEEP_DAYS = 30;
const MAX_AREAS = 3;
const MAX_SAVED = 5;
const DAY_MS = 86_400_000;
const EMPTY_CHOICES = Object.freeze({ branch: '', areas: [], keyword: '', district: '', mode: '', time: '' });
const STEP_KEYS = ['read_page', 'checked_travel', 'applied_myself'];

function emptyState() {
  return { version: 1, at: 0, choices: { ...EMPTY_CHOICES, areas: [] }, saved: [], checks: {} };
}

function parseStored(raw, now = Date.now()) {
  try {
    const value = JSON.parse(raw || 'null');
    if (!value || value.version !== 1 || !Number.isFinite(value.at) || now - value.at > KEEP_DAYS * DAY_MS || value.at > now) return null;
    const choices = value.choices;
    if (!choices || typeof choices !== 'object' || Array.isArray(choices)) return null;
    const saved = Array.isArray(value.saved) ? value.saved.filter((item) => (
      item && /^\d{1,12}$/.test(String(item.code || '')) && typeof item.name === 'string'
      && typeof item.url === 'string' && item.url.startsWith('https://enstitu.ibb.istanbul/')
    )).slice(0, MAX_SAVED) : [];
    const checks = value.checks && typeof value.checks === 'object' && !Array.isArray(value.checks) ? value.checks : {};
    const normalizedChecks = {};
    for (const item of saved) {
      const list = Array.isArray(checks[item.code]) ? checks[item.code].filter((id) => STEP_KEYS.includes(id)) : [];
      if (list.length) normalizedChecks[item.code] = [...new Set(list)];
    }
    const source = choices;
    return {
      version: 1,
      at: value.at,
      choices: {
        branch: typeof source.branch === 'string' ? source.branch : '',
        areas: Array.isArray(source.areas) ? source.areas.filter((name) => typeof name === 'string').slice(0, MAX_AREAS) : [],
        keyword: typeof source.keyword === 'string' ? source.keyword.slice(0, 40) : '',
        district: typeof source.district === 'string' ? source.district : '',
        mode: typeof source.mode === 'string' ? source.mode : '',
        time: typeof source.time === 'string' ? source.time : '',
      },
      saved,
      checks: normalizedChecks,
    };
  } catch (error) {
    return null;
  }
}

function toStored(consent, choices, saved, checks, now = Date.now()) {
  if (!consent) return null;
  return {
    version: 1,
    at: now,
    choices: {
      branch: choices.branch || '', areas: (choices.areas || []).slice(0, MAX_AREAS),
      keyword: String(choices.keyword || '').slice(0, 40), district: choices.district || '',
      mode: choices.mode || '', time: choices.time || '',
    },
    saved: (saved || []).slice(0, MAX_SAVED).map(({ code, name, url }) => ({ code, name, url })),
    checks: Object.fromEntries((saved || []).slice(0, MAX_SAVED).map(({ code }) => (
      [code, [...new Set((checks && checks[code] || []).filter((id) => STEP_KEYS.includes(id)))]]
    ))),
  };
}

function link(url, label, lang = currentLang()) {
  return `<a href="${esc(url)}" target="_blank" rel="noopener" lang="${lang}">${esc(label)} ${icon('external-link')}</a>`;
}

function sectionMarkup(options, state, status, result, checklists, failure) {
  const lang = currentLang();
  const retrievedAt = options && options.source && options.source.retrieved_at;
  const freshness = retrievedAt && Number.isFinite(Date.parse(retrievedAt))
    ? new Intl.DateTimeFormat(lang === 'en' ? 'en-GB' : 'tr-TR', { timeZone: 'Europe/Istanbul', dateStyle: 'short' })
      .format(Date.parse(retrievedAt))
    : '';
  const stamp = freshness
    ? t('ui.skills.freshness', 'İSMEK kataloğu · kayıtlı · alındı {date}', { date: freshness })
    : t('ui.skills.freshness_unknown', 'İSMEK kataloğunun kayıt tarihi okunamadı.');
  const form = options && options.available ? formMarkup(options, state.choices, state.consent) : '';
  const resultHtml = result ? resultMarkup(result, state.saved, checklists) : '';
  const official = options && options.source ? [
    { name: options.source.name, url: options.source.programs_url, lang: 'tr' },
    { name: options.jobs_status?.name || t('ui.skills.bio_name', 'Bölgesel İstihdam Ofisleri'), url: options.jobs_status?.url || 'https://bio.ibb.istanbul/', lang: 'tr' },
  ] : [
    { name: t('ui.skills.ismek_name', 'Enstitü İstanbul İSMEK'), url: 'https://enstitu.ibb.istanbul/', lang: currentLang() },
    { name: t('ui.skills.bio_name', 'Bölgesel İstihdam Ofisleri'), url: 'https://bio.ibb.istanbul/', lang: currentLang() },
  ];
  const unavailable = failure || (options && !options.available)
    ? `<div class="skills-unavailable"><ul>${official.map((item) => `<li>${link(item.url, item.name, item.lang)}</li>`).join('')}</ul></div>` : '';
  const defaultJobs = options && options.jobs_status ? {
    card: options.jobs_status, search_terms: [], label: t('ui.skills.nabiz_suggests', 'Nabız önerisi; ilan değildir'),
  } : { card: { name: t('ui.skills.bio_name', 'Bölgesel İstihdam Ofisleri'), title: t('ui.skills.bio_name', 'Bölgesel İstihdam Ofisleri'), url: 'https://bio.ibb.istanbul/', reason: '' }, search_terms: [], label: t('ui.skills.nabiz_suggests', 'Nabız önerisi; ilan değildir') };
  const bio = result && result.jobs ? jobsMarkup(result.jobs) : jobsMarkup(defaultJobs);
  const list = checklistMarkup(state.saved, checklists, state.checks);
  return `<details id="kurs-is" class="more tool-detail skills">
    <summary><h2>${esc(t('ui.skills.title', 'Kurs ve iş keşfi'))}</h2></summary>
    <section aria-labelledby="kurs-is-baslik">
      <h3 id="kurs-is-baslik" class="skills-heading">${esc(t('ui.skills.title', 'Kurs ve iş keşfi'))}</h3>
      <p class="skills-intro">${esc(t('ui.skills.intro', 'İBB’nin Enstitü İstanbul İSMEK kataloğundaki program adlarını seçiminize göre gösterir; başvuruyu siz yaparsınız.'))}</p>
      <p class="skills-disclaimer">${esc(t('ui.skills.disclaimer', 'Resmî İBB hizmeti değildir.'))}</p>
      <p class="skills-freshness" lang="${lang}">${esc(stamp)}</p>
      ${form}${unavailable}
      <p class="skills-status" role="status" aria-live="polite" lang="${lang}">${esc(status || '')}</p>
      <div class="skills-results">${resultHtml}${bio}${list}</div>
    </section>
  </details>`;
}

function radioGroup(name, legend, values, selected, firstLabel) {
  const rows = [{ value: '', label: firstLabel }, ...values.map((value) => ({ value, label: value }))];
  return `<fieldset class="skills-choice"><legend>${esc(legend)}</legend><div class="skills-options">${rows.map((item, index) => (
    `<label class="skills-option"><input type="radio" name="${name}" value="${esc(item.value)}"${selected === item.value || (!selected && index === 0) ? ' checked' : ''}> <span lang="${item.value ? 'tr' : currentLang()}">${esc(item.label)}</span></label>`
  )).join('')}</div></fieldset>`;
}

function formMarkup(options, choices = EMPTY_CHOICES, consent = false) {
  const branches = options.branches || [];
  const areas = (options.areas || []).filter((item) => choices.branch && item.branch === choices.branch);
  const branchFields = radioGroup('branch', t('ui.skills.branch_label', 'Ne için?'), branches, choices.branch, t('ui.skills.any', 'Fark etmez'));
  const areaRows = areas.map((item) => `<label class="skills-option" lang="tr"><input type="checkbox" name="areas" value="${esc(item.name)}"${choices.areas.includes(item.name) ? ' checked' : ''} aria-describedby="kurs-is-alan-durumu"> <span>${esc(item.name)}</span><small>${esc(item.programs)} ${esc(t('ui.skills.program_count', 'program'))}</small></label>`).join('');
  const areaField = `<fieldset class="skills-choice"><legend>${esc(t('ui.skills.area_label', 'İlgilendiğiniz alanlar'))}</legend><div class="skills-options">${areaRows || `<p>${esc(t('ui.skills.choose_branch', 'Alanları görmek için önce bir dal seçin.'))}</p>`}</div><p id="kurs-is-alan-durumu" class="skills-hint">${esc(t('ui.skills.area_limit', 'En çok üç alan seçebilirsiniz.'))}</p></fieldset>`;
  const districts = `<div class="skills-field"><label for="kurs-is-ilce">${esc(t('ui.skills.district_label', 'İlçe'))}</label><select id="kurs-is-ilce" name="district"><option value="">${esc(t('ui.skills.optional', 'İsteğe bağlı'))}</option>${(options.districts || []).map((name) => `<option lang="tr" value="${esc(name)}"${choices.district === name ? ' selected' : ''}>${esc(name)}</option>`).join('')}</select></div>`;
  const keyword = `<div class="skills-field"><label for="kurs-is-kelime">${esc(t('ui.skills.keyword_label', 'Anahtar kelime'))}</label><input id="kurs-is-kelime" name="keyword" maxlength="40" autocomplete="off" value="${esc(choices.keyword)}"><p class="skills-hint">${esc(t('ui.skills.keyword_hint', 'Kişisel bilgi yazmayın. En çok 40 karakter.'))}</p></div>`;
  const more = `<details class="skills-more"><summary>${esc(t('ui.skills.more', 'Daha fazla'))}</summary>${radioGroup('mode', t('ui.skills.mode_label', 'Eğitim tipi'), options.modes || [], choices.mode, t('ui.skills.any', 'Fark etmez'))}${radioGroup('time', t('ui.skills.time_label', 'Zaman'), options.times || [], choices.time, t('ui.skills.any', 'Fark etmez'))}</details>`;
  const controls = `<label class="skills-consent"><input type="checkbox" name="consent"${consent ? ' checked' : ''}><span>${esc(t('ui.skills.consent', 'Seçimlerimi ve listemi bu cihazda hatırla'))}</span></label>`;
  const buttons = `<div class="skills-actions"><button class="btn" type="submit">${esc(t('ui.skills.submit', 'Eşleşmeleri göster'))}</button><button class="btn btn-quiet" type="button" data-action="clear">${esc(t('ui.skills.clear', 'Seçimleri temizle'))}</button><button class="btn btn-quiet" type="button" data-action="erase">${esc(t('ui.skills.erase', 'Bu cihazdan sil'))}</button></div>`;
  return `<form class="skills-form">${branchFields}<p class="skills-hint">${esc(t('ui.skills.work_hint', 'İşe hazırlanmak istiyorsanız Mesleki ve Teknik Eğitimler dalını seçin.'))}</p>${areaField}${keyword}${districts}${more}${controls}${buttons}</form>`;
}

function resultMarkup(data, saved = [], checklists = {}) {
  if (!data || !data.available) return '';
  const areas = (data.areas || []).map((item) => `<article class="skills-card" lang="tr"><h4>${esc(item.name)}</h4><p>${esc(item.programs)} ${esc(t('ui.skills.program_count', 'eğitim'))}</p>${link(item.url, t('ui.skills.open_ismek', 'İSMEK’te aç'))}</article>`).join('');
  const programs = (data.programs || []).map((item) => {
    const reasons = (item.reasons || []).map((reason) => `<li><span class="skills-reason-label">${esc(reason.from === 'choice' ? t('ui.skills.reason_choice', 'Sizin seçiminiz') : t('ui.skills.reason_catalog', 'İSMEK kataloğu'))}</span><span lang="tr">${esc(reason.text)}</span></li>`).join('');
    const isSaved = saved.some((entry) => entry.code === item.code);
    const note = item.note ? `<p class="skills-hint" lang="tr">${esc(item.note)}</p>` : '';
    const why = `<details class="skills-why"><summary>${esc(t('ui.skills.why', 'Neden bu sonuç?'))}</summary><ul class="skills-reasons">${reasons}</ul>${note}</details>`;
    return `<article class="skills-card" lang="tr"><h4>${esc(item.name)}</h4>${why}<div class="skills-actions">${link(item.url, t('ui.skills.open_ismek', 'İSMEK’te aç'))}<button class="btn" type="button" data-add-code="${esc(item.code)}"${isSaved ? ' disabled' : ''}>${esc(isSaved ? t('ui.skills.saved', 'Listemde') : t('ui.skills.add', 'Listeme ekle'))}</button></div></article>`;
  }).join('');
  const centerCards = (data.centers || []).map((item) => `<article class="skills-card" lang="tr"><h4>${esc(item.name)}</h4><p>${esc(item.classrooms ?? t('ui.skills.catalog_missing', 'katalogda yok'))} ${esc(t('ui.skills.classrooms', 'derslik'))} · ${esc(item.programs ?? t('ui.skills.catalog_missing', 'katalogda yok'))} ${esc(t('ui.skills.program_count', 'program'))}</p><p class="skills-hint" lang="tr">${esc(item.note)}</p>${link(item.url, t('ui.skills.open_ismek', 'İSMEK’te aç'))}</article>`).join('');
  const time = data.time_hint ? `<p class="skills-hint">${esc(t('ui.skills.nabiz_suggests', 'Nabız önerisi'))}: <span lang="tr">${esc(data.time_hint.text)}</span> ${link(data.time_hint.url, t('ui.skills.open_ismek', 'İSMEK’te aç'))}</p>` : '';
  const groups = `${areas ? `<section><h4>${esc(t('ui.skills.areas_found', 'Seçilen alanlar'))}</h4><div class="skills-grid">${areas}</div></section>` : ''}${programs ? `<section><h4>${esc(t('ui.skills.programs_found', 'Program adları'))}</h4><div class="skills-grid">${programs}</div></section>` : ''}${centerCards ? `<section><h4>${esc(t('ui.skills.centers_found', 'Seçilen ilçedeki merkezler'))}</h4><div class="skills-grid">${centerCards}</div></section>` : ''}`;
  const hasItems = Boolean(areas || programs || centerCards || time);
  const heading = hasItems
    ? `<h3 id="kurs-is-sonuc-baslik" tabindex="-1">${esc(t('ui.skills.results_title', 'Eşleşme sonuçları'))}</h3>` : '';
  const emptyReason = data.empty_reason
    ? `<p lang="tr"${hasItems ? '' : ' id="kurs-is-sonuc-bos" tabindex="-1"'}>${esc(data.empty_reason)}</p>` : '';
  const source = data.source ? `<details class="skills-source"><summary>${esc(t('ui.skills.source', 'Kaynak'))}</summary><p lang="tr">${esc(data.source.name)} · ${esc(data.source.license)}</p><div>${link(data.source.programs_url, t('ui.skills.program_catalog', 'Eğitim programları'))} ${link(data.source.centers_url, t('ui.skills.centers_catalog', 'Eğitim merkezleri'))}</div></details>` : '';
  return `<section${hasItems ? ' aria-labelledby="kurs-is-sonuc-baslik"' : ''}>${heading}${emptyReason}${groups}${time}${source}</section>`;
}

function jobsMarkup(jobs) {
  if (!jobs) return '';
  const card = jobs.card || {};
  const terms = jobs.search_terms || [];
  const list = terms.length ? `<ul>${terms.map((term) => `<li lang="tr">${esc(term)}</li>`).join('')}</ul>` : `<p>${esc(t('ui.skills.no_terms', 'Arama rehberi için bir alan ya da anahtar kelime seçin.'))}</p>`;
  const sourceTitle = card.title ? `<p lang="tr">${esc(card.title)}</p>` : '';
  const reason = card.reason ? `<p lang="tr">${esc(card.reason)}</p>` : '';
  const sourceLanguage = currentLang() === 'en' ? `<p>${esc(t('ui.skills.source_turkish', 'Source text is Turkish.'))}</p>` : '';
  return `<section class="skills-bio"><h3>${esc(t('ui.skills.bio_title', 'Bölgesel İstihdam Ofisleri iş ilanları'))}</h3>${sourceTitle}${link(card.url || 'https://bio.ibb.istanbul/', t('ui.skills.open_bio', 'BİO sayfasını aç'))}<p>${esc(t('ui.skills.bio_unavailable', 'İlanları Nabız göremez; sayfa içeriği JavaScript ile yükleniyor, veri alınamadı.'))}</p>${reason}<h4>${esc(t('ui.skills.search_guide', 'Neyi arayacaksınız'))}</h4><p>${esc(jobs.label || t('ui.skills.nabiz_suggests', 'Nabız önerisi'))}</p>${list}${sourceLanguage}</section>`;
}

function checklistMarkup(saved, checklists, checks) {
  if (!saved.length) return `<section class="skills-list"><h3>${esc(t('ui.skills.list_title', 'Listem'))}</h3><p>${esc(t('ui.skills.list_empty', 'Henüz program eklemediniz.'))}</p></section>`;
  const cards = saved.map((item) => {
    const data = checklists[item.code];
    if (!data || data.error) {
      const message = data && data.error ? t('ui.skills.checklist_error', 'Resmî kontrol listesi okunamadı.') : t('ui.skills.checklist_loading', 'Kontrol listesi okunuyor.');
      return `<article class="skills-card" lang="tr"><h4>${esc(item.name)}</h4><p>${esc(message)}</p><button class="btn btn-quiet" type="button" data-remove-code="${esc(item.code)}">${esc(t('ui.skills.remove', 'Listeden çıkar'))}</button></article>`;
    }
    const links = (data.official || []).map((line) => `<li>${link(line.url, t('ui.skills.official_from', 'Resmî sayfadan'))} <span lang="tr">${esc(line.text)}</span></li>`).join('');
    const quoteDate = data.quote && data.quote.retrieved_at && Number.isFinite(Date.parse(data.quote.retrieved_at))
      ? new Intl.DateTimeFormat(currentLang() === 'en' ? 'en-GB' : 'tr-TR', { timeZone: 'Europe/Istanbul', dateStyle: 'short' }).format(Date.parse(data.quote.retrieved_at))
      : t('ui.skills.date_unknown', 'bilinmiyor');
    const quote = data.quote ? `<blockquote lang="tr">${esc(data.quote.text)}<footer>${link(data.quote.source, t('ui.skills.source', 'Kaynak'))} · ${esc(t('ui.skills.freshness', 'İSMEK kataloğu · kayıtlı · alındı {date}', { date: quoteDate }))}${currentLang() === 'en' ? `<p>${esc(t('ui.skills.source_turkish', 'Source text is Turkish.'))}</p>` : ''}</footer></blockquote>` : '';
    const steps = (data.self_steps || []).map((step) => `<label class="skills-check"><input type="checkbox" data-check-code="${esc(item.code)}" value="${esc(step.id)}"${(checks[item.code] || []).includes(step.id) ? ' checked' : ''}><span>${esc(t(`ui.skills.step_${step.id}`, 'Bu adımı kendim kontrol ettim.'))}</span></label>`).join('');
    return `<article class="skills-card" lang="tr"><h4>${esc(item.name)}</h4><h5>${esc(t('ui.skills.official_group', 'Resmî sayfadan'))}</h5><ul>${links}</ul>${quote}<h5>${esc(t('ui.skills.self_group', 'Sizin işaretiniz'))}</h5><div>${steps}</div><p class="skills-hint">${esc(t('ui.skills.checklist_disclaimer', data.note))}</p><button class="btn btn-quiet" type="button" data-remove-code="${esc(item.code)}">${esc(t('ui.skills.remove', 'Listeden çıkar'))}</button></article>`;
  }).join('');
  return `<section class="skills-list"><h3>${esc(t('ui.skills.list_title', 'Listem'))}</h3><div class="skills-grid">${cards}</div></section>`;
}

export { STORAGE_KEY, KEEP_DAYS, MAX_AREAS, MAX_SAVED, emptyState, parseStored, toStored, sectionMarkup, formMarkup, resultMarkup, jobsMarkup, checklistMarkup };
