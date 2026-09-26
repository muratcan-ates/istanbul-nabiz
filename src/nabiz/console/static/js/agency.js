import { esc } from './format.js';
import { icon } from './icons.js';

export const AGENCY_MAX = 300;

export function shouldShow(data) {
  return Boolean(data && data.agency && !data.emergency);
}

export function agencyCard(data, uid, withCall = true) {
  const why = data.matched ? `<p class="agency-why">Sorunda '${esc(data.matched)}' geçiyor.</p>` : '';
  const page = data.url
    ? `<a class="btn" href="${esc(data.url)}" target="_blank" rel="noopener noreferrer">${esc(data.name)} resmî sayfası ${icon('external-link')}</a>` : '';
  const call = withCall ? '<a class="btn btn-primary agency-call" href="tel:153">153\'ü arayın</a>' : '';
  const districts = data.district_needed ? `<form class="agency-district" data-agency-district autocomplete="off">
    <label for="agency-district-${uid}">Hangi ilçedesiniz?</label>
    <input id="agency-district-${uid}" list="agency-districts-${uid}" name="district" maxlength="40" enterkeyhint="done">
    <datalist id="agency-districts-${uid}">${(data.districts || []).map((name) => `<option value="${esc(name)}"></option>`).join('')}</datalist>
    <button type="submit" class="btn">Göster</button>
  </form>` : '';
  return `<article class="agency-card" aria-labelledby="agency-title-${uid}">
    <p class="agency-kicker">Hangi kurumun işi?</p>
    <h3 id="agency-title-${uid}" tabindex="-1">${esc(data.text)}</h3>
    ${why}<div class="btn-row">${page}${call}</div>${districts}
    <p class="agency-note">Nabız başvuruyu sizin yerinize yapmaz; yalnız doğru kurumu gösterir.</p>
    <p class="sr-only" role="status"></p>
  </article>`;
}

let turnId = 0;
let turnCard = null;
let turnHas153 = false;
const cardState = new WeakMap();

async function requestRoute(q, district) {
  const params = new URLSearchParams({ q });
  if (district !== null) params.set('district', district);
  const response = await fetch(`/api/agency?${params}`, { headers: { Accept: 'application/json' } });
  return response.ok ? response.json() : null;
}

async function showRoute(q, district, expectedTurn, card = null) {
  try {
    const data = await requestRoute(q, district);
    const log = document.querySelector('#chat-log');
    const previous = card ? cardState.get(card) : null;
    if ((!card && expectedTurn !== turnId) || (card && !previous) || !log || !shouldShow(data)) return;
    const withCall = previous ? previous.hasCall : !turnHas153;
    const item = card || document.createElement('li');
    item.className = 'chat-msg is-agency';
    item.innerHTML = agencyCard(data, `turn-${expectedTurn}`, withCall);
    cardState.set(item, { question: q, turnId: expectedTurn, hasCall: withCall });
    if (!card) {
      log.append(item);
      turnCard = item;
    } else {
      item.querySelector('h3')?.focus();
      item.querySelector('[role="status"]').textContent = 'Kurum bilgisi güncellendi.';
    }
  } catch {
    return;
  }
}

function submitDistrict(evt) {
  evt.preventDefault();
  const form = evt.target;
  const input = form.elements.district;
  const value = input.value.trim();
  const status = form.closest('.agency-card')?.querySelector('[role="status"]');
  if (!value) {
    if (status) status.textContent = 'Bir ilçe seçin.';
    input.focus();
    return;
  }
  const card = form.closest('li.chat-msg.is-agency');
  const state = card && cardState.get(card);
  if (card && state) void showRoute(state.question, value, state.turnId, card);
}

function onSubmit(evt) {
  if (evt.target.matches('form[data-agency-district]')) {
    submitDistrict(evt);
    return;
  }
  if (evt.target.id !== 'chat-form') return;
  if (document.querySelector('#chat-submit')?.getAttribute('aria-disabled') === 'true') return;
  turnCard = null;
  turnHas153 = false;
  const question = document.querySelector('#chat-input')?.value.trim() || '';
  if (!question || question.length > AGENCY_MAX) return;
  turnId += 1;
  void showRoute(question, null, turnId);
}

function hasOutsideCall(node) {
  if (node.nodeType !== 1 || node.closest('.agency-card')) return false;
  return node.matches('a[href="tel:153"]') || Boolean(node.querySelector('a[href="tel:153"]'));
}

function boot() {
  if (!document.querySelector('link[href="/css/agency.css"]')) {
    const sheet = document.createElement('link');
    sheet.rel = 'stylesheet';
    sheet.href = '/css/agency.css';
    document.head.append(sheet);
  }
  document.addEventListener('submit', onSubmit, true);
  const log = document.querySelector('#chat-log');
  if (!log) return;
  const observer = new MutationObserver((records) => {
    for (const record of records) {
      for (const node of record.addedNodes) {
        if (!hasOutsideCall(node)) continue;
        turnHas153 = true;
        const state = turnCard && cardState.get(turnCard);
        if (state) state.hasCall = false;
        turnCard?.querySelector('.agency-call')?.remove();
      }
    }
  });
  observer.observe(log, { childList: true, subtree: true });
}

if (typeof document !== 'undefined') boot();
