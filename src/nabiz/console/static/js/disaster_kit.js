/* A source-led household file. Personal notes stay in this browser and are never request data. */

import { MOCK, get } from './api.js';
import { currentLang, onLang, t } from './i18n_text.js';
import { esc } from './format.js';
import { icon } from './icons.js';

const STATE_KEY = 'nabiz.disaster.v1';
const CATALOG_KEY = 'nabiz.disaster.catalog.v1';
const TEXT_FIELDS = ['bag_place', 'meet_near', 'meet_far', 'assembly_note'];

function planLabel(field) {
  if (field === 'bag_place') return t('ui.disaster.bag_place', 'Çantamız nerede duruyor');
  if (field === 'meet_near') return t('ui.disaster.meet_near', 'Evin yakınında buluşma yeri');
  if (field === 'meet_far') return t('ui.disaster.meet_far', 'Mahalle dışında buluşma yeri');
  return t('ui.disaster.assembly_note', 'Bildiğim toplanma alanı');
}

function blankState() {
  return { version: 1, consent: false, items: {}, plan: { bag_place: '', meet_near: '', meet_far: '', assembly_note: '', contacts: [] }, print_contacts: false, reviewed_at: null, saved_at: null };
}

function browserStorage() { try { return window.localStorage; } catch { return null; } }

export function readKit(storage) {
  try {
    const value = JSON.parse(storage.getItem(STATE_KEY) || 'null');
    if (!value || value.version !== 1 || value.consent !== true) return blankState();
    const plan = value.plan && typeof value.plan === 'object' ? value.plan : {};
    const fields = Object.fromEntries(TEXT_FIELDS.map((field) => [field, typeof plan[field] === 'string' ? plan[field].slice(0, 80) : '']));
    const contacts = (Array.isArray(plan.contacts) ? plan.contacts : []).slice(0, 3).map((person) => ({
      name: typeof person?.name === 'string' ? person.name.slice(0, 40) : '', phone: typeof person?.phone === 'string' ? person.phone.slice(0, 32) : '',
    }));
    return {
      ...blankState(), ...value, consent: true,
      items: value.items && typeof value.items === 'object' ? value.items : {},
      plan: { ...fields, contacts },
      print_contacts: value.print_contacts === true,
    };
  } catch { return blankState(); }
}

export function writeKit(storage, state) { if (!storage || !state || state.consent !== true) return false; try { storage.setItem(STATE_KEY, JSON.stringify(state)); return true; } catch { return false; } }

export function clearKit(storage) { try { storage.removeItem(STATE_KEY); return true; } catch { return false; } }

export function kitProgress(state, items) {
  const list = Array.isArray(items) ? items : [], checks = state?.items && typeof state.items === 'object' ? state.items : {};
  return { done: list.filter((item) => checks[item.id]?.checked === true).length, total: list.length };
}

export function checkPlan(plan) {
  const value = plan && typeof plan === 'object' ? plan : {};
  const errors = [];
  for (const field of TEXT_FIELDS) {
    const text = typeof value[field] === 'string' ? value[field] : '';
    if (text.length > 80) errors.push({ field, code: 'too_long' });
    if (/\d{6,}/.test(text)) errors.push({ field, code: 'digits' });
  }
  const contacts = Array.isArray(value.contacts) ? value.contacts : [];
  if (contacts.length > 3) errors.push({ field: 'contacts', code: 'too_many' });
  contacts.slice(0, 3).forEach((person, index) => {
    const name = typeof person?.name === 'string' ? person.name : '', phone = typeof person?.phone === 'string' ? person.phone : '';
    if (name.length > 40) errors.push({ field: `contact-${index}-name`, code: 'too_long' });
    if (/\d{6,}/.test(name)) errors.push({ field: `contact-${index}-name`, code: 'digits' });
    const normalized = phone.replace(/[\s\-()]/g, '');
    if (normalized && !/^(?:\+90|0)?\d{10}$/.test(normalized)) errors.push({ field: `contact-${index}-phone`, code: 'phone_format' });
  });
  return { ok: errors.length === 0, errors };
}

function readCatalog(storage) {
  try {
    const saved = JSON.parse(storage.getItem(CATALOG_KEY) || 'null');
    return saved && saved.data && typeof saved.saved_at === 'string' ? saved : null;
  } catch { return null; }
}

function saveCatalog(storage, data, lang) {
  try { storage.setItem(CATALOG_KEY, JSON.stringify({ saved_at: new Date().toISOString(), lang, data })); return true; } catch { return false; }
}

function formatDate(value, withTime = false) {
  const stamp = Date.parse(value || '');
  if (!Number.isFinite(stamp)) return t('ui.disaster.no_date', 'bilinmiyor');
  return new Intl.DateTimeFormat(currentLang() === 'en' ? 'en-GB' : 'tr-TR', {
    timeZone: 'Europe/Istanbul', day: '2-digit', month: '2-digit', year: 'numeric', ...(withTime ? { hour: '2-digit', minute: '2-digit' } : {}),
  }).format(stamp);
}

const dateOnly = (value) => formatDate(value);
const dateTime = (value) => formatDate(value, true);

function sourceMarkup(source, quote, quoteId) {
  if (!source) return '';
  const updated = source.source_updated_at
    ? t('ui.disaster.updated', 'sayfa güncellemesi {date}', { date: dateOnly(source.source_updated_at) })
    : t('ui.disaster.no_update', 'sayfada tarih yok');
  const saved = t('ui.disaster.saved_date', 'kaydedildi {date}', { date: dateOnly(source.fetched_at) });
  const open = t('ui.disaster.open_source', 'Kaynağı aç');
  const newTab = t('ui.disaster.new_tab', 'yeni sekmede açılır');
  const quoteBlock = quote ? `<details class="disaster-quote"><summary>${esc(t('ui.disaster.quote_toggle', 'Kaynaktaki metin'))}</summary><blockquote lang="tr">${esc(quote)}</blockquote></details>` : '';
  return `<div class="disaster-source" id="${esc(quoteId || '')}" lang="${currentLang()}">
    <span>${esc(source.institution || '')} · ${esc(source.title || '')} · ${esc(updated)} · ${esc(saved)}</span>
    <a href="${esc(source.url)}" target="_blank" rel="noopener">${icon('external-link')}${esc(open)}<span class="sr-only">, ${esc(newTab)}</span></a>
    ${quoteBlock}</div>`;
}

function fieldMarkup(id, label, maxLength, value, error) {
  const errorId = `afet-error-${id}`;
  const message = error ? fieldError(error) : '';
  return `<div class="disaster-field"><label for="afet-${id}">${esc(label)}</label>
    <textarea id="afet-${id}" name="${id}" rows="2" maxlength="${maxLength}" aria-describedby="${error ? errorId : ''}">${esc(value || '')}</textarea>
    <p class="disaster-error" id="${errorId}" ${error ? '' : 'hidden'}>${esc(message)}</p></div>`;
}

function contactMarkup(contacts, errors) {
  if (!contacts.length) return '';
  return `<div class="disaster-contact-list">${contacts.slice(0, 3).map((person, index) => {
    const nameField = `contact-${index}-name`, phoneField = `contact-${index}-phone`;
    const nameError = errors.find((item) => item.field === nameField)?.code, phoneError = errors.find((item) => item.field === phoneField)?.code;
    const nameErrorId = `afet-error-${nameField}`, phoneErrorId = `afet-error-${phoneField}`;
    return `<fieldset class="disaster-contact"><legend>${esc(t('ui.disaster.person', 'Kişi {number}', { number: index + 1 }))}</legend><div class="disaster-contact-fields">
      <div class="disaster-field"><label for="afet-${nameField}">${esc(t('ui.disaster.person_name', 'Ad ya da yakınlık'))}</label><input id="afet-${nameField}" data-contact-name="${index}" maxlength="40" autocomplete="off" value="${esc(person.name)}" aria-describedby="${nameError ? nameErrorId : ''}"><p class="disaster-error" id="${nameErrorId}" ${nameError ? '' : 'hidden'}>${esc(fieldError(nameError))}</p></div>
      <div class="disaster-field"><label for="afet-${phoneField}">${esc(t('ui.disaster.phone', 'Telefon'))}</label><input id="afet-${phoneField}" type="tel" inputmode="tel" data-contact-phone="${index}" maxlength="32" autocomplete="off" value="${esc(person.phone)}" aria-describedby="${phoneError ? phoneErrorId : ''}"><p class="disaster-error" id="${phoneErrorId}" ${phoneError ? '' : 'hidden'}>${esc(fieldError(phoneError))}</p></div>
      </div><button class="btn btn-quiet disaster-remove" type="button" data-remove-contact="${index}">${esc(t('ui.disaster.remove_person', 'Kişiyi kaldır'))}</button></fieldset>`;
  }).join('')}</div>`;
}

function fieldError(code) {
  if (code === 'too_long') return t('ui.disaster.error_too_long', 'Bu alanın sınırını kısaltın.');
  if (code === 'digits') return t('ui.disaster.error_digits', 'Bu alana numara yazmayın; kimlik ya da adres numarası gerekmez.');
  if (code === 'phone_format') return t('ui.disaster.error_phone_format', 'Telefonu ülke koduyla ya da başında 0 ile yazın.');
  return '';
}

export function reviewDue(state, now = new Date()) {
  const checks = state?.items && typeof state.items === 'object' ? state.items : {};
  const nowMs = now instanceof Date ? now.getTime() : Date.parse(now);
  if (!Number.isFinite(nowMs)) return [];
  const due = [];
  for (const id of ['su', 'gida']) {
    const stamp = Date.parse(checks[id]?.checked_at || '');
    if (checks[id]?.checked && Number.isFinite(stamp) && nowMs - stamp >= 182 * 86400000) {
      due.push({ id: 'six_months', since: new Date(stamp).toISOString() });
      break;
    }
  }
  const checked = Object.values(checks).filter((item) => item?.checked === true).map((item) => Date.parse(item.checked_at || '')).filter(Number.isFinite);
  if (checked.length) {
    const reviewed = Date.parse(state?.reviewed_at || '');
    if (!Number.isFinite(reviewed) || nowMs - reviewed >= 365 * 86400000) {
      due.push({ id: 'yearly', since: Number.isFinite(reviewed) ? new Date(reviewed).toISOString() : new Date(Math.min(...checked)).toISOString() });
    }
  }
  return due;
}

export function printKit(doc) {
  const root = doc?.getElementById('afet-detail');
  if (!root || !doc.defaultView || typeof doc.defaultView.print !== 'function') return false;
  const wasOpen = root.open;
  const opened = [...root.querySelectorAll('details')].map((node) => [node, node.open]);
  root.open = true;
  opened.forEach(([node]) => { node.open = true; });
  root.dataset.printContacts = doc.getElementById('afet-print-contacts')?.checked ? 'true' : 'false';
  doc.documentElement.classList.add('nd-print-afet');
  const finish = () => {
    doc.documentElement.classList.remove('nd-print-afet');
    opened.forEach(([node, wasOpen]) => { node.open = wasOpen; });
    root.open = wasOpen;
  };
  doc.defaultView.addEventListener('afterprint', finish, { once: true });
  doc.defaultView.print();
  return true;
}

export function mountDisasterKit(doc) {
  const host = doc.getElementById('hesabim');
  if (!host || doc.getElementById('afet-detail')) return null;
  if (!doc.querySelector('link[data-disaster-kit-style]')) {
    const link = doc.createElement('link');
    link.rel = 'stylesheet';
    link.href = new URL('../css/disaster_kit.css', import.meta.url).href;
    link.dataset.disasterKitStyle = 'true';
    doc.head.append(link);
  }
  const detail = doc.createElement('details');
  detail.id = 'afet-detail';
  detail.className = 'more account-detail';
  detail.innerHTML = `<summary><h2 id="disaster-title" tabindex="-1"></h2></summary><section id="afet-dosyasi" aria-labelledby="disaster-title"></section>`;
  detail.querySelector('#afet-dosyasi').className = 'disaster-section';
  host.append(detail);

  const title = detail.querySelector('#disaster-title');
  const section = detail.querySelector('#afet-dosyasi');
  const storage = browserStorage();
  let state = readKit(storage);
  let draftPlan = { ...state.plan, contacts: state.plan.contacts.map((person) => ({ ...person })) };
  let cached = readCatalog(storage);
  let data = null;
  let view = MOCK ? 'mock' : 'idle';
  let request = 0;
  let deleteArmed = false;
  let planErrors = [];

  function sourceFor(id) { return data?.sources?.[id] || null; }
  function setStateLine(text) {
    const status = section.querySelector('#afet-state-status');
    if (status) status.textContent = text;
  }
  function saveState() {
    state.saved_at = new Date().toISOString();
    if (!state.consent) {
      setStateLine(t('ui.disaster.save_off', 'Kaydetme kapalı; sayfa yenilenince işaretler silinir.'));
      return false;
    }
    if (writeKit(storage, state)) {
      setStateLine(t('ui.disaster.saved', 'Bu cihazda kaydedildi, {time}', { time: dateTime(state.saved_at) }));
      return true;
    }
    setStateLine(t('ui.disaster.storage_closed', 'Bu tarayıcıda saklama kapalı.'));
    return false;
  }
  function savePlan() {
    const checked = checkPlan(draftPlan);
    planErrors = checked.errors;
    state.plan = { ...state.plan };
    for (const field of TEXT_FIELDS) {
      if (!planErrors.some((item) => item.field === field)) state.plan[field] = draftPlan[field] || '';
    }
    state.plan.contacts = draftPlan.contacts.slice(0, 3).map((person, index) => ({
      name: planErrors.some((item) => item.field === `contact-${index}-name`) ? '' : person.name || '',
      phone: planErrors.some((item) => item.field === `contact-${index}-phone`) ? '' : person.phone || '',
    })).filter((person) => person.name || person.phone);
    state.print_contacts = Boolean(draftPlan.print_contacts);
    applyPlanErrors();
    saveState();
  }
  function applyPlanErrors() {
    section.querySelectorAll('.disaster-field').forEach((field) => {
      const input = field.querySelector('[name], [data-contact-name], [data-contact-phone]');
      if (!input) return;
      const fieldId = input.name || `contact-${input.dataset.contactName ?? input.dataset.contactPhone}-${input.dataset.contactName !== undefined ? 'name' : 'phone'}`;
      const error = planErrors.find((item) => item.field === fieldId)?.code;
      const errorNode = field.querySelector('.disaster-error');
      input.setAttribute('aria-describedby', error ? errorNode.id : '');
      errorNode.textContent = fieldError(error);
      errorNode.hidden = !error;
    });
  }
  function renderContacts() {
    const target = section.querySelector('#afet-contacts');
    const empty = t('ui.disaster.no_people', 'Henüz kişi eklenmedi.');
    target.innerHTML = draftPlan.contacts.length
      ? contactMarkup(draftPlan.contacts, planErrors)
      : `<p class="disaster-no-people">${esc(empty)}</p>`;
    const add = section.querySelector('#afet-add-person');
    add.disabled = draftPlan.contacts.length >= 3;
  }
  function renderReview() {
    const target = section.querySelector('#afet-review');
    if (!target || !data) return;
    const due = reviewDue(state);
    if (!due.length) { target.innerHTML = ''; return; }
    const note = (id) => data.care.find((item) => item.id === id);
    const rows = due.map((item) => {
      const care = note(item.id === 'six_months' ? 'su_gida' : 'yillik_gozden_gecirme');
      const line = item.id === 'six_months'
        ? t('ui.disaster.review_six_months', 'Su ya da gıda maddesini gözden geçirme zamanı.')
        : t('ui.disaster.review_yearly', 'Çanta içeriğini ve ailenizin gereksinimlerini gözden geçirme zamanı.');
      return `<li><p>${esc(line)}</p>${care ? `<details class="disaster-quote"><summary>${esc(t('ui.disaster.quote_toggle', 'Kaynaktaki metin'))}</summary><blockquote lang="tr">${esc(care.quote)}</blockquote></details>` : ''}</li>`;
    }).join('');
    target.innerHTML = `<ul>${rows}</ul><button class="btn btn-quiet" id="afet-reviewed" type="button">${esc(t('ui.disaster.review_done', 'Gözden geçirdim'))}</button>`;
    target.querySelector('#afet-reviewed').addEventListener('click', () => {
      state.reviewed_at = new Date().toISOString();
      saveState();
      renderReview();
    });
  }
  function drawChrome() {
    const lang = currentLang();
    title.textContent = t('ui.disaster.title', 'Afet hazırlık dosyam');
    title.lang = lang;
    const notice = data?.notice || t('ui.disaster.notice', 'Bu dosya yalnız bu cihazda durur. Nabız binanızın ya da evinizin güvenliği hakkında değerlendirme yapmaz. Resmî İBB hizmeti değildir.');
    const offlineNote = t('ui.disaster.offline_note', 'Kaynak listesi çevrimdışı kullanım için bu cihazda saklanır.');
    const progress = data ? kitProgress(state, data.items) : { done: 0, total: 0 };
    const bagItems = data ? data.items.map((item) => `<label class="disaster-item"><input type="checkbox" data-kit-item="${esc(item.id)}" ${state.items[item.id]?.checked ? 'checked' : ''}><span>${esc(item.label)}</span></label>`).join('') : '';
    const bagStatus = view === 'loading' ? t('ui.disaster.loading', 'Kaynaklı liste yükleniyor.')
      : view === 'error' ? t('ui.disaster.failed', 'Kaynaklı liste alınamadı.')
        : view === 'mock' ? t('ui.disaster.mock', 'Örnek veri kipinde afet dosyası kapalı.')
          : data ? t('ui.disaster.count', '{total} maddeden {done} işaretli', progress) : t('ui.disaster.empty', 'Kaynaklı liste henüz alınmadı.');
    const bagSource = data ? sourceMarkup(sourceFor('akom_sss')) : '';
    const quoteTitle = t('ui.disaster.quote_toggle', 'Kaynaktaki metin');
    const care = data ? `<details id="afet-care"><summary>${esc(t('ui.disaster.care_title', 'Çantanın bakımı'))}</summary><ul class="disaster-care">${data.care.map((item) => `<li><p>${esc(item.text)}</p><details class="disaster-quote"><summary>${esc(quoteTitle)}</summary><blockquote lang="tr">${esc(item.quote)}</blockquote></details></li>`).join('')}</ul>${bagSource}</details>` : '';
    const planFields = TEXT_FIELDS.map((id) => fieldMarkup(id, planLabel(id), 80, draftPlan[id], planErrors.find((item) => item.field === id)?.code)).join('');
    const contacts = data ? sourceMarkup(sourceFor(data.contact_basis.source), data.contact_basis.quote, 'afet-contact-basis') : '';
    const assemblyText = data?.assembly?.dataset_found
      ? t('ui.disaster.assembly_found', 'Katalogda bir veri seti bulundu: {name}', { name: data.assembly.dataset_name || '' })
      : data ? t('ui.disaster.assembly_missing', 'İBB açık veri kataloğunda toplanma alanı veri seti bulunamadı ({count} veri seti tarandı, kaydedildi {date}). Nabız toplanma alanı göstermez.', {
        count: data.assembly.catalog_check.count, date: dateOnly(data.assembly.catalog_check.captured_at_utc),
      }) : '';
    const assemblyCards = data ? [
      `<article><p>${esc(sourceFor(data.assembly.plan_mention.source)?.note || '')}</p>${sourceMarkup(sourceFor(data.assembly.plan_mention.source), data.assembly.plan_mention.quote)}</article>`,
      `<article>${sourceMarkup(sourceFor(data.assembly.afis.source), data.assembly.afis.quote)}</article>`,
    ].join('') : '';
    const buildingQuotes = data ? data.building.quotes.map((item) => `<li><details class="disaster-quote"><summary>${esc(quoteTitle)}</summary><blockquote lang="tr">${esc(item.quote)}</blockquote></details></li>`).join('') : '';
    const buildingSource = data ? sourceMarkup(sourceFor('bina_sss')) : '';
    const cacheText = view === 'cached' && cached
      ? `<p class="disaster-state" role="status">${icon('cloud-off')}${esc(t('ui.disaster.cached', 'Kaydedilen kopya ({date})', { date: dateOnly(cached.saved_at) }))}</p>` : '';
    const call = data?.channels?.call || t('ui.disaster.call_number', '153');
    const errorText = view === 'error' ? `<p class="disaster-state" role="status">${esc(t('ui.disaster.error_next', 'Kaynaklar alınamadı. Bağlantıyı yeniden deneyin ya da 153’ü arayın.'))} <a href="tel:${esc(call)}">${esc(call)}</a></p>` : '';
    const saveStatus = state.consent && state.saved_at ? t('ui.disaster.saved', 'Bu cihazda kaydedildi, {time}', { time: dateTime(state.saved_at) }) : t('ui.disaster.save_off', 'Kaydetme kapalı; sayfa yenilenince işaretler silinir.');
    section.innerHTML = `<p class="disaster-notice">${esc(notice)}</p><p class="disaster-state">${esc(offlineNote)}</p>${cacheText}${errorText}
      <fieldset id="afet-canta" class="disaster-block" aria-labelledby="afet-canta-title"><legend id="afet-canta-title">${esc(t('ui.disaster.bag_title', 'Afet çantası'))}</legend><span class="disaster-badge">${esc(t('ui.disaster.institution_badge', 'Kurum kaynağı: AKOM'))}</span><p id="afet-kit-count" class="disaster-state" role="status" aria-live="polite">${esc(bagStatus)}</p><div class="disaster-items">${bagItems}</div>${bagSource}${care}</fieldset>
      <form id="afet-plan" class="disaster-block" novalidate><h3>${esc(t('ui.disaster.plan_title', 'Aile planı'))}</h3><span class="disaster-badge">${esc(t('ui.disaster.personal_badge', 'Sizin notunuz, Nabız doğrulamaz'))}</span>${planFields}<div class="disaster-field"><h4>${esc(t('ui.disaster.contacts_title', 'İletişime geçilecek kişiler'))}</h4>${contacts}<div id="afet-contacts"></div><button class="btn btn-quiet" id="afet-add-person" type="button">${esc(t('ui.disaster.add_person', 'Kişi ekle'))}</button></div>
        <label class="disaster-consent"><input id="afet-consent" type="checkbox" ${state.consent ? 'checked' : ''}><span>${esc(t('ui.disaster.consent', 'Bu dosyayı yalnız bu cihazda sakla'))}</span></label><p class="disaster-state" id="afet-state-status" role="status" aria-live="polite">${esc(saveStatus)}</p></form>
      <div id="afet-review" class="disaster-review"></div><section id="afet-toplanma" class="disaster-block"><h3>${esc(t('ui.disaster.assembly_title', 'Toplanma alanı'))}</h3><p>${esc(assemblyText)}</p>${assemblyCards}</section>
      <details id="afet-bina" class="disaster-block"><summary><h3>${esc(t('ui.disaster.building_title', 'Binam'))}</h3></summary><p>${esc(t('ui.disaster.building_notice', 'Nabız binanızın durumu hakkında değerlendirme yapmaz ve fotoğraf almaz.'))}</p><ul class="disaster-building-quotes">${buildingQuotes}</ul>${buildingSource}</details>
      <div class="disaster-actions"><button class="btn btn-primary" id="afet-print" type="button">${icon('list-details')}${esc(t('ui.disaster.print', 'Yazdır ya da PDF olarak kaydet'))}</button><label class="disaster-consent disaster-print-option"><input id="afet-print-contacts" type="checkbox" ${state.print_contacts ? 'checked' : ''}><span>${esc(t('ui.disaster.print_contacts', 'Yazdırırken kişileri de ekle'))}</span></label><button class="btn btn-quiet" id="afet-delete" type="button">${esc(deleteArmed ? t('ui.disaster.delete_again', 'Silmek için yeniden basın') : t('ui.disaster.delete', 'Bu cihazdaki afet dosyasını sil'))}</button></div>
      <p class="disaster-print-footer">${esc(data?.disclaimer || t('ui.disaster.disclaimer', 'Resmî İBB hizmeti değildir.'))} <span>${esc(t('ui.disaster.printed_on', 'Yazdırma tarihi: {date}', { date: dateOnly(new Date().toISOString()) }))}</span></p>`;
    renderContacts();
    renderReview();
    bindControls();
  }
  function bindControls() {
    section.querySelector('#afet-plan').addEventListener('submit', (event) => event.preventDefault());
    section.querySelector('#afet-canta')?.addEventListener('change', (event) => {
      const input = event.target.closest('[data-kit-item]');
      if (!input || !data) return;
      if (input.checked) state.items[input.dataset.kitItem] = { checked: true, checked_at: new Date().toISOString() };
      else delete state.items[input.dataset.kitItem];
      const progress = kitProgress(state, data.items);
      section.querySelector('#afet-kit-count').textContent = t('ui.disaster.count', '{total} maddeden {done} işaretli', progress);
      saveState();
      renderReview();
    });
    section.querySelector('#afet-plan').addEventListener('change', (event) => {
      if (event.target.id === 'afet-consent') {
        state.consent = event.target.checked;
        if (state.consent) saveState();
        else if (clearKit(storage)) setStateLine(t('ui.disaster.save_off', 'Kaydetme kapalı; sayfa yenilenince işaretler silinir.'));
        else setStateLine(t('ui.disaster.storage_closed', 'Bu tarayıcıda saklama kapalı.'));
        return;
      }
      const form = event.currentTarget;
      draftPlan = {
        ...draftPlan,
        bag_place: form.elements.bag_place.value,
        meet_near: form.elements.meet_near.value,
        meet_far: form.elements.meet_far.value,
        assembly_note: form.elements.assembly_note.value,
        contacts: [...form.querySelectorAll('[data-contact-name]')].map((input, index) => ({
          name: input.value, phone: form.querySelector(`[data-contact-phone="${index}"]`)?.value || '',
        })),
      };
      savePlan();
    });
    section.querySelector('#afet-plan').addEventListener('click', (event) => {
      const remove = event.target.closest('[data-remove-contact]');
      if (remove) {
        draftPlan.contacts.splice(Number(remove.dataset.removeContact), 1);
        savePlan();
        renderContacts();
      }
    });
    section.querySelector('#afet-add-person').addEventListener('click', () => {
      if (draftPlan.contacts.length >= 3) return;
      draftPlan.contacts.push({ name: '', phone: '' });
      renderContacts();
      section.querySelector(`[data-contact-name="${draftPlan.contacts.length - 1}"]`)?.focus();
    });
    section.querySelector('#afet-print-contacts').addEventListener('change', (event) => {
      draftPlan.print_contacts = event.target.checked;
      state.print_contacts = event.target.checked;
      saveState();
    });
    section.querySelector('#afet-print').addEventListener('click', () => printKit(doc));
    section.querySelector('#afet-delete').addEventListener('click', () => {
      if (!deleteArmed) { deleteArmed = true; drawChrome(); return; }
      if (!clearKit(storage)) { setStateLine(t('ui.disaster.storage_closed', 'Bu tarayıcıda saklama kapalı.')); return; }
      state = blankState();
      draftPlan = { ...state.plan, contacts: [] };
      deleteArmed = false;
      planErrors = [];
      drawChrome();
      setStateLine(t('ui.disaster.deleted', 'Bu cihazdaki afet dosyası silindi.'));
    });
  }
  async function loadData() {
    if (MOCK) { view = 'mock'; drawChrome(); return; }
    const mine = ++request;
    const lang = currentLang() === 'en' ? 'en' : 'tr';
    view = 'loading';
    drawChrome();
    try {
      const result = await get('/api/disaster-kit', { lang });
      if (mine !== request) return;
      data = result;
      cached = { saved_at: new Date().toISOString(), lang, data: result };
      saveCatalog(storage, result, lang);
      view = 'ready';
    } catch {
      if (mine !== request) return;
      cached = readCatalog(storage);
      if (cached) { data = cached.data; view = 'cached'; }
      else { data = null; view = 'error'; }
    }
    drawChrome();
  }

  drawChrome();
  detail.addEventListener('toggle', () => { if (detail.open && (view === 'idle' || view === 'error')) void loadData(); });
  onLang(() => { drawChrome(); if (detail.open) void loadData(); });
  if (doc.defaultView?.location?.hash === '#afet') {
    detail.open = true;
    title.focus();
    if (view === 'idle') void loadData();
  }
  return detail;
}

if (typeof document !== 'undefined') mountDisasterKit(document);
