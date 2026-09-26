export const EMERGENCY_EVENT = 'nabiz:emergency';

export const CARD_TEXT = Object.freeze({
  tr: Object.freeze({
    title: 'Acil durum olabilir',
    desc: 'Sohbeti durdurdum. Bu site yardım çağıramaz; aramayı siz yapın.',
    live: 'Acil durum olabilir. 112\'yi arayın.',
    call: '112\'yi ara',
    locate: 'Konumumu göster',
    copy: 'Kopyala',
    line153: '153 Çözüm Merkezi (acil olmayan konular)',
    back: 'Acil değil, geri dön',
    foot: 'Resmî İBB hizmeti değildir. Nabız bağımsız bir projedir. Konumunuz yalnız bu cihazda kalır.',
  }),
  en: Object.freeze({
    title: 'This may be an emergency',
    desc: 'I stopped the chat. This site cannot call for help; make the call yourself.',
    live: 'This may be an emergency. Call 112.',
    call: 'Call 112',
    locate: 'Show my location',
    copy: 'Copy',
    line153: '153 Solution Centre (non-emergency matters)',
    back: 'Not an emergency, go back',
    foot: 'Not an official İBB service. Nabız is an independent project. Your location stays on this device only.',
  }),
  ar: Object.freeze({
    title: 'قد تكون هذه حالة طارئة',
    desc: 'أوقفتُ المحادثة. لا يستطيع هذا الموقع طلب المساعدة؛ اتصل أنت بنفسك.',
    live: 'قد تكون هذه حالة طارئة. اتصل بالرقم 112.',
    call: 'اتصل بالرقم 112',
    locate: 'أظهر موقعي',
    copy: 'انسخ',
    line153: 'مركز الحلول 153 (للأمور غير الطارئة)',
    back: 'ليست حالة طارئة، عودة',
    foot: 'ليست خدمة رسمية من İBB. Nabız مشروع مستقل. يبقى موقعك على هذا الجهاز فقط.',
  }),
});

const LOCATION_TEXT = Object.freeze({
  tr: Object.freeze({
    waiting: 'Konum alınıyor.',
    shown: 'Konumunuz: {coords}. Bu sayıları 112\'ye okuyabilirsiniz.',
    copied: 'Panoya kopyalandı: {coords}.',
    copyfail: 'Kopyalanamadı. Sayıları ekrandan okuyun: {coords}.',
    denied: 'Konum alınamadı. Adresinizi 112\'ye söyleyin.',
  }),
  en: Object.freeze({
    waiting: 'Getting your location.',
    shown: 'Your location: {coords}. You can read these numbers to 112.',
    copied: 'Copied to the clipboard: {coords}.',
    copyfail: 'Could not copy. Read the numbers from the screen: {coords}.',
    denied: 'Could not get your location. Tell 112 your address.',
  }),
  ar: Object.freeze({
    waiting: 'جارٍ تحديد موقعك.',
    shown: 'موقعك: {coords}. يمكنك قراءة هذه الأرقام على 112.',
    copied: 'تم النسخ إلى الحافظة: {coords}.',
    copyfail: 'تعذّر النسخ. اقرأ الأرقام من الشاشة: {coords}.',
    denied: 'تعذّر تحديد موقعك. أخبر 112 بعنوانك.',
  }),
});

let activeDocument = null;
let previousInert = new Map();
let currentCoords = null;
let locationRequested = false;

export function pickLang(value) {
  const code = String(value ?? '').trim().toLowerCase().slice(0, 2);
  return code === 'en' || code === 'ar' ? code : 'tr';
}

function htmlLang(lang) {
  return lang === 'ar' ? ' lang="ar" dir="rtl"' : lang === 'en' ? ' lang="en"' : '';
}

export function cardMarkup(lang = 'tr') {
  const text = CARD_TEXT[pickLang(lang)];
  return `<section class="emergency-card" id="emergency-card" role="alertdialog" aria-modal="true" aria-labelledby="emergency-title" aria-describedby="emergency-desc"${htmlLang(pickLang(lang))}>`
    + `<h2 id="emergency-title">${text.title}</h2><p id="emergency-desc">${text.desc}</p>`
    + '<p class="emergency-live" aria-live="assertive"></p>'
    + `<a class="emergency-call" href="tel:112">${text.call}</a>`
    + `<button type="button" class="emergency-locate" data-act="locate">${text.locate}</button>`
    + '<p class="emergency-location" role="status"></p>'
    + `<button type="button" class="emergency-copy" data-act="copy" hidden>${text.copy}</button>`
    + `<a class="emergency-153" href="tel:153">${text.line153}</a>`
    + `<button type="button" class="emergency-back" data-act="back">${text.back}</button>`
    + `<p class="emergency-foot">${text.foot}</p></section>`;
}

export function formatCoords(lat, lon) {
  if (!Number.isFinite(lat) || !Number.isFinite(lon) || lat < -90 || lat > 90 || lon < -180 || lon > 180) {
    return null;
  }
  return `${lat.toFixed(5)}, ${lon.toFixed(5)}`;
}

export function locationMessage(kind, coords, lang = 'tr') {
  const text = LOCATION_TEXT[pickLang(lang)][kind] || LOCATION_TEXT.tr.denied;
  const safeCoords = coords == null ? '' : (pickLang(lang) === 'ar' ? `\u2066${coords}\u2069` : coords);
  return text.replace('{coords}', safeCoords);
}

function filled(value) {
  return typeof value === 'string' && value.trim().length > 0;
}

function emergencyMessage(doc) {
  return doc.querySelector('.chat-msg.is-emergency');
}

function resolveLang(doc, eventLang, message) {
  if (filled(eventLang)) return pickLang(eventLang);
  const messageLang = message?.closest('[lang]')?.lang;
  if (filled(messageLang)) return pickLang(messageLang);
  if (filled(doc.documentElement?.lang)) return pickLang(doc.documentElement.lang);
  return 'tr';
}

function addStylesheet(doc) {
  if (doc.querySelector('[data-emergency-styles]')) return;
  const link = doc.createElement('link');
  link.rel = 'stylesheet';
  link.href = '/css/emergency.css';
  link.setAttribute('data-emergency-styles', '');
  (doc.head || doc.documentElement).appendChild(link);
}

function setBackgroundInert(doc, card) {
  previousInert = new Map();
  for (const child of doc.body.children) {
    if (child === card) continue;
    previousInert.set(child, Boolean(child.inert));
    if (!child.inert) child.inert = true;
  }
  doc.documentElement.classList.add('emergency-open');
}

function restoreBackground(doc) {
  for (const [element, wasInert] of previousInert) {
    if (element.isConnected) element.inert = wasInert;
  }
  previousInert.clear();
  doc.documentElement.classList.remove('emergency-open');
}

function focusables(card) {
  return Array.from(card.querySelectorAll('a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])'))
    .filter((element) => !element.hidden && !element.inert);
}

function trapFocus(card, event) {
  if (event.key === 'Escape') {
    event.preventDefault();
    closeEmergency();
    return;
  }
  if (event.key !== 'Tab') return;
  const items = focusables(card);
  if (!items.length) return;
  const first = items[0];
  const last = items[items.length - 1];
  if (event.shiftKey && card.ownerDocument.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && card.ownerDocument.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function updateLocation(card, kind, coords, lang) {
  const status = card.querySelector('.emergency-location');
  status.textContent = locationMessage(kind, coords, lang);
  if (kind === 'shown') card.querySelector('[data-act="copy"]').hidden = false;
}

function locate(card, lang) {
  if (locationRequested) return;
  locationRequested = true;
  card.querySelector('[data-act="locate"]').disabled = true;
  updateLocation(card, 'waiting', null, lang);
  const geolocation = activeDocument?.defaultView?.navigator?.geolocation;
  const positionMethod = 'getCurrentPosition';
  const requestPosition = geolocation?.[positionMethod];
  if (typeof requestPosition !== 'function') {
    updateLocation(card, 'denied', null, lang);
    return;
  }
  requestPosition.call(
    geolocation,
    (position) => {
      const coords = formatCoords(position.coords.latitude, position.coords.longitude);
      if (!coords) {
        updateLocation(card, 'denied', null, lang);
        return;
      }
      currentCoords = coords;
      updateLocation(card, 'shown', coords, lang);
    },
    () => updateLocation(card, 'denied', null, lang),
    { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 },
  );
}

async function copyLocation(card, lang) {
  const clipboard = activeDocument?.defaultView?.navigator?.clipboard;
  if (!currentCoords || typeof clipboard?.writeText !== 'function') {
    updateLocation(card, 'copyfail', currentCoords, lang);
    return;
  }
  try {
    await clipboard.writeText(currentCoords);
    updateLocation(card, 'copied', currentCoords, lang);
  } catch {
    updateLocation(card, 'copyfail', currentCoords, lang);
  }
}

function wireCard(card, lang) {
  card.addEventListener('keydown', (event) => trapFocus(card, event));
  card.addEventListener('click', (event) => {
    const action = event.target?.closest?.('[data-act]');
    if (!action || !card.contains(action)) return;
    if (action.dataset.act === 'back') closeEmergency();
    if (action.dataset.act === 'locate') locate(card, lang);
    if (action.dataset.act === 'copy') void copyLocation(card, lang);
  });
}

export function openEmergency(lang) {
  const doc = activeDocument || (typeof document === 'undefined' ? null : document);
  if (!doc?.body) return;
  const current = doc.getElementById('emergency-card');
  if (current) {
    current.querySelector('.emergency-call')?.focus();
    return;
  }
  const message = emergencyMessage(doc);
  const selectedLang = resolveLang(doc, lang, message);
  const holder = doc.createElement('div');
  holder.innerHTML = cardMarkup(selectedLang);
  const card = holder.firstElementChild;
  doc.body.appendChild(card);
  setBackgroundInert(doc, card);
  card.querySelector('.emergency-live').textContent = CARD_TEXT[selectedLang].live;
  wireCard(card, selectedLang);
  currentCoords = null;
  locationRequested = false;
  card.querySelector('.emergency-call').focus();
}

export function closeEmergency() {
  const doc = activeDocument || (typeof document === 'undefined' ? null : document);
  const card = doc?.getElementById('emergency-card');
  if (!doc || !card) return;
  card.remove();
  restoreBackground(doc);
  currentCoords = null;
  locationRequested = false;
  doc.getElementById('chat-input')?.focus();
}

function markExistingMessages(log) {
  for (const message of log.querySelectorAll('.chat-msg.is-emergency')) {
    message.dataset.emergencySeen = '1';
  }
}

function inspectNode(node, doc) {
  if (node.nodeType !== 1) return;
  const candidates = [];
  if (node.matches?.('.chat-msg.is-emergency')) candidates.push(node);
  candidates.push(...node.querySelectorAll('.chat-msg.is-emergency'));
  for (const message of candidates) {
    if (message.dataset.emergencySeen === '1') continue;
    message.dataset.emergencySeen = '1';
    openEmergency(resolveLang(doc, null, message));
  }
}

export function mountEmergency(doc) {
  if (!doc || !doc.body || doc.__nabizEmergencyMounted) return;
  doc.__nabizEmergencyMounted = true;
  activeDocument = doc;
  addStylesheet(doc);
  doc.addEventListener(EMERGENCY_EVENT, (event) => openEmergency(resolveLang(doc, event.detail?.lang, emergencyMessage(doc))));
  const log = doc.getElementById('chat-log');
  if (!log) return;
  markExistingMessages(log);
  const MutationObserver = doc.defaultView?.MutationObserver || globalThis.MutationObserver;
  if (!MutationObserver) return;
  const observer = new MutationObserver((records) => {
    for (const record of records) {
      if (record.type === 'attributes') inspectNode(record.target, doc);
      for (const node of record.addedNodes) inspectNode(node, doc);
    }
  });
  observer.observe(log, { childList: true, subtree: true, attributes: true, attributeFilter: ['class'] });
}

if (typeof document !== 'undefined') mountEmergency(document);
