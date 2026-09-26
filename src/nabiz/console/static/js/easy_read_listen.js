import { pickVoice } from './voice.js';

export const RATES = Object.freeze([0.8, 1, 1.2]);
export const LISTEN_SOURCES = Object.freeze([
  Object.freeze({ kind: 'answer', selector: '.answer-short p, .answer-card .ac-short p, .answer-card .ac-fixed' }),
  Object.freeze({ kind: 'quote', selector: '.quote-exact, .quote-box blockquote.quote-text' }),
  Object.freeze({ kind: 'step', selector: '.chat-final ol > li, .answer-card .ac-steps li' }),
]);

const ABBREVIATIONS = new Set(['vb', 'vs', 'örn', 'bkz', 'dr', 'prof', 'no', 'mah', 'cad', 'sok']);

export function splitSentences(text) {
  const source = String(text ?? '');
  const parts = [];
  let start = 0;
  let depth = 0;
  for (let i = 0; i < source.length; i += 1) {
    const char = source[i];
    if (char === '(') depth += 1;
    if (char === ')') depth = Math.max(0, depth - 1);
    if (depth) continue;
    let end = -1;
    if (char === '\n') {
      end = i + 1;
    } else if (char === '\r' && source[i + 1] === '\n') {
      end = i + 2;
    } else if ('.!?…'.includes(char) && /\s/u.test(source[i + 1] || '')) {
      if (char === '.' && /\d/u.test(source[i - 1] || '') && /\d/u.test(source[i + 1] || '')) continue;
      const before = source.slice(start, i).match(/([\p{L}]+)$/u)?.[1]?.toLocaleLowerCase('tr-TR');
      if (char === '.' && ABBREVIATIONS.has(before)) continue;
      end = i + 1;
      while (end < source.length && /\s/u.test(source[end])) end += 1;
    }
    if (end > start) {
      parts.push(source.slice(start, end));
      start = end;
      i = end - 1;
    }
  }
  if (start < source.length) parts.push(source.slice(start));
  return parts;
}

export function collectBlocks(card) {
  if (!card || typeof card.querySelectorAll !== 'function') return [];
  const selectors = LISTEN_SOURCES.map((source) => source.selector).join(', ');
  return Array.from(card.querySelectorAll(selectors)).map((node) => {
    const source = LISTEN_SOURCES.find((item) => node.matches(item.selector));
    return { kind: source.kind, text: node.textContent || '', node };
  }).filter((block) => block.text.trim());
}

export function listenPlan(blocks) {
  const plan = [];
  for (const source of Array.isArray(blocks) ? blocks : []) {
    const text = String(source?.text ?? '');
    let offset = 0;
    for (const sentence of splitSentences(text)) {
      const leading = sentence.match(/^\s*/u)?.[0].length || 0;
      const trailing = sentence.match(/\s*$/u)?.[0].length || 0;
      const start = offset + leading;
      const end = offset + sentence.length - trailing;
      if (end > start) plan.push({ block: source.node || source, start, end, text: sentence });
      offset += sentence.length;
    }
  }
  return plan;
}

export function chooseVoice(voices) {
  const available = Array.isArray(voices) ? voices.filter(Boolean) : [];
  return pickVoice(available.filter((voice) => voice.localService === true)) || pickVoice(available);
}

export function createListener({ synth, getVoice, onState = () => {}, onSentence = () => {} } = {}) {
  let plan = [];
  let index = -1;
  let rate = 1;
  let generation = 0;
  let currentState = 'idle';

  function report(state) {
    currentState = state;
    onState({ state, index, total: plan.length });
  }

  function finish() {
    index = -1;
    onSentence(null);
    report('idle');
  }

  function speakAt(nextIndex) {
    if (!synth || typeof SpeechSynthesisUtterance !== 'function' || nextIndex >= plan.length) {
      finish();
      return;
    }
    index = nextIndex;
    const item = plan[index];
    const text = item.text.trim();
    if (!text) {
      speakAt(index + 1);
      return;
    }
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = 'tr-TR';
    utterance.rate = rate;
    utterance.voice = typeof getVoice === 'function' ? getVoice() : null;
    const token = generation;
    onSentence(item);
    report('speaking');
    utterance.onend = () => {
      if (token === generation && currentState === 'speaking') speakAt(index + 1);
    };
    utterance.onerror = () => {
      if (token === generation && currentState === 'speaking') finish();
    };
    synth.speak(utterance);
  }

  function start(card, nextPlan, nextRate = 1) {
    generation += 1;
    if (synth) synth.cancel();
    plan = Array.isArray(nextPlan) ? nextPlan : [];
    rate = RATES.includes(nextRate) ? nextRate : 1;
    index = 0;
    if (!plan.length) {
      finish();
      return false;
    }
    speakAt(0);
    return true;
  }

  function pause() {
    if (currentState !== 'speaking') return;
    generation += 1;
    if (synth) synth.cancel();
    report('paused');
  }

  function resume() {
    if (currentState !== 'paused' || index < 0) return;
    generation += 1;
    speakAt(index);
  }

  function stop() {
    generation += 1;
    if (synth) synth.cancel();
    finish();
  }

  function setRate(nextRate) {
    if (RATES.includes(nextRate)) rate = nextRate;
    return rate;
  }

  return {
    start,
    pause,
    resume,
    stop,
    setRate,
    get state() { return currentState; },
  };
}
