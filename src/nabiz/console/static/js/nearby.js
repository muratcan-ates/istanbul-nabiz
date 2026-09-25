/* Yakınımda: location permission is requested only after the visitor presses the button. The
 * browser keeps the current coordinate in memory; its cache contains nearby results only. */

import { MOCK, get, post } from './api.js';
import { citations, stamp } from './provenance.js';
import { esc, shortAge } from './format.js';

const CACHE_KEY = 'nabiz.nearby.v1';
const MODE_LABEL = { drive: 'Araba', metro: 'Metro', bus: 'Otobüs', walk: 'Yürüyüş' };
let currentPosition = null;

const mount = document.querySelector('#yakinimda-mount');

if (mount) {
  const sheet = document.createElement('link');
  sheet.rel = 'stylesheet';
  sheet.href = '/css/nearby.css';
  document.head.append(sheet);
  mount.setAttribute('aria-labelledby', 'nearby-title');
  mount.innerHTML = '<div class="section-head"><h2 id="nearby-title">Yakınımda</h2>'
    + '<span class="section-note">Konum izni yalnızca bu istek için kullanılır</span></div>'
    + '<p class="nearby-intro">En yakın durakları ve seçenekleri görmek için konumunuzu paylaşın.</p>'
    + '<button type="button" class="btn btn-primary" id="nearby-locate">Konumumu paylaş</button>'
    + '<p class="nearby-status" id="nearby-status" role="status" aria-live="polite"></p>'
    + '<div class="nearby-grid" id="nearby-cards"></div>';
  boot();
}

function provenance(data, key) {
  return data && data[key] ? data[key] : { source: 'bilinmiyor', url: null, observed_at: null, age_s: null, mode: 'unknown' };
}

function distanceText(value) {
  return Number.isFinite(value) ? `${Math.round(value)} m` : 'Mesafe doğrulanamadı';
}

function nearbyCard({ kind, name, distance, details, source, lat, lon, planned = false }) {
  const actionable = Number.isFinite(lat) && Number.isFinite(lon) && !MOCK && !planned;
  const button = `<button type="button" class="btn nearby-go" data-nearby-journey data-lat="${esc(String(lat ?? ''))}" `
    + `data-lon="${esc(String(lon ?? ''))}" data-name="${esc(name || '')}"${actionable ? '' : ' disabled'}>`
    + 'Buraya nasıl giderim</button>';
  return `<article class="nearby-card${planned ? ' is-planned' : ''}">`
    + `<p class="nearby-kind">${esc(kind)}</p><h3>${esc(name)}</h3>`
    + `<p class="nearby-distance">${distanceText(distance)}</p>`
    + (details ? `<p class="nearby-detail">${esc(details)}</p>` : '')
    + (source ? stamp(source) : '<span class="stamp is-unknown">Veri yaşı bilinmiyor</span>')
    + button + '</article>';
}

function statusCard(kind, message, source) {
  return `<article class="nearby-card is-empty"><p class="nearby-kind">${esc(kind)}</p>`
    + `<p>${esc(message)}</p>${source ? stamp(source) : ''}</article>`;
}

function render(data) {
  const cards = [];
  const stopsProvenance = provenance(data, 'stops_provenance');
  if ((data.stops || []).length) {
    for (const stop of data.stops) {
      cards.push(nearbyCard({
        kind: 'Otobüs durağı', name: stop.name || 'Durak', distance: stop.distance_m,
        source: stop.provenance || stopsProvenance, lat: stop.lat, lon: stop.lon,
      }));
    }
  } else {
    cards.push(statusCard('Otobüs durakları', stopsProvenance.mode === 'unknown'
      ? 'Durak verisi doğrulanamadı.' : 'Yakında durak bulunamadı.', stopsProvenance));
  }

  const metroProvenance = provenance(data, 'metro_provenance');
  if (data.metro) {
    const lift = { working: 'İBB kaydında asansör arızası yok', out_of_service: 'Asansör kullanılamıyor', unknown: 'Asansör durumu doğrulanamadı' };
    const line = data.metro.line ? ` · ${data.metro.line}` : '';
    cards.push(nearbyCard({
      kind: `Metro istasyonu${line}`, name: data.metro.station || 'Metro', distance: data.metro.distance_m,
      details: lift[data.metro.lift_status] || lift.unknown, source: data.metro.provenance || metroProvenance,
      lat: data.metro.lat, lon: data.metro.lon,
    }));
  } else {
    cards.push(statusCard('Metro istasyonu', metroProvenance.mode === 'unknown'
      ? 'Metro verisi doğrulanamadı.' : 'Yakında istasyon bulunamadı.', metroProvenance));
  }

  const parkingProvenance = provenance(data, 'parking_provenance');
  if (data.parking) {
    cards.push(nearbyCard({
      kind: 'İSPARK', name: data.parking.name || 'İSPARK otoparkı', distance: data.parking.distance_m,
      details: Number.isFinite(data.parking.empty) ? `${data.parking.empty} boş yer` : 'Boş yer sayısı doğrulanamadı',
      source: data.parking.provenance || parkingProvenance, lat: data.parking.lat, lon: data.parking.lon,
    }));
  } else {
    cards.push(statusCard('İSPARK', parkingProvenance.mode === 'unknown'
      ? 'Otopark verisi doğrulanamadı.' : 'Yakında boş yeri olan otopark bulunamadı.', parkingProvenance));
  }

  const charging = data.charging || { status: 'planlanan' };
  cards.push(nearbyCard({
    kind: 'Akülü sandalye şarjı', name: charging.name || 'Şarj noktası',
    distance: charging.distance_m, details: charging.status === 'planlanan'
      ? 'Yakında doğrulanmış nokta verisi yok. Veri eklenmesi planlanıyor.' : '',
    source: charging.provenance, lat: charging.lat, lon: charging.lon, planned: charging.status === 'planlanan',
  }));
  document.querySelector('#nearby-cards').innerHTML = cards.join('');
}

function cached() {
  try {
    const value = JSON.parse(localStorage.getItem(CACHE_KEY) || 'null');
    return value && value.data && Number.isFinite(value.saved_at) ? value : null;
  } catch { return null; }
}

function remember(data) {
  try { localStorage.setItem(CACHE_KEY, JSON.stringify({ data, saved_at: Date.now() })); } catch { /* storage may be disabled */ }
}

function showCached(message) {
  const saved = cached();
  const status = document.querySelector('#nearby-status');
  if (!saved) {
    status.textContent = `${message} Son bilinen sonuç bulunmuyor.`;
    document.querySelector('#nearby-cards').innerHTML = statusCard('Yakınımda', message, null);
    return;
  }
  render(saved.data);
  const age = shortAge(Math.max(0, (Date.now() - saved.saved_at) / 1000));
  status.textContent = `${message} Bu cihazdaki son sonuçlar ${age} önce alındı.`;
}

function needs() {
  if (!document.querySelector('#profile-consent')?.checked) return '';
  return [...document.querySelectorAll('#profile-form input[name="needs"]:checked')].map((item) => item.value).join(',');
}

function position() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) { reject(new Error('Tarayıcı konum paylaşımını desteklemiyor.')); return; }
    navigator.geolocation.getCurrentPosition(resolve, reject, { enableHighAccuracy: false, timeout: 10000, maximumAge: 30000 });
  });
}

function hasSourceData(data) {
  return ['stops_provenance', 'metro_provenance', 'parking_provenance']
    .some((key) => data[key] && data[key].mode !== 'unknown');
}

async function refreshNearby() {
  const status = document.querySelector('#nearby-status');
  status.textContent = 'Konum alınıyor.';
  try {
    const point = await position();
    currentPosition = { lat: point.coords.latitude, lon: point.coords.longitude };
    const data = await get('/api/nearby', { ...currentPosition, needs: needs() });
    render(data);
    if (hasSourceData(data)) remember(data);
    status.textContent = 'Yakınınızdaki sonuçlar güncellendi.';
  } catch (error) {
    const message = error && error.code === 1 ? 'Konum izni verilmedi.'
      : error && error.code === 3 ? 'Konum isteği zaman aşımına uğradı.'
        : error && error.code === 2 ? 'Konum alınamadı.' : (error.message || 'Yakınınızdaki veriler alınamadı.');
    showCached(message);
  }
}

function journeyText(data, destination) {
  if (data.error) return data.message || 'Yolculuk karşılaştırması doğrulanamadı.';
  const lines = [`Konumunuz ile ${destination} arasındaki yolculuk karşılaştırması:`];
  for (const option of data.data?.options || []) {
    const label = MODE_LABEL[option.mode] || option.label || 'Seçenek';
    const time = Number.isFinite(option.total_minutes)
      ? `${option.total_minutes.toLocaleString('tr-TR', { maximumFractionDigits: 1 })} dk` : 'süre doğrulanamadı';
    lines.push(`${label}: ${time}`);
  }
  for (const option of data.data?.unavailable_options || []) {
    lines.push(`${MODE_LABEL[option.mode] || option.label || 'Seçenek'}: ${option.reason || 'hesaplanamadı'}`);
  }
  if (data.data?.disclaimer) lines.push(data.data.disclaimer);
  if (data.note) lines.push(data.note);
  return lines.join('\n');
}

function showJourney(text, citation) {
  const log = document.querySelector('#chat-log');
  const status = document.querySelector('#chat-status');
  if (!log) { document.querySelector('#nearby-status').textContent = text; return; }
  const item = document.createElement('li');
  item.className = 'chat-msg is-assistant';
  item.innerHTML = '<p class="chat-who">Yolculuk karşılaştırması</p><p class="chat-text"></p><div class="chat-final"></div>';
  item.querySelector('.chat-text').textContent = text;
  if (citation && item.querySelector('.chat-final')) item.querySelector('.chat-final').innerHTML = citations([citation]);
  log.append(item);
  log.scrollTop = log.scrollHeight;
  if (status) status.textContent = 'Yolculuk karşılaştırması hazır.';
}

async function goTo(button) {
  const destination = button.dataset.name || 'seçilen nokta';
  try {
    if (MOCK) throw new Error('Örnek veride yolculuk karşılaştırması çalıştırılmıyor.');
    if (!currentPosition) {
      const point = await position();
      currentPosition = { lat: point.coords.latitude, lon: point.coords.longitude };
    }
    const result = await post('/api/nearby/journey', {
      ...currentPosition,
      destination_lat: Number(button.dataset.lat),
      destination_lon: Number(button.dataset.lon),
      destination_name: destination,
    });
    showJourney(journeyText(result, destination), result.provenance);
  } catch (error) {
    showJourney(error.message || 'Yolculuk karşılaştırması doğrulanamadı.');
  }
}

function boot() {
  const locate = document.querySelector('#nearby-locate');
  if (MOCK) {
    locate.textContent = 'Örnek veriyi göster';
    const showMock = () => get('/api/nearby').then((data) => {
      render(data);
      document.querySelector('#nearby-status').textContent = 'Örnek veri.';
    }).catch(() => showCached('Örnek veri açılamadı.'));
    showMock();
    locate.addEventListener('click', showMock);
  } else if (cached()) {
    const saved = cached();
    render(saved.data);
    const age = shortAge(Math.max(0, (Date.now() - saved.saved_at) / 1000));
    document.querySelector('#nearby-status').textContent = `Bu cihazdaki son sonuçlar ${age} önce alındı.`;
  }
  if (!MOCK) locate.addEventListener('click', refreshNearby);
  document.querySelector('#nearby-cards').addEventListener('click', (event) => {
    const button = event.target.closest('[data-nearby-journey]');
    if (button && !button.disabled) goTo(button);
  });
}
