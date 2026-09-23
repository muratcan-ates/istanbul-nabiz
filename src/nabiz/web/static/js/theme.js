/* The theme toggle cycles system, light and dark, and remembers the choice in this browser. */

const $ = (sel) => document.querySelector(sel);

const THEME_ORDER = ['system', 'light', 'dark'];
const THEME_TR = { system: 'sistem', light: 'açık', dark: 'koyu' };

function readTheme() {
  try { return window.localStorage.getItem('nabiz-theme') || 'system'; } catch (err) { return 'system'; }
}

function applyTheme(mode) {
  const root = document.documentElement;
  if (mode === 'system') root.removeAttribute('data-theme');
  else root.setAttribute('data-theme', mode);
  const btn = $('#theme-toggle');
  if (btn) btn.title = `Tema: ${THEME_TR[mode] || mode}`;
  try { window.localStorage.setItem('nabiz-theme', mode); } catch (err) { /* private mode */ }
}

export { THEME_ORDER, readTheme, applyTheme };
