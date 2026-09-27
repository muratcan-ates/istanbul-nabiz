/* One active conversation at a time. Storage writes are queued so a reply's turns keep their order. */
import * as conversations from './conversations.js';
import { t } from './i18n_text.js';

const DELETED_TEXT = 'Açık sohbet silindi. Yeni sohbet başladı.';
const CLEARED_TEXT = 'Tüm sohbetler silindi. Yeni sohbet başladı.';
const RECOVERED_TEXT = 'Önceki sohbet bulunamadı. Mesaj yeni bir sohbete kaydedildi.';
const FULL_TEXT = 'Bu sohbet 80 mesaja ulaştı; yeni sohbette devam ediyoruz. Eski sohbet olduğu gibi duruyor.';

function mountConversationSession({ chat, root, store = conversations }) {
  if (!chat || typeof chat.loadHistory !== 'function') throw new TypeError('Chat history loader is required');
  let active = null;
  let restoringContinuation = false;
  let queue = Promise.resolve();
  const pendingCards = new Map();
  const boundForms = new WeakSet();
  const serial = (task) => {
    const result = queue.then(task);
    queue = result.catch(() => {});
    return result;
  };
  const announce = (message) => {
    const status = root?.querySelector?.('.convo-status');
    if (status) status.textContent = message;
  };
  const clearView = (message) => {
    active = null;
    pendingCards.clear();
    chat.loadHistory([]);
    announce(message);
  };

  async function continueFrom(id) {
    const pending = new Map(pendingCards);
    clearView('');
    pendingCards.clear();
    for (const [messageId, cards] of pending) pendingCards.set(messageId, cards);
    active = await store.newConversation(id);
    restoringContinuation = true;
    return active;
  }

  function startNew(options = {}) {
    return serial(async () => {
      if (options.continued_from) { await continueFrom(options.continued_from); announce(t('ui.history.full', FULL_TEXT)); return active; }
      clearView('Yeni sohbet başladı.');
      return null;
    });
  }

  function bindFullSubmit(form, input) {
    if (!form?.addEventListener || !input || typeof input.value !== 'string') throw new TypeError('Chat form and input are required');
    if (boundForms.has(form)) return false;
    boundForms.add(form);
    let preparing = false, resubmitting = false;
    form.addEventListener('submit', async (event) => {
      if (resubmitting || !input.value.trim()) return;
      event.preventDefault();
      event.stopImmediatePropagation?.();
      if (preparing) return;
      preparing = true;
      const submitter = event.submitter;
      try {
        await queue;
        if (active?.full) await startNew({ continued_from: active.id });
        resubmitting = true;
        if (typeof form.requestSubmit === 'function') {
          if (submitter) form.requestSubmit(submitter);
          else form.requestSubmit();
        } else form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      } catch { announce('Yeni sohbet açılamadı. Lütfen yeniden deneyin.'); }
      finally { resubmitting = false; preparing = false; }
    }, true);
    return true;
  }

  function open(id) {
    return serial(async () => {
      const record = await store.load(id);
      if (!record) { clearView('Sohbet bulunamadı. Yeni sohbet başladı.'); return null; }
      active = record;
      pendingCards.clear();
      chat.loadHistory(record.turns);
      return record;
    });
  }

  function ensureActive() {
    return serial(async () => {
      if (!active) active = await store.newConversation();
      return active;
    });
  }

  function keepTurn(turn) {
    return serial(async () => {
      if (!active) active = await store.newConversation();
      let continued = false;
      if (active.full) { await continueFrom(active.id); continued = true; }
      let saved = await store.saveTurn(active.id, turn);
      if (!saved) {
        const old = await store.load(active.id);
        if (old?.full) { await continueFrom(active.id); continued = true; }
        else active = await store.newConversation();
        saved = await store.saveTurn(active.id, turn);
        if (!saved) throw new Error('Message could not be saved on this device');
        if (!continued) { chat.loadHistory(saved.turns); announce(RECOVERED_TEXT); }
      }
      active = saved;
      if (turn.role === 'assistant' && turn.message_id && pendingCards.has(turn.message_id)) {
        const cards = pendingCards.get(turn.message_id);
        pendingCards.delete(turn.message_id);
        for (const card of cards) active = await store.appendCardToTurn(active.id, turn.message_id, card) || active;
      }
      if (continued || restoringContinuation) chat.loadHistory(active.turns);
      if (turn.role === 'assistant') restoringContinuation = false;
      if (continued) announce(t('ui.history.full', FULL_TEXT));
      return saved;
    });
  }

  function addCard(messageId, card) {
    return serial(async () => {
      if (!messageId || !card) return null;
      if (active) {
        const saved = await store.appendCardToTurn(active.id, messageId, card);
        if (saved) { active = saved; return saved; }
      }
      if (!pendingCards.has(messageId) && pendingCards.size >= 20) pendingCards.delete(pendingCards.keys().next().value);
      pendingCards.set(messageId, [...(pendingCards.get(messageId) || []), card].slice(-6));
      return null;
    });
  }

  function onDeleted(id) {
    const wasActive = active?.id === id;
    return serial(() => {
      if (wasActive || active?.id === id) clearView(DELETED_TEXT);
    });
  }

  function deleteConversation(id) {
    return serial(async () => {
      const removed = await store.removeWithScoped(id);
      if (removed && active?.id === id) clearView(DELETED_TEXT);
      return removed;
    });
  }

  function clearConversations() {
    return serial(async () => {
      const cleared = await store.clearAll();
      if (cleared) clearView(CLEARED_TEXT);
      return cleared;
    });
  }

  function onClearedAll() {
    return serial(() => clearView(CLEARED_TEXT));
  }

  function refreshActive() {
    return serial(async () => {
      if (!active) return null;
      const record = await store.load(active.id);
      if (!record) { clearView('Sohbet bulunamadı. Yeni sohbet başladı.'); return null; }
      active = record;
      return record;
    });
  }

  return {
    activeId: () => active?.id || null, activeRecord: () => active,
    startNew, bindFullSubmit, open, ensureActive, keepTurn, addCard, onDeleted, onClearedAll,
    deleteConversation, clearConversations, refreshActive,
  };
}

export { mountConversationSession, DELETED_TEXT, CLEARED_TEXT, RECOVERED_TEXT, FULL_TEXT };
