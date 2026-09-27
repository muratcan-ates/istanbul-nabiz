/* Operator incident files are an optional page module: no anchor means no request. */
import { MOCK, get, post } from './api.js';
import { dateTime, esc } from './format.js';
import { onLang, t } from './i18n_text.js';
const FALLBACK = {
  title: 'Olay dosyaları', description: 'Aynı istasyondaki vatandaş bildirimleri, fotoğraflar ve İBB kaydı bir arada. Öncelik bir öneridir; karar sizindir.', empty: 'Bu pencerede olay dosyası yok. Vatandaş bildirimi gelince burada görünür.', mock: 'Örnek veri modunda olay dosyaları gösterilmez.',
  loading: 'Olay dosyaları yükleniyor.', loadError: 'Olay dosyaları şu an yüklenemedi.', count: '{count} olay dosyası', priorityHigh: 'Yüksek', priorityMedium: 'Orta', priorityNormal: 'Olağan', suggestion: 'Öneri: {level}',
  operatorDecision: 'Operatör kararı: {level}', reportsPhotos: '{reports} bildirim · {photos} fotoğraf · {record}', recordYes: 'İBB kaydı var', recordNo: 'İBB kaydı yok', people: '{count} kişi bildirdi',
  reportGroup: 'Vatandaş bildirimleri (doğrulanmamış)', photoGroup: 'Fotoğraflar (vatandaş ekledi)', equipmentGroup: 'Resmî kayıt (kurum kaydı)', noPhotos: 'Fotoğraf modülü bu sunucuda yok.',
  photoNoProof: 'Fotoğraf tek başına kanıt değildir.', sourceLedger: 'defter', sourceRecord: 'kurum kaydı', sourceCitizen: 'vatandaş (doğrulanmamış)', repeatFactor: '{people} kişi, {cards} kart. Tekrar kodu: {repeat}. Pencere: {days} gün.',
  waitingFactor: 'En eski açık kart {hours} saattir bekliyor; eşik {threshold} saat.', accessVerified: 'Kurum kaydında {equipment} için {status}.', accessUnverified: 'Erişim etkisi vatandaş bildirimiyle sınırlı; kurum kaydı yok.',
  interchange: 'Aktarma istasyonu ({line}).', conflictFactor: 'Bildirim ile kurum kaydı çelişiyor: {text}. Yerinde kontrol gerekebilir.', noConflict: 'Kaynak çelişkisi yok.', statusAwaiting: 'onay bekliyor', statusApproved: 'onaylandı',
  statusRejected: 'reddedildi', statusDeferred: 'ertelendi', statusExpired: 'süresi doldu', statusReceived: 'alındı', openCard: 'Kartı aç', split: 'Ayır', merge: 'Başka olayla birleştir', changePriority: 'Önceliği değiştir',
  returnSuggestion: 'Öneriye dön', undo: 'Geri al', history: 'Geçmiş', howCalculated: 'Nasıl hesaplandı?', calculationNote: 'Eşikler tasarım kararıdır: bekleme {wait} saat, tekrar eşiği {support} kişi. Doğrulanmış erişim etkisi yalnız İBB kaydından gelir.',
  agency: 'Önerilen kurum: {name}', agencyFallback: '153 Çözüm Merkezi', agencyNote: 'Öneri. Nabız hiçbir ekibe iş atamaz; karar ve iletme İBB çalışanınındır.',
  noRecord: 'Bu istasyon için İBB arıza kaydında satır yok. Kayıtta olmamak çalıştığını kanıtlamaz.', multiStation: 'Bu olay birden çok istasyonu içeriyor.', reasonLabel: 'Gerekçe',
  reasonHelp: '5 ile 280 karakter. Kişisel bilgi yazmayın.', reasonInvalid: 'Gerekçe 5 ile 280 karakter olmalı ve kişisel bilgi içermemelidir.', save: 'Kaydet', cancel: 'Vazgeç', targetLabel: 'Hedef olay', levelLabel: 'Öncelik düzeyi',
  prioritySaved: 'Öncelik kaydedildi. Defter #{entry}.', splitSaved: 'Üye ayrıldı. Defter #{entry}.', mergeSaved: 'Olaylar birleştirildi. Defter #{entry}.', undoSaved: 'Eylem geri alındı. Defter #{entry}.',
  saveError: 'İşlem kaydedilemedi: {message}', actionSplit: 'Üye ayrıldı', actionMerge: 'Olay birleştirildi', actionUndo: 'Eylem geri alındı', ledgerRow: 'defter #{entry}', undone: 'geri alındı',
  reasonHistory: 'Gerekçe: {reason}', at: 'kayıtlı · {time}', photoAlt: 'Vatandaşın gönderdiği fotoğraf: {category}, {station}', repeatCode: 'var', repeatNoCode: 'yok', waitOver: 'bekleme eşiği {threshold} saat aşıldı',
  waitUnder: 'bekleme eşiği {threshold} saat aşılmadı', waitNone: 'Açık kart yok; bekleme eşiği {threshold} saat.', thresholds: 'Önerinin dayanakları',
  incidentLink: 'Bu bildirim {station} olay dosyasında: {reports} bildirim, {photos} fotoğraf.', openIncident: 'Olay dosyasını aç', noReports: 'Bu olay dosyasına bağlı vatandaş bildirimi yok.', noPhotosAttached: 'Bu olay dosyasına bağlı fotoğraf yok.',
  escalatorContext: 'Yürüyen merdiven kaydı erişilebilir güzergâhı doğrulamaz.', agencyLink: 'resmî sayfa',
};
const I18N_KEYS = Object.keys(FALLBACK);
const tx = (key, vars = {}) => esc(t(`ui.inc.${key}`, FALLBACK[key] || '', Object.fromEntries(
  Object.entries(vars).map(([name, value]) => [name, esc(value)]),
)));
const levelKey = (level) => ({ high: 'priorityHigh', medium: 'priorityMedium', normal: 'priorityNormal' }[level] || 'priorityNormal'); const levelName = (level) => tx(levelKey(level)); const at = (value) => value ? tx('at', { time: dateTime(value) }) : '';
export function validReason(value) {
  const reason = String(value || '').trim();
  return reason.length >= 5 && reason.length <= 280 && !/[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}/.test(reason)
    && !/(?:\+?90|0)?5\d{9}/.test(reason) && !/\b[1-9]\d{10}\b/.test(reason);
}
export function priorityBadge(priority = {}) {
  const level = levelName(priority.level);
  const tone = priority.level === 'high' ? 'warn' : priority.level === 'medium' ? 'accent' : 'quiet';
  return priority.by === 'operator' ? { text: tx('operatorDecision', { level }), tone: 'accent' }
    : { text: tx('suggestion', { level }), tone };
}
export function factorLines(suggestion = {}) {
  return (suggestion.factors || []).map((factor) => {
    const values = factor.values || {};
    let text = '';
    if (factor.key === 'repeat') text = tx('repeatFactor', { people: values.people ?? 0, cards: values.cards ?? 0,
      repeat: tx(values.repeat_code ? 'repeatCode' : 'repeatNoCode'), days: Number(values.window_hours || 0) / 24 });
    if (factor.key === 'waiting') text = values.hours === null
      ? tx('waitNone', { threshold: values.threshold_hours ?? 0 })
      : `${tx('waitingFactor', { hours: values.hours, threshold: values.threshold_hours ?? 0 })} `
        + tx(values.over ? 'waitOver' : 'waitUnder', { threshold: values.threshold_hours ?? 0 });
    if (factor.key === 'access') {
      text = factor.verified
        ? tx('accessVerified', { equipment: values.equipment_type || 'asansör', status: values.status_type || 'kurum kaydı' })
        : tx('accessUnverified');
      if (values.interchange) text += ` ${tx('interchange', { line: values.line || '' })}`;
      if (values.escalator_recorded) text += ` ${tx('escalatorContext')}`;
    }
    if (factor.key === 'conflict') text = tx('conflictFactor', { text: values.text || '' });
    return { key: factor.key, text, source: factor.source, verified: factor.verified };
  });
}
function badgeMarkup(priority) { const badge = priorityBadge(priority); return `<span class="incident-priority is-${badge.tone}">${badge.text}</span>`; }
export function listMarkup(data = {}, ui = {}) {
  const items = data.items || [];
  if (!items.length) return `<p class="incident-empty">${tx('empty')}</p>`;
  return `<ul class="incident-list">${items.map((item) => {
    const selected = item.id === ui.selectedId;
    const count = tx('reportsPhotos', { reports: item.members?.reports || 0, photos: item.members?.photos || 0,
      record: item.members?.equipment ? tx('recordYes') : tx('recordNo') });
    return `<li><button class="incident-row" type="button" data-select="${esc(item.id)}" aria-current="${selected}">`
      + `<span class="incident-row-title" lang="tr">${esc(item.title_station)}</span>${badgeMarkup(item.priority)}`
      + `<span class="incident-row-count">${count}</span></button></li>`;
  }).join('')}</ul>`;
}
function sourceLabel(source, verified) { return source === 'ibb_record' ? tx('sourceRecord') : tx(verified === false ? 'sourceCitizen' : 'sourceLedger'); }
function factorMarkup(suggestion) {
  return `<section class="incident-factors"><h4>${tx('thresholds')}</h4><ul>${factorLines(suggestion).map((line) => {
    const factor = (suggestion.factors || []).find((item) => item.key === line.key) || {};
    return `<li><p>${line.text}</p><span class="incident-source">${sourceLabel(line.source, line.verified)}</span>`
      + `${factor.observed_at ? `<time>${at(factor.observed_at)}</time>` : ''}</li>`;
  }).join('')}</ul></section>`;
}
function memberActions(member, kind) {
  const split = `<button class="btn btn-quiet" type="button" data-action="split" data-ref="${esc(member.ref)}">${tx('split')}</button>`;
  const open = kind === 'report' ? `<button class="btn btn-quiet" type="button" data-open-card="${esc(member.signal_id)}">${tx('openCard')}</button>` : '';
  return `<div class="incident-member-actions">${open}${split}</div>`;
}
function reportGroup(items) {
  return `<section class="incident-group"><h4>${tx('reportGroup')}</h4>${items.length ? `<ul>${items.map((item) =>
    `<li><div><b lang="tr">${esc(item.kind_text || item.report_kind || '')}</b> · ${tx('people', { count: item.support || 1 })}`
    + `<span class="incident-meta">${tx(`status${({ awaiting_approval: 'Awaiting', approved: 'Approved', rejected: 'Rejected', deferred: 'Deferred', expired: 'Expired', received: 'Received' }[item.status] || 'Received')}`)} · ${at(item.received_at)}</span></div>`
    + memberActions(item, 'report') + '</li>',
  ).join('')}</ul>` : `<p>${tx('noReports')}</p>`}</section>`;
}
function photoGroup(items, photosAvailable) {
  const body = !photosAvailable ? `<p>${tx('noPhotos')}</p>` : items.length ? `<ul>${items.map((item) =>
    `<li><div><b lang="tr">${esc(item.category || '')}</b><span class="incident-meta">${at(item.created_at)} · ${esc(item.status || '')}</span>`
    + `${item.photo_url ? `<img loading="lazy" src="${esc(item.photo_url)}" alt="${tx('photoAlt', { category: item.category || '', station: item.station || '' })}">` : ''}`
    + `<p>${tx('photoNoProof')}</p></div>${memberActions(item, 'photo')}</li>`,
  ).join('')}</ul>` : `<p>${tx('noPhotosAttached')}</p>`;
  return `<section class="incident-group"><h4>${tx('photoGroup')}</h4>${body}</section>`;
}
function equipmentGroup(items, recordNote) {
  const body = items.length ? `<ul>${items.map((item) => `<li><div><b lang="tr">${esc(item.equipment_type || '')} · ${esc(item.status_type || item.status_class || '')}</b>`
    + `<span class="incident-meta">${esc(item.source || tx('sourceRecord'))} · ${at(item.observed_at || item.ibb_date)}</span></div>${memberActions(item, 'equipment')}</li>`).join('')}</ul>`
    : `<p>${tx(recordNote === 'no_record' ? 'noRecord' : 'noConflict')}</p>`;
  return `<section class="incident-group"><h4>${tx('equipmentGroup')}</h4>${body}</section>`;
}
function historyMarkup(actions) {
  return `<details><summary>${tx('history')}</summary><ul class="incident-history">${(actions || []).map((item) => {
    const action = tx(item.kind === 'split' ? 'actionSplit' : 'actionMerge');
    return `<li><b>${action}</b> · ${esc(item.actor || '')} · ${at(item.at)} · ${tx('ledgerRow', { entry: item.ledger_entry })}`
      + `<p>${tx('reasonHistory', { reason: item.reason || '' })}</p>`
      + `${item.undone_at ? `<p>${tx('undone')}: ${esc(item.undo_reason || '')} · ${at(item.undone_at)}</p>`
        : `<button class="btn btn-quiet" type="button" data-action="undo" data-id="${item.id}">${tx('undo')}</button>`}</li>`;
  }).join('')}</ul></details>`;
}
function formMarkup(form, incident, ui) {
  if (!form) return '';
  let select = '';
  if (form.kind === 'merge') select = `<label for="incident-target">${tx('targetLabel')}</label><select id="incident-target" name="target" required>${(ui.data?.items || []).filter((item) => item.id !== incident.id)
    .map((item) => `<option value="${esc(item.id)}">${esc(item.title_station)}</option>`).join('')}</select>`;
  if (form.kind === 'priority') select = `<label for="incident-level">${tx('levelLabel')}</label><select id="incident-level" name="level">${[['high', 'priorityHigh'], ['medium', 'priorityMedium'], ['normal', 'priorityNormal'], ['suggested', 'returnSuggestion']].map(([value, key]) => `<option value="${value}"${form.level === value ? ' selected' : ''}>${tx(key)}</option>`).join('')}</select>`;
  return `<form class="incident-form" data-form="${esc(form.kind)}" data-ref="${esc(form.ref || '')}" data-id="${esc(form.id || '')}">`
    + `${select}<label for="incident-reason">${tx('reasonLabel')}</label>`
    + `<textarea id="incident-reason" name="reason" maxlength="280" required aria-describedby="incident-reason-help incident-reason-error"></textarea>`
    + `<span id="incident-reason-help">${tx('reasonHelp')}</span><span id="incident-reason-error" class="incident-error" hidden>${tx('reasonInvalid')}</span>`
    + `<div class="incident-form-actions"><button class="btn btn-primary" type="submit">${tx('save')}</button>`
    + `<button class="btn btn-quiet" type="button" data-cancel>${tx('cancel')}</button></div></form>`;
}
function actionsMarkup(incident, ui) {
  const merge = (ui.data?.items || []).length > 1 ? `<button class="btn btn-quiet" type="button" data-action="merge">${tx('merge')}</button>` : '';
  return `${merge}<button class="btn btn-quiet" type="button" data-action="priority">${tx('changePriority')}</button>`
    + `${incident.priority.by === 'operator' ? `<button class="btn btn-quiet" type="button" data-action="priority" data-level="suggested">${tx('returnSuggestion')}</button>` : ''}${formMarkup(ui.form, incident, ui)}`;
}
export function detailMarkup(incident, ui = {}) {
  if (!incident) return `<p class="incident-empty">${tx('empty')}</p>`;
  const priority = incident.priority || {};
  const suggestion = incident.suggestion || {};
  const groups = incident.members || {};
  const suggested = priority.by === 'operator'
    ? `<p class="incident-suggested">${tx('suggestion', { level: levelName(priority.suggested_level) })}</p>` : '';
  const decision = priority.by === 'operator'
    ? `<p>${tx('reasonHistory', { reason: priority.reason || '' })} · ${esc(priority.actor || '')} · ${at(priority.at)}</p>` : '';
  const agency = incident.agency || {};
  const url = typeof agency.url === 'string' && /^https:\/\//.test(agency.url) ? agency.url : '';
  return `<article class="incident-detail"><h3 id="incident-detail-title" tabindex="-1" lang="tr">${esc(incident.title_station)}</h3>`
    + `${incident.multi_station ? `<p>${tx('multiStation')}</p>` : ''}<section class="incident-priority-card"><h4>${badgeMarkup(priority)}</h4>`
    + `${decision}${suggested}${factorMarkup(suggestion)}</section>`
    + `${reportGroup(groups.reports || [])}${photoGroup(groups.photos || [], incident.photos_available)}${equipmentGroup(groups.equipment || [], incident.record_note)}`
    + `<section class="incident-agency"><h4>${tx('agency', { name: agency.name || tx('agencyFallback') })}</h4>`
    + `${url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${tx('agencyLink')}</a>` : ''}`
    + `<p>${tx('agencyNote')}</p></section>`
    + `${historyMarkup(incident.actions || [])}<details><summary>${tx('howCalculated')}</summary><p>${tx('calculationNote', {
      wait: suggestion.factors?.find((item) => item.key === 'waiting')?.values?.threshold_hours ?? 0,
      support: suggestion.factors?.find((item) => item.key === 'repeat')?.values?.threshold_people ?? 0,
    })}</p></details>${actionsMarkup(incident, ui)}</article>`;
}
function sectionShell() {
  return `<div class="incidents-head"><h2 id="incidents-title">${tx('title')}</h2><span data-count></span></div>`
    + `<p class="incidents-description">${tx('description')}</p><p class="incidents-status" role="status" aria-live="polite"></p>`
    + `<div class="incidents-grid"><div class="incidents-list-host"></div><div class="incidents-detail-host"></div></div>`;
}
function mount() {
  if (typeof document === 'undefined' || typeof window === 'undefined') return;
  const anchor = document.getElementById('report-map') || document.getElementById('day');
  if (!anchor) return;
  let section = document.getElementById('incidents');
  if (!section) {
    section = document.createElement('section');
    section.id = 'incidents'; section.className = 'incidents';
    section.setAttribute('aria-labelledby', 'incidents-title');
    section.innerHTML = sectionShell(); anchor.after(section);
  }
  if (!document.querySelector('link[data-incidents-styles]')) {
    const link = document.createElement('link');
    link.rel = 'stylesheet'; link.href = '/css/console_incidents.css'; link.dataset.incidentsStyles = '';
    document.head.append(link);
  }
  const state = { data: { items: [] }, selectedId: '', detail: null, form: null, error: '', status: '' };
  let selfWrite = false;
  const count = section.querySelector('[data-count]');
  const status = section.querySelector('[role="status"]');
  const listHost = section.querySelector('.incidents-list-host');
  const detailHost = section.querySelector('.incidents-detail-host');
  const render = (draw = true) => {
    count.textContent = tx('count', { count: state.data.items?.length || 0 });
    status.textContent = state.status || state.error;
    if (!draw) return;
    if (MOCK) { listHost.replaceChildren(); detailHost.replaceChildren(); return; }
    listHost.innerHTML = listMarkup(state.data, state);
    detailHost.innerHTML = detailMarkup(state.detail, state);
  };
  const load = async ({ keepForm = false } = {}) => {
    if (MOCK) { state.data = { items: [] }; state.detail = null; state.status = tx('mock'); render(); return; }
    try {
      state.data = await get('/api/console/incidents');
      state.error = '';
      if (keepForm && state.form) { render(false); return; }
      if (!state.data.items?.some((item) => item.id === state.selectedId)) state.selectedId = state.data.items?.[0]?.id || '';
      state.detail = state.selectedId ? await get(`/api/console/incidents/${encodeURIComponent(state.selectedId)}`) : null;
      render();
    } catch (error) { state.error = error.message || tx('loadError'); render(); }
  };
  const selectIncident = async (id, focus = false) => {
    state.selectedId = id; state.form = null;
    try { state.detail = await get(`/api/console/incidents/${encodeURIComponent(id)}`); state.error = ''; }
    catch (error) { state.error = error.message || tx('loadError'); }
    render();
    if (focus) section.querySelector('#incident-detail-title')?.focus();
  };
  section.addEventListener('click', async (event) => {
    const select = event.target.closest('[data-select]');
    if (select) { await selectIncident(select.dataset.select); return; }
    const open = event.target.closest('[data-open-card]');
    if (open) { document.dispatchEvent(new CustomEvent('nabiz:open-decision', { detail: { id: open.dataset.openCard } })); return; }
    if (event.target.closest('[data-cancel]')) { state.form = null; render(); return; }
    const button = event.target.closest('[data-action]');
    if (!button) return;
    const kind = button.dataset.action;
    if (kind === 'undo') state.form = { kind, id: button.dataset.id };
    else state.form = { kind, ref: button.dataset.ref || '', level: button.dataset.level || state.detail?.priority?.level || '' };
    state.status = ''; render(); section.querySelector('#incident-reason')?.focus();
  });
  section.addEventListener('input', (event) => {
    if (event.target.name === 'reason') {
      const error = section.querySelector('#incident-reason-error');
      if (error) error.hidden = validReason(event.target.value);
    }
  });
  section.addEventListener('submit', async (event) => {
    const form = event.target.closest('[data-form]');
    if (!form) return;
    event.preventDefault();
    const reason = form.elements.reason.value.trim();
    if (!validReason(reason)) { section.querySelector('#incident-reason-error').hidden = false; form.elements.reason.focus(); return; }
    const kind = form.dataset.form;
    const body = { reason };
    if (kind === 'split') body.ref = form.dataset.ref;
    if (kind === 'merge') body.target = form.elements.target.value;
    if (kind === 'priority') body.level = form.elements.level.value;
    const paths = {
      split: `/api/console/incidents/${encodeURIComponent(state.selectedId)}/split`,
      merge: `/api/console/incidents/${encodeURIComponent(state.selectedId)}/merge`,
      priority: `/api/console/incidents/${encodeURIComponent(state.selectedId)}/priority`,
      undo: `/api/console/incidents/actions/${encodeURIComponent(form.dataset.id)}/undo`,
    };
    try {
      const saved = await post(paths[kind], body);
      state.status = tx(kind === 'split' ? 'splitSaved' : kind === 'merge' ? 'mergeSaved' : kind === 'undo' ? 'undoSaved' : 'prioritySaved', { entry: saved.ledger_entry_id });
      state.form = null; state.selectedId = saved.incident_id || state.selectedId;
      selfWrite = true;
      document.dispatchEvent(new CustomEvent('nabiz:ledger-changed'));
      await load();
      selfWrite = false;
      section.querySelector('#incident-detail-title')?.focus();
    } catch (error) { state.error = tx('saveError', { message: error.message || '' }); render(); }
  });
  document.addEventListener('nabiz:decided', () => { void load({ keepForm: true }); });
  document.addEventListener('nabiz:ledger-changed', () => { if (!selfWrite) void load({ keepForm: true }); });
  onLang(() => render());
  state.status = tx('loading');
  const attachDecision = async () => {
    if (MOCK) return;
    const host = document.getElementById('decision-body');
    if (!host) return;
    const existing = host.querySelector('[data-incident-link]');
    const id = host.querySelector('.decision-meta span')?.textContent.trim();
    let report = null;
    if (id) {
      for (const item of state.data.items || []) {
        try {
          const detail = item.id === state.selectedId && state.detail
            ? state.detail : await get(`/api/console/incidents/${encodeURIComponent(item.id)}`);
          if (detail.members?.reports?.some((member) => member.signal_id === id)) { report = item; break; }
        } catch (error) { /* A missing detail does not block the decision card. */ }
      }
    }
    const triage = host.querySelector('#report-triage');
    if (!report || !triage) { existing?.remove(); return; }
    if (existing?.dataset.incidentLink === report.id) return;
    existing?.remove();
    const link = document.createElement('p'); link.dataset.incidentLink = report.id;
    link.innerHTML = `${tx('incidentLink', { station: report.title_station, reports: report.members.reports, photos: report.members.photos })} `
      + `<button class="btn btn-quiet" type="button">${tx('openIncident')}</button>`;
    link.querySelector('button').addEventListener('click', async () => {
      section.scrollIntoView({ block: 'start' }); await selectIncident(report.id, true);
    });
    triage.after(link);
  };
  if (typeof MutationObserver === 'function' && !MOCK) {
    const observer = new MutationObserver(() => { void attachDecision(); });
    const decision = document.getElementById('decision-body');
    if (decision) observer.observe(decision, { childList: true, subtree: true });
    document.addEventListener('nabiz:decided', () => { void attachDecision(); });
  }
  void load().then(attachDecision);
}
if (typeof document !== 'undefined') mount(); export { FALLBACK, I18N_KEYS };
