/* The accessible-journey card. Last-known results stay in this page session only. */

import { MOCK, get } from './api.js';
import { esc } from './format.js';
import { icon } from './icons.js';
import { ageSentence, sourceLink } from './provenance.js';

const LIFT_TEXT = {
  working: 'İBB kaydında asansör arızası yok',
  out_of_service: 'İBB kaydına göre asansör arızalı',
  unknown: 'Asansör durumu doğrulanamadı',
};

let lastKnown = null;

function mount() {
  const alternative = document.querySelector('#alternative')?.closest('section');
  if (!alternative || document.querySelector('#journey-section')) return;
  const section = document.createElement('section');
  section.id = 'journey-section';
  section.setAttribute('aria-labelledby', 'journey-title');
  section.innerHTML = '<div class="section-head"><h2 id="journey-title">Erişilebilir yolculuk</h2>'
    + '<span class="section-note">raylı sistem ve asansör kaydı</span></div>'
    + '<form id="journey-form" class="arrival-form" autocomplete="off">'
    + '<div class="field"><label for="journey-from">Başlangıç</label><input id="journey-from" name="from" type="text" required maxlength="120" placeholder="Kadıköy"></div>'
    + '<div class="field"><label for="journey-to">Varış</label><input id="journey-to" name="to" type="text" required maxlength="120" placeholder="Levent"></div>'
    + '<button type="submit" class="btn">Yolculuğu ara</button>'
    + '<p class="field-hint">Asansör bilgisi İBB kaydına dayanır. Kişi veya profil bilgisi istenmez.</p></form>'
    + '<div id="journey-result" aria-live="polite" aria-busy="false"></div>'
    + '<p class="sr-only" id="journey-status" role="status"></p>';
  alternative.after(section);
  section.querySelector('#journey-form').addEventListener('submit', submitJourney);
}

function mapLink(value, label) {
  if (typeof value !== 'string') return '';
  try {
    const url = new URL(value);
    if (url.protocol !== 'https:' || !['maps.apple.com', 'www.google.com'].includes(url.hostname)) return '';
    return `<a class="btn" href="${esc(url.href)}" target="_blank" rel="noopener noreferrer">${label}</a>`;
  } catch (err) {
    return '';
  }
}

function stationState(station) {
  const status = LIFT_TEXT[station.lift_status] ? station.lift_status : 'unknown';
  const tone = status === 'working' ? 'is-ok' : status === 'out_of_service' ? 'is-warning' : 'is-unverified';
  return `<li>${esc(station.name)}: <span class="tag ${tone}">${LIFT_TEXT[status]}</span></li>`;
}

function stepView(step, index) {
  const title = step.kind === 'ride'
    ? `${esc(step.line || 'Raylı sistem')}: ${esc(step.from_station)} → ${esc(step.to_station)}`
    : step.kind === 'transfer'
      ? `${esc(step.at_station)} istasyonunda aktarma`
      : esc(step.description || 'Yürüyüş');
  const status = LIFT_TEXT[step.lift_status]
    ? `<p>${LIFT_TEXT[step.lift_status]}</p>` : '';
  const stations = Array.isArray(step.stations) && step.stations.length
    ? `<ul>${step.stations.map(stationState).join('')}</ul>` : '';
  const note = step.note ? `<p>${esc(step.note)}</p>` : '';
  const links = step.map_links
    ? `<p class="journey-map-links">${mapLink(step.map_links.google, 'Haritada aç')}${mapLink(step.map_links.apple, 'Apple Maps')}</p>` : '';
  const minutes = Number.isFinite(step.minutes) ? `<span class="badge">${step.minutes} dk tahmini</span>` : '';
  return `<li class="journey-step"><h4>${index + 1}. ${title}</h4>${minutes}${status}${stations}${note}${links}</li>`;
}

function render(data, cached = false) {
  const host = document.querySelector('#journey-result');
  if (!host) return;
  const state = data.available
    ? (data.uncertainty?.length ? 'warning' : 'ok')
    : 'unverified';
  const reason = data.available ? '' : `<p class="card-status">Doğrulanamadı: ${esc(data.reason || 'Yolculuk hesaplanamadı.')}</p>`;
  const steps = data.available && data.steps.length
    ? `<ol class="journey-steps">${data.steps.map(stepView).join('')}</ol>` : '';
  const detours = (data.alternatives_used || (data.alternative_used ? [data.alternative_used] : []));
  const alternative = detours.length
    ? `<p>Alternatif istasyon: ${detours.map((item) => `${esc(item.station)} (${esc(item.line)})`).join(', ')}. Tahmini ek süre: ${Number(data.extra_minutes) || 0} dk.</p>` : '';
  const badge = data.operator_approved
    ? '<p><span class="tag">Operatör onaylı (simüle)</span></p>' : '';
  const warning = cached ? '<p class="tag is-warning">Bağlantı yok. Son bilinen plan bu sayfa açıkken alınmıştı.</p>' : '';
  const provenance = data.provenance
    ? `<p class="card-foot">${ageSentence(data.provenance)} ${sourceLink(data.provenance)}</p>` : '<p class="card-foot">Veri kaynağı ve yaşı bilinmiyor.</p>';
  const uncertainty = data.uncertainty?.length
    ? `<p>Belirsizlik: ${esc(data.uncertainty.join(', '))}</p>` : '';
  host.innerHTML = `<article class="card card-in is-${state}" aria-labelledby="journey-result-title">`
    + `<span class="card-kind" aria-hidden="true">${icon('wheelchair')}</span>`
    + `<h3 class="card-title" id="journey-result-title">${data.available ? `${esc(data.from)} → ${esc(data.to)}` : 'Erişilebilir yolculuk doğrulanamadı'}</h3>`
    + `${reason}${steps}${alternative}${badge}${warning}${uncertainty}`
    + `<p>${esc(data.disclaimer || '')}</p>${provenance}</article>`;
}

function cachedCopy() {
  if (!lastKnown) return null;
  const age = Number(lastKnown.data.provenance?.age_s);
  const elapsed = Math.max(0, (Date.now() - lastKnown.receivedAt) / 1000);
  return {
    ...lastKnown.data,
    provenance: lastKnown.data.provenance
      ? { ...lastKnown.data.provenance, age_s: Number.isFinite(age) ? age + elapsed : null }
      : null,
  };
}

async function submitJourney(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const origin = form.elements.from.value.trim();
  const destination = form.elements.to.value.trim();
  if (!origin || !destination) return;
  const host = document.querySelector('#journey-result');
  const status = document.querySelector('#journey-status');
  host.setAttribute('aria-busy', 'true');
  status.textContent = 'Erişilebilir yolculuk aranıyor.';
  try {
    // The mock helper maps this short path to /mock/journey.json. Real requests use the route below.
    const path = MOCK ? '/api/journey' : '/api/journey/accessible';
    const data = await get(path, { from: origin, to: destination, needs: 'step_free' });
    lastKnown = { data, origin, destination, receivedAt: Date.now() };
    render(data);
    status.textContent = data.available ? 'Erişilebilir yolculuk planı hazır.' : `Doğrulanamadı. ${data.reason || ''}`;
  } catch (error) {
    const sameRequest = lastKnown && lastKnown.origin === origin && lastKnown.destination === destination;
    const data = sameRequest ? cachedCopy() : null;
    if (data) {
      render(data, true);
      status.textContent = 'Bağlantı yok. Son bilinen yolculuk gösteriliyor.';
    } else {
      render({
        available: false,
        from: origin,
        to: destination,
        steps: [],
        reason: error.message,
        uncertainty: ['equipment_data_unavailable'],
        disclaimer: 'Yeni plan alınamadı. Önceki bir plan bu sayfada bulunmuyor.',
      });
      status.textContent = `Yolculuk doğrulanamadı. ${error.message}`;
    }
  } finally {
    host.setAttribute('aria-busy', 'false');
  }
}

mount();
