/* Confirmed memory stays in this browser. Profile records use localStorage; conversation records
 * live in the conversation store so deleting a conversation also deletes its scoped memory. */

import * as conversationStore from './conversations.js';

const MEMORY_KEY = 'nabiz.memory.v2';
const LEGACY_KEY = 'nabiz.memory.v1';
const FORGOTTEN_KEY = 'nabiz.memory.forgotten.v1';
const FORGOTTEN_DAYS = 30;
const NEED_KEYS = new Set([
  'step_free', 'stroller', 'slow_walk', 'low_vision', 'hearing', 'plain_language', 'answer_en',
]);
const INTERESTS = Object.freeze([
  'culture', 'museum', 'theatre', 'concert', 'cinema', 'library', 'sport', 'nature', 'children', 'course',
]);
const TYPES = new Set(['interest', 'place', 'need', 'health']);
const SOURCES = new Set(['chat_suggestion', 'user_typed', 'profile_form', 'migrated_v1']);
const transient = new Map();

function defaultStorage() {
  try { return globalThis.localStorage || null; } catch { return null; }
}

function createMemoryStore({ storage = defaultStorage(), now = () => new Date(), conversations = conversationStore } = {}) {
  const fallback = storage ? new Map() : transient;
  const clock = () => {
    const date = new Date(now());
    return Number.isFinite(date.getTime()) ? date.toISOString() : new Date().toISOString();
  };
  const read = (key) => {
    if (fallback.has(key)) return fallback.get(key);
    try { return storage ? storage.getItem(key) : null; }
    catch { return fallback.get(key) || null; }
  };
  const write = (key, value) => {
    try {
      if (storage) { storage.setItem(key, value); fallback.delete(key); }
      else fallback.set(key, value);
      return true;
    } catch {
      fallback.set(key, value);
      return false;
    }
  };
  const erase = (key) => {
    try { if (storage) storage.removeItem(key); } catch { /* Private browsing may block storage. */ }
    fallback.delete(key);
  };
  const array = (key) => {
    try {
      const value = JSON.parse(read(key) || '[]');
      return Array.isArray(value) ? value : [];
    } catch { return []; }
  };
  const makeId = () => {
    try { if (globalThis.crypto?.randomUUID) return `mem-${globalThis.crypto.randomUUID()}`; } catch { /* fallback */ }
    return `mem-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  };

  function normalise(raw, fallbackScope = 'profile') {
    if (!raw || typeof raw !== 'object' || !TYPES.has(raw.type)) return null;
    if (raw.owner != null && raw.owner !== 'browser') return null;
    const type = raw.type;
    const scope = raw.scope === 'conversation' ? 'conversation'
      : raw.scope === 'profile' ? 'profile' : fallbackScope;
    const label = String(raw.label || '').trim().slice(0, 1000);
    if (!label) return null;
    let key = typeof raw.key === 'string' ? raw.key.trim().slice(0, 200) : null;
    if (type === 'need' && !NEED_KEYS.has(key)) return null;
    if (type === 'interest' && !INTERESTS.includes(key)) return null;
    if (type === 'place' && key && !/^(station|line):.+/.test(key)) return null;
    if (type === 'health') key = null;
    const conversationId = scope === 'conversation' ? String(raw.conversation_id || '') : null;
    if (scope === 'conversation' && !conversationId) return null;
    const needKey = NEED_KEYS.has(raw.need_key) ? raw.need_key : null;
    const at = clock();
    return {
      id: typeof raw.id === 'string' && raw.id ? raw.id : makeId(),
      type, label, key, scope, conversation_id: conversationId,
      source: SOURCES.has(raw.source) ? raw.source : 'user_typed',
      consent_at: typeof raw.consent_at === 'string' && Number.isFinite(Date.parse(raw.consent_at))
        ? raw.consent_at : at,
      updated_at: typeof raw.updated_at === 'string' && Number.isFinite(Date.parse(raw.updated_at))
        ? raw.updated_at : at,
      reviewed_at: typeof raw.reviewed_at === 'string' && Number.isFinite(Date.parse(raw.reviewed_at))
        ? raw.reviewed_at : null,
      sensitive: type === 'health' ? true : raw.sensitive === true,
      need_key: type === 'health' ? needKey : null,
      related_ids: Array.isArray(raw.related_ids)
        ? raw.related_ids.filter((id) => typeof id === 'string').slice(0, 20) : [],
      owner: 'browser',
    };
  }

  function forgotten() {
    const cutoff = Date.parse(clock()) - FORGOTTEN_DAYS * 86400000;
    const kept = array(FORGOTTEN_KEY).filter((item) => item && TYPES.has(item.type)
      && typeof item.key === 'string' && Number.isFinite(Date.parse(item.at))
      && Date.parse(item.at) >= cutoff);
    if (kept.length !== array(FORGOTTEN_KEY).length) write(FORGOTTEN_KEY, JSON.stringify(kept));
    return kept;
  }

  function isForgotten(type, key) {
    if (!TYPES.has(type) || typeof key !== 'string' || !key) return false;
    return forgotten().some((item) => item.type === type && item.key === key);
  }

  function markForgotten(record) {
    if (!record?.key) return;
    const next = forgotten().filter((item) => item.type !== record.type || item.key !== record.key);
    next.push({ type: record.type, key: record.key, at: clock() });
    write(FORGOTTEN_KEY, JSON.stringify(next));
  }

  function migrateV1() {
    const old = array(LEGACY_KEY);
    if (!read(LEGACY_KEY)) return 0;
    const stored = array(MEMORY_KEY);
    const foreign = stored.filter((item) => item?.owner != null && item.owner !== 'browser');
    const current = stored.map((item) => normalise(item)).filter(Boolean);
    let added = 0;
    old.forEach((item) => {
      if (!item || typeof item.key !== 'string') return;
      const key = item.key;
      const type = NEED_KEYS.has(key) ? 'need' : INTERESTS.includes(key) ? 'interest' : 'place';
      const validKey = type === 'place' && !/^(station|line):.+/.test(key) ? null : key;
      if (isForgotten(type, validKey) || current.some((entry) => entry.type === type && entry.key === validKey
        && entry.label === String(item.label || key))) return;
      const entry = normalise({
        type, key: validKey, label: item.label || key, scope: 'profile', source: 'migrated_v1',
        consent_at: item.added_at, updated_at: item.added_at,
      });
      if (entry) { current.push(entry); added += 1; }
    });
    if (write(MEMORY_KEY, JSON.stringify([...foreign, ...current]))) erase(LEGACY_KEY);
    return added;
  }

  function listProfile() {
    migrateV1();
    const stored = array(MEMORY_KEY);
    const records = stored.map((item) => normalise(item)).filter((item) => item?.scope === 'profile');
    if (stored.some((item) => item && typeof item === 'object' && item.owner == null)) {
      write(MEMORY_KEY, JSON.stringify(stored.map((item) => item && typeof item === 'object'
        && item.owner == null ? { ...item, owner: 'browser' } : item)));
    }
    return records;
  }

  function writeProfileRecords(records) {
    const foreign = array(MEMORY_KEY).filter((item) => item?.owner != null && item.owner !== 'browser');
    return write(MEMORY_KEY, JSON.stringify([...foreign, ...records]));
  }

  function saveProfile(record) {
    const entry = normalise({ ...record, scope: 'profile', conversation_id: null });
    if (!entry) return null;
    const records = listProfile().filter((item) => item.id !== entry.id);
    return writeProfileRecords([...records, entry]) ? entry : null;
  }

  function healthAllowed(record) {
    return record?.type !== 'health' || (
      (record.source === 'user_typed' || record.source === 'profile_form')
      && record.explicit_health_consent === true);
  }

  function addProfile(record) {
    return healthAllowed(record) ? saveProfile(record) : null;
  }

  function forgetProfileKey(key) {
    const records = listProfile();
    const removed = records.filter((item) => item.key === key);
    if (writeProfileRecords(records.filter((item) => item.key !== key))) {
      removed.forEach(markForgotten);
    }
    return listProfile();
  }

  function clearProfileRecords() {
    const records = listProfile();
    if (writeProfileRecords([])) records.forEach(markForgotten);
    erase(LEGACY_KEY);
  }

  async function scopedRecords(conversationId) {
    if (conversationId) {
      const record = await conversations.load(conversationId);
      return record ? [record] : [];
    }
    return conversations.list();
  }

  async function list({ type, scope, conversationId } = {}) {
    const result = scope === 'conversation' ? [] : listProfile();
    if (scope !== 'profile') {
      for (const conversation of await scopedRecords(conversationId)) {
        const scoped = Array.isArray(conversation.scoped) ? conversation.scoped : [];
        for (const raw of scoped) {
          const item = normalise(raw, 'conversation');
          if (item?.scope === 'conversation' && item.conversation_id === conversation.id) result.push(item);
        }
        if (scoped.some((item) => item && typeof item === 'object' && item.owner == null)) {
          await conversations.updateScoped(conversation.id,
            (items) => items.map((item) => item && typeof item === 'object' && item.owner == null
              ? { ...item, owner: 'browser' } : item));
        }
      }
    }
    return result.filter((item) => (!type || item.type === type)
      && (!conversationId || item.scope === 'profile' || item.conversation_id === conversationId));
  }

  async function saveScoped(entry) {
    const updated = await conversations.updateScoped(entry.conversation_id, (scoped) => [
      ...(Array.isArray(scoped) ? scoped : []).filter((item) => item.id !== entry.id), entry,
    ]);
    return updated ? entry : null;
  }

  async function add(record) {
    if (!healthAllowed(record)) return null;
    const entry = normalise(record, record?.scope === 'conversation' ? 'conversation' : 'profile');
    if (!entry) return null;
    return entry.scope === 'profile' ? saveProfile(entry) : saveScoped(entry);
  }

  async function update(id, patch) {
    const all = await list();
    const old = all.find((item) => item.id === id);
    if (!old || !patch || typeof patch !== 'object') return null;
    const next = normalise({ ...old, ...patch, id, updated_at: clock() }, old.scope);
    if (!next) return null;
    if (old.scope === next.scope && old.conversation_id === next.conversation_id) {
      if (next.scope === 'profile') return saveProfile(next);
      const saved = await conversations.updateScoped(old.conversation_id, (scoped) =>
        scoped.map((item) => item.id === id ? next : item));
      return saved ? next : null;
    }
    if (next.scope === 'conversation') {
      if (old.scope === 'profile') {
        const profileRecords = listProfile();
        if (!writeProfileRecords(profileRecords.filter((item) => item.id !== id))) return null;
        try {
          if (await saveScoped(next)) return next;
        } catch { /* Restore the original record below. */ }
        writeProfileRecords(profileRecords);
        return null;
      }
      if (!await saveScoped(next)) return null;
      try {
        if (await conversations.updateScoped(old.conversation_id,
          (scoped) => scoped.filter((item) => item.id !== id))) return next;
      } catch { /* Remove the destination copy below. */ }
      await conversations.updateScoped(next.conversation_id, (scoped) => scoped.filter((item) => item.id !== id));
      return null;
    } else {
      if (!saveProfile(next)) return null;
      try {
        if (await conversations.updateScoped(old.conversation_id,
          (scoped) => scoped.filter((item) => item.id !== id))) return next;
      } catch { /* Remove the destination copy below. */ }
      writeProfileRecords(listProfile().filter((item) => item.id !== id));
      return null;
    }
  }

  async function forget(id) {
    const old = (await list()).find((item) => item.id === id);
    if (!old) return null;
    if (old.scope === 'profile') {
      if (!writeProfileRecords(listProfile().filter((item) => item.id !== id))) return null;
    } else {
      const saved = await conversations.updateScoped(old.conversation_id, (scoped) =>
        scoped.filter((item) => item.id !== id));
      if (!saved) return null;
    }
    markForgotten(old);
    return old;
  }

  async function forgetAll() {
    const all = await list();
    const conversationsToClear = await scopedRecords();
    if (!writeProfileRecords([])) return false;
    erase(LEGACY_KEY);
    all.filter((item) => item.scope === 'profile').forEach(markForgotten);
    let complete = true;
    for (const conversation of conversationsToClear) {
      const owned = all.filter((item) => item.scope === 'conversation' && item.conversation_id === conversation.id);
      if (!owned.length) continue;
      try {
        const saved = await conversations.updateScoped(conversation.id,
          (scoped) => scoped.filter((item) => item?.owner != null && item.owner !== 'browser'));
        if (saved) owned.forEach(markForgotten);
        else complete = false;
      } catch { complete = false; }
    }
    return complete;
  }

  function requestNeeds({ profile, conversation } = {}) {
    const allowed = new Set();
    if (profile?.consent === true) {
      for (const key of Array.isArray(profile.needs) ? profile.needs : []) if (NEED_KEYS.has(key)) allowed.add(key);
      for (const item of listProfile()) {
        if (item.type === 'need' && NEED_KEYS.has(item.key)) allowed.add(item.key);
        if (item.type === 'health' && NEED_KEYS.has(item.need_key)) allowed.add(item.need_key);
      }
    }
    for (const raw of Array.isArray(conversation?.scoped) ? conversation.scoped : []) {
      const item = normalise(raw, 'conversation');
      if (!item || item.conversation_id !== conversation.id) continue;
      if (item.type === 'need' && NEED_KEYS.has(item.key)) allowed.add(item.key);
      if (item.type === 'health' && NEED_KEYS.has(item.need_key)) allowed.add(item.need_key);
    }
    return [...allowed].slice(0, 16);
  }

  function shareable(purpose, context = {}) {
    return purpose === 'model' ? requestNeeds(context) : [];
  }

  return {
    list, listProfile, add, addProfile, update, forget, forgetAll, isForgotten, requestNeeds, shareable,
    migrateV1, forgetProfileKey, clearProfileRecords,
  };
}

export { createMemoryStore, MEMORY_KEY, LEGACY_KEY, FORGOTTEN_KEY, NEED_KEYS, INTERESTS };
