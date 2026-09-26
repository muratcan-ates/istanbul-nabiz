/* Local, one-tap appearance presets. Persona labels and state stay in this browser. */
import { PREFS_KEY, applyPrefs, parsePrefs, readPrefs, savePrefs } from './a11y.js';
import { NEEDS, NEED_KEYS, answerLanguage, readProfile, setAnswerLanguage, writeProfile } from './profile.js';
import { esc } from './format.js';
import { icon } from './icons.js';

const PERSONA_KEY = 'nabiz.persona.v1';
const PERSONA_ORDER = Object.freeze(['gorme', 'isitme', 'hareket', 'yasli', 'ilk_kez', 'yabanci', 'okuma']);
const PRESETS = Object.freeze({
  gorme: Object.freeze({ id: 'gorme', label: 'Görme', hint: 'Büyük yazı, yüksek kontrast, sesli okuma teklifi', icon: 'search', prefs: Object.freeze({ text: 150, contrast: 'more', motion: 'reduce' }), simple: true, needs: Object.freeze(['low_vision']), lang: null, voice: 'offer', call153: true }),
  isitme: Object.freeze({ id: 'isitme', label: 'İşitme', hint: 'Sesli özellikler kapalı, yanıtlar yazılı', icon: 'bell', prefs: Object.freeze({}), simple: null, needs: Object.freeze(['hearing']), lang: null, voice: 'off', call153: false }),
  hareket: Object.freeze({ id: 'hareket', label: 'Hareket', hint: 'Adımsız yol, kısa yürüme', icon: 'wheelchair', prefs: Object.freeze({}), simple: null, needs: Object.freeze(['step_free', 'slow_walk']), lang: null, voice: 'keep', call153: false }),
  yasli: Object.freeze({ id: 'yasli', label: 'Yaşlı', hint: 'Büyük yazı, kısa yürüme, sade dil', icon: 'walk', prefs: Object.freeze({ text: 150, motion: 'reduce' }), simple: true, needs: Object.freeze(['slow_walk', 'plain_language']), lang: null, voice: 'offer', call153: true }),
  ilk_kez: Object.freeze({ id: 'ilk_kez', label: 'İlk kez / çocuk', hint: 'Büyük yazı, kısa ve sade anlatım', icon: 'list-details', prefs: Object.freeze({ text: 125 }), simple: true, needs: Object.freeze(['plain_language']), lang: null, voice: 'keep', call153: false }),
  yabanci: Object.freeze({ id: 'yabanci', label: 'Yabancı', hint: 'İngilizce cevaplar', icon: null, prefs: Object.freeze({}), simple: null, needs: Object.freeze([]), lang: 'en', voice: 'keep', call153: false }),
  okuma: Object.freeze({ id: 'okuma', label: 'Okuma güçlüğü', hint: 'Büyük yazı, sade dil, sesli okuma teklifi', icon: 'list-details', prefs: Object.freeze({ text: 125, motion: 'reduce' }), simple: true, needs: Object.freeze(['plain_language']), lang: null, voice: 'offer', call153: false }),
});
function planPreset(id, currentPrefs, currentProfile) {
  const preset = PRESETS[id];
  if (!preset) return null;
  const currentNeeds = (Array.isArray(currentProfile?.needs) ? currentProfile.needs : [])
    .filter((key) => NEED_KEYS.has(key) && key !== 'answer_en');
  const needs = [...new Set([...currentNeeds, ...preset.needs])];
  const alreadyEnglish = currentProfile?.needs?.includes('answer_en') === true;
  const needsConsent = currentProfile?.consent !== true && (needs.length > 0 || alreadyEnglish || preset.lang === 'en');
  return {
    id, label: preset.label, prefs: parsePrefs(JSON.stringify({ ...currentPrefs, ...preset.prefs })),
    simple: preset.simple, needs, lang: preset.lang, voice: preset.voice,
    call153: preset.call153, needsConsent,
  };
}
function snapshotOf(prefs, profile, simple, hadProfile) {
  return {
    prefs: parsePrefs(JSON.stringify(prefs)),
    needs: (Array.isArray(profile?.needs) ? profile.needs : [])
      .filter((key) => NEED_KEYS.has(key) && key !== 'answer_en'),
    consent: profile?.consent === true, lang: answerLanguage(profile || {}),
    simple: simple === true, hadProfile: hadProfile === true,
  };
}
function emptyState() { return { version: 1, active: null, dismissed: false, previous: null }; }
function validSnapshot(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)
    || !value.prefs || typeof value.prefs !== 'object' || Array.isArray(value.prefs)) return null;
  const prefs = parsePrefs(JSON.stringify(value.prefs));
  const fields = { version: value.prefs.version, text: value.prefs.text, contrast: value.prefs.contrast, motion: value.prefs.motion };
  if (JSON.stringify(prefs) !== JSON.stringify(fields) || !Array.isArray(value.needs)
    || value.needs.some((key) => !NEED_KEYS.has(key) || key === 'answer_en')
    || typeof value.consent !== 'boolean' || !['tr', 'en'].includes(value.lang)
    || typeof value.simple !== 'boolean' || typeof value.hadProfile !== 'boolean') return null;
  return { prefs, needs: [...new Set(value.needs)], consent: value.consent, lang: value.lang, simple: value.simple, hadProfile: value.hadProfile };
}
function parseState(raw) {
  try {
    const value = raw ? JSON.parse(raw) : null;
    if (!value || typeof value !== 'object' || Array.isArray(value) || value.version !== 1
      || !(value.active === null || PERSONA_ORDER.includes(value.active)) || typeof value.dismissed !== 'boolean') return emptyState();
    const previous = value.previous === null ? null : validSnapshot(value.previous);
    if (value.previous !== null && !previous) return emptyState();
    return { version: 1, active: value.active, dismissed: value.dismissed, previous };
  } catch (error) { return emptyState(); }
}
function readState(storage) {
  try { return parseState((storage || window.localStorage).getItem(PERSONA_KEY)); } catch (error) { return emptyState(); }
}
function writeState(value, storage) {
  try { (storage || window.localStorage).setItem(PERSONA_KEY, JSON.stringify(value)); return true; } catch (error) { return false; }
}
function localStorageOrNull() { try { return window.localStorage; } catch (error) { return null; } }
function nextIndex(index, key, count) {
  if (count < 1) return 0;
  if (key === 'Home') return 0;
  if (key === 'End') return count - 1;
  if (key === 'ArrowRight' || key === 'ArrowDown') return (index + 1) % count;
  if (key === 'ArrowLeft' || key === 'ArrowUp') return (index - 1 + count) % count;
  return index;
}
function pickerMarkup() {
  const buttons = PERSONA_ORDER.map((id, index) => {
    const preset = PRESETS[id];
    return '<button type="button" class="persona-btn" data-persona="' + id + '" tabindex="' + (index === 0 ? '0' : '-1') + '">'
      + (preset.icon ? icon(preset.icon) : '') + '<span class="persona-btn-copy"><span class="persona-label">'
      + esc(preset.label) + '</span><span class="persona-hint">' + esc(preset.hint) + '</span></span></button>';
  }).join('');
  return '<section id="persona-picker" class="persona-picker" aria-labelledby="persona-title">'
    + '<h2 id="persona-title">Size nasıl kolaylık sağlayalım?</h2>'
    + '<p>Tek dokunuş yazıyı, kontrastı ve yardımı birlikte ayarlar. Seçiminiz yalnız bu tarayıcıda durur.</p>'
    + '<div class="persona-grid" role="group" aria-label="Kişiye göre görünüm">' + buttons + '</div>'
    + '<div class="persona-confirm" id="persona-confirm"></div>'
    + '<button type="button" class="btn persona-later" id="persona-later">Şimdi değil</button>'
    + '<p class="sr-only" id="persona-status" role="status" aria-live="polite"></p></section>';
}
function badgeMarkup(id, offerVoice = false) {
  const preset = PRESETS[id];
  if (!preset) return '';
  const offer = offerVoice
    ? '<div class="persona-offer"><span>Cevapları sesli dinlemek ister misiniz?</span>'
      + '<button type="button" class="btn" id="persona-voice">Sesli okumaya git</button></div>' : '';
  return '<div id="persona-strip" class="persona-strip"><span class="persona-badge" id="persona-badge">Açık: '
    + esc(preset.label) + '</span><button type="button" class="btn" id="persona-undo">Geri al</button>'
    + '<button type="button" class="btn" id="persona-change">Değiştir</button>' + offer + '</div>';
}
function callBarMarkup() { return '<a class="persona-call" id="persona-call" href="tel:153">153\'ü ara · İnsanla konuşun</a>'; }
function confirmMarkup(plan) {
  const labels = plan.needs.map((key) => NEEDS.find((need) => need.key === key)?.label).filter(Boolean);
  if (plan.lang === 'en' || (!readProfile().consent && readProfile().needs.includes('answer_en'))) labels.push('İngilizce cevap');
  return '<section class="persona-consent" aria-labelledby="persona-consent-title"><h3 id="persona-consent-title">Profil onayı</h3>'
    + '<p>Bu seçim şu kısıtları bu cihazda saklar ve sorularınızla birlikte sunucuya gönderir: '
    + esc(labels.join(', ') || 'İngilizce cevap')
    + '. Sunucuya kimlik, tanı ya da Görme gibi bir etiket gitmez.</p><div class="btn-row">'
    + '<button type="button" class="btn btn-primary" id="persona-consent-yes">Onaylıyorum</button>'
    + '<button type="button" class="btn" id="persona-consent-view">Yalnız görünümü değiştir</button></div></section>';
}
let state;
let picker;
let status;
let pickerOpen = false;
let restoring = false;
function announce(message) { if (status) status.textContent = message; }
function ensureStyles() {
  if (!document.head || document.head.querySelector('link[href="/css/personas.css"]')) return;
  const link = document.createElement('link');
  link.rel = 'stylesheet'; link.href = '/css/personas.css'; document.head.appendChild(link);
}
function setSimple(on) {
  const button = document.querySelector('#simple-toggle');
  if (button && (document.documentElement.getAttribute('data-simple') === 'on') !== on) button.click();
}
function applyAppearance(plan) {
  const storage = localStorageOrNull();
  applyPrefs(plan.prefs, window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true);
  savePrefs(plan.prefs, storage);
  window.dispatchEvent(new StorageEvent('storage', { key: PREFS_KEY, newValue: JSON.stringify(plan.prefs) }));
  if (plan.simple !== null) setSimple(plan.simple);
}
function setProfileThroughForm(needs, consent) {
  const form = document.querySelector('#profile-form');
  const box = document.querySelector('#needs');
  if (!form || !box) return false;
  box.querySelectorAll('input[name="needs"]').forEach((input) => { input.checked = needs.includes(input.value); });
  const consentBox = document.querySelector('#profile-consent');
  if (consentBox) consentBox.checked = consent;
  form.requestSubmit();
  return true;
}
function updateProfile(plan) {
  if (!setProfileThroughForm(plan.needs, true)) {
    const profile = readProfile();
    writeProfile(setAnswerLanguage({ ...profile, needs: plan.needs, consent: true }, plan.lang || answerLanguage(profile)));
  }
  if (plan.lang !== null && answerLanguage(readProfile()) !== plan.lang) document.querySelector('#chat-lang-en')?.click();
}
function updateVoice(plan) {
  const optin = document.querySelector('#voice-optin');
  if (plan.voice === 'off' && optin?.getAttribute('aria-pressed') === 'true') optin.click();
  return plan.voice === 'offer' && Boolean(optin);
}
function renderCall(plan) {
  document.querySelector('#persona-call')?.remove();
  if (plan?.call153) {
    document.documentElement.setAttribute('data-persona-call', 'on');
    document.body.insertAdjacentHTML('beforeend', callBarMarkup());
  } else document.documentElement.removeAttribute('data-persona-call');
}
function openButton() {
  const host = document.querySelector('.topbar-inner');
  if (!host || state.active) return;
  let button = host.querySelector('#persona-open');
  if (pickerOpen) { button?.remove(); return; }
  if (!button) {
    button = document.createElement('button');
    button.type = 'button'; button.className = 'btn persona-open'; button.id = 'persona-open';
    button.textContent = 'Görünümü seç'; host.appendChild(button);
    button.addEventListener('click', () => showPicker(true, true));
  }
}
function showPicker(open, focusFirst = false) {
  pickerOpen = open; picker.hidden = !open; openButton();
  if (focusFirst) picker.querySelector('.persona-btn[tabindex="0"]')?.focus();
}
function renderBadge() {
  const host = document.querySelector('.topbar-inner');
  if (!host) return;
  host.querySelector('#persona-strip')?.remove();
  if (!state.active) { openButton(); return; }
  host.querySelector('#persona-open')?.remove();
  const offer = PRESETS[state.active].voice === 'offer' && Boolean(document.querySelector('#voice-optin'));
  host.insertAdjacentHTML('beforeend', badgeMarkup(state.active, offer));
  host.querySelector('#persona-undo')?.addEventListener('click', undoPersona);
  host.querySelector('#persona-change')?.addEventListener('click', () => showPicker(true, true));
  host.querySelector('#persona-voice')?.addEventListener('click', () => {
    const optin = document.querySelector('#voice-optin');
    if (optin) { optin.scrollIntoView({ block: 'center' }); optin.focus(); }
  });
}
function applyPlan(plan, includeProfile) {
  applyAppearance(plan);
  if (includeProfile) updateProfile(plan);
  updateVoice(plan);
  state = { version: 1, active: plan.id, dismissed: true, previous: state.previous };
  writeState(state); picker.querySelector('#persona-confirm').replaceChildren();
  showPicker(false); renderBadge(); renderCall(plan);
  announce(PRESETS[plan.id].label + ' görünümü açıldı.');
  document.querySelector('#persona-undo')?.focus();
}
function choosePersona(id) {
  const profile = readProfile();
  const storage = localStorageOrNull();
  const currentPrefs = readPrefs(storage);
  const plan = planPreset(id, currentPrefs, profile);
  if (!plan) return;
  const previous = state.previous || snapshotOf(
    currentPrefs, profile, document.documentElement.getAttribute('data-simple') === 'on',
    (() => { try { return storage?.getItem('nabiz.profile.v1') !== null; } catch (error) { return false; } })(),
  );
  state = { ...state, previous }; writeState(state);
  if (plan.needsConsent) {
    picker.querySelector('#persona-confirm').innerHTML = confirmMarkup(plan);
    picker.querySelector('#persona-consent-yes')?.addEventListener('click', () => applyPlan(plan, true));
    picker.querySelector('#persona-consent-view')?.addEventListener('click', () => applyPlan(plan, false));
    picker.querySelector('#persona-consent-yes')?.focus();
  } else applyPlan(plan, true);
}
function restoreProfile(previous) {
  if (previous.hadProfile) {
    if (!setProfileThroughForm(previous.needs, previous.consent)) {
      const profile = readProfile();
      writeProfile(setAnswerLanguage({ ...profile, needs: previous.needs, consent: previous.consent }, previous.lang));
    }
  } else {
    const clear = document.querySelector('#profile-clear');
    if (clear) clear.click();
    else writeProfile({ needs: [], stations: [], lines: [], consent: false });
  }
  const current = readProfile();
  if (answerLanguage(current) !== previous.lang) document.querySelector('#chat-lang-en')?.click();
}
function undoPersona() {
  if (!state.previous) return;
  const previous = state.previous;
  const wasHearing = state.active === 'isitme';
  restoring = true;
  try {
    applyAppearance({ prefs: previous.prefs, simple: null });
    if ((document.documentElement.getAttribute('data-simple') === 'on') !== previous.simple) setSimple(previous.simple);
    restoreProfile(previous); renderCall(null);
    state = { version: 1, active: null, dismissed: true, previous: null }; writeState(state);
    document.querySelector('#persona-strip')?.remove();
    announce(wasHearing ? 'Sesli okuma kapalı kaldı; isterseniz Sesle sormayı aç düğmesine basın.' : 'Önceki görünüme dönüldü.');
    showPicker(false); openButton(); document.querySelector('#persona-open')?.focus();
  } finally { restoring = false; }
}
function clearPersona() {
  if (restoring) return;
  state = { version: 1, active: null, dismissed: state.dismissed, previous: null };
  writeState(state); document.querySelector('#persona-strip')?.remove();
  renderCall(null); openButton();
}
function mountPersonas() {
  if (typeof document === 'undefined' || document.documentElement.dataset.personasMounted === 'true') return;
  document.documentElement.dataset.personasMounted = 'true'; ensureStyles(); state = readState();
  const wrapper = document.createElement('div');
  wrapper.innerHTML = pickerMarkup();
  const section = wrapper.firstElementChild;
  const home = document.querySelector('#home-screen');
  if (home) home.insertAdjacentElement('afterend', section);
  else document.querySelector('#main')?.prepend(section);
  picker = section; status = picker.querySelector('#persona-status'); document.body.appendChild(status);
  showPicker(state.active === null && !state.dismissed);
  if (state.active) renderCall(PRESETS[state.active]);
  renderBadge();
  picker.addEventListener('click', (event) => {
    const button = event.target.closest?.('button');
    if (button?.matches('.persona-btn[data-persona]')) choosePersona(button.dataset.persona);
    else if (button?.id === 'persona-later') {
      state = { ...state, dismissed: true }; writeState(state);
      picker.querySelector('#persona-confirm').replaceChildren(); showPicker(false);
    }
  });
  picker.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      event.preventDefault(); picker.querySelector('#persona-confirm').replaceChildren(); showPicker(false); return;
    }
    const current = event.target.closest?.('.persona-btn[data-persona]');
    if (!current) return;
    const buttons = [...picker.querySelectorAll('.persona-btn[data-persona]')];
    const index = buttons.indexOf(current); const next = nextIndex(index, event.key, buttons.length);
    if (next === index) return;
    event.preventDefault(); buttons.forEach((button, i) => button.setAttribute('tabindex', i === next ? '0' : '-1'));
    buttons[next].focus();
  });
  document.addEventListener('click', (event) => {
    if (event.target.closest?.('#a11y-reset, #profile-clear')) clearPersona();
  });
}
if (typeof document !== 'undefined') mountPersonas();
export {
  PERSONA_KEY, PERSONA_ORDER, PRESETS, planPreset, snapshotOf, parseState, readState, writeState,
  nextIndex, pickerMarkup, badgeMarkup, callBarMarkup, mountPersonas,
};
