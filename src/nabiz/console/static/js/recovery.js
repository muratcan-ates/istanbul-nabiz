/* Mounts the digital access guide without changing the page that owns its anchor. */

import { get, MOCK } from './api.js';
import { currentLang, onLang, t } from './i18n_text.js';
import { FALLBACK_CALL, STORAGE_KEY, back, choose, emptyState, parseStored, sectionMarkup, stepMarkup, trailMarkup } from './recovery_view.js';

const ANCHORS = [['#city-tools', 'beforeend'], ['#hesabim', 'beforebegin']], STYLESHEET = '/css/recovery.css', SECTION_ID = 'erisim-kurtar';
let flowsPromise = null;
const ACTION_TEXT = {
  back: () => t('ui.erisim.back', 'Geri'),
  restart: () => t('ui.erisim.restart', 'Baştan başla'),
  forget: () => t('ui.erisim.forget', 'Bu cihazdan sil'),
};

function safeStorage() {
  try { return globalThis.localStorage || null; } catch { return null; }
}
function addStylesheet(doc) {
  if (!doc.head || doc.head.querySelector(`link[href="${STYLESHEET}"]`)) return;
  const link = doc.createElement('link');
  link.rel = 'stylesheet';
  link.href = STYLESHEET;
  doc.head.append(link);
}
function readState(storage) {
  try { return storage ? storage.getItem(STORAGE_KEY) : null; } catch { return null; }
}
function writeState(storage, state) {
  if (!storage) return;
  try {
    storage.setItem(STORAGE_KEY, JSON.stringify({
      version: state.version, node: state.node, path: state.path, checks: state.checks, at: state.at,
    }));
  } catch { /* Private browsing can disable storage. */ }
}
function removeState(storage) {
  if (!storage) return;
  try { storage.removeItem(STORAGE_KEY); } catch { /* Private browsing can disable storage. */ }
}
function requestFlows() {
  if (!flowsPromise) flowsPromise = get('/api/erisim/flows');
  return flowsPromise;
}
function updateShell(section) {
  const title = section.querySelector('#erisim-title'), note = section.querySelector('.section-note');
  const safe = section.querySelector('.erisim-safe'), remember = section.querySelector('.erisim-remember-copy');
  const trail = section.querySelector('.erisim-trail'), foot = section.querySelector('.erisim-foot');
  if (title) title.textContent = t('ui.erisim.title', 'Uygulamaya ya da hesaba giremiyorum');
  if (note) note.textContent = t('ui.erisim.note', 'Denediğiniz adımları sırayla yazar; her adım kurumun resmî sayfasından. Hesabınıza erişemeyiz ve erişiminizi geri getiremeyiz.');
  if (safe && safe.lastChild) safe.lastChild.textContent = t('ui.erisim.no_secrets', 'Nabız şifre, doğrulama kodu, kart numarası ya da T.C. kimlik numarası istemez. Bu bölümde bunları yazacağınız bir alan yok.');
  if (remember) remember.textContent = t('ui.erisim.remember', 'Adımlarımı bu cihazda hatırla (sunucuya gitmez, 30 gün)');
  if (trail) trail.setAttribute('aria-label', t('ui.erisim.trail', 'Yanıtlarınız'));
  if (foot) foot.textContent = t('ui.culture.disclaimer', 'Resmî İBB hizmeti değildir.');
  for (const action of Object.keys(ACTION_TEXT)) {
    const button = section.querySelector(`[data-erisim="${action}"]`);
    if (button) button.textContent = ACTION_TEXT[action]();
  }
}

function activeTarget(section, doc) {
  const active = doc.activeElement;
  if (!section.contains(active)) return null;
  if (active.id) return { id: active.id };
  if (active.dataset?.erisimAnswer) return { answer: active.dataset.erisimAnswer };
  if (active.dataset?.erisim) return { action: active.dataset.erisim };
  return { question: true };
}

function restoreTarget(section, target) {
  if (!target) return;
  const selector = target.id ? `#${target.id}` : target.answer ? `[data-erisim-answer="${target.answer}"]`
    : target.action ? `[data-erisim="${target.action}"]` : target.question ? '#erisim-q' : '';
  const element = selector && section.querySelector(selector);
  if (element && typeof element.focus === 'function') element.focus();
}

function mountRecovery(doc, storage) {
  if (MOCK || !doc) return null;
  const anchor = ANCHORS.map(([selector, position]) => ({ node: doc.querySelector(selector), position })).find((item) => item.node);
  if (!anchor) return null;
  addStylesheet(doc);
  const existing = doc.getElementById(SECTION_ID);
  if (existing) return existing;
  const stateStore = storage === undefined ? safeStorage() : storage;
  const holder = doc.createElement('div');
  holder.innerHTML = sectionMarkup(null, emptyState(), false);
  const section = holder.firstElementChild;
  anchor.node.insertAdjacentElement(anchor.position, section);
  let flows = null, state = null, failed = false, lang = currentLang();
  const remember = section.querySelector('#erisim-remember'), step = section.querySelector('.erisim-step');

  const setStatus = (message) => {
    const status = section.querySelector('.status-line');
    if (status) status.textContent = message;
  };
  const updateControls = () => {
    const backButton = section.querySelector('[data-erisim="back"]'), restartButton = section.querySelector('[data-erisim="restart"]');
    const forgetButton = section.querySelector('[data-erisim="forget"]');
    if (backButton) backButton.hidden = !state || !state.path.length;
    if (restartButton) restartButton.hidden = !state || (!state.path.length && state.node !== '__solved');
    if (forgetButton) forgetButton.hidden = !remember.checked;
  };
  const render = ({ focus = false, status = '', target = null } = {}) => {
    if (!flows || !step) return;
    lang = currentLang();
    step.innerHTML = stepMarkup(flows, state, lang, Boolean(doc.getElementById('kart-sorun')));
    const trail = section.querySelector('.erisim-trail');
    if (trail) { trail.innerHTML = trailMarkup(flows, state); trail.setAttribute('aria-label', t('ui.erisim.trail', 'Yanıtlarınız')); }
    updateControls();
    setStatus(status);
    if (target) restoreTarget(section, target);
    else if (focus) {
      const question = section.querySelector('#erisim-q');
      if (question && typeof question.focus === 'function') question.focus();
    }
  };
  const showFailure = () => {
    failed = true;
    step.replaceChildren();
    const message = doc.createElement('p');
    message.className = 'status-line';
    message.setAttribute('role', 'status');
    message.setAttribute('aria-live', 'polite');
    message.textContent = t('ui.erisim.load_failed', 'Adımlar şu an yüklenemedi. İnsanla konuşmak için 153\'ü arayabilirsiniz.');
    const call = doc.createElement('a');
    call.className = 'btn btn-quiet';
    call.href = `tel:${FALLBACK_CALL}`;
    call.textContent = t('ui.erisim.contact_call', 'Arayın: {call}', { call: FALLBACK_CALL });
    step.append(message, call);
  };
  const persist = () => {
    if (remember.checked && state && state.node !== '__solved') writeState(stateStore, state);
    else if (!remember.checked || state?.node === '__solved') removeState(stateStore);
  };

  updateShell(section);
  updateControls();
  section.addEventListener('click', async (event) => {
    const target = event.target?.closest?.('[data-erisim-answer], [data-erisim]');
    if (!target || !section.contains(target)) return;
    if (target.dataset.erisimAnswer) {
      const next = choose(flows, state, state.node, target.dataset.erisimAnswer, Date.now());
      if (next === state) return;
      state = next;
      persist();
      render({ focus: true, status: state.node === '__solved'
        ? t('ui.erisim.solved_note', 'Tamam. Bu cihazdaki adımlar silindi.')
        : t('ui.erisim.step_status', 'Adım {n}: {question}', {
          n: state.path.length + 1, question: flows.nodes[state.node]?.text?.[lang] || '',
        }) });
      return;
    }
    const action = target.dataset.erisim;
    if (action === 'back') {
      state = back(flows, state);
      persist();
      render({ focus: true });
    } else if (action === 'restart') {
      state = { ...emptyState(), node: flows.start, at: Date.now() };
      persist();
      render({ focus: true });
    } else if (action === 'forget') {
      removeState(stateStore);
      remember.checked = false;
      state = { ...emptyState(), node: flows.start, at: Date.now() };
      render({ focus: true, status: t('ui.erisim.forgotten', 'Bu cihazdaki adımlar silindi.') });
    } else if (action === 'copy') {
      const summary = section.querySelector('#erisim-summary');
      try {
        const clipboard = doc.defaultView?.navigator?.clipboard;
        if (!clipboard || typeof clipboard.writeText !== 'function') throw new Error('clipboard unavailable');
        await clipboard.writeText(summary?.value || '');
        setStatus(t('ui.erisim.copied', 'Kopyalandı.'));
      } catch {
        if (summary && typeof summary.select === 'function') summary.select();
        setStatus(t('ui.erisim.copy_failed', 'Kopyalanamadı; metin seçildi, kendiniz kopyalayın.'));
      }
    }
  });
  section.addEventListener('change', (event) => {
    if (event.target !== remember) return;
    if (remember.checked && state) writeState(stateStore, state);
    else removeState(stateStore);
    updateControls();
  });
  const hashOpen = () => {
    if (doc.defaultView?.location?.hash !== `#${SECTION_ID}`) return;
    section.open = true;
    if (flows) {
      const question = section.querySelector('#erisim-q');
      if (question && typeof question.focus === 'function') question.focus();
    }
  };
  doc.defaultView?.addEventListener('hashchange', hashOpen);
  hashOpen();
  onLang((nextLang) => {
    const target = activeTarget(section, doc);
    lang = nextLang;
    updateShell(section);
    if (failed) showFailure();
    else if (flows) render({ target });
    else setStatus(t('ui.erisim.loading', 'Adımlar yükleniyor.'));
  });
  requestFlows().then((payload) => {
    flows = payload;
    const raw = readState(stateStore);
    const stored = parseStored(raw, flows, Date.now());
    state = stored || { ...emptyState(), node: flows.start, at: Date.now() };
    if (raw && !stored) removeState(stateStore);
    remember.checked = Boolean(stored || remember.checked);
    if (remember.checked && !stored) persist();
    render({ focus: doc.defaultView?.location?.hash === `#${SECTION_ID}` });
    hashOpen();
  }).catch(showFailure);
  return section;
}

if (typeof document !== 'undefined') mountRecovery(document, safeStorage());

export { ANCHORS, STYLESHEET, SECTION_ID, mountRecovery };
