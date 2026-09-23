/* Question to endpoint to renderer. Each journey fetches, builds its answer as one string and
 * writes the results region once, then hands the points to the map. */

import { api } from './api.js';
import { esc, num, int, has, shortAge } from './format.js';
import { icon } from './icons.js';
import { sourceLabel } from './provenance.js';
import { nextCardId, resultHead, cards, simpleCard } from './cards/shell.js';
import { parkingCard } from './cards/parking.js';
import { arrivalCard, diagnosticsCard, busCard } from './cards/transit.js';
import { metroCard, metroClearCard, stationCard } from './cards/metro.js';
import { airCard, forecastCard, trafficCard } from './cards/environment.js';
import { routeCard } from './cards/route.js';
import { showError } from './errors.js';
import { showOnMap, highlightMarker } from './map.js';
import { loadReliability } from './reliability.js';
import { refreshFreshness } from './freshness.js';

const $ = (sel) => document.querySelector(sel);
const results = $('#results');

/* A cold İSPARK answer costs several detail calls at the gateway's six-second spacing, so
 * "nothing happened" is a real user experience here. Say we are working, and say why.
 * aria-disabled, not disabled: a disabled "Sor" drops keyboard focus to <body>. */
function setBusy(on) {
  results.setAttribute('aria-busy', on ? 'true' : 'false');
  const submit = $('#ask-submit');
  if (submit) submit.setAttribute('aria-disabled', on ? 'true' : 'false');
  if (on) {
    results.innerHTML = `<p class="loading-label">${icon('refresh')} İBB uçlarından okunuyor. İlk sorgu birkaç saniye sürebilir.</p>
      <div class="skeleton"><div class="sk-card"></div><div class="sk-card"></div></div>`;
  }
}

function render(html, points) {
  results.innerHTML = html;
  showOnMap(points || []);
  bindCards();
}

function bindCards() {
  document.querySelectorAll('#results .card').forEach((el) => {
    el.addEventListener('click', () => highlightMarker(el.id));
  });
}

const JOURNEYS = {
  async parking({ place }) {
    const res = await api('/api/parking', { place, radius_km: 1.5, min_free: 1 });
    const parks = res.data.parks || [];
    const ids = parks.map(() => nextCardId());
    render(
      resultHead(`${res.data.near} çevresinde otopark`, `${res.data.count} sonuç · ${num(res.data.radius_km)} km`, res.provenance, res.note)
      + (parks.length
        ? cards(parks.map((p, i) => parkingCard(p, res.provenance, ids[i])).join(''), true)
        : `<p class="callout">Bu yarıçapta boş yeri olan açık otopark bulunamadı.</p>`),
      parks.map((p, i) => ({ lat: p.lat, lon: p.lon, kind: 'park', card: ids[i], label: `${p.name} · ${has(p.empty) ? `${p.empty} boş` : 'boş yer bilinmiyor'}` })),
    );
  },

  async bus({ line }) {
    const res = await api('/api/buses', { line });
    const buses = res.data.buses || [];
    const shown = buses.slice(0, 12);
    const ids = shown.map(() => nextCardId());
    const hint = 'Varış tahmini için durak adı ekleyin, örneğin: “500T Şifa Sondurak”.';
    render(
      resultHead(`${res.data.line_code} hattı canlı araçlar`, `${res.data.count} araç`, res.provenance, res.note ? `${res.note} ${hint}` : hint)
      + `<p class="callout">Plaka hiçbir zaman saklanmaz ve gösterilmez; araçlar yalnızca kapı numarasıyla anılır (KVKK).</p>`
      + cards(shown.map((b, i) => busCard(b, res.provenance, ids[i])).join(''), true),
      shown.map((b, i) => ({ lat: b.lat, lon: b.lon, kind: 'bus', card: ids[i], label: `${b.door_no} → ${b.direction || ''}` })),
    );
    loadReliability(res.data.line_code);
  },

  async arrivals({ line, stop }) {
    const res = await api('/api/arrivals', { line, stop, limit: 3 });
    const arrivals = res.data.arrivals || [];
    const stopInfo = res.data.stop || {};
    const ids = arrivals.map(() => nextCardId());
    const stopId = nextCardId();
    const body = arrivals.length
      ? cards(arrivals.map((a, i) => arrivalCard(a, res.provenance, ids[i])).join(''), true)
      : cards(diagnosticsCard(res.data.diagnostics, res.provenance, nextCardId()));
    render(
      resultHead(`${res.data.line_code} · ${stopInfo.name || stop}`, arrivals.length ? `${arrivals.length} yaklaşan araç` : 'yaklaşan araç yok', res.provenance, res.note)
      + body
      + (res.data.disclaimer ? `<p class="hint">${esc(res.data.disclaimer)}</p>` : ''),
      [{ lat: stopInfo.lat, lon: stopInfo.lon, kind: 'station', card: stopId, label: stopInfo.name || stop }],
    );
    loadReliability(res.data.line_code);
  },

  async metro({ line }) {
    const res = await api('/api/metro', { line });
    const all = res.data.lines || [];
    const wanted = line ? all.filter((l) => (l.line_name || '').toLocaleUpperCase('tr') === line.toLocaleUpperCase('tr')) : all;
    const list = line ? wanted : all;
    render(
      resultHead(line ? `${line} servis durumu` : 'Metro servis duyuruları', `${list.length} duyuru`, res.provenance, res.note)
      + (list.length
        ? cards(list.map((l) => metroCard(l, res.provenance, nextCardId())).join(''))
        : cards(metroClearCard(line, res.provenance, nextCardId())))
      + (line && !wanted.length && all.length
        ? `<p class="callout">Şu anda duyurusu olan hatlar: ${esc(all.map((l) => l.line_name).join(', '))}.</p>` : ''),
      [],
    );
  },

  async station({ name }) {
    const res = await api('/api/metro/station', { name });
    const stations = res.data.stations || [];
    const ids = stations.map(() => nextCardId());
    render(
      resultHead(`${res.data.query} istasyonu`, `${res.data.count} eşleşme`, res.provenance, res.note)
      + (stations.length
        ? cards(stations.map((s, i) => stationCard(s, res.provenance, ids[i])).join(''), true)
        : '<p class="callout">Bu adla bir metro istasyonu bulunamadı.</p>'),
      stations.map((s, i) => ({ lat: s.lat, lon: s.lon, kind: 'station', card: ids[i], label: `${s.name} (${s.line_name})` })),
    );
  },

  async air({ place }) {
    const now = await api('/api/air', { place });
    const airId = nextCardId();
    let forecastHtml = '';
    try {
      const fc = await api('/api/air/forecast', { place, hours: 6 });
      forecastHtml = forecastCard(fc.data, fc.provenance, nextCardId());
    } catch (err) {
      forecastHtml = `<p class="note">Tahmin alınamadı: ${esc(err.message)}</p>`;
    }
    const st = now.data.station || {};
    render(
      resultHead(`${now.data.place} hava kalitesi`, st.name ? `${st.name} istasyonu` : '', now.provenance, now.note)
      + cards(airCard(now.data, now.provenance, airId) + forecastHtml, true),
      [{ lat: st.lat, lon: st.lon, kind: 'air', card: airId, label: `${st.name} ölçüm istasyonu` }],
    );
  },

  async traffic() {
    const res = await api('/api/traffic', { window: 'now' });
    let extra = {};
    try {
      const hist = await api('/api/traffic', { window: '24h' });
      extra = {
        history: hist.data.history || [],
        same_hour_yesterday: hist.data.same_hour_yesterday,
        delta: hist.data.delta,
        description: res.data.description || hist.data.description,
      };
    } catch (err) {
      extra = {};
    }
    render(
      resultHead('Trafik', '24 saatlik kayıt', res.provenance, res.note)
      + cards(trafficCard({ ...res.data, ...extra }, res.provenance, nextCardId())),
      [],
    );
  },

  async stops({ q }) {
    const res = await api('/api/stops', { q });
    const stops = res.data.stops || [];
    const ids = stops.map(() => nextCardId());
    render(
      resultHead(`“${res.data.query}” durakları`, `${res.data.count} durak`, res.provenance, res.note)
      + (stops.length
        ? cards(stops.map((s, i) => simpleCard({
          id: ids[i], kind: 'station', icon: 'stop', prov: res.provenance,
          title: s.name || s.stop_code, sub: s.description || '',
          meta: [`durak kodu ${s.stop_code}`, s.stop_id ? `stop_id ${s.stop_id}` : null],
        })).join(''), true)
        : '<p class="callout">Bu adla bir durak bulunamadı.</p>')
      + '<p class="hint">Varış tahmini için hat kodu ekleyin, örneğin: <em>500T Şifa Sondurak</em>.</p>',
      stops.map((s, i) => ({ lat: s.lat, lon: s.lon, kind: 'station', card: ids[i], label: s.name || s.stop_code })),
    );
  },

  async places({ q }) {
    const res = await api('/api/places', { q });
    const matches = res.data.matches || [];
    const ids = matches.map(() => nextCardId());
    render(
      resultHead(`“${res.data.query}” için yerler`, `${matches.length} eşleşme`, res.provenance,
        res.note || 'Otopark, otobüs, metro veya hava kalitesi sormak için soruya bir anahtar kelime ekleyin.')
      + (matches.length
        ? cards(matches.map((p, i) => simpleCard({
          id: ids[i], kind: 'place', icon: 'pin', prov: res.provenance,
          title: p.label || p.name, sub: p.district || '', meta: [p.kind],
        })).join(''), true)
        : '<p class="callout">Bu adla bir yer bulunamadı. Semt, meydan ya da istasyon adı deneyin.</p>'),
      matches.map((p, i) => ({ lat: p.lat, lon: p.lon, kind: 'place', card: ids[i], label: p.label || p.name })),
    );
  },

  async freshness() {
    const res = await api('/api/freshness');
    const sources = res.data.sources || {};
    const items = Object.entries(sources).map(([name, s]) => simpleCard({
      id: nextCardId(), kind: '', icon: 'clock', prov: res.provenance,
      title: sourceLabel(name), sub: s.healthy ? 'sağlıklı' : 'sorunlu',
      meta: [
        `veri yaşı: ${shortAge(s.data_age_seconds)}`,
        `son okuma: ${shortAge(s.age_seconds)} önce`,
        `önbellek isabeti: ${int(s.hits)}`,
        `ıskalama: ${int(s.misses)}`,
        `bayat servis: ${int(s.stale_served)}`,
        `hata: ${int(s.errors)}`,
        s.last_error ? `son hata: ${s.last_error}` : null,
      ],
    }));
    const budget = res.data.request_budget_remaining || {};
    render(
      resultHead('Veri tazeliği', `${items.length} kaynak`, res.provenance, res.note)
      + (Object.keys(budget).length
        ? `<p class="callout">Kalan istek bütçesi: ${esc(Object.entries(budget).map(([k, v]) => `${k} ${v}`).join(', '))}. İETT’nin saatlik 100 sınırının altında, 80’de duruyoruz.</p>`
        : '')
      + (items.length ? cards(items.join(''), true) : '<p class="callout">Henüz hiçbir kaynak sorgulanmadı.</p>'),
      [],
    );
  },

  /* A comparison of modes, never navigation — the server's disclaimer is shown verbatim. */
  async route({ from, to }) {
    if (!from || !to) {
      render('<p class="callout">Başlangıcı ve varışı şöyle yazın: <em>Kadıköy’den Taksim’e nasıl giderim</em>. '
        + 'Semt, meydan ya da istasyon adı kullanın.</p>', []);
      return;
    }
    const res = await api('/api/route', { from, to });
    const d = res.data;
    const options = d.options || [];
    const ids = options.map(() => nextCardId());
    const ends = [
      { lat: d.origin.lat, lon: d.origin.lon, kind: 'place', card: ids[0], label: d.origin.name },
      { lat: d.destination.lat, lon: d.destination.lon, kind: 'place', card: ids[0], label: d.destination.name },
    ];
    render(
      resultHead(`${d.origin.name} → ${d.destination.name}`, `${options.length} seçenek`, res.provenance, res.note)
      + (options.length
        ? cards(options.map((o, i) => routeCard(o, d, res.provenance, ids[i])).join(''), true)
        : '<p class="callout">Bu iki nokta arasında hiçbir seçenek hesaplanamadı.</p>')
      + (d.disclaimer ? `<p class="hint">${esc(d.disclaimer)}</p>` : ''),
      ends,
    );
  },
};

async function run(journey, args) {
  const handler = JOURNEYS[journey];
  if (!handler) { await showError(new Error('Bu soruyu nasıl yanıtlayacağımı bilmiyorum.')); return; }
  setBusy(true);
  try {
    await handler(args || {});
  } catch (err) {
    await showError(err);
  } finally {
    setBusy(false);
    refreshFreshness(null); // the answer read a source; show it now, not at the next poll
  }
}

export { run };
