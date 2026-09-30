/* v19 (+ 30 Sep: mock_calls.js, no real calls): the Takvim tab's calendar view (calendar_view.js/.css) and P26's citation_card.js and context_chips.js; v18: P00 D2a, chat shell, chat cards and memory in the shell (v17: P00 wave, catalogues and kvkk for the
   E5x-E7x back ends; v16: the home screen's category pills;
   v15: E48's official-path source label in provenance.js; v14: redesigned citizen shell and locally served
   Istanbul panorama; v13: E45's answer_actions.js): bump VERSION when this worker's behavior or shell changes. */
const VERSION = 'v19';
const SHELL_CACHE = 'nabiz-shell-' + VERSION;
const BRIEF_CACHE = 'nabiz-brief-' + VERSION;
const BRIEF_PATH = '/api/brief';
const PAGES = ['/', '/index.html', '/offline.html', '/kvkk.html', '/kolay.html', '/nasil.html'];
const STATIC_PREFIXES = ['/css/', '/js/', '/fonts/', '/icons/', '/images/', '/i18n/'];
const STATIC_FILES = ['/icons.svg', '/manifest.webmanifest'];
const OPERATOR_PREFIX = 'console';
const NETWORK_TIMEOUT_MS = 4000;
const SHELL = [
  '/', '/index.html', '/offline.html', '/kvkk.html', '/manifest.webmanifest',
  '/images/istanbul-panorama.jpg',
  '/css/tokens.css', '/css/base.css', '/css/components.css', '/css/citizen.css', '/css/workspace.css',
  '/css/a11y.css', '/css/map.css', '/css/nearby.css', '/css/voice.css', '/css/share.css',
  '/js/citizen.js', '/js/home.js', '/js/workspace_nav.js', '/js/api.js', '/js/config.js', '/js/cards.js', '/js/chat.js',
  '/js/profile.js', '/js/provenance.js', '/js/history.js', '/js/a11y.js', '/js/disclosure.js',
  '/js/feedback.js', '/js/format.js', '/js/icons.js', '/js/theme.js', '/js/journey.js',
  '/js/nearby.js', '/js/voice.js', '/js/voice_provider.js', '/js/share.js', '/js/compare.js', '/js/map.js', '/js/pwa.js',
  '/icons.svg', '/icons/nabiz.svg',
  '/icons/nabiz-192.png', '/icons/nabiz-512.png', '/icons/nabiz-maskable-512.png',
  // wave 1 (E01-E25): the citizen page's new modules and sheets, and the kolay page
  '/kolay.html', '/css/kolay.css', '/js/kolay.js',
  '/css/agency.css', '/css/answer_card.css', '/css/conversations.css', '/css/easy_read.css', '/css/emergency.css',
  '/css/map_layers.css', '/css/my_stops.css', '/css/personas.css', '/css/progress.css', '/css/service_status.css',
  '/css/trip.css', '/data/glossary_tr.json',
  '/js/agency.js', '/js/answer_card.js', '/js/answer_actions.js', '/js/arrival_confidence.js', '/js/char_counter.js', '/js/conversations-ui.js',
  '/js/conversations.js', '/js/easy_read.js', '/js/easy_read_listen.js', '/js/emergency.js', '/js/map_layers.js',
  '/js/my_stops.js', '/js/personas.js', '/js/pii_badge.js', '/js/service_status.js', '/js/tool_labels.js',
  '/js/transcript.js', '/js/trip.js', '/js/trip_view.js',
  // cloud PRs (B02, B04): the how-it-works page and the handoff card
  '/nasil.html', '/css/how.css', '/js/how.js', '/css/handoff.css', '/js/handoff.js',
  // E06: the page language switch and the Turkish and English catalogues
  '/js/i18n.js', '/js/i18n_text.js', '/i18n/tr.json', '/i18n/en.json',
  // DECISIONS #38: the quota strip, the example account and the follows
  '/css/account.css', '/js/identity.js', '/js/account_view.js', '/js/account.js', '/js/quota_strip.js', '/js/follow.js',
  // DECISIONS #39 (operatör-çeviri): the request card (its /api/requests reads always go to the network)
  '/js/request_status.js', '/css/operator_requests.css',
  // DECISIONS #40: the emergency card's text in every card language, cached so the card opens offline
  '/js/emergency_text.js',
  // DECISIONS #41: the İBB Açık Veri section
  '/js/open_data.js', '/css/open_data.css',
  // DECISIONS #42 (E24): the one-tap lift report under the step-free card
  '/js/report.js', '/css/report.css',
  // DECISIONS #43 (E21): the quick-question chips
  '/js/quick_chips.js', '/css/quick_chips.css',
  // DECISIONS #44 (E23): the citizen's model note (the console receipt strip is a console file, never cached)
  '/js/model_strip.js',
  // E35: the escalator and walkway helpers map_layers.js imports lazily
  '/js/map_equipment.js',
  // E27: report by voice (the E28/E29 console files are console_* and never cached)
  '/js/voice_intent.js', '/js/voice_report.js',
  // E30: libraries and museums open now (the answers come from /api/culture and are never cached)
  '/js/culture.js', '/css/culture.css',
  // P00 D2a (P01): the chat shell's cards; every module index.html, chat.js and citizen.js import is here,
  // or an offline start cannot load the module graph
  '/js/chat_cards.js', '/js/chat_card_actions.js', '/js/chat_card_map.js', '/js/chat_scroll.js', '/css/chat_cards.css',
  // P00 D2a (P02): history and memory (their styles live in conversations.css, already above)
  '/js/conversation_session.js', '/js/data_reset.js', '/js/memory_card.js', '/js/memory_forget.js',
  '/js/memory_store.js', '/js/memory_ui.js',
  // P00 D2a (K): the wave's citizen modules the page now loads, with their views and styles
  '/js/step_voice.js', '/js/step_voice_core.js', '/css/step_voice.css', '/js/photo_report.js', '/css/photo_report.css',
  '/js/family.js', '/js/family_view.js', '/css/family.css', '/js/booking.js', '/css/booking.css',
  '/js/poll.js', '/js/poll_view.js', '/css/poll.css', '/js/notices_center.js', '/css/notices_center.css', '/js/calendar_view.js', '/css/calendar_view.css', '/js/citation_card.js', '/js/context_chips.js', '/js/mock_calls.js',
  '/js/audience.js', '/js/audience_view.js', '/css/audience.css', '/js/visitor.js', '/js/visitor_view.js', '/css/visitor.css',
  '/js/troubleshoot.js', '/js/troubleshoot_view.js', '/css/troubleshoot.css',
  '/js/recovery.js', '/js/recovery_view.js', '/css/recovery.css', '/js/bill.js', '/css/bill.css', '/js/fare.js', '/css/fare.css',
  '/js/disaster_kit.js', '/css/disaster_kit.css', '/js/journey_watch.js', '/css/journey_watch.css',
  '/js/escort.js', '/css/escort.css', '/js/report_timeline.js', '/css/report_timeline.css',
  '/js/outage_watch.js', '/css/outage_watch.css', '/js/ibb_yerleri.js', '/js/ibb_yerleri_view.js', '/css/ibb_yerleri.css',
];

function ruleFor(url, method, mode) {
  if (method !== 'GET') return 'pass';
  const parsed = new URL(url, self.location.origin);
  if (parsed.origin !== self.location.origin) return 'pass';
  const path = parsed.pathname;
  if (path === BRIEF_PATH) return 'brief';
  if (path.startsWith('/api/')) return 'pass';
  if (PAGES.includes(path)) return 'page';
  if (mode === 'navigate') return 'pass';
  const fileName = path.slice(path.lastIndexOf('/') + 1);
  if (fileName.startsWith(OPERATOR_PREFIX)) return 'pass';
  if (STATIC_FILES.includes(path) || STATIC_PREFIXES.some((prefix) => path.startsWith(prefix))) return 'static';
  return 'pass';
}

function markSaved(body, savedAt) {
  const cards = Array.isArray(body && body.cards) ? body.cards.map((card) => {
    const provenance = { ...(card.provenance || {}) };
    if (provenance.observed_at) provenance.mode = 'recorded';
    else {
      provenance.mode = 'unknown';
      provenance.age_s = null;
    }
    return {
      ...card,
      status: card.status === 'ok' ? 'stale' : card.status,
      provenance,
    };
  }) : [];
  return { ...body, cards, saved_at: savedAt, from_device: true };
}

function staleCaches(keys) {
  return keys.filter((key) => key.startsWith('nabiz-') && key !== SHELL_CACHE && key !== BRIEF_CACHE);
}

function briefMissingMessage(onLine) {
  return onLine === false
    ? 'Bağlantı yok ve bu cihazda kayıtlı kart yok.'
    : 'Sunucuya ulaşılamıyor ve bu cihazda kayıtlı kart yok.';
}

function notifyClient(clientId, message) {
  if (!clientId) return;
  self.clients.get(clientId).then((client) => {
    if (client) client.postMessage(message);
  }).catch(() => {});
}

async function networkFirst(request, cacheName, fallback) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), NETWORK_TIMEOUT_MS);
  try {
    const response = await fetch(request, { signal: controller.signal });
    if (response.ok) {
      try { await (await caches.open(cacheName)).put(request, response.clone()); } catch (_) { /* Keep the network response usable. */ }
    }
    return response;
  } catch (_) {
    const cache = await caches.open(cacheName);
    const saved = await cache.match(request, { ignoreSearch: true });
    if (saved) return saved;
    return fallback ? await cache.match(fallback) || new Response('Bağlantı yok. 153', {
      status: 503,
      headers: { 'Content-Type': 'text/plain; charset=utf-8' },
    }) : Promise.reject(_);
  } finally {
    clearTimeout(timeout);
  }
}

async function briefResponse(request, event) {
  try {
    const response = await fetch(request);
    if (!response.ok) return response;
    try {
      const savedAt = new Date().toISOString();
      const headers = new Headers(response.headers);
      headers.set('X-Nabiz-Saved-At', savedAt);
      const stored = new Response(await response.clone().arrayBuffer(), {
        status: response.status,
        statusText: response.statusText,
        headers,
      });
      await (await caches.open(BRIEF_CACHE)).put(BRIEF_PATH, stored);
      notifyClient(event.clientId, { type: 'nabiz:brief', source: 'network', saved_at: null });
    } catch (_) { /* A cache failure does not replace a valid response. */ }
    return response;
  } catch (_) {
    let saved;
    try { saved = await (await caches.open(BRIEF_CACHE)).match(BRIEF_PATH); } catch (_) { saved = null; }
    if (!saved) return new Response(JSON.stringify({ error: 'offline', message: briefMissingMessage(self.navigator.onLine) }), {
      status: 503,
      headers: { 'Content-Type': 'application/json' },
    });
    try {
      const savedAt = saved.headers.get('X-Nabiz-Saved-At');
      const body = markSaved(await saved.json(), savedAt);
      notifyClient(event.clientId, { type: 'nabiz:brief', source: 'saved', saved_at: savedAt });
      return new Response(JSON.stringify(body), {
        headers: { 'Content-Type': 'application/json', 'X-Nabiz-Saved-At': savedAt || '' },
      });
    } catch (_) {
      return new Response(JSON.stringify({ error: 'offline', message: briefMissingMessage(self.navigator.onLine) }), {
        status: 503,
        headers: { 'Content-Type': 'application/json' },
      });
    }
  }
}

if (typeof self !== 'undefined' && self.addEventListener) {
  self.addEventListener('install', (event) => {
    event.waitUntil((async () => {
      const cache = await caches.open(SHELL_CACHE);
      await Promise.all(SHELL.map((path) => cache.add(path).catch(() => {})));
      await self.skipWaiting();
    })());
  });
  self.addEventListener('activate', (event) => {
    event.waitUntil((async () => {
      const keys = await caches.keys();
      await Promise.all(staleCaches(keys).map((key) => caches.delete(key)));
      await self.clients.claim();
    })());
  });
  self.addEventListener('fetch', (event) => {
    const { request } = event;
    const rule = ruleFor(request.url, request.method, request.mode);
    if (rule === 'page') event.respondWith(networkFirst(request, SHELL_CACHE, '/offline.html'));
    else if (rule === 'static') event.respondWith(networkFirst(request, SHELL_CACHE, null));
    else if (rule === 'brief') event.respondWith(briefResponse(request, event));
  });
}

if (typeof self !== 'undefined') self.nabizSw = { VERSION, ruleFor, markSaved, staleCaches, briefMissingMessage, SHELL };
