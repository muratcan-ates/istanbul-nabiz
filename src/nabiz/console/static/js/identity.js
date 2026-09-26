/* Who this browser is, for the quota and the example account (DECISIONS #36). Pure storage helpers:
 * no DOM, no network, so node can import it in tests.
 *
 * nabiz.device.v1   a random id this browser made; not personal data. It goes only with the chat, the
 *                   quota strip and the account routes, and the server keeps only a salted hash of it,
 *                   in memory, for today's count.
 * nabiz.account.v1  {token, email, provider_label, tier}: the example account's sign-in token and what
 *                   the page shows about it. Deleted with the account. */

const DEVICE_KEY = 'nabiz.device.v1';
const ACCOUNT_KEY = 'nabiz.account.v1';
const IDENTITY_PATHS = ['/api/chat', '/api/quota', '/api/account', '/api/follow'];

function storage() {
  try { return window.localStorage; } catch (err) { return null; }
}

function randomId() {
  const bytes = new Uint8Array(16);
  (globalThis.crypto || window.crypto).getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

/** This browser's random id, made on first use; '' when storage is blocked (the address counts alone). */
function deviceId() {
  const store = storage();
  if (!store) return '';
  try {
    let id = store.getItem(DEVICE_KEY);
    if (!id || !/^[A-Za-z0-9_-]{16,64}$/.test(id)) { id = randomId(); store.setItem(DEVICE_KEY, id); }
    return id;
  } catch (err) { return ''; }
}

function readAccount() {
  const store = storage();
  try {
    const value = JSON.parse((store && store.getItem(ACCOUNT_KEY)) || 'null');
    return value && typeof value.token === 'string' ? value : null;
  } catch (err) { return null; }
}

function writeAccount(account) {
  const store = storage();
  try { store.setItem(ACCOUNT_KEY, JSON.stringify(account)); return true; } catch (err) { return false; }
}

function clearAccount() {
  const store = storage();
  try { store.removeItem(ACCOUNT_KEY); } catch (err) { /* private mode */ }
}

/** The headers a request to `path` carries: the device id and the account token, only where needed. */
function identityHeaders(path) {
  if (!IDENTITY_PATHS.some((prefix) => String(path).startsWith(prefix))) return {};
  const headers = {};
  const device = deviceId();
  if (device) headers['X-Nabiz-Device'] = device;
  const account = readAccount();
  if (account) headers['X-Nabiz-Account'] = account.token;
  return headers;
}

/** Every key this site keeps in this browser: "Hesabımı ve verilerimi sil" clears them all. */
function clearDeviceData() {
  const store = storage();
  if (!store) return 0;
  const keys = [];
  for (let i = 0; i < store.length; i += 1) {
    const key = store.key(i);
    if (key && key.startsWith('nabiz')) keys.push(key);
  }
  keys.forEach((key) => { try { store.removeItem(key); } catch (err) { /* keep going */ } });
  return keys.length;
}

export { DEVICE_KEY, ACCOUNT_KEY, deviceId, readAccount, writeAccount, clearAccount, identityHeaders, clearDeviceData };
