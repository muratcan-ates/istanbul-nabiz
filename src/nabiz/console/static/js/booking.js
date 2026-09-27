/* Example bookings stay in Nabız: the recorded library schedule only controls which times appear. */

import { MOCK } from './api.js';
import { currentLang, onLang, t } from './i18n_text.js';
import { esc } from './format.js';
import { icon } from './icons.js';
import { deviceId, readAccount } from './identity.js';

const BOOKING_CSS = '/css/booking.css';

function hhmm(value, language = currentLang()) {
  const minute = Number(value);
  const hour = minute === 1440 ? 24 : Math.floor(minute / 60);
  const part = `${String(hour).padStart(2, '0')}${language === 'en' ? ':' : '.'}${String(minute === 1440 ? 0 : minute % 60).padStart(2, '0')}`;
  return part;
}

function slotText(slot, language = currentLang()) {
  return `${hhmm(slot.start, language)}-${hhmm(slot.end, language)}`;
}

function dayName(index) {
  if (index === 0) return t('ui.booking.day0', 'Pzt');
  if (index === 1) return t('ui.booking.day1', 'Sal');
  if (index === 2) return t('ui.booking.day2', 'Çar');
  if (index === 3) return t('ui.booking.day3', 'Per');
  if (index === 4) return t('ui.booking.day4', 'Cum');
  if (index === 5) return t('ui.booking.day5', 'Cmt');
  return t('ui.booking.day6', 'Paz');
}

function dayText(day, language = currentLang(), todayDate = day.date) {
  const offset = Math.round((Date.parse(`${day.date}T12:00:00Z`) - Date.parse(`${todayDate}T12:00:00Z`)) / 86400000);
  const label = offset === 0 ? t('ui.booking.today', 'Bugün') : offset === 1 ? t('ui.booking.tomorrow', 'Yarın') : dayName(day.weekday);
  const date = `${day.date.slice(8, 10)}.${day.date.slice(5, 7)}`;
  const value = t('ui.booking.day_label', '{day} {date}', { day: label, date });
  if (day.reason === 'closed') return t('ui.booking.closed', '{day} · kayda göre kapalı', { day: value });
  if (day.reason === 'no_slots_left') return t('ui.booking.no_slots_left', '{day} · bugün için saat kalmadı', { day: value });
  return value;
}

function seatLabel(seat, state = 'free', accessible = false) {
  const row = seat.charAt(0);
  const number = seat.slice(1);
  const vars = { row, number };
  let base;
  if (state === 'taken') base = t('ui.booking.seat_taken', '{row} sırası, {number} numaralı koltuk, dolu', vars);
  else if (state === 'mine') base = t('ui.booking.seat_mine', '{row} sırası, {number} numaralı koltuk, sizin randevunuz', vars);
  else if (state === 'selected') base = t('ui.booking.seat_selected', '{row} sırası, {number} numaralı koltuk, seçtiğiniz', vars);
  else base = t('ui.booking.seat_free', '{row} sırası, {number} numaralı koltuk, boş', vars);
  return accessible ? `${base}, ${t('ui.booking.seat_accessible', 'erişilebilir masa')}` : base;
}

function seatMapMarkup(room, taken = [], mine = null, selected = '') {
  const occupied = new Set(taken);
  const rows = Array.from(room.rows || 'ABCDEF');
  const accessible = new Set(room.accessible || []);
  const markup = rows.map((row) => {
    const seats = [];
    for (let number = 1; number <= Number(room.seats_per_row || 6); number += 1) {
      if (number === Number(room.aisle_after || 3) + 1) seats.push('<span class="booking-aisle" aria-hidden="true"></span>');
      const seat = `${row}${number}`;
      const isMine = Boolean(mine && mine.seat === seat);
      const isTaken = occupied.has(seat) || isMine;
      const isSelected = selected === seat;
      const state = isMine ? 'mine' : isTaken ? 'taken' : isSelected ? 'selected' : 'free';
      const face = isMine || isTaken ? '' : isSelected ? icon('circle-check') : icon('armchair');
      const aid = accessible.has(seat);
      seats.push(`<label class="booking-seat is-${state}${aid ? ' is-accessible' : ''}"><input class="sr-only" type="radio" name="booking-seat" value="${esc(seat)}" aria-label="${esc(seatLabel(seat, state, aid))}"${isTaken ? ' disabled' : ''}${isSelected ? ' checked' : ''}><span class="booking-seat-face">${face}<span aria-hidden="true">${number}</span></span>${aid ? `<span class="booking-seat-mark">${icon('wheelchair')}<span class="sr-only">${esc(t('ui.booking.seat_accessible', 'erişilebilir masa'))}</span></span>` : ''}</label>`);
    }
    return `<div class="booking-row" role="group" aria-label="${esc(t('ui.booking.row', '{row} sırası', { row }))}"><span class="booking-row-name" aria-hidden="true">${row}</span><div class="booking-row-seats">${seats.join('')}</div></div>`;
  });
  return `<fieldset class="booking-seats" tabindex="-1"><legend>${esc(t('ui.booking.seat_legend', 'Koltuk seçin: {room}, {capacity} koltuk', { room: t('ui.booking.room', 'Çalışma salonu (örnek)'), capacity: room.capacity || rows.length * Number(room.seats_per_row || 6) }))}</legend><p class="booking-entrance" aria-hidden="true">${esc(t('ui.booking.entrance', 'Giriş'))}</p><div class="booking-room">${markup.join('')}</div></fieldset>`;
}

function errorText(code, body = {}) {
  if (code === 'seat_taken') return t('ui.booking.err_seat_taken', 'Bu koltuk az önce ayrıldı; başka bir koltuk seçin.');
  if (code === 'slot_held') return t('ui.booking.err_slot_held', 'Bu saat aralığında zaten bir randevunuz var.');
  if (code === 'active_limit') return t('ui.booking.err_active_limit', 'En çok {limit} yaklaşan randevunuz olabilir; önce birini iptal edin.', { limit: body.limit || 2 });
  if (code === 'too_many') return t('ui.booking.err_too_many', 'Bu saat içinde çok deneme oldu; biraz sonra tekrar deneyin.');
  if (code === 'no_holder') return t('ui.booking.err_no_holder', 'Bu tarayıcı cihaz kodunu saklayamıyor (gizli pencere olabilir); randevu alınamıyor.');
  if (code === 'not_offered') return t('ui.booking.err_not_offered', 'Bu gün ya da saat artık seçilemiyor; liste yenilendi.');
  if (code === 'consent_required') return t('ui.booking.consent_error', 'Randevu için onay kutusunu işaretleyin.');
  if (code === 'bad_seat') return t('ui.booking.err_bad_seat', 'Seçtiğiniz koltuk örnek salon planında yok.');
  if (code === 'offline') return t('ui.booking.err_offline', 'Sunucuya ulaşılamadı; bağlantınızı kontrol edip tekrar deneyin.');
  const retry = t('ui.booking.retry', 'Tekrar deneyin.');
  return t('ui.booking.err_failed', 'Randevu kaydedilemedi: {message}', { message: currentLang() === 'en' ? 'Please try again.' : (body.message || retry) });
}

function api(path, options = {}) {
  const headers = { Accept: 'application/json', ...(options.body ? { 'Content-Type': 'application/json' } : {}) };
  const device = deviceId();
  const account = readAccount();
  if (device) headers['X-Nabiz-Device'] = device;
  if (account && account.token) headers['X-Nabiz-Account'] = account.token;
  return fetch(path, { ...options, headers }).then(async (response) => {
    const body = await response.json();
    if (!response.ok) {
      const error = new Error(body.message || 'request failed');
      error.code = body.error;
      error.body = body;
      throw error;
    }
    return body;
  });
}

function keyForDay(day) {
  return `input[name="booking-day"][value="${day}"]`;
}

function focusQuery(doc, selector) {
  if (!selector) return;
  const target = doc.querySelector(selector);
  if (target && typeof target.focus === 'function') target.focus();
}

function ensureStyles(doc) {
  if (doc.querySelector(`link[href="${BOOKING_CSS}"]`)) return;
  const stylesheet = doc.createElement('link');
  stylesheet.rel = 'stylesheet';
  stylesheet.href = BOOKING_CSS;
  doc.head.appendChild(stylesheet);
}

function ensureDialog(doc, state) {
  if (state.dialog) return state.dialog;
  ensureStyles(doc);
  const dialog = doc.createElement('dialog');
  dialog.id = 'randevu';
  dialog.className = 'booking booking-dialog';
  dialog.setAttribute('aria-labelledby', 'randevu-title');
  dialog.setAttribute('aria-describedby', 'randevu-notice');
  doc.body.appendChild(dialog);
  state.dialog = dialog;
  dialog.addEventListener('click', (event) => {
    const action = event.target.closest('[data-action]');
    if (!action) return;
    const type = action.dataset.action;
    if (type === 'close' && !state.submitting && !state.cancelPending) dialog.close();
    if (type === 'submit') submitBooking(state, doc);
    if (type === 'cancel-start') {
      if (!state.result && state.seats && state.seats.mine) {
        const slot = (selectedDay(state)?.slots || []).find((item) => item.start === state.start);
        state.result = {
          code: state.seats.mine.code, library: state.data.library, day: state.day,
          start: state.start, end: slot.end, seat: state.seats.mine.seat,
          held_by: readAccount() ? 'account' : 'device',
        };
        state.existing = true;
      }
      state.confirmCancel = true;
      renderSuccess(state, doc, true);
    }
    if (type === 'cancel-no') { state.confirmCancel = false; renderSuccess(state, doc, true); }
    if (type === 'cancel-yes') cancelBooking(state, doc);
  });
  dialog.addEventListener('cancel', (event) => {
    if (state.submitting || state.cancelPending) event.preventDefault();
  });
  dialog.addEventListener('change', (event) => {
    const { target } = event;
    if (target.type === 'checkbox') {
      state.consent = target.checked;
      const submit = dialog.querySelector('[data-action="submit"]');
      if (submit) submit.setAttribute('aria-disabled', state.seat && state.consent ? 'false' : 'true');
    } else if (target.name === 'booking-day') {
      state.day = target.value;
      const day = state.data.days.find((item) => item.date === state.day);
      state.start = (day?.slots || []).find((item) => item.bookable)?.start ?? null;
      state.seat = '';
      renderForm(state, doc, keyForDay(state.day));
      if (state.start !== null) loadSeats(state, doc, keyForDay(state.day));
    } else if (target.name === 'booking-slot') {
      state.start = Number(target.value);
      state.seat = '';
      renderForm(state, doc, `input[name="booking-slot"][value="${state.start}"]`);
      loadSeats(state, doc, `input[name="booking-slot"][value="${state.start}"]`);
    } else if (target.name === 'booking-seat') {
      state.seat = target.value;
      renderForm(state, doc, `input[name="booking-seat"][value="${state.seat}"]`);
    }
  });
  dialog.addEventListener('close', () => {
    if (state.abort) state.abort.abort();
    const opener = state.opener;
    if (opener && opener.isConnected) opener.focus();
    else {
      const replacement = state.list.querySelector(`[data-booking="${state.key}"]`);
      if (replacement) replacement.focus();
      else focusQuery(doc, '#kultur-title');
    }
  });
  return dialog;
}

function noticeMarkup() {
  return `<aside class="booking-notice" id="randevu-notice"><p>${esc(t('ui.booking.notice', 'Örnek: İBB kütüphane randevu sistemine bağlı değildir.'))}</p><p>${esc(t('ui.booking.room_note', 'Salon planı ve kapasite örnektir; kütüphanenin gerçek doluluğunu göstermez. Dolu koltuklar yalnız Nabız\'da alınan örnek randevulardır.'))}</p></aside>`;
}

function renderLoading(state, doc) {
  state.dialog.innerHTML = `<div class="booking-sheet"><h2 id="randevu-title" tabindex="-1">${esc(t('ui.booking.title', 'Kütüphane randevusu (örnek)'))}</h2>${noticeMarkup()}<p class="booking-status" role="status" aria-live="polite">${esc(t('ui.booking.loading_library', 'Kayıtlar yükleniyor.'))}</p><div class="booking-actions"><button class="btn btn-quiet" type="button" data-action="close">${esc(t('ui.booking.close', 'Vazgeç'))}</button></div><p class="booking-footnote">${esc(t('ui.culture.note_holidays', 'Resmî tatil ve özel kapanışlar kayıtta yok; gitmeden önce arayın.'))} ${esc(t('ui.culture.disclaimer', 'Resmî İBB hizmeti değildir.'))}</p></div>`;
  focusQuery(doc, '#randevu-title');
}

function renderLoadError(state, doc) {
  state.dialog.innerHTML = `<div class="booking-sheet"><h2 id="randevu-title" tabindex="-1">${esc(t('ui.booking.title', 'Kütüphane randevusu (örnek)'))}</h2>${noticeMarkup()}<p class="booking-status" tabindex="-1" role="status" aria-live="polite">${icon('alert-triangle')}${esc(state.status)}</p><div class="booking-actions"><button class="btn btn-quiet" type="button" data-action="close">${esc(t('ui.booking.close', 'Vazgeç'))}</button></div><p class="booking-footnote">${esc(t('ui.culture.note_holidays', 'Resmî tatil ve özel kapanışlar kayıtta yok; gitmeden önce arayın.'))} ${esc(t('ui.culture.disclaimer', 'Resmî İBB hizmeti değildir.'))}</p></div>`;
  focusQuery(doc, '#randevu-title');
}

function dayMarkup(state) {
  const rows = state.data.days.map((day) => {
    const available = day.open && (day.slots || []).some((slot) => slot.bookable);
    const text = esc(dayText(day, currentLang(), state.data.days[0]?.date || day.date));
    if (!available) return `<span class="booking-day-closed">${text}</span>`;
    return `<label class="booking-choice"><input class="sr-only" type="radio" name="booking-day" value="${esc(day.date)}" aria-label="${text}"${state.day === day.date ? ' checked' : ''}><span>${text}</span></label>`;
  });
  return `<fieldset class="booking-group"><legend>${esc(t('ui.booking.day_legend', 'Gün'))}</legend><div class="booking-choices">${rows.join('')}</div></fieldset>`;
}

function selectedDay(state) {
  return state.data.days.find((day) => day.date === state.day) || null;
}

function renderForm(state, doc, focus = '') {
  const library = state.data.library;
  const day = selectedDay(state);
  const slots = day ? (day.slots || []).filter((slot) => slot.bookable) : [];
  const selectedSlot = slots.find((slot) => slot.start === state.start) || null;
  const held = state.seats && state.seats.mine;
  const hasSlots = Boolean(day && selectedSlot);
  const slotMarkup = hasSlots ? `<fieldset class="booking-group"><legend>${esc(t('ui.booking.slot_legend', 'Saat aralığı'))}</legend><div class="booking-choices">${slots.map((slot) => `<label class="booking-choice"><input class="sr-only" type="radio" name="booking-slot" value="${slot.start}" aria-label="${esc(slotText(slot))}"${slot.start === state.start ? ' checked' : ''}><span>${esc(slotText(slot))}</span></label>`).join('')}</div></fieldset>` : '';
  let seatContent = '';
  if (hasSlots) {
    if (state.loading) seatContent = `<fieldset class="booking-seats" aria-busy="true"><legend>${esc(t('ui.booking.seat_legend', 'Koltuk seçin: {room}, {capacity} koltuk', { room: t('ui.booking.room', 'Çalışma salonu (örnek)'), capacity: state.data.room.capacity }))}</legend><p class="booking-room-state">${esc(t('ui.booking.loading', 'Koltuklar yükleniyor.'))}</p></fieldset>`;
    else if (state.seats) seatContent = `${seatMapMarkup(state.data.room, state.seats.taken, state.seats.mine, state.seat)}${legendMarkup()}`;
    else seatContent = `<p class="booking-status" role="status" aria-live="polite">${esc(t('ui.booking.loading', 'Koltuklar yükleniyor.'))}</p>`;
  }
  const status = state.status || (!hasSlots ? t('ui.booking.none', 'Önümüzdeki 7 günde seçilebilir saat yok.') : '');
  const statusMarkup = status ? `<p class="booking-status" tabindex="-1" role="status" aria-live="polite">${state.isError ? icon('alert-triangle') : ''}${esc(status)}</p>` : '<p class="booking-status" tabindex="-1" role="status" aria-live="polite"></p>';
  const heldMarkup = held ? `<p class="booking-has-mine">${esc(t('ui.booking.has_booking', 'Bu saatte randevunuz var: koltuk {seat}.', { seat: held.seat }))}</p>` : '';
  const actions = hasSlots ? `${heldMarkup ? `<button class="btn btn-quiet" type="button" data-action="cancel-start">${esc(t('ui.booking.cancel', 'Randevuyu iptal et'))}</button>` : `<button class="btn btn-primary" type="button" data-action="submit" aria-disabled="${state.seat && state.consent ? 'false' : 'true'}">${esc(t('ui.booking.submit', 'Randevuyu al'))}</button>`}<button class="btn btn-quiet" type="button" data-action="close">${esc(t('ui.booking.close', 'Vazgeç'))}</button>` : `<button class="btn btn-quiet" type="button" data-action="close">${esc(t('ui.booking.close', 'Vazgeç'))}</button>`;
  const consent = hasSlots && !held ? `<div class="booking-consent-wrap"><label class="booking-consent"><input type="checkbox"${state.consent ? ' checked' : ''}> <span>${esc(t('ui.booking.consent', 'Kütüphane, gün, saat ve koltuk seçimimin, bu cihazın ya da örnek hesabımın kodunun özetiyle birlikte Nabız sunucusunda en çok 30 gün saklanmasını kabul ediyorum. Ad, telefon ve TC kimlik istenmez; iptal ettiğimde kayıt hemen silinir.'))}</span></label><details><summary>${esc(t('ui.booking.consent_more', 'Ne saklanır?'))}</summary><p>${esc(t('ui.booking.consent_detail', 'Saklanan: kütüphane, gün, saat aralığı, koltuk, randevu kodu, onay sürümü ve cihaz kodunuzun ya da örnek hesabınızın tuzlu özeti. İBB\'ye ya da kütüphaneye gönderilmez.'))}</p></details></div>` : '';
  state.dialog.innerHTML = `<div class="booking-sheet"><h2 id="randevu-title" tabindex="-1">${esc(t('ui.booking.title', 'Kütüphane randevusu (örnek)'))}</h2><p class="booking-library"><span lang="tr">${esc(library.name)}</span> · <span lang="tr">${esc(library.district)}</span></p>${noticeMarkup()}<p class="booking-hours"><span>${esc(t('ui.booking.hours', 'Kayıtlı çalışma saati'))}:</span> <span lang="tr">${esc(library.hours_text)} · ${esc(library.days_text)}</span></p>${dayMarkup(state)}${slotMarkup}${seatContent ? `<section class="booking-seat-section">${seatContent}</section>` : ''}${consent}${statusMarkup}<div class="booking-actions">${actions}</div><p class="booking-footnote">${esc(t('ui.culture.note_holidays', 'Resmî tatil ve özel kapanışlar kayıtta yok; gitmeden önce arayın.'))} ${esc(t('ui.culture.disclaimer', 'Resmî İBB hizmeti değildir.'))}</p></div>`;
  if (focus) focusQuery(doc, focus);
}

function legendMarkup() {
  return `<ul class="booking-legend"><li><span class="booking-swatch is-free">${icon('armchair')}</span>${esc(t('ui.booking.legend_free', 'Boş'))}</li><li><span class="booking-swatch is-taken"></span>${esc(t('ui.booking.legend_taken', 'Dolu (Nabız\'da ayrılmış)'))}</li><li><span class="booking-swatch is-selected">${icon('circle-check')}</span>${esc(t('ui.booking.legend_selected', 'Seçtiğiniz'))}</li><li><span class="booking-swatch is-accessible">${icon('wheelchair')}</span>${esc(t('ui.booking.legend_accessible', 'Erişilebilir masa'))}</li></ul>`;
}

async function loadSeats(state, doc, focus = '') {
  if (!state.data || state.start === null) return;
  if (state.abort) state.abort.abort();
  state.abort = new AbortController();
  const request = state.abort;
  state.loading = true;
  state.seats = null;
  state.status = '';
  renderForm(state, doc, focus || '#randevu-title');
  try {
    const query = new URLSearchParams({ library: state.key, day: state.day, start: String(state.start) });
    state.seats = await api(`/api/booking/seats?${query}`, { signal: request.signal });
    if (state.abort !== request || request.signal.aborted) return;
    state.isError = false;
  } catch (error) {
    if (error.name === 'AbortError' || state.abort !== request) return;
    state.status = errorText(error.code || 'offline', error.body || {});
    state.isError = true;
  }
  state.loading = false;
  renderForm(state, doc, focus || '#randevu-title');
}

async function openBooking(state, doc, key, opener) {
  if (state.abort) state.abort.abort();
  state.abort = new AbortController();
  const request = state.abort;
  state.key = key;
  state.opener = opener;
  state.data = null;
  state.status = '';
  state.result = null;
  state.existing = false;
  state.cancelled = false;
  state.isError = false;
  state.confirmCancel = false;
  state.detailsLoading = true;
  const dialog = ensureDialog(doc, state);
  renderLoading(state, doc);
  dialog.showModal();
  try {
    state.data = await api(`/api/booking/libraries/${encodeURIComponent(key)}`, { signal: request.signal });
    if (state.abort !== request || request.signal.aborted) return;
    state.detailsLoading = false;
  } catch (error) {
    if (error.name === 'AbortError' || state.abort !== request) return;
    state.detailsLoading = false;
    state.status = errorText(error.code || 'offline', error.body || {});
    state.isError = true;
    renderLoadError(state, doc);
    return;
  }
  const firstDay = state.data.days.find((item) => item.open && (item.slots || []).some((slot) => slot.bookable));
  state.day = firstDay ? firstDay.date : null;
  state.start = firstDay ? firstDay.slots.find((slot) => slot.bookable).start : null;
  state.seat = '';
  state.consent = false;
  state.seats = null;
  state.loading = Boolean(firstDay);
  state.status = '';
  state.isError = false;
  renderForm(state, doc, '#randevu-title');
  if (firstDay) loadSeats(state, doc);
}

async function submitBooking(state, doc) {
  const seat = state.dialog.querySelector('input[name="booking-seat"]:checked');
  const consent = state.dialog.querySelector('.booking-consent input');
  if (!seat || state.start === null) {
    state.status = t('ui.booking.pick_seat', 'Bir koltuk seçin.');
    state.isError = false;
    renderForm(state, doc, '.booking-seats');
    return;
  }
  if (!consent || !consent.checked) {
    state.status = t('ui.booking.consent_error', 'Randevu için onay kutusunu işaretleyin.');
    state.isError = true;
    renderForm(state, doc, '.booking-consent input');
    return;
  }
  const button = state.dialog.querySelector('[data-action="submit"]');
  if (!button || state.submitting || button.getAttribute('aria-disabled') === 'true') return;
  state.submitting = true;
  button.setAttribute('aria-busy', 'true');
  state.dialog.querySelector('.booking-status').textContent = t('ui.booking.busy', 'Randevu kaydediliyor.');
  try {
    state.result = await api('/api/booking', {
      method: 'POST',
      body: JSON.stringify({ library: state.key, day: state.day, start: state.start, seat: seat.value, consent: true }),
    });
    state.submitting = false;
    state.status = '';
    state.isError = false;
    state.confirmCancel = false;
    renderSuccess(state, doc, false);
  } catch (error) {
    state.submitting = false;
    state.status = errorText(error.code || 'offline', error.body || {});
    state.isError = true;
    if (error.code === 'seat_taken') {
      state.seat = '';
      const message = state.status;
      await loadSeats(state, doc, '.booking-seats');
      state.status = message;
      state.isError = true;
      renderForm(state, doc, '.booking-seats');
    } else if (error.code === 'not_offered') {
      state.data = await api(`/api/booking/libraries/${encodeURIComponent(state.key)}`).catch(() => state.data);
      const firstDay = state.data.days.find((item) => item.open && (item.slots || []).some((slot) => slot.bookable));
      state.day = firstDay ? firstDay.date : null;
      state.start = firstDay ? firstDay.slots.find((slot) => slot.bookable).start : null;
      state.seat = '';
      const message = state.status;
      renderForm(state, doc, firstDay ? keyForDay(state.day) : '#randevu-title');
      if (firstDay) await loadSeats(state, doc, keyForDay(state.day));
      state.status = message;
      state.isError = true;
      renderForm(state, doc, '.booking-status');
    } else renderForm(state, doc, '.booking-status');
  }
}

function renderSuccess(state, doc, focus) {
  const result = state.result;
  if (!result) return;
  if (state.cancelled) {
    state.dialog.innerHTML = `<div class="booking-sheet"><h2 id="randevu-title" tabindex="-1">${esc(t('ui.booking.cancelled_title', 'Randevunuz iptal edildi (örnek)'))}</h2>${noticeMarkup()}<p class="booking-status" role="status" aria-live="polite">${esc(t('ui.booking.cancelled', 'Randevu iptal edildi; kayıt silindi.'))}</p><div class="booking-actions"><button class="btn btn-primary" type="button" data-action="close">${esc(t('ui.booking.ok', 'Tamam'))}</button></div></div>`;
  } else {
    const confirm = state.confirmCancel ? `<p class="booking-cancel-confirm" role="status">${esc(t('ui.booking.cancel_confirm', 'Randevu iptal edilsin mi? Koltuk yeniden boş olur.'))}</p><div class="booking-actions"><button class="btn btn-primary" type="button" data-action="cancel-yes">${esc(t('ui.booking.cancel_yes', 'Evet, iptal et'))}</button><button class="btn btn-quiet" type="button" data-action="cancel-no">${esc(t('ui.booking.cancel_no', 'Vazgeç'))}</button></div>` : `<div class="booking-actions"><button class="btn btn-primary" type="button" data-action="close">${esc(t('ui.booking.ok', 'Tamam'))}</button><button class="btn btn-quiet" type="button" data-action="cancel-start">${esc(t('ui.booking.cancel', 'Randevuyu iptal et'))}</button></div>`;
    const day = state.data.days.find((item) => item.date === result.day);
    const text = t('ui.booking.done_line', '{library} · {day} {slot} · koltuk {seat}', {
      library: '__LIBRARY__',
      day: t('ui.booking.day_label', '{day} {date}', { day: dayName(day?.weekday || 0), date: `${result.day.slice(8, 10)}.${result.day.slice(5, 7)}` }),
      slot: slotText(result), seat: result.seat,
    });
    const [beforeLibrary, afterLibrary] = text.split('__LIBRARY__');
    const resultTitle = state.existing ? t('ui.booking.title', 'Kütüphane randevusu (örnek)') : t('ui.booking.done_title', 'Randevunuz alındı (örnek)');
    state.dialog.innerHTML = `<div class="booking-sheet"><h2 id="randevu-title" tabindex="-1">${esc(resultTitle)}</h2>${noticeMarkup()}<p class="booking-summary">${esc(beforeLibrary)}<span lang="tr">${esc(result.library.name)}</span>${esc(afterLibrary)}</p><p>${esc(t('ui.booking.code', 'Randevu kodu: {code}', { code: result.code }))}</p><p>${esc(result.held_by === 'account' ? t('ui.booking.held_account', 'Bu randevu örnek hesabınıza bağlı.') : t('ui.booking.held_device', 'Bu randevu bu cihaza bağlı.'))}</p><p>${esc(t('ui.booking.ttl', 'Kayıt 30 gün sonra kendiliğinden silinir; kütüphane bu randevuyu görmez.'))}</p>${state.status ? `<p class="booking-status" tabindex="-1" role="status" aria-live="polite">${state.isError ? icon('alert-triangle') : ''}${esc(state.status)}</p>` : ''}${confirm}<p class="booking-footnote">${esc(t('ui.culture.disclaimer', 'Resmî İBB hizmeti değildir.'))}</p></div>`;
  }
  if (focus) focusQuery(doc, '#randevu-title');
}

async function cancelBooking(state, doc) {
  if (state.cancelPending) return;
  state.cancelPending = true;
  try {
    await api(`/api/booking/${encodeURIComponent(state.result.code)}`, { method: 'DELETE' });
    state.cancelPending = false;
    state.cancelled = true;
    state.confirmCancel = false;
    renderSuccess(state, doc, true);
  } catch (error) {
    state.cancelPending = false;
    state.status = errorText(error.code || 'offline', error.body || {});
    state.isError = true;
    state.confirmCancel = false;
    renderSuccess(state, doc, true);
  }
}

function mountBooking(doc) {
  if (MOCK) return;
  const list = doc.querySelector('#kultur .culture-list');
  if (!list) return;
  ensureStyles(doc);
  const state = { list, dialog: null, libraries: null, asked: false, key: '', opener: null, data: null, seats: null, seat: '', start: null, day: null, consent: false, loading: false, detailsLoading: false, status: '', isError: false, abort: null, result: null, existing: false, cancelled: false, confirmCancel: false, submitting: false, cancelPending: false };
  const observe = async () => {
    if (!list.querySelector('li.culture-item')) return;
    if (!state.asked) {
      state.asked = true;
      try { state.libraries = (await api('/api/booking/libraries')).libraries || []; } catch { state.libraries = []; }
    }
    if (!state.libraries) return;
    const byName = new Map(state.libraries.map((item) => [item.name, item.key]));
    list.querySelectorAll('li.culture-item').forEach((item) => {
      const existingButton = item.querySelector('.booking-open');
      if (existingButton) {
        existingButton.lang = currentLang();
        existingButton.innerHTML = `${icon('armchair')} ${esc(t('ui.booking.open', 'Randevu al (örnek)'))}`;
        return;
      }
      const name = item.querySelector('.culture-name');
      const key = name && byName.get(name.textContent.trim());
      if (!key) return;
      const action = doc.createElement('p');
      action.className = 'booking-card-action';
      const button = doc.createElement('button');
      button.type = 'button';
      button.className = 'btn btn-quiet booking-open';
      button.dataset.booking = key;
      button.setAttribute('aria-haspopup', 'dialog');
      button.lang = currentLang();
      button.innerHTML = `${icon('armchair')} ${esc(t('ui.booking.open', 'Randevu al (örnek)'))}`;
      action.appendChild(button);
      item.appendChild(action);
    });
  };
  list.addEventListener('click', (event) => {
    const button = event.target.closest('.booking-open');
    if (button) openBooking(state, doc, button.dataset.booking, button);
  });
  const Observer = doc.defaultView && doc.defaultView.MutationObserver ? doc.defaultView.MutationObserver : globalThis.MutationObserver;
  if (typeof Observer === 'function') {
    const observer = new Observer(observe);
    observer.observe(list, { childList: true, subtree: false });
  }
  observe();
  onLang(() => {
    if (state.dialog && state.dialog.open) {
      if (state.result) renderSuccess(state, doc, false);
      else if (state.data) renderForm(state, doc);
      else if (state.detailsLoading) renderLoading(state, doc);
      else if (state.status) renderLoadError(state, doc);
      else renderLoading(state, doc);
    }
    observe();
  });
}

export { mountBooking, hhmm, slotText, dayText, seatLabel, seatMapMarkup, errorText };

if (typeof document !== 'undefined') mountBooking(document);
