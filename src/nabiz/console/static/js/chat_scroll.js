import { onLang, t } from './i18n_text.js';

let messageCount = 0;
export function newMessageId() {
  return globalThis.crypto?.randomUUID?.() || `msg-${Date.now()}-${++messageCount}`;
}

export function isNearEnd({ scrollY, innerHeight, docHeight }, threshold = 160) {
  return Number.isFinite(scrollY) && Number.isFinite(innerHeight) && Number.isFinite(docHeight)
    && docHeight - scrollY - innerHeight <= threshold;
}

export function createFollower(win, doc) {
  let follow = true;
  const position = () => ({
    scrollY: win.scrollY || 0,
    innerHeight: win.innerHeight || 0,
    docHeight: Math.max(doc.documentElement?.scrollHeight || 0, doc.body?.scrollHeight || 0),
  });
  const onUserScroll = () => { follow = isNearEnd(position()); };
  win.addEventListener('scroll', onUserScroll, { passive: true });
  return { following: () => follow, onUserScroll, reset: () => { follow = true; } };
}

export function mountNewReplyButton(form) {
  const doc = form.ownerDocument || document;
  const button = doc.createElement('button');
  button.type = 'button';
  button.id = 'chat-new-reply';
  button.className = 'btn btn-quiet';
  button.hidden = true;
  button.setAttribute('aria-controls', 'chat-log');
  let target = null;
  const label = (lang) => { button.textContent = t('ui.shell.new_reply', lang === 'en' ? 'New reply' : 'Yeni yanıt'); };
  label(doc.documentElement?.lang);
  onLang(label);
  form.prepend(button);
  button.addEventListener('click', () => {
    if (!target) return;
    const heading = target.querySelector('h3, .answer-card, .chat-final') || target;
    heading.setAttribute('tabindex', '-1');
    heading.scrollIntoView?.({ block: 'nearest', behavior: 'instant' });
    heading.focus?.({ preventScroll: true });
    button.hidden = true;
  });
  const chat = doc.getElementById?.('asistan');
  const updateHeight = () => {
    const height = form.getBoundingClientRect?.().height;
    if (chat && Number.isFinite(height)) chat.style?.setProperty('--chat-composer-height', `${Math.ceil(height)}px`);
  };
  if (typeof ResizeObserver !== 'undefined') new ResizeObserver(updateHeight).observe(form);
  updateHeight();
  return { button, show: (reply) => { target = reply; button.hidden = false; }, hide: () => { target = null; button.hidden = true; } };
}
