/* ChatCard v1 is data only. Renderers receive normalized data, never model HTML. */
import { t } from './i18n_text.js';
import { ACTION_KIND, CARD_RESULTS, RESTORED_ACTIONS, normalizeAction, fromV0,
  resultLabel, appendActionControls } from './chat_card_actions.js';
export { ACTION_KIND, CARD_ACTIONS, CARD_RESULTS, CONSENT_ACTIONS, ACTION_ALIASES, RESTORED_ACTIONS,
  normalizeAction, fromV0, prepareCardActions, releaseCardAction, operationId } from './chat_card_actions.js';
export const CARD_TYPES = Object.freeze(['route', 'map', 'event', 'calendar_draft', 'photo_report', 'status', 'info', 'memory']);
export const CARD_STATUSES = Object.freeze(['preparing', 'needs_input', 'ready', 'awaiting_confirmation', 'done', 'unavailable', 'error']);
export const FRESHNESS = Object.freeze(['guncel', 'kayitli', 'tarife', 'dogrulanamadi']);

const MAX_CARDS = 6;
const renderers = new Map();
let titleCount = 0;
let warned = false;
const TYPE_ACTIONS = {
  route: ['use_location', 'type_place', 'expand_map', 'listen', 'open_official', 'share'],
  map: ['expand_map', 'listen', 'open_official', 'share'],
  event: ['save_calendar', 'add_outlook', 'export_ics', 'listen', 'open_official', 'share'],
  calendar_draft: ['change', 'save_calendar', 'add_outlook', 'export_ics', 'cancel', 'open_official'],
  photo_report: ['review_report', 'send', 'confirm_resolved', 'reopen', 'cancel', 'open_official'],
  status: ['listen', 'open_official', 'appeal', 'cancel'], info: ['listen', 'open_official', 'share'],
  memory: ['remember_here', 'remember_always', 'change', 'forget'],
};
const STATUS_ACTIONS = {
  preparing: [], needs_input: ['use_location', 'type_place', 'change'],
  ready: ['expand_map', 'listen', 'save_calendar', 'add_outlook', 'export_ics', 'review_report',
    'open_official', 'change', 'share', 'appeal', 'cancel', 'use_location'],
  awaiting_confirmation: ['remember_here', 'remember_always', 'send', 'save_calendar', 'add_outlook',
    'change', 'forget', 'confirm_resolved', 'reopen', 'cancel', 'appeal', 'share', 'use_location'],
  done: ['expand_map', 'listen', 'open_official', 'export_ics', 'forget', 'add_outlook',
    'confirm_resolved', 'reopen', 'cancel', 'appeal', 'share'],
  unavailable: [], error: [],
};
const STATUS_TR = { preparing: 'Hazırlanıyor', needs_input: 'Bilgi bekliyor', ready: 'Hazır',
  awaiting_confirmation: 'Onayınızı bekliyor', done: 'Tamamlandı', unavailable: 'Kullanılamıyor', error: 'Hata' };
const FRESHNESS_TR = { guncel: 'güncel', kayitli: 'kayıtlı', tarife: 'tarifeye göre',
  dogrulanamadi: 'doğrulanamadı' };

function plain(value, limit) {
  if (typeof value !== 'string') return '';
  return value.replace(/<(script|style|template|iframe|object|svg)\b[^>]*>[\s\S]*?<\/\1\s*>/gi, ' ')
    .replace(/<[^>]*>/g, ' ').replace(/[<>]/g, '').replace(/\s+/g, ' ').trim().slice(0, limit);
}

function cleanBody(value, depth = 0) {
  if (depth > 6) return null;
  if (typeof value === 'string') return plain(value, 600);
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  if (typeof value === 'boolean' || value === null) return value;
  if (Array.isArray(value)) return value.slice(0, 20).map((item) => cleanBody(item, depth + 1));
  if (!value || typeof value !== 'object') return null;
  const clean = {};
  Object.entries(value).slice(0, 20).forEach(([key, item]) => {
    const name = plain(key, 120);
    if (name && name !== '__proto__' && name !== 'constructor' && name !== 'prototype') {
      clean[name] = cleanBody(item, depth + 1);
    }
  });
  return clean;
}

function safeUrl(raw) {
  if (typeof raw !== 'string' || raw.length > 2000 || !/^https:\/\//.test(raw)
    || /[\s\u0000-\u001f<>"'\\]/.test(raw)) return null;
  try {
    const url = new URL(raw);
    return url.protocol === 'https:' && url.hostname && !url.username && !url.password ? raw : null;
  } catch { return null; }
}

function iso(value) {
  return typeof value === 'string' && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(value)
    && Number.isFinite(Date.parse(value))
    ? value : null;
}

function stableId(type, title, linkedId) {
  const data = new TextEncoder().encode(`${type}\0${title}\0${linkedId || ''}`);
  let hash = 0x811c9dc5;
  data.forEach((byte) => { hash = Math.imul(hash ^ byte, 0x01000193) >>> 0; });
  return `card-${type}-${hash.toString(16).padStart(8, '0')}`;
}

function cleanSources(raw, errors) {
  if (!Array.isArray(raw)) {
    if (raw !== undefined && raw !== null) errors.push('sources');
    return [];
  }
  return raw.slice(0, 20).filter((item) => item && typeof item === 'object' && !Array.isArray(item)
    && plain(item.label, 120))
    .map((item) => {
      const url = safeUrl(item.url);
      if (item.url && !url) errors.push('source_url');
      return { label: plain(item.label, 120), url, source_time: iso(item.source_time),
        freshness: FRESHNESS.includes(item.freshness) ? item.freshness : 'dogrulanamadi' };
    });
}

function cleanLinked(raw, errors, legacyId) {
  const legacy = typeof legacyId === 'string' ? /^(event|report|op):(.+)$/.exec(legacyId) : null;
  const source = raw && typeof raw === 'object' && !Array.isArray(raw) ? raw : {};
  const linked = { event_id: plain(source.event_id, 120) || null,
    report_code: plain(source.report_code, 120) || null,
    operation_id: plain(source.operation_id, 120) || null };
  const active = Object.entries(linked).filter(([, value]) => value);
  if (active.length > 1) {
    errors.push('linked');
    Object.keys(linked).forEach((name) => { linked[name] = null; });
  } else if (!active.length && legacy) linked[{ event: 'event_id', report: 'report_code',
    op: 'operation_id' }[legacy[1]]] = plain(legacy[2], 120) || null;
  return linked;
}

function linkedId(linked) {
  if (linked.event_id) return `event:${linked.event_id}`;
  if (linked.report_code) return `report:${linked.report_code}`;
  if (linked.operation_id) return `op:${linked.operation_id}`;
  return null;
}

export function validateCard(raw) {
  const errors = [];
  const candidate = raw?.v === 0 ? fromV0(raw) : raw;
  const data = candidate && typeof candidate === 'object' && !Array.isArray(candidate) ? candidate : {};
  const type = CARD_TYPES.includes(data.type) ? data.type : null;
  const title = plain(data.title, 120);
  if (data.v !== 1) errors.push('v');
  if (!type) errors.push('type');
  if (!title) errors.push('title');
  const sources = cleanSources(data.sources, errors);
  const status = CARD_STATUSES.includes(data.status) ? data.status : 'unavailable';
  if (data.status !== undefined && !CARD_STATUSES.includes(data.status)) errors.push('status');
  const linked = cleanLinked(data.linked, errors, data.linked_id);
  const linkId = linkedId(linked);
  const candidateActions = Array.isArray(data.actions) ? data.actions : [];
  if (data.actions !== undefined && !Array.isArray(data.actions)) errors.push('actions');
  const actions = [];
  for (const rawAction of candidateActions.slice(0, 20)) {
    const action = normalizeAction(rawAction);
    if (!action) {
      const id = typeof rawAction === 'string' ? rawAction : rawAction?.id;
      errors.push(`unknown_action:${plain(id, 80) || 'invalid'}`);
    } else if (!actions.some((item) => item.id === action.id)) {
      if (action.id !== 'open_official' || sources.some((source) => source.url)) actions.push(action);
    }
  }
  const sourceTimes = [iso(data.source_time), ...sources.map((source) => source.source_time)].filter(Boolean);
  sourceTimes.sort((a, b) => Date.parse(a) - Date.parse(b));
  const body = cleanBody(data.body && typeof data.body === 'object' && !Array.isArray(data.body) ? data.body : {});
  if (type === 'map' && Array.isArray(data.body?.points)) body.points = data.body.points.slice(0, 60)
    .map((point) => cleanBody(point, 2));
  if (body.result !== undefined && !CARD_RESULTS.includes(body.result)) { body.result = null; errors.push('result'); }
  const healthMemory = type === 'memory' && body.kind === 'health';
  const sensitive = data.sensitive === true || healthMemory;
  const filteredActions = (!CARD_STATUSES.includes(data.status) ? [] : sensitive
    ? actions.filter((action) => action.kind === 'view' && (!healthMemory || action.id === 'change')) : actions).slice(0, 4);
  const card = { v: 1, id: plain(data.id, 120) || stableId(type || 'unknown', title, linkId),
    conversation_id: plain(data.conversation_id, 120) || null,
    message_id: plain(data.message_id, 120) || null, type: type || 'unknown', status, title,
    body, sources, source_time: sourceTimes[0] || null, linked, linked_id: linkId,
    actions: filteredActions, sensitive };
  return { ok: data.v === 1 && Boolean(type && title), card, errors };
}

export function registerCardType(type, render) {
  if (!CARD_TYPES.includes(type) || typeof render !== 'function') throw new TypeError('Invalid card renderer');
  renderers.set(type, render);
}

export function hasCardType(type) { return renderers.has(type); }

function element(tag, className, content) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (content !== undefined) node.textContent = content;
  return node;
}

function bodyText(card) {
  return typeof card.body?.text === 'string' ? card.body.text : '';
}

function fallback(card) {
  const box = element('div', 'chat-card-fallback');
  box.append(element('p', '', t('ui.cards.fallback', 'Bu kart gösterilemedi; bilgisi aşağıda.')));
  if (bodyText(card)) box.append(element('p', '', bodyText(card)));
  return box;
}

function timeLabel(value) {
  if (!value) return '';
  const time = Date.parse(value);
  if (!Number.isFinite(time)) return '';
  const parts = Object.fromEntries(new Intl.DateTimeFormat('tr-TR', { timeZone: 'Europe/Istanbul',
    day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
    .formatToParts(time).map((part) => [part.type, part.value]));
  return `${parts.day}.${parts.month} ${parts.hour}:${parts.minute}`;
}

function sourcesLine(card, restored = false) {
  const row = element('div', 'chat-card-sources');
  row.append(element('span', 'chat-card-sources-label', t('ui.cards.sources', 'Kaynak')));
  card.sources.forEach((source) => {
    const item = element('span', 'chat-card-source');
    const label = source.label || t('ui.cards.sources', 'Kaynak');
    if (source.url) {
      const link = element('a', '', label);
      link.href = source.url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      item.append(link);
    } else item.append(element('span', '', label));
    const freshnessKey = restored ? 'kayitli' : source.freshness;
    const freshness = t(`ui.cards.freshness_${freshnessKey}`, FRESHNESS_TR[freshnessKey]);
    const stamp = timeLabel(source.source_time) || t('ui.cards.time_unknown', 'zaman bilinmiyor');
    item.append(element('span', 'chat-card-freshness', ` · ${freshness} · ${stamp}`));
    row.append(item);
  });
  return row;
}

function mapHasPoint(card) {
  return Array.isArray(card.body?.points) && card.body.points.some((point) => point
    && Number.isFinite(point.lat) && point.lat >= -90 && point.lat <= 90
    && Number.isFinite(point.lon) && point.lon >= -180 && point.lon <= 180
    && typeof point.label === 'string' && point.label.trim());
}

function allowedActions(card, ctx, normal) {
  if (!normal || card.type === 'memory') return [];
  return card.actions.filter((action) => TYPE_ACTIONS[card.type]?.includes(action.id)
    && STATUS_ACTIONS[card.status]?.includes(action.id)
    && (!ctx.restored || RESTORED_ACTIONS.includes(action.id))
    && (!card.sensitive || (ACTION_KIND[action.id] === 'view' && !action.requires_consent))
    && !(card.sensitive && card.type === 'map' && action.id === 'expand_map')
    && (action.id !== 'expand_map' || card.type !== 'map' || mapHasPoint(card))
    && (!['open_official', 'share'].includes(action.id) || card.sources.some((source) => source.url)));
}

export function appendCard(host, raw, ctx = {}) {
  if (!host?.append) return null;
  const result = validateCard(raw);
  const card = result.card;
  card.message_id = ctx.messageId || card.message_id;
  card.conversation_id = ctx.conversationId || card.conversation_id;
  const article = element('article', 'chat-card');
  article.dataset.cardId = card.id;
  article.dataset.cardType = card.type;
  article.dataset.cardStatus = card.status;
  const title = element('h4', '', card.title || t('ui.cards.fallback', 'Bu kart gösterilemedi; bilgisi aşağıda.'));
  title.id = `chat-card-title-${++titleCount}`;
  article.setAttribute('aria-labelledby', title.id);
  article.append(title);
  article.append(element('span', 'chat-card-status', t(`ui.cards.status_${card.status}`, STATUS_TR[card.status])));
  const outcome = resultLabel(card.body?.result);
  if (outcome) article.append(element('p', 'chat-card-result', outcome));
  let normal = result.ok && renderers.has(card.type);
  if (normal) {
    try {
      const body = renderers.get(card.type)(card, ctx);
      if (!body || typeof body !== 'object' || typeof body.append !== 'function') {
        throw new TypeError('Card renderer must return an Element');
      }
      article.append(body);
    } catch { normal = false; }
  }
  if (!normal) {
    if (!warned) { console.warn('Chat card used its safe fallback.'); warned = true; }
    article.append(fallback(card));
  }
  if (card.sources.length) article.append(sourcesLine(card, ctx.restored));
  const actions = allowedActions(card, ctx, normal);
  if (actions.length) appendActionControls(article, card, actions);
  if (result.errors.some((error) => error.startsWith('unknown_action:'))) {
    article.append(element('p', 'chat-card-action-unsupported', t('ui.cards.action_unsupported',
      'Bu kartta desteklenmeyen bir işlem var; düğme gösterilmedi.')));
    if (!warned) { console.warn('Chat card has an unsupported action.'); warned = true; }
  }
  host.append(article);
  return article;
}

export function renderCards(host, cards, ctx = {}) {
  if (!Array.isArray(cards) || !host?.append) return [];
  const rendered = [];
  const seen = new Set();
  for (const raw of cards.slice(0, 80)) {
    const id = validateCard(raw).card.id;
    if (seen.has(id)) continue;
    seen.add(id);
    const card = appendCard(host, raw, ctx);
    if (card) rendered.push(card);
    if (rendered.length >= MAX_CARDS) break;
  }
  return rendered;
}

registerCardType('info', (card) => element('p', 'chat-card-body', bodyText(card)));
registerCardType('status', (card) => element('p', 'chat-card-body', bodyText(card)
  || t(`ui.cards.status_${card.status}`, STATUS_TR[card.status])));
