/* Self-mount the recorded places section after the existing map layers. */

import { MOCK, get } from './api.js';
import { currentLang, onLang, t } from './i18n_text.js';
import * as view from './ibb_yerleri_view.js';

export const ANCHORS = Object.freeze(['harita-katmanlari', 'harita', 'map-space']);
export const STYLESHEET = '/css/ibb_yerleri.css';
export const SECTION_ID = 'ibb-yerleri';

function ready(doc) {
  return doc.readyState === 'loading'
    ? new Promise((resolve) => doc.addEventListener('DOMContentLoaded', resolve, { once: true }))
    : Promise.resolve();
}

function mountIbbPlaces(doc = document) {
  if (!doc || doc.getElementById(SECTION_ID)) return Promise.resolve(null);
  return ready(doc).then(async () => {
    const [mapApi] = await Promise.all([import('./map.js')]);
    const section = doc.createElement('section');
    let info = null, infoLoaded = false, infoPromise = null;
    let category = 'closed', where = 'nearby', result = null, userPoint = null;
    let message = 'idle', retryMode = null, busy = false, showingPlaces = false, actionVersion = 0;
    let io = null, placementObserver = null;

    function statusText() {
      if (message === 'result') return view.statusText(result, where);
      // Literal t() calls (P00 D2a): the page's catalogue check reads each key beside its Turkish.
      const messages = {
        summary_error: () => t('ui.ibbplaces.error', 'İBB yerleri şu an okunamadı.'),
        location_error: () => t('ui.ibbplaces.location_error', 'Konumunuz alınamadı. İlçe seçerek bakabilirsiniz.'),
        outside: () => t('ui.ibbplaces.outside_istanbul', 'Bu konum İstanbul aralığında değil. İlçe seçerek bakabilirsiniz.'),
        points_error: () => t('ui.ibbplaces.error', 'İBB yerleri şu an okunamadı.'),
        unavailable: () => t('ui.ibbplaces.list_unavailable', 'Bu liste alınamadı.'),
        other_map_layer: () => t('ui.ibbplaces.other_layer', 'Harita şu an başka bir katmanı gösteriyor.'),
      };
      return messages[message] ? messages[message]() : '';
    }

    function render() {
      const focused = section.contains(doc.activeElement)
        ? { id: doc.activeElement.id, name: doc.activeElement.name, value: doc.activeElement.value } : null;
      section.innerHTML = view.sectionMarkup(info, currentLang());
      section.querySelectorAll('input[name="ibb-yerleri-category"]').forEach((input) => {
        input.checked = input.value === category;
      });
      const controls = section.querySelector('.ibb-yerleri-controls');
      controls.hidden = category === 'closed';
      const whereSelect = section.querySelector('#ibb-yerleri-where');
      whereSelect.value = where === 'nearby' ? 'nearby' : where;
      const sources = section.querySelector('#ibb-yerleri-sources');
      sources.hidden = category === 'closed' || !infoLoaded;
      const status = section.querySelector('#ibb-yerleri-status');
      status.textContent = statusText();
      section.querySelector('#ibb-yerleri-show').disabled = busy;
      const retry = section.querySelector('#ibb-yerleri-retry');
      retry.hidden = !retryMode;
      section.querySelector('#ibb-yerleri-results').hidden = !result;
      section.querySelector('.ibb-yerleri-list').innerHTML = view.rowsMarkup(result, userPoint);
      section.querySelector('#ibb-yerleri-mock').hidden = !MOCK;
      section.setAttribute('aria-busy', busy ? 'true' : 'false');
      if (focused) {
        const target = focused.id ? doc.getElementById(focused.id)
          : [...section.querySelectorAll(`input[name="${focused.name}"]`)].find((input) => input.value === focused.value);
        target?.focus({ preventScroll: true });
      }
    }

    function place() {
      const slot = doc.getElementById('map-space');
      const anchor = doc.getElementById('harita-katmanlari') || doc.getElementById('harita');
      if (!anchor) return false;
      if (anchor.nextElementSibling !== section) anchor.after(section);
      if (slot && anchor.parentElement === slot && section.parentElement === slot) {
        placementObserver?.disconnect();
        return true;
      }
      return false;
    }

    async function loadInfo() {
      if (MOCK) return false;
      if (infoLoaded) return true;
      if (infoPromise) return infoPromise;
      retryMode = null;
      infoPromise = get('/api/ibb-places').then((value) => {
        info = value; infoLoaded = true; message = 'idle'; retryMode = null; render(); return true;
      }).catch(() => {
        message = 'summary_error'; retryMode = 'summary'; render(); return false;
      }).finally(() => { infoPromise = null; });
      return infoPromise;
    }

    function focusResults() {
      section.querySelector('#ibb-yerleri-results-title')?.focus({ preventScroll: true });
    }

    function clearPlacesMap() {
      if (!showingPlaces) return;
      mapApi.hideMap();
      showingPlaces = false;
    }

    function location() {
      return new Promise((resolve, reject) => {
        if (!navigator.geolocation) { reject(new Error('location')); return; }
        navigator.geolocation.getCurrentPosition(
          (position) => resolve({ lat: position.coords.latitude, lon: position.coords.longitude }),
          () => reject(new Error('location')),
          { enableHighAccuracy: false, maximumAge: 60000, timeout: 10000 },
        );
      });
    }

    async function showPlaces() {
      if (category === 'closed' || MOCK) { if (MOCK) { message = 'idle'; render(); } return; }
      const version = ++actionVersion;
      busy = true; message = 'idle'; retryMode = null; render();
      if (!await loadInfo()) { if (version === actionVersion) { busy = false; render(); } return; }
      if (version !== actionVersion) return;
      const categoryInfo = info.categories.find((item) => item.id === category);
      if (!categoryInfo || categoryInfo.status !== 'alindi') {
        result = { status: 'veri_alinamadi', points: [], total: 0, shown: 0, truncated: false };
        message = 'unavailable'; retryMode = null; busy = false; clearPlacesMap(); render(); focusResults(); return;
      }
      let params;
      if (where === 'nearby') {
        try { userPoint = await location(); }
        catch {
          if (version !== actionVersion) return;
          userPoint = null; busy = false; message = 'location_error'; retryMode = null; render();
          section.querySelector('#ibb-yerleri-where')?.focus({ preventScroll: true }); return;
        }
        if (version !== actionVersion) return;
        const box = view.searchBox(userPoint.lat, userPoint.lon);
        if (!box) {
          userPoint = null; busy = false; message = 'outside'; retryMode = null; render();
          section.querySelector('#ibb-yerleri-where')?.focus({ preventScroll: true }); return;
        }
        params = { bbox: [box.minLon, box.minLat, box.maxLon, box.maxLat].join(',') };
      } else {
        userPoint = null; params = { district: where };
      }
      try {
        result = await get(`/api/ibb-places/${category}`, params);
        if (version !== actionVersion) return;
        message = 'result'; retryMode = null;
        const points = view.mapPoints(result.points, userPoint);
        if (points.length) { mapApi.showOnMap(points); showingPlaces = true; }
        else clearPlacesMap();
      } catch {
        if (version !== actionVersion) return;
        result = null; message = 'points_error'; retryMode = 'points'; clearPlacesMap();
      }
      busy = false; render(); focusResults();
    }

    section.id = SECTION_ID;
    section.innerHTML = view.sectionMarkup(info, currentLang());
    if (!doc.querySelector(`link[href="${STYLESHEET}"]`)) {
      const link = doc.createElement('link');
      link.rel = 'stylesheet'; link.href = STYLESHEET; link.dataset.ibbYerleriStyles = '';
      doc.head.append(link);
    }
    place();
    placementObserver = new MutationObserver(() => place());
    placementObserver.observe(doc.body, { childList: true, subtree: true });

    section.addEventListener('change', (event) => {
      if (event.target.matches('input[name="ibb-yerleri-category"]')) {
        actionVersion += 1; busy = false;
        category = event.target.value; result = null; userPoint = null; message = 'idle'; retryMode = null;
        if (category === 'closed') clearPlacesMap();
        render();
        if (category !== 'closed') void loadInfo();
      } else if (event.target.id === 'ibb-yerleri-where') {
        actionVersion += 1; busy = false;
        where = event.target.value; result = null; userPoint = null; message = 'idle'; retryMode = null;
        clearPlacesMap(); render();
      }
    });
    section.addEventListener('click', (event) => {
      if (event.target.closest('#ibb-yerleri-show')) { void showPlaces(); return; }
      if (event.target.closest('#ibb-yerleri-retry')) {
        if (retryMode === 'summary') { message = 'idle'; void loadInfo(); }
        else if (retryMode === 'points') void showPlaces();
        return;
      }
      const summary = event.target.closest('.ibb-yerleri-list summary');
      if (summary) mapApi.highlightMarker(summary.closest('details').id);
    });
    doc.addEventListener('nabiz:show-on-map', () => {
      if (!showingPlaces) return;
      actionVersion += 1; busy = false;
      showingPlaces = false;
      if (category !== 'closed') { message = 'other_map_layer'; render(); }
    });
    onLang(() => render());
    if (MOCK) { section.querySelector('#ibb-yerleri-mock').hidden = false; }
    else if ('IntersectionObserver' in globalThis) {
      io = new IntersectionObserver((entries) => {
        if (entries.some((entry) => entry.isIntersecting)) { io.disconnect(); void loadInfo(); }
      });
      io.observe(section);
    }
    render();
    return section;
  });
}

if (typeof document !== 'undefined') void mountIbbPlaces(document);
export { mountIbbPlaces };
