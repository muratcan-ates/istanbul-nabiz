/* Adapted from DOU-Synapse apps/web/components/chat-feedback.tsx (MIT, Copyright (c) 2026 Muratcan Ates). */

import { esc } from './format.js';
import { onLang, t } from './i18n_text.js';

const FEEDBACK_KEY = 'nabiz.feedback.v1';
const REASON_TR = Object.freeze({ wrong: 'Yanlış', stale: 'Eski bilgi', misunderstood: 'Sorumu anlamadı', other: 'Başka' });
const PROBLEM_REASONS = Object.freeze(['wrong', 'stale', 'misunderstood', 'other']);
const FEEDBACK_TEXT = Object.freeze({
  label: 'Cevap geri bildirimi', question: 'Bu cevap işinize yaradı mı?',
  up: 'Evet, işime yaradı', down: 'Hayır, işime yaramadı', why: 'Neden?',
  share: 'Anonim olarak gönder: yalnız oy ve neden kodu gider; sorunuz, cevap ve kimliğiniz gitmez',
  save: 'Kaydet', cancel: 'Vazgeç', thanks: 'Teşekkürler.', saved: 'Kaydedildi.',
  saved_reason: 'Kaydedildi: {reason}.', no_reason: 'neden seçilmedi',
});
const feedbackText = (key, vars) => t(`dyn.feedback_${key}`, FEEDBACK_TEXT[key], vars);
const reasonLabel = (reason) => REASON_TR[reason]
  ? t(`dyn.feedback_reason_${reason}`, REASON_TR[reason]) : feedbackText('no_reason');

function feedbackNote(control, key, reason = '') {
  const note = control.querySelector('.feedback-note');
  note.dataset.feedbackText = key;
  note.dataset.feedbackReason = reason || '';
  note.textContent = feedbackText(key, { reason: reasonLabel(reason) });
}

function translateFeedback(log) {
  log.querySelectorAll('.feedback').forEach((control) => {
    control.setAttribute('aria-label', feedbackText('label'));
    control.querySelectorAll('.feedback-vote').forEach((button) => button.setAttribute('aria-label', feedbackText(button.dataset.vote)));
    control.querySelectorAll('[data-feedback-text]').forEach((node) => {
      node.textContent = feedbackText(node.dataset.feedbackText, { reason: reasonLabel(node.dataset.feedbackReason) });
    });
    control.querySelectorAll('span[data-feedback-reason]').forEach((node) => { node.textContent = reasonLabel(node.dataset.feedbackReason); });
  });
}
const EMPTY_COUNTS = Object.freeze({
  version: 1,
  up: 0,
  down: 0,
  reasons: Object.freeze({ wrong: 0, stale: 0, misunderstood: 0, other: 0 }),
  share: false,
});

function feedbackMarkup(answerId) {
  const reasons = PROBLEM_REASONS.map((reason) => `<label class="check"><input type="radio" name="reason" value="${reason}">`
    + `<span data-feedback-reason="${reason}">${esc(reasonLabel(reason))}</span></label>`).join('');
  return `<div class="feedback" data-answer-id="${esc(answerId)}" role="group" aria-label="${esc(feedbackText('label'))}">`
    + `<p class="feedback-q" data-feedback-text="question">${esc(feedbackText('question'))}</p>`
    + '<div class="btn-row">'
    + `<button type="button" class="btn feedback-vote" data-vote="up" aria-pressed="false" aria-label="${esc(feedbackText('up'))}">`
    + '<span aria-hidden="true">👍</span></button>'
    + `<button type="button" class="btn feedback-vote" data-vote="down" aria-pressed="false" aria-label="${esc(feedbackText('down'))}">`
    + '<span aria-hidden="true">👎</span></button></div>'
    + '<p class="feedback-note" role="status" aria-live="polite"></p>'
    + `<form class="feedback-why" hidden><fieldset><legend data-feedback-text="why">${esc(feedbackText('why'))}</legend>${reasons}</fieldset>`
    + '<label class="check"><input type="checkbox" name="share">'
    + `<span data-feedback-text="share">${esc(feedbackText('share'))}</span></label>`
    + `<div class="btn-row"><button type="submit" class="btn" data-feedback-text="save">${esc(feedbackText('save'))}</button>`
    + `<button type="button" class="btn" data-act="cancel" data-feedback-text="cancel">${esc(feedbackText('cancel'))}</button></div></form></div>`;
}

function blankCounts() {
  return { version: 1, up: 0, down: 0, reasons: { wrong: 0, stale: 0, misunderstood: 0, other: 0 }, share: false };
}

function copyCounts(counts) {
  const source = counts && typeof counts === 'object' ? counts : {};
  const reasons = source.reasons && typeof source.reasons === 'object' ? source.reasons : {};
  return {
    version: 1,
    up: Number.isSafeInteger(source.up) && source.up >= 0 ? source.up : 0,
    down: Number.isSafeInteger(source.down) && source.down >= 0 ? source.down : 0,
    reasons: Object.fromEntries(PROBLEM_REASONS.map((key) => [key,
      Number.isSafeInteger(reasons[key]) && reasons[key] >= 0 ? reasons[key] : 0])),
    share: source.share === true,
  };
}

function countFeedback(counts, vote, reason) {
  const next = copyCounts(counts);
  if (vote === 'up' || vote === 'down') next[vote] += 1;
  if (PROBLEM_REASONS.includes(reason)) next.reasons[reason] += 1;
  return next;
}

function feedbackPayload(answerId, vote, reason) {
  return { answer_id: answerId, vote, reason: reason || null };
}

function newAnswerId() {
  const bytes = new Uint8Array(8);
  globalThis.crypto.getRandomValues(bytes);
  return `a-${Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')}`;
}

function answerIdFor(message) {
  if (message.dataset.answerId) return message.dataset.answerId;
  const id = newAnswerId();
  message.dataset.answerId = id;
  return id;
}

function readCounts(storage) {
  try {
    const raw = storage.getItem(FEEDBACK_KEY);
    if (!raw) return blankCounts();
    const value = JSON.parse(raw);
    if (!value || typeof value !== 'object' || Array.isArray(value) || value.version !== 1) return blankCounts();
    return copyCounts(value);
  } catch (error) {
    return blankCounts();
  }
}

function writeCounts(counts, storage) {
  try { storage.setItem(FEEDBACK_KEY, JSON.stringify(copyCounts(counts))); } catch (error) { /* Private mode keeps feedback in memory. */ }
}

function mountFeedback(log) {
  if (!log || typeof document === 'undefined' || typeof MutationObserver === 'undefined') return;
  if (log.dataset.feedbackMounted === 'true') return;
  log.dataset.feedbackMounted = 'true';
  const priorByAnswer = new Map();
  const storage = {
    getItem: (key) => { try { return window.localStorage.getItem(key); } catch (error) { return null; } },
    setItem: (key, value) => { try { window.localStorage.setItem(key, value); } catch (error) { /* Private mode. */ } },
  };
  let counts = readCounts(storage);
  onLang(() => translateFeedback(log));

  const send = async (answerId, vote, reason) => {
    try {
      await fetch('/api/feedback', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(feedbackPayload(answerId, vote, reason)),
        credentials: 'omit',
        referrerPolicy: 'no-referrer',
      });
    } catch (error) { /* The device counter remains useful when the optional endpoint is absent. */ }
  };

  const saveVote = (control, vote, reason, share) => {
    const answerId = control.dataset.answerId;
    const previous = priorByAnswer.get(answerId);
    if (previous && (previous.vote !== vote || previous.reason !== reason)) {
      counts[previous.vote] = Math.max(0, counts[previous.vote] - 1);
      if (previous.reason) counts.reasons[previous.reason] = Math.max(0, counts.reasons[previous.reason] - 1);
    } else if (previous) {
      if (counts.share !== share) {
        counts.share = share;
        writeCounts(counts, storage);
        if (share) void send(answerId, vote, reason);
      }
      feedbackNote(control, vote === 'up' ? 'thanks' : 'saved_reason', reason);
      return false;
    }
    counts = countFeedback(counts, vote, reason);
    counts.share = share;
    writeCounts(counts, storage);
    priorByAnswer.set(answerId, { vote, reason: PROBLEM_REASONS.includes(reason) ? reason : null });
    control.querySelectorAll('.feedback-vote').forEach((button) => {
      button.setAttribute('aria-pressed', button.dataset.vote === vote ? 'true' : 'false');
    });
    if (share) void send(answerId, vote, reason);
    return true;
  };

  const attach = () => {
    log.querySelectorAll('li.chat-msg.is-assistant').forEach((message) => {
      if (message.getAttribute('aria-busy') !== 'false' || message.classList.contains('is-error')
        || !message.querySelector('.chat-foot') || message.querySelector('.feedback')) return;
      const final = message.querySelector('.chat-final');
      if (!final) return;
      const template = document.createElement('template');
      template.innerHTML = feedbackMarkup(answerIdFor(message));
      final.append(template.content.firstElementChild);
    });
  };

  log.addEventListener('click', (event) => {
    const button = event.target.closest('.feedback-vote, [data-act="cancel"]');
    if (!button) return;
    const control = button.closest('.feedback');
    if (!control) return;
    const form = control.querySelector('.feedback-why');
    if (button.matches('[data-act="cancel"]')) {
      form.hidden = true;
      saveVote(control, 'down', null, counts.share);
      feedbackNote(control, 'saved');
      return;
    }
    if (button.dataset.vote === 'up') {
      form.hidden = true;
      if (saveVote(control, 'up', null, counts.share) !== false) feedbackNote(control, 'thanks');
      return;
    }
    const previous = priorByAnswer.get(control.dataset.answerId);
    const previousReason = form.querySelector(`input[name="reason"][value="${previous && previous.reason || 'wrong'}"]`);
    if (previousReason) previousReason.checked = true;
    form.querySelector('input[name="share"]').checked = counts.share;
    form.hidden = false;
    form.querySelector('input[name="reason"]')?.focus();
  });

  log.addEventListener('submit', (event) => {
    const form = event.target.closest('.feedback-why');
    if (!form) return;
    event.preventDefault();
    const control = form.closest('.feedback');
    const reason = form.querySelector('input[name="reason"]:checked')?.value || null;
    const share = form.querySelector('input[name="share"]').checked;
    if (saveVote(control, 'down', reason, share) !== false) {
      form.hidden = true;
      feedbackNote(control, 'saved_reason', reason);
    }
  });

  const observer = new MutationObserver(attach);
  observer.observe(log, { childList: true, attributes: true, attributeFilter: ['aria-busy'], subtree: true });
  attach();
}

if (typeof document !== 'undefined') mountFeedback(document.querySelector('#chat-log'));

export {
  REASON_TR, PROBLEM_REASONS, feedbackMarkup, countFeedback, feedbackPayload, newAnswerId, answerIdFor, mountFeedback,
};
