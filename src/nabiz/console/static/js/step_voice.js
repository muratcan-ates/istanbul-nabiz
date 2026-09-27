/* A self-mounting, optional route panel for the citizen chat. */

import { get } from './api.js';
import { esc } from './format.js';
import { icon } from './icons.js';
import { currentLang, onLang, t } from './i18n_text.js';
import { createSpeaker, pickVoiceFor, routeHint, stepPosition, voiceNote } from './step_voice_core.js';

const STYLESHEET = '/css/step_voice.css';
const OFFER_INTENT_TR = /nasıl\s+gid|gider|gidil|gidebil|ulaş|yol\s+tarif|yön\s+tarif|aktarma|adımsız/iu;
const OFFER_INTENT_EN = /how\s+do\s+i\s+get|how\s+to\s+get|directions|route|step-free/iu;

const COPY = Object.freeze({
  offer: (vars) => t('ui.steps.offer', 'Buraya adım adım yön tarifi ister misiniz?', vars),
  toLabel: (vars) => t('ui.steps.toLabel', 'Varış: {place}', vars),
  title: (vars) => t('ui.steps.title', 'Adım adım rota', vars),
  close: (vars) => t('ui.steps.close', 'Kapat', vars),
  from: (vars) => t('ui.steps.from', 'Nereden?', vars),
  to: (vars) => t('ui.steps.to', 'Nereye?', vars),
  getSteps: (vars) => t('ui.steps.getSteps', 'Adımları getir', vars),
  loading: (vars) => t('ui.steps.loading', 'Adımlar hazırlanıyor.', vars),
  unavailable: (vars) => t('ui.steps.unavailable', 'Bu rota doğrulanamadı.', vars),
  error: (vars) => t('ui.steps.error', 'Adımlar alınamadı.', vars),
  tryAnother: (vars) => t('ui.steps.tryAnother', 'Başka bir yer deneyin', vars),
  emptyPlaces: (vars) => t('ui.steps.emptyPlaces', 'İki yeri de yazın.', vars),
  noVoice: (vars) => t('ui.steps.noVoice', 'Bu tarayıcıda {lang} ses yok; adımları ekrandan okuyabilirsiniz.', vars),
  languageTr: (vars) => t('ui.steps.languageTr', 'Türkçe', vars),
  languageEn: (vars) => t('ui.steps.languageEn', 'English', vars),
  onlineVoice: (vars) => t('ui.steps.onlineVoice', 'Bu ses çevrim içi; okunan metin tarayıcının ses sağlayıcısına gidebilir. Nabız sunucusuna gitmez.', vars),
  readAloud: (vars) => t('ui.steps.readAloud', 'Sesli oku', vars),
  readAgain: (vars) => t('ui.steps.readAgain', 'Tekrar oku', vars),
  stopReading: (vars) => t('ui.steps.stopReading', 'Sesi kapat', vars),
  scope: (vars) => t('ui.steps.scope', 'İstasyon içi ve kayıtlı rota adımları; sokak navigasyonu değildir.', vars),
  source: (vars) => t('ui.steps.source', 'Kaynak', vars),
  sourceName: (vars) => t('ui.steps.sourceName', 'İBB Açık Veri Portalı', vars),
  sample: (vars) => t('ui.steps.sample', 'Örnek', vars),
  sampleRoute: (vars) => t('ui.steps.sampleRoute', 'Örnek rota: {route}', vars),
  official: (vars) => t('ui.steps.official', 'Resmî İBB hizmeti değildir.', vars),
  next: (vars) => t('ui.steps.next', 'Sonraki adım', vars),
  finish: (vars) => t('ui.steps.finish', 'Bitir', vars),
  previous: (vars) => t('ui.steps.previous', 'Önceki adım', vars),
  stopsBetween: (vars) => t('ui.steps.stopsBetween', 'Aradaki duraklar ({count})', vars),
  stepPosition: (vars) => t('ui.steps.stepPosition', 'Adım {n} / {total}', vars),
  stepTitle: (vars) => t('ui.steps.stepTitle', 'Adım {n}: {title}', vars),
  minutes: (vars) => t('ui.steps.minutes', 'yaklaşık {count} dk', vars),
  allSteps: (vars) => t('ui.steps.allSteps', 'Tüm adımlar', vars),
  journeyLaunch: (vars) => t('ui.steps.journeyLaunch', 'Adım adım ve sesli', vars),
  mapOpen: (vars) => t('ui.steps.mapOpen', 'Harita uygulamasında aç', vars),
  mapNotice: (vars) => t('ui.steps.mapNotice', 'Sokak yolunu harita uygulamanız çizer; Nabız çizmez.', vars),
});

function copy(key, vars) {
  return esc(COPY[key](vars || {}));
}

function addStylesheet(doc) {
  if (doc.head.querySelector(`link[href="${STYLESHEET}"]`)) return;
  const link = doc.createElement('link');
  link.rel = 'stylesheet';
  link.href = STYLESHEET;
  doc.head.append(link);
}

function transportTools(shell) {
  return [...shell.querySelectorAll('.chat-final li.cite')]
    .map((node) => node.textContent.trim())
    .filter((text) => text.startsWith('Ara\u00e7:'))
    .map((text) => text.match(/\(([\w.-]+)\)/u)?.[1] || '')
    .filter(Boolean);
}

function previousQuestion(log, shell) {
  const messages = [...log.querySelectorAll('li.chat-msg')];
  const position = messages.indexOf(shell);
  for (let index = position - 1; index >= 0; index -= 1) {
    if (messages[index].classList.contains('is-user')) {
      return (messages[index].querySelector('.chat-text') || messages[index]).textContent.trim();
    }
  }
  return '';
}

function journeyIntent(question, lang) {
  const pattern = lang === 'en' ? OFFER_INTENT_EN : OFFER_INTENT_TR;
  return pattern.test(question);
}

function walkingMapMarkup(card) {
  if (!card || card.kind !== 'walk' || !card.map_links || typeof card.map_links !== 'object') return '';
  const candidates = [card.map_links.google, card.map_links.apple].filter((value) => typeof value === 'string');
  let href = '';
  for (const value of candidates) {
    try {
      const url = new URL(value);
      if (url.protocol === 'https:' && ['www.google.com', 'maps.apple.com'].includes(url.hostname)) {
        href = url.href;
        break;
      }
    } catch { /* Ignore an invalid recorded map link. */ }
  }
  if (!href) return '';
  return `<p class="sv-map"><a class="btn btn-quiet" href="${esc(href)}" target="_blank" rel="noopener noreferrer">${copy('mapOpen')}</a>`
    + `<span>${copy('mapNotice')}</span></p>`;
}

function offerRow(doc, hint) {
  const row = doc.createElement('div');
  row.className = 'sv-offer-row';
  const button = doc.createElement('button');
  button.type = 'button';
  button.className = 'sv-offer glass';
  button.setAttribute('aria-haspopup', 'dialog');
  button._routeHint = hint;
  button.innerHTML = `${icon('route')}<span>${copy('offer')}</span>`
    + `<span class="sv-offer-to">${copy('toLabel', { place: hint.to })}</span>`;
  row.append(button);
  return row;
}

function mountStepVoice(log) {
  if (!log) return;
  const doc = log.ownerDocument;
  const host = doc.defaultView || globalThis;
  addStylesheet(doc);

  let dialog = null;
  let content = null;
  let footer = null;
  let activeIndex = 0;
  let route = null;
  let lastParams = null;
  let stepWasSpoken = false;
  let requestNumber = 0;
  let selectedVoice = null;
  const speechApi = host.speechSynthesis || null;
  const Utterance = host.SpeechSynthesisUtterance;
  const speaker = createSpeaker({
    synth: speechApi,
    Utterance,
    onState: () => refreshSpeechControls(),
  });

  function tr(key, vars) {
    return copy(key, vars);
  }

  function setFooter(result) {
    const stamp = result && result.freshness && result.freshness.text;
    const source = result && result.provenance && result.provenance.source;
    const sample = result && result.sample === true;
    const routeName = result && result.sample_route;
    footer.innerHTML = `<p id="sv-scope">${tr('scope')}</p>`
      + (stamp ? `<p class="sv-freshness">${esc(stamp)}</p>` : '')
      + (source ? `<p class="sv-source">${tr('source')}: ${tr('sourceName')}</p>` : '')
      + (sample ? `<p class="sv-sample"><span>${tr('sample')}</span> ${tr('sampleRoute', { route: routeName || '' })}</p>` : '')
      + `<p class="sv-official">${tr('official')}</p>`;
    dialog.setAttribute('aria-describedby', 'sv-scope');
  }

  function createDialog() {
    if (dialog) return dialog;
    dialog = doc.createElement('dialog');
    dialog.id = 'step-sheet';
    dialog.className = 'sv-sheet';
    dialog.setAttribute('aria-labelledby', 'sv-title');
    dialog.innerHTML = '<div class="sv-sheet-inner">'
      + '<header class="sv-header"><h2 id="sv-title"></h2><button type="button" class="btn btn-quiet sv-close"></button></header>'
      + '<div class="sv-content"></div><footer class="sv-footer"></footer></div>';
    doc.body.append(dialog);
    content = dialog.querySelector('.sv-content');
    footer = dialog.querySelector('.sv-footer');
    setFooter(null);
    dialog.addEventListener('cancel', () => speaker.stop());
    dialog.addEventListener('close', panelClosed);
    dialog.addEventListener('click', onPanelClick);
    dialog.addEventListener('submit', onPanelSubmit);
    return dialog;
  }

  function panelClosed() {
    speaker.stop();
    requestNumber += 1;
    route = null;
    stepWasSpoken = false;
    lastParams = null;
    activeIndex = 0;
    log.querySelector('.sv-offer')?.focus();
    if (!doc.querySelector('.sv-offer')) doc.querySelector('#chat-input')?.focus();
  }

  function openPanel(hint) {
    const panel = createDialog();
    speaker.stop();
    route = null;
    stepWasSpoken = false;
    activeIndex = 0;
    lastParams = null;
    panel.querySelector('#sv-title').textContent = copy('title');
    panel.querySelector('.sv-close').textContent = copy('close');
    if (!panel.open) {
      if (typeof panel.showModal === 'function') {
        try { panel.showModal(); } catch { panel.setAttribute('open', ''); }
      } else panel.setAttribute('open', '');
    }
    const from = hint && hint.from ? hint.from : '';
    const to = hint && hint.to ? hint.to : '';
    if (from && to) void loadRoute(from, to);
    else renderForm({ from, to });
    queueMicrotask(() => {
      const inputs = [...panel.querySelectorAll('.sv-form input')];
      const firstEmpty = inputs.find((input) => !input.value.trim());
      const primary = panel.querySelector('.btn-primary');
      (firstEmpty || primary || panel.querySelector('.sv-close') || panel).focus();
    });
  }

  function renderForm(values = {}, message = '') {
    route = null;
    const fromValue = esc(values.from || '');
    const toValue = esc(values.to || '');
    content.innerHTML = '<form class="sv-form" novalidate autocomplete="off">'
      + `<label for="sv-from">${tr('from')}</label>`
      + `<input id="sv-from" name="from" maxlength="120" required value="${fromValue}">`
      + `<label for="sv-to">${tr('to')}</label>`
      + `<input id="sv-to" name="to" maxlength="120" required value="${toValue}">`
      + `<p class="sv-inline-status" role="status">${esc(message)}</p>`
      + `<div class="sv-actions"><button type="submit" class="btn btn-primary">${tr('getSteps')}</button></div>`
      + '</form>';
    setFooter(null);
  }

  function renderLoading() {
    content.innerHTML = `<p class="sv-loading" role="status" aria-busy="true">${tr('loading')}</p>`;
    setFooter(null);
  }

  function renderUnavailable(result) {
    content.innerHTML = `<section class="sv-unavailable"><p>${esc(result.reason || copy('unavailable'))}</p>`
      + `<p class="sv-disclaimer">${esc(result.disclaimer || '')}</p>`
      + `<div class="sv-actions"><button type="button" class="btn btn-primary" data-step-action="another">${tr('tryAnother')}</button></div></section>`;
    setFooter(result);
  }

  function voiceMarkup(card) {
    if (!selectedVoice) {
      const langName = currentLang() === 'en' ? copy('languageEn') : copy('languageTr');
      return `<p class="sv-voice-note">${tr('noVoice', { lang: langName })}</p>`;
    }
    const note = voiceNote(selectedVoice) === 'online'
      ? `<p class="sv-voice-note">${tr('onlineVoice')}</p>`
      : '';
    const label = speaker.speaking || stepWasSpoken ? tr('readAgain') : tr('readAloud');
    return `<button type="button" class="btn" data-step-action="read">${label}</button>`
      + `<button type="button" class="btn btn-quiet" data-step-action="stop"${speaker.speaking ? '' : ' hidden'}>${tr('stopReading')}</button>${note}`;
  }

  function renderAvailable(result, focusNext = false, direction = '') {
    route = result;
    const cards = Array.isArray(result.cards) ? result.cards : [];
    const position = stepPosition(activeIndex, cards.length);
    activeIndex = position.index;
    const card = cards[position.index];
    if (!card) {
      renderUnavailable({ ...result, reason: result.reason || copy('unavailable') });
      return;
    }
    const between = Array.isArray(card.between) ? card.between : [];
    const stopDetails = between.length
      ? `<details class="sv-more"><summary>${tr('stopsBetween', { count: between.length })}</summary><ul>${between.map((stop) => `<li>${esc(stop)}</li>`).join('')}</ul></details>`
      : '';
    const allSteps = cards.map((item, index) => `<li><span>${tr('stepTitle', { n: index + 1, title: item.title })}</span><span>${tr('minutes', { count: item.minutes })}</span></li>`).join('');
    const note = Array.isArray(result.notes) && result.notes.length
      ? `<p class="sv-note">${result.notes.map(esc).join(' ')}</p>` : '';
    const header = `${tr('stepPosition', { n: position.n, total: position.total })}`;
    const statusText = speaker.speaking || stepWasSpoken ? header : `${header}. ${card.title}`;
    const primary = position.last ? tr('finish') : tr('next');
    content.innerHTML = `<p class="sv-route-summary">${esc(result.summary || '')}</p>${note}<article class="sv-step-card"${direction ? ` data-direction="${direction}"` : ''} aria-labelledby="sv-current-title">`
      + `<p class="sv-position">${header}</p><div class="sv-step-icon">${icon(card.icon)}</div>`
      + `<h3 id="sv-current-title">${esc(card.title)}</h3><p class="sv-detail">${esc(card.detail)}</p>`
      + `${walkingMapMarkup(card)}`
      + (card.lift_text ? `<p class="sv-lift">${icon('elevator')}<span>${esc(card.lift_text)}</span></p>` : '')
      + `${stopDetails}</article>`
      + `<div class="sv-actions"><button type="button" class="btn btn-primary" data-step-action="next">${primary}</button>`
      + `<div class="sv-audio-actions">${voiceMarkup(card)}</div>`
      + (position.first ? '' : `<button type="button" class="btn btn-quiet" data-step-action="previous">${tr('previous')}</button>`)
      + '</div>'
      + `<details class="sv-all"><summary>${tr('allSteps')}</summary><ol>${allSteps}</ol></details>`
      + `<p id="sv-step-status" class="sv-step-status" role="status" aria-live="polite">${esc(statusText)}</p>`
      + `<p class="sv-disclaimer">${esc(result.disclaimer || '')}</p>`;
    setFooter(result);
    refreshSpeechControls();
    if (focusNext) content.querySelector('[data-step-action="next"]')?.focus();
  }

  function refreshSpeechControls() {
    if (!dialog || !route || !dialog.open) return;
    const card = route.cards && route.cards[activeIndex];
    if (!card) return;
    const read = content.querySelector('[data-step-action="read"]');
    const stop = content.querySelector('[data-step-action="stop"]');
    if (read) read.textContent = copy(speaker.speaking || stepWasSpoken ? 'readAgain' : 'readAloud');
    if (stop) stop.hidden = !speaker.speaking;
    const status = content.querySelector('#sv-step-status');
    if (status) {
      const pos = stepPosition(activeIndex, route.cards.length);
      const label = copy('stepPosition', { n: pos.n, total: pos.total });
      status.textContent = speaker.speaking || stepWasSpoken ? label : `${label}. ${card.title}`;
    }
  }

  async function loadRoute(from, to) {
    const lang = currentLang() === 'en' ? 'en' : 'tr';
    const token = ++requestNumber;
    lastParams = { from, to };
    stepWasSpoken = false;
    speaker.stop();
    renderLoading();
    try {
      const result = await get('/api/route/steps', { from, to, needs: 'step_free', lang });
      if (token !== requestNumber || !dialog.open) return;
      route = result;
      activeIndex = 0;
      if (result.available === true) renderAvailable(result, doc.activeElement === dialog.querySelector('.sv-close'));
      else renderUnavailable(result);
    } catch {
      if (token !== requestNumber || !dialog.open) return;
      route = null;
      content.innerHTML = `<section class="sv-error"><p role="status">${tr('error')}</p>`
        + `<div class="sv-actions"><button type="button" class="btn btn-primary" data-step-action="another">${tr('tryAnother')}</button></div></section>`;
      setFooter(null);
    }
  }

  function onPanelSubmit(event) {
    const form = event.target.closest('.sv-form');
    if (!form) return;
    event.preventDefault();
    const from = form.elements.namedItem('from');
    const to = form.elements.namedItem('to');
    if (!from.value.trim() || !to.value.trim()) {
      const missing = !from.value.trim() ? from : to;
      const values = { from: from.value, to: to.value };
      renderForm(values, copy('emptyPlaces'));
      content.querySelector(!from.value.trim() ? '#sv-from' : '#sv-to')?.focus();
      return;
    }
    void loadRoute(from.value.trim(), to.value.trim());
  }

  function onPanelClick(event) {
    if (event.target.closest('.sv-close')) { closePanel(); return; }
    const action = event.target.closest('[data-step-action]')?.dataset.stepAction;
    if (!action) return;
    if (action === 'another') {
      stepWasSpoken = false;
      speaker.stop();
      renderForm({ from: lastParams && lastParams.from || '', to: lastParams && lastParams.to || '' });
      content.querySelector('#sv-from')?.focus();
      return;
    }
    if (action === 'read') {
      const card = route && route.cards[activeIndex];
      if (card && selectedVoice) {
        stepWasSpoken = true;
        speaker.say(card.speech, selectedVoice, currentLang());
      }
      return;
    }
    if (action === 'stop') { stepWasSpoken = false; speaker.stop(); refreshSpeechControls(); return; }
    if (action === 'next' && route) {
      const wasSpeaking = speaker.speaking;
      const pos = stepPosition(activeIndex, route.cards.length);
      if (pos.last) { closePanel(); return; }
      stepWasSpoken = wasSpeaking;
      activeIndex = pos.index + 1;
      renderAvailable(route, true, 'next');
      if (wasSpeaking && selectedVoice) speaker.say(route.cards[activeIndex].speech, selectedVoice, currentLang());
      return;
    }
    if (action === 'previous' && route) {
      const wasSpeaking = speaker.speaking;
      stepWasSpoken = wasSpeaking;
      activeIndex = Math.max(0, activeIndex - 1);
      renderAvailable(route, true, 'previous');
      if (wasSpeaking && selectedVoice) speaker.say(route.cards[activeIndex].speech, selectedVoice, currentLang());
    }
  }

  function closePanel() {
    if (!dialog) return;
    speaker.stop();
    if (dialog.open && typeof dialog.close === 'function') dialog.close();
    else {
      dialog.removeAttribute('open');
      panelClosed();
    }
  }

  function evaluate() {
    if (doc.querySelector('#handoff-card')) {
      log.querySelectorAll('.sv-offer-row').forEach((row) => row.remove());
      return;
    }
    const fresh = [...log.querySelectorAll('li.chat-msg.is-assistant[aria-busy="false"]:not([data-steps-seen])')];
    if (!fresh.length) return;
    fresh.forEach((shell) => { shell.dataset.stepsSeen = '1'; });
    const assistants = [...log.querySelectorAll('li.chat-msg.is-assistant')];
    const latest = assistants[assistants.length - 1];
    log.querySelectorAll('.sv-offer-row').forEach((row) => row.remove());
    if (!latest || !fresh.includes(latest)) return;
    if (latest.classList.contains('is-emergency') || latest.classList.contains('is-refused')
      || latest.classList.contains('is-error')) return;
    const question = previousQuestion(log, latest);
    const lang = currentLang();
    const hint = routeHint({ question, tools: transportTools(latest), emergency: false, refused: false, lang });
    if (!hint || !journeyIntent(question, lang)) return;
    const final = latest.querySelector('.chat-final');
    if (!final) return;
    if (final.querySelector('.answer-card.is-unknown')) return;
    const answer = final.querySelector('section.answer-card');
    (answer || final).insertAdjacentElement('afterend', offerRow(doc, hint));
  }

  function mountJourneyLauncher() {
    const section = doc.querySelector('#journey-section');
    if (!section || section.querySelector('.sv-journey-launch')) return;
    const button = doc.createElement('button');
    button.type = 'button';
    button.className = 'btn btn-quiet sv-journey-launch';
    button.textContent = copy('journeyLaunch');
    button.setAttribute('data-step-launcher', '1');
    section.append(button);
  }

  log.addEventListener('click', (event) => {
    const offer = event.target.closest('.sv-offer');
    if (offer) openPanel(offer._routeHint || {});
  });
  doc.addEventListener('click', (event) => {
    if (!event.target.closest('.sv-journey-launch')) return;
    openPanel({
      from: doc.querySelector('#journey-from')?.value.trim() || '',
      to: doc.querySelector('#journey-to')?.value.trim() || '',
    });
  });
  doc.querySelector('#chat-form')?.addEventListener('submit', () => {
    speaker.stop();
  }, true);
  doc.addEventListener('visibilitychange', () => { if (doc.hidden) speaker.stop(); });
  const observer = new MutationObserver(() => { evaluate(); mountJourneyLauncher(); });
  observer.observe(log, { childList: true, attributes: true, attributeFilter: ['aria-busy'], subtree: true });
  const launcherObserver = new MutationObserver(mountJourneyLauncher);
  if (doc.documentElement) launcherObserver.observe(doc.documentElement, { childList: true, subtree: true });
  onLang((language) => {
    const launcher = doc.querySelector('.sv-journey-launch');
    if (launcher) launcher.textContent = copy('journeyLaunch');
    if (!dialog || !dialog.open) return;
    dialog.querySelector('#sv-title').textContent = copy('title');
    dialog.querySelector('.sv-close').textContent = copy('close');
    selectedVoice = pickVoiceFor(speechApi && speechApi.getVoices ? speechApi.getVoices() : [], language);
    if (lastParams) void loadRoute(lastParams.from, lastParams.to);
    else if (route) renderAvailable(route);
    else renderForm({
      from: content.querySelector('#sv-from')?.value || '',
      to: content.querySelector('#sv-to')?.value || '',
    });
  });
  if (speechApi && typeof speechApi.addEventListener === 'function') {
    speechApi.addEventListener('voiceschanged', () => {
      selectedVoice = pickVoiceFor(speechApi.getVoices(), currentLang());
      if (route && dialog && dialog.open) renderAvailable(route);
    });
  }
  selectedVoice = pickVoiceFor(speechApi && speechApi.getVoices ? speechApi.getVoices() : [], currentLang());
  evaluate();
  mountJourneyLauncher();
}

if (typeof document !== 'undefined') mountStepVoice(document.querySelector('#chat-log'));
