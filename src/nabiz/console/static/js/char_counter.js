const CHAR_LIMIT = 300;
const WARN_FROM = 280;
const INVISIBLE = /[\p{Cf}\u{E0100}-\u{E01EF}]|[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F-\u009F]/gu;

function visibleLength(value) {
  return Array.from(String(value ?? '').replace(INVISIBLE, '')).length;
}

function counterState(value) {
  const count = visibleLength(value);
  const over = count > CHAR_LIMIT;
  return {
    count,
    remaining: Math.max(0, CHAR_LIMIT - count),
    over,
    warn: count >= WARN_FROM,
    text: over
      ? `300 karakteri ${count - CHAR_LIMIT} aştın. Lütfen kısalt.`
      : `Kalan ${CHAR_LIMIT - count} karakter`,
  };
}

function mountCharCounter(doc) {
  if (!doc) return;
  const form = doc.querySelector('#chat-form');
  const input = doc.querySelector('#chat-input');
  const row = form?.querySelector('.chat-row');
  if (!form || !input || !row) return;

  const visible = doc.createElement('p');
  visible.id = 'chat-count';
  visible.className = 'field-hint stamp';
  visible.setAttribute('aria-hidden', 'true');
  const live = doc.createElement('p');
  live.id = 'chat-count-live';
  live.className = 'sr-only';
  live.setAttribute('aria-live', 'polite');
  row.insertAdjacentElement('afterend', visible);
  visible.insertAdjacentElement('afterend', live);

  const describedBy = (input.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean);
  if (!describedBy.includes(live.id)) describedBy.push(live.id);
  input.setAttribute('aria-describedby', describedBy.join(' '));

  let timer = null;
  let lastAnnounced = counterState(input.value).text;
  const refresh = () => {
    const state = counterState(input.value);
    visible.textContent = state.text;
    visible.classList.toggle('is-warn', state.warn);
    if (state.over) input.setAttribute('aria-invalid', 'true');
    else input.removeAttribute('aria-invalid');
    if (timer !== null) clearTimeout(timer);
    timer = setTimeout(() => {
      if (state.text !== lastAnnounced) {
        live.textContent = state.text;
        lastAnnounced = state.text;
      }
      timer = null;
    }, 1000);
  };

  for (const eventName of ['input', 'change', 'focus', 'keyup']) input.addEventListener(eventName, refresh);
  doc.addEventListener('submit', (event) => {
    if (event.target === form) setTimeout(refresh, 0);
  }, true);
  refresh();
}

if (typeof document !== 'undefined') mountCharCounter(document);

export { CHAR_LIMIT, WARN_FROM, visibleLength, counterState, mountCharCounter };
