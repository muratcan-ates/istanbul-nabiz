/* Conversation history stays in this browser. IndexedDB is preferred, with progressively smaller
 * storage fallbacks for browsers that block persistent storage. */
import { HISTORY_TURNS } from './config.js';
const STORAGE_KEY = 'nabiz.conversations.v1', DATABASE_NAME = 'nabiz-conversations', STORE_NAME = 'conversations';
const DATABASE_VERSION = 1;
const RETENTION_DAYS = 30;
const MAX_CONTENT_LENGTH = 4000, MAX_TURNS = 80, MAX_CARD_TEXT = 600;
const REDACTED_TEXT = '[acil yönlendirme]';
const SENSITIVE_REDACTED_TEXT = '[hassas bilgi saklanmadı]';
const CARD_TYPES = new Set(['route', 'map', 'event', 'calendar_draft', 'photo_report', 'status', 'info', 'memory']);
const CARD_STATUSES = new Set(['preparing', 'needs_input', 'ready', 'awaiting_confirmation', 'done', 'unavailable', 'error']);
const CARD_ACTION_KIND = Object.freeze({ use_location: 'device', type_place: 'view', expand_map: 'view', listen: 'view', remember_here: 'device', remember_always: 'device', change: 'view', forget: 'device', save_calendar: 'nabiz', export_ics: 'device', review_report: 'view', send: 'nabiz', open_official: 'external', add_outlook: 'external', confirm_resolved: 'nabiz', reopen: 'nabiz', cancel: 'nabiz', appeal: 'nabiz', share: 'external' });
const CARD_CONSENT = new Set(['use_location', 'remember_here', 'remember_always', 'save_calendar', 'send', 'add_outlook', 'confirm_resolved', 'reopen', 'cancel', 'appeal', 'share']);
const CARD_ACTION_ALIASES = Object.freeze({ add_calendar: 'save_calendar', download_ics: 'export_ics', open_map: 'expand_map', remember: 'remember_here' });
const EMERGENCY_TEXT = /acil|ambulans|can güvenliği|imdat/i;
const SENSITIVE_TEXT = /sağlık|hastalık|rahatsızlık|rahatsiz|ameliyat|kalp|kanser|ilaç|doktor|teşhis|tani|kan tahlil|gebelik|hamile|psikolog|terapi|hukuk|avukat|dava|ceza|borç|maaş|banka|kredi|şifre|kimlik|adres|telefon|e-?posta|\b\d{11}\b|\b\d{10,}\b/i;
let databasePromise, indexedDbUnavailable = false, storageMode = 'unknown', memoryRecords = [];
function timestamp(value) {
  const parsed = Date.parse(value || '');
  return Number.isFinite(parsed) ? parsed : 0;
}
function normaliseRecords(records) {
  return Array.isArray(records)
    ? records.filter((record) => record && typeof record.id === 'string' && Array.isArray(record.turns))
      .map((record) => {
        const turns = record.turns.filter((turn) => turn && (turn.role === 'user' || turn.role === 'assistant')
          && typeof turn.content === 'string').map((turn) => ({ ...turn,
          cards: Array.isArray(turn.cards) ? turn.cards.slice(0, 6)
            .map((card) => cleanCard(card, record.id, turn.message_id)).filter(Boolean) : [] }));
        const links = turns.reduce((all, turn) => withCardLinks(all, turn.cards),
          (Array.isArray(record.links) ? record.links : []).filter((link) => link && typeof link.kind === 'string' && typeof link.id === 'string'));
        return { ...record, schema: 2, title: typeof record.title === 'string' ? record.title : 'Yeni sohbet',
          turns, scoped: Array.isArray(record.scoped) ? record.scoped : [], links,
          full: record.full === true || turns.length >= MAX_TURNS,
          trimmed: Number.isInteger(record.trimmed) && record.trimmed >= 0 ? record.trimmed : 0 };
      })
    : [];
}
function openDatabase() {
  if (indexedDbUnavailable || typeof indexedDB === 'undefined') return Promise.reject(new Error('IndexedDB is unavailable'));
  if (!databasePromise) databasePromise = new Promise((resolve, reject) => {
    try {
      const request = indexedDB.open(DATABASE_NAME, DATABASE_VERSION);
      request.onupgradeneeded = () => {
        if (!request.result.objectStoreNames.contains(STORE_NAME)) request.result.createObjectStore(STORE_NAME, { keyPath: 'id' });
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error || new Error('IndexedDB could not open'));
      request.onblocked = () => reject(new Error('IndexedDB is blocked'));
    } catch (error) { reject(error); }
  });
  return databasePromise;
}
function mutateIndexedDb(mutator) {
  return openDatabase().then((database) => new Promise((resolve, reject) => {
    let value;
    let failure = null;
    const transaction = database.transaction(STORE_NAME, 'readwrite');
    const store = transaction.objectStore(STORE_NAME);
    const request = store.getAll();
    request.onsuccess = () => {
      try {
        const result = mutator(normaliseRecords(request.result));
        value = result.value;
        if (result.write) {
          store.clear();
          result.records.forEach((record) => store.put(record));
        }
      } catch (error) { failure = error; transaction.abort(); }
    };
    request.onerror = () => { failure = request.error || new Error('IndexedDB read failed'); };
    transaction.oncomplete = () => resolve(value);
    transaction.onerror = () => reject(failure || transaction.error || new Error('IndexedDB write failed'));
    transaction.onabort = () => reject(failure || transaction.error || new Error('IndexedDB transaction aborted'));
  }));
}
function localStorageObject() {
  try { return globalThis.localStorage || null; } catch { return null; }
}
function mutateLocalStorage(mutator) {
  const storage = localStorageObject();
  if (!storage) throw new Error('localStorage is unavailable');
  const raw = storage.getItem(STORAGE_KEY);
  let records = [];
  if (raw) { try { records = normaliseRecords(JSON.parse(raw)); } catch { records = []; } }
  const result = mutator(records);
  if (result.write) storage.setItem(STORAGE_KEY, JSON.stringify(result.records));
  return result.value;
}
async function withStorage(mutator) {
  if (!indexedDbUnavailable) {
    try {
      const value = await mutateIndexedDb(mutator);
      storageMode = 'indexedDB';
      return value;
    } catch { indexedDbUnavailable = true; databasePromise = null; }
  }
  try {
    const value = mutateLocalStorage(mutator);
    storageMode = 'localStorage';
    return value;
  } catch {
    const result = mutator(memoryRecords);
    memoryRecords = result.records;
    storageMode = 'memory';
    return result.value;
  }
}
function makeId() {
  try { if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID(); } catch { /* Use a local ID. */ }
  return `convo-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}
function bounded(value, depth = 0) {
  if (typeof value === 'string') return value.slice(0, MAX_CARD_TEXT);
  if (value == null || typeof value === 'boolean' || typeof value === 'number') return value;
  if (depth >= 3) return null;
  if (Array.isArray(value)) return value.slice(0, 20).map((item) => bounded(item, depth + 1));
  if (typeof value !== 'object') return null;
  return Object.fromEntries(Object.entries(value).slice(0, 20)
    .map(([key, item]) => [key.slice(0, 64), bounded(item, depth + 1)]));
}
function cleanAction(raw) {
  const given = typeof raw === 'string' ? raw : raw && typeof raw === 'object' ? String(raw.id || '') : '';
  const id = CARD_ACTION_ALIASES[given] || given;
  if (!Object.hasOwn(CARD_ACTION_KIND, id)) return null;
  const operationId = ['nabiz', 'external'].includes(CARD_ACTION_KIND[id]) && typeof raw?.operation_id === 'string'
    && raw.operation_id ? raw.operation_id.slice(0, 128) : null;
  return { id, label: String(raw?.label || '').slice(0, 40), kind: CARD_ACTION_KIND[id],
    requires_consent: CARD_CONSENT.has(id) || raw?.requires_consent === true, operation_id: operationId };
}
function cleanLinked(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const value = (key) => (typeof raw[key] === 'string' && raw[key] ? raw[key].slice(0, 128) : null);
  return { event_id: value('event_id'), report_code: value('report_code'), operation_id: value('operation_id') };
}
function cleanCard(raw, conversationId, messageId) {
  if (!raw || typeof raw !== 'object' || !CARD_TYPES.has(raw.type) || !CARD_STATUSES.has(raw.status)) return null;
  const sensitive = raw.sensitive === true, health = sensitive && raw.type === 'memory' && raw.body?.kind === 'health';
  const actions = (Array.isArray(raw.actions) ? raw.actions : []).map(cleanAction).filter(Boolean);
  const card = {
    v: 1, id: String(raw.id || '').slice(0, 128), conversation_id: conversationId,
    message_id: String(raw.message_id || messageId || '').slice(0, 128), type: raw.type, status: raw.status,
    title: sensitive ? health ? 'Sağlık beyanı ekle' : SENSITIVE_REDACTED_TEXT : String(raw.title || '').slice(0, 120),
    body: health ? { key: null, label: 'Sağlık beyanı ekle', kind: 'health', scope_options: ['conversation', 'profile'], items: null } : sensitive ? null : bounded(raw.body),
    sources: (sensitive ? [] : Array.isArray(raw.sources) ? raw.sources : []).slice(0, 6).map((source) => ({
      label: String(source?.label || '').slice(0, MAX_CARD_TEXT), url: typeof source?.url === 'string' && source.url.startsWith('https://') ? source.url.slice(0, 2048) : null,
      source_time: typeof source?.source_time === 'string' && timestamp(source.source_time) ? source.source_time.slice(0, 128) : null, freshness: String(source?.freshness || '').slice(0, 128),
    })),
    source_time: sensitive || typeof raw.source_time !== 'string' || !timestamp(raw.source_time) ? null : raw.source_time.slice(0, 128),
    linked_id: raw.linked_id == null ? null : String(raw.linked_id).slice(0, 128),
    actions: sensitive ? [] : actions.slice(0, 4),
    sensitive,
  };
  const linked = cleanLinked(raw.linked); if (linked) card.linked = linked;
  return card;
}
function cleanTurn(turn, now, conversationId) {
  const role = turn?.role === 'user' ? 'user' : turn?.role === 'assistant' ? 'assistant' : null;
  if (!role) return null;
  const content = String(turn.content ?? '');
  const detectionText = content.toLocaleLowerCase('tr-TR');
  const emergency = turn.emergency === true || turn.mode === 'redirect' || EMERGENCY_TEXT.test(detectionText);
  const sensitive = !emergency && (turn.sensitive === true || SENSITIVE_TEXT.test(detectionText));
  const saved = {
    role,
    content: (emergency ? REDACTED_TEXT : sensitive ? SENSITIVE_REDACTED_TEXT : content).slice(0, MAX_CONTENT_LENGTH),
    at: typeof turn.at === 'string' && Number.isFinite(Date.parse(turn.at)) ? turn.at : now,
  };
  if (typeof turn.mode === 'string') saved.mode = turn.mode.slice(0, 64);
  if (typeof turn.message_id === 'string') saved.message_id = turn.message_id.slice(0, 128);
  if (emergency || sensitive) saved.redacted = emergency ? 'emergency' : 'sensitive';
  if (Array.isArray(turn.cards)) saved.cards = turn.cards.slice(0, 6)
    .map((card) => cleanCard(card, conversationId, saved.message_id)).filter(Boolean);
  return saved;
}
function compactionNote(turnCount, keptTurns) {
  const count = Number(turnCount);
  const kept = Math.max(0, Math.floor(Number(keptTurns) || 0));
  if (!Number.isFinite(count) || count <= HISTORY_TURNS * 2) return '';
  return `Önceki mesajlar kısaltılarak gönderiliyor; yalnız son ${kept} soru hatırlanıyor.`;
}
function cardLinks(card) {
  const linked = card.linked;
  return [['event_id', 'calendar'], ['report_code', 'report'], ['operation_id', 'operation']]
    .flatMap(([key, kind]) => linked?.[key] ? [{ kind, id: linked[key] }] : []);
}
function withCardLinks(links, cards) {
  const next = [...links];
  for (const card of cards) for (const link of cardLinks(card)) {
    if (link && !next.some((item) => item.kind === link.kind && item.id === link.id)) next.push(link);
  }
  return next;
}
function expiresAt(record) {
  return timestamp(record?.updatedAt) ? new Date(timestamp(record.updatedAt) + RETENTION_DAYS * 86400000).toISOString() : null;
}
function linkedCounts(record) {
  const counts = { calendar: 0, report: 0, operation: 0, request: 0, follow: 0, total: 0 };
  for (const link of Array.isArray(record?.links) ? record.links : []) {
    if (Object.hasOwn(counts, link.kind) && link.kind !== 'total') { counts[link.kind] += 1; counts.total += 1; }
  }
  return counts;
}
async function saveTurn(id, turn) {
  const conversationId = String(id || '');
  const now = new Date().toISOString();
  const savedTurn = cleanTurn(turn, now, conversationId);
  if (!conversationId || !savedTurn) return null;
  return withStorage((records) => {
    const index = records.findIndex((record) => record.id === conversationId);
    if (index < 0) return { records, value: null, write: false };
    const previous = records[index];
    if (previous.full || previous.turns.length >= MAX_TURNS) return { records, value: null, write: false };
    const turns = [...previous.turns, savedTurn];
    const title = previous.title === 'Yeni sohbet' && savedTurn.role === 'user' && !savedTurn.redacted
      ? savedTurn.content.slice(0, 48).trimEnd() || 'Yeni sohbet'
      : previous.title;
    const links = withCardLinks(previous.links, savedTurn.cards || []);
    const updated = { ...previous, schema: 2, title, updatedAt: now, turns, links, full: turns.length >= MAX_TURNS };
    const next = records.map((item, position) => (position === index ? updated : item));
    return { records: next, value: updated, write: true };
  });
}
async function appendCardToTurn(id, messageId, card) {
  return withStorage((records) => {
    const index = records.findIndex((record) => record.id === String(id || ''));
    if (index < 0) return { records, value: null, write: false };
    const record = records[index];
    const turnIndex = record.turns.findIndex((turn) => turn.role === 'assistant' && turn.message_id === messageId);
    if (turnIndex < 0) return { records, value: null, write: false };
    const safe = cleanCard(card, record.id, messageId);
    if (!safe) return { records, value: null, write: false };
    const turns = [...record.turns];
    const existing = turns[turnIndex].cards || [];
    const cards = [...existing.filter((item) => item.id !== safe.id), safe].slice(-6);
    turns[turnIndex] = { ...turns[turnIndex], cards };
    const updated = { ...record, turns, updatedAt: new Date().toISOString(), links: withCardLinks(record.links, [safe]) };
    const next = records.map((item, position) => (position === index ? updated : item));
    return { records: next, value: updated, write: true };
  });
}
async function list() {
  return withStorage((records) => ({ records,
    value: [...records].sort((left, right) => timestamp(right.updatedAt) - timestamp(left.updatedAt)), write: false }));
}
async function load(id) {
  const conversationId = String(id || '');
  return withStorage((records) => ({ records,
    value: records.find((record) => record.id === conversationId) || null, write: false }));
}
async function remove(id) { return Boolean(await removeWithScoped(id)); }
async function removeWithScoped(id) {
  const conversationId = String(id || '');
  return withStorage((records) => {
    const removed = records.find((record) => record.id === conversationId) || null;
    const next = records.filter((record) => record.id !== conversationId);
    return { records: next, value: removed, write: Boolean(removed) };
  });
}
async function updateScoped(id, updater) {
  if (typeof updater !== 'function') throw new TypeError('Scoped updater must be a function');
  return withStorage((records) => {
    const index = records.findIndex((record) => record.id === String(id || ''));
    if (index < 0) return { records, value: null, write: false };
    const scoped = updater([...records[index].scoped]);
    if (!Array.isArray(scoped)) throw new TypeError('Scoped updater must return an array');
    const updated = { ...records[index], schema: 2, scoped, updatedAt: new Date().toISOString() };
    const next = records.map((item, position) => (position === index ? updated : item));
    return { records: next, value: updated, write: true };
  });
}
async function clearAll() { return withStorage(() => ({ records: [], value: true, write: true })); }
async function purgeOlderThan(days = RETENTION_DAYS, now = Date.now()) {
  const retention = Number.isFinite(Number(days)) && Number(days) >= 0 ? Number(days) : RETENTION_DAYS;
  const cutoff = Number(now) - retention * 86400000;
  return withStorage((records) => {
    const next = records.filter((record) => timestamp(record.updatedAt) >= cutoff);
    return { records: next, value: records.length - next.length, write: next.length !== records.length };
  });
}
async function newConversation(continuedFrom = null) {
  const now = new Date().toISOString();
  const conversation = { schema: 2, id: makeId(), title: 'Yeni sohbet', createdAt: now, updatedAt: now,
    turns: [], scoped: [], links: [], trimmed: 0, full: false,
    continued_from: typeof continuedFrom === 'string' && continuedFrom ? continuedFrom : null };
  await withStorage((records) => ({ records: [...records, conversation], value: conversation, write: true }));
  return conversation;
}
async function storageStatus() {
  await withStorage((records) => ({ records, value: null, write: false }));
  return { mode: storageMode, persistent: storageMode !== 'memory' };
}
export { MAX_CONTENT_LENGTH, MAX_TURNS, RETENTION_DAYS, REDACTED_TEXT, SENSITIVE_REDACTED_TEXT,
  saveTurn, appendCardToTurn, list, load, remove, removeWithScoped, updateScoped, clearAll, purgeOlderThan, newConversation,
  storageStatus, compactionNote, expiresAt, linkedCounts };
