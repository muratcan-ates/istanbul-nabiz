/* Saved journeys stay on this device unless a linked example account gets separate consent. */

import { get, post, del, MOCK } from './api.js';
import { readProfile, effectiveNeeds } from './profile.js';
import { readAccount } from './identity.js';
import { esc } from './format.js';
import { icon } from './icons.js';
import { t, currentLang, onLang } from './i18n_text.js';

const STORAGE_KEY = 'nabiz.journey-watch.v1';
const DEVICE_LIMIT = 3;
const ACCOUNT_LIMIT = 5;
const NEED_KEYS = ['step_free', 'slow_walk'];

function emptySaved() {
  return { consent_at: null, journeys: [], last: {}, choice: {}, account_ids: [] };
}

function cleanJourney(raw) {
  if (!raw || typeof raw !== 'object') return null;
  const origin = String(raw.from || raw.origin || '').trim().replace(/\s+/g, ' ');
  const destination = String(raw.to || raw.destination || '').trim().replace(/\s+/g, ' ');
  const needs = Array.isArray(raw.needs) ? [...new Set(raw.needs)] : [];
  const time = raw.time ? String(raw.time) : null;
  if (origin.length < 2 || origin.length > 60 || destination.length < 2 || destination.length > 60) return null;
  if (origin.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('tr')
    === destination.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('tr')) return null;
  if (time && !/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(time)) return null;
  if (!needs.length || needs.some((need) => !NEED_KEYS.includes(need))) return null;
  const id = /^[a-z0-9-]{1,24}$/.test(String(raw.id || '')) ? String(raw.id)
    : `j-${hash(`${origin}|${destination}|${time || ''}|${needs.join(',')}`)}`;
  return { id, from: origin, to: destination, time, needs };
}

function hash(value) {
  let out = 2166136261;
  for (let index = 0; index < value.length; index += 1) out = Math.imul(out ^ value.charCodeAt(index), 16777619);
  return (out >>> 0).toString(36);
}

function readSaved(storage) {
  try {
    const target = storage || (typeof window !== 'undefined' ? window.localStorage : null);
    if (!target) return emptySaved();
    const raw = target.getItem(STORAGE_KEY);
    if (!raw) return emptySaved();
    const value = JSON.parse(raw);
    if (!value || typeof value !== 'object' || !Array.isArray(value.journeys)) return [];
    const accountIds = Array.isArray(value.account_ids) ? value.account_ids.filter((id) => typeof id === 'string') : [];
    const clean = value.journeys.map(cleanJourney).filter(Boolean);
    let localCount = 0;
    const journeys = clean.filter((journey) => {
      if (accountIds.includes(journey.id)) return true;
      localCount += 1;
      return localCount <= DEVICE_LIMIT;
    }).slice(0, DEVICE_LIMIT + ACCOUNT_LIMIT);
    return {
      consent_at: typeof value.consent_at === 'string' ? value.consent_at : null,
      journeys,
      last: value.last && typeof value.last === 'object' ? value.last : {},
      choice: value.choice && typeof value.choice === 'object' ? value.choice : {},
      account_ids: accountIds,
    };
  } catch (err) {
    return [];
  }
}

function writeSaved(storage, value) {
  try {
    const target = storage || (typeof window !== 'undefined' ? window.localStorage : null);
    if (!target) return false;
    target.setItem(STORAGE_KEY, JSON.stringify(value));
    return true;
  } catch (err) {
    return false;
  }
}

function shouldShowOnHome(result) {
  return Boolean(result && (result.level === 'affected' || result.level === 'unverified'));
}

function cardModel(result, choice, previousFingerprint) {
  const show = shouldShowOnHome(result);
  const fingerprint = Array.isArray(result && result.fingerprint) ? result.fingerprint : [];
  const previous = Array.isArray(previousFingerprint) ? previousFingerprint : [];
  const hasPrevious = Array.isArray(previousFingerprint);
  const isNew = result && result.comparable === true && hasPrevious
    && fingerprint.join('|') !== previous.join('|');
  const sameChoice = choice && (result.comparable !== true || choice.fingerprint === fingerprint.join('|')) ? choice : null;
  return {
    show,
    tone: result && result.level === 'affected' ? 'warn' : 'quiet',
    title: result && result.headline ? result.headline : '',
    reasons: Array.isArray(result && result.reasons) ? result.reasons : [],
    alternative: result && result.alternative ? result.alternative : null,
    isNew: Boolean(isNew),
    choice: sameChoice,
    sourceLine: result && result.provenance ? result.provenance : null,
  };
}

function safeStore() {
  try { return window.localStorage; } catch (err) { return null; }
}

function formatTime(value) {
  return value ? String(value).replace(':', '.') : '';
}

function formatRecorded(value) {
  const timestamp = Date.parse(value || '');
  if (!Number.isFinite(timestamp)) return t('ui.jw.unknown_time', 'zaman bilinmiyor');
  const locale = currentLang() === 'en' ? 'en-GB' : 'tr-TR';
  const text = new Intl.DateTimeFormat(locale, {
    timeZone: 'Europe/Istanbul', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
  }).format(timestamp);
  return t('ui.jw.recorded_at', 'kayıtlı · {when}', { when: text });
}

function needLabel(key) {
  return key === 'step_free' ? t('ui.jw.step_free', 'Adımsız yol') : t('ui.jw.slow_walk', 'Az yürüme');
}

function templateMarkup(state, storageReady, accountMode) {
  const accountExtra = accountMode
    ? `<div id="jw-account-consent-group"><label class="jw-check"><input id="jw-account-consent" type="checkbox" aria-describedby="jw-account-hint">${esc(t('ui.jw.account_consent', 'Hesabımda saklanmasını ve belirtilen toplu kullanımı ayrı açık rızayla kabul ediyorum.'))}</label><p class="jw-hint" id="jw-account-hint">${esc(t('ui.jw.account_hint', 'Açık rızamla kayıtlı yolculuklarımın başlangıç, varış, saat ve kısıt bilgilerinin hesabıma bağlı olarak saklanmasını kabul ediyorum. İstediğim an silebilirim; 90 gün kullanılmazsa silinir. Yolculuklar adınız ve cihazınız olmadan yalnız toplam sayı olarak İBB operatörünün etki senaryolarında kullanılabilir.'))}</p></div>`
    : '';
  const unavailable = storageReady ? '' : `<p class="jw-error" role="status">${esc(t('ui.jw.storage_unavailable', 'Bu tarayıcı kayıt tutamıyor. Bu bölümde yolculuk saklanamaz.'))}</p>`;
  return `<details class="more account-detail jw-detail" id="yolculuklarim-detail">`
    + `<summary>${esc(t('ui.jw.section_title', 'Kayıtlı yolculuklarım'))}</summary>`
    + `<div class="jw-content"><p class="jw-note">${esc(t('ui.jw.section_note', 'Yalnız bu cihazda, isteğe bağlı.'))}</p>`
    + unavailable
    + `<form id="jw-form" class="jw-form"${storageReady ? '' : ' hidden'}>`
    + `<div class="jw-fields"><div class="field"><label for="jw-from">${esc(t('ui.jw.start', 'Başlangıç'))}</label><input id="jw-from" name="from" maxlength="60" autocomplete="off" required aria-describedby="jw-error"></div>`
    + `<div class="field"><label for="jw-to">${esc(t('ui.jw.destination', 'Varış'))}</label><input id="jw-to" name="to" maxlength="60" autocomplete="off" required aria-describedby="jw-error"></div>`
    + `<div class="field"><label for="jw-time">${esc(t('ui.jw.time', 'Saat (isteğe bağlı)'))}</label><input id="jw-time" name="time" type="time"></div></div>`
    + `<fieldset class="jw-needs"><legend>${esc(t('ui.jw.needs_legend', 'Yolculuk tercihleriniz'))}</legend>`
    + `<label class="jw-check"><input name="needs" type="checkbox" value="step_free">${esc(t('ui.jw.step_free', 'Adımsız yol'))}</label>`
    + `<label class="jw-check"><input name="needs" type="checkbox" value="slow_walk">${esc(t('ui.jw.slow_walk', 'Az yürüme'))}</label></fieldset>`
    + `<label class="jw-check jw-consent"><input id="jw-consent" type="checkbox" aria-describedby="jw-consent-hint jw-error">${esc(t('ui.jw.consent', 'Anladım, bu yolculuğu bu cihazda saklamak istiyorum.'))}</label>`
    + `<p class="jw-hint" id="jw-consent-hint">${esc(t('ui.jw.consent_hint', 'Sunucuya yalnız kontrol anında başlangıç, varış ve kısıt gider; orada saklanmaz. Kimlik, konum ya da sağlık bilgisi istenmez.'))}</p>`
    + accountExtra
    + `<p class="jw-error" id="jw-error" role="status"></p><button class="btn btn-primary" type="submit">${esc(t('ui.jw.save', 'Kaydet'))}</button></form>`
    + `<div class="jw-list-head"><h3>${esc(t('ui.jw.list_title', 'Yolculuklarınız'))}</h3><button id="jw-check" class="btn btn-quiet" type="button"${storageReady ? '' : ' disabled'}>${icon('refresh')} ${esc(t('ui.jw.check', 'Şimdi kontrol et'))}</button></div>`
    + `<div id="jw-list" aria-live="polite" aria-busy="false"></div></div></details>`;
}

function listRow(journey, state, accountMode) {
  const result = state.last[journey.id] && state.last[journey.id].result;
  // Literal t() calls (P00 D2a): the page's catalogue check reads each key beside its Turkish.
  const statusText = result && result.level === 'affected' ? t('ui.jw.status_affected', 'Etkileniyor')
    : result && result.level === 'unverified' ? t('ui.jw.status_unverified', 'Doğrulanamadı')
      : result && result.level === 'clear' ? t('ui.jw.status_clear', 'Etkileyen kayıt yok')
        : t('ui.jw.status_waiting', 'Henüz kontrol edilmedi');
  const when = result && result.checked_at ? `<span class="jw-recorded">${esc(formatRecorded(result.checked_at))}</span>` : '';
  const detour = result && result.alternative && journey.needs.includes('slow_walk') && !journey.needs.includes('step_free')
    ? `<span class="jw-recorded" lang="tr">${esc(t('ui.jw.slow_walk_detour', 'Planlayıcı asansör durumuna göre {station} istasyonunu atladı; yolculuk yaklaşık {minutes} dk uzadı.', {
      station: result.alternative.station,
      minutes: Number.isFinite(Number(result.alternative.extra_minutes)) ? result.alternative.extra_minutes : 'bilinmiyor',
    }))}</span>` : '';
  const choices = journey.needs.map(needLabel).join(', ');
  const removeLabel = t('ui.jw.remove', 'Sil');
  return `<article class="jw-row"><div class="jw-row-copy"><p class="jw-trip"><strong>${esc(journey.from)} → ${esc(journey.to)}</strong>`
    + `${journey.time ? ` · ${esc(formatTime(journey.time))}` : ''} · ${esc(choices)}</p>`
    + `<span class="jw-badge jw-badge-${esc(result && result.level || 'quiet')}">${esc(statusText)}</span>${when}${detour}</div>`
    + `<button class="btn btn-quiet jw-remove" type="button" data-remove="${esc(journey.id)}" aria-label="${esc(removeLabel)} ${esc(journey.from)} ${esc(t('ui.jw.to', 'ile'))} ${esc(journey.to)}">${esc(removeLabel)}</button></article>`;
}

function impactMarkup(result, model, choice) {
  if (!model.show) return '';
  const title = `${result.from} → ${result.to}${result.time ? ` (${formatTime(result.time)})` : ''}`;
  const status = result.level === 'affected'
    ? t('ui.jw.card_affected', 'Kayıtlı yolculuğunuz etkileniyor: {trip}.', { trip: title })
    : t('ui.jw.card_unverified', 'Kayıtlı yolculuğunuz doğrulanamadı: {trip}.', { trip: title });
  const needNames = (result.affected_needs || []).map(needLabel).join(', ');
  const reasonMarkup = model.reasons.filter((item) => !item.informational).slice(0, 2).map((item) => (
    `<li lang="tr">${esc(item.text)}<span class="jw-reason-source">${esc(item.source)}${item.observed_at ? ` · ${esc(formatRecorded(item.observed_at))}` : ''}</span></li>`
  )).join('');
  const source = model.sourceLine;
  const sourceLabel = source && source.source ? `${source.source}${source.observed_at ? ` · ${formatRecorded(source.observed_at)}` : ''}` : '';
  const sourceUrl = source && typeof source.url === 'string' && /^https?:\/\//i.test(source.url) ? source.url : null;
  const sourceMarkup = sourceLabel && sourceUrl
    ? `<a href="${esc(sourceUrl)}" target="_blank" rel="noopener noreferrer">${esc(sourceLabel)}</a>`
    : sourceLabel ? `<span>${esc(sourceLabel)}</span>` : '';
  const timeNote = result.time_note ? `<p class="jw-time-note" lang="tr">${esc(result.time_note)}</p>` : '';
  const warning = result.level === 'unverified'
    ? `<p class="jw-warning" lang="tr">${esc(t('ui.jw.unverified_detail', 'Kaynak şu an doğrulanamadı; yola çıkmadan önce yeniden kontrol edin.'))}</p>` : '';
  const isNew = model.isNew ? `<span class="jw-new">${esc(t('ui.jw.new', 'Yeni'))}</span>` : '';
  const alt = model.alternative;
  let action = '';
  if (alt && !choice) {
    const extra = Number.isFinite(Number(alt.extra_minutes))
      ? t('ui.jw.extra_minutes', 'yaklaşık {minutes} dk ek', { minutes: alt.extra_minutes }) : '';
    const proposed = t('ui.jw.alternative_text', 'Önerilen: {station} ({line}), {extra}', {
      station: esc(alt.station), line: esc(alt.line || ''), extra: esc(extra),
    });
    const approval = alt.operator_approved === true
      ? `<p class="jw-approval" lang="tr">${esc(alt.approved_text || alt.reason || '')} <span>${esc(t('ui.jw.approved_badge', 'Simüle operatör onayladı'))}</span></p>` : '';
    action = `<div class="jw-alternative"><p lang="tr">${proposed}</p>${approval}<div class="jw-actions">`
      + `<button class="btn btn-primary" type="button" data-choice="alternative" data-id="${esc(result.id)}">${esc(t('ui.jw.select_alternative', 'Alternatifi seç'))}</button>`
      + `<button class="btn btn-quiet" type="button" data-choice="later" data-id="${esc(result.id)}">${esc(t('ui.jw.later', 'Şimdilik değil'))}</button></div></div>`;
  } else if (choice && choice.value === 'alternative' && alt) {
    action = `<p class="jw-selected">${esc(t('ui.jw.selected', 'Alternatifi seçtiniz: {station}. Durum değişirse yeniden sorarız.', { station: alt.station }))}</p>`;
  } else if (choice && choice.value === 'later') {
    action = `<p class="jw-selected">${esc(t('ui.jw.deferred', 'Şimdilik yeniden karar vermediniz. Durum değişirse kartı gösteririz.'))}</p>`;
  } else if (!alt) {
    const anchor = typeof document !== 'undefined' ? document.querySelector('#alternative') : null;
    action = anchor ? `<a class="btn btn-quiet" href="#alternative" data-focus-alternative>${esc(t('ui.jw.open_alternative', 'Adımsız yol bölümüne git'))}</a>` : '';
  }
  const more = (result.uncertainty || []).length
    ? `<details class="jw-more"><summary>${esc(t('ui.jw.more', 'Ayrıntı'))}</summary><ul>${result.uncertainty.map((item) => `<li>${esc(item)}</li>`).join('')}</ul></details>` : '';
  return `<section class="jw-impact jw-impact-${model.tone}" aria-labelledby="jw-impact-title"><div class="jw-card-head">`
    + `<h2 id="jw-impact-title">${esc(status)}</h2>${isNew}</div>`
    + `${needNames ? `<p class="jw-preference">${esc(t('ui.jw.affected_need', 'Etkilenen tercih: {need}', { need: needNames }))}</p>` : ''}`
    + `${reasonMarkup ? `<ul class="jw-reasons">${reasonMarkup}</ul>` : ''}${timeNote}${warning}${action}${more}`
    + `${sourceMarkup ? `<p class="jw-source">${esc(t('ui.jw.source', 'Kaynak'))}: ${sourceMarkup}</p>` : ''}</section>`;
}

function install() {
  if (typeof document === 'undefined' || document.querySelector('[data-journey-watch-installed]')) return;
  const home = document.querySelector('#city-cards');
  const main = document.querySelector('main');
  const account = document.querySelector('#hesabim');
  if (!account || !main) return;

  const styleHref = '/css/journey_watch.css';
  if (![...document.querySelectorAll('link[rel="stylesheet"]')].some((link) => link.getAttribute('href') === styleHref)) {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = styleHref;
    document.head.append(link);
  }

  const storage = safeStore();
  const storageReady = Boolean(storage);
  const savedValue = readSaved(storage);
  let deviceState = Array.isArray(savedValue) ? emptySaved() : savedValue;
  let accountMode = Boolean(readAccount());
  account.insertAdjacentHTML('beforeend', templateMarkup(deviceState, storageReady, accountMode));
  account.dataset.journeyWatchInstalled = 'true';
  const section = account.querySelector('#yolculuklarim-detail');
  const form = account.querySelector('#jw-form');
  const listHost = account.querySelector('#jw-list');
  const statusHost = account.querySelector('#jw-error');
  const checkButton = account.querySelector('#jw-check');
  const impactId = 'jw-impact-section';

  function currentState() {
    return deviceState;
  }

  function saveDevice() {
    return writeSaved(storage, deviceState);
  }

  function renderList() {
    if (!listHost) return;
    const state = currentState();
    const rows = state.journeys.map((journey) => listRow(journey, state, accountMode)).join('');
    listHost.innerHTML = rows || `<p class="jw-empty">${esc(t('ui.jw.empty', 'Henüz kayıtlı yolculuk yok.'))}</p>`;
  }

  function renderImpact() {
    const existing = document.getElementById(impactId);
    const items = deviceState.journeys.map((journey) => ({
      journey,
      result: deviceState.last[journey.id] && deviceState.last[journey.id].result,
    })).filter((item) => shouldShowOnHome(item.result));
    if (!items.length) {
      if (existing) existing.remove();
      return;
    }
    const item = items[0];
    const previous = deviceState.last[item.journey.id] && deviceState.last[item.journey.id].previous_fingerprint;
    const choice = deviceState.choice[item.journey.id];
    const model = cardModel(item.result, choice, previous);
    const markup = impactMarkup(item.result, model, model.choice);
    if (!markup) return;
    const shell = document.createElement('div');
    shell.id = impactId;
    shell.innerHTML = markup;
    shell.querySelector('section').id = 'jw-impact';
    shell.querySelector('section').setAttribute('aria-busy', 'false');
    if (existing) existing.replaceWith(shell);
    else {
      const cards = home && home.querySelector('#cards');
      if (cards) cards.before(shell);
      else if (home) home.prepend(shell);
      else main.prepend(shell);
    }
    if (items.length > 1) {
      const more = document.createElement('a');
      more.className = 'btn btn-quiet jw-more-journeys';
      more.href = '#yolculuklarim-detail';
      more.textContent = t('ui.jw.more_journeys', '+{count} yolculuk daha', { count: items.length - 1 });
      shell.querySelector('section').append(more);
    }
  }

  function render() {
    renderList();
    renderImpact();
  }

  function syncSaveCurrentJourney() {
    const journeySection = document.querySelector('#journey-section');
    const result = journeySection && journeySection.querySelector('#journey-result');
    if (!result) return;
    const existing = journeySection.querySelector('#jw-save-current');
    const populated = Boolean(result.textContent.trim() || result.children.length);
    if (!populated) {
      if (existing) existing.remove();
      return;
    }
    if (existing) {
      existing.textContent = t('ui.jw.save_current', 'Bu yolculuğu kaydet');
      return;
    }
    const button = document.createElement('button');
    button.id = 'jw-save-current';
    button.type = 'button';
    button.className = 'btn btn-quiet';
    button.textContent = t('ui.jw.save_current', 'Bu yolculuğu kaydet');
    result.after(button);
    button.addEventListener('click', () => {
      const origin = document.querySelector('#journey-from');
      const destination = document.querySelector('#journey-to');
      const startField = form.querySelector('#jw-from');
      const destinationField = form.querySelector('#jw-to');
      if (!origin || !destination || !startField || !destinationField) return;
      startField.value = origin.value;
      destinationField.value = destination.value;
      section.open = true;
      startField.focus();
    });
  }

  function observeJourneyResult() {
    const journeyResult = document.querySelector('#journey-section #journey-result');
    if (!journeyResult || typeof MutationObserver === 'undefined') return false;
    const observer = new MutationObserver(syncSaveCurrentJourney);
    observer.observe(journeyResult, { childList: true, subtree: true, characterData: true });
    syncSaveCurrentJourney();
    return true;
  }

  function showMessage(message, error) {
    if (!statusHost) return;
    statusHost.textContent = message || '';
    statusHost.classList.toggle('is-error', Boolean(error));
  }

  function seedNeeds() {
    const profile = readProfile();
    const needs = profile.consent ? effectiveNeeds(profile, []) : [];
    const initial = needs.filter((need) => NEED_KEYS.includes(need));
    if (!initial.length) initial.push('step_free');
    form.querySelectorAll('input[name="needs"]').forEach((input) => { input.checked = initial.includes(input.value); });
  }

  async function checkNow({ announce = false } = {}) {
    if (!deviceState.journeys.length) return;
    if (MOCK) {
      showMessage(t('ui.jw.mock_unavailable', 'Örnek modda yolculuk kontrolü yapılmaz.'), true);
      return;
    }
    const prior = { ...deviceState.last };
    if (listHost) listHost.setAttribute('aria-busy', 'true');
    const card = document.querySelector('#jw-impact');
    if (card) card.setAttribute('aria-busy', 'true');
    checkButton.setAttribute('aria-busy', 'true');
    checkButton.setAttribute('aria-disabled', 'true');
    try {
      const accountIds = new Set(deviceState.account_ids || []);
      const accountJourneys = deviceState.journeys.filter((journey) => accountIds.has(journey.id));
      const deviceJourneys = deviceState.journeys.filter((journey) => !accountIds.has(journey.id));
      const responses = [];
      if (deviceJourneys.length) responses.push(await post('/api/journey-watch/check', { journeys: deviceJourneys }));
      if (accountJourneys.length) responses.push(await post('/api/account/journeys/check', {}));
      const response = { checked_at: responses[0] && responses[0].checked_at, results: responses.flatMap((item) => item.results || []) };
      const results = response.results;
      results.forEach((result) => {
        if (!deviceState.journeys.some((journey) => journey.id === result.id)) return;
        const old = prior[result.id];
        const priorFingerprint = old && (old.comparable === true ? old.fingerprint : old.previous_fingerprint);
        deviceState.last[result.id] = {
          level: result.level,
          fingerprint: result.fingerprint || [],
          checked_at: result.checked_at || response.checked_at,
          previous_fingerprint: priorFingerprint === undefined ? null : priorFingerprint,
          result: { ...result, checked_at: result.checked_at || response.checked_at },
          comparable: result.comparable === true,
        };
        const choice = deviceState.choice[result.id];
        if (choice && result.comparable === true && choice.fingerprint !== (result.fingerprint || []).join('|')) {
          delete deviceState.choice[result.id];
        }
      });
      saveDevice();
      showMessage('');
      render();
      document.dispatchEvent(new CustomEvent('nabiz:journey-impact', {
        detail: {
          affected: results.filter((result) => result.level === 'affected').length,
          unverified: results.filter((result) => result.level === 'unverified').length,
          checked_at: response.checked_at,
        },
      }));
      if (announce) showMessage(t('ui.jw.checked', 'Yolculuk kayıtları kontrol edildi.'), false);
    } catch (error) {
      showMessage(error && error.message ? error.message : t('ui.jw.check_error', 'Kontrol tamamlanamadı. Yeniden deneyin.'), true);
    } finally {
      if (listHost) listHost.setAttribute('aria-busy', 'false');
      const refreshedCard = document.querySelector('#jw-impact');
      if (refreshedCard) refreshedCard.setAttribute('aria-busy', 'false');
      checkButton.removeAttribute('aria-busy');
      checkButton.removeAttribute('aria-disabled');
    }
  }

  function addStyleAndCard() {
    render();
    seedNeeds();
    if (storageReady && (accountMode || (deviceState.account_ids || []).length)) syncAccount();
    else if (storageReady && deviceState.journeys.length) checkNow();
  }

  async function syncAccount() {
    accountMode = Boolean(readAccount());
    const consentGroup = form.querySelector('#jw-account-consent-group');
    if (accountMode && !consentGroup) {
      const hint = form.querySelector('#jw-consent-hint');
      hint.insertAdjacentHTML('afterend', `<div id="jw-account-consent-group"><label class="jw-check"><input id="jw-account-consent" type="checkbox" aria-describedby="jw-account-hint">${esc(t('ui.jw.account_consent', 'Hesabımda saklanmasını ve belirtilen toplu kullanımı ayrı açık rızayla kabul ediyorum.'))}</label><p class="jw-hint" id="jw-account-hint">${esc(t('ui.jw.account_hint', 'Açık rızamla kayıtlı yolculuklarımın başlangıç, varış, saat ve kısıt bilgilerinin hesabıma bağlı olarak saklanmasını kabul ediyorum. İstediğim an silebilirim; 90 gün kullanılmazsa silinir. Yolculuklar adınız ve cihazınız olmadan yalnız toplam sayı olarak İBB operatörünün etki senaryolarında kullanılabilir.'))}</p></div>`);
    } else if (!accountMode && consentGroup) {
      consentGroup.remove();
    }
    if (!accountMode) {
      const previousAccountIds = new Set(deviceState.account_ids || []);
      deviceState.journeys = deviceState.journeys.filter((journey) => !previousAccountIds.has(journey.id));
      previousAccountIds.forEach((id) => { delete deviceState.last[id]; delete deviceState.choice[id]; });
      deviceState.account_ids = [];
      saveDevice();
      render();
      if (deviceState.journeys.length) await checkNow();
      return;
    }
    if (MOCK) return;
    try {
      const response = await get('/api/account/journeys');
      const accountJourneys = (response.journeys || []).map(cleanJourney).filter(Boolean);
      const accountIds = accountJourneys.map((journey) => journey.id);
      const localOnly = deviceState.journeys.filter((journey) => !(deviceState.account_ids || []).includes(journey.id));
      deviceState = {
        ...deviceState,
        journeys: [...localOnly, ...accountJourneys].slice(0, DEVICE_LIMIT + ACCOUNT_LIMIT),
        account_ids: accountIds,
      };
      saveDevice();
      render();
      if (deviceState.journeys.length) await checkNow();
    } catch (error) {
      showMessage(error && error.message ? error.message : t('ui.jw.account_load_error', 'Hesap yolculukları yüklenemedi.'), true);
    }
  }

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    showMessage('');
    if (!storageReady) return;
    const data = new FormData(form);
    if (!form.querySelector('#jw-consent').checked) {
      showMessage(t('ui.jw.consent_required', 'Kaydetmeden önce bu cihazda saklamaya izin verdiğinizi işaretleyin.'), true);
      form.querySelector('#jw-consent').focus();
      return;
    }
    const raw = {
      from: data.get('from'),
      to: data.get('to'),
      time: data.get('time') || null,
      needs: data.getAll('needs'),
    };
    const journey = cleanJourney(raw);
    if (!journey) {
      showMessage(t('ui.jw.invalid_form', 'Başlangıç, varış ve yolculuk tercihlerinizi kontrol edin.'), true);
      return;
    }
    const accountConsent = Boolean(accountMode && form.querySelector('#jw-account-consent').checked);
    if (accountConsent && MOCK) {
      showMessage(t('ui.jw.mock_unavailable', 'Örnek modda yolculuk kontrolü yapılmaz.'), true);
      return;
    }
    const next = deviceState.journeys.filter((item) => item.id !== journey.id);
    const localCount = next.filter((item) => !(deviceState.account_ids || []).includes(item.id)).length;
    if (!accountConsent && localCount >= DEVICE_LIMIT) {
      showMessage(t('ui.jw.device_limit', 'Bu cihazda en çok 3 yolculuk saklayabilirsiniz.'), true);
      return;
    }
    if (accountConsent) {
      try {
        await post('/api/account/journeys', { journey, consent: true });
        deviceState.account_ids = [...new Set([...(deviceState.account_ids || []), journey.id])];
      } catch (error) {
        showMessage(error && error.message ? error.message : t('ui.jw.account_save_error', 'Hesap yolculuğu saklanamadı.'), true);
        return;
      }
    } else {
      if ((deviceState.account_ids || []).includes(journey.id)) {
        try { await del(`/api/account/journeys/${encodeURIComponent(journey.id)}`); }
        catch (error) {
          showMessage(error && error.message ? error.message : t('ui.jw.account_delete_error', 'Hesap yolculuğu silinemedi.'), true);
          return;
        }
      }
      deviceState.account_ids = (deviceState.account_ids || []).filter((id) => id !== journey.id);
    }
    next.push(journey);
    deviceState = { ...deviceState, consent_at: new Date().toISOString(), journeys: next };
    if (!saveDevice()) {
      deviceState.journeys = deviceState.journeys.filter((item) => item.id !== journey.id);
      showMessage(t('ui.jw.storage_unavailable', 'Bu tarayıcı kayıt tutamıyor. Bu bölümde yolculuk saklanamaz.'), true);
      return;
    }
    form.reset();
    seedNeeds();
    render();
    await checkNow();
  });

  checkButton.addEventListener('click', () => checkNow({ announce: true }));
  section.addEventListener('click', async (event) => {
    const remove = event.target.closest('[data-remove]');
    if (remove) {
      const id = remove.getAttribute('data-remove');
      if ((deviceState.account_ids || []).includes(id)) {
        if (MOCK) {
          showMessage(t('ui.jw.mock_unavailable', 'Örnek modda yolculuk kontrolü yapılmaz.'), true);
          return;
        }
        try { await del(`/api/account/journeys/${encodeURIComponent(id)}`); }
        catch (error) {
          showMessage(error && error.message ? error.message : t('ui.jw.account_delete_error', 'Hesap yolculuğu silinemedi.'), true);
          return;
        }
        deviceState.account_ids = deviceState.account_ids.filter((item) => item !== id);
      }
      deviceState.journeys = deviceState.journeys.filter((journey) => journey.id !== id);
      delete deviceState.last[id];
      delete deviceState.choice[id];
      saveDevice();
      render();
      return;
    }
    const decide = event.target.closest('[data-choice]');
    if (decide) {
      const id = decide.getAttribute('data-id');
      const previous = deviceState.last[id];
      deviceState.choice[id] = {
        fingerprint: (previous && previous.fingerprint || []).join('|'),
        value: decide.getAttribute('data-choice'),
      };
      saveDevice();
      renderImpact();
      return;
    }
    const target = event.target.closest('[data-focus-alternative]');
    if (target) {
      event.preventDefault();
      const anchor = document.querySelector('#alternative');
      if (anchor) { anchor.tabIndex = -1; anchor.scrollIntoView(); anchor.focus(); }
    }
  });

  onLang(() => { render(); syncSaveCurrentJourney(); });
  if (typeof MutationObserver !== 'undefined' && !observeJourneyResult()) {
    const observer = new MutationObserver(() => {
      if (observeJourneyResult()) observer.disconnect();
    });
    observer.observe(main, { childList: true, subtree: true });
  }
  if (typeof window !== 'undefined') window.addEventListener('nabiz:account-changed', () => syncAccount());
  addStyleAndCard();
  syncSaveCurrentJourney();
}

if (typeof document !== 'undefined') install();

export { STORAGE_KEY, cleanJourney, readSaved, writeSaved, cardModel, shouldShowOnHome };
