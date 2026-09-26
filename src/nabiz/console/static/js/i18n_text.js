let activeLanguage = 'tr';
let activeCatalog = {};
let fallbackCatalog = {};

const usable = (value) => typeof value === 'string' && Boolean(value.trim());

function applyVars(value, vars) {
  return value.replace(/\{(\w+)\}/g, (match, name) => (
    Object.prototype.hasOwnProperty.call(vars || {}, name) ? String(vars[name]) : match
  ));
}

function announceLanguage(language) {
  if (typeof window === 'undefined' || typeof window.dispatchEvent !== 'function') return;
  const EventType = window.CustomEvent || globalThis.CustomEvent;
  if (typeof EventType === 'function') window.dispatchEvent(new EventType('nabiz:lang', { detail: { lang: language } }));
}

export function currentLang() {
  return activeLanguage;
}

export function setCatalogs(language, catalog, trCatalog) {
  activeLanguage = language === 'en' ? 'en' : 'tr';
  activeCatalog = catalog && typeof catalog === 'object' && !Array.isArray(catalog) ? catalog : {};
  fallbackCatalog = trCatalog && typeof trCatalog === 'object' && !Array.isArray(trCatalog) ? trCatalog : {};
}

export function t(key, fallback, vars = {}) {
  const translated = activeLanguage === 'en' ? activeCatalog[key] : null;
  const source = usable(translated) ? translated : usable(fallback) ? fallback : fallbackCatalog[key];
  return applyVars(usable(source) ? source : '', vars);
}

export async function loadCatalogs(language) {
  const selected = language === 'en' ? 'en' : 'tr';
  let trCatalog = {};
  let catalog = {};
  try {
    const [trResponse, selectedResponse] = await Promise.all([
      fetch('/i18n/tr.json'),
      selected === 'en' ? fetch('/i18n/en.json') : null,
    ]);
    if (!trResponse.ok || (selectedResponse && !selectedResponse.ok)) throw new Error('catalog unavailable');
    trCatalog = await trResponse.json();
    catalog = selectedResponse ? await selectedResponse.json() : trCatalog;
  } catch {
    setCatalogs('tr', trCatalog, trCatalog);
    announceLanguage('tr');
    return 'tr';
  }
  setCatalogs(selected, catalog, trCatalog);
  announceLanguage(selected);
  return selected;
}

export function onLang(callback) {
  if (typeof window === 'undefined' || typeof window.addEventListener !== 'function') return () => {};
  const listener = (event) => callback(event.detail && event.detail.lang === 'en' ? 'en' : 'tr');
  window.addEventListener('nabiz:lang', listener);
  return () => window.removeEventListener('nabiz:lang', listener);
}
