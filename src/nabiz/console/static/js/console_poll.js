/* A self-mounting operator panel for drafting, approving and closing a citizen poll. */

import { MOCK, get, post } from './api.js';
import { clock, dateTime, esc } from './format.js';
import { loadCatalogs, onLang, t } from './i18n_text.js';
import { cardMarkup, resultsMarkup } from './poll_view.js';

const ANCHORS = [['#polls-mount', 'afterend'], ['#citizen-requests', 'afterend'], ['#day', 'afterend']];
const POLL_MS = 20_000;
const POLL_STYLESHEET = '/css/poll.css';
const CONSOLE_STYLESHEET = '/css/console_poll.css';

function addStylesheet(doc, href) {
  if (doc.head.querySelector(`link[href="${href}"]`)) return;
  const link = doc.createElement('link');
  link.rel = 'stylesheet';
  link.href = href;
  link.id = href === POLL_STYLESHEET ? 'poll-preview-stylesheet' : 'poll-console-stylesheet';
  doc.head.append(link);
}

function dayInIstanbul(offset = 0) {
  const parts = new Intl.DateTimeFormat('en', {
    timeZone: 'Europe/Istanbul', year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(new Date());
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  const date = new Date(Date.UTC(Number(values.year), Number(values.month) - 1, Number(values.day) + offset));
  return date.toISOString().slice(0, 10);
}

function optionFields(options = ['', '']) {
  return options.map((value, index) => `<div class="poll-console-option"><label for="poll-option-${index + 1}">`
    + `${esc(t('ui.pollc.option_number', 'Seçenek {number}', { number: index + 1 }))}</label>`
    + `<input id="poll-option-${index + 1}" name="option" maxlength="40" value="${esc(value)}" required>`
    + `${index > 1 ? `<button type="button" class="btn btn-quiet" data-op="remove-option" data-index="${index}">${esc(t('ui.pollc.remove_option', 'Kaldır'))}</button>` : ''}</div>`
  ).join('');
}

function sectionHead() {
  return `<div class="section-head"><h2 id="poll-console-title">${esc(t('ui.pollc.title', 'İstanbul\'a Sor'))}</h2></div>`
    + `<p class="section-note">${esc(t('ui.pollc.description', 'Vatandaşa tek soruluk kısa anket. Yayımlamadan önce onayınız gerekir; yayın ve bitiş karar defterine yazılır.'))}</p>`
    + `<p class="status-line" role="status" aria-live="polite" data-pollc-status></p>`;
}

function pollForm(districts, values = {}) {
  const options = Array.isArray(values.options) ? values.options.map((item) => item.label || '') : ['', ''];
  const closeDate = values.closes_on || dayInIstanbul(1);
  const target = values.target || { kind: 'all', district: null };
  const districtOptions = districts.map((district) => `<option value="${esc(district)}"${target.district === district ? ' selected' : ''}>${esc(district)}</option>`).join('');
  return `<details class="poll-new" data-pollc-details${values.question ? ' open' : ''}><summary>${esc(t('ui.pollc.new', 'Yeni anket'))}</summary>`
    + `<form class="poll-create" data-poll-create><label for="poll-question">${esc(t('ui.pollc.question', 'Soru'))}</label>`
    + `<textarea id="poll-question" name="question" rows="3" maxlength="140" required aria-describedby="poll-question-hint poll-question-error">${esc(values.question || '')}</textarea>`
    + `<p class="field-hint" id="poll-question-hint">${esc(t('ui.pollc.question_hint', 'Kişi adı, telefon ya da adres yazmayın.'))}</p>`
    + `<p class="poll-character-count" data-pollc-count>${esc(t('ui.pollc.remaining', 'Kalan {count} karakter', { count: Math.max(0, 140 - (values.question || '').length) }))}</p>`
    + `<p class="field-error" id="poll-question-error" data-error="question" hidden></p>`
    + `<fieldset class="poll-console-options" aria-describedby="poll-options-error"><legend>${esc(t('ui.pollc.options', 'Seçenekler'))}</legend>`
    + `<div data-pollc-options>${optionFields(options.length ? options : ['', ''])}</div>`
    + `<p class="field-error" id="poll-options-error" data-error="options" hidden></p>`
    + `<button type="button" class="btn btn-quiet" data-op="add-option">${esc(t('ui.pollc.add_option', 'Seçenek ekle'))}</button></fieldset>`
    + `<label for="poll-closes">${esc(t('ui.pollc.closes_on', 'Bitiş günü'))}</label>`
    + `<input id="poll-closes" name="closes_on" type="date" min="${dayInIstanbul()}" max="${dayInIstanbul(14)}" value="${esc(closeDate)}" required aria-describedby="poll-closes-error">`
    + `<p class="field-error" id="poll-closes-error" data-error="closes_on" hidden></p>`
    + `<label for="poll-target">${esc(t('ui.pollc.target', 'Kime'))}</label>`
    + `<select id="poll-target" name="target" aria-describedby="poll-target-error"><option value="all"${target.kind === 'all' ? ' selected' : ''}>${esc(t('ui.pollc.all', 'Tüm vatandaşlar'))}</option>`
    + `<option value="district"${target.kind === 'district' ? ' selected' : ''}>${esc(t('ui.pollc.district', 'İlçe'))}</option></select>`
    + `<select name="district" data-pollc-district${target.kind === 'district' ? '' : ' hidden'} aria-label="${esc(t('ui.pollc.district', 'İlçe'))}" aria-describedby="poll-target-error"><option value="">${esc(t('ui.pollc.choose_district', 'İlçe seçin'))}</option>${districtOptions}</select>`
    + `<p class="field-error" id="poll-target-error" data-error="target" hidden></p>`
    + `<div class="poll-console-actions"><button type="submit" class="btn" data-op="preview">${esc(t('ui.pollc.preview', 'Önizle'))}</button></div></form></details>`;
}

function targetLabel(target) {
  return target.kind === 'district'
    ? t('ui.pollc.target_district', '{district} ilçesi', { district: target.district })
    : t('ui.pollc.all', 'Tüm vatandaşlar');
}

function draftMarkup(draft) {
  return `<div class="poll-console-draft"><h3>${esc(t('ui.pollc.preview_heading', 'Vatandaş böyle görecek'))}</h3>`
    + cardMarkup(draft, { preview: true })
    + `<div class="poll-console-actions"><button type="button" class="btn" data-op="open-publish">${esc(t('ui.pollc.publish', 'Yayımla'))}</button>`
    + `<button type="button" class="btn btn-quiet" data-op="edit-draft">${esc(t('ui.pollc.edit', 'Taslağı düzenle'))}</button></div>`
    + `<dialog class="poll-dialog" data-pollc-publish aria-labelledby="poll-publish-title">`
    + `<h3 id="poll-publish-title">${esc(t('ui.pollc.publish_title', 'Anketi yayımla'))}</h3>`
    + `<p>${esc(t('ui.pollc.publish_text', 'Bu soru vatandaş sayfasında {date} saatine kadar görünecek. Yayın karar defterine adınızla yazılır.', { date: dateTime(draft.closes_at) }))}</p>`
    + `<label class="poll-confirm"><input type="checkbox" data-pollc-confirm>${esc(t('ui.pollc.confirm', 'Soruyu ve seçenekleri okudum; kişisel veri yok.'))}</label>`
    + `<p class="field-error" data-pollc-confirm-error hidden></p><div class="poll-console-actions">`
    + `<button type="button" class="btn btn-primary" data-op="publish-confirm" aria-disabled="true">${esc(t('ui.pollc.publish', 'Yayımla'))}</button>`
    + `<button type="button" class="btn btn-quiet" data-op="cancel-dialog">${esc(t('ui.pollc.cancel', 'Vazgeç'))}</button></div></dialog></div>`;
}

function activeMarkup(active) {
  const count = active.results.total;
  const updated = clock(active.read_at);
  return `<div class="poll-console-active"><p class="poll-console-meta">${esc(t('ui.pollc.active_line', 'Yayında · Kime: {target} · Bitiş: {date}', { target: targetLabel(active.target), date: dateTime(active.closes_at) }))}</p>`
    + `<p class="poll-results-disclaimer">${esc(t('ui.pollc.results_disclaimer', 'Bu sonuçlar temsili değildir; yalnız Nabız\'da oy verenleri gösterir.'))}</p>`
    + resultsMarkup(active.results)
    + `<p class="poll-console-meta">${esc(t('ui.pollc.total_line', 'Toplam {count} cevap · son okuma {time}', { count, time: updated }))}</p>`
    + `<button type="button" class="btn" data-op="open-close">${esc(t('ui.pollc.close', 'Anketi bitir'))}</button>`
    + `<dialog class="poll-dialog" data-pollc-close aria-labelledby="poll-close-title">`
    + `<h3 id="poll-close-title">${esc(t('ui.pollc.close_title', 'Anketi bitir'))}</h3>`
    + `<label for="poll-close-reason">${esc(t('ui.pollc.reason', 'Gerekçe'))}</label>`
    + `<textarea id="poll-close-reason" maxlength="280" required aria-describedby="poll-close-hint poll-close-error"></textarea>`
    + `<p class="field-hint" id="poll-close-hint">${esc(t('ui.pollc.reason_hint', 'Deftere yazılır, vatandaşa gösterilmez. Kişi adı yazmayın.'))}</p>`
    + `<p class="field-error" id="poll-close-error" data-pollc-close-error hidden></p><div class="poll-console-actions">`
    + `<button type="button" class="btn btn-primary" data-op="close-confirm">${esc(t('ui.pollc.close', 'Anketi bitir'))}</button>`
    + `<button type="button" class="btn btn-quiet" data-op="cancel-dialog">${esc(t('ui.pollc.cancel', 'Vazgeç'))}</button></div></dialog></div>`;
}

function lastClosedMarkup(poll) {
  const audit = [...poll.audit].reverse().find((entry) => entry.act === 'closed');
  const closure = audit?.how === 'time'
    ? t('ui.pollc.closed_time', 'Süre doldu.')
    : t('ui.pollc.closed_operator', 'Operatör kararıyla bitti.');
  return `<details class="poll-last-closed"><summary>${esc(t('ui.pollc.last_closed', 'Son biten anket'))}</summary>`
    + `<p class="poll-console-meta">${esc(closure)}</p><p class="poll-results-disclaimer">`
    + `${esc(t('ui.pollc.results_disclaimer', 'Bu sonuçlar temsili değildir; yalnız Nabız\'da oy verenleri gösterir.'))}</p>`
    + `<p class="poll-console-meta">${esc(poll.question)}</p>${resultsMarkup(poll.results)}</details>`;
}

function showProblem(section, field, message) {
  section.querySelectorAll('[data-error]').forEach((node) => { node.hidden = true; node.textContent = ''; });
  const target = section.querySelector(`[data-error="${field}"]`);
  if (!target) return;
  target.textContent = message;
  target.hidden = false;
  const input = field === 'question' ? section.querySelector('#poll-question')
    : field === 'options' ? section.querySelector('#poll-option-1')
      : field === 'closes_on' ? section.querySelector('#poll-closes') : section.querySelector('#poll-target');
  input?.focus();
}

function syncOptionControls(section) {
  const count = section.querySelectorAll('[data-pollc-options] input[name="option"]').length;
  const add = section.querySelector('[data-op="add-option"]');
  if (add) add.hidden = count >= 5;
}

export async function mountPollConsole(doc) {
  let anchor = null;
  for (const [selector, position] of ANCHORS) {
    const element = doc.querySelector(selector);
    if (element) { anchor = { element, position }; break; }
  }
  if (!anchor || MOCK) return null;
  const location = doc.defaultView.location || globalThis.location || { search: '' };
  if (new URLSearchParams(location.search).get('lang') === 'en') await loadCatalogs('en');
  addStylesheet(doc, CONSOLE_STYLESHEET);
  addStylesheet(doc, POLL_STYLESHEET);
  anchor.element.insertAdjacentHTML(anchor.position, `<section id="istanbula-sor-konsol" class="poll-console" aria-labelledby="poll-console-title"></section>`);
  const section = doc.getElementById('istanbula-sor-konsol');
  if (!section) return null;
  let current = null;
  let pollTimer = null;
  let dialogTrigger = null;
  let refreshing = false;
  let lastSnapshot = '';

  function render(data, force = false) {
    if (section.querySelector('dialog[open]')) return;
    current = data;
    const snapshot = JSON.stringify({ draft: data.draft, active: data.active });
    if (!force && snapshot === lastSnapshot) return;
    lastSnapshot = snapshot;
    const closed = data.last_closed ? lastClosedMarkup(data.last_closed) : '';
    const content = data.active
      ? activeMarkup({ ...data.active, read_at: data.read_at })
      : data.draft ? draftMarkup(data.draft) + closed : pollForm(data.districts) + closed;
    section.innerHTML = sectionHead() + content;
    const targetSelect = section.querySelector('#poll-target');
    targetSelect?.addEventListener('change', () => {
      section.querySelector('[data-pollc-district]').hidden = targetSelect.value !== 'district';
    });
    const question = section.querySelector('#poll-question');
    if (question) question.addEventListener('input', () => {
      section.querySelector('[data-pollc-count]').textContent = t('ui.pollc.remaining', 'Kalan {count} karakter', { count: Math.max(0, 140 - question.value.length) });
    });
    const check = section.querySelector('[data-pollc-confirm]');
    if (check) check.addEventListener('change', () => {
      section.querySelector('[data-op="publish-confirm"]').setAttribute('aria-disabled', check.checked ? 'false' : 'true');
    });
    syncOptionControls(section);
  }

  async function refresh(force = false) {
    if (refreshing || doc.hidden) return;
    refreshing = true;
    try {
      const data = await get('/api/console/polls');
      render(data, force);
      if (data.active && !pollTimer) pollTimer = setInterval(() => { if (!doc.hidden) void refresh(); }, POLL_MS);
      if (!data.active && pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    } catch (error) {
      section.querySelector('[data-pollc-status]').textContent = error.message || t('ui.pollc.load_error', 'Anket bilgisi alınamadı. Yeniden deneyin.');
    } finally { refreshing = false; }
  }

  function announceLedger() {
    const view = doc.defaultView;
    const EventType = view.CustomEvent || globalThis.CustomEvent;
    if (view.dispatchEvent && EventType) view.dispatchEvent(new EventType('nabiz:ledger-changed'));
  }

  async function createPreview(form) {
    const options = Array.from(form.querySelectorAll('input[name="option"]')).map((input) => input.value);
    const target = form.querySelector('#poll-target').value;
    const payload = {
      question: form.querySelector('#poll-question').value,
      options,
      closes_on: form.querySelector('#poll-closes').value,
      target: { kind: target, district: target === 'district' ? form.querySelector('[data-pollc-district]').value : null },
    };
    try {
      const answer = await post('/api/console/polls', payload);
      section.querySelector('[data-pollc-status]').textContent = t('ui.pollc.draft_saved', 'Önizleme hazır. Soru ve seçenekleri kontrol edin.');
      await refresh(true);
    } catch (error) {
      const message = error.message || t('ui.pollc.load_error', 'Anket bilgisi alınamadı. Yeniden deneyin.');
      const field = /seçenek|aynı olamaz/i.test(message) ? 'options'
        : /bitiş günü/i.test(message) ? 'closes_on'
          : /ilçe/i.test(message) ? 'target' : 'question';
      showProblem(section, field, message);
    }
  }

  function openDialog(selector, trigger) {
    const dialog = section.querySelector(selector);
    if (!dialog || typeof dialog.showModal !== 'function') return;
    dialogTrigger = trigger;
    dialog.addEventListener('close', () => { dialogTrigger?.focus(); }, { once: true });
    dialog.showModal();
    dialog.querySelector('input, textarea, button')?.focus();
  }

  section.addEventListener('submit', (event) => {
    if (!event.target.matches('[data-poll-create]')) return;
    event.preventDefault();
    void createPreview(event.target);
  });

  section.addEventListener('click', async (event) => {
    const button = event.target.closest('[data-op]');
    if (!button) return;
    const operation = button.dataset.op;
    if (operation === 'add-option') {
      const fields = section.querySelector('[data-pollc-options]');
      const values = Array.from(fields.querySelectorAll('input')).map((input) => input.value);
      if (values.length < 5) {
        fields.innerHTML = optionFields([...values, '']);
        section.querySelector(`#poll-option-${values.length + 1}`)?.focus();
        syncOptionControls(section);
      }
    } else if (operation === 'remove-option') {
      const fields = section.querySelector('[data-pollc-options]');
      const values = Array.from(fields.querySelectorAll('input')).map((input) => input.value);
      if (values.length > 2) {
        values.splice(Number(button.dataset.index), 1);
        fields.innerHTML = optionFields(values);
        syncOptionControls(section);
      }
    } else if (operation === 'edit-draft') {
      const details = pollForm(current.districts, current.draft);
      section.querySelector('.poll-console-draft').insertAdjacentHTML('beforebegin', details);
      button.closest('.poll-console-draft').remove();
      section.querySelector('[data-pollc-details]')?.querySelector('#poll-question')?.focus();
    } else if (operation === 'open-publish') openDialog('[data-pollc-publish]', button);
    else if (operation === 'open-close') openDialog('[data-pollc-close]', button);
    else if (operation === 'cancel-dialog') button.closest('dialog')?.close();
    else if (operation === 'publish-confirm') {
      const dialog = button.closest('dialog');
      const check = dialog.querySelector('[data-pollc-confirm]');
      const error = dialog.querySelector('[data-pollc-confirm-error]');
      if (!check.checked) {
        error.textContent = t('ui.pollc.confirm_required', 'Önce onay kutusunu işaretleyin.');
        error.hidden = false;
        check.focus();
        return;
      }
      button.textContent = t('ui.pollc.publishing', 'Yayımlanıyor');
      button.setAttribute('aria-busy', 'true');
      button.setAttribute('aria-disabled', 'true');
      try {
        await post(`/api/console/polls/${encodeURIComponent(current.draft.id)}/publish`, { confirm: true, digest: current.draft.digest });
        dialog.close();
        announceLedger();
        await refresh(true);
        section.querySelector('[data-pollc-status]').textContent = t('ui.pollc.published', 'Yayımlandı: karar deftere yazıldı.');
        section.querySelector('[data-pollc-status]').setAttribute('tabindex', '-1');
        section.querySelector('[data-pollc-status]').focus();
      } catch (error) {
        error.message && (section.querySelector('[data-pollc-status]').textContent = error.message);
        button.textContent = t('ui.pollc.publish', 'Yayımla');
        button.removeAttribute('aria-busy');
        button.setAttribute('aria-disabled', check.checked ? 'false' : 'true');
      }
    } else if (operation === 'close-confirm') {
      const dialog = button.closest('dialog');
      const reason = dialog.querySelector('#poll-close-reason');
      const error = dialog.querySelector('[data-pollc-close-error]');
      if (!reason.value.trim()) {
        error.textContent = t('ui.pollc.reason_required', 'Anketi bitirmek için gerekçe yazın.');
        error.hidden = false;
        reason.focus();
        return;
      }
      button.textContent = t('ui.pollc.closing', 'Bitiriliyor');
      button.setAttribute('aria-busy', 'true');
      button.setAttribute('aria-disabled', 'true');
      try {
        await post(`/api/console/polls/${encodeURIComponent(current.active.id)}/close`, { reason: reason.value });
        dialog.close();
        announceLedger();
        await refresh(true);
        section.querySelector('[data-pollc-status]').textContent = t('ui.pollc.closed', 'Anket bitti; son sonuçlar deftere yazıldı.');
        section.querySelector('[data-pollc-status]').setAttribute('tabindex', '-1');
        section.querySelector('[data-pollc-status]').focus();
      } catch (error) {
        section.querySelector('[data-pollc-status]').textContent = error.message || t('ui.pollc.load_error', 'Anket bilgisi alınamadı. Yeniden deneyin.');
        button.textContent = t('ui.pollc.close', 'Anketi bitir');
        button.removeAttribute('aria-busy');
        button.removeAttribute('aria-disabled');
      }
    }
  });

  onLang(() => { if (current) render(current, true); });
  if (doc.addEventListener) doc.addEventListener('visibilitychange', () => { if (!doc.hidden) void refresh(true); });
  section.innerHTML = sectionHead();
  await refresh(true);
  return section;
}

if (typeof document !== 'undefined') void mountPollConsole(document);
