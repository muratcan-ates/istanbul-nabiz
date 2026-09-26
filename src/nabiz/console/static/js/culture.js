/* Kütüphane ve müze: şu an açık mı? (E30). The citizen picks a district; the server reads İBB's recorded
 * library and museum hours (GET /api/culture) and says, in İstanbul time, which are open by the record.
 * No location is asked, no occupancy is promised, holidays are not in the record and the page says so.
 * The district and the two kind chips are remembered on this device only (nabiz.culture.v1). Labels follow
 * the page language (i18n_text.js); names, addresses and phones are İBB's data and stay Turkish. */

import { MOCK, get } from './api.js';
import { currentLang, onLang, t } from './i18n_text.js';
import { esc } from './format.js';

const STORAGE_KEY = 'nabiz.culture.v1';
const KINDS = ['library', 'museum'];
const CHIP_IDS = { library: 'kultur-kutuphane', museum: 'kultur-muze' };

function kindLabel(kind) {
  return kind === 'museum' ? t('ui.culture.museum', 'Müze') : t('ui.culture.library', 'Kütüphane');
}

function dayName(index) {
  const names = [
    t('ui.culture.day0', 'Pazartesi'), t('ui.culture.day1', 'Salı'), t('ui.culture.day2', 'Çarşamba'),
    t('ui.culture.day3', 'Perşembe'), t('ui.culture.day4', 'Cuma'), t('ui.culture.day5', 'Cumartesi'),
    t('ui.culture.day6', 'Pazar'),
  ];
  return names[index] || '';
}

function clock(value) {
  return currentLang() === 'en' ? String(value || '').replace('.', ':') : String(value || '');
}

export function readPreferences() {
  const fallback = { district: '', kinds: [...KINDS] };
  try {
    const value = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || 'null');
    if (!value || typeof value !== 'object') return fallback;
    const kinds = Array.isArray(value.kinds) ? value.kinds.filter((kind) => KINDS.includes(kind)) : [...KINDS];
    return { district: typeof value.district === 'string' ? value.district : '', kinds: [...new Set(kinds)] };
  } catch (error) {
    return fallback;
  }
}

function savePreferences(preferences) {
  try { window.localStorage.setItem(STORAGE_KEY, JSON.stringify(preferences)); } catch (error) { /* private mode: this visit only */ }
}

/** The dialable part of a recorded phone: digits and a leading plus, the extension dropped. */
export function telHref(phone) {
  return String(phone || '').replace(/dahili.*/i, '').replace(/[^\d+]/g, '');
}

/** The state sentence in the page language, from the server's structured fields (never a guess). */
export function stateLine(venue) {
  if (venue.state === 'open' && venue.closes_at) {
    return t('ui.culture.open_until', 'Kayda göre şu an açık · kapanış {time}', { time: clock(venue.closes_at) });
  }
  if (venue.state === 'open') return t('ui.culture.open_always', 'Kayda göre 7/24 açık');
  const next = venue.state === 'closed' ? venue.opens_on : null;
  if (next && next.today) {
    return t('ui.culture.closed_today', 'Kayda göre şu an kapalı · açılış bugün {time}', { time: clock(next.time) });
  }
  if (next) {
    return t('ui.culture.closed_until', 'Kayda göre şu an kapalı · açılış {day} {time}', {
      day: dayName(next.weekday), time: clock(next.time),
    });
  }
  return t('ui.culture.no_hours', 'Çalışma saati kayıtta yok');
}

export function venueMarkup(venue) {
  const lang = currentLang();
  const phones = (venue.phones || []).map((phone) => {
    const href = telHref(phone);
    return href ? `<a href="tel:${esc(href)}">${esc(phone)}</a>` : `<span>${esc(phone)}</span>`;
  }).join('');
  const address = venue.address ? `<p class="culture-address">${esc(venue.address)}</p>` : '';
  return `<li class="culture-item" lang="tr">
    <h3 class="culture-name">${esc(venue.name)}</h3>
    <p class="culture-meta"><span class="culture-kind" lang="${lang}">${esc(kindLabel(venue.kind))}</span>`
    + `<span class="culture-state" lang="${lang}">${esc(stateLine(venue))}</span></p>
    ${address}${phones ? `<p class="culture-phones">${phones}</p>` : ''}
  </li>`;
}

function dateText(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value || '');
  return match ? `${match[3]}.${match[2]}.${match[1]}` : t('ui.culture.no_date', 'bilinmiyor');
}

function notesMarkup(data) {
  const lang = currentLang();
  const source = Object.values((data && data.provenance_by_kind) || {})[0] || {};
  const lines = [
    t('ui.culture.note_occupancy', 'Doluluk bilgisi yok: İBB kütüphane ve müze doluluğunu açık veri olarak yayımlamıyor.'),
    t('ui.culture.note_holidays', 'Resmî tatil ve özel kapanışlar kayıtta yok; gitmeden önce arayın.'),
    t('ui.culture.note_location', 'Bu kayıtlarda konum yok; haritada gösterilemiyor.'),
    t('ui.culture.source', 'İBB Açık Veri Portalı · kayıt tarihi {recorded} · indirildi {captured} · İBB Açık Veri Lisansı', {
      recorded: dateText(source.observed_at), captured: dateText(source.captured_at),
    }),
    t('ui.culture.disclaimer', 'Resmî İBB hizmeti değildir.'),
  ];
  return lines.map((line) => `<p class="culture-note" lang="${lang}">${esc(line)}</p>`).join('');
}

export function mountCulture(doc) {
  const host = doc.getElementById('yakinimda-mount');
  if (!host || doc.getElementById('kultur')) return;
  const section = doc.createElement('section');
  section.id = 'kultur';
  section.className = 'culture-section';
  section.setAttribute('aria-labelledby', 'kultur-title');
  section.innerHTML = `
    <h2 id="kultur-title" class="culture-title"></h2>
    <div class="culture-controls">
      <div class="culture-field"><label for="kultur-ilce" data-culture-label="district"></label>
        <select id="kultur-ilce"><option value=""></option></select></div>
      <fieldset class="culture-kinds"><legend data-culture-label="kinds"></legend>${KINDS.map((kind) => (
        `<label class="culture-chip" for="${CHIP_IDS[kind]}"><input type="checkbox" id="${CHIP_IDS[kind]}" value="${kind}" checked>`
        + `<span data-culture-kind="${kind}"></span></label>`)).join('')}</fieldset>
    </div>
    <p class="culture-status" role="status" aria-live="polite"></p>
    <ol class="culture-list"></ol>
    <div class="culture-notes"></div>`;
  host.insertAdjacentElement('afterend', section);

  const title = section.querySelector('#kultur-title');
  const status = section.querySelector('[role="status"]');
  const select = section.querySelector('#kultur-ilce');
  const list = section.querySelector('.culture-list');
  const notes = section.querySelector('.culture-notes');
  const chip = (kind) => section.querySelector(`#${CHIP_IDS[kind]}`);
  const preferences = readPreferences();
  for (const kind of KINDS) chip(kind).checked = preferences.kinds.includes(kind);

  let view = { kind: MOCK ? 'mock' : 'pick' };
  let lastData = null;
  let request = 0;

  function drawChrome() {
    const lang = currentLang();
    title.textContent = t('ui.culture.title', 'Kütüphane ve müze: şu an açık mı?');
    title.setAttribute('lang', lang);
    section.querySelector('[data-culture-label="district"]').textContent = t('ui.culture.district', 'İlçe');
    section.querySelector('[data-culture-label="kinds"]').textContent = t('ui.culture.kinds', 'Tür');
    for (const kind of KINDS) section.querySelector(`[data-culture-kind="${kind}"]`).textContent = kindLabel(kind);
    select.options[0].textContent = t('ui.culture.pick', 'İlçe seçin');
  }

  function drawStatus() {
    status.setAttribute('lang', currentLang());
    if (view.kind === 'mock') status.textContent = t('ui.culture.mock', 'Örnek veri modunda bu bölüm gösterilmez.');
    else if (view.kind === 'none') status.textContent = t('ui.culture.no_capture', 'Kütüphane ve müze kaydı bu sunucuda yok.');
    else if (view.kind === 'loading') status.textContent = t('ui.culture.loading', 'Kayıtlar yükleniyor.');
    else if (view.kind === 'no_kind') status.textContent = t('ui.culture.no_kind', 'Tür seçilmedi.');
    else if (view.kind === 'error') status.textContent = t('ui.culture.failed', 'Kayıtlar alınamadı: {message}', { message: view.message });
    else if (view.kind === 'list') {
      status.textContent = t('ui.culture.count', '{district}: {total} kayıt; kayda göre şu an açık: {open}.', {
        district: view.data.district, total: view.data.counts.total, open: view.data.counts.open,
      });
    } else status.textContent = t('ui.culture.pick', 'İlçe seçin');
  }

  function draw() {
    drawChrome();
    drawStatus();
    list.innerHTML = view.kind === 'list' ? (view.data.venues || []).map(venueMarkup).join('') : '';
    list.hidden = view.kind !== 'list' || !list.innerHTML;
    notes.innerHTML = lastData ? notesMarkup(lastData) : '';
  }

  const selectedKinds = () => KINDS.filter((kind) => chip(kind).checked);
  const persist = () => savePreferences({ district: select.value, kinds: selectedKinds() });

  async function loadVenues() {
    persist();
    const kinds = selectedKinds();
    if (!select.value) view = { kind: 'pick' };
    else if (!kinds.length) view = { kind: 'no_kind' };
    if (!select.value || !kinds.length) { draw(); return; }
    const mine = ++request;
    view = { kind: 'loading' };
    draw();
    try {
      const data = await get('/api/culture', { district: select.value, kinds: kinds.join(',') });
      if (mine !== request) return;
      lastData = data;
      view = { kind: 'list', data: { ...data, counts: data.counts || { total: 0, open: 0 } } };
    } catch (error) {
      if (mine !== request) return;
      view = { kind: 'error', message: error.message };
    }
    draw();
  }

  async function loadDistricts() {
    try {
      const data = await get('/api/culture');
      const districts = Array.isArray(data.districts) ? data.districts : [];
      select.insertAdjacentHTML('beforeend', districts.map((name) => `<option value="${esc(name)}" lang="tr">${esc(name)}</option>`).join(''));
      lastData = districts.length ? data : null;
      if (!districts.length) { view = { kind: 'none' }; draw(); return; }
      if (preferences.district && districts.includes(preferences.district)) {
        select.value = preferences.district;
        await loadVenues();
        return;
      }
      view = { kind: 'pick' };
    } catch (error) {
      view = { kind: 'error', message: error.message };
    }
    draw();
  }

  draw();
  if (MOCK) return;
  select.addEventListener('change', loadVenues);
  for (const kind of KINDS) chip(kind).addEventListener('change', loadVenues);
  onLang(draw);
  void loadDistricts();
}

if (typeof document !== 'undefined') mountCulture(document);
