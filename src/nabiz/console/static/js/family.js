import { MOCK, get, post, del } from './api.js';
import { readAccount } from './identity.js';
import { readStore } from './my_stops.js';
import { onLang, t } from './i18n_text.js';
import { esc } from './format.js';
import { familyMarkup, normalizeCode } from './family_view.js';

const FAMILY_PATH = '/api/account/family';
let root = null;
let data = null;
let loaded = false;
let loading = false;
let activeToken = '';
function addStylesheet() {
  if (document.querySelector('link[data-family-style]')) return;
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = '/css/family.css';
  link.dataset.familyStyle = 'true';
  document.head.append(link);
}
function makeRoot() {
  const details = document.createElement('details');
  details.className = 'more account-detail';
  details.id = 'aile-detail';
  details.innerHTML = '<summary><h2 id="family-title" tabindex="-1">' + esc(t('ui.family.title', 'Aile')) + '</h2></summary>'
    + '<section id="aile" aria-labelledby="family-title"><p class="status-line" id="family-status" role="status"></p>'
    + '<div id="family-body"></div></section>';
  const account = document.getElementById('hesabim');
  const follow = account && account.querySelector('#takip');
  const anchor = follow && follow.closest('details');
  if (anchor && anchor.parentElement) anchor.after(details);
  else account.append(details);
  return details;
}
function setStatus(message, serverText = false) {
  const status = root && root.querySelector('#family-status');
  if (!status) return;
  status.replaceChildren();
  if (serverText) {
    const span = document.createElement('span');
    span.lang = 'tr';
    span.textContent = message || '';
    status.append(span);
  } else status.textContent = message || '';
}

function preserveState(body) {
  const fields = Array.from(body.querySelectorAll('input, textarea, select')).map((field) => ({
    id: field.id, name: field.name, index: Array.from(body.querySelectorAll('[name="' + field.name + '"]')).indexOf(field),
    value: field.value, checked: field.type === 'checkbox' ? field.checked : undefined,
  }));
  const active = body.contains(document.activeElement) ? document.activeElement : null;
  return {
    fields,
    open: Array.from(body.querySelectorAll('details')).map((item) => item.open),
    activeId: active && active.id,
    activeName: active && active.name,
    activeIndex: active && active.name
      ? Array.from(body.querySelectorAll('[name="' + active.name + '"]')).indexOf(active) : -1,
    start: active && typeof active.selectionStart === 'number' ? active.selectionStart : null,
    end: active && typeof active.selectionEnd === 'number' ? active.selectionEnd : null,
  };
}
function restoreState(body, snapshot) {
  const allFields = Array.from(body.querySelectorAll('input, textarea, select'));
  snapshot.fields.forEach((saved, index) => {
    const target = saved.id ? body.querySelector('#' + CSS.escape(saved.id))
      : saved.name ? Array.from(body.querySelectorAll('[name="' + saved.name + '"]'))[saved.index] : allFields[index];
    if (!target) return;
    if (saved.checked !== undefined) target.checked = saved.checked;
    else target.value = saved.value;
  });
  Array.from(body.querySelectorAll('details')).forEach((item, index) => { item.open = Boolean(snapshot.open[index]); });
  const active = snapshot.activeId ? body.querySelector('#' + CSS.escape(snapshot.activeId))
    : snapshot.activeName ? Array.from(body.querySelectorAll('[name="' + snapshot.activeName + '"]'))[snapshot.activeIndex] : null;
  if (active) {
    active.focus();
    if (snapshot.start !== null && typeof active.setSelectionRange === 'function') {
      active.setSelectionRange(snapshot.start, snapshot.end);
    }
  }
}
function render(next, options = {}) {
  const body = root && root.querySelector('#family-body');
  if (!body) return;
  const snapshot = options.preserve ? preserveState(body) : null;
  data = next;
  body.innerHTML = familyMarkup(next, readStore(), options.newMemberIds || []);
  const status = root && root.querySelector('#family-status');
  if (status) status.setAttribute('aria-busy', 'false');
  if (snapshot) restoreState(body, snapshot);
  if (options.message) setStatus(options.message, true);
  else if (!options.preserveStatus) setStatus('');
  if (options.focus) focusDestination();
}
function focusDestination() {
  (root?.querySelector('#family-body .btn-primary') || root?.querySelector('#family-title'))?.focus();
}
function showError(error) {
  if (error && error.status === 401) {
    removeRoot();
    return;
  }
  const status = root && root.querySelector('#family-status');
  if (!status) return;
  status.replaceChildren();
  const message = document.createElement('span');
  message.lang = 'tr';
  message.textContent = error && error.message ? error.message : '';
  status.append(message, document.createTextNode(' '));
  const retry = document.createElement('button');
  retry.type = 'button';
  retry.className = 'btn btn-quiet';
  retry.dataset.familyAction = 'retry';
  retry.textContent = t('ui.family.retry', 'Yeniden dene');
  status.append(retry);
  status.setAttribute('aria-busy', 'false');
}

async function loadFamily(force = false) {
  if (!root || loading || (!force && loaded && data)) return;
  loading = true;
  const status = root && root.querySelector('#family-status');
  if (status) status.setAttribute('aria-busy', 'true');
  setStatus(t('ui.family.loading', 'Aile bilgisi yükleniyor.'));
  try {
    const result = await get(FAMILY_PATH);
    loaded = true;
    render(result);
  } catch (error) {
    showError(error);
  } finally {
    loading = false;
  }
}
function sendChanged() {
  document.dispatchEvent(new CustomEvent('nabiz:family-changed', { detail: { state: data && data.state } }));
}
function consentAllowed(form) {
  const consent = form.querySelector('input[name="consent"]');
  const error = form.querySelector('.fam-consent-error');
  if (consent && consent.checked) {
    if (error) error.hidden = true;
    return true;
  }
  if (error) error.hidden = false;
  consent?.focus();
  return false;
}

async function runAction(action, element) {
  if (action === 'retry') return loadFamily(true);
  if (action === 'copy') {
    try {
      await navigator.clipboard.writeText(data.family.code.display);
      setStatus(t('ui.family.copied', 'Aile kodu kopyalandı.'));
    } catch {
      setStatus(t('ui.family.copy_failed', 'Kopyalanamadı; kodu elle seçip kopyalayın.'));
    }
    return;
  }
  const requestId = encodeURIComponent(element.dataset.requestId || '');
  const memberId = encodeURIComponent(element.dataset.memberId || '');
  const routes = {
    renew: [FAMILY_PATH + '/code/renew', 'post'], cancel: [FAMILY_PATH + '/join', 'del'],
    approve: [FAMILY_PATH + '/requests/' + requestId + '/approve', 'post'],
    reject: [FAMILY_PATH + '/requests/' + requestId + '/reject', 'post'],
    remove: [FAMILY_PATH + '/members/' + memberId, 'del'], leave: [FAMILY_PATH + '/leave', 'post'],
  };
  const [path, method] = routes[action] || ['', ''];
  if (!path || loading) return;
  loading = true;
  element.setAttribute('aria-busy', 'true');
  element.setAttribute('aria-disabled', 'true');
  const oldIds = new Set((data && data.family && data.family.members || []).map((member) => member.id));
  try {
    const result = method === 'del' ? await del(path) : await post(path, {});
    const newMemberIds = (result.family && result.family.members || [])
      .filter((member) => !oldIds.has(member.id)).map((member) => member.id);
    loaded = true;
    render(result, { message: result.message, focus: true, newMemberIds });
    sendChanged();
  } catch (error) {
    showError(error);
  } finally {
    loading = false;
  }
}

async function submitForm(form) {
  if (loading) return;
  const values = new FormData(form);
  let path = '';
  let payload = {};
  if (form.matches('[data-family-create]')) {
    if (!consentAllowed(form)) return;
    path = FAMILY_PATH + '/code';
    payload = { display_name: values.get('display_name'), consent: true };
  } else if (form.matches('[data-family-join]')) {
    if (!consentAllowed(form)) return;
    const code = normalizeCode(values.get('code'));
    if (!code) {
      const field = form.elements.code;
      const error = form.querySelector('.fam-code-error');
      if (error) error.hidden = false;
      field?.focus();
      return;
    }
    const error = form.querySelector('.fam-code-error');
    if (error) error.hidden = true;
    path = FAMILY_PATH + '/join';
    payload = { code, display_name: values.get('display_name'), consent: true };
  } else if (form.matches('[data-family-shares]')) {
    path = FAMILY_PATH + '/shares';
    payload = {
      follow_ids: Array.from(form.querySelectorAll('input[name="follow_ids"]:checked')).map((input) => input.value),
      stops: Array.from(form.querySelectorAll('input[name="stops"]:checked'))
        .map((input) => ({ line: input.dataset.line, stop: input.dataset.stop })),
    };
  }
  if (!path) return;
  loading = true;
  const submit = form.querySelector('button[type="submit"]');
  if (submit) submit.setAttribute('aria-busy', 'true');
  try {
    const result = await post(path, payload);
    loaded = true;
    render(result, { message: result.message, focus: true });
    sendChanged();
  } catch (error) {
    showError(error);
  } finally {
    loading = false;
  }
}

function wireDetails(details) {
  details.addEventListener('toggle', () => {
    if (details.open) loadFamily();
  });
  details.addEventListener('click', (event) => {
    const button = event.target.closest('[data-family-action]');
    if (!button || !details.contains(button)) return;
    event.preventDefault();
    runAction(button.dataset.familyAction, button);
  });
  details.addEventListener('submit', (event) => {
    const form = event.target.closest('form[data-family-create], form[data-family-join], form[data-family-shares]');
    if (!form) return;
    event.preventDefault();
    submitForm(form);
  });
}
function install() {
  const account = readAccount();
  if (!account) {
    removeRoot();
    return;
  }
  if (root && activeToken === account.token) return;
  removeRoot();
  activeToken = account.token;
  addStylesheet();
  const host = document.getElementById('hesabim');
  if (!host) return;
  root = makeRoot();
  wireDetails(root);
  if (window.location.hash === '#aile') {
    root.open = true;
    loadFamily();
  }
}
function removeRoot() {
  root?.remove();
  root = null;
  data = null;
  loaded = false;
  activeToken = '';
}
if (typeof document !== 'undefined') {
  const boot = () => {
    if (MOCK) return;
    install();
    document.addEventListener('nabiz:account-changed', install);
    window.addEventListener('hashchange', () => {
      if (window.location.hash === '#aile' && root) {
        root.open = true;
        loadFamily();
      }
    });
    onLang(() => {
      if (!root) return;
      root.querySelector('#family-title').textContent = t('ui.family.title', 'Aile');
      if (data) render(data, { preserve: true, preserveStatus: true });
      else if (root.open) loadFamily();
    });
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true }); else boot();
}
