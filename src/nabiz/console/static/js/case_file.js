import { identityHeaders, readAccount } from './identity.js';
import { MOCK } from './api.js';
import { onLang, t } from './i18n_text.js';
import { STORE_KEY, caseMarkup } from './case_file_view.js';

function readLocal() {
  try {
    const value = JSON.parse(window.localStorage.getItem(STORE_KEY) || '{}');
    return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  } catch { return {}; }
}
function writeLocal(value) {
  try { window.localStorage.setItem(STORE_KEY, JSON.stringify(value)); return true; } catch { return false; }
}
function isoToday() {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Europe/Istanbul', year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(new Date()).map((part) => [part.type, part.value]));
  return `${parts.year}-${parts.month}-${parts.day}`;
}
function savedTime() { return new Intl.DateTimeFormat('tr-TR', { timeZone: 'Europe/Istanbul', hour: '2-digit', minute: '2-digit' }).format(new Date()); }

function mountCaseFile() {
  if (MOCK) return;
  const accountSection = document.querySelector('#hesabim');
  if (!accountSection || accountSection.querySelector('#is-dosyasi-detail')) return;
  const details = document.createElement('details');
  details.className = 'more account-detail'; details.id = 'is-dosyasi-detail';
  const summary = document.createElement('summary'), title = document.createElement('h2');
  title.id = 'case-title';
  const reminders = document.createElement('span');
  reminders.className = 'case-summary-reminders'; reminders.dataset.caseSummaryReminders = '';
  summary.append(title, reminders);
  const section = document.createElement('section');
  section.id = 'is-dosyasi';
  section.setAttribute('aria-labelledby', 'case-title');
  const content = document.createElement('div');
  content.dataset.caseContent = '';
  section.append(content);
  details.append(summary, section);
  const memory = accountSection.querySelector('#hafizam');
  const insertion = memory?.closest('details');
  if (insertion?.parentElement === accountSection) insertion.insertAdjacentElement('afterend', details);
  else accountSection.append(details);
  if (!document.querySelector('link[data-case-file-style]')) {
    const style = document.createElement('link');
    style.rel = 'stylesheet'; style.href = '/css/case_file.css'; style.dataset.caseFileStyle = '';
    document.head.append(style);
  }

  const state = { plans: [], consent: {}, file: null, reminders: [], screen: 'start', message: '', status: '', retry: null,
    busy: false, plansLoaded: false, openLoaded: false, drafts: {}, renderedScreen: '' };
  const host = content;
  const local = () => readLocal();
  const hasOwner = () => Boolean(local().key || readAccount());
  let ownerRevision = 0;

  function focusState() {
    const active = document.activeElement;
    if (!host.contains(active)) return null;
    return { kind: active.dataset.caseFocus || '', step: active.dataset.stepId || active.closest('[data-step-id]')?.dataset.stepId || '',
      answer: active.dataset.caseAnswer || '', name: active.name || '', value: active.value || '',
      start: typeof active.selectionStart === 'number' ? active.selectionStart : null, end: typeof active.selectionEnd === 'number' ? active.selectionEnd : null };
  }
  function rememberDrafts() {
    host.querySelectorAll('[data-case-note], [data-case-reminder]').forEach((form) => {
      const id = form.dataset.stepId;
      if (!id) return;
      state.drafts[id] = { ...(state.drafts[id] || {}),
        ...(form.elements.note ? { note: form.elements.note.value } : {}),
        ...(form.elements.ref_code ? { ref_code: form.elements.ref_code.value } : {}),
        ...(form.elements.remind_on ? { remind_on: form.elements.remind_on.value } : {}) };
    });
  }
  function rerenderPreserving() { rememberDrafts(); render(); }
  function displayFile() {
    if (!state.file) return null;
    const shown = JSON.parse(JSON.stringify(state.file));
    shown.steps.forEach((step) => Object.assign(step, state.drafts[step.step_id] || {}));
    shown.reminders = state.reminders.filter((item) => item.file_id === shown.id);
    return shown;
  }
  function render() {
    const current = focusState();
    const nextScreen = state.file && state.screen !== 'error' ? 'file' : state.screen;
    const openBefore = state.renderedScreen === nextScreen ? [...host.querySelectorAll('details.case-disclosure')].map((item) => item.open) : [];
    const justDone = state.file?.just_done_step_id || '';
    if (nextScreen === 'file') {
      host.innerHTML = caseMarkup({ screen: 'file', file: displayFile(), plan: state.file.plan, today: isoToday(), district: local().district || '' });
    } else {
      host.innerHTML = caseMarkup({ screen: nextScreen, plans: state.plans, consent: state.consent, message: state.message });
    }
    host.querySelectorAll('details.case-disclosure').forEach((item, index) => { item.open = Boolean(openBefore[index]); });
    state.renderedScreen = nextScreen;
    if (justDone) {
      state.file.just_done_step_id = '';
      window.setTimeout(() => host.querySelector(`[data-case-step="${justDone}"]`)?.classList.remove('case-just-done'), 240);
    }
    const status = host.querySelector('[data-case-status]');
    if (status) status.textContent = state.status;
    title.textContent = t('ui.case.title', 'İş dosyam');
    reminders.textContent = state.reminders.length ? t('ui.case.reminder_count', 'Bugün {count} hatırlatma', { count: state.reminders.length }) : '';
    if (current) restoreFocus(current);
  }
  function restoreFocus(saved) {
    const candidates = [...host.querySelectorAll('[data-case-focus]')];
    const target = candidates.find((item) => item.dataset.caseFocus === saved.kind
      && (item.dataset.stepId || item.closest('[data-step-id]')?.dataset.stepId || '') === saved.step
      && (item.dataset.caseAnswer || '') === saved.answer && (item.name || '') === saved.name)
      || candidates.find((item) => item.dataset.caseFocus === saved.kind);
    if (!target) return;
    target.focus({ preventScroll: true });
    if (saved.start !== null && typeof target.setSelectionRange === 'function') {
      try { target.setSelectionRange(saved.start, saved.end); } catch { /* date inputs have no text selection */ }
    }
  }
  function headers(extraKey = '') {
    const values = { ...identityHeaders('/api/account') };
    const key = readAccount() ? '' : (extraKey || local().key);
    if (key) values['X-Nabiz-Case'] = key;
    return values;
  }
  async function request(path, { method = 'GET', body, key = '' } = {}) {
    const requestHeaders = headers(key);
    const options = { method, headers: requestHeaders, cache: 'no-store' };
    if (body !== undefined) {
      options.headers = { ...requestHeaders, 'Content-Type': 'application/json' };
      options.body = JSON.stringify(body);
    }
    const response = await fetch(path, options), data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = Object.assign(new Error(data.message || t('ui.case.error', 'İş dosyası açılamadı. Yeniden deneyin.')),
        { status: response.status, code: data.error || 'request_failed' });
      throw error;
    }
    return data;
  }
  function signalChange(file) {
    document.dispatchEvent(new CustomEvent('nabiz:case-file-changed', { detail: { plan_id: file.plan_id, done: file.progress.done, total: file.progress.total } }));
  }
  function resetDrafts(file) {
    state.drafts = {};
    state.file = file;
    state.status = t('ui.case.saved_at', 'Kaydedildi · {time}', { time: savedTime() });
    if (file) signalChange(file);
  }
  function dueFor(file) {
    if (!file) return [];
    const today = isoToday();
    const steps = new Map(file.plan.steps.map((step) => [step.id, step.title]));
    return file.steps.filter((step) => step.remind_on && step.remind_on <= today && !step.done_at)
      .map((step) => ({ file_id: file.id, plan_id: file.plan_id, step_id: step.step_id, title: steps.get(step.step_id) || '', remind_on: step.remind_on }));
  }
  function updateStep(stepId, fields, after = () => {}) {
    const fileId = state.file?.id;
    if (!fileId) return;
    void run(() => request(`/api/case-file/${fileId}/step`, {
      method: 'POST', body: { step_id: stepId, ...fields },
    }), (data, isCurrent) => {
      if (!isCurrent()) return;
      resetDrafts(data.file); state.reminders = dueFor(data.file); after(data, isCurrent);
    });
  }
  async function run(action, after) {
    if (state.busy) return;
    const revision = ownerRevision;
    state.busy = true;
    const live = host.querySelector('[role="status"]');
    if (live) live.textContent = t('ui.case.saving', 'Kaydediliyor');
    try {
      const result = await action();
      if (revision !== ownerRevision) return;
      await after(result, () => revision === ownerRevision);
      if (revision !== ownerRevision) return;
      state.screen = state.file ? 'file' : 'start'; state.message = ''; state.retry = null;
      state.busy = false; render();
    } catch (error) {
      if (revision !== ownerRevision) return;
      state.busy = false;
      if (error.code === 'file_not_found' && local().key && !readAccount()) {
        writeLocal({ district: local().district || '' });
        state.file = null; state.openLoaded = false; state.screen = 'start'; state.status = '';
        await loadPlans();
        return;
      }
      if (error.status === 400 && state.file) { state.status = error.message; state.screen = 'file'; render(); return; }
      state.screen = 'error'; state.message = error.message; state.retry = () => run(action, after); render();
    }
  }
  async function loadScreen(path, options, after, retry, isCurrent = () => true) {
    state.screen = 'loading';
    render();
    try {
      const data = await request(path, options);
      if (!isCurrent()) return;
      await after(data);
      if (!isCurrent()) return;
      state.screen = state.file ? 'file' : 'start'; state.message = ''; state.retry = null;
      render();
    } catch (error) {
      if (!isCurrent()) return;
      state.screen = 'error'; state.message = error.message; state.retry = retry; render();
    }
  }
  async function loadPlans() {
    await loadScreen('/api/case-file/plans', {}, (data) => {
      state.plans = data.plans || []; state.consent = data.consent || {}; state.plansLoaded = true;
    }, loadPlans);
  }
  async function openFiles() {
    const revision = ++ownerRevision;
    await loadScreen('/api/case-file/open', { method: 'POST', body: {} }, async (data) => {
      const files = data.files || [];
      state.reminders = data.reminders || []; state.openLoaded = true; state.file = files[0] || null;
      if (!state.file && details.open && !state.plansLoaded) {
        const plans = await request('/api/case-file/plans');
        state.plans = plans.plans || []; state.consent = plans.consent || {}; state.plansLoaded = true;
      }
    }, openFiles, () => revision === ownerRevision);
  }
  async function ensureLoaded() {
    if (state.file || state.screen === 'error' || state.screen === 'loading') return;
    if (hasOwner() && !state.openLoaded) { await openFiles(); return; }
    if (!state.plansLoaded) await loadPlans();
  }

  details.addEventListener('toggle', () => {
    if (details.open) void ensureLoaded();
  });
  host.addEventListener('input', (event) => {
    const input = event.target;
    const stepId = input.dataset.stepId || input.closest('[data-step-id]')?.dataset.stepId;
    if (!stepId) return;
    const field = { note: 'note', ref_code: 'ref_code', remind_on: 'remind_on' }[input.name];
    if (field) state.drafts[stepId] = { ...(state.drafts[stepId] || {}), [field]: input.value };
  });
  host.addEventListener('change', (event) => {
    const input = event.target;
    if (input.matches('[data-case-district]')) {
      const next = { ...local(), district: input.value };
      writeLocal(next);
      rerenderPreserving();
      return;
    }
    if (input.matches('[data-case-done]')) {
      const stepId = input.dataset.caseDone, done = input.checked;
      updateStep(stepId, { done }, () => { state.file.just_done_step_id = done ? stepId : ''; });
    }
    if (input.matches('[data-case-answer]') && input.checked) {
      const fileId = state.file?.id, choice = input.dataset.caseAnswer;
      void run(() => request(`/api/case-file/${fileId}/answer`, { method: 'POST', body: { step_id: 'su', choice } }), (data) => {
        resetDrafts(data.file); state.reminders = dueFor(data.file);
      });
    }
  });
  host.addEventListener('submit', (event) => {
    const form = event.target;
    if (form.matches('[data-case-start]')) {
      event.preventDefault();
      const accepted = form.elements.consent.checked;
      const error = host.querySelector('[data-case-consent-error]');
      if (!accepted) { error.hidden = false; form.elements.consent.focus(); return; }
      const planId = form.elements.plan_id?.value;
      if (!planId) return;
      const key = local().key || '';
      void run(async () => {
        const data = await request('/api/case-file', { method: 'POST', body: { plan_id: planId, consent: true } });
        if (data.key) {
          const next = { ...local(), key: data.key };
          if (!writeLocal(next)) {
            try { await request(`/api/case-file/${data.file.id}`, { method: 'DELETE', key: data.key }); } catch { /* do not keep an unreachable file */ }
            throw new Error(t('ui.case.storage_error', 'Tarayıcı bu iş dosyasını saklayamadı. Hesapla yeniden deneyin.'));
          }
        } else if (key && !writeLocal({ ...local(), key })) {
          throw new Error(t('ui.case.storage_error', 'Tarayıcı verisi kaydedilemedi.'));
        }
        return data;
      }, (data) => {
        resetDrafts(data.file); state.reminders = dueFor(data.file); state.openLoaded = true;
      });
    } else if (form.matches('[data-case-note]')) {
      event.preventDefault();
      rememberDrafts();
      updateStep(form.dataset.stepId, { note: form.elements.note.value, ref_code: form.elements.ref_code.value });
    } else if (form.matches('[data-case-reminder]')) {
      event.preventDefault();
      rememberDrafts();
      updateStep(form.dataset.stepId, { remind_on: form.elements.remind_on.value });
    } else if (form.matches('[data-case-delete]')) {
      event.preventDefault();
      const fileId = state.file.id;
      void run(() => request(`/api/case-file/${fileId}`, { method: 'DELETE' }), async (_result, isCurrent) => {
        const removed = state.file;
        const data = await request('/api/case-file/open', { method: 'POST', body: {} });
        if (!isCurrent()) return;
        state.reminders = data.reminders || [];
        const files = data.files || [];
        state.file = files[0] || null;
        document.dispatchEvent(new CustomEvent('nabiz:case-file-changed', {
          detail: { plan_id: removed.plan_id, done: 0, total: removed.progress.total },
        }));
        if (!files.length && !readAccount()) {
          const saved = local(); delete saved.key; writeLocal(saved);
        }
        if (!files.length) {
          const plans = await request('/api/case-file/plans');
          if (!isCurrent()) return;
          state.plans = plans.plans || [];
          state.consent = plans.consent || {};
          state.plansLoaded = true;
        }
        state.drafts = {};
      });
    }
  });
  host.addEventListener('click', (event) => {
    if (event.target.closest('[data-case-retry]') && state.retry) { void state.retry(); return; }
    const clear = event.target.closest('[data-case-reminder-clear]');
    if (clear && state.file) {
      updateStep(clear.dataset.caseReminderClear, { remind_on: '' });
    }
  });

  document.addEventListener('nabiz:account-changed', () => {
    ownerRevision += 1; state.file = null; state.drafts = {}; state.reminders = []; state.screen = 'start'; state.openLoaded = false; state.busy = false;
    if (hasOwner()) void openFiles();
    else if (details.open) { state.file = null; state.plansLoaded = false; void loadPlans(); }
  });
  onLang(rerenderPreserving);
  window.addEventListener('hashchange', () => {
    if (window.location.hash === '#is-dosyasi') { details.open = true; void ensureLoaded(); }
  });
  if (window.location.hash === '#is-dosyasi') details.open = true;
  if (hasOwner()) void openFiles();
  else if (details.open) void loadPlans();
  render();
}

export { mountCaseFile, readLocal, writeLocal };

if (typeof document !== 'undefined') {
  const boot = () => mountCaseFile();
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true });
  else boot();
}
