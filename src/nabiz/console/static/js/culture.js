import { MOCK, get } from './api.js';
import { esc } from './format.js';

const mount = document.getElementById('yakinimda-mount');
if (mount && !document.getElementById('kultur')) mountCulture(mount);

const STORAGE_KEY = 'nabiz.culture.v1';
const KIND_OPTIONS = [
  { key: 'library', id: 'kultur-kutuphane', label: 'Kütüphane' },
  { key: 'museum', id: 'kultur-muze', label: 'Müze' },
];
const NOTES = [
  'Doluluk bilgisi yok: İBB kütüphane ve müze doluluğunu açık veri olarak yayımlamıyor.',
  'Resmî tatil ve özel kapanışlar kayıtta yok; gitmeden önce arayın.',
  'Bu kayıtlarda konum yok; haritada gösterilemiyor.',
];

function readPreferences() {
  try {
    const value = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || 'null');
    if (!value || typeof value !== 'object') return { district: '', kinds: ['library', 'museum'] };
    const kinds = Array.isArray(value.kinds) ? value.kinds.filter((kind) => KIND_OPTIONS.some((option) => option.key === kind)) : [];
    return { district: typeof value.district === 'string' ? value.district : '', kinds: [...new Set(kinds)] };
  } catch (error) {
    return { district: '', kinds: ['library', 'museum'] };
  }
}

function savePreferences(preferences) {
  try { window.localStorage.setItem(STORAGE_KEY, JSON.stringify(preferences)); } catch (error) { /* Private mode keeps this session only. */ }
}

function phoneHref(phone) {
  return String(phone || '').replace(/Dahili:.*/i, '').replace(/[^\d+]/g, '');
}

function dateText(value) {
  const datePart = /^(\d{4}-\d{2}-\d{2})/.exec(value || '');
  const date = new Date(datePart ? `${datePart[1]}T12:00:00Z` : '');
  if (!Number.isFinite(date.getTime())) return 'bilinmiyor';
  return new Intl.DateTimeFormat('tr-TR', { timeZone: 'UTC', day: '2-digit', month: '2-digit', year: 'numeric' }).format(date);
}

function cultureListMarkup(venues) {
  return venues.map((venue) => {
    const name = esc(venue.name);
    const kind = esc(venue.kind_tr);
    const state = esc(venue.state_text);
    const address = venue.address ? `<p class="culture-address">${esc(venue.address)}</p>` : '';
    const phones = (venue.phones || []).map((phone) => {
      const href = phoneHref(phone);
      return href ? `<a href="tel:${esc(href)}">${esc(phone)}</a>` : '';
    }).filter(Boolean).join('<span aria-hidden="true"> · </span>');
    const contact = phones ? `<p class="culture-phones">${phones}</p>` : '';
    return `<li class="culture-item"><div class="culture-heading"><strong>${name}</strong><span class="culture-kind">${kind}</span><span>${state}</span></div>${address}${contact}</li>`;
  }).join('');
}

function mountCulture(host) {
  if (!document.querySelector('link[data-culture-styles]')) {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = '/css/culture.css';
    link.dataset.cultureStyles = '';
    document.head.append(link);
  }
  const section = document.createElement('section');
  section.id = 'kultur';
  section.className = 'culture-section';
  section.setAttribute('aria-labelledby', 'kultur-title');
  section.innerHTML = `
    <div class="culture-section-head"><h2 id="kultur-title">Kütüphane ve müze: şu an açık mı?</h2></div>
    <div class="culture-controls">
      <div class="culture-district-field"><label for="kultur-ilce">İlçe</label><select id="kultur-ilce"><option value="">İlçe seçin</option></select></div>
      <fieldset class="culture-kinds"><legend>Tür</legend>${KIND_OPTIONS.map((option) => `<label class="culture-chip" for="${option.id}"><input type="checkbox" id="${option.id}" value="${option.key}" checked><span>${option.label}</span></label>`).join('')}</fieldset>
    </div>
    <p class="culture-status" role="status" aria-live="polite">İlçe seçin.</p>
    <ol class="culture-list"></ol>
    <div class="culture-notes"></div>`;
  host.insertAdjacentElement('afterend', section);

  const status = section.querySelector('[role="status"]');
  const districtSelect = section.querySelector('#kultur-ilce');
  const list = section.querySelector('.culture-list');
  const notes = section.querySelector('.culture-notes');
  const preferences = readPreferences();
  for (const option of KIND_OPTIONS) section.querySelector(`#${option.id}`).checked = preferences.kinds.includes(option.key);

  if (MOCK) {
    status.textContent = 'Örnek veri modunda bu bölüm gösterilmez.';
    return;
  }

  function selectedKinds() {
    return KIND_OPTIONS.filter((option) => section.querySelector(`#${option.id}`).checked).map((option) => option.key);
  }

  function persist() {
    savePreferences({ district: districtSelect.value, kinds: selectedKinds() });
  }

  function renderNotes(data) {
    const source = Object.values(data.provenance_by_kind || {})[0] || {};
    const recordDate = dateText(source.observed_at);
    const captureDate = dateText(source.captured_at);
    const license = data.license || 'İBB Açık Veri Lisansı';
    notes.innerHTML = `${NOTES.map((note) => `<p class="culture-note">${esc(note)}</p>`).join('')}
      <p class="culture-note">İBB Açık Veri Portalı · kayıt tarihi ${esc(recordDate)} · indirildi ${esc(captureDate)} · ${esc(license)}</p>
      <p class="culture-note">${esc(data.disclaimer || 'Resmî İBB hizmeti değildir.')}</p>`;
  }

  async function loadDistrict() {
    try {
      const data = await get('/api/culture');
      const districts = Array.isArray(data.districts) ? data.districts : [];
      districtSelect.innerHTML = `<option value="">İlçe seçin</option>${districts.map((district) => `<option value="${esc(district)}">${esc(district)}</option>`).join('')}`;
      renderNotes(data);
      if (preferences.district && districts.includes(preferences.district)) {
        districtSelect.value = preferences.district;
        await loadVenues();
      } else {
        if (preferences.district) {
          preferences.district = '';
          persist();
        }
        status.textContent = data.note || 'İlçe seçin.';
      }
    } catch (error) {
      status.textContent = `Kayıtlar alınamadı: ${error.message}`;
    }
  }

  async function loadVenues() {
    persist();
    if (!districtSelect.value) {
      status.textContent = 'İlçe seçin.';
      list.innerHTML = '';
      return;
    }
    const kinds = selectedKinds();
    if (!kinds.length) {
      status.textContent = 'Tür seçilmedi.';
      list.innerHTML = '';
      return;
    }
    status.textContent = 'Kayıtlar yükleniyor.';
    try {
      const data = await get('/api/culture', { district: districtSelect.value, kinds: kinds.join(',') });
      const count = data.counts || { total: 0, open: 0 };
      status.textContent = `${data.district}: ${count.total} kayıt; kayda göre şu an açık: ${count.open}.`;
      list.innerHTML = cultureListMarkup(data.venues || []);
      renderNotes(data);
    } catch (error) {
      list.innerHTML = '';
      status.textContent = `Kayıtlar alınamadı: ${error.message}`;
    }
  }

  districtSelect.addEventListener('change', loadVenues);
  for (const option of KIND_OPTIONS) section.querySelector(`#${option.id}`).addEventListener('change', loadVenues);
  void loadDistrict();
}
