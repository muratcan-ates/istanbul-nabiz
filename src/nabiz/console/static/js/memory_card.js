/* A memory suggestion is a request for consent, never a saved preference by itself. */
import { currentLang, t } from './i18n_text.js';
import { INTERESTS, NEED_KEYS } from './memory_store.js';
const COPY = {
  title: 'Hatırlayayım mı?', choose: 'Hatırlamamı istediğiniz satırları seçin.',
  here: 'Yalnız bu sohbette', always: 'Sonraki sohbetlerde de hatırla',
  remember: 'Hatırla', no: 'Hayır', expired: 'Bu öneri artık geçerli değil.',
  cardSaved: 'Seçtiğiniz bilgiler Hafızam bölümüne eklendi.', cardFailed: 'Kaydedilemedi. Yeniden deneyin.',
  change: 'Düzelt', healthAdd: 'Sağlık beyanı ekle', healthHint: 'Sağlık beyanı Hafızam bölümünde ayrı onayla eklenir.',
};
const tx = (key) => t(`ui.memory.${key}`, COPY[key]);
const INTEREST_WORDS = [
  ['culture', /kültür|sanat/u, 'Kültür ve sanat'], ['museum', /müze/u, 'Müze'], ['theatre', /tiyatro/u, 'Tiyatro'],
  ['concert', /konser/u, 'Konser'], ['cinema', /sinema/u, 'Sinema'], ['library', /kütüphane/u, 'Kütüphane'],
  ['sport', /spor/u, 'Spor'], ['nature', /doğa|orman|park/u, 'Doğa'], ['children', /çocuk/u, 'Çocuk etkinlikleri'], ['course', /kurs|atölye/u, 'Kurs'],
];
const NEED_WORDS = [
  ['slow_walk', /uzun\s+yürü|az\s+yürü|yavaş\s+yürü/u, 'Yavaş yürüyorum'], ['step_free', /merdivensiz|asansör\s+şart|tekerlekli\s+sandalye/u, 'Adımsız erişim'],
  ['stroller', /bebek\s+arabası|puset/u, 'Bebek arabası'],
];
const FIRST_PERSON = /seviyorum|ilgileniyorum|istemiyorum|yürüyemiyorum|zorlanıyorum|kullanıyorum/u;
const HEALTH_WORDS = /kalp|(?:^|[^\p{L}])diz(?:im|imi|imde|imden|ler|lerim)?(?!\p{L})|ameliyat|hastalık|rahatsızlık|ilaç|teşhis|tanı|tedavi|kanser|hamile|gebelik|sağlık\s+beyan/u;
const HEALTH_REQUEST = /hatırla|hafız|kaydet|(?:^|[^\p{L}])ekle(?:r|yin)?(?!\p{L})/u; // whole-word: "bekleme" is not a request
const MEMORY_REPEAT_THRESHOLD = 2;
const SENSITIVE_MASK = '[hassas bilgi saklanmadı]';
const LEGACY_NEEDS = new Map([['Adımsız erişim (asansör, rampa)', 'step_free'],
  ['Bebek arabası', 'stroller'], ['Yavaş yürüyüş', 'slow_walk']]);
function itemType(item) {
  const type = item?.kind || item?.type;
  if (['interest', 'need', 'place', 'health'].includes(type)) return type;
  return NEED_KEYS.has(item?.key) ? 'need' : INTERESTS.includes(item?.key) ? 'interest' : null;
}
function cardItems(card) {
  const body = card?.body || {}, source = Array.isArray(body.items) ? body.items : body.key ? [body] : [];
  return source.map((item) => ({ type: itemType(item), key: item?.key,
    label: typeof item?.label === 'string' ? item.label.slice(0, 160) : '' }))
    .filter((item) => item.type && item.key && item.label).slice(0, 6);
}
function element(doc, tag, className = '', value = '') {
  const node = doc.createElement(tag);
  if (className) node.className = className; if (value) node.textContent = value; return node;
}
function renderMemoryCard(card, ctx = {}) {
  const doc = ctx.document || globalThis.document;
  const root = element(doc, 'article', 'memory-card');
  root.dataset.cardId = String(card.id || ''); root.dataset.messageId = String(card.message_id || '');
  root.dataset.conversationId = String(card.conversation_id || ''); root.lang = currentLang();
  const health = card.body?.kind === 'health' || card.sensitive === true;
  root.dataset.memoryHealth = String(health);
  root.append(element(doc, 'h3', 'memory-card-title', health ? tx('healthAdd') : card.title || tx('title')));
  const items = cardItems(card);
  const unavailable = Boolean(ctx.restored || ctx.forgotten || card.status === 'done'
    || (health && !card.actions?.some((action) => (action.id || action) === 'change'))
    || items.some((item) => ctx.isForgotten?.(item.type, item.key)));
  if (health && !unavailable) {
    root.append(element(doc, 'p', 'memory-card-hint', tx('healthHint')));
    const actions = element(doc, 'div', 'memory-card-actions'), change = element(doc, 'button', 'btn', tx('change'));
    change.type = 'button'; change.dataset.cardAction = 'change'; actions.append(change); root.append(actions);
    change.addEventListener('click', (event) => { emitAction(doc, root, 'change'); event.stopPropagation?.(); });
    return root;
  }
  if (!items.length || unavailable) {
    root.append(element(doc, 'p', 'memory-card-status', tx('expired'))); return root;
  }
  const choices = element(doc, 'div', 'memory-card-choices');
  items.forEach((item) => {
    const label = element(doc, 'label', 'memory-card-choice'); const input = element(doc, 'input');
    input.type = 'checkbox'; input.checked = false; input.dataset.type = item.type;
    input.dataset.key = item.key; input.dataset.label = item.label;
    label.append(input, element(doc, 'span', '', item.label)); choices.append(label);
  });
  const scope = element(doc, 'fieldset', 'memory-card-scope');
  scope.append(element(doc, 'legend', '', t('ui.memory.scope', 'Hatırlama süresi')));
  for (const [value, key] of [['conversation', 'here'], ['profile', 'always']]) {
    const label = element(doc, 'label', 'memory-card-choice'); const input = element(doc, 'input');
    input.type = 'radio'; input.name = `memory-scope-${card.id}`; input.value = value; input.checked = value === 'conversation';
    label.append(input, element(doc, 'span', '', tx(key))); scope.append(label);
  }
  const hint = element(doc, 'p', 'memory-card-hint', tx('choose')); hint.setAttribute('role', 'status');
  const actions = element(doc, 'div', 'memory-card-actions');
  const remember = element(doc, 'button', 'btn', tx('remember'));
  remember.type = 'button'; remember.dataset.cardAction = 'remember_here'; remember.setAttribute('aria-disabled', 'true');
  const no = element(doc, 'button', 'btn btn-quiet', tx('no'));
  no.type = 'button'; no.dataset.memoryDismiss = 'true';
  const change = element(doc, 'button', 'btn btn-quiet', tx('change'));
  change.type = 'button'; change.dataset.cardAction = 'change';
  actions.append(remember, change, no);
  root.append(choices, scope, hint, actions);
  root.addEventListener('change', () => {
    const selected = [...choices.querySelectorAll('input[type="checkbox"]')].some((input) => input.checked);
    remember.setAttribute('aria-disabled', String(!selected));
    remember.dataset.cardAction = scope.querySelector('input[value="profile"]').checked ? 'remember_always' : 'remember_here';
    hint.hidden = selected;
  });
  root.addEventListener('click', (event) => {
    if (event.target === remember && remember.getAttribute('aria-disabled') === 'true') {
      event.preventDefault(); event.stopPropagation?.(); hint.hidden = false;
    } else if (event.target === remember) {
      // The card is the consent step: the action event leaves only after "Hatırla", with consented_at.
      emitAction(doc, root, remember.dataset.cardAction); event.stopPropagation?.();
    }
    if (event.target === change) { emitAction(doc, root, 'change'); event.stopPropagation?.(); }
    if (event.target === no) {
      actions.remove(); choices.remove(); scope.remove(); hint.remove();
      root.append(element(doc, 'p', 'memory-card-status', tx('expired')));
    }
  });
  return root;
}
function emitAction(doc, root, action) {
  const Event = doc.defaultView?.CustomEvent || globalThis.CustomEvent;
  doc.dispatchEvent(new Event('nabiz:card-action', { detail: { card_id: root.dataset.cardId, type: 'memory',
    action, kind: action === 'change' ? 'view' : 'device', requires_consent: action !== 'change',
    message_id: root.dataset.messageId || null, conversation_id: root.dataset.conversationId || null,
    operation_id: null, consented_at: action === 'change' ? null : new Date().toISOString() } }));
}
async function suggestMemoryItems(question, store, { conversationId = null, exclude = [] } = {}) {
  const text = String(question || '').toLocaleLowerCase('tr-TR');
  if (!FIRST_PERSON.test(text) || HEALTH_WORDS.test(text)) return [];
  const [profile, scoped] = await Promise.all([store.list({ scope: 'profile' }),
    conversationId ? store.list({ scope: 'conversation', conversationId }) : []]);
  const existing = new Set([...profile, ...scoped, ...exclude].map((item) => `${item.type}:${item.key}`));
  const possible = [
    ...NEED_WORDS.filter(([, pattern]) => pattern.test(text)).map(([key, , label]) => ({ type: 'need', key, label })),
    ...INTEREST_WORDS.filter(([, pattern]) => pattern.test(text)).map(([key, , label]) => ({ type: 'interest', key, label }))];
  return possible.filter((item) => !existing.has(`${item.type}:${item.key}`)
    && !store.isForgotten(item.type, item.key)).slice(0, 6);
}
function makeCard(items, messageId, conversationId) {
  const id = globalThis.crypto?.randomUUID?.() || `memory-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const health = items === null;
  return { v: 1, id, conversation_id: conversationId || null, message_id: String(messageId || ''),
    type: 'memory', status: 'awaiting_confirmation', title: health ? tx('healthAdd') : tx('title'),
    body: health ? { key: null, label: tx('healthAdd'), kind: 'health', scope_options: ['conversation', 'profile'], items: null }
      : { key: null, label: items.map((item) => item.label).join(', '), kind: items[0].type,
        scope_options: ['conversation', 'profile'], items: items.map((item) => ({ key: item.key, label: item.label, kind: item.type })) },
    sources: [], source_time: '', linked: { event_id: null, report_code: null, operation_id: null }, linked_id: null, sensitive: health,
    actions: (health ? [['change', 'change']] : [['remember_here', 'here'], ['remember_always', 'always'],
      ['change', 'change']]).map(([action, label]) => ({ id: action, label: tx(label).slice(0, 40),
      kind: action === 'change' ? 'view' : 'device', requires_consent: action !== 'change', operation_id: null })) };
}
function mountMemorySuggestions({ store, session, onChanged = () => {}, registry = null,
  legacyLog = null, chatForm = null, chatInput = null, onLocalTurn = null, doc = globalThis.document }) {
  const ready = registry ? Promise.resolve(registry) : import('./chat_cards.js').then((module) => module).catch(() => null);
  const renderWithForgotten = (card, ctx) => renderMemoryCard(card, { ...ctx, isForgotten: store.isForgotten });
  const seen = new Set(), declarations = new Map(), offered = new Set();
  const completed = new Set(), visibleCards = new Map();
  let countedConversation = null;
  const active = async () => {
    let id = session.activeId();
    if (!id) id = (await session.ensureActive?.())?.id || session.activeId();
    if (id !== countedConversation) {
      countedConversation = id; seen.clear(); declarations.clear(); offered.clear();
    }
    return id;
  };
  const show = async (host, card, cards, existing = null) => {
    visibleCards.set(card.id, card); await session.addCard?.(card.message_id, card);
    if (existing) existing.replaceWith(renderWithForgotten(card, { document: doc }));
    else if (cards?.appendCard) cards.appendCard(host, card, { isForgotten: store.isForgotten });
    else host.append(renderWithForgotten(card, { document: doc }));
  };
  const scanLegacy = async () => {
    for (const text of legacyLog?.querySelectorAll('.chat-text') || []) { if (text.closest?.('.is-assistant')) continue; // never hide an answer
      const value = text.textContent;
      if (HEALTH_WORDS.test(value.toLocaleLowerCase('tr-TR')) && value !== SENSITIVE_MASK) text.textContent = SENSITIVE_MASK;
    }
    for (const box of legacyLog?.querySelectorAll('.chat-suggest') || []) {
      if (box.dataset.memoryHandled) continue; box.dataset.memoryHandled = 'true';
      const label = box.querySelector('b')?.textContent?.trim(), key = LEGACY_NEEDS.get(label);
      if (!key || store.isForgotten('need', key)) { box.remove(); continue; }
      const id = await active(), saved = await store.list({});
      if (saved.some((item) => item.type === 'need' && item.key === key)) { box.remove(); continue; }
      const shell = box.closest('.is-assistant');
      const messageId = shell?.querySelector('.feedback-slot')?.dataset.turnId
        || `legacy-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      const card = makeCard([{ type: 'need', key, label }], messageId, id);
      visibleCards.set(card.id, card); box.replaceWith(renderWithForgotten(card, { document: doc }));
      if (session.activeRecord?.()?.turns?.some((turn) => turn.message_id === messageId)) await session.addCard?.(messageId, card);
    }
  };
  chatForm?.addEventListener('submit', (event) => {
    const question = String(chatInput?.value || '').toLocaleLowerCase('tr-TR');
    if (!HEALTH_WORDS.test(question) || !HEALTH_REQUEST.test(question) || !legacyLog) return;
    event.preventDefault(); event.stopImmediatePropagation?.(); event.stopPropagation?.(); chatInput.value = '';
    const user = element(doc, 'li', 'chat-msg is-user'), answer = element(doc, 'li', 'chat-msg is-assistant'),
      host = element(doc, 'div', 'chat-final');
    user.append(element(doc, 'p', 'chat-who', 'Siz'), element(doc, 'p', 'chat-text', SENSITIVE_MASK));
    answer.append(element(doc, 'p', 'chat-who', 'Asistan'), host); legacyLog.append(user, answer);
    const messageId = `health-${globalThis.crypto?.randomUUID?.() || Date.now()}`; void (async () => {
      const turn = onLocalTurn || session.keepTurn;
      try {
        const id = await active();
        await turn?.({ role: 'user', content: SENSITIVE_MASK, sensitive: true });
        await turn?.({ role: 'assistant', content: tx('healthHint'), message_id: messageId });
        await show(host, makeCard(null, messageId, id), await ready);
      } catch { host.append(renderWithForgotten(makeCard(null, messageId, session.activeId()), { document: doc })); }
    })();
  }, true);
  void ready.then((cards) => cards?.registerCardType?.('memory', renderWithForgotten));
  if (legacyLog) {
    const Observer = doc.defaultView?.MutationObserver || globalThis.MutationObserver;
    if (Observer) new Observer(() => { void scanLegacy().catch(() => {}); }).observe(legacyLog, { childList: true, subtree: true });
    void scanLegacy().catch(() => {});
  }
  doc.addEventListener('nabiz:chat-final', async (event) => {
    const { question, final, host, messageId } = event.detail || {};
    if (!host || !question || !messageId || final?.refused || final?.emergency || final?.mode === 'redirect') return;
    const conversationId = await active();
    if (!conversationId || seen.has(messageId)) return; seen.add(messageId);
    const text = String(question).toLocaleLowerCase('tr-TR');
    if (HEALTH_WORDS.test(text) && HEALTH_REQUEST.test(text)) {
      await show(host, makeCard(null, messageId, conversationId), await ready); return;
    }
    const server = final?.memory_suggestion;
    const serverItem = server?.key ? { type: itemType(server), key: server.key,
      label: String(server.label || server.key).slice(0, 160) } : null;
    const candidates = await suggestMemoryItems(question, store, { conversationId });
    const items = candidates.filter((item) => {
      const key = `${item.type}:${item.key}`, count = (declarations.get(key) || 0) + 1;
      declarations.set(key, count);
      if (count !== MEMORY_REPEAT_THRESHOLD || offered.has(key)) return false;
      offered.add(key); return true;
    });
    if (!items.length) return;
    await new Promise((resolve) => setTimeout(resolve, 0));
    const existing = [...host.querySelectorAll('.memory-card')].find((node) => node.dataset.messageId === String(messageId));
    try {
      const cards = await ready; if (serverItem && !existing && cards?.appendCard) return;
      const saved = serverItem ? await store.list({}) : [];
      const fresh = serverItem && !store.isForgotten(serverItem.type, serverItem.key)
        && !saved.some((item) => item.type === serverItem.type && item.key === serverItem.key);
      const merged = fresh && existing
        ? [serverItem, ...items.filter((item) => item.key !== serverItem.key)] : items;
      const card = makeCard(merged, messageId, conversationId);
      if (existing) card.id = existing.dataset.cardId;
      await show(host, card, cards, existing);
    } catch { /* No suggestion is safer than a partial consent card. */ }
  });
  doc.addEventListener('nabiz:card-action', async (event) => {
    const { card_id: cardId, type, action, conversation_id: conversationId } = event.detail || {};
    if (type !== 'memory' || !cardId) return;
    const card = [...doc.querySelectorAll('.memory-card')].find((node) => node.dataset.cardId === cardId);
    if (action === 'change' && card) {
      const Event = doc.defaultView?.CustomEvent || globalThis.CustomEvent, name = card.dataset.memoryHealth === 'true' ? 'nabiz:memory-health-form' : 'nabiz:reveal';
      doc.dispatchEvent(new Event(name, { detail: name === 'nabiz:memory-health-form'
        ? { card_id: cardId } : { id: 'hafizam' } })); return;
    }
    if (!['remember_here', 'remember_always'].includes(action) || completed.has(cardId)) return;
    if (!card || !card.querySelector('.memory-card-actions')) return;
    const boundId = conversationId || card.dataset.conversationId;
    if (boundId && session.activeId() && boundId !== session.activeId()) {
      for (const selector of ['.memory-card-actions', '.memory-card-choices', '.memory-card-scope', '.memory-card-hint'])
        card.querySelector(selector)?.remove();
      card.append(element(doc, 'p', 'memory-card-status', tx('expired')));
      completed.add(cardId);
      return;
    }
    const selected = [...card.querySelectorAll('input[type="checkbox"]:checked')];
    if (!selected.length) return;
    const scope = action === 'remember_always' ? 'profile' : 'conversation';
    completed.add(cardId);
    try {
      if (scope === 'conversation' && !session.activeId()) await session.ensureActive();
      const activeId = session.activeId();
      if (scope === 'conversation' && !activeId) throw new Error('No active conversation');
      const [profile, scoped] = await Promise.all([
        store.list({ scope: 'profile' }),
        activeId ? store.list({ scope: 'conversation', conversationId: activeId }) : [],
      ]);
      const existing = new Set([...profile, ...scoped].map((item) => `${item.type}:${item.key}`));
      let storedCount = 0;
      for (const input of selected) {
        const identity = `${input.dataset.type}:${input.dataset.key}`;
        if (store.isForgotten(input.dataset.type, input.dataset.key) || existing.has(identity)) continue;
        const saved = await store.add({ type: input.dataset.type, key: input.dataset.key,
          label: input.dataset.label, scope, conversation_id: scope === 'conversation' ? activeId : null,
          source: 'chat_suggestion', sensitive: false, need_key: null,
          related_ids: scope === 'profile' && (conversationId || activeId) ? [conversationId || activeId] : [] });
        if (!saved) throw new Error('Memory was not saved');
        existing.add(identity); storedCount += 1;
      }
      await session.refreshActive?.(); await onChanged();
      const original = visibleCards.get(cardId) || session.activeRecord?.()?.turns
        ?.flatMap((turn) => turn.cards || []).find((entry) => entry.id === cardId);
      if (original) await session.addCard?.(original.message_id || event.detail.message_id,
        { ...original, status: storedCount ? 'done' : 'unavailable', actions: [] });
      for (const selector of ['.memory-card-actions', '.memory-card-choices', '.memory-card-scope', '.memory-card-hint'])
        card.querySelector(selector)?.remove();
      card.append(element(doc, 'p', 'memory-card-status', tx(storedCount ? 'cardSaved' : 'expired')));
    } catch {
      completed.delete(cardId);
      card.querySelector('.memory-card-hint').textContent = tx('cardFailed');
      card.querySelector('.memory-card-hint').hidden = false;
    }
  });
  return { ready, scanLegacy };
}
const mountMemoryCards = mountMemorySuggestions;
export { renderMemoryCard, suggestMemoryItems, mountMemorySuggestions, mountMemoryCards };
