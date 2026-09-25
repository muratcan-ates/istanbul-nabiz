/* Question to endpoint to answer. Each journey fetches; a pure renderer in cards/ builds the whole
 * answer as one string with its map points and its sentence; run() writes #results once, hands
 * the points to the map and says the sentence in #answer-status. A newer question aborts the one
 * in flight, so a slow answer can never overwrite a later one. */

import { api } from './api.js';
import { ageSentence } from './provenance.js';
import { parkingAnswer } from './cards/parking.js';
import { arrivalsAnswer, busAnswer } from './cards/transit.js';
import { metroAnswer, stationAnswer } from './cards/metro.js';
import { airAnswer, trafficAnswer } from './cards/environment.js';
import { routeAnswer } from './cards/route.js';
import { stopsAnswer, placesAnswer, freshnessAnswer } from './cards/places.js';
import { callout, errorCard, errorTitle } from './cards/sheet.js';
import { showOnMap, highlightMarker, showMarker } from './map.js';
import { loadReliability } from './reliability.js';
import { refreshFreshness } from './freshness.js';
import { recentTraffic } from './hero.js';
import { announce, loading } from './status.js';
import { scrollToElement } from './motion.js';

const results = document.querySelector('#results');
let controller = null;
let last = null;
let observer = null;

/* `get` is api() bound to this run's abort signal. */
const JOURNEYS = {
  parking: async ({ place }, get) => parkingAnswer(await get('/api/parking', { place, radius_km: 1.5, min_free: 1 })),

  async bus({ line }, get) {
    const res = await get('/api/buses', { line });
    loadReliability(res.data.line_code);
    return busAnswer(res);
  },

  async arrivals({ line, stop }, get) {
    const res = await get('/api/arrivals', { line, stop, limit: 3 });
    loadReliability(res.data.line_code);
    return arrivalsAnswer(res, stop);
  },

  metro: async ({ line }, get) => metroAnswer(await get('/api/metro', { line }), line),
  station: async ({ name }, get) => stationAnswer(await get('/api/metro/station', { name })),

  async air({ place }, get) {
    // Both calls at once (FE-OPT-4); a failed forecast leaves the reading standing.
    const [now, forecast] = await Promise.allSettled([get('/api/air', { place }), get('/api/air/forecast', { place, hours: 6 })]);
    if (now.status === 'rejected') throw now.reason;
    return airAnswer(now.value, forecast.value || null, forecast.reason);
  },

  async traffic(_, get) {
    // Both halves at once; the 24-hour half is the hero's own payload when it is under a minute old.
    const [now, day] = await Promise.all([
      get('/api/traffic', { window: 'now' }),
      recentTraffic() || get('/api/traffic', { window: '24h' }).catch(() => null),
    ]);
    return trafficAnswer(now, day, Date.now());
  },

  stops: async ({ q }, get) => stopsAnswer(await get('/api/stops', { q })),
  places: async ({ q }, get) => placesAnswer(await get('/api/places', { q })),
  freshness: async (_, get) => freshnessAnswer(await get('/api/freshness')),

  /* A comparison of modes, never navigation; the server's disclaimer is shown verbatim. */
  async route({ from, to }, get) {
    if (!from || !to) {
      const text = 'Başlangıcı ve varışı şöyle yazın: Kadıköy’den Taksim’e nasıl giderim. Semt, meydan ya da istasyon adı kullanın.';
      return { html: callout(text), say: text };
    }
    return routeAnswer(await get('/api/route', { from, to }));
  },
};

/** A failure is an answer too. When İBB or the network is the one failing, the card lists how old
 * the last thing we knew is, from /api/freshness (cache statistics, never İBB). */
async function errorAnswer(err) {
  let sources = null;
  if ([0, 429, 503].includes(err.status || 0)) {
    try {
      sources = (await api('/api/freshness')).data.sources;
    } catch (ignored) {
      sources = null; // the server itself is unreachable: the card says so without the list
    }
  }
  return { html: errorCard(err, sources), say: `${errorTitle(err)}.` };
}

/* A drawing needs its measured width (drawn before layout it sits at x 0), so an answer leaves an
 * empty [data-draw] host that this fills, and fills again after a resize, until the next answer. */
function observe(draw) {
  const hosts = [...results.querySelectorAll('[data-draw]')].filter((el) => draw[el.dataset.draw]);
  if (!hosts.length) return;
  const widths = new WeakMap();
  observer = new ResizeObserver((entries) => entries.forEach(({ target, contentRect }) => {
    const width = Math.round(contentRect.width);
    if (!width || widths.get(target) === width) return;
    widths.set(target, width);
    target.innerHTML = draw[target.dataset.draw](width, Math.round(contentRect.height), Date.now());
  }));
  hosts.forEach((el) => observer.observe(el));
}

function render({ html, points = [], draw = {}, say, prov }) {
  if (observer) observer.disconnect();
  observer = null;
  loading(null);
  results.innerHTML = `<div>${html}</div>`;
  showOnMap(points);
  observe(draw);
  announce(prov ? `${say} ${ageSentence(prov)}` : say);
  // On a phone the answer can land below the fold; bring its head up, without moving focus.
  const top = results.firstElementChild;
  if (top.getBoundingClientRect().top > window.innerHeight) scrollToElement(top, 'start');
}

async function run(journey, args) {
  if (controller) controller.abort();
  const ctl = new AbortController();
  controller = ctl;
  last = [journey, args];
  loadReliability(null);
  loading(journey);
  let answer;
  try {
    if (!JOURNEYS[journey]) throw new Error('Bu soruyu nasıl yanıtlayacağımı bilmiyorum.');
    answer = await JOURNEYS[journey](args || {}, (path, params) => api(path, params, ctl.signal));
  } catch (err) {
    if (ctl.signal.aborted) return;
    answer = await errorAnswer(err);
  }
  if (ctl.signal.aborted) return;
  render(answer);
  refreshFreshness(null); // the answer read a source; show it now, not at the next poll
}

/** The one delegated listener of the answer region (main.js): retry, "Haritada göster", and a
 * press anywhere on a row lifts its marker. */
function onResultsClick(event) {
  const target = event.target;
  if (target.closest('[data-retry]')) { if (last) run(...last); return; }
  const mapButton = target.closest('[data-map]');
  if (mapButton) { showMarker(mapButton.dataset.map); return; }
  const card = target.closest('.card');
  if (card) highlightMarker(card.id);
}

export { run, onResultsClick };
