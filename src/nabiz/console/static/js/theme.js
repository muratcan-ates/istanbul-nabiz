/* The theme toggle cycles system, light and dark; the simple-mode toggle enlarges type and stops
 * motion. Both remember the choice in this browser only. Adapted from the web page's theme.js. */

import { onLang, t } from './i18n_text.js';

const $ = (sel) => document.querySelector(sel);

const THEME_ORDER = ['system', 'light', 'dark'];
const THEME_LABELS_TR = {
  system: 'Tema: sistem. Açık temaya geçmek için basın.',
  light: 'Tema: açık. Koyu temaya geçmek için basın.',
  dark: 'Tema: koyu. Sistem temasına geçmek için basın.',
};
const THEME_ICONS = { system: 'device-desktop', light: 'sun', dark: 'moon' };

function updateThemeLabel(mode) {
  const known = THEME_ORDER.includes(mode) ? mode : 'system';
  const btn = $('#theme-toggle');
  if (btn) btn.setAttribute('aria-label', t(`dyn.theme_${known}`, THEME_LABELS_TR[known]));
}

function readStored(key, fallback) {
  try { return window.localStorage.getItem(key) || fallback; } catch (err) { return fallback; }
}

function store(key, value) {
  try { window.localStorage.setItem(key, value); } catch (err) { /* private mode */ }
}

function applyTheme(mode) {
  const root = document.documentElement;
  const known = THEME_ORDER.includes(mode) ? mode : 'system';
  if (known === 'system') root.removeAttribute('data-theme');
  else root.setAttribute('data-theme', known);
  const btn = $('#theme-toggle');
  if (btn) {
    updateThemeLabel(known);
    btn.querySelector('use').setAttribute('href', `#i-${THEME_ICONS[known]}`);
  }
  store('nabiz-theme', known);
}

function applySimple(on) {
  const root = document.documentElement;
  if (on) root.setAttribute('data-simple', 'on');
  else root.removeAttribute('data-simple');
  const btn = $('#simple-toggle');
  if (btn) btn.setAttribute('aria-pressed', on ? 'true' : 'false');
  store('nabiz-simple', on ? 'on' : 'off');
}

/** Wire both toggles; call once at boot. */
function mountToggles() {
  let theme = readStored('nabiz-theme', 'system');
  applyTheme(theme);
  onLang(() => updateThemeLabel(document.documentElement.getAttribute('data-theme') || 'system'));
  const themeBtn = $('#theme-toggle');
  if (themeBtn) {
    themeBtn.addEventListener('click', () => {
      theme = THEME_ORDER[(THEME_ORDER.indexOf(theme) + 1) % THEME_ORDER.length];
      applyTheme(theme);
    });
  }
  let simple = readStored('nabiz-simple', 'off') === 'on';
  applySimple(simple);
  const simpleBtn = $('#simple-toggle');
  if (simpleBtn) {
    simpleBtn.addEventListener('click', () => { simple = !simple; applySimple(simple); });
  }
}

export { THEME_ORDER, applyTheme, applySimple, mountToggles };
