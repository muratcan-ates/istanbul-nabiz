/* Pure markup for the case-file module. Source text is escaped and stays Turkish. */
import { setCatalogs as setTextCatalogs, t as translate } from './i18n_text.js';

const BAND = 'Örnek iş dosyası · kurumlara hiçbir şey gönderilmez · resmî işlem bağlantıları kurumların kendi sayfalarıdır';
const STORE_KEY = 'nabiz.case-file.v1';
function setCatalogs(language, catalog, trCatalog) {
  setTextCatalogs(language, catalog, trCatalog);
}

function t(key, fallback, vars = {}) {
  return translate(key, fallback, vars);
}

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]
  ));
}

function bandMarkup() {
  return `<p class="case-band" role="note"><span class="tag is-warn">${t('ui.case.example', 'Örnek')}</span> ${esc(BAND)}</p>`;
}

function sourceDate(value) {
  const match = String(value || '').match(/^(\d{4})-(\d{2})-(\d{2})/);
  return match ? `${match[3]}.${match[2]}.${match[1]}` : '';
}

function sourceLink(source, label = 'ui.case.open_source') {
  if (!source || !source.indexed || !source.url) return '';
  return `<a class="btn btn-quiet case-link" href="${esc(source.url)}" target="_blank" rel="noopener">${t(label, 'Resmî sayfayı aç')}</a>`;
}

function sourceMarkup(source) {
  if (!source || !source.indexed) return '';
  const quoteList = source.quotes?.length
    ? `<ul class="case-quotes">${source.quotes.map((item) => `<li lang="tr">${esc(item)}</li>`).join('')}</ul>` : '';
  const documents = source.documents?.length
    ? `<details class="more case-disclosure"><summary>${t('ui.case.documents', 'Gerekli belgeler')}</summary>`
      + `<ul>${source.documents.map((item) => `<li lang="tr">${esc(item)}</li>`).join('')}</ul></details>` : '';
  const stamp = sourceDate(source.fetched_at);
  return `<div class="case-source"><p class="case-source-line" lang="tr">${esc(source.institution)} · ${t('ui.case.recorded', 'kayıtlı')} · ${esc(stamp)}</p>`
    + quoteList + documents + sourceLink(source) + '</div>';
}

function agencyLink(agency, label = 'ui.case.open_official') {
  if (!agency?.url) return '';
  return `<a class="btn btn-quiet case-link" href="${esc(agency.url)}" target="_blank" rel="noopener">${t(label, 'Resmî sayfayı aç')}</a>`;
}

function startView(plans, consent) {
  const available = Array.isArray(plans) ? plans : [];
  const options = available.map((plan, index) => `<label class="check case-plan-option">`
    + `<input type="radio" name="plan_id" value="${esc(plan.id)}"${index === 0 ? ' checked' : ''}>`
    + `<span>${t('ui.case.plan.' + plan.id, plan.title_en || plan.title)}</span></label>`).join('');
  const disabled = available.length ? '' : ' disabled';
  const consentText = consent && consent.text ? consent.text : '';
  return bandMarkup()
    + `<p class="case-intro">${t('ui.case.intro', 'Bir yaşam olayını resmî sayfalara bağlı adımlara çevirir; kaldığınız yeri hatırlar.')}</p>`
    + `<form class="case-start" data-case-start><fieldset><legend>${t('ui.case.choose_plan', 'Plan seçin')}</legend>${options}</fieldset>`
    + `<label class="check"><input type="checkbox" name="consent" required><span lang="tr">${esc(consentText)} `
    + `<a href="/kvkk.html#kvkk-hesap">${t('ui.case.privacy', 'Gizlilik bilgisi')}</a></span></label>`
    + `<p class="field-error" data-case-consent-error hidden>${t('ui.case.consent_error', 'Devam etmek için açık rıza kutusunu işaretleyin.')}</p>`
    + `<button class="btn btn-primary" type="submit" data-case-create data-case-focus="start"${disabled}>${t('ui.case.start', 'Planı başlat')}</button></form>`
    + `<p class="field-hint">${t('ui.case.device_hint', 'Hesapsız da çalışır: iş dosyanız bu tarayıcıya bağlı bir anahtarla açılır. Tarayıcı verilerini silerseniz dosyaya ulaşamazsınız.')}</p>`
    + `<details class="more case-disclosure"><summary>${t('ui.case.how', 'Bu nasıl çalışır?')}</summary>`
    + `<p>${t('ui.case.how_text', 'Her adım ilgili kurumun sayfasına dayanır. Resmî işlem bağlantıları kurumların kendi sayfalarıdır.')}</p></details>`;
}

function waterRoute(choice) {
  const rows = {
    iptal: { source_index: 0, message: "Seçtiğiniz duruma göre ilgili İSKİ sayfası bu. Karar İSKİ'nindir." },
    yenileme: { source_index: 1, message: "Seçtiğiniz duruma göre ilgili İSKİ sayfası bu. Karar İSKİ'nindir." },
    yeni: { source_index: 2, message: "Seçtiğiniz duruma göre ilgili İSKİ sayfası bu. Karar İSKİ'nindir." },
    bilmiyorum: { source_index: null, message: "Bu durum kaynakta açıkça anlatılmıyor. İSKİ'ye ya da 153'e sorun." },
  };
  if (!Object.hasOwn(rows, choice)) throw new TypeError('Unknown water choice');
  return { choice, ...rows[choice] };
}

function addDays(value, amount) {
  const parts = String(value || '').split('-').map(Number);
  if (parts.length !== 3 || parts.some((part) => !Number.isInteger(part))) return '';
  let [year, month, day] = parts;
  const leap = (number) => number % 4 === 0 && (number % 100 !== 0 || number % 400 === 0);
  for (let count = 0; count < amount; count += 1) {
    const sizes = [31, leap(year) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    day += 1;
    if (day > sizes[month - 1]) { day = 1; month += 1; }
    if (month > 12) { month = 1; year += 1; }
  }
  return `${String(year).padStart(4, '0')}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
}

function stepState(file, stepId) {
  return file.steps?.find((item) => item.step_id === stepId) || { step_id: stepId };
}

function pointsMarkup(step, district) {
  const selected = district || '';
  const options = (step.districts || []).map((item) => `<option lang="tr" value="${esc(item)}"${selected === item ? ' selected' : ''}>${esc(item)}</option>`).join('');
  const control = `<label class="case-field">${t('ui.case.district', 'İlçe seçin')}<select data-case-district data-case-focus="district"><option value="">${t('ui.case.choose_district', 'İlçenizi seçin')}</option>${options}</select></label>`;
  if (!selected) return control + `<p class="field-hint">${t('ui.case.select_district_first', 'İlçenizi seçin.')}</p>`;
  const points = (step.points || []).filter((item) => item.district === selected);
  if (!points.length) {
    const source = step.sources?.find((item) => item.indexed);
    return control + `<p>${t('ui.case.no_district_points', 'Bu ilçe için listede nokta yok.')}</p>`
      + sourceLink(source) + `<p lang="tr">${esc(step.agency_info?.name || '')}</p>`;
  }
  return control + `<ul class="case-points">${points.map((item) => `<li><strong lang="tr">${esc(item.name)}</strong>`
    + `<span lang="tr">${esc(item.address)}</span></li>`).join('')}</ul>`;
}

function choiceMarkup(step, file, plan) {
  const value = file.answers?.[step.id] || '';
  const choices = (step.choices || []).map((choice) => `<label class="check case-choice"><input type="radio" name="water-${esc(file.id)}"`
    + ` data-case-answer="${esc(choice.id)}" data-case-focus="answer"${value === choice.id ? ' checked' : ''}><span>`
    + `${t('ui.case.choice.' + choice.id, choice.label_en || choice.label)}</span></label>`).join('');
  let detail = '';
  if (value) {
    const route = waterRoute(value);
    detail = `<p class="case-route">${t('ui.case.route_' + value, route.message)}</p>`;
    if (route.source_index === null) {
      detail += `<ul class="case-source-links">${step.sources.map((source) => sourceLink(source)).filter(Boolean).map((item) => `<li>${item}</li>`).join('')}`;
      const help = plan.steps.find((item) => item.id === '153');
      if (help) detail += `<li>${agencyLink(help.agency_info)}</li>`;
      detail += '</ul>';
    } else {
      detail += sourceMarkup(step.sources[route.source_index]);
      if (value === 'yeni') detail += `<p>${t('ui.case.channel_missing', 'Başvuru kanalı bu sayfada yazmıyor; resmî sayfayı açın.')}</p>`;
      if (!step.sources[route.source_index]?.indexed) detail += `<p>${t('ui.case.source_missing', 'Bu konuda dizinde kaynak henüz yok; resmî siteyi açın.')}</p>`;
    }
  }
  return `<fieldset class="case-choice-group"><legend>${t('ui.case.water_question', 'Bu evde su aboneliği ne durumda?')}</legend>`
    + choices + '</fieldset>' + detail;
}

function taskMarkup(step) {
  const available = (step.sources || []).filter((source) => source.indexed);
  if (!available.length) return `<p>${t('ui.case.source_missing', 'Bu konuda dizinde kaynak henüz yok; resmî siteyi açın.')}</p>`;
  return available.map((source) => sourceMarkup(source)).join('');
}

function linkMarkup(step) {
  const message = t('ui.case.source_missing', 'Bu konuda dizinde kaynak henüz yok; resmî siteyi açın.');
  if (step.agency === 'district_office') {
    return `<p>${esc(step.agency_info?.hint || t('ui.case.district_office_hint', 'ilçe belediyenizin resmî sitesi'))}</p>`;
  }
  const source = step.sources?.find((item) => item.indexed);
  if (source) return `<p>${t('ui.case.points_unavailable', 'Noktalar listelenemedi; resmî sayfayı açın.')}</p>${sourceLink(source)}`;
  return `<p>${message}</p>${agencyLink(step.agency_info)}`;
}

function editDetails(step, saved) {
  return `<details class="more case-disclosure"><summary>${t('ui.case.note_ref', 'Not ve referans kodu')}</summary>`
    + `<form data-case-note data-step-id="${esc(step.id)}"><label class="case-field">${t('ui.case.note', 'Not')}`
    + `<textarea name="note" maxlength="280" data-case-note-input data-case-focus="note" data-step-id="${esc(step.id)}">${esc(saved.note || '')}</textarea></label>`
    + `<p class="field-hint">${t('ui.case.no_pii', 'Kimlik, kart, telefon yazmayın.')}</p>`
    + `<label class="case-field">${t('ui.case.reference', 'Referans kodu (kurumdan aldığınız başvuru numarası)')}`
    + `<input type="text" name="ref_code" maxlength="40" autocomplete="off" data-case-ref-input data-case-focus="reference" data-step-id="${esc(step.id)}" value="${esc(saved.ref_code || '')}"></label>`
    + `<button class="btn" type="submit" data-case-focus="save-note" data-step-id="${esc(step.id)}">${t('ui.case.save', 'Kaydet')}</button></form></details>`;
}

function reminderDetails(step, saved, today) {
  const end = addDays(today, 365);
  return `<details class="more case-disclosure"><summary>${t('ui.case.reminder', 'Hatırlatma')}</summary>`
    + `<form data-case-reminder data-step-id="${esc(step.id)}"><label class="case-field">${t('ui.case.remind_on', 'Hatırlatma tarihi')}`
    + `<input type="date" name="remind_on" min="${esc(today)}" max="${esc(end)}" data-case-remind-input data-case-focus="reminder" data-step-id="${esc(step.id)}" value="${esc(saved.remind_on || '')}"></label>`
    + `<p class="field-hint">${t('ui.case.reminder_hint', 'Hatırlatma yalnız bu sayfayı açtığınızda görünür; bildirim gönderilmez.')}</p>`
    + `<button class="btn" type="submit" data-case-focus="save-reminder" data-step-id="${esc(step.id)}">${t('ui.case.save', 'Kaydet')}</button>`
    + (saved.remind_on ? `<button class="btn btn-quiet" type="button" data-case-reminder-clear="${esc(step.id)}">${t('ui.case.remove_reminder', 'Hatırlatmayı kaldır')}</button>` : '')
    + '</form></details>';
}

function stepMarkup(step, file, plan, today, district) {
  const saved = stepState(file, step.id);
  const justDone = file.just_done_step_id === step.id;
  let content = '';
  if (step.kind === 'choice') content = choiceMarkup(step, file, plan);
  else if (step.kind === 'task') content = taskMarkup(step);
  else if (step.kind === 'points') content = pointsMarkup(step, district);
  else content = linkMarkup(step);
  const done = saved.done_at ? ' checked' : '';
  const added = saved.done_at || saved.note || saved.ref_code || saved.remind_on
    ? `<p class="case-added" lang="tr">${t('ui.case.added_by_user', 'Siz eklediniz')} · ${t('ui.case.not_verified', 'Kurum doğrulaması yok')}</p>` : '';
  return `<li class="case-step${saved.done_at ? ' is-done' : ''}${justDone ? ' case-just-done' : ''}" data-case-step="${esc(step.id)}">`
    + `<div class="case-step-head"><h3>${t('ui.case.step.' + step.id, step.title)}</h3><label class="check"><input type="checkbox" data-case-done="${esc(step.id)}" data-case-focus="done" data-step-id="${esc(step.id)}"${done}>`
    + `<span>${t('ui.case.completed', 'Tamamlandı')}</span></label>${saved.done_at ? '<span class="case-checkmark" aria-hidden="true">✓</span>' : ''}`
    + `</div><div class="case-step-content">${content}</div>${added}`
    + editDetails(step, saved) + reminderDetails(step, saved, today) + '</li>';
}

function deleteDetails() {
  return `<details class="more case-disclosure case-delete"><summary>${t('ui.case.delete_file', 'İş dosyasını sil')}</summary>`
    + `<p>${t('ui.case.delete_explain', 'Adımlarınız, notlarınız ve referans kodlarınız silinir.')}</p>`
    + `<form data-case-delete><button class="btn" type="submit" data-case-focus="delete">${t('ui.case.delete', 'Sil')}</button></form></details>`;
}

function fileView(file, plan, today, district = '') {
  const day = typeof today === 'string' ? today : today?.today || '';
  const p = file.progress || { done: 0, total: plan.steps.length };
  const reminders = (file.reminders || []).map((item) => `<li>${t('ui.case.reminder_today', 'Bugün hatırlatma: {step}', { step: esc(item.title) })}</li>`).join('');
  const steps = plan.steps.map((step) => stepMarkup(step, file, plan, day, district)).join('');
  const complete = p.total > 0 && p.done === p.total
    ? `<p class="case-complete">${t('ui.case.all_done', 'Tüm adımlar tamam')}</p>` : '';
  return bandMarkup()
    + `<div class="case-progress"><p>${t('ui.case.progress', '{done}/{total} adım tamam', { done: p.done, total: p.total })}</p>`
    + `<progress max="${p.total}" value="${p.done}">${esc(p.done)}/${esc(p.total)}</progress></div>`
    + (reminders ? `<ul class="case-reminders">${reminders}</ul>` : '') + complete
    + `<ol class="case-steps">${steps}</ol>${deleteDetails()}`
    + `<p class="status-line" id="case-status" role="status" data-case-status></p>`;
}

function loadingView() {
  return bandMarkup() + `<p class="case-loading" aria-busy="true">${t('ui.case.loading', 'Yükleniyor')}</p>`;
}

function errorView(message) {
  return bandMarkup() + `<p class="field-error" lang="tr">${esc(message || t('ui.case.error', 'İş dosyası açılamadı. Yeniden deneyin.'))}</p>`
    + `<button class="btn btn-primary" type="button" data-case-retry data-case-focus="retry">${t('ui.case.retry', 'Yeniden dene')}</button>`;
}

function caseMarkup(state) {
  if (!state || state.screen === 'loading') return loadingView();
  if (state.screen === 'error') return errorView(state.message);
  if (state.file && state.plan) return fileView(state.file, state.plan, state.today || '', state.district || '');
  return startView(state.plans || [], state.consent || {});
}

export {
  BAND, STORE_KEY, caseMarkup, errorView, fileView, loadingView, setCatalogs, sourceMarkup, startView, waterRoute,
};
