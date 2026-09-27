/* Mount the citizen-side helper without changing the page's owned HTML. */

import { MOCK, get } from './api.js';
import { currentLang, onLang, t } from './i18n_text.js';
import {
  STORAGE_KEY, back, choose, emptyState, parseStored, sectionMarkup,
} from './troubleshoot_view.js';

const ANCHORS = [['#city-tools', 'beforeend'], ['#hesabim', 'beforebegin']];
const STYLESHEET = '/css/troubleshoot.css';
const SECTION_ID = 'kart-sorun';
const FLOW_URL = '/api/istanbulkart/flows';

function safeRemove(storage) {
  try { storage?.removeItem(STORAGE_KEY); } catch { /* device storage can be unavailable */ }
}

function safeWrite(storage, state) {
  try {
    storage?.setItem(STORAGE_KEY, JSON.stringify({
      version: 1, node: state.node, path: state.path, when: state.when, checks: state.checks, at: state.at,
    }));
  } catch { /* private mode keeps this visit in memory */ }
}

function addStylesheet(doc) {
  if (!doc.head || doc.querySelector(`link[href="${STYLESHEET}"]`)) return;
  const link = doc.createElement('link');
  link.rel = 'stylesheet';
  link.href = STYLESHEET;
  doc.head.append(link);
}

function insertSection(doc, anchor, position) {
  anchor.insertAdjacentHTML(position, sectionMarkup(null, emptyState(), false, 'loading'));
  return doc.querySelector(`#${SECTION_ID}`);
}

function mountTroubleshoot(doc, storage) {
  if (!doc || MOCK) return null;
  const existing = doc.querySelector(`#${SECTION_ID}`);
  if (existing) return existing;
  const anchor = ANCHORS.map(([selector, position]) => ({ node: doc.querySelector(selector), position }))
    .find((item) => item.node);
  if (!anchor) return null;
  addStylesheet(doc);
  const root = insertSection(doc, anchor.node, anchor.position);
  if (!root) return null;
  let flows = null;
  let state = emptyState();
  let phase = 'loading';
  let remember = false;
  let statusText = '';

  function persist() {
    if (remember && state.node !== '__solved') safeWrite(storage, { ...state, at: Date.now() });
  }

  function render(focusId = null) {
    const wasOpen = root.open;
    root.innerHTML = sectionMarkup(flows, state, remember, phase);
    root.open = wasOpen;
    const status = root.querySelector('.status-line');
    if (status) status.textContent = statusText;
    if (focusId) root.querySelector(focusId.startsWith('#') || focusId.startsWith('[') ? focusId : `#${focusId}`)
      ?.focus?.({ preventScroll: true });
  }

  function statusForCurrentStep() {
    const node = flows?.nodes[state.node];
    if (!node) return '';
    return t('ui.ikart.step_status', 'Adım {n}: {question}', {
      n: state.path.length + 1, question: node.text[currentLang()] || node.text.tr,
    });
  }

  function adoptPayload(payload) {
    if (!payload || !payload.nodes || !payload.contact) throw new Error('invalid flow');
    flows = payload;
    let raw = null;
    try { raw = storage?.getItem(STORAGE_KEY); } catch { raw = null; }
    const restored = parseStored(raw, flows);
    if (raw && !restored) safeRemove(storage);
    remember = Boolean(restored);
    state = restored || { ...emptyState(), node: flows.start, at: Date.now() };
    phase = 'ready';
    statusText = '';
    render(view?.location?.hash === '#kart-sorun' ? 'ikart-q' : null);
  }

  async function act(event) {
    const target = event.target?.closest?.('[data-ikart-answer], [data-ikart]');
    if (!target || !root.contains(target)) return;
    const answer = target.dataset?.ikartAnswer;
    const action = target.dataset?.ikart;
    if (answer !== undefined && flows) {
      const next = choose(flows, state, state.node, answer);
      if (next === state) return;
      state = next;
      if (state.node === '__solved') safeRemove(storage);
      else persist();
      statusText = statusForCurrentStep();
      render('ikart-q');
      return;
    }
    if (action === 'next' || action === 'skip') {
      const input = root.querySelector('#ikart-when');
      state = choose(flows, state, state.node, action === 'skip' ? null : input?.value || null);
      persist();
      statusText = statusForCurrentStep();
      render('ikart-q');
    } else if (action === 'back') {
      state = back(flows, state);
      persist();
      statusText = statusForCurrentStep();
      render('ikart-q');
    } else if (action === 'restart') {
      state = { ...emptyState(), node: flows.start, at: Date.now() };
      persist();
      statusText = statusForCurrentStep();
      render('ikart-q');
    } else if (action === 'forget') {
      safeRemove(storage);
      remember = false;
      state = { ...emptyState(), node: flows.start, at: Date.now() };
      statusText = t('ui.ikart.forgotten', 'Bu cihazdaki adımlar silindi.');
      render('ikart-remember');
    } else if (action === 'copy') {
      const area = root.querySelector('#ikart-summary');
      try {
        if (!globalThis.navigator?.clipboard?.writeText) throw new Error('clipboard unavailable');
        await globalThis.navigator.clipboard.writeText(area?.value || '');
        statusText = t('ui.ikart.copied', 'Kopyalandı.');
      } catch {
        area?.select?.();
        area?.setSelectionRange?.(0, (area.value || '').length);
        statusText = t('ui.ikart.copy_failed', 'Kopyalanamadı; metin seçildi, kendiniz kopyalayın.');
      }
      const status = root.querySelector('.status-line');
      if (status) status.textContent = statusText;
    }
  }

  root.addEventListener('click', (event) => { void act(event); });
  root.addEventListener('change', (event) => {
    if (event.target?.id !== 'ikart-remember') return;
    remember = Boolean(event.target.checked);
    if (remember) persist();
    else safeRemove(storage);
    render('ikart-remember');
  });
  onLang((_language) => {
    const active = doc.activeElement;
    if (!active || !root.contains(active)) return render();
    const focusTarget = active.id ? `#${active.id}`
      : active.dataset?.ikartAnswer ? `[data-ikart-answer="${active.dataset.ikartAnswer}"]`
        : active.dataset?.ikart ? `[data-ikart="${active.dataset.ikart}"]` : null;
    render(focusTarget);
  });

  const view = doc.defaultView || globalThis.window;
  const openFromHash = () => {
    if (view?.location?.hash !== '#kart-sorun') return;
    root.open = true;
    root.querySelector('#ikart-q')?.focus?.({ preventScroll: true });
  };
  if (view?.addEventListener) view.addEventListener('hashchange', openFromHash);
  openFromHash();
  render();
  get(FLOW_URL).then(adoptPayload).catch(() => {
    phase = 'failed';
    state = emptyState();
    render();
  });
  return root;
}

export { ANCHORS, STYLESHEET, SECTION_ID, mountTroubleshoot };

if (typeof document !== 'undefined') mountTroubleshoot(document, (() => { try { return globalThis.localStorage; } catch { return null; } })());
