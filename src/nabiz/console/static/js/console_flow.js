/* A decision is a human event: show the path the ledger and citizen face actually take. */

const STEP_IDS = ['signal', 'arena', 'human', 'ledger', 'citizen'];
const PUBLISH_CARD_LABEL = 'vatandaş kartını güncelle';
const STEP_MARKUP = [
  ['signal', 'Sinyal', 'kaynak'],
  ['arena', 'Arena', 'koltuklar'],
  ['human', 'İnsan onayı', 'operatör'],
  ['ledger', 'Defter', 'zincir'],
  ['citizen', 'Vatandaş', 'yayın'],
];

let root;
let decisionBody;
let section;
let pendingAction = null;
let timers = new Set();

function emptyFlow() {
  return { lit: [], stop: null, citizen: null, message: '' };
}

function flowFor(act, hasCard, willPublish = true) {
  if (!hasCard) return emptyFlow();
  if (act === null || act === undefined) {
    return { lit: ['signal', 'arena'], stop: 'human', citizen: null, message: 'İnsan onayı bekliyor.' };
  }
  if (act === 'approve' || act === 'edit') {
    if (willPublish) {
      return {
        lit: [...STEP_IDS], stop: 'citizen', citizen: 'published',
        message: 'Onaylandı: karar deftere yazıldı, metin vatandaş yüzünde yayımlandı.',
      };
    }
    return {
      lit: STEP_IDS.slice(0, 4), stop: 'ledger', citizen: 'not_published',
      message: 'Onaylandı: karar deftere yazıldı; vatandaş yüzünde yayımlanmadı.',
    };
  }
  if (act === 'reject') {
    return {
      lit: STEP_IDS.slice(0, 4), stop: 'ledger', citizen: 'not_published',
      message: 'Reddedildi: karar gerekçesiyle deftere yazıldı; vatandaşa yayımlanmadı.',
    };
  }
  if (act === 'defer') {
    return {
      lit: STEP_IDS.slice(0, 4), stop: 'ledger', citizen: null,
      message: 'Ertelendi: kart yeniden karara gelecek.',
    };
  }
  return { lit: ['signal', 'arena'], stop: 'human', citizen: null, message: 'İnsan onayı bekliyor.' };
}

function ensureStyle() {
  if (!document.head || document.head.querySelector('link[href="/css/console_flow.css"]')) return;
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = '/css/console_flow.css';
  document.head.appendChild(link);
}

function markup() {
  const steps = STEP_MARKUP.map(([id, name, caption], index) => `<li class="flow-step" data-step="${id}">
    <span class="flow-mark" aria-hidden="true"></span><span class="flow-name">${name}</span>
    <span class="flow-caption">${caption}</span>
    ${index < STEP_IDS.length - 1 ? '<span class="flow-connector" aria-hidden="true"><span></span></span>' : ''}
  </li>`).join('');
  return `<section class="decision-flow" aria-label="Karar yolu">
    <ol class="flow-steps">${steps}</ol>
    <p class="flow-status" role="status" aria-live="polite"></p>
  </section>`;
}

function cancelTimers() {
  timers.forEach((timer) => clearTimeout(timer));
  timers.clear();
}

function later(callback, delay) {
  const timer = setTimeout(() => {
    timers.delete(timer);
    callback();
  }, delay);
  timers.add(timer);
}

function allowsMotion() {
  return !window.matchMedia('(prefers-reduced-motion: reduce)').matches
    && root.dataset.motion !== 'reduce' && root.dataset.simple !== 'on';
}

function markStep(step, flow, glowing) {
  const lit = flow.lit.includes(step.dataset.step);
  const current = flow.stop === step.dataset.step && flow.stop === 'human' && flow.citizen === null;
  const unpublished = step.dataset.step === 'citizen' && flow.citizen === 'not_published';
  step.classList.toggle('is-lit', lit);
  step.classList.toggle('is-stop', flow.stop === step.dataset.step);
  step.classList.toggle('is-unpublished', unpublished);
  step.classList.toggle('is-glowing', glowing && lit);
  if (current) step.setAttribute('aria-current', 'step');
  else step.removeAttribute('aria-current');
}

function paint(flow) {
  const steps = [...section.querySelectorAll('.flow-step')];
  steps.forEach((step) => markStep(step, flow, false));
  steps.slice(0, -1).forEach((step, index) => {
    const connector = step.querySelector('.flow-connector');
    if (connector) connector.classList.toggle('is-filled', flow.lit.includes(STEP_IDS[index + 1]));
  });
  const status = section.querySelector('.flow-status');
  if (status.textContent !== flow.message) status.textContent = flow.message;
}

function animate(flow) {
  cancelTimers();
  const steps = [...section.querySelectorAll('.flow-step')];
  steps.forEach((step) => markStep(step, emptyFlow(), false));
  steps.slice(0, -1).forEach((step) => step.querySelector('.flow-connector')?.classList.remove('is-filled'));
  const status = section.querySelector('.flow-status');
  if (status.textContent !== flow.message) status.textContent = flow.message;
  if (!allowsMotion()) {
    paint(flow);
    return;
  }

  const litIndexes = flow.lit.map((id) => STEP_IDS.indexOf(id)).filter((index) => index >= 0);
  litIndexes.forEach((stepIndex, order) => {
    later(() => {
      const step = steps[stepIndex];
      step.classList.add('is-lit', 'is-glowing');
      if (stepIndex > 0) {
        const connector = steps[stepIndex - 1].querySelector('.flow-connector');
        connector?.classList.add('is-filled');
      }
      if (order === litIndexes.length - 1) {
        step.classList.toggle('is-unpublished', flow.citizen === 'not_published' && stepIndex === 4);
        later(() => steps.forEach((item) => item.classList.remove('is-glowing')), 6000);
      }
    }, order * 120);
  });
  steps.forEach((step) => {
    if (flow.stop === step.dataset.step && flow.stop === 'human' && flow.citizen === null) {
      step.setAttribute('aria-current', 'step');
    } else {
      step.removeAttribute('aria-current');
    }
    if (step.dataset.step === 'citizen' && flow.citizen === 'not_published') step.classList.add('is-unpublished');
  });
}

function hasPendingCard() {
  return Boolean(decisionBody.querySelector('#decision-actions:not([hidden])'));
}

function resetForSelection(hasCard = hasPendingCard()) {
  if (pendingAction) return;
  cancelTimers();
  const flow = flowFor(null, hasCard);
  paint(flow);
}

function willPublish() {
  const proposedAction = decisionBody.querySelector('.proposed > p > b');
  return proposedAction?.textContent.trim() === PUBLISH_CARD_LABEL;
}

function onClickCapture(event) {
  const queueItem = event.target.closest('#queue .queue-item');
  if (queueItem) {
    pendingAction = null;
    resetForSelection(false);
    return;
  }
  const button = event.target.closest('#decision #decision-body button[data-act]');
  if (!button || !['approve', 'edit', 'reject', 'defer'].includes(button.dataset.act)) {
    if (!event.target.closest('#decision')) pendingAction = null;
    return;
  }
  if (button.dataset.act === 'edit' && button.dataset.confirm !== 'true') return;
  if ((button.dataset.act === 'approve' || button.dataset.act === 'edit')
    && button.getAttribute('aria-disabled') === 'true') return;
  pendingAction = { act: button.dataset.act, willPublish: willPublish(), hasCard: true };
}

function onDecided() {
  if (!pendingAction) return;
  const result = flowFor(pendingAction.act, pendingAction.hasCard, pendingAction.willPublish);
  pendingAction = null;
  animate(result);
}

function mount() {
  root = document.documentElement;
  decisionBody = document.querySelector('#decision-body');
  const anchor = document.querySelector('.console-grid') || document.querySelector('#decision');
  if (!anchor || !decisionBody) return;
  section = document.createElement('section');
  section.innerHTML = markup();
  anchor.before(section.firstElementChild);
  section = document.querySelector('.decision-flow');
  ensureStyle();
  resetForSelection();
  document.addEventListener('click', onClickCapture, true);
  document.addEventListener('nabiz:decided', onDecided);
  const observer = new MutationObserver(() => resetForSelection());
  observer.observe(decisionBody, { childList: true });
}

if (typeof document !== 'undefined') mount();

export { flowFor };
