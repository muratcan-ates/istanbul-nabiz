/* A memory suggestion is a request for consent, never a saved preference by itself. */
import { currentLang, t } from './i18n_text.js';
import { INTERESTS, NEED_KEYS } from './memory_store.js';

const COPY = {
  title: 'Hatırlayayım mı?', choose: 'Hatırlamamı istediğiniz satırları seçin.',
  here: 'Yalnız bu sohbette', always: 'Sonraki sohbetlerde de hatırla',
  remember: 'Hatırla', no: 'Hayır', expired: 'Bu öneri artık geçerli değil.',
  cardSaved: 'Seçtiğiniz bilgiler Hafızam bölümüne eklendi.', cardFailed: 'Kaydedilemedi. Yeniden deneyin.',
};
const tx = (key) => t(`ui.memory.${key}`, COPY[key]);
const INTEREST_WORDS = [
  ['culture', /kültür|sanat/u, 'Kültür ve sanat'],
  ['museum', /müze/u, 'Müze'], ['theatre', /tiyatro/u, 'Tiyatro'],
  ['concert', /konser/u, 'Konser'], ['cinema', /sinema/u, 'Sinema'],
  ['library', /kütüphane/u, 'Kütüphane'], ['sport', /spor/u, 'Spor'],
  ['nature', /doğa|orman|park/u, 'Doğa'], ['children', /çocuk/u, 'Çocuk etkinlikleri'],
  ['course', /kurs|atölye/u, 'Kurs'],
];
const NEED_WORDS = [
  ['slow_walk', /uzun\s+yürü|az\s+yürü|yavaş\s+yürü/u, 'Yavaş yürüyorum'],
  ['step_free', /merdivensiz|asansör\s+şart|tekerlekli\s+sandalye/u, 'Adımsız erişim'],
  ['stroller', /bebek\s+arabası|puset/u, 'Bebek arabası'],
];
const FIRST_PERSON = /seviyorum|ilgileniyorum|istemiyorum|yürüyemiyorum|zorlanıyorum|kullanıyorum/u;
const HEALTH_WORDS = /kalp|diz|ameliyat|hastalık|rahatsızlık|ilaç|teşhis|tanı|tedavi|kanser|hamile|gebelik/u;

function itemType(item) {
  if (item?.type === 'interest' || item?.type === 'need') return item.type;
  return NEED_KEYS.has(item?.key) ? 'need' : INTERESTS.includes(item?.key) ? 'interest' : null;
}

function cardItems(card) {
  const body = card?.body || {};
  const source = Array.isArray(body.items) ? body.items : body.key ? [body] : [];
  return source.map((item) => ({ type: itemType(item), key: item?.key,
    label: typeof item?.label === 'string' ? item.label.slice(0, 160) : '' }))
    .filter((item) => item.type && item.key && item.label).slice(0, 6);
}

function element(doc, tag, className = '', value = '') {
  const node = doc.createElement(tag);
  if (className) node.className = className;
  if (value) node.textContent = value;
  return node;
}

function renderMemoryCard(card, ctx = {}) {
  const doc = ctx.document || globalThis.document;
  const root = element(doc, 'article', 'memory-card');
  root.dataset.cardId = String(card.id || '');
  root.dataset.messageId = String(card.message_id || '');
  root.dataset.conversationId = String(card.conversation_id || '');
  root.lang = currentLang();
  root.append(element(doc, 'h3', 'memory-card-title', card.title || tx('title')));
  const items = cardItems(card);
  const unavailable = Boolean(ctx.restored || ctx.forgotten || card.status === 'done'
    || items.some((item) => ctx.isForgotten?.(item.type, item.key)));
  if (!items.length || unavailable) {
    root.append(element(doc, 'p', 'memory-card-status', tx('expired')));
    return root;
  }
  const choices = element(doc, 'div', 'memory-card-choices');
  items.forEach((item) => {
    const label = element(doc, 'label', 'memory-card-choice');
    const input = element(doc, 'input');
    input.type = 'checkbox'; input.checked = false;
    input.dataset.type = item.type; input.dataset.key = item.key; input.dataset.label = item.label;
    label.append(input, element(doc, 'span', '', item.label)); choices.append(label);
  });
  const scope = element(doc, 'fieldset', 'memory-card-scope');
  scope.append(element(doc, 'legend', '', t('ui.memory.scope', 'Hatırlama süresi')));
  for (const [value, key] of [['conversation', 'here'], ['profile', 'always']]) {
    const label = element(doc, 'label', 'memory-card-choice');
    const input = element(doc, 'input');
    input.type = 'radio'; input.name = `memory-scope-${card.id}`; input.value = value;
    input.checked = value === 'conversation';
    label.append(input, element(doc, 'span', '', tx(key))); scope.append(label);
  }
  const hint = element(doc, 'p', 'memory-card-hint', tx('choose'));
  hint.setAttribute('role', 'status');
  const actions = element(doc, 'div', 'memory-card-actions');
  const remember = element(doc, 'button', 'btn', tx('remember'));
  remember.type = 'button'; remember.dataset.cardAction = 'remember_here';
  remember.setAttribute('aria-disabled', 'true');
  const no = element(doc, 'button', 'btn btn-quiet', tx('no'));
  no.type = 'button'; no.dataset.memoryDismiss = 'true';
  actions.append(remember, no);
  root.append(choices, scope, hint, actions);
  root.addEventListener('change', () => {
    const selected = [...choices.querySelectorAll('input[type="checkbox"]')].some((input) => input.checked);
    remember.setAttribute('aria-disabled', String(!selected));
    remember.dataset.cardAction = scope.querySelector('input[value="profile"]').checked
      ? 'remember_always' : 'remember_here';
    hint.hidden = selected;
  });
  root.addEventListener('click', (event) => {
    if (event.target === remember && remember.getAttribute('aria-disabled') === 'true') {
      event.preventDefault(); event.stopPropagation?.(); hint.hidden = false;
    } else if (event.target === remember) {
      // The card is the consent step: the action event leaves only after "Hatırla", with consented_at.
      const Event = doc.defaultView?.CustomEvent || globalThis.CustomEvent;
      doc.dispatchEvent(new Event('nabiz:card-action', { detail: { card_id: root.dataset.cardId, type: 'memory',
        action: remember.dataset.cardAction, message_id: root.dataset.messageId || null,
        conversation_id: root.dataset.conversationId || null, operation_id: null,
        consented_at: new Date().toISOString() } }));
    }
    if (event.target === no) {
      actions.remove(); choices.remove(); scope.remove(); hint.remove();
      root.append(element(doc, 'p', 'memory-card-status', tx('expired')));
    }
  });
  return root;
}

async function suggestMemoryItems(question, store, { conversationId = null, exclude = [] } = {}) {
  const text = String(question || '').toLocaleLowerCase('tr-TR');
  if (!FIRST_PERSON.test(text) || HEALTH_WORDS.test(text)) return [];
  const [profile, scoped] = await Promise.all([
    store.list({ scope: 'profile' }),
    conversationId ? store.list({ scope: 'conversation', conversationId }) : [],
  ]);
  const existing = new Set([...profile, ...scoped, ...exclude].map((item) => `${item.type}:${item.key}`));
  const possible = [
    ...NEED_WORDS.filter(([, pattern]) => pattern.test(text)).map(([key, , label]) => ({ type: 'need', key, label })),
    ...INTEREST_WORDS.filter(([, pattern]) => pattern.test(text)).map(([key, , label]) => ({ type: 'interest', key, label })),
  ];
  return possible.filter((item) => !existing.has(`${item.type}:${item.key}`)
    && !store.isForgotten(item.type, item.key)).slice(0, 6);
}

function makeCard(items, messageId, conversationId) {
  const id = globalThis.crypto?.randomUUID?.() || `memory-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  return { v: 1, id, conversation_id: conversationId || null, message_id: String(messageId || ''),
    type: 'memory', status: 'awaiting_confirmation', title: tx('title'), body: { items }, sources: [],
    source_time: '', linked_id: null, sensitive: false,
    actions: [['remember_here', 'here'], ['remember_always', 'always']].map(([action, label]) => ({ id: action,
      label: tx(label).slice(0, 40), kind: 'device', requires_consent: true, operation_id: null })) };
}

function mountMemorySuggestions({ store, session, onChanged = () => {}, registry = null, doc = globalThis.document }) {
  const ready = registry ? Promise.resolve(registry) : import('./chat_cards.js').then((module) => module).catch(() => null);
  const renderWithForgotten = (card, ctx) => renderMemoryCard(card, { ...ctx, isForgotten: store.isForgotten });
  void ready.then((cards) => cards?.registerCardType?.('memory', renderWithForgotten));
  const seen = new Set();
  const completed = new Set();
  const visibleCards = new Map();
  doc.addEventListener('nabiz:chat-final', async (event) => {
    const { question, final, host, messageId } = event.detail || {};
    if (!host || !question || !messageId || final?.refused || final?.emergency || final?.mode === 'redirect'
      || seen.has(messageId)) return;
    seen.add(messageId);
    const server = final?.memory_suggestion;
    const serverItem = server?.key ? { type: itemType(server), key: server.key,
      label: String(server.label || server.key).slice(0, 160) } : null;
    await new Promise((resolve) => setTimeout(resolve, 0));
    const existing = [...host.querySelectorAll('.memory-card')]
      .find((node) => node.dataset.messageId === String(messageId));
    if (serverItem && !existing) return;
    const excluded = serverItem ? [serverItem] : [];
    try {
      const items = await suggestMemoryItems(question, store,
        { conversationId: session.activeId(), exclude: excluded });
      if (!items.length) return;
      const cards = await ready;
      if (!cards?.appendCard) return;
      const card = makeCard(serverItem ? [serverItem, ...items] : items, messageId, session.activeId());
      if (existing) card.id = existing.dataset.cardId;
      await session.addCard?.(messageId, card);
      visibleCards.set(card.id, card);
      if (existing) existing.replaceWith(renderMemoryCard(card, { document: doc, isForgotten: store.isForgotten }));
      else cards.appendCard(host, card, { isForgotten: store.isForgotten });
    } catch { /* No suggestion is safer than a partial consent card. */ }
  });
  doc.addEventListener('nabiz:card-action', async (event) => {
    const { card_id: cardId, type, action, conversation_id: conversationId } = event.detail || {};
    if (type !== 'memory' || !['remember_here', 'remember_always'].includes(action)
      || !cardId || completed.has(cardId)) return;
    const card = [...doc.querySelectorAll('.memory-card')].find((node) => node.dataset.cardId === cardId);
    if (!card || !card.querySelector('.memory-card-actions')) return;
    const boundId = conversationId || card.dataset.conversationId;
    if (boundId && session.activeId() && boundId !== session.activeId()) {
      for (const selector of ['.memory-card-actions', '.memory-card-choices', '.memory-card-scope', '.memory-card-hint']) {
        card.querySelector(selector)?.remove();
      }
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
      card.querySelector('.memory-card-actions')?.remove();
      card.querySelector('.memory-card-choices')?.remove();
      card.querySelector('.memory-card-scope')?.remove();
      card.querySelector('.memory-card-hint')?.remove();
      card.append(element(doc, 'p', 'memory-card-status', tx(storedCount ? 'cardSaved' : 'expired')));
    } catch {
      completed.delete(cardId);
      card.querySelector('.memory-card-hint').textContent = tx('cardFailed');
      card.querySelector('.memory-card-hint').hidden = false;
    }
  });
  return { ready };
}

const mountMemoryCards = mountMemorySuggestions;
export { renderMemoryCard, suggestMemoryItems, mountMemorySuggestions, mountMemoryCards };
