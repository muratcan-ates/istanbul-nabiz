/* Adapted from DOU-Synapse apps/web/components/chat-feedback.tsx (MIT, Copyright (c) 2026 Muratcan Ates). */

import { esc } from './format.js';

const FEEDBACK_KEY = 'nabiz.feedback.v1';
const REASON_TR = Object.freeze({ wrong: 'Yanlış', stale: 'Eski bilgi', misunderstood: 'Sorumu anlamadı', other: 'Başka' });
const PROBLEM_REASONS = Object.freeze(['wrong', 'stale', 'misunderstood', 'other']);
const EMPTY_COUNTS = Object.freeze({
  version: 1,
  up: 0,
  down: 0,
  reasons: Object.freeze({ wrong: 0, stale: 0, misunderstood: 0, other: 0 }),
  share: false,
});

function feedbackMarkup(answerId) {
  const reasons = PROBLEM_REASONS.map((reason) => `<label class="check"><input type="radio" name="reason" value="${reason}">`
    + `<span>${REASON_TR[reason]}</span></label>`).join('');
  return `<div class="feedback" data-answer-id="${esc(answerId)}" role="group" aria-label="Cevap geri bildirimi">`
    + '<p class="feedback-q">Bu cevap işine yaradı mı?</p>'
    + '<div class="btn-row">'
    + '<button type="button" class="btn feedback-vote" data-vote="up" aria-pressed="false" aria-label="Evet, işime yaradı">'
    + '<span aria-hidden="true">👍</span></button>'
    + '<button type="button" class="btn feedback-vote" data-vote="down" aria-pressed="false" aria-label="Hayır, işime yaramadı">'
    + '<span aria-hidden="true">👎</span></button></div>'
    + '<p class="feedback-note" role="status" aria-live="polite"></p>'
    + `<form class="feedback-why" hidden><fieldset><legend>Neden?</legend>${reasons}</fieldset>`
    + '<label class="check"><input type="checkbox" name="share">'
    + '<span>Anonim olarak gönder: yalnız oy ve neden kodu gider; sorunuz, cevap ve kimliğiniz gitmez</span></label>'
    + '<div class="btn-row"><button type="submit" class="btn">Kaydet</button>'
    + '<button type="button" class="btn" data-act="cancel">Vazgeç</button></div></form></div>';
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
      control.querySelector('.feedback-note').textContent = vote === 'up' ? 'Teşekkürler.' : `Kaydedildi: ${REASON_TR[reason] || 'neden seçilmedi'}.`;
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
    const note = control.querySelector('.feedback-note');
    if (button.matches('[data-act="cancel"]')) {
      form.hidden = true;
      saveVote(control, 'down', null, counts.share);
      note.textContent = 'Kaydedildi.';
      return;
    }
    if (button.dataset.vote === 'up') {
      form.hidden = true;
      if (saveVote(control, 'up', null, counts.share) !== false) note.textContent = 'Teşekkürler.';
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
      control.querySelector('.feedback-note').textContent = `Kaydedildi: ${REASON_TR[reason]}.`;
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
