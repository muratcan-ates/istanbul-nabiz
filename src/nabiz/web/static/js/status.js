/* The state of #results while an answer loads (spec 8.3), and #answer-status, which says one
 * sentence per answer: #results is not a live region, because re-reading a whole answer is noise. */

const $ = (sel) => document.querySelector(sel);
const LOADING = 'İBB uçlarından okunuyor. İlk sorgu birkaç saniye sürebilir.';
const SLOW = 'Kaynak yavaş yanıt veriyor; beklemeye devam ediyoruz.';
/* The skeleton takes the answer's shape, so the page does not jump when it lands. */
const ROWS = { parking: 3, arrivals: 3, bus: 3, route: 3, air: 2, stops: 3, places: 3 };
let timers = [];

function announce(text) {
  const status = $('#answer-status');
  if (status) status.textContent = text;
}

const line = (text) => `<p class="panel-note" data-loading>${text}</p>`;

function skeleton(rows) {
  const block = `<div class="skeleton">${'<i class="skeleton-line"></i>'.repeat(3)}</div>`;
  return `<div class="sheet" data-loading aria-hidden="true">${block.repeat(rows)}</div>`;
}

/**
 * `journey` starts the loading state in that answer's shape; null ends it. The previous answer
 * dims and goes inert at once, a skeleton replaces it only after 400 ms (a fast answer never
 * flashes one), and after 6 s a sentence says the source is slow. "Sor" is aria-disabled, never
 * disabled: a disabled button drops keyboard focus to <body>.
 */
function loading(journey) {
  const results = $('#results');
  timers.forEach(clearTimeout);
  timers = [];
  results.setAttribute('aria-busy', journey ? 'true' : 'false');
  $('#ask-submit').setAttribute('aria-disabled', journey ? 'true' : 'false');
  if (!journey) return;
  // Focus inside the old answer would drop to <body> once it is inert, so it moves first.
  if (results.contains(document.activeElement) && document.activeElement !== results) results.focus({ preventScroll: true });
  results.querySelectorAll('[data-loading]').forEach((el) => el.remove());
  [...results.children].forEach((el) => { el.inert = true; });
  results.insertAdjacentHTML('afterbegin', line(LOADING));
  announce('Yükleniyor.');
  timers.push(setTimeout(() => { results.innerHTML = line(LOADING) + skeleton(ROWS[journey] || 1); }, 400));
  timers.push(setTimeout(() => results.insertAdjacentHTML('beforeend', line(SLOW)), 6000));
}

export { announce, loading };
