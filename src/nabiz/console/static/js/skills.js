/* E72 self-mounting course discovery. The module waits until its disclosure is opened before reading. */

import { get, post } from './api.js';
import { currentLang, onLang, t } from './i18n_text.js';
import { esc } from './format.js';
import {
  STORAGE_KEY, MAX_AREAS, MAX_SAVED, emptyState, parseStored, toStored, sectionMarkup,
} from './skills_view.js';

const ANCHORS = ['#city-tools', '#hesabim'];
const STYLESHEET = '/css/skills.css';
const SECTION_ID = 'kurs-is';
const CHECK_CODES = /^\d{1,12}$/;

function anchorFor(doc) {
  for (const selector of ANCHORS) {
    const node = doc.querySelector(selector);
    if (node) return { node, before: selector === '#hesabim' };
  }
  return null;
}

function addStyles(doc) {
  if (doc.querySelector(`link[data-e72-skills="${SECTION_ID}"]`)) return;
  const link = doc.createElement('link');
  link.rel = 'stylesheet';
  link.href = STYLESHEET;
  link.dataset.e72Skills = SECTION_ID;
  doc.head.append(link);
}

function readDeviceState() {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    const value = parseStored(raw);
    if (!value) {
      if (raw) window.localStorage.removeItem(STORAGE_KEY);
      return { ...emptyState(), consent: false };
    }
    return { ...value, consent: true };
  } catch (error) {
    return { ...emptyState(), consent: false };
  }
}

function mountSkills(doc = globalThis.document) {
  if (!doc || typeof doc.querySelector !== 'function' || doc.getElementById(SECTION_ID)) return null;
  const anchor = anchorFor(doc);
  if (!anchor) return null;
  addStyles(doc);
  const parent = anchor.node.parentNode;
  if (!parent) return null;
  const state = readDeviceState();
  let optionsData = null;
  let result = null;
  let status = '';
  let failure = '';
  let optionsLoading = false;
  let detail = doc.createElement('details');
  let checklists = {};

  const insert = (node) => {
    if (anchor.before) parent.insertBefore(node, anchor.node);
    else anchor.node.insertAdjacentElement('afterend', node);
  };
  const save = () => {
    try {
      const value = toStored(state.consent, state.choices, state.saved, state.checks);
      if (value) window.localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
      else window.localStorage.removeItem(STORAGE_KEY);
    } catch (error) { /* Private browsing keeps this visit in memory. */ }
  };
  const redraw = (focusResult = false) => {
    const wasOpen = detail.open;
    const template = doc.createElement('template');
    template.innerHTML = sectionMarkup(optionsData, state, status, result, checklists, failure);
    const next = template.content.firstElementChild;
    next.open = wasOpen;
    detail.replaceWith(next);
    detail = next;
    bind();
    if (focusResult) detail.querySelector('#kurs-is-sonuc-baslik, #kurs-is-sonuc-bos')?.focus();
  };
  const syncChoices = (form) => {
    const selectedBranch = form.querySelector('input[name="branch"]:checked');
    const selectedAreas = [...form.querySelectorAll('input[name="areas"]:checked')].map((node) => node.value);
    const field = new FormData(form);
    state.choices = {
      branch: selectedBranch ? selectedBranch.value : '', areas: selectedAreas.slice(0, MAX_AREAS),
      keyword: String(field.get('keyword') || '').trim(), district: String(field.get('district') || ''),
      mode: String(field.get('mode') || ''), time: String(field.get('time') || ''),
    };
  };
  const getChecklist = async (code) => {
    if (!CHECK_CODES.test(code) || checklists[code]) return;
    try {
      checklists[code] = await get('/api/skills/checklist', { code });
    } catch (error) {
      checklists[code] = { error: true };
      status = t('ui.skills.checklist_error', 'Resmî kontrol listesi okunamadı.');
    }
  };
  const getSavedChecklists = async () => {
    await Promise.all(state.saved.map((item) => getChecklist(item.code)));
    redraw();
  };
  const loadOptions = async () => {
    if (optionsLoading || optionsData) return;
    optionsLoading = true;
    status = t('ui.skills.loading', 'Katalog okunuyor.');
    redraw();
    try {
      optionsData = await get('/api/skills/options');
      failure = optionsData.available ? '' : (optionsData.reason || t('ui.skills.unavailable', 'Katalog şu an okunamadı.'));
      status = optionsData.available ? t('ui.skills.loaded', 'Katalog verisi okundu.') : failure;
      if (optionsData.available && state.saved.length) await getSavedChecklists();
    } catch (error) {
      failure = t('ui.skills.offline', 'Katalog şu an okunamadı.');
      status = failure;
    } finally {
      optionsLoading = false;
      redraw();
    }
  };
  const bind = () => {
    detail.addEventListener('toggle', () => { if (detail.open) void loadOptions(); });
    const form = detail.querySelector('.skills-form');
    if (form) {
      form.addEventListener('change', (event) => {
        const target = event.target;
        if (target.name === 'consent') {
          state.consent = target.checked;
          save();
          return;
        }
        let notice = '';
        if (target.name === 'areas') {
          const selected = form.querySelectorAll('input[name="areas"]:checked');
          if (selected.length > MAX_AREAS) {
            target.checked = false;
            notice = t('ui.skills.area_limit', 'En çok üç alan seçebilirsiniz.');
          }
        }
        syncChoices(form);
        if (target.name === 'branch') state.choices.areas = state.choices.areas.filter((name) => (
          (optionsData.areas || []).some((area) => area.name === name && area.branch === state.choices.branch)
        ));
        result = null;
        failure = '';
        status = notice;
        save();
        redraw();
      });
      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        syncChoices(form);
        save();
        result = null;
        failure = '';
        status = t('ui.skills.loading_matches', 'Eşleşmeler hazırlanıyor.');
        redraw();
        try {
          result = await post('/api/skills/match', state.choices);
          const count = (result.programs || []).length;
          const centers = (result.centers || []).length;
          status = result.available
            ? t('ui.skills.result_count', '{programs} program adı, {centers} merkez', { programs: count, centers })
            : (result.reason || t('ui.skills.unavailable', 'Katalog şu an okunamadı.'));
          failure = result.available ? '' : status;
          await getSavedChecklists();
        } catch (error) {
          failure = error.status === 400 ? t('ui.skills.bad_request', 'Seçimleri kontrol edip yeniden deneyin.') : t('ui.skills.offline', 'Katalog şu an okunamadı.');
          status = failure;
        }
        redraw(true);
      });
    }
    detail.addEventListener('change', (event) => {
      const code = event.target.dataset.checkCode;
      if (code) {
        const ids = new Set(state.checks[code] || []);
        if (event.target.checked) ids.add(event.target.value); else ids.delete(event.target.value);
        state.checks[code] = [...ids];
        save();
      }
    });
    detail.addEventListener('click', async (event) => {
      const addCode = event.target.closest('[data-add-code]')?.dataset.addCode;
      const removeCode = event.target.closest('[data-remove-code]')?.dataset.removeCode;
      if (event.target.closest('[data-action="clear"]')) {
        state.choices = { ...emptyState().choices };
        result = null;
        status = '';
        save();
        redraw();
      } else if (event.target.closest('[data-action="erase"]')) {
        Object.assign(state, { ...emptyState(), consent: false });
        result = null;
        checklists = {};
        status = t('ui.skills.erased', 'Bu cihazdaki liste silindi.');
        save();
        redraw();
      } else if (addCode && CHECK_CODES.test(addCode)) {
        if (state.saved.length >= MAX_SAVED) {
          status = t('ui.skills.list_limit', 'En çok beş program ekleyebilirsiniz.');
        } else if (!state.saved.some((item) => item.code === addCode)) {
          const item = (result?.programs || []).find((program) => program.code === addCode);
          if (item) {
            state.saved.push({ code: item.code, name: item.name, url: item.url });
            await getChecklist(item.code);
            status = t('ui.skills.added', 'Program listenize eklendi.');
            save();
          }
        }
        redraw();
      } else if (removeCode) {
        state.saved = state.saved.filter((item) => item.code !== removeCode);
        delete state.checks[removeCode];
        delete checklists[removeCode];
        save();
        redraw();
      }
    });
  };

  const placeholder = doc.createElement('template');
  placeholder.innerHTML = sectionMarkup(null, state, t('ui.skills.open_to_load', 'Kataloğu okumak için bölümü açın.'), null, {}, '');
  detail = placeholder.content.firstElementChild;
  insert(detail);
  bind();
  onLang(() => redraw());
  return detail;
}

if (typeof document !== 'undefined') mountSkills(document);

export { ANCHORS, STYLESHEET, SECTION_ID, mountSkills };
