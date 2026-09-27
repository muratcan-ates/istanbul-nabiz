/* Pure selection and markup helpers for the device-local suggestions section. */

import { t } from './i18n_text.js';
import { esc } from './format.js';
import { icon } from './icons.js';

export const AUDIENCE_KEY = 'nabiz.audience.v1';

export const GROUPS = [
  { id: 'ogrenci', kind: 'age', label: () => t('ui.aud.g_ogrenci', 'Öğrenci'), hint: () => t('ui.aud.h_ogrenci', 'Kart, kütüphane ve kurslar') },
  { id: 'calisan', kind: 'age', label: () => t('ui.aud.g_calisan', 'Çalışan'), hint: () => t('ui.aud.h_calisan', 'Günlük yol, durak ve otopark') },
  { id: 'yas65', kind: 'age', label: () => t('ui.aud.g_yas65', '65 yaş ve üstü'), hint: () => t('ui.aud.h_yas65', 'Sağlık ve sosyal hizmetler, adımsız yol') },
  { id: 'tekerlekli', kind: 'need', label: () => t('ui.aud.g_tekerlekli', 'Tekerlekli sandalye'), hint: () => t('ui.aud.h_tekerlekli', 'Asansör ve adımsız yol') },
  { id: 'gorme', kind: 'need', label: () => t('ui.aud.g_gorme', 'Görme'), hint: () => t('ui.aud.h_gorme', 'Az görme ya da ekran okuyucu') },
  { id: 'isitme', kind: 'need', label: () => t('ui.aud.g_isitme', 'İşitme'), hint: () => t('ui.aud.h_isitme', 'Yazılı bilgi ve yazılı iletişim') },
  { id: 'bilissel', kind: 'need', label: () => t('ui.aud.g_bilissel', 'Bilişsel kolaylık'), hint: () => t('ui.aud.h_bilissel', 'Kısa ve sade anlatım') },
  { id: 'turist', kind: 'need', label: () => t('ui.aud.g_turist', 'Turist'), hint: () => t('ui.aud.h_turist', 'Şehre yeni gelenler için') },
];

const GROUP_IDS = new Set(GROUPS.map((group) => group.id));
const AGE_IDS = new Set(GROUPS.filter((group) => group.kind === 'age').map((group) => group.id));
const PROFILE_NEEDS = {
  step_free: () => t('ui.aud.need_step_free', 'Adımsız erişim'),
  low_vision: () => t('ui.aud.need_low_vision', 'Az görüyorum'),
  hearing: () => t('ui.aud.need_hearing', 'Az duyuyorum'),
  plain_language: () => t('ui.aud.need_plain_language', 'Sade dil'),
};
const PERSONA_BY_GROUP = {
  tekerlekli: 'hareket', gorme: 'gorme', isitme: 'isitme', bilissel: 'okuma', yas65: 'yasli', turist: 'yabanci',
};

function emptySelection() {
  return { version: 1, age: null, needs: [], kolay_hidden: false };
}

export function parseSelection(raw) {
  let value = raw;
  if (typeof raw === 'string') {
    try { value = JSON.parse(raw); } catch (error) { return emptySelection(); }
  }
  if (!value || typeof value !== 'object' || Array.isArray(value) || value.version !== 1) return emptySelection();
  const age = AGE_IDS.has(value.age) ? value.age : null;
  const needs = Array.isArray(value.needs)
    ? [...new Set(value.needs.filter((need) => GROUP_IDS.has(need) && !AGE_IDS.has(need)))]
    : [];
  return { version: 1, age, needs, kolay_hidden: value.kolay_hidden === true };
}

export function hasSelection(selection) {
  return Boolean(selection && (AGE_IDS.has(selection.age) || (Array.isArray(selection.needs) && selection.needs.length)));
}

export function orderedGroups(selection) {
  const needs = GROUPS.filter((group) => group.kind === 'need' && selection.needs.includes(group.id));
  const age = GROUPS.find((group) => group.kind === 'age' && group.id === selection.age);
  return age ? [...needs, age] : needs;
}

export function pickSuggestions(payload, selection, { lang = 'tr', present = new Set(), profile = {}, personaUnset = false } = {}) {
  if (!hasSelection(selection) || !payload) {
    return { chips: [], more: [], shortcuts: [], profileNeeds: [], kolay: false, persona: null, switchLanguage: false };
  }
  const groups = new Map((payload.groups || []).map((group) => [group.id, group]));
  const items = new Map((payload.suggestions || []).map((item) => [item.id, item]));
  const shortcutsById = new Map((payload.shortcuts || []).map((item) => [item.id, item]));
  const selected = orderedGroups(selection).map((group) => groups.get(group.id)).filter(Boolean);
  const chosen = [];
  const usedItems = new Set();
  const depthLimit = Math.max(0, ...selected.map((group) => (group.suggestions || []).length));
  for (let depth = 0; depth < depthLimit; depth += 1) {
    for (const group of selected) {
      const item = items.get((group.suggestions || [])[depth]);
      if (!item || usedItems.has(item.id) || (lang === 'en' && !item.text_en)) continue;
      if (['tool', 'agency', 'knowledge'].includes(item.kind) && !present.has('composer')) continue;
      usedItems.add(item.id);
      chosen.push(item);
    }
  }

  const shortcuts = [];
  const usedShortcuts = new Set();
  const shortcutLimit = Math.max(0, ...selected.map((group) => (group.shortcuts || []).length));
  for (let depth = 0; depth < shortcutLimit && shortcuts.length < 3; depth += 1) {
    for (const group of selected) {
      const item = shortcutsById.get((group.shortcuts || [])[depth]);
      if (!item || usedShortcuts.has(item.id) || !present.has(item.target)) continue;
      usedShortcuts.add(item.id);
      shortcuts.push(item);
      if (shortcuts.length === 3) break;
    }
  }

  const profileNeeds = [];
  const accepted = new Set(profile.consent === true && Array.isArray(profile.needs) ? profile.needs : []);
  if (present.has('profilim')) {
    for (const group of selected) {
      for (const need of group.profile || []) {
        if (PROFILE_NEEDS[need] && !accepted.has(need) && !profileNeeds.includes(need)) profileNeeds.push(need);
      }
    }
  }
  const kolay = lang === 'tr' && !selection.kolay_hidden && selected.some((group) => group.kolay === true);
  const persona = personaUnset && present.has('persona')
    ? orderedGroups(selection).map((group) => PERSONA_BY_GROUP[group.id]).find(Boolean) || null
    : null;
  const switchLanguage = lang === 'tr' && present.has('language-switch') && selected.some((group) => group.id === 'turist');
  return { chips: chosen.slice(0, 3), more: chosen.slice(3, 9), shortcuts, profileNeeds, kolay, persona, switchLanguage };
}

function selectedLabels(selection) {
  return orderedGroups(selection).map((group) => GROUPS.find((item) => item.id === group.id)?.label() || '').filter(Boolean);
}

export function sectionMarkup(selection, lang = 'tr') {
  return `<section id="size-gore" class="aud" lang="${esc(lang)}" aria-labelledby="aud-title">
    <h2 id="aud-title" tabindex="-1">${esc(t('ui.aud.title', 'Size göre öneriler'))}</h2>
    <p class="aud-note">${esc(t('ui.aud.note', 'İsteğe bağlı. Seçiminiz yalnız bu cihazda durur, sunucuya gönderilmez; bir soruya dokunursanız yalnız o soru gönderilir.'))}</p>
    <div class="aud-result" id="aud-result" hidden></div>
    ${formMarkup(selection)}
    <p class="status-line aud-status" id="aud-status" role="status" aria-live="polite"></p>
  </section>`;
}

function optionMarkup(name, value, group, checked) {
  const type = group === 'age' ? 'radio' : 'checkbox';
  const controlValue = value === null ? '' : value;
  const controlId = group === 'age' ? `aud-age-${value}` : `aud-need-${value}`;
  return `<label class="check"><input id="${esc(controlId)}" type="${type}" name="aud-${group}" value="${esc(controlValue)}"${checked ? ' checked' : ''}>`
    + `<span><span class="check-label">${esc(name.label())}</span> <span class="field-hint">${esc(name.hint())}</span></span></label>`;
}

export function formMarkup(selection) {
  const summary = hasSelection(selection) ? t('ui.aud.edit_change', 'Seçimi değiştir') : t('ui.aud.edit_start', 'Yaş grubunuzu ve ihtiyacınızı seçin');
  const ages = [
    `<label class="check"><input id="aud-age-none" type="radio" name="aud-age" value=""${selection.age ? '' : ' checked'}><span class="check-label">${esc(t('ui.aud.age_none', 'Belirtmek istemiyorum'))}</span></label>`,
    ...GROUPS.filter((group) => group.kind === 'age').map((group) => optionMarkup(group, group.id, 'age', selection.age === group.id)),
  ];
  const needs = GROUPS.filter((group) => group.kind === 'need')
    .map((group) => optionMarkup(group, group.id, 'need', selection.needs.includes(group.id)));
  return `<details class="more aud-edit" id="aud-edit"><summary>${esc(summary)}</summary>
    <form id="aud-form" class="aud-form" autocomplete="off">
      <fieldset><legend>${esc(t('ui.aud.age_legend', 'Yaş grubu'))}</legend>${ages.join('')}</fieldset>
      <fieldset><legend>${esc(t('ui.aud.needs_legend', 'İhtiyaç (birden çok seçebilirsiniz)'))}</legend>${needs.join('')}</fieldset>
      <button type="button" class="btn btn-quiet" id="aud-clear"${hasSelection(selection) ? '' : ' hidden'}>${esc(t('ui.aud.clear', 'Seçimi temizle'))}</button>
    </form>
  </details>`;
}

export function chipMarkup(suggestion, lang = 'tr') {
  const text = lang === 'en' ? suggestion.text_en : suggestion.text_tr;
  if (!text) return '';
  if (suggestion.kind === 'page' && typeof suggestion.url === 'string' && suggestion.url.startsWith('https://')) {
    const suffix = t('ui.aud.page_suffix', '(resmî sayfa, yeni sekmede açılır)');
    return `<a class="chip aud-chip" data-aud="${esc(suggestion.id)}" href="${esc(suggestion.url)}" target="_blank" rel="noopener noreferrer">`
      + `${icon('external-link')}${esc(text)}<span class="sr-only"> ${esc(suffix)}</span></a>`;
  }
  if (!['tool', 'agency', 'knowledge'].includes(suggestion.kind)) return '';
  const suffix = t('ui.aud.ask_suffix', '(dokununca sorulur)');
  return `<button type="button" class="chip aud-chip" data-aud="${esc(suggestion.id)}" aria-label="${esc(`${text} ${suffix}`)}">${esc(text)}</button>`;
}

export function resultMarkup(picked, selection, lang = 'tr') {
  const choice = t('ui.aud.chosen', 'Seçiminiz: {list}', { list: selectedLabels(selection).join(', ') });
  const chipLabel = t('ui.aud.chips_label', 'Size göre sorular ve sayfalar');
  const chips = [...picked.chips, ...picked.more].map((item) => chipMarkup(item, lang));
  const visible = picked.chips.map((item) => chipMarkup(item, lang)).join('');
  const extra = picked.more.map((item) => chipMarkup(item, lang)).join('');
  const more = extra ? `<details class="more aud-more"><summary>${esc(t('ui.aud.more', 'Daha fazla öneri'))}</summary><div class="chips aud-chips">${extra}</div></details>` : '';
  const shortcutLinks = picked.shortcuts.map((item) => `<li><a class="btn btn-quiet aud-link" href="#${esc(item.target)}">${esc(lang === 'en' ? item.text_en : item.text_tr)}</a></li>`).join('');
  const shortcutNav = shortcutLinks ? `<nav class="aud-shortcuts" aria-labelledby="aud-shortcuts-title"><h3 id="aud-shortcuts-title">${esc(t('ui.aud.shortcuts', 'Kısayollar'))}</h3><ul>${shortcutLinks}</ul></nav>` : '';
  const needNames = picked.profileNeeds.map((need) => PROFILE_NEEDS[need]?.()).filter(Boolean);
  const profile = needNames.length ? `<div class="aud-profile"><p>${esc(t('ui.aud.profile_line', "Cevaplarınızda bu ihtiyaçları dikkate almak için Profilim'de ilgili kutuları işaretleyebilirsiniz: {needs}.", { needs: needNames.join(', ') }))}</p><a class="btn btn-quiet aud-link" href="#profilim">${esc(t('ui.aud.profile_go', "Profilim'e git"))}</a></div>` : '';
  const easy = picked.kolay ? `<div class="aud-kolay" role="note"><p>${esc(t('ui.aud.kolay_text', 'Daha büyük düğmeler ve tek adımlı bir ekran için Kolay ekranı deneyin.'))}</p><div class="btn-row"><a class="btn" href="/kolay.html">${esc(t('ui.aud.kolay_open', 'Kolay ekranı aç'))}</a><button type="button" class="btn btn-quiet" id="aud-kolay-hide">${esc(t('ui.aud.kolay_hide', 'Gizle'))}</button></div></div>` : '';
  const persona = picked.persona ? `<div class="aud-persona"><p>${esc(t('ui.aud.persona_text', 'Yazı boyutu ve kontrast için görünümü de ayarlayabilirsiniz.'))}</p><button type="button" class="btn btn-quiet" id="aud-persona-open">${esc(t('ui.aud.persona_open', 'Görünümü ayarla'))}</button></div>` : '';
  const switchLanguage = picked.switchLanguage ? '<button type="button" class="btn btn-quiet aud-switch-language" id="aud-switch-english" lang="en">Switch to English</button>' : '';
  const empty = chips.length || shortcutLinks || profile || easy || persona || switchLanguage
    ? '' : `<p class="aud-empty">${esc(t('ui.aud.empty', 'Bu seçim için şu an gösterilecek öneri yok. Sorunuzu yukarıya yazabilirsiniz.'))}</p>`;
  return `<div class="aud-results" lang="${esc(lang)}"><p class="aud-chosen">${esc(choice)}</p><h3>${esc(chipLabel)}</h3>`
    + `${visible ? `<div class="chips aud-chips">${visible}</div>` : ''}${more}${shortcutNav}${profile}${easy}${persona}${switchLanguage}${empty}</div>`;
}
