/* A counted, explicit browser reset. External calendar files and Outlook events are out of reach. */
import * as conversationStore from './conversations.js';
import { t } from './i18n_text.js';

const DATA_GROUPS = Object.freeze([
  { id: 'conversations', label: 'Sohbetler', keys: ['nabiz.conversations.v1'] },
  { id: 'memory', label: 'Hafıza', keys: ['nabiz.memory.v2', 'nabiz.memory.forgotten.v1', 'nabiz.memory.v1'] },
  { id: 'profile', label: 'Profil', keys: ['nabiz.profile.v1'] },
  { id: 'follows', label: 'Takip', keys: ['nabiz.follows.v1', 'nabiz.follows.seen.v1'] },
  { id: 'stops', label: 'Kayıtlı duraklar', keys: ['nabiz.my-stops.v1', 'nabiz.my-stops.asked.v1'] },
  { id: 'reports', label: 'Bildirimler', keys: ['nabiz.report.v1', 'nabiz.report-codes.v1'] },
  { id: 'requests', label: 'Operatör talepleri', keys: ['nabiz.requests.v1'] },
  { id: 'cards', label: 'Kaydedilen kartlar', keys: ['nabiz.saved-cards.v1'] },
  { id: 'discovery', label: 'Keşif tercihleri', keys: ['nabiz.nearby.v1', 'nabiz.culture.v1'] },
  { id: 'account', label: 'Örnek hesap', keys: ['nabiz.account.v1', 'nabiz.device.v1'] },
  { id: 'feedback', label: 'Geri bildirim', keys: ['nabiz.feedback.v1'] },
  { id: 'appearance', label: 'Görünüm ve dil', optional: true,
    keys: ['nabiz.a11y.v1', 'nabiz-simple', 'nabiz-theme', 'nabiz.lang.v1',
      'nabiz.persona.v1', 'nabiz.kolay.v1', 'nabiz.easyread.v1'] },
]);
const COPY = {
  title: 'Tüm Nabız verimi sil', confirm: 'Evet, hepsini sil', cancel: 'Vazgeç',
  description: 'Bu tarayıcıdaki seçili veri grupları silinir. Bu işlem geri alınamaz.',
  external: "Bilgisayarınıza indirilen takvim dosyaları ve Outlook'a eklenmiş kayıtlar buradan silinemez.",
  deleted: 'silindi', failed: 'silinemedi', reload: 'Sayfayı yenile',
  result: 'Silme bitti. Her grubun sonucunu aşağıda görebilirsiniz.',
  count: '{count} kayıt', kept: 'silinmedi, bu tarayıcıda kaldı',
  retryAccount: 'Hesap bölümünden yeniden deneyin.',
};
const tx = (key, vars) => t(`ui.reset.${key}`, COPY[key], vars);

function storageObject() {
  try { return globalThis.localStorage || globalThis.window?.localStorage || null; } catch { return null; }
}

function storedCount(value) {
  if (value == null) return 0;
  try {
    const data = JSON.parse(value);
    if (Array.isArray(data)) return data.length;
    if (data && typeof data === 'object') {
      if (Array.isArray(data.pairs)) return data.pairs.length;
      if (Array.isArray(data.entries)) return data.entries.length;
      return Object.keys(data).length ? 1 : 0;
    }
    return data ? 1 : 0;
  } catch { return value ? 1 : 0; }
}

async function deleteExampleAccount() {
  const { del } = await import('./api.js');
  return del('/api/account');
}

function briefCaches(cacheStorage) {
  return cacheStorage?.keys ? cacheStorage.keys().then((keys) => keys.filter((key) => key.startsWith('nabiz-brief-')))
    : Promise.resolve([]);
}

async function groupCounts({ storage = storageObject(), store, conversations = conversationStore,
  cacheStorage = globalThis.caches || globalThis.window?.caches || null }) {
  const counts = {};
  for (const group of DATA_GROUPS) {
    try {
      if (group.id === 'conversations') counts[group.id] = (await conversations.list()).length;
      else if (group.id === 'memory') counts[group.id] = (await store.list({})).length;
      else counts[group.id] = storage ? group.keys.reduce((total, key) => total + storedCount(storage.getItem(key)), 0) : null;
      if (group.id === 'discovery' && counts[group.id] !== null) counts[group.id] += (await briefCaches(cacheStorage)).length;
    } catch { counts[group.id] = null; }
  }
  return counts;
}

async function clearDataGroups({ storage = storageObject(), store, conversations = conversationStore,
  includeAppearance = false, deleteAccount = deleteExampleAccount,
  cacheStorage = globalThis.caches || globalThis.window?.caches || null } = {}) {
  const results = [];
  let remoteAccountFailed = false;
  let account = null;
  try { account = JSON.parse(storage?.getItem('nabiz.account.v1') || 'null'); } catch { account = null; }
  try {
    if (account && typeof account.token === 'string' && account.token) await deleteAccount();
  } catch { remoteAccountFailed = true; }
  for (const group of DATA_GROUPS) {
    if (group.optional && !includeAppearance) continue;
    let deleted = true;
    try {
      if (group.id === 'memory' && !await store.forgetAll()) deleted = false;
      if (group.id === 'conversations' && !await conversations.clearAll()) deleted = false;
      if (group.id === 'discovery') {
        for (const key of await briefCaches(cacheStorage)) if (!await cacheStorage.delete(key)) deleted = false;
      }
    } catch { deleted = false; }
    if (group.id === 'account' && remoteAccountFailed) {
      results.push({ id: group.id, label: group.label, deleted: false, remoteFailure: true });
      continue;
    }
    for (const key of group.keys) {
      try {
        if (!storage) throw new Error('Device storage unavailable');
        storage.removeItem(key);
        if (storage.getItem(key) !== null) deleted = false;
      } catch { deleted = false; }
    }
    if (group.id === 'conversations') {
      try { if ((await conversations.list()).length) deleted = false; } catch { deleted = false; }
    }
    if (group.id === 'follows' && remoteAccountFailed) deleted = false;
    results.push({ id: group.id, label: group.label, deleted,
      remoteFailure: remoteAccountFailed && (group.id === 'follows' || group.id === 'account') });
  }
  return results;
}

function element(doc, tag, className = '', value = '') {
  const node = doc.createElement(tag);
  if (className) node.className = className;
  if (value) node.textContent = value;
  return node;
}

function mountDataReset(root, { store, session, onChanged = () => {},
  storage = storageObject(), conversations = conversationStore,
  deleteAccount = deleteExampleAccount, cacheStorage = globalThis.caches || globalThis.window?.caches || null } = {}) {
  if (!root) throw new TypeError('Hesabım bölümü bulunamadı.');
  const doc = root.ownerDocument;
  const host = element(doc, 'div', 'data-reset'); host.id = 'veri-sil';
  const trigger = element(doc, 'button', 'btn btn-danger', tx('title'));
  trigger.type = 'button';
  const dialog = element(doc, 'dialog', 'data-reset-dialog');
  const heading = element(doc, 'h3', '', tx('title')); heading.id = 'data-reset-title';
  dialog.setAttribute('aria-labelledby', heading.id);
  const description = element(doc, 'p', '', tx('description'));
  const groups = element(doc, 'ul', 'data-reset-groups');
  const optional = element(doc, 'label', 'data-reset-optional');
  const checkbox = element(doc, 'input'); checkbox.type = 'checkbox'; checkbox.checked = false;
  optional.append(checkbox, element(doc, 'span', '', DATA_GROUPS.find((group) => group.optional).label));
  const external = element(doc, 'p', 'data-reset-external', tx('external'));
  const actions = element(doc, 'div', 'data-reset-actions');
  const cancel = element(doc, 'button', 'btn btn-quiet', tx('cancel')); cancel.type = 'button';
  const confirm = element(doc, 'button', 'btn btn-danger', tx('confirm')); confirm.type = 'button';
  actions.append(cancel, confirm);
  const status = element(doc, 'p', 'data-reset-status');
  status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
  dialog.append(heading, description, groups, optional, external, actions, status);
  host.append(trigger, dialog); root.append(host);
  let reload = null;

  trigger.addEventListener('click', async () => {
    reload?.remove(); reload = null;
    trigger.setAttribute('aria-busy', 'true');
    const counts = await groupCounts({ storage, store, conversations, cacheStorage });
    groups.replaceChildren();
    for (const group of DATA_GROUPS.filter((item) => !item.optional)) {
      const item = element(doc, 'li', 'data-reset-group'); item.dataset.group = group.id;
      item.append(element(doc, 'span', '', tx(group.id) || group.label),
        element(doc, 'span', 'data-reset-count', counts[group.id] == null ? '?' : tx('count', { count: counts[group.id] })));
      groups.append(item);
    }
    const appearance = DATA_GROUPS.find((item) => item.optional);
    optional.querySelector('span').textContent = tx(appearance.id) || appearance.label;
    checkbox.checked = false; optional.hidden = false;
    confirm.hidden = false; cancel.hidden = false; status.textContent = '';
    trigger.removeAttribute('aria-busy');
    dialog.showModal(); cancel.focus();
  });
  cancel.addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => trigger.focus());
  dialog.addEventListener('cancel', (event) => { event.preventDefault(); dialog.close(); });
  confirm.addEventListener('click', async () => {
    confirm.setAttribute('aria-busy', 'true'); confirm.disabled = true;
    const resetConversations = session?.clearConversations
      ? { list: () => conversations.list(), clearAll: () => session.clearConversations() }
      : conversations;
    const results = await clearDataGroups({ storage, store, conversations: resetConversations,
      includeAppearance: checkbox.checked,
      deleteAccount, cacheStorage });
    if (!checkbox.checked) results.push({ id: 'appearance', label: DATA_GROUPS.find((item) => item.optional).label,
      kept: true });
    results.forEach((result) => {
      let item = [...groups.children].find((entry) => entry.dataset.group === result.id);
      if (!item) { item = element(doc, 'li', 'data-reset-group'); item.dataset.group = result.id; groups.append(item); }
      item.replaceChildren(element(doc, 'span', '', tx(result.id) || result.label),
        element(doc, 'strong', result.kept ? 'data-reset-kept' : result.deleted ? 'data-reset-done' : 'data-reset-failed',
          tx(result.kept ? 'kept' : result.deleted ? 'deleted' : 'failed')));
      if (result.id === 'account' && result.remoteFailure) {
        const retry = element(doc, 'a', '', tx('retryAccount')); retry.href = '#hesap'; item.append(retry);
      }
    });
    if (!session?.clearConversations) await session.onClearedAll?.();
    await onChanged();
    optional.hidden = true; confirm.hidden = true; cancel.hidden = true;
    confirm.disabled = false; confirm.removeAttribute('aria-busy');
    status.textContent = tx('result');
    reload = element(doc, 'button', 'btn', tx('reload'));
    reload.type = 'button'; reload.addEventListener('click', () => doc.defaultView?.location.reload());
    actions.append(reload); reload.focus();
  });
  return { trigger, dialog };
}

export { DATA_GROUPS, groupCounts, clearDataGroups, mountDataReset };
