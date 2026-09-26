/* The operator page's live NEXUS organ cards and ledger-backed learning loop. */

import { MOCK, get } from './api.js';
import { REFRESH_MS } from './config.js';
import { esc, int, clock, dateTime, UNKNOWN } from './format.js';
import { icon } from './icons.js';
import { errorCard } from './cards.js';

const ICONS = {
  router: 'route', reflex: 'bolt', arena: 'armchair', approval: 'circle-check',
  rules: 'list-details', lifecycle: 'clock-pause', ledger: 'shield-lock',
};
const STATES = { active: 'bugün çalıştı', idle: 'bugün boş', ok: 'zincir sağlam', broken: 'zincir kırık' };
let lastStates = '';
let loading = false;
let refreshTimer = null;

function tagClass(state) {
  if (state === 'active' || state === 'ok') return ' is-ok';
  if (state === 'broken') return ' is-bad';
  return '';
}

function lastSeen(organ) {
  if (!organ.last_activity) return 'son etkinlik yok';
  return Number(organ.today_count) > 0
    ? `son: ${clock(organ.last_activity)}`
    : `son: ${dateTime(organ.last_activity)}`;
}

function organDetail(organ) {
  if (organ.key === 'reflex' && Number(organ.failed_today) > 0) {
    return `<p class="nx-organ-detail">${int(organ.failed_today)} kez insana devretti</p>`;
  }
  if (organ.key === 'approval') return `<p class="nx-organ-detail">${int(organ.awaiting)} kart karar bekliyor</p>`;
  if (organ.key === 'rules') {
    return `<p class="nx-organ-detail">${int(organ.drafts)} taslak · ${int(organ.active_rules)} etkin kural</p>`;
  }
  if (organ.key === 'ledger') {
    return `<p class="nx-organ-detail">${int(organ.entries)} kayıt · mühür ${esc(organ.head_short || UNKNOWN)}</p>`
      + '<div class="nx-drill" id="nx-drill"></div>';
  }
  return '';
}

export function organCard(organ) {
  const state = String(organ.state || 'idle');
  const label = STATES[state] || esc(organ.state_label || UNKNOWN);
  return `<li class="nx-organ card" data-organ="${esc(organ.key)}" data-state="${esc(state)}">`
    + `<span class="card-kind">${icon(ICONS[organ.key] || 'info-circle')}</span>`
    + `<h3 class="nx-organ-title">${esc(organ.name || UNKNOWN)}</h3>`
    + `<p class="nx-organ-what">${esc(organ.what || '')}</p>`
    + `<p><span class="tag${tagClass(state)}">${label}</span></p>`
    + `<p class="nx-organ-count">bugün ${int(organ.today_count)} · toplam ${int(organ.total_count)}</p>`
    + `<p class="nx-organ-last">${esc(lastSeen(organ))}</p>`
    + organDetail(organ)
    + '</li>';
}

export function loopStrip(loop) {
  const stages = Array.isArray(loop && loop.stages) ? loop.stages : [];
  const items = stages.map((stage) => {
    const count = stage.count === null || stage.count === undefined ? 'veri yok' : int(stage.count);
    return `<li><span class="nx-loop-count">${esc(count)}</span><span>${esc(stage.label || UNKNOWN)}</span></li>`;
  }).join('');
  return `<ol class="nx-loop" aria-label="Öğrenme döngüsü">${items}</ol>`;
}

export function metroEmptyCard(routerTotal) {
  const read = Number(routerTotal) > 0
    ? 'Şehir uyarısı kayıtlı veriden okundu; Yönlendirici ve Arena onunla çalıştı.'
    : 'Şehir uyarısı henüz okunmadı.';
  return '<aside class="card is-unverified nx-metro-empty" role="note">'
    + '<span class="card-kind">' + icon('info-circle') + '</span>'
    + '<h3>Metro arıza kaydı yok</h3>'
    + '<p>Asansör ve yürüyen merdiven organları kayıtlı Metro verisiyle beslenir.</p>'
    + `<p>${read}</p></aside>`;
}

export function organsSection(payload) {
  const organs = Array.isArray(payload.organs) ? payload.organs : [];
  const router = organs.find((organ) => organ.key === 'router');
  const emptyMetro = Number(payload.metro_signals) === 0 ? metroEmptyCard(router ? router.total_count : 0) : '';
  return emptyMetro + `<ul class="nx-organs" aria-label="NEXUS organları">${organs.map(organCard).join('')}</ul>`
    + loopStrip(payload.loop);
}

function ensureSection() {
  let section = document.querySelector('#nx-organs');
  if (!section) {
    section = document.createElement('section');
    section.id = 'nx-organs';
    section.setAttribute('aria-labelledby', 'nx-organs-title');
    section.innerHTML = '<div class="section-head"><h2 id="nx-organs-title">NEXUS organları</h2>'
      + '<span class="section-note">Defterden canlı okunur · kişi bazında metrik yok</span></div>'
      + '<p class="sr-only" id="nx-status" role="status" aria-live="polite"></p>'
      + '<div id="nx-organs-content"></div>';
    const drafts = document.querySelector('#drafts-title');
    const anchor = drafts && drafts.closest('section');
    const main = document.querySelector('main#main');
    if (anchor && anchor.parentElement) anchor.parentElement.insertBefore(section, anchor);
    else if (main) main.append(section);
  }
  if (!document.querySelector('link[href="/css/console_organs.css"]')) {
    const style = document.createElement('link');
    style.rel = 'stylesheet';
    style.href = '/css/console_organs.css';
    document.head.append(style);
  }
  return section;
}

function render(host, html) {
  if (host.innerHTML === html) return;
  const active = host.contains(document.activeElement) ? document.activeElement : null;
  const drillKind = active && active.dataset.nxDrill;
  host.innerHTML = html;
  if (drillKind) {
    [...host.querySelectorAll('[data-nx-drill]')]
      .find((button) => button.dataset.nxDrill === drillKind)?.focus({ preventScroll: true });
  }
}

function announce(payload) {
  const current = payload.organs.map((organ) => [organ.key, organ.state_label]);
  const states = JSON.stringify(current);
  if (lastStates && states !== lastStates) {
    const previous = JSON.parse(lastStates);
    const changed = payload.organs.find((organ, index) => previous[index]?.[1] !== organ.state_label);
    if (changed) document.querySelector('#nx-status').textContent = `${changed.name} ${changed.state_label}.`;
  }
  lastStates = states;
}

async function mountDrill() {
  const host = document.querySelector('#nx-drill');
  if (!host) return;
  try {
    const module = await import('./console_drill.js');
    module.mountDrill(host, { onDone: load });
  } catch {
    // The drill lane can be integrated later; organ cards remain useful without it.
  }
}

async function load() {
  const host = document.querySelector('#nx-organs-content');
  if (!host || loading) return;
  if (MOCK) {
    render(host, '<p class="section-note">Örnek veri modunda NEXUS organları gösterilmez; sunucuya bağlanın.</p>');
    return;
  }
  loading = true;
  try {
    const payload = await get('/api/console/organs');
    render(host, organsSection(payload));
    announce(payload);
    await mountDrill();
  } catch (err) {
    render(host, errorCard('NEXUS organları okunamadı', err.message));
  } finally {
    loading = false;
  }
}

function refreshForConsoleAction(event) {
  const target = event.target instanceof Element ? event.target.closest('#simulate, #decision .actions .btn, #drafts .btn') : null;
  if (target) setTimeout(load, 1500);
}

function refreshOnVisibility() {
  clearInterval(refreshTimer);
  refreshTimer = null;
  if (document.visibilityState === 'visible') {
    refreshTimer = setInterval(load, REFRESH_MS);
    load();
  }
}

function boot() {
  ensureSection();
  load();
  document.addEventListener('click', refreshForConsoleAction);
  document.addEventListener('visibilitychange', refreshOnVisibility);
}

if (typeof document !== 'undefined') boot();
