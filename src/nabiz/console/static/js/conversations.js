/* Conversation history stays in this browser. IndexedDB is preferred, with progressively smaller
 * storage fallbacks for browsers that block persistent storage. */

import { HISTORY_TURNS } from './config.js';

const STORAGE_KEY = 'nabiz.conversations.v1';
const DATABASE_NAME = 'nabiz-conversations';
const DATABASE_VERSION = 1;
const STORE_NAME = 'conversations';
const RETENTION_DAYS = 30;
const MAX_CONTENT_LENGTH = 4000;
const MAX_TURNS = 80;
const REDACTED_TEXT = '[acil yönlendirme]';

const EMERGENCY_TEXT = /112|acil|ambulans|can güvenliği|imdat/i;
const SENSITIVE_TEXT = /sağlık|hastalık|ilaç|doktor|teşhis|tani|kan tahlil|gebelik|hamile|psikolog|terapi|hukuk|avukat|dava|ceza|borç|maaş|banka|kredi|şifre|kimlik|adres|telefon|e-?posta|\b\d{11}\b|\b\d{10,}\b/i;

let databasePromise;
let indexedDbUnavailable = false;
let storageMode = 'unknown';
let memoryRecords = [];

function timestamp(value) {
  const parsed = Date.parse(value || '');
  return Number.isFinite(parsed) ? parsed : 0;
}

function normaliseRecords(records) {
  return Array.isArray(records)
    ? records.filter((record) => record && typeof record.id === 'string' && Array.isArray(record.turns))
    : [];
}

function openDatabase() {
  if (indexedDbUnavailable || typeof indexedDB === 'undefined') {
    return Promise.reject(new Error('IndexedDB is unavailable'));
  }
  if (!databasePromise) {
    databasePromise = new Promise((resolve, reject) => {
      try {
        const request = indexedDB.open(DATABASE_NAME, DATABASE_VERSION);
        request.onupgradeneeded = () => {
          if (!request.result.objectStoreNames.contains(STORE_NAME)) {
            request.result.createObjectStore(STORE_NAME, { keyPath: 'id' });
          }
        };
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error || new Error('IndexedDB could not open'));
        request.onblocked = () => reject(new Error('IndexedDB is blocked'));
      } catch (error) {
        reject(error);
      }
    });
  }
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
      } catch (error) {
        failure = error;
        transaction.abort();
      }
    };
    request.onerror = () => { failure = request.error || new Error('IndexedDB read failed'); };
    transaction.oncomplete = () => resolve(value);
    transaction.onerror = () => reject(failure || transaction.error || new Error('IndexedDB write failed'));
    transaction.onabort = () => reject(failure || transaction.error || new Error('IndexedDB transaction aborted'));
  }));
}

function localStorageObject() {
  try {
    return globalThis.localStorage || null;
  } catch (error) {
    return null;
  }
}

function mutateLocalStorage(mutator) {
  const storage = localStorageObject();
  if (!storage) throw new Error('localStorage is unavailable');
  const raw = storage.getItem(STORAGE_KEY);
  let records = [];
  if (raw) {
    try { records = normaliseRecords(JSON.parse(raw)); } catch (error) { records = []; }
  }
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
    } catch (error) {
      indexedDbUnavailable = true;
      databasePromise = null;
    }
  }
  try {
    const value = mutateLocalStorage(mutator);
    storageMode = 'localStorage';
    return value;
  } catch (error) {
    const result = mutator(memoryRecords);
    memoryRecords = result.records;
    storageMode = 'memory';
    return result.value;
  }
}

function makeId() {
  try {
    if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  } catch (error) {
    // Use a local identifier when browser crypto is unavailable.
  }
  return `convo-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function cleanTurn(turn, now) {
  const role = turn?.role === 'user' ? 'user' : turn?.role === 'assistant' ? 'assistant' : null;
  if (!role) return null;
  const content = String(turn.content ?? '');
  const detectionText = content.toLocaleLowerCase('tr-TR');
  const privateContent = turn.sensitive === true || turn.emergency === true || turn.mode === 'redirect'
    || EMERGENCY_TEXT.test(detectionText) || SENSITIVE_TEXT.test(detectionText);
  return {
    role,
    content: (privateContent ? REDACTED_TEXT : content).slice(0, MAX_CONTENT_LENGTH),
    at: typeof turn.at === 'string' && Number.isFinite(Date.parse(turn.at)) ? turn.at : now,
  };
}

function compactionNote(turnCount, keptTurns) {
  const count = Number(turnCount);
  const kept = Math.max(0, Math.floor(Number(keptTurns) || 0));
  if (!Number.isFinite(count) || count <= HISTORY_TURNS * 2) return '';
  return `Önceki mesajlar kısaltılarak gönderiliyor; yalnız son ${kept} soru hatırlanıyor.`;
}

async function saveTurn(id, turn) {
  const conversationId = String(id || '');
  const now = new Date().toISOString();
  const savedTurn = cleanTurn(turn, now);
  if (!conversationId || !savedTurn) return null;
  return withStorage((records) => {
    const index = records.findIndex((record) => record.id === conversationId);
    if (index < 0) return { records, value: null, write: false };
    const previous = records[index];
    const turns = [...previous.turns, savedTurn].slice(-MAX_TURNS);
    const title = previous.title === 'Yeni sohbet' && savedTurn.role === 'user'
      ? savedTurn.content.slice(0, 48).trimEnd() || 'Yeni sohbet'
      : previous.title;
    const updated = { ...previous, title, updatedAt: now, turns };
    const next = [...records];
    next[index] = updated;
    return { records: next, value: updated, write: true };
  });
}

async function list() {
  return withStorage((records) => ({
    records,
    value: [...records].sort((left, right) => timestamp(right.updatedAt) - timestamp(left.updatedAt)),
    write: false,
  }));
}

async function load(id) {
  const conversationId = String(id || '');
  return withStorage((records) => ({
    records,
    value: records.find((record) => record.id === conversationId) || null,
    write: false,
  }));
}

async function remove(id) {
  const conversationId = String(id || '');
  return withStorage((records) => {
    const next = records.filter((record) => record.id !== conversationId);
    return { records: next, value: next.length !== records.length, write: next.length !== records.length };
  });
}

async function clearAll() {
  return withStorage(() => ({ records: [], value: true, write: true }));
}

async function purgeOlderThan(days = RETENTION_DAYS, now = Date.now()) {
  const retention = Number.isFinite(Number(days)) && Number(days) >= 0 ? Number(days) : RETENTION_DAYS;
  const cutoff = Number(now) - retention * 86400000;
  return withStorage((records) => {
    const next = records.filter((record) => timestamp(record.createdAt) >= cutoff);
    return { records: next, value: records.length - next.length, write: next.length !== records.length };
  });
}

async function newConversation() {
  const now = new Date().toISOString();
  const conversation = { id: makeId(), title: 'Yeni sohbet', createdAt: now, updatedAt: now, turns: [] };
  await withStorage((records) => ({ records: [...records, conversation], value: conversation, write: true }));
  return conversation;
}

async function storageStatus() {
  await withStorage((records) => ({ records, value: null, write: false }));
  return { mode: storageMode, persistent: storageMode !== 'memory' };
}

export {
  MAX_CONTENT_LENGTH, MAX_TURNS, RETENTION_DAYS, REDACTED_TEXT,
  saveTurn, list, load, remove, clearAll, purgeOlderThan, newConversation, storageStatus, compactionNote,
};
