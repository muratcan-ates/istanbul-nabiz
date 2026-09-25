/* The theme toggle cycles system, light and dark, and remembers the choice in this browser. Its
 * icon shows the current mode and its label says the mode and what a press does. */

const $ = (sel) => document.querySelector(sel);

const THEME_ORDER = ['system', 'light', 'dark'];
const THEME_TR = { system: 'sistem', light: 'açık', dark: 'koyu' };
const NEXT_TR = { system: 'Açık temaya', light: 'Koyu temaya', dark: 'Sistem temasına' };
const THEME_ICONS = { system: 'device-desktop', light: 'sun', dark: 'moon' };

function readTheme() {
  try { return window.localStorage.getItem('nabiz-theme') || 'system'; } catch (err) { return 'system'; }
}

function applyTheme(mode) {
  const root = document.documentElement;
  const known = THEME_TR[mode] ? mode : 'system';
  if (known === 'system') root.removeAttribute('data-theme');
  else root.setAttribute('data-theme', known);
  const btn = $('#theme-toggle');
  if (btn) {
    btn.setAttribute('aria-label', `Tema: ${THEME_TR[known]}. ${NEXT_TR[known]} geçmek için basın.`);
    btn.querySelector('use').setAttribute('href', `#i-${THEME_ICONS[known]}`);
  }
  try { window.localStorage.setItem('nabiz-theme', known); } catch (err) { /* private mode */ }
}

export { THEME_ORDER, readTheme, applyTheme };
