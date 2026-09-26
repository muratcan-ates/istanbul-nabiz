/* Saved stops stay on this device; the strip reads only the public arrival and station views. */
import { arrivalDisplay, lineBadge } from './cards.js';
import { REFRESH_MS } from './config.js';
import { esc, trName } from './format.js';
import { icon } from './icons.js';
import { savedPlaces, readMemory, readProfile } from './profile.js';
import { ageText } from './provenance.js';
const STORE_KEY = 'nabiz.my-stops.v1', ASKED_KEY = 'nabiz.my-stops.asked.v1';
const ASK_THRESHOLD = 3, MAX_ITEMS = 6, MAX_ASKED = 20;
const METRO_LINE = /^(?:M\d+[AB]?|T\d|TF\d|F\d)$/;
function stopKey(line, stop) { return `${String(line || '').trim().toLocaleUpperCase('tr')}|${String(stop || '').replace(/\s+/g, ' ').trim().toLocaleLowerCase('tr')}`; }
function cleanPair(pair) {
  if (!pair || typeof pair !== 'object') return null;
  const line = String(pair.line || '').trim().toLocaleUpperCase('tr'), stop = String(pair.stop || '').replace(/\s+/g, ' ').trim();
  return line && stop && line.length <= 12 && stop.length <= 80
    ? { line, stop, added_at: typeof pair.added_at === 'string' ? pair.added_at : '' } : null;
}
function uniquePairs(pairs) {
  const seen = new Set();
  return (Array.isArray(pairs) ? pairs : []).map(cleanPair).filter((pair) => {
    const key = pair && stopKey(pair.line, pair.stop);
    if (!key || seen.has(key)) return false;
    seen.add(key); return true;
  });
}
function readStore() {
  try {
    const raw = window.localStorage.getItem(STORE_KEY), data = raw ? JSON.parse(raw) : null;
    return data?.v === 1 && Array.isArray(data.pairs) ? uniquePairs(data.pairs).slice(0, MAX_ITEMS) : [];
  } catch (err) { return []; }
}
function writeStore(pairs) {
  try {
    window.localStorage.setItem(STORE_KEY, JSON.stringify({ v: 1, pairs: uniquePairs(pairs).slice(0, MAX_ITEMS) }));
    return true;
  } catch (err) { return false; }
}
function buildItems(profile, memory, pairs) {
  const places = savedPlaces({
    stations: Array.isArray(profile?.stations) ? profile.stations : [],
    lines: Array.isArray(profile?.lines) ? profile.lines : [],
  }, Array.isArray(memory) ? memory : []);
  const items = [], seen = new Set(), clean = uniquePairs(pairs);
  const add = (item, identity) => {
    if (identity && !seen.has(identity) && items.length < MAX_ITEMS) { seen.add(identity); items.push(item); }
  };
  clean.forEach((pair) => add({ kind: 'stop', line: pair.line, stop: pair.stop, key: stopKey(pair.line, pair.stop) }, `stop:${stopKey(pair.line, pair.stop)}`));
  (places.stations || []).forEach((raw) => {
    const station = String(raw || '').trim();
    if (station) add({ kind: 'station', station, key: `station:${station}` }, `station:${stopKey('', station)}`);
  });
  const paired = new Set(clean.map((pair) => pair.line));
  (places.lines || []).forEach((raw) => {
    const line = String(raw || '').trim().toLocaleUpperCase('tr');
    if (line && !METRO_LINE.test(line) && !paired.has(line)) add({ kind: 'line', line, key: `line:${line}` }, `line:${line}`);
  });
  return items;
}
function requestsFor(item) {
  if (item?.kind === 'stop') return [{ path: '/api/arrival', params: { line: item.line, stop: item.stop } }];
  if (item?.kind === 'station') return [{ path: '/api/alternative', params: { station: item.station, needs: 'step_free' } }];
  return [];
}
function arrivalRow(data) {
  const age = ageText(data?.provenance || null);
  return `<p class="mystop-row mystop-arrival">${icon('bus')}<span class="mystop-value">${esc(arrivalDisplay(data || {}))}</span>`
    + `<span class="mystop-age">${esc(age)}</span></p>`;
}
function liftRow(data, id) {
  const state = ['working', 'out_of_service'].includes(data?.lift_status) ? data.lift_status : 'unknown';
  const labels = {
    working: ['İBB kaydında arıza yok', 'is-ok', 'circle-check'],
    out_of_service: ['asansör arızalı (İBB kaydı)', 'is-warn', 'alert-triangle'],
    unknown: ['asansör durumu doğrulanamadı', 'is-unverified', 'clock-question'],
  };
  const [label, cls, glyph] = labels[state], prefix = data?.stale ? 'son bilinen durum: ' : '';
  let html = `<p class="mystop-row ${cls}">${icon(glyph)}<span>${esc(prefix + label)}</span>`
    + `<span class="mystop-age">${esc(ageText(data?.provenance || null))}</span></p>`;
  if (state !== 'out_of_service') return html;
  const panelId = `${id}-alt`, alt = data.alternative;
  html += `<button type="button" class="btn mystop-stepfree" aria-expanded="false" aria-controls="${esc(panelId)}">`
    + `${icon('wheelchair')}Adımsız yol</button><div class="mystop-alt" id="${esc(panelId)}" hidden>`;
  if (!alt) return html + '<p>İBB kaydında asansör arızası görünmeyen yakın bir istasyon bulunamadı.</p>'
    + '<p><a href="tel:153">153 ile teyit edin</a></p></div>';
  const extra = alt.extra_minutes !== null && Number.isFinite(Number(alt.extra_minutes))
    ? `istasyonlar arası tahminen ${Number(alt.extra_minutes)} dk (dönüş dahil değil)` : 'süre bilinmiyor';
  const approval = data.operator_approved
    ? `<span class="mystop-approval is-ok">${icon('circle-check')}Operatör onaylı (simüle)</span>`
    : `<span class="mystop-approval is-warn">${icon('clock-question')}Operatör onayı yok</span>`;
  return html + `<p>Adımsız alternatif: <b>${esc(trName(alt.station))}</b> ${lineBadge(alt.line)}</p>`
    + `<p>${esc(extra)}</p><p>${esc(alt.reason || '')}</p>${approval}</div>`;
}
function stripMarkup(items, results = {}) {
  const cards = Array.isArray(items) ? items : [];
  const empty = '<li class="mystop mystop-add" id="mystop-0" tabindex="0">'
    + '<h3 class="mystop-title" id="mystop-0-t">Durak ekle</h3>'
    + '<p>Sık kullandığın durağı ekle; varış burada görünür.</p><a href="#profilim">İstasyonu Profilim\'den ekle</a>'
    + '<button type="button" class="btn" id="my-stops-add" aria-expanded="false" aria-controls="my-stops-form">Durak ekle</button></li>';
  const rows = cards.length ? cards.map((item, index) => {
    const id = `mystop-${index}`, result = results[item.key] || {};
    const title = item.kind === 'stop' ? `${lineBadge(item.line)} <span>${esc(trName(item.stop))}</span>`
      : item.kind === 'station' ? esc(trName(item.station)) : lineBadge(item.line);
    let body;
    if (item.kind === 'stop') {
      body = result.error ? `<p class="mystop-row is-warn">${icon('alert-triangle')}<span>Varış alınamadı: ${esc(result.error.message || result.error)}</span></p>`
        : result.data ? arrivalRow(result.data) : '<p class="mystop-row">Varış bilgisi alınıyor.</p>';
      body += `<button type="button" class="link-btn mystop-remove" data-mystop-remove="${esc(item.key)}" `
        + `aria-label="${esc(item.line)} ${esc(item.stop)} kaydını kaldır">Kaldır</button>`;
    } else if (item.kind === 'station') {
      body = result.error ? `<p class="mystop-row is-unverified">${icon('clock-question')}<span>Asansör bilgisi alınamadı: ${esc(result.error.message || result.error)}</span>`
        + '<span class="mystop-age">veri yaşı bilinmiyor</span></p>'
        : result.data ? liftRow(result.data, id) : '<p class="mystop-row">Asansör bilgisi alınıyor.</p>';
      body += '<p class="mystop-manage">Profilim\'den yönetilir</p>';
    } else body = `<button type="button" class="btn" data-mystop-add-line="${esc(item.line)}" aria-expanded="false" `
      + 'aria-controls="my-stops-form">Durak ekle</button>';
    return `<li class="mystop" id="${id}" tabindex="${index ? '-1' : '0'}" aria-labelledby="${id}-t">`
      + `<h3 class="mystop-title" id="${id}-t">${title}</h3>${body}</li>`;
  }).join('') : empty;
  return `<ul class="mystops-strip" aria-label="Kayıtlı duraklar ve istasyonlar">${rows}</ul>`;
}
function normalizeAsked(state) {
  if (!state || state.v !== 1 || !state.asked || typeof state.asked !== 'object' || Array.isArray(state.asked)) return { v: 1, asked: {} };
  const asked = {};
  Object.entries(state.asked).forEach(([key, entry]) => {
    if (entry && typeof entry.line === 'string' && typeof entry.stop === 'string') {
      asked[key] = { line: entry.line, stop: entry.stop, n: Math.max(0, Number(entry.n) || 0), no: entry.no === true };
    }
  });
  return { v: 1, asked };
}
function bumpAsk(state, line, stop, savedKeys = []) {
  const next = normalizeAsked(state), key = stopKey(line, stop);
  const prior = next.asked[key] || { line: String(line).trim().toLocaleUpperCase('tr'), stop: String(stop).replace(/\s+/g, ' ').trim(), n: 0, no: false };
  next.asked[key] = { ...prior, n: prior.n + 1 };
  while (Object.keys(next.asked).length > MAX_ASKED) delete next.asked[Object.keys(next.asked)[0]];
  const saved = savedKeys instanceof Set ? savedKeys.has(key) : Array.isArray(savedKeys) && savedKeys.includes(key);
  return { state: next, suggest: next.asked[key].n >= ASK_THRESHOLD && !next.asked[key].no && !saved };
}
function dismissAsk(state, key) {
  const next = normalizeAsked(state);
  if (next.asked[key]) next.asked[key] = { ...next.asked[key], no: true };
  return next;
}
function readAsked() {
  try { const raw = window.localStorage.getItem(ASKED_KEY); return normalizeAsked(raw ? JSON.parse(raw) : null); }
  catch (err) { return { v: 1, asked: {} }; }
}
function writeAsked(state) {
  try { window.localStorage.setItem(ASKED_KEY, JSON.stringify(normalizeAsked(state))); return true; }
  catch (err) { return false; }
}
function addStylesheet() {
  if (document.querySelector('[data-my-stops-styles]')) return;
  const link = document.createElement('link'); link.rel = 'stylesheet'; link.href = '/css/my_stops.css'; link.dataset.myStopsStyles = '';
  document.head.append(link);
}
async function mountMyStops(host) {
  if (!host || typeof document === 'undefined') return;
  addStylesheet();
  host.innerHTML = '<section class="mystops" aria-labelledby="my-stops-title">'
    + '<div class="mystops-head"><h2 id="my-stops-title">Duraklarım</h2><span class="section-note">yalnız bu cihazda</span></div>'
    + '<div id="my-stops-suggest" role="group" aria-label="Durak önerisi" hidden></div>'
    + '<ul class="mystops-strip" id="my-stops-list" aria-label="Kayıtlı duraklar ve istasyonlar"></ul>'
    + '<form id="my-stops-form" class="mystops-form" autocomplete="off" novalidate hidden>'
    + '<label for="my-stops-line">Hat</label><input id="my-stops-line" name="line" type="text" maxlength="12" autocapitalize="characters" required>'
    + '<label for="my-stops-stop">Durak</label><input id="my-stops-stop" name="stop" type="text" maxlength="80" required>'
    + '<button type="submit" class="btn btn-primary">Ekle</button> <button type="button" class="btn" id="my-stops-cancel">Vazgeç</button>'
    + '<p class="field-error" id="my-stops-error" role="alert" hidden></p></form><p class="sr-only" id="my-stops-status" role="status"></p></section>';
  const { get } = await import('./api.js');
  const list = host.querySelector('#my-stops-list'), form = host.querySelector('#my-stops-form');
  const lineInput = host.querySelector('#my-stops-line'), stopInput = host.querySelector('#my-stops-stop');
  const errorBox = host.querySelector('#my-stops-error'), status = host.querySelector('#my-stops-status');
  const suggestion = host.querySelector('#my-stops-suggest');
  let asked = readAsked(), controller = null, inMemory = readStore();
  const beginTurn = () => { if (controller) controller.abort(); controller = new AbortController(); return controller; };
  const currentItems = () => buildItems(readProfile(), readMemory(), inMemory);
  const draw = (items, results) => {
    const template = document.createElement('template'); template.innerHTML = stripMarkup(items, results);
    const markup = template.content.querySelector('ul').innerHTML;
    if (list.innerHTML === markup) return;
    const active = document.activeElement?.closest?.('.mystop'), activeId = active && list.contains(active) ? active.id : '';
    list.innerHTML = markup;
    const target = activeId && list.querySelector(`#${activeId}`);
    if (target) target.focus({ preventScroll: true });
  };
  const refresh = async () => {
    const items = currentItems(), turn = beginTurn();
    if (document.visibilityState === 'hidden') return;
    const results = {};
    await Promise.all(items.flatMap((item) => requestsFor(item).map(async (request) => {
      try { results[item.key] = { data: await get(request.path, request.params, turn.signal) }; }
      catch (err) { if (!turn.signal.aborted) results[item.key] = { error: err }; }
    })));
    if (turn === controller && !turn.signal.aborted) draw(items, results);
  };
  const closeForm = () => {
    form.hidden = true; form.reset(); host.querySelector('#my-stops-add')?.setAttribute('aria-expanded', 'false');
    host.querySelectorAll('[data-mystop-add-line]').forEach((button) => button.setAttribute('aria-expanded', 'false'));
  };
  const openForm = (line = '') => {
    form.hidden = false; lineInput.value = line; errorBox.hidden = true;
    host.querySelector('#my-stops-add')?.setAttribute('aria-expanded', 'true');
    host.querySelectorAll('[data-mystop-add-line]').forEach((button) => button.setAttribute('aria-expanded', button.dataset.mystopAddLine === line ? 'true' : 'false'));
    stopInput.focus();
  };
  list.addEventListener('focusin', (event) => {
    const card = event.target.closest('.mystop');
    if (card) [...list.querySelectorAll('.mystop')].forEach((item) => { item.tabIndex = item === card ? 0 : -1; });
  });
  list.addEventListener('keydown', (event) => {
    if (!['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(event.key)) return;
    const cards = [...list.querySelectorAll('.mystop')], index = cards.indexOf(event.target.closest('.mystop'));
    if (index < 0) return;
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? cards.length - 1
      : (index + (event.key === 'ArrowRight' ? 1 : -1) + cards.length) % cards.length;
    event.preventDefault(); cards.forEach((card, i) => { card.tabIndex = i === next ? 0 : -1; });
    cards[next].focus(); cards[next].scrollIntoView({ block: 'nearest', inline: 'nearest' });
  });
  list.addEventListener('click', async (event) => {
    const step = event.target.closest('.mystop-stepfree');
    if (step) {
      const panel = host.querySelector(`#${step.getAttribute('aria-controls')}`), open = step.getAttribute('aria-expanded') !== 'true';
      step.setAttribute('aria-expanded', String(open)); panel.hidden = !open;
      if (open) status.textContent = 'Adımsız yol gösterildi.';
      return;
    }
    const remove = event.target.closest('[data-mystop-remove]');
    if (remove) {
      const key = remove.dataset.mystopRemove, next = inMemory.filter((pair) => stopKey(pair.line, pair.stop) !== key);
      if (!writeStore(next)) { status.textContent = 'Kaydedilemedi: tarayıcı depolamaya izin vermiyor.'; return; }
      inMemory = next; status.textContent = 'Durak kaldırıldı.'; await refresh(); return;
    }
    if (event.target.closest('#my-stops-add')) openForm();
    const addLine = event.target.closest('[data-mystop-add-line]');
    if (addLine) openForm(addLine.dataset.mystopAddLine);
  });
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const line = lineInput.value.trim().toLocaleUpperCase('tr'), stop = stopInput.value.replace(/\s+/g, ' ').trim();
    if (!line || !stop) { errorBox.textContent = 'Hat ve durak yazın.'; errorBox.hidden = false; return; }
    errorBox.hidden = true;
    const turn = beginTurn();
    try {
      await get('/api/arrival', { line, stop }, turn.signal);
      if (turn !== controller || turn.signal.aborted) return;
      const next = [...inMemory.filter((pair) => stopKey(pair.line, pair.stop) !== stopKey(line, stop)), { line, stop, added_at: new Date().toISOString() }];
      if (!writeStore(next)) { errorBox.textContent = 'Kaydedilemedi: tarayıcı depolamaya izin vermiyor.'; errorBox.hidden = false; return; }
      inMemory = next; closeForm(); status.textContent = `${line}, ${trName(stop)} eklendi.`; await refresh();
    } catch (err) {
      if (turn === controller && !turn.signal.aborted) { errorBox.textContent = err.message; errorBox.hidden = false; }
    }
  });
  host.querySelector('#my-stops-cancel').addEventListener('click', closeForm);
  const arrivalForm = document.querySelector('#arrival-form');
  if (arrivalForm) arrivalForm.addEventListener('submit', (event) => {
    const line = arrivalForm.elements.line?.value.trim(), stop = arrivalForm.elements.stop?.value.replace(/\s+/g, ' ').trim();
    if (!line || !stop) return;
    const update = bumpAsk(asked, line, stop, new Set(inMemory.map((pair) => stopKey(pair.line, pair.stop))));
    asked = update.state; writeAsked(asked);
    if (!update.suggest) return;
    const turn = beginTurn();
    get('/api/arrival', { line, stop }, turn.signal).then(() => {
      if (turn !== controller || turn.signal.aborted) return;
      suggestion.innerHTML = `<p>Bu durağı ${ASK_THRESHOLD} kez sordun. Duraklarıma ekleyeyim mi? `
        + `<b>${lineBadge(line)} ${esc(trName(stop))}</b></p><div class="btn-row">`
        + '<button type="button" class="btn btn-primary" data-mystop-suggest="yes">Evet</button>'
        + '<button type="button" class="btn" data-mystop-suggest="no">Hayır</button></div>'
        + '<p class="field-hint">Onaylamazsan hiçbir şey kaydedilmez. Kayıt yalnız bu tarayıcıda durur.</p>';
      suggestion.dataset.key = stopKey(line, stop); suggestion.dataset.line = line; suggestion.dataset.stop = stop;
      suggestion.hidden = false; status.textContent = 'Duraklarına ekleme önerisi var.';
    }).catch(() => {});
  });
  suggestion.addEventListener('click', async (event) => {
    const answer = event.target.closest('[data-mystop-suggest]')?.dataset.mystopSuggest;
    if (!answer) return;
    const { key, line, stop } = suggestion.dataset;
    if (answer === 'no') {
      asked = dismissAsk(asked, key); writeAsked(asked); suggestion.hidden = true; status.textContent = 'Eklenmedi.'; return;
    }
    const next = [...inMemory.filter((pair) => stopKey(pair.line, pair.stop) !== key), { line, stop, added_at: new Date().toISOString() }];
    if (!writeStore(next)) { status.textContent = 'Kaydedilemedi: tarayıcı depolamaya izin vermiyor.'; return; }
    inMemory = next; suggestion.hidden = true; status.textContent = 'Eklendi. Duraklarım şeridinde; Kaldır ile silinir.'; await refresh();
  });
  const observer = new MutationObserver(() => { refresh(); });
  ['#stations-list', '#memory-list'].forEach((selector) => {
    const target = document.querySelector(selector);
    if (target) observer.observe(target, { childList: true, subtree: true });
  });
  window.addEventListener('storage', () => { inMemory = readStore(); asked = readAsked(); refresh(); });
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') refresh(); else if (controller) controller.abort();
  });
  setInterval(() => { if (document.visibilityState === 'visible') refresh(); }, REFRESH_MS); draw(currentItems(), {}); await refresh();
}
if (typeof document !== 'undefined') {
  const boot = () => { const host = document.getElementById('my-stops'); if (host) mountMyStops(host); };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true }); else boot();
}
export { STORE_KEY, ASKED_KEY, ASK_THRESHOLD, MAX_ITEMS, MAX_ASKED, stopKey, readStore, writeStore, buildItems,
  requestsFor, arrivalRow, liftRow, stripMarkup, bumpAsk, dismissAsk, mountMyStops };
