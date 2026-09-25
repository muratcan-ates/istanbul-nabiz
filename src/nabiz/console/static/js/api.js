/* How the pages talk to their server: get, post and an event stream. A failure becomes an Error
 * carrying the HTTP status and a Turkish message, never a stack trace on screen.
 *
 * In mock mode (js/config.js) every /api path maps to a JSON file under /mock/, and a little session
 * state (decisions taken, the simulated signal) makes the demo flow read naturally. */

import { API_BASE, isMock } from './config.js';

const MOCK = isMock(window.location.search);
const OFFLINE = 'Sunucuya ulaşılamadı. Bağlantınızı kontrol edip tekrar deneyin.';

function failure(status, body) {
  const error = new Error((body && body.message) || (body && body.detail) || `İstek başarısız (HTTP ${status}).`);
  error.status = status;
  return error;
}

async function readJson(response) {
  try { return await response.json(); } catch (err) { return null; }
}

/* ---- mock mapping ---------------------------------------------------------------------- */
const mockState = { decided: {}, simulated: false, adopted: new Set() };

function mockFile(method, path) {
  const p = path.replace(/^\/api\//, '');
  const decision = /^console\/decisions\/([^/]+)$/.exec(p);
  if (method === 'POST') {
    if (decision) return 'console-decision-post';
    if (/^console\/rule-drafts\/[^/]+\/adopt$/.test(p)) return 'console-adopt';
    if (p === 'console/simulate') return 'console-simulate';
    return null;
  }
  if (decision) return `console-decision-${decision[1]}`;
  if (/^console\/ledger\/[^/]+\/trace$/.test(p)) return 'console-trace';
  return p.replace(/\//g, '-');
}

async function mockJson(name) {
  const response = await fetch(`/mock/${name}.json`, { headers: { Accept: 'application/json' } });
  if (!response.ok) throw failure(response.status, null);
  return response.json();
}

async function mockGet(path) {
  const name = mockFile('GET', path);
  let body;
  try {
    body = await mockJson(name);
  } catch (err) {
    if (err.status === 404 && name.startsWith('console-decision-')) body = await mockJson('console-decision-default');
    else throw err;
  }
  if (path === '/api/console/queue') {
    body.items = body.items
      .filter((item) => mockState.simulated || item.signal_id !== 'sig-006')
      .map((item) => (mockState.decided[item.signal_id] ? { ...item, status: mockState.decided[item.signal_id] } : item));
  }
  if (path === '/api/console/rule-drafts') body.drafts = body.drafts.filter((d) => !mockState.adopted.has(d.draft_id));
  return body;
}

async function mockPost(path, payload) {
  const name = mockFile('POST', path);
  if (!name) throw failure(404, null);
  const body = await mockJson(name);
  const decision = /^\/api\/console\/decisions\/([^/]+)$/.exec(path);
  if (decision) {
    const status = { approve: 'approved', edit: 'approved', reject: 'rejected', defer: 'deferred' }[payload.action] || 'approved';
    mockState.decided[decision[1]] = status;
    return { ...body, status };
  }
  if (path === '/api/console/simulate') mockState.simulated = true;
  const adopt = /^\/api\/console\/rule-drafts\/([^/]+)\/adopt$/.exec(path);
  if (adopt) mockState.adopted.add(adopt[1]);
  return body;
}

/* ---- real endpoints -------------------------------------------------------------------- */
function url(path, params) {
  const target = new URL(API_BASE + path, window.location.origin);
  Object.entries(params || {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') target.searchParams.set(k, v);
  });
  return target;
}

async function get(path, params, signal) {
  if (MOCK) return mockGet(path);
  let response;
  try {
    response = await fetch(url(path, params), { headers: { Accept: 'application/json' }, signal });
  } catch (err) {
    if (signal && signal.aborted) throw err;
    throw failure(0, { message: OFFLINE });
  }
  const body = await readJson(response);
  if (!response.ok) throw failure(response.status, body);
  return body;
}

async function post(path, payload) {
  if (MOCK) return mockPost(path, payload);
  let response;
  try {
    response = await fetch(url(path), {
      method: 'POST',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    });
  } catch (err) {
    throw failure(0, { message: OFFLINE });
  }
  const body = await readJson(response);
  if (!response.ok) throw failure(response.status, body);
  return body;
}

/* ---- server-sent events over a POST ---------------------------------------------------- */
/** One "event: x\ndata: {...}" block, as {event, data}; data parsed as JSON when it is JSON. */
function parseBlock(block) {
  let event = 'message';
  const lines = [];
  for (const line of block.split(/\r?\n/)) {
    if (line.startsWith('event:')) event = line.slice(6).trim();
    else if (line.startsWith('data:')) lines.push(line.slice(5).replace(/^ /, ''));
  }
  const raw = lines.join('\n');
  let data = raw;
  try { data = JSON.parse(raw); } catch (err) { /* a bare string */ }
  return { event, data };
}

const sleep = (ms) => new Promise((resolve) => { setTimeout(resolve, ms); });

/** The mock replays a recorded stream from /mock/chat*.json, paced so the streaming UI is exercised. */
async function mockStream(payload, onEvent) {
  const text = String(payload.message || '').toLocaleLowerCase('tr');
  let name = 'chat';
  if (/ücret|ceza|hak|sağlık|indirim|fiyat|bilet|para/.test(text)) name = 'chat-refused';
  else if (/asansör|adımsız|tekerlekli|bebek/.test(text)) name = 'chat-memory';
  const body = await mockJson(name);
  for (const evt of body.events) {
    onEvent(evt.event, evt.data);
    await sleep(evt.event === 'token' ? 35 : 250);
  }
}

/**
 * POST `payload` and read the text/event-stream reply, calling onEvent(name, data) per event. The
 * stream ends when the server closes it or `signal` aborts. EventSource cannot POST, so this reads
 * the body by hand; a block ends at a blank line.
 */
async function stream(path, payload, onEvent, signal) {
  if (MOCK) return mockStream(payload, onEvent);
  let response;
  try {
    response = await fetch(url(path), {
      method: 'POST',
      headers: { Accept: 'text/event-stream', 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
      signal,
    });
  } catch (err) {
    if (signal && signal.aborted) throw err;
    throw failure(0, { message: OFFLINE });
  }
  if (!response.ok) throw failure(response.status, await readJson(response));
  if (!response.body) throw failure(0, { message: 'Bu tarayıcı akışlı yanıtı desteklemiyor.' });
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let cut = buffer.indexOf('\n\n');
    while (cut >= 0) {
      const block = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      if (block.trim()) { const { event, data } = parseBlock(block); onEvent(event, data); }
      cut = buffer.indexOf('\n\n');
    }
  }
  if (buffer.trim()) { const { event, data } = parseBlock(buffer); onEvent(event, data); }
  return undefined;
}

export { MOCK, get, post, stream, parseBlock };
