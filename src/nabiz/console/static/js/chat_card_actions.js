/* ChatCard actions are inert data until an owner accepts their cancelable event. */
import { t } from './i18n_text.js';

export const ACTION_KIND = Object.freeze({
  use_location: 'device', type_place: 'view', expand_map: 'view', listen: 'view',
  remember_here: 'device', remember_always: 'device', change: 'view', forget: 'device',
  save_calendar: 'nabiz', export_ics: 'device', review_report: 'view', send: 'nabiz',
  open_official: 'external', add_outlook: 'external', confirm_resolved: 'nabiz',
  reopen: 'nabiz', cancel: 'nabiz', appeal: 'nabiz', share: 'external',
});
export const CARD_ACTIONS = Object.freeze(Object.keys(ACTION_KIND));
export const CONSENT_ACTIONS = Object.freeze(['use_location', 'remember_here', 'remember_always',
  'save_calendar', 'send', 'add_outlook', 'confirm_resolved', 'reopen', 'cancel', 'appeal', 'share']);
export const ACTION_ALIASES = Object.freeze({ add_calendar: 'save_calendar', download_ics: 'export_ics',
  open_map: 'expand_map', remember: 'remember_here' });
export const CARD_RESULTS = Object.freeze([null, 'saved_nabiz', 'ics_downloaded', 'outlook_verifying',
  'outlook_added', 'outlook_failed', 'report_sent', 'resolution_confirmed', 'reopened', 'cancelled', 'appeal_sent']);
export const RESTORED_ACTIONS = Object.freeze(['expand_map', 'listen', 'open_official']);

const ACTION_TR = { use_location: 'Konumumu kullan', type_place: 'Yer yaz', listen: 'Dinle',
  remember_here: 'Burada hatırla', remember_always: 'Her zaman hatırla', change: 'Değiştir', forget: 'Unut',
  save_calendar: 'Takvime kaydet', export_ics: 'Takvim dosyası indir', review_report: 'Bildirimi gözden geçir',
  send: 'Gönder', open_official: 'Resmî kaynağı aç', add_outlook: "Outlook'a ekle",
  confirm_resolved: 'Çözüldü, onayla', reopen: 'Yeniden aç', cancel: 'İptal et', appeal: 'İtiraz et', share: 'Paylaş' };
const CONSENT_TR = {
  use_location: 'Konumunuz bu cihazda kullanılacak.',
  remember_here: 'Bu bilgi yalnız bu sohbette hatırlanacak.',
  remember_always: 'Bu bilgi bu tarayıcıdaki profilinize kaydedilecek.',
  save_calendar: 'Bu plan Nabız takviminize kaydedilecek.',
  send: 'Bu bildirim Nabız üzerinden ilgili ekibe gönderilecek.',
  add_outlook: 'Bu olay Outlook takviminize eklenecek; Microsoft hesabınıza yazılır.',
  confirm_resolved: 'Bu bildirimi çözüldü olarak onaylayacaksınız.',
  reopen: 'Bu bildirim yeniden açılacak.',
  cancel: 'Bu işlem iptal edilecek.',
  appeal: 'Bu itiraz Nabız üzerinden ilgili ekibe gönderilecek.',
  share: 'Yalnız başlık ve resmî kaynak adresi paylaşılacak.',
};
const CONSENT_KIND_TR = { view: 'Bu kartın görünümü değişecek.',
  device: 'Bu işlem yalnız bu cihazda uygulanacak.', nabiz: 'Bu işlem Nabız üzerinde kaydedilecek.',
  external: 'Bu işlem Nabız dışındaki bağlı hizmete gönderilecek.' };
const RESULT_TR = { saved_nabiz: 'Nabız takvimine kaydedildi.', ics_downloaded: 'Takvim dosyası indirildi.',
  outlook_verifying: "Outlook'a ekleniyor, doğrulanıyor.", outlook_added: "Outlook'a eklendi.",
  outlook_failed: "Outlook'a eklenemedi.", report_sent: 'Bildirim gönderildi.',
  resolution_confirmed: 'Çözüldüğü onaylandı.', reopened: 'Yeniden açıldı.', cancelled: 'İptal edildi.',
  appeal_sent: 'İtiraz gönderildi.' };
const pending = new Map();
let consentCount = 0;

function plain(value, limit) {
  if (typeof value !== 'string') return '';
  return value.replace(/<(script|style|template|iframe|object|svg)\b[^>]*>[\s\S]*?<\/\1\s*>/gi, ' ')
    .replace(/<[^>]*>/g, ' ').replace(/[<>]/g, '').replace(/\s+/g, ' ').trim().slice(0, limit);
}

export function normalizeAction(raw) {
  const data = typeof raw === 'string' ? { id: raw } : raw && typeof raw === 'object' && !Array.isArray(raw) ? raw : {};
  const id = ACTION_ALIASES[data.id] || data.id;
  if (!CARD_ACTIONS.includes(id)) return null;
  const kind = ACTION_KIND[id];
  return { id, label: plain(data.label, 40), kind,
    requires_consent: CONSENT_ACTIONS.includes(id) || data.requires_consent === true,
    operation_id: kind === 'nabiz' || kind === 'external' ? plain(data.operation_id, 120) || null : null };
}

function linkedId(linked) {
  if (linked.event_id) return `event:${linked.event_id}`;
  if (linked.report_code) return `report:${linked.report_code}`;
  if (linked.operation_id) return `op:${linked.operation_id}`;
  return null;
}

function sourceFromV0(raw) {
  if (!raw || typeof raw !== 'object') return null;
  return { label: raw.name ?? raw.label, url: raw.url ?? null,
    source_time: raw.observed_at ?? raw.source_time ?? null, freshness: raw.freshness };
}

export function fromV0(raw) {
  if (!raw || typeof raw !== 'object' || raw.v !== 0) return raw;
  const body = raw.data && typeof raw.data === 'object' && !Array.isArray(raw.data) ? raw.data : {};
  const sources = [raw.source, ...(Array.isArray(body.sources) ? body.sources.slice(0, 5) : [])]
    .map(sourceFromV0).filter(Boolean);
  const times = sources.map((source) => source.source_time).filter((value) => Number.isFinite(Date.parse(value)));
  times.sort((a, b) => Date.parse(a) - Date.parse(b));
  const linked = raw.linked && typeof raw.linked === 'object' ? { ...raw.linked } : {};
  const actions = Array.isArray(raw.actions) ? raw.actions.map((action) => normalizeAction(action) || action) : [];
  return { ...raw, v: 1, body, sources, source_time: times[0] || null,
    linked, linked_id: linkedId(linked), actions };
}

export async function operationId(card, action, messageId) {
  const normalized = normalizeAction(action);
  if (!normalized || !['nabiz', 'external'].includes(normalized.kind)) return null;
  if (normalized.operation_id) return normalized.operation_id;
  if (!globalThis.crypto?.subtle || !card?.id || !messageId) return null;
  const input = new TextEncoder().encode(`${card.id}\0${normalized.id}\0${messageId}`);
  try {
    const digest = await globalThis.crypto.subtle.digest('SHA-256', input);
    const hex = [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
    return `op-${hex.slice(0, 16)}`;
  } catch { return null; }
}

export async function prepareCardActions(raw, messageId) {
  const card = raw?.v === 0 ? fromV0(raw) : raw;
  if (!card || typeof card !== 'object') return card;
  const actions = Array.isArray(card.actions) ? (await Promise.all(card.actions.slice(0, 20).map(async (rawAction) => {
    const action = normalizeAction(rawAction);
    if (!action) return null;
    if (action.kind === 'nabiz' || action.kind === 'external') {
      action.operation_id = await operationId(card, action, messageId || card.message_id);
    }
    return action;
  }))).filter(Boolean) : [];
  return { ...card, message_id: messageId || card.message_id || null, actions };
}

export function resultLabel(result) {
  return result && CARD_RESULTS.includes(result) ? t(`ui.cards.result_${result}`, RESULT_TR[result]) : '';
}

function element(tag, className, content) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (content !== undefined) node.textContent = content;
  return node;
}

function actionKey(cardId, actionId) { return `${cardId}\0${actionId}`; }

export function releaseCardAction(cardId, actionId) {
  const key = actionKey(cardId, actionId);
  const button = pending.get(key);
  if (button) button.removeAttribute('aria-disabled');
  pending.delete(key);
}

function unhandledStatus(action, status) {
  status.textContent = action.id === 'add_outlook'
    ? t('ui.cards.outlook_not_connected', "Outlook bağlantısı yok; plan yalnız Nabız'da duruyor, Outlook'a eklenmedi.")
    : t('ui.cards.action_not_ready', 'Bu işlem henüz bağlı değil; hiçbir şey kaydedilmedi.');
}

function publish(card, action, button, status, consentedAt) {
  const key = actionKey(card.id, action.id);
  if (pending.has(key)) return;
  if (['nabiz', 'external'].includes(action.kind) && !action.operation_id) {
    unhandledStatus(action, status);
    return;
  }
  pending.set(key, button);
  button.setAttribute('aria-disabled', 'true');
  const event = new CustomEvent('nabiz:card-action', { cancelable: true, detail: {
    card_id: card.id, type: card.type, action: action.id, kind: action.kind,
    requires_consent: action.requires_consent, operation_id: action.operation_id,
    consented_at: consentedAt, message_id: card.message_id, conversation_id: card.conversation_id,
  } });
  const unhandled = document.dispatchEvent(event) !== false && !event.defaultPrevented;
  if (unhandled) { unhandledStatus(action, status); releaseCardAction(card.id, action.id); }
}

function consentRow(article, card, action, button, status) {
  const prior = article.querySelector?.('.chat-card-consent');
  prior?.remove();
  const actions = article.querySelector?.('.chat-card-actions');
  if (actions) actions.hidden = true;
  const row = element('div', 'chat-card-consent');
  const consent = CONSENT_TR[action.id]
    ? t(`ui.cards.consent_${action.id}`, CONSENT_TR[action.id])
    : t(`ui.cards.consent_kind_${action.kind}`, CONSENT_KIND_TR[action.kind]);
  const sentence = element('p', '', consent);
  sentence.id = `chat-card-consent-${++consentCount}`;
  row.append(sentence);
  const controls = element('div', 'chat-card-consent-controls');
  const confirm = element('button', 'btn', t('ui.cards.confirm', 'Onayla'));
  confirm.type = 'button';
  confirm.setAttribute('aria-describedby', sentence.id);
  const dismiss = element('button', 'btn btn-quiet', t('ui.cards.dismiss', 'Vazgeç'));
  dismiss.type = 'button';
  confirm.addEventListener('click', () => {
    if (pending.has(actionKey(card.id, action.id))) return;
    row.remove();
    if (actions) actions.hidden = false;
    publish(card, action, button, status, new Date().toISOString());
    button.focus({ preventScroll: true });
  });
  dismiss.addEventListener('click', () => {
    row.remove();
    if (actions) actions.hidden = false;
    button.focus({ preventScroll: true });
  });
  controls.append(confirm, dismiss);
  row.append(controls);
  article.append(row);
  confirm.focus();
}

function addButton(article, row, card, action, index) {
  const label = action.id === 'expand_map' ? t('ui.cards.expand_map', 'Haritayı büyüt')
    : t(`ui.cards.action_${action.id}`, ACTION_TR[action.id]);
  const button = element('button', index < 2 ? 'btn' : 'btn btn-quiet', label);
  button.type = 'button';
  button.dataset.cardAction = action.id;
  const status = element('span', 'chat-card-action-status', '');
  status.setAttribute('role', 'status');
  button.addEventListener('click', () => {
    if (pending.has(actionKey(card.id, action.id))) return;
    status.textContent = '';
    if (action.requires_consent) consentRow(article, card, action, button, status);
    else publish(card, action, button, status, null);
  });
  const item = element('span', 'chat-card-action');
  item.append(button, status);
  row.append(item);
}

export function appendActionControls(article, card, actions) {
  if (!actions.length) return null;
  const row = element('div', 'chat-card-actions');
  article.append(row);
  const mount = (ready) => ready.forEach((action, index) => addButton(article, row, card, action, index));
  const missing = actions.some((action) => ['nabiz', 'external'].includes(action.kind) && !action.operation_id);
  if (!missing) mount(actions);
  else prepareCardActions({ ...card, actions }, card.message_id).then((prepared) => {
    card.actions = prepared.actions;
    mount(prepared.actions);
  }).catch(() => {
    const status = element('span', 'chat-card-action-status',
      t('ui.cards.action_not_ready', 'Bu işlem henüz bağlı değil; hiçbir şey kaydedilmedi.'));
    status.setAttribute('role', 'status');
    row.append(status);
  });
  return row;
}
