/* Adapted from DOU-Synapse apps/web/lib/accessibility.ts, apps/web/components/accessibility-provider.tsx, and apps/web/public/accessibility-boot.js (MIT, Copyright (c) 2026 Muratcan Ates). */

import { readProfile } from './profile.js';

const PREFS_KEY = 'nabiz.a11y.v1';
const DEFAULT_PREFS = Object.freeze({ version: 1, text: 100, contrast: 'standard', motion: 'system' });

function parsePrefs(raw) {
  try {
    const value = raw ? JSON.parse(raw) : null;
    if (!value || typeof value !== 'object' || Array.isArray(value) || value.version !== 1) return { ...DEFAULT_PREFS };
    if (![100, 125, 150].includes(value.text) || !['standard', 'more'].includes(value.contrast)
      || !['system', 'reduce'].includes(value.motion)) return { ...DEFAULT_PREFS };
    return { version: 1, text: value.text, contrast: value.contrast, motion: value.motion };
  } catch (error) {
    return { ...DEFAULT_PREFS };
  }
}

function readPrefs(storage) {
  try { return parsePrefs(storage.getItem(PREFS_KEY)); } catch (error) { return { ...DEFAULT_PREFS }; }
}

function savePrefs(prefs, storage) {
  try {
    storage.setItem(PREFS_KEY, JSON.stringify({
      version: 1,
      text: prefs.text,
      contrast: prefs.contrast,
      motion: prefs.motion,
    }));
    return true;
  } catch (error) {
    return false;
  }
}

function reduceMotion(prefs, systemReduced) {
  return prefs.motion === 'reduce' || systemReduced === true;
}

function applyPrefs(prefs, systemReduced, root = document.documentElement) {
  root.setAttribute('data-text-scale', String(prefs.text));
  root.setAttribute('data-contrast', prefs.contrast);
  root.setAttribute('data-motion', reduceMotion(prefs, systemReduced) ? 'reduce' : 'full');
}

function shortcut(event) {
  if (!event || !event.altKey || !event.shiftKey || event.isComposing) return null;
  return ({ KeyB: 'text', KeyK: 'contrast', KeyH: 'motion', KeyS: 'simple', KeyE: 'panel' })[event.code] || null;
}

function mountA11y() {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  if (root.dataset.a11yMounted === 'true') return;
  root.dataset.a11yMounted = 'true';

  const media = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;
  let systemReduced = media ? media.matches : false;
  let raw = null;
  try { raw = window.localStorage.getItem(PREFS_KEY); } catch (error) { /* Private mode uses defaults. */ }
  let prefs = parsePrefs(raw);
  if (raw === null) {
    try {
      if (readProfile().needs.includes('low_vision')) prefs = { ...prefs, text: 125 };
    } catch (error) { /* A profile that cannot be read does not block the page. */ }
  }
  applyPrefs(prefs, systemReduced, root);

  const head = document.head;
  if (head && !head.querySelector('link[href="/css/a11y.css"]')) {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = '/css/a11y.css';
    head.appendChild(link);
  }

  const actions = document.querySelector('.topbar-actions');
  if (!actions) return;
  let textButton = document.querySelector('#text-toggle');
  if (!textButton) {
    textButton = document.createElement('button');
    textButton.type = 'button';
    textButton.className = 'btn';
    textButton.id = 'text-toggle';
    textButton.textContent = 'Büyük yazı';
    const simpleButton = actions.querySelector('#simple-toggle');
    actions.insertBefore(textButton, simpleButton || actions.firstChild);
  }
  let panelButton = document.querySelector('#a11y-toggle');
  if (!panelButton) {
    panelButton = document.createElement('button');
    panelButton.type = 'button';
    panelButton.className = 'btn';
    panelButton.id = 'a11y-toggle';
    panelButton.setAttribute('aria-expanded', 'false');
    panelButton.setAttribute('aria-controls', 'a11y-panel');
    panelButton.textContent = 'Erişilebilirlik';
    actions.insertBefore(panelButton, actions.querySelector('#simple-toggle') || null);
  }
  panelButton.setAttribute('aria-expanded', panelButton.getAttribute('aria-expanded') || 'false');
  panelButton.setAttribute('aria-controls', 'a11y-panel');

  let panel = document.querySelector('#a11y-panel');
  if (!panel) {
    panel = document.createElement('section');
    panel.id = 'a11y-panel';
    panel.className = 'a11y-panel wrap';
    panel.hidden = true;
    panel.setAttribute('aria-labelledby', 'a11y-title');
    panel.innerHTML = '<h2 id="a11y-title">Erişilebilirlik tercihleri</h2>'
      + '<fieldset><legend>Yazı boyutu</legend><div class="a11y-options">'
      + '<label class="check"><input type="radio" name="a11y-text" value="100"><span>Normal</span></label>'
      + '<label class="check"><input type="radio" name="a11y-text" value="125"><span>Büyük</span></label>'
      + '<label class="check"><input type="radio" name="a11y-text" value="150"><span>Çok büyük</span></label></div></fieldset>'
      + '<label class="check"><input id="a11y-contrast" type="checkbox"><span>Yüksek kontrast</span></label>'
      + '<label class="check"><input id="a11y-motion" type="checkbox"><span>Hareketi azalt</span></label>'
      + '<label class="check"><input id="a11y-simple" type="checkbox"><span>Sade mod</span></label>'
      + '<div class="btn-row"><button type="button" class="btn" id="a11y-reset">Sıfırla</button>'
      + '<a href="/kvkk.html">Kişisel veriler ve gizlilik</a></div>'
      + '<p class="sr-only" id="a11y-status" role="status" aria-live="polite"></p>'
      + '<p class="a11y-shortcuts">Kısayollar: Alt + Shift + B yazı boyutu, K kontrast, H hareket, S sade mod, E bu panel.</p>';
    const topbar = document.querySelector('.topbar');
    if (topbar) topbar.insertAdjacentElement('afterend', panel);
    else actions.insertAdjacentElement('afterend', panel);
  }

  const status = panel.querySelector('#a11y-status');
  const textToggle = () => {
    prefs = { ...prefs, text: prefs.text === 100 ? 125 : prefs.text === 125 ? 150 : 100 };
    persist('Yazı boyutu güncellendi.');
  };
  const syncControls = () => {
    panel.querySelectorAll('input[name="a11y-text"]').forEach((input) => { input.checked = Number(input.value) === prefs.text; });
    const contrast = panel.querySelector('#a11y-contrast');
    const motion = panel.querySelector('#a11y-motion');
    const simple = panel.querySelector('#a11y-simple');
    if (contrast) contrast.checked = prefs.contrast === 'more';
    if (motion) motion.checked = prefs.motion === 'reduce';
    if (simple) simple.checked = root.getAttribute('data-simple') === 'on';
    textButton.setAttribute('aria-pressed', prefs.text === 100 ? 'false' : 'true');
  };
  function persist(message) {
    applyPrefs(prefs, systemReduced, root);
    try { savePrefs(prefs, window.localStorage); } catch (error) { /* Storage can be disabled by the browser. */ }
    syncControls();
    if (status) status.textContent = message;
  }
  function setSimple(on, announce = true) {
    const button = document.querySelector('#simple-toggle');
    if (button && (button.getAttribute('aria-pressed') === 'true') !== on) button.click();
    else if (!button) {
      if (on) root.setAttribute('data-simple', 'on');
      else root.removeAttribute('data-simple');
      try { window.localStorage.setItem('nabiz-simple', on ? 'on' : 'off'); } catch (error) { /* Storage can be disabled. */ }
    }
    syncControls();
    if (announce && status) status.textContent = on ? 'Sade mod açık.' : 'Sade mod kapalı.';
  }
  function openPanel(open) {
    panel.hidden = !open;
    panelButton.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (open) panel.querySelector('input, button, a')?.focus();
    else panelButton.focus();
  }
  function activate(action) {
    if (action === 'text') textToggle();
    else if (action === 'contrast') {
      prefs = { ...prefs, contrast: prefs.contrast === 'more' ? 'standard' : 'more' };
      persist(prefs.contrast === 'more' ? 'Yüksek kontrast açık.' : 'Yüksek kontrast kapalı.');
    } else if (action === 'motion') {
      prefs = { ...prefs, motion: prefs.motion === 'reduce' ? 'system' : 'reduce' };
      persist(prefs.motion === 'reduce' ? 'Hareket azaltıldı.' : 'Sistem hareket tercihi kullanılıyor.');
    } else if (action === 'simple') setSimple(root.getAttribute('data-simple') !== 'on');
    else if (action === 'panel') openPanel(panel.hidden);
  }

  textButton.addEventListener('click', textToggle);
  panelButton.addEventListener('click', () => activate('panel'));
  const simpleButton = document.querySelector('#simple-toggle');
  if (simpleButton) simpleButton.addEventListener('click', () => {
    queueMicrotask(() => {
      syncControls();
      if (status) status.textContent = root.getAttribute('data-simple') === 'on' ? 'Sade mod açık.' : 'Sade mod kapalı.';
    });
  });
  panel.addEventListener('change', (event) => {
    const input = event.target;
    if (input.matches('input[name="a11y-text"]')) {
      prefs = { ...prefs, text: Number(input.value) };
      persist('Yazı boyutu güncellendi.');
    } else if (input.id === 'a11y-contrast') {
      prefs = { ...prefs, contrast: input.checked ? 'more' : 'standard' };
      persist(input.checked ? 'Yüksek kontrast açık.' : 'Yüksek kontrast kapalı.');
    } else if (input.id === 'a11y-motion') {
      prefs = { ...prefs, motion: input.checked ? 'reduce' : 'system' };
      persist(input.checked ? 'Hareket azaltıldı.' : 'Sistem hareket tercihi kullanılıyor.');
    } else if (input.id === 'a11y-simple') setSimple(input.checked);
  });
  panel.querySelector('#a11y-reset').addEventListener('click', () => {
    prefs = { ...DEFAULT_PREFS };
    persist('Erişilebilirlik tercihleri sıfırlandı.');
    setSimple(false, false);
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !panel.hidden) {
      event.preventDefault();
      openPanel(false);
      return;
    }
    const action = shortcut(event);
    if (!action) return;
    event.preventDefault();
    activate(action);
  });

  const observeSimple = new MutationObserver(syncControls);
  observeSimple.observe(root, { attributes: true, attributeFilter: ['data-simple'] });
  syncControls();
  if (media) media.addEventListener('change', (event) => {
    systemReduced = event.matches;
    applyPrefs(prefs, systemReduced, root);
  });
  window.addEventListener('storage', (event) => {
    if (event.key !== PREFS_KEY && event.key !== null) return;
    prefs = parsePrefs(event.key === null ? null : event.newValue);
    if (event.key === null) {
      try {
        if (readProfile().needs.includes('low_vision')) prefs = { ...prefs, text: 125 };
      } catch (error) { /* Keep defaults when the profile is unavailable. */ }
    }
    applyPrefs(prefs, systemReduced, root);
    syncControls();
  });
}

if (typeof document !== 'undefined') mountA11y();

export { PREFS_KEY, DEFAULT_PREFS, parsePrefs, readPrefs, savePrefs, applyPrefs, reduceMotion, mountA11y, shortcut };
