/* Integrity drills only touch a temporary database copy; the ledger badge stays independent. */

import { post } from './api.js';
import { esc } from './format.js';
import { icon } from './icons.js';
import { errorCard } from './cards.js';

export const DRILL_KINDS = [
  { kind: 'detay', label: 'Detayı değiştir', glyph: 'list-details' },
  { kind: 'silme', label: 'Kaydı sil', glyph: 'alert-triangle' },
  { kind: 'sira', label: 'Sırayı boz', glyph: 'arrows-exchange' },
  { kind: 'hash', label: 'Mührü yeniden hesapla', glyph: 'shield-lock' },
];

let lastResult = null;
const mountedHosts = new WeakMap();

export function drillControls() {
  const buttons = DRILL_KINDS.map(({ kind, label, glyph }) =>
    `<button type="button" class="btn" data-nx-drill="${kind}" aria-disabled="false">${icon(glyph)}<span>${label}</span></button>`
  ).join('');
  return '<details class="more nx-drill"><summary>Tatbikat: defterin kopyasında bir kaydı boz</summary>'
    + `<p class="nx-drill-lead">Doğrulama yakalasın.</p><div class="btn-row nx-drill-controls">${buttons}</div>`
    + '<p class="sr-only" id="nx-drill-status" role="status" aria-live="polite"></p>'
    + '<div id="nx-drill-result"></div></details>';
}

export function drillCard(result) {
  const original = result.original || {};
  const badge = original.unchanged
    ? '<span class="tag is-ok">tatbikat · gerçek defter değişmedi</span>'
    : `<span class="tag ${original.verify_ok ? 'is-ok' : 'is-bad'}">${esc(result.note || '')}</span>`;
  const caught = result.caught === false
    ? '<p class="tag is-bad">Doğrulama bu bozulmayı yakalamadı</p>'
    : '';
  const before = String(original.sha256_before || '').slice(0, 12);
  const after = String(original.sha256_after || '').slice(0, 12);
  return '<article class="card nx-drill-card">'
    + `<h3 class="card-title">${icon(result.caught ? 'circle-check' : 'alert-triangle')}Tatbikat sonucu</h3>`
    + `<p>${esc(result.sentence || '')}</p>`
    + `<p>${badge}</p>${caught}`
    + `<p class="card-foot">Gerçek defter mührü: önce ${esc(before)} · sonra ${esc(after)}</p>`
    + '</article>';
}

export function mountDrill(host, { onDone } = {}) {
  if (!host) return;
  if (!host.querySelector('[data-nx-drill]')) host.innerHTML = drillControls();
  const currentResult = host.querySelector('#nx-drill-result');
  if (lastResult && currentResult) currentResult.innerHTML = drillCard(lastResult);

  let state = mountedHosts.get(host);
  if (state) {
    state.onDone = onDone;
    return;
  }
  state = { onDone, running: false };
  mountedHosts.set(host, state);

  host.addEventListener('click', async (event) => {
    const button = event.target.closest?.('[data-nx-drill]');
    if (!button || state.running) return;
    state.running = true;
    const buttons = [...host.querySelectorAll('[data-nx-drill]')];
    buttons.forEach((item) => item.setAttribute('aria-disabled', 'true'));
    const status = host.querySelector('#nx-drill-status');
    if (status) status.textContent = 'Tatbikat sürüyor: defterin kopyası alınıyor.';
    try {
      lastResult = await post('/api/console/ledger/drill', { kind: button.dataset.nxDrill });
      const result = host.querySelector('#nx-drill-result');
      if (result) result.innerHTML = drillCard(lastResult);
      if (status) status.textContent = `${lastResult.sentence} ${lastResult.note}`;
    } catch (error) {
      const message = error && error.message ? error.message : 'Tatbikat yapılamadı.';
      const result = host.querySelector('#nx-drill-result');
      if (result) result.innerHTML = errorCard('Tatbikat yapılamadı', message);
      if (status) status.textContent = message;
    } finally {
      buttons.forEach((item) => item.setAttribute('aria-disabled', 'false'));
      state.running = false;
      state.onDone?.();
    }
  });
}
