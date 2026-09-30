/* No button on these pages dials a number. Every tel: link (153 and any other) is caught here, on every page
   that loads this module, and answers with a note instead of opening the phone: the owner decided on 30 Sep
   that the prototype must never place a real call to an emergency or municipal line. */
import { t } from './i18n_text.js';

const NOTE_ID = 'mock-call-note';

function note(doc) {
  let box = doc.getElementById(NOTE_ID);
  if (!box) {
    box = doc.createElement('p');
    box.id = NOTE_ID;
    box.className = 'mock-call-note';
    box.setAttribute('role', 'status');
    box.setAttribute('aria-live', 'polite');
    doc.body.append(box);
  }
  return box;
}

export function onCallClick(event, doc = document) {
  const link = event.target?.closest?.('a[href^="tel:"]');
  if (!link) return false;
  event.preventDefault();
  event.stopPropagation();
  const box = note(doc);
  box.textContent = t('ui.mockcall.note', 'Örnek: Nabız gerçek arama yapmaz. Bu düğme yalnız gösterim içindir.');
  box.hidden = false;
  clearTimeout(box.timer);
  box.timer = setTimeout(() => { box.hidden = true; }, 4000);
  return true;
}

if (typeof document !== 'undefined') document.addEventListener('click', (event) => onCallClick(event), true);
