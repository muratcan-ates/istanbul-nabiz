/* Self-installing operator panel for offline knowledge gap review. */
const API = '/api/console/knowledge-editor';
const STYLE = '/css/console_knowledge_editor.css';
const ownEvent = 'knowledge-editor';
let languageTools = null;
let api = null;
let state = { data: null, selectedRef: null, selectedCandidate: null, candidateForm: false, reasonForm: null, busy: false, error: '', status: '' };
export function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
}
const t = (key, fallback, vars = {}) => languageTools
  ? languageTools.t(key, fallback, vars)
  : fallback.replace(/\{(\w+)\}/g, (_match, name) => String(vars[name] ?? `{${name}}`));
const tagCopy = (tag) => ({ missing_source: t('ui.ked.tag_missing', 'kaynak yok'), wrong_route: t('ui.ked.tag_wrong', 'yanlış yönlendirme'), stale: t('ui.ked.tag_stale', 'eski bilgi'), not_a_gap: t('ui.ked.tag_not_gap', 'açık değil') })[tag] || t('ui.ked.tag_missing', 'kaynak yok');
const statusCopy = (status) => ({ proposed: t('ui.ked.status_proposed', 'Önerildi'), tried: t('ui.ked.status_tried', 'Denendi'), approved: t('ui.ked.status_approved', 'Onaylandı · dizine alınmayı bekliyor'), rejected: t('ui.ked.status_rejected', 'Reddedildi') })[status] || t('ui.ked.status_proposed', 'Önerildi');
const eventCopy = (kind) => ({ proposed: t('ui.ked.event_proposed', 'Önerildi'), tried: t('ui.ked.event_tried', 'Denendi'), approved: t('ui.ked.event_approved', 'Onaylandı'), rejected: t('ui.ked.event_rejected', 'Reddedildi'), undone: t('ui.ked.event_undone', 'Geri alındı') })[kind] || String(kind);
function timeLabel(value) {
  if (!value) return t('ui.ked.not_available', 'bilinmiyor');
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? String(value) : new Intl.DateTimeFormat(
    languageTools?.currentLang?.() || 'tr', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' },
  ).format(date);
}
function checkList(checks = []) {
  return `<ul class="ked-checks">${checks.map((item) => `<li class="ked-check ked-${esc(item.state)}">`
    + `<span>${esc(({ pass: t('ui.ked.check_pass', 'geçti'), fail: t('ui.ked.check_fail', 'geçmedi'), unknown: t('ui.ked.check_unknown', 'bilinmiyor') })[item.state] || item.state)}</span>`
    + `<span>${esc(item.detail)}</span></li>`).join('')}</ul>`;
}
export function groupMarkup(groups = [], requiredRefusals = 0) {
  if (!groups.length) {
    const empty = `<p class="ked-empty">${esc(t('ui.ked.no_gaps', 'Cevaplanamayan soru yok.'))}</p>`;
    return empty + (requiredRefusals ? `<details class="ked-refusals"><summary>${esc(t('ui.ked.required_refusals', 'Gerekli ret: {count}', { count: requiredRefusals }))}</summary><p>${esc(t('ui.ked.required_refusal_note', 'Doğru reddedilmiş sorular açık sayılmaz.'))}</p></details>` : '');
  }
  const groupHtml = groups.map((group) => `<section class="ked-group" aria-label="${esc(group.category)}">`
    + `<h3>${esc(group.category)} <span>${esc(t('ui.ked.question_count', '{count} soru', { count: group.count }))}</span></h3>`
    + `<ul class="ked-list">${group.items.map((item) => `<li role="listitem"><a href="#knowledge-editor-detail" role="button" class="ked-row" data-ked-ref="${esc(item.ref)}">`
      + `<span class="ked-row-main"><strong lang="${esc(item.lang || 'tr')}">${esc(item.excerpt)}</strong><span class="ked-row-meta">${esc(tagCopy(item.tag))} · ${esc(item.tag_by === 'operator' ? t('ui.ked.operator_tag', 'Operatör etiketi') : t('ui.ked.suggestion', 'Öneri'))}</span></span>`
      + `<span class="ked-row-count">${esc(t('ui.ked.linked_count', '{count} bağlı aday', { count: item.candidates || 0 }))}</span>`
      + `</a></li>`).join('')}</ul></section>`).join('');
  const refusals = requiredRefusals || groups.required_refusals || 0;
  return groupHtml + (refusals ? `<details class="ked-refusals"><summary>${esc(t('ui.ked.required_refusals', 'Gerekli ret: {count}', { count: refusals }))}</summary><p>${esc(t('ui.ked.required_refusal_note', 'Doğru reddedilmiş sorular açık sayılmaz.'))}</p></details>` : '');
}
export function gapMarkup(gap) {
  const source = gap.source === 'request'
    ? t('ui.ked.source_request', 'Operatöre aktarılan talep · maskeli')
    : t('ui.ked.source_eval', 'Değerlendirme sorusu');
  const measurement = gap.measurement || {};
  const answer = measurement.top_url
    ? `<p class="ked-answer">${esc(t('ui.ked.today_source', 'Dizin bugün: {title} · {institution}', { title: measurement.top_title || '', institution: measurement.top_institution || '' }))}<br><a href="${esc(measurement.top_url)}" target="_blank" rel="noopener noreferrer">${esc(measurement.top_url)}</a></p>`
    : `<p class="ked-answer">${esc(t('ui.ked.today_empty', 'Dizin bugün: cevap yok'))}</p>`;
  const gold = (gap.gold_urls || []).map((item) => `<li><a href="${esc(item.url)}" target="_blank" rel="noopener noreferrer">${esc(item.url)}</a> · ${esc(item.versions.length ? t('ui.ked.in_index', 'dizinde var') : t('ui.ked.not_in_index', 'dizinde yok'))}</li>`).join('');
  const tags = ['missing_source', 'wrong_route', 'stale', 'not_a_gap'];
  return `<div class="ked-gap"><p class="ked-origin">${esc(source)}${gap.source === 'request' ? ` · ${esc(t('ui.ked.request_retention', '30 gün saklanır'))}` : ''}</p>`
    + `<h3 lang="${esc(gap.lang || 'tr')}">${esc(gap.question)}</h3>`
    + `<p class="ked-mode">${esc(t('ui.ked.mode_label', 'Cevap modu: {mode} · kanıt: {level}', { mode: measurement.mode || 'unknown', level: measurement.level || 'unknown' }))}</p>${answer}`
    + (gold ? `<details><summary>${esc(t('ui.ked.gold_sources', 'Altın kaynaklar'))}</summary><ul>${gold}</ul></details>` : '')
    + (measurement.stale_hint ? `<p class="ked-stale">${esc(measurement.updated_at_method === 'fetched' ? t('ui.ked.stale_fetched', 'Sayfanın güncelleme tarihi bilinmiyor; bu tarih dizine alındığı gün.') : t('ui.ked.stale_hint', 'Kaynak eski olabilir.'))}</p>` : '')
    + `<fieldset class="ked-tags"><legend>${esc(t('ui.ked.reason_label', 'Neden etiketi'))}</legend>${tags.map((tag) => `<label><input type="radio" name="ked-tag" value="${tag}" ${gap.tag === tag ? 'checked' : ''}>${esc(tagCopy(tag))}${gap.tag === tag ? ` <span>${esc(gap.tag_by === 'operator' ? t('ui.ked.operator_tag', 'Operatör etiketi') : t('ui.ked.suggestion', 'Öneri'))}</span>` : ''}</label>`).join('')}</fieldset>`
    + `<div class="ked-actions"><button type="button" class="btn btn-quiet" data-ked="open-candidate">${esc(t('ui.ked.propose_source', 'Kaynak aday öner'))}</button></div></div>`;
}
function trialMarkup(candidate) {
  if (!candidate.trials?.length) return '';
  const trial = candidate.trials[candidate.trials.length - 1];
  const summary = trial.summary;
  const absent = Math.max(0, summary.questions - summary.in_top_k);
  const rows = trial.rows.map((row) => { const question = candidate.gap_questions?.[row.ref] || {}; return `<tr><th scope="row" data-label="${esc(t('ui.ked.question', 'Soru'))}"><span lang="${esc(question.lang || 'tr')}">${esc(question.question || row.ref)}</span></th>`
    + `<td data-label="${esc(t('ui.ked.mode', 'Cevap modu'))}">${esc(row.mode || 'unknown')}</td>`
    + `<td data-label="${esc(t('ui.ked.first_source', 'İlk kaynak'))}">${row.top_url ? `<a href="${esc(row.top_url)}" rel="noopener noreferrer">${esc(row.top_url)}</a>` : esc(t('ui.ked.no_source', 'kaynak yok'))}</td>`
    + `<td data-label="${esc(t('ui.ked.candidate_rank', 'Aday sırası'))}">${esc(row.candidate_rank || t('ui.ked.not_top_eight', 'ilk 8 içinde yok'))}</td></tr>`; }).join('');
  const previous = candidate.diff ? `<p class="ked-diff">${esc(t('ui.ked.trial_diff', 'Dizin değişti ({before_documents} → {after_documents} belge): ilk sırada {before_rank}/{before_questions} → {after_rank}/{after_questions}', { before_documents: candidate.diff.before_fingerprint.documents ?? '?', after_documents: candidate.diff.after_fingerprint.documents ?? '?', before_rank: candidate.diff.before.top1, before_questions: candidate.diff.before.questions, after_rank: candidate.diff.after.top1, after_questions: candidate.diff.after.questions }))}</p>` : '';
  return `<p class="ked-trial-summary">${esc(t('ui.ked.trial_summary', 'Bugünkü dizinle: {questions} sorunun {top1} tanesinde aday ilk sırada; {absent} tanesinde ilk 8 içinde yok.', { questions: summary.questions, top1: summary.top1, absent }))}</p>`
    + (summary.not_indexed ? `<p>${esc(t('ui.ked.candidate_not_indexed', 'Bu sayfa dizinde yok; dizine alındıktan sonra aynı deneme yeniden koşulur.'))}</p>` : '')
    + previous + `<table class="ked-trial"><caption>${esc(t('ui.ked.trial_table', 'Bugünkü dizinle deneme sonuçları'))}</caption><thead><tr><th>${esc(t('ui.ked.question', 'Soru'))}</th><th>${esc(t('ui.ked.mode', 'Cevap modu'))}</th><th>${esc(t('ui.ked.first_source', 'İlk kaynak'))}</th><th>${esc(t('ui.ked.candidate_rank', 'Aday sırası'))}</th></tr></thead><tbody>${rows}</tbody></table>`;
}
export function candidateMarkup(candidate, options = {}) {
  const active = options.active !== false;
  const form = options.form || null;
  const status = `<span class="ked-status">${esc(statusCopy(candidate.status))}</span>`;
  const primary = candidate.status === 'tried'
    ? `<button class="btn btn-primary" type="button" data-ked="approve">${esc(t('ui.ked.approve', 'Onayla'))}</button>`
    : candidate.status === 'proposed'
      ? `<button class="btn btn-primary" type="button" data-ked="trial">${esc(t('ui.ked.try_today', 'Bugünkü dizinle dene'))}</button>` : '';
  const actions = active && !form ? `<div class="ked-actions">${primary}${candidate.status === 'tried' ? `<button class="btn btn-quiet" type="button" data-ked="reject">${esc(t('ui.ked.reject', 'Reddet'))}</button>` : ''}</div>` : '';
  const reasonLabel = form === 'undo' ? t('ui.ked.undo_reason', 'Geri alma gerekçesi · 5-280 karakter') : t('ui.ked.reason_required', 'Gerekçe · 5-280 karakter');
  const confirm = form === 'approve' ? t('ui.ked.confirm_approve', 'Onayı kaydet') : form === 'undo' ? t('ui.ked.confirm_undo', 'Geri almayı kaydet') : t('ui.ked.confirm_reject', 'Red kararını kaydet');
  const reason = form ? `<form class="ked-reason-form" data-ked-form="reason"><label for="ked-reason">${esc(reasonLabel)}</label><textarea id="ked-reason" name="reason" minlength="5" maxlength="280" required></textarea><div class="ked-actions"><button class="btn btn-primary" type="submit">${esc(confirm)}</button><button class="btn btn-quiet" type="button" data-ked="cancel-reason">${esc(t('ui.ked.cancel', 'Vazgeç'))}</button></div></form>` : '';
  const events = (candidate.events || []).map((event) => `<li><p>${esc(eventCopy(event.kind))} · ${esc(timeLabel(event.at))} · ${esc(event.actor)}${event.ledger_entry ? ` · ${esc(t('ui.ked.ledger_line', 'defter satırı {id}', { id: event.ledger_entry }))}` : ''}</p>${event.reason ? `<p lang="tr">${esc(event.reason)}</p>` : ''}${event.kind !== 'undone' && !event.undone_by ? `<button class="btn btn-quiet" type="button" data-ked-undo="${event.id}">${esc(t('ui.ked.undo', 'Geri al'))}</button>` : ''}${event.undone_by ? `<span>${esc(t('ui.ked.event_undone', 'Geri alındı'))}</span>` : ''}</li>`).join('');
  const activeSha = candidate.versions?.find((item) => item.active)?.sha256;
  const versionItems = candidate.versions?.length
    ? candidate.versions.map((item) => `<li>${esc(item.active ? t('ui.ked.active_version', 'dizinde etkin') : t('ui.ked.old_version', 'önceki sürüm'))} · ${esc(item.sha256)}${activeSha && item.sha256 !== activeSha ? ` · ${esc(t('ui.ked.content_changed', 'içerik değişti'))}` : ''}${item.updated_at_method === 'fetched' ? ` · ${esc(t('ui.ked.updated_unknown', 'sayfa güncelleme tarihi bilinmiyor'))}` : ''} · ${esc(item.title || '')} · ${esc(timeLabel(item.source_updated_at || item.fetched_at))}</li>`).join('')
    : `<li>${esc(t('ui.ked.page_not_in_index', 'Bu sayfa dizinde yok.'))}</li>`;
  return `<article class="ked-candidate" data-candidate-id="${candidate.id}"><header><div><h3>${esc(candidate.url)}</h3><p>${esc(candidate.host)} · ${status}</p>${candidate.note ? `<p>${esc(candidate.note)}</p>` : ''}</div>${active ? '' : `<button class="btn btn-quiet" type="button" data-ked="select-candidate">${esc(t('ui.ked.open_candidate', 'Adayı aç'))}</button>`}</header>`
    + (active ? checkList(candidate.checks) : '')
    + (active ? trialMarkup(candidate) : '')
    + (active ? `<details><summary>${esc(t('ui.ked.versions', 'Sürümler'))}</summary><ul>${versionItems}</ul></details><details><summary>${esc(t('ui.ked.history', 'Geçmiş'))}</summary><ul>${events}</ul></details>` : '')
    + actions + reason + '</article>';
}
function addStylesheet(doc) {
  if (doc.head.querySelector(`link[href="${STYLE}"]`)) return;
  const link = doc.createElement('link');
  link.rel = 'stylesheet';
  link.href = STYLE;
  doc.head.append(link);
}
function indexText(index) {
  if (!index?.built) return t('ui.ked.index_missing', 'Dizin kurulmadı.');
  return t('ui.ked.index_line', 'Dizin: {documents} belge · kuruldu {time}', {
    documents: index.documents, time: timeLabel(index.built_at),
  });
}
function sectionMarkup(data) {
  const feedback = data?.feedback || { up: 0, down: 0, reasons: {} };
  const last = data?.last_scan;
  const scanLabel = last
    ? t('ui.ked.last_scan', 'Son ölçüm {time} · {documents} belge', { time: timeLabel(last.at), documents: last.fingerprint?.documents ?? '?' })
    : t('ui.ked.scan_never', 'Değerlendirme soruları henüz ölçülmedi.');
  const feedbackText = t('ui.ked.feedback_line', 'Bu oturumda: {down} olumsuz oy · {stale} eski bilgi · {wrong} yanlış yönlendirme · soruya bağlı değildir', {
    down: feedback.down, stale: feedback.reasons?.stale || 0, wrong: feedback.reasons?.wrong || 0,
  });
  return `<div class="section-head"><div><h2 id="knowledge-editor-title">${esc(t('ui.ked.title', 'Bilgi açıkları'))}</h2><p class="section-note">${esc(indexText(data?.index))}</p></div>`
    + `<button type="button" class="btn btn-quiet" data-ked="scan" ${state.busy ? 'disabled' : ''}>${esc(t('ui.ked.scan', 'Değerlendirme sorularını ölç'))}</button></div>`
    + `<p class="ked-feedback">${esc(feedbackText)}</p><p class="section-note">${esc(t('ui.ked.privacy_note', 'Sohbet soruları sunucuda saklanmaz; bu liste yalnızca operatöre aktarılan talepler ve değerlendirme sorularından oluşur.'))}</p>`
    + `<p class="section-note">${esc(scanLabel)}</p><p class="ked-status-line" role="status" aria-live="polite">${esc(state.busy ? t('ui.ked.measuring', 'Ölçülüyor') : state.status || '')}</p>`
    + (state.error ? `<p class="ked-error" lang="tr" role="status">${esc(state.error)}</p>` : '')
    + `<div class="ked-grid"><div class="ked-list-panel">${!last ? `<p class="ked-empty">${esc(t('ui.ked.scan_first', 'Değerlendirme sorularını görmek için ölçün.'))}</p>` : ''}${groupMarkup(data?.gaps?.groups || [], data?.gaps?.required_refusals || 0)}`
    + `<div class="ked-detail" id="knowledge-editor-detail" tabindex="-1">${state.detail ? gapMarkup(state.detail) : `<p class="ked-empty">${esc(t('ui.ked.select_gap', 'Bir soru seçin.'))}</p>`}${state.candidateForm ? proposalForm(data) : ''}</div></div>`
    + `<section class="ked-candidates" aria-label="${esc(t('ui.ked.candidates', 'Kaynak adayları'))}"><h3>${esc(t('ui.ked.candidates', 'Kaynak adayları'))}</h3>${candidateList(data?.candidates || [])}</section>`;
}
function proposalForm(data) {
  const groups = data?.gaps?.groups || [];
  const detail = state.detail;
  const same = groups.flatMap((group) => group.items.map((item) => ({ ...item, category: group.category })))
    .filter((item) => item.category === detail?.category);
  const checks = same.map((item) => `<label><input type="checkbox" name="gap_ref" value="${esc(item.ref)}" ${item.ref === detail?.ref ? 'checked' : ''}>${esc(item.excerpt)}</label>`).join('');
  return `<form class="ked-proposal" data-ked-form="proposal"><h3>${esc(t('ui.ked.propose_title', 'Kaynak aday öner'))}</h3>`
    + `<label for="ked-url">${esc(t('ui.ked.url_label', 'Kaynak URL'))}</label><input id="ked-url" name="url" type="url" inputmode="url" required maxlength="2048">`
    + `<fieldset><legend>${esc(t('ui.ked.linked_questions', 'Bağlanacak sorular'))}</legend>${checks}</fieldset>`
    + `<label for="ked-note">${esc(t('ui.ked.note_label', 'Kısa not · 5-280 karakter'))}</label><textarea id="ked-note" name="note" minlength="5" maxlength="280" required></textarea>`
    + `<p class="ked-counter" data-ked-counter>${esc(t('ui.ked.character_count', '{count} / 280', { count: 0 }))}</p>`
    + `${state.proposalChecks?.length ? checkList(state.proposalChecks) : ''}<div class="ked-actions"><button class="btn btn-primary" type="submit">${esc(t('ui.ked.propose', 'Aday öner'))}</button><button class="btn btn-quiet" type="button" data-ked="cancel-proposal">${esc(t('ui.ked.cancel', 'Vazgeç'))}</button></div></form>`;
}
function candidateList(items) {
  if (!items.length) return `<p class="ked-empty">${esc(t('ui.ked.no_candidates', 'Henüz kaynak adayı yok.'))}</p>`;
  return items.map((item) => {
    const selected = item.id === state.selectedCandidate;
    const active = selected && !state.candidateForm;
    return candidateMarkup(active ? state.candidateDetail || item : item, { active, form: active ? state.reasonForm : null });
  }).join('');
}
async function refresh(section, { keepSelection = true } = {}) {
  state.data = await api.get(API);
  if (keepSelection && state.selectedRef) {
    try { state.detail = await api.get(`${API}/gaps/${encodeURIComponent(state.selectedRef)}`); }
    catch { state.detail = null; state.selectedRef = null; }
  }
  if (keepSelection && state.selectedCandidate) {
    try { state.candidateDetail = await api.get(`${API}/candidates/${state.selectedCandidate}`); }
    catch { state.candidateDetail = null; state.selectedCandidate = null; }
  }
  section.innerHTML = sectionMarkup(state.data);
}
function publishChange() {
  if (typeof window !== 'undefined' && typeof window.dispatchEvent === 'function') {
    window.dispatchEvent(new CustomEvent('nabiz:ledger-changed', { detail: { source: ownEvent } }));
  }
}
async function boot() {
  const doc = document;
  const anchor = doc.querySelector('#citizen-requests');
  const fallback = doc.querySelector('#day');
  const section = doc.createElement('section');
  section.id = 'knowledge-editor';
  state.section = section;
  section.setAttribute('aria-labelledby', 'knowledge-editor-title');
  if (anchor) anchor.insertAdjacentElement('afterend', section);
  else if (fallback) fallback.insertAdjacentElement('afterend', section);
  else return;
  addStylesheet(doc);
  [api, languageTools] = await Promise.all([import('./api.js'), import('./i18n_text.js')]);
  if (new URLSearchParams(location.search).get('lang') === 'en') await languageTools.loadCatalogs('en');
  const onLang = languageTools.onLang(() => { section.innerHTML = sectionMarkup(state.data); });
  window.addEventListener('nabiz:ledger-changed', (event) => {
    if (event.detail?.source !== ownEvent) refresh(section).catch(showError);
  });
  section.addEventListener('keydown', (event) => {
    if (event.key === ' ' && event.target.matches('[role="button"][data-ked-ref]')) {
      event.preventDefault(); event.target.click();
    }
  });
  section.addEventListener('input', (event) => {
    if (event.target.matches('#ked-note')) {
      const counter = section.querySelector('[data-ked-counter]');
      if (counter) counter.textContent = t('ui.ked.character_count', '{count} / 280', { count: event.target.value.length });
    }
  });
  section.addEventListener('change', async (event) => {
    if (!event.target.matches('input[name="ked-tag"]') || !state.selectedRef) return;
    try { await postDetailed(`${API}/gaps/${encodeURIComponent(state.selectedRef)}/tag`, { tag: event.target.value }); publishChange(); await refresh(section); }
    catch (error) { showError(error); }
  });
  section.addEventListener('click', (event) => handleClick(event, section));
  section.addEventListener('submit', (event) => handleSubmit(event, section));
  try { await refresh(section, { keepSelection: false }); }
  catch (error) { showError(error); section.innerHTML = sectionMarkup(null); }
  window.addEventListener('beforeunload', onLang, { once: true });
}
function showError(error) {
  state.error = error?.message || t('ui.ked.request_error', 'İstek tamamlanamadı.');
  if (state.section) state.section.innerHTML = sectionMarkup(state.data);
}
async function handleClick(event, section) {
  const target = event.target.closest('[data-ked], [data-ked-ref], [data-ked-undo]');
  if (!target) return;
  const command = target.dataset.ked;
  try {
    if (target.dataset.kedRef) {
      state.selectedRef = target.dataset.kedRef;
      state.detail = await api.get(`${API}/gaps/${encodeURIComponent(state.selectedRef)}`);
      state.selectedCandidate = null; state.candidateForm = false; state.reasonForm = null;
    } else if (command === 'scan') {
      state.busy = true; state.status = ''; section.innerHTML = sectionMarkup(state.data);
      state.data = await postDetailed(`${API}/scan`, {}); state.busy = false; state.detail = null; state.selectedRef = null;
    } else if (command === 'open-candidate') {
      state.candidateForm = true; state.proposalChecks = [];
    } else if (command === 'cancel-proposal') {
      state.candidateForm = false; state.proposalChecks = [];
    } else if (command === 'select-candidate') {
      state.selectedCandidate = Number(target.closest('[data-candidate-id]').dataset.candidateId);
      state.selectedRef = null; state.detail = null; state.candidateDetail = await api.get(`${API}/candidates/${state.selectedCandidate}`);
    } else if (command === 'trial') {
      state.busy = true; section.innerHTML = sectionMarkup(state.data);
      state.candidateDetail = await postDetailed(`${API}/candidates/${state.selectedCandidate}/trial`, {});
      state.busy = false; publishChange(); state.data = await api.get(API);
    } else if (command === 'approve' || command === 'reject') {
      state.reasonForm = command;
    } else if (command === 'cancel-reason') {
      state.reasonForm = null;
    } else if (target.dataset.kedUndo) {
      state.pendingUndo = Number(target.dataset.kedUndo); state.reasonForm = 'undo';
    }
    section.innerHTML = sectionMarkup(state.data);
    section.querySelector(state.candidateForm ? '#ked-url' : state.reasonForm ? '#ked-reason' : '#knowledge-editor-detail')?.focus();
  } catch (error) { state.busy = false; showError(error); }
}
async function handleSubmit(event, section) {
  const form = event.target.closest('[data-ked-form]');
  if (!form) return;
  event.preventDefault();
  const data = new FormData(form);
  try {
    if (form.dataset.kedForm === 'proposal') {
      const response = await postDetailed(`${API}/candidates`, {
        url: data.get('url'), note: data.get('note'), gap_refs: data.getAll('gap_ref'),
      });
      state.selectedCandidate = response.id; state.candidateDetail = response; state.candidateForm = false;
      state.selectedRef = null; state.detail = null; publishChange();
    } else if (form.dataset.kedForm === 'reason') {
      const reason = data.get('reason');
      if (state.reasonForm === 'undo') {
        await postDetailed(`${API}/candidates/${state.selectedCandidate}/events/${state.pendingUndo}/undo`, { reason });
      } else {
        await postDetailed(`${API}/candidates/${state.selectedCandidate}/decide`, {
          action: state.reasonForm, reason,
        });
      }
      state.reasonForm = null; state.pendingUndo = null; publishChange();
    }
    state.error = ''; state.status = t('ui.ked.saved', 'Kaydedildi'); await refresh(section);
  } catch (error) {
    state.error = error?.message || t('ui.ked.request_error', 'İstek tamamlanamadı.');
    const checks = error?.checks || error?.body?.checks;
    if (checks) state.proposalChecks = checks;
    section.innerHTML = sectionMarkup(state.data);
    if (checks) section.querySelector('.ked-checks')?.focus();
  }
}
async function postDetailed(path, payload) {
  const { API_BASE } = await import('./config.js');
  const response = await fetch(new URL(API_BASE + path, location.origin), {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify(payload || {}),
  });
  let body = null;
  try { body = await response.json(); } catch { body = null; }
  if (!response.ok) {
    const error = new Error(body?.message || t('ui.ked.request_error', 'İstek tamamlanamadı.'));
    error.status = response.status;
    error.body = body;
    throw error;
  }
  return body;
}
if (typeof document !== 'undefined') {
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => boot().catch(showError), { once: true });
  else boot().catch(showError);
}
