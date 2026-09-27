/* A self mounting, device saved planner for the dated Kultur AŞ capture. */
import { API_BASE, isMock } from './config.js';
import { get } from './api.js';
import { currentLang, onLang, t } from './i18n_text.js';
import { addDays, eventCardHtml, formatDate, formatStamp, hiddenReasonHtml, pastPlanHtml, planPanelHtml, plannerMarkup, routeFormHtml, sourceFooterHtml } from './day_plan_view.js';
const STORE_KEY = 'nabiz.dayplan.v1';
const DAYS_AHEAD = 30;
const TIME_ZONE = 'Europe/Istanbul';
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[char]));
function pageToday() {
  const value = Object.fromEntries(new Intl.DateTimeFormat('en-CA', { timeZone: TIME_ZONE, year: 'numeric', month: '2-digit', day: '2-digit' })
    .formatToParts(new Date()).map((part) => [part.type, part.value]));
  return `${value.year}-${value.month}-${value.day}`;
}
function readPlan() {
  try { const value = JSON.parse(window.localStorage.getItem(STORE_KEY) || 'null');
    return value && value.v === 1 && typeof value.date === 'string' && value.event?.id ? value : null;
  } catch (error) { return null; }
}
function savePlan(plan) {
  try { window.localStorage.setItem(STORE_KEY, JSON.stringify(plan)); return true; } catch (error) { return false; }
}
function removePlan() {
  try { window.localStorage.removeItem(STORE_KEY); } catch (error) { /* storage may be disabled */ }
}
function ensureStyles(doc) {
  if (doc.querySelector('link[data-day-plan-style]')) return;
  const link = doc.createElement('link');
  link.rel = 'stylesheet'; link.href = '/css/day_plan.css'; link.dataset.dayPlanStyle = 'true'; doc.head.append(link);
}
function mount(doc) {
  const host = doc.getElementById('city-tools') || doc.getElementById('yakinimda-mount');
  if (!host || doc.getElementById('gun-plani')) return;
  ensureStyles(doc);
  const details = doc.createElement('details');
  details.className = 'more tool-detail';
  details.id = 'gun-plani';
  details.innerHTML = `<summary><h2 id="gun-plani-title"></h2></summary>${plannerMarkup()}`;
  host.append(details);
  const root = details;
  const form = root.querySelector('[data-filters]'), dateInput = root.querySelector('#dayplan-date');
  const districtSelect = root.querySelector('#dayplan-district'), status = root.querySelector('[data-status]');
  const list = root.querySelector('[data-list]'), source = root.querySelector('[data-source]'), hidden = root.querySelector('[data-hidden]');
  const planHost = root.querySelector('[data-plan-host]');
  const mock = isMock(window.location.search);
  const savedPlan = mock ? null : readPlan();
  const state = { data: null, plan: savedPlan, loaded: false, routeError: false, request: 0, districtRestore: savedPlan?.filters?.district || '',
    expiredPlan: Boolean(savedPlan && savedPlan.date < pageToday()) };
  const translate = (key, fallback, vars) => t(key, fallback, vars); const input = (selector) => root.querySelector(selector);
  dateInput.value = pageToday(); dateInput.min = pageToday();
  dateInput.max = addDays(pageToday(), DAYS_AHEAD);
  if (state.plan) {
    dateInput.value = state.plan.date;
    const savedAudience = state.plan.filters?.with;
    if (['all', 'child', 'adult'].includes(savedAudience)) form.querySelector(`[name="audience"][value="${savedAudience}"]`).checked = true;
    input('[name="free"]').checked = Boolean(state.plan.filters?.free); input('[name="stepFree"]').checked = Boolean(state.plan.filters?.stepFree);
  }
  function renderChrome() {
    const lang = currentLang();
    const title = input('#gun-plani-title');
    title.textContent = t('ui.dayplan.title', 'Bir gün planı'); title.setAttribute('lang', lang);
    for (const [selector, label] of [
      ['[data-intro]', t('ui.dayplan.intro', 'Kaynakta tarihli etkinlikleri seçin ve gününüzü planlayın.')], ['[data-date-label]', t('ui.dayplan.date', 'Tarih')],
      ['[data-district-label]', t('ui.dayplan.district', 'İlçe')], ['[data-audience-label]', t('ui.dayplan.audience', 'Kimle')],
      ['[data-audience-all]', t('ui.dayplan.all', 'Herkes')], ['[data-audience-child]', t('ui.dayplan.child', 'Çocukla')], ['[data-audience-adult]', t('ui.dayplan.adult', 'Yetişkin')],
      ['[data-free-label]', t('ui.dayplan.free', 'Yalnız ücretsiz')],
      ['[data-stepfree-label]', t('ui.dayplan.step_free', 'Basamaksız ulaşım')], ['[data-submit]', t('ui.dayplan.show', 'Etkinlikleri göster')],
      ['[data-hidden-title]', t('ui.dayplan.hidden_title', 'Neden bazı etkinlikler yok?')],
    ]) input(selector).textContent = label;
    input('[data-filter-hint]').textContent = `${t('ui.dayplan.age_note', 'Yaş aralığı kaynakta yok; kurumun “Çocuklar için” etiketi kullanılır.')} ${t('ui.dayplan.access_note', 'Mekân erişim bilgisi kaynakta yok.')}`;
    const districts = state.data?.districts || [];
    const prior = districtSelect.value || state.districtRestore;
    districtSelect.innerHTML = `<option value="">${esc(t('ui.dayplan.all_districts', 'Tümü'))}</option>${districts.map((name) => `<option value="${esc(name)}" lang="tr">${esc(name)}</option>`).join('')}`;
    if (districts.includes(prior)) districtSelect.value = prior;
    districtSelect.closest('.dayplan-district')?.toggleAttribute('hidden', !districts.length);
    state.districtRestore = '';
    renderList();
    renderPlan();
  }
  function setStatus(key, fallback, vars = {}, sourceMessage = '') {
    status.setAttribute('lang', currentLang()); status.innerHTML = esc(t(key, fallback, vars)) + (sourceMessage ? ` <span lang="tr">${esc(sourceMessage)}</span>` : '');
  }
  function renderList() {
    if (!state.data) return;
    if (state.data.status === 'no_data') {
      list.hidden = true;
      source.hidden = true;
      setStatus('ui.dayplan.no_data', 'Etkinlik verisi henüz yok.');
      return;
    }
    const events = state.data.events || [];
    list.innerHTML = events.map((event) => eventCardHtml(event, currentLang(), translate)).join('');
    list.hidden = !events.length;
    if (events.length) setStatus('ui.dayplan.count', '{count} etkinlik bulundu.', { count: events.length });
    else if (input('[name="free"]').checked) setStatus('ui.dayplan.empty_free', 'Bu tarihte kaynakta ücretsiz etkinlik yok.');
    else setStatus('ui.dayplan.empty', 'Seçtiğiniz ölçütlerde bu tarihte etkinlik yok.');
    source.hidden = false;
    const captured = formatStamp(state.data.source?.captured_at, currentLang());
    const missing = Boolean(state.data.source?.not_captured?.length);
    source.innerHTML = sourceFooterHtml(state.data, currentLang(), translate, captured);
    const counts = state.data.hidden || {};
    const hiddenCount = ['past', 'cancelled', 'started', 'undated', 'unparsed'].reduce((sum, key) => sum + Number(counts[key] || 0), 0);
    hidden.hidden = !hiddenCount && !missing;
    input('[data-hidden-body]').innerHTML = hiddenReasonHtml(counts, missing, translate);
  }
  function renderPlan() {
    if (!state.plan) { planHost.innerHTML = ''; return; }
    if (state.plan.date < pageToday()) planHost.innerHTML = pastPlanHtml(translate);
    else planHost.innerHTML = planPanelHtml(state.plan, currentLang(), translate, pageToday()) + routeFormHtml(state.plan, currentLang(), translate, state.routeError, pageToday());
  }
  async function loadEvents() {
    if (mock) return;
    const serial = ++state.request;
    const params = { date: dateInput.value, district: districtSelect.value,
      with: form.querySelector('[name="audience"]:checked')?.value || 'all', free: input('[name="free"]').checked ? '1' : '0' };
    list.hidden = true;
    source.hidden = true;
    hidden.hidden = true;
    setStatus('ui.dayplan.loading', 'Etkinlikler yükleniyor.');
    try {
      const data = await get('/api/events', params);
      if (serial !== state.request) return;
      state.data = data;
      renderChrome();
    } catch (error) {
      if (serial !== state.request) return;
      setStatus('ui.dayplan.error', 'Etkinlikler alınamadı. Bağlantınızı denetleyip yeniden deneyin.', {}, error.message);
    }
  }
  async function refreshSavedPlan() {
    if (!state.plan || state.plan.date < pageToday()) return;
    try {
      const data = await get('/api/events/day', { id: state.plan.event.id, date: state.plan.date });
      state.plan = { ...state.plan, event: data.event, venue_hours: data.venue_hours, nearby: data.nearby, notes: data.notes,
        venue_sources: data.venue_sources, holiday_note: (data.notes || []).some((note) => note.startsWith('Resmî tatil')) };
      savePlan(state.plan);
      renderPlan();
    } catch (error) {
      const saved = input('[data-plan-status]');
      if (saved && error.status === 404) saved.textContent = t('ui.dayplan.gone', 'Bu etkinlik artık kaynakta yok ya da bu tarihte sürmüyor; planı kaldırabilirsiniz.');
      else if (saved) saved.textContent = t('ui.dayplan.refresh_failed', 'Etkinlik bilgisi yenilenemedi; bu cihazdaki planınız duruyor.');
    }
  }
  function persistFilters() {
    if (!state.plan) return;
    state.plan.filters = { district: districtSelect.value, with: form.querySelector('[name="audience"]:checked')?.value || 'all',
      free: input('[name="free"]').checked, stepFree: input('[name="stepFree"]').checked };
    savePlan(state.plan);
  }
  async function routeCompare(route) {
    const from = route.querySelector('[name="from"]').value.trim();
    const to = route.querySelector('[name="to"]')?.value.trim() || state.plan.event.venue;
    const result = route.querySelector('[data-route-status]');
    const button = route.querySelector('[data-route-submit]');
    if (!from || !to) { result.textContent = t('ui.dayplan.route_required', 'Çıkış semtinizi veya durağınızı yazın.'); return; }
    state.plan.from = from;
    state.plan.to = to;
    savePlan(state.plan);
    button.setAttribute('aria-busy', 'true');
    button.setAttribute('aria-disabled', 'true');
    result.textContent = t('ui.dayplan.comparing', 'Ulaşım seçenekleri karşılaştırılıyor.');
    const compare = async (start, end) => {
      const url = new URL(`${API_BASE}/api/compare`, window.location.origin);
      url.searchParams.set('from', start); url.searchParams.set('to', end);
      url.searchParams.set('needs', input('[name="stepFree"]').checked ? 'step_free' : '');
      const response = await fetch(url, { headers: { Accept: 'application/json' } });
      let body = {};
      try { body = await response.json(); } catch (error) { body = {}; }
      if (!response.ok) throw new Error(body.message || t('ui.dayplan.compare_failed', 'Ulaşım karşılaştırması alınamadı.'));
      return body;
    };
    try {
      const [out, back] = await Promise.all([compare(from, to), compare(to, from)]);
      state.plan.trip = { out: out.options || [], back: back.options || [] };
      const unavailable = !(state.plan.trip.out.some((item) => item.available) || state.plan.trip.back.some((item) => item.available));
      state.routeError = unavailable;
      result.textContent = unavailable ? t('ui.dayplan.compare_unavailable', 'Bu mekân için ulaşım karşılaştırılamadı. Mekânın yakınındaki durağın adını yazarak deneyin.')
        : t('ui.dayplan.compare_done', 'Gidiş ve dönüş karşılaştırması eklendi.');
      persistFilters(); savePlan(state.plan); renderPlan();
      root.querySelector('[data-route-status]').textContent = result.textContent;
    } catch (error) {
      state.routeError = true;
      const message = t('ui.dayplan.compare_unavailable', 'Bu mekân için ulaşım karşılaştırılamadı. Mekânın yakınındaki durağın adını yazarak deneyin.');
      renderPlan();
      root.querySelector('[data-route-status]').textContent = message;
    } finally { const current = root.querySelector('[data-route-submit]');
      if (current) { current.removeAttribute('aria-busy'); current.removeAttribute('aria-disabled'); }
    }
  }
  async function downloadCalendar(button) {
    button.setAttribute('aria-busy', 'true'); button.setAttribute('aria-disabled', 'true');
    try {
      const response = await fetch(`${API_BASE}/api/events/calendar`, {
        method: 'POST', headers: { Accept: 'text/calendar', 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: state.plan.event.id, date: state.plan.date, lang: currentLang() }),
      });
      if (!response.ok) {
        let body = {}; try { body = await response.json(); } catch (error) { body = {}; }
        throw new Error(body.message || t('ui.dayplan.calendar_error', 'Takvim dosyası indirilemedi.'));
      }
      const blobUrl = URL.createObjectURL(await response.blob());
      const anchor = document.createElement('a');
      anchor.href = blobUrl; anchor.download = 'nabiz-gun-plani.ics'; anchor.hidden = true;
      document.body.append(anchor); anchor.click(); anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
      setStatus('ui.dayplan.calendar_done', 'Takvim dosyası indirildi.');
    } catch (error) {
      setStatus('ui.dayplan.calendar_error', 'Takvim dosyası indirilemedi.', {}, error.message);
    } finally {
      button.removeAttribute('aria-busy'); button.removeAttribute('aria-disabled');
    }
  }
  form.addEventListener('submit', (event) => { event.preventDefault(); void loadEvents(); });
  root.addEventListener('toggle', () => { if (!mock && !state.expiredPlan && root.open && !state.loaded) { state.loaded = true; void loadEvents(); } });
  root.addEventListener('click', (event) => {
    const planButton = event.target.closest('[data-plan-id]');
    if (planButton && state.data) {
      const selected = (state.data.events || []).find((item) => item.id === planButton.dataset.planId);
      if (!selected) return;
      state.plan = { v: 1, saved_at: new Date().toISOString(), date: state.data.date,
        filters: { district: districtSelect.value, with: form.querySelector('[name="audience"]:checked')?.value || 'all',
          free: input('[name="free"]').checked, stepFree: input('[name="stepFree"]').checked },
        from: '', to: selected.venue, event: { ...selected }, trip: { out: [], back: [] } };
      state.routeError = false;
      state.plan.date_label = formatDate(state.plan.date, currentLang());
      state.plan.saved_label = formatStamp(state.plan.saved_at, currentLang());
      savePlan(state.plan);
      root.open = true; renderPlan();
      planHost.querySelector('#dayplan-panel-title')?.focus();
      setStatus('ui.dayplan.plan_saved', 'Plan bu cihazda kaydedildi.');
      void refreshSavedPlan();
    }
    if (event.target.closest('[data-remove-plan]')) {
      state.plan = null; state.expiredPlan = false; removePlan(); renderPlan(); input('[data-submit]').focus();
      form.hidden = false; input('[data-intro]').hidden = false; dateInput.value = pageToday();
      setStatus('ui.dayplan.plan_removed', 'Plan bu cihazdan kaldırıldı.');
    }
    const calendarButton = event.target.closest('[data-calendar]');
    if (calendarButton && state.plan) void downloadCalendar(calendarButton);
  });
  root.addEventListener('submit', (event) => { if (event.target.matches('[data-route]')) { event.preventDefault(); void routeCompare(event.target); } });
  onLang(() => {
    if (state.plan) {
      state.plan.date_label = formatDate(state.plan.date, currentLang());
      state.plan.saved_label = formatStamp(state.plan.saved_at, currentLang());
    }
    renderChrome();
  });
  if (state.plan) { root.open = true; state.plan.date_label = formatDate(state.plan.date, currentLang());
    state.plan.saved_label = formatStamp(state.plan.saved_at, currentLang()); renderPlan(); void refreshSavedPlan(); }
  if (mock) {
    form.hidden = true; input('[data-intro]').hidden = true; list.hidden = true; source.hidden = true; planHost.innerHTML = '';
    setStatus('ui.dayplan.mock', 'Örnek veri kipinde gün planı kapalı.');
  }
  if (state.expiredPlan) { form.hidden = true; input('[data-intro]').hidden = true; list.hidden = true; source.hidden = true; hidden.hidden = true; }
  renderChrome();
}
if (typeof document !== 'undefined') mount(document);
