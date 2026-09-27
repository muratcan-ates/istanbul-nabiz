/* Native workspace and composer, adapted from DOU-Synapse ChatDraft (MIT).
 * Attribution and source revision: docs/design/synapse-adaptation.md. */
import { onLang, t } from './i18n_text.js';

// Murat's 27 Sep decision: city, travel, map and nearby under "Daha fazla"; open data waits for the
// operator area (P08) and follow lives in Hesabım, both reachable by address; Kolay ekran in the top bar.
// placement: 'nav' | 'more' | 'hash-only' | 'topbar'. No section is removed.
export const LEGACY_PLACEMENT = [
  { id: 'city', href: '#city-cards', i18n: 'design.nav_city', placement: 'more' },
  { id: 'travel', href: '#city-tools', i18n: 'design.nav_tools', placement: 'more' },
  { id: 'map', href: '#map-workspace', i18n: 'design.nav_map', placement: 'more' },
  { id: 'nearby', href: '#explore-workspace', i18n: 'design.nav_nearby', placement: 'more' },
  { id: 'data', href: '#acik-veri', i18n: 'design.nav_data', placement: 'hash-only' },
  { id: 'follow', href: '#takip', i18n: 'ui.shell.nav_follow', placement: 'hash-only' },
  { id: 'easy', href: '/kolay.html', i18n: 'design.nav_easy', placement: 'topbar' },
];

const VIEWS = {
  assistant: ['home-screen', 'asistan'], calendar: ['takvim'], city: ['city-cards'],
  travel: ['journey-workspace'], data: ['open-data-workspace'],
  map: ['map-workspace'], nearby: ['explore-workspace'], account: ['hesabim'],
};

export function applyLegacyPlacement() {
  const nav = document.getElementById('legacy-nav');
  const more = document.getElementById('legacy-more');
  const moreLinks = document.getElementById('legacy-more-links');
  if (!nav || !more || !moreLinks) return;
  const topbar = document.getElementById('legacy-topbar');
  const links = [...nav.querySelectorAll('a'), ...moreLinks.querySelectorAll('a'),
    ...(topbar ? topbar.querySelectorAll('a') : [])];
  for (const item of LEGACY_PLACEMENT) {
    const link = links.find((node) => node.getAttribute('data-legacy') === item.id);
    if (!link) continue;
    link.setAttribute('href', item.href);
    if (item.i18n) link.setAttribute('data-i18n', item.i18n);
    const row = link.parentElement;
    row.hidden = item.placement === 'hash-only';
    const home = item.placement === 'more' ? moreLinks : item.placement === 'topbar' && topbar ? topbar : nav;
    home.append(row);
  }
  nav.hidden = ![...nav.children].some((row) => !row.hidden);
  more.hidden = ![...moreLinks.children].some((row) => !row.hidden);
}

function labelPrimaryNavigation(language) {
  const labels = {
    assistant: ['ui.shell.nav_assistant', 'Asistan', 'Assistant'],
    calendar: ['ui.shell.nav_calendar', 'Takvim', 'Calendar'],
    account: ['ui.shell.nav_account', 'Hesabım', 'My account'],
  };
  for (const link of document.querySelectorAll('.nav-primary a')) {
    const [key, tr, en] = labels[link.getAttribute('data-primary')] || [];
    const name = link.querySelector('span');
    if (name && key) name.textContent = t(key, language === 'en' ? en : tr);
  }
  const follow = document.querySelector('[data-legacy="follow"] span');
  if (follow) follow.textContent = t('ui.shell.nav_follow', language === 'en' ? 'Follow' : 'Takip');
  const other = document.querySelector('.nav-secondary');
  other?.setAttribute('aria-label', t('ui.shell.nav_other', language === 'en' ? 'Other sections' : 'Diğer bölümler'));
  const summary = document.querySelector('#legacy-more summary');
  if (summary) summary.textContent = t('ui.shell.more', language === 'en' ? 'More' : 'Daha fazla');
  for (const [selector, key, tr, en] of [
    ['#takvim-title', 'ui.shell.calendar_title', 'Takvim', 'Calendar'],
    ['#takvim > p:not([id])', 'ui.shell.calendar_note', 'Kaydettiğiniz planlar burada görünür.', 'Your saved plans appear here.'],
    ['#takvim-empty', 'ui.shell.calendar_empty', 'Henüz kaydedilmiş plan yok. Sohbette bir etkinliği takvime eklediğinizde burada görünür.',
      'No saved plans yet. When you add an event to your calendar in chat, it will appear here.'],
  ]) {
    const node = document.querySelector(selector);
    if (node) node.textContent = t(key, language === 'en' ? en : tr);
  }
}

function targetForId(id) {
  const targetId = /^takibi-birak=[A-Za-z0-9.]{3,120}$/.test(id || '') ? 'takip' : id;
  return document.getElementById(targetId || '');
}

function openDetails(target) {
  for (let node = target?.closest('details'); node; node = node.parentElement?.closest('details')) node.open = true;
}

export function revealTarget(id, { focus = false, block } = {}) {
  const target = targetForId(id);
  if (!target) return null;
  document.dispatchEvent(new CustomEvent('nabiz:reveal', { detail: { id: target.id } }));
  openDetails(target);
  if (block) target.scrollIntoView({ block });
  if (focus) target.focus({ preventScroll: true });
  return target;
}

export function viewForTarget(target) {
  if (!target) return 'assistant';
  if (target.closest('footer')) return 'about';
  for (const [view, ids] of Object.entries(VIEWS)) {
    if (ids.some((id) => target.id === id || target.closest(`#${id}`))) return view;
  }
  return 'assistant';
}

export function mountWorkspace({ form, input }) {
  const main = document.getElementById('main'), hero = document.getElementById('home-screen');
  const chat = document.getElementById('asistan'), log = document.getElementById('chat-log');
  if (!main || !hero || !chat || !log) return;
  applyLegacyPlacement();
  labelPrimaryNavigation(document.documentElement.lang);
  onLang(labelPrimaryNavigation);
  const placeholder = document.createComment('composer home');
  form.before(placeholder);
  const submit = document.getElementById('chat-submit');
  const bottom = form.querySelector('.composer-bottom');
  if (bottom && submit) bottom.append(submit);
  const show = (name, destination = null) => {
    document.body.dataset.view = name;
    for (const [view, ids] of Object.entries(VIEWS)) {
      for (const id of ids) {
        const node = document.getElementById(id);
        if (!node) continue;
        node.hidden = view !== name;
        if (node.matches('details') && view === name) node.open = true;
      }
    }
    const tools = main.querySelector('.workspace');
    if (tools) tools.hidden = !['travel', 'data', 'map', 'nearby'].includes(name);
    const footer = document.querySelector('footer');
    if (footer) footer.hidden = name !== 'about';
    const links = [...document.querySelectorAll('.topbar-nav a')];
    const current = links.find((link) => link.getAttribute('data-primary') === name);
    links.forEach((link) => {
      if (link === current) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    });
  };
  const reveal = (id) => {
    const target = targetForId(id);
    show(viewForTarget(target), target);
    openDetails(target);
  };
  document.addEventListener('nabiz:reveal', (event) => reveal(event.detail?.id));
  document.addEventListener('nabiz:show-on-map', () => show('map'));
  document.addEventListener('click', (event) => {
    const link = event.target.closest('a[href^="#"]');
    if (link) {
      try { reveal(decodeURIComponent(link.getAttribute('href').slice(1))); } catch { /* Ignore malformed fragments. */ }
    }
  });
  const followHash = () => {
    let id;
    try { id = decodeURIComponent(location.hash.slice(1)); } catch { return; }
    if (id) reveal(id);
    else show('assistant');
  };
  window.addEventListener('hashchange', followHash);
  followHash();
  // The same composer follows the transcript. Listeners, consent and draft survive the move.
  const syncConversation = () => {
    const active = !!log.querySelector('.chat-msg.is-user, .chat-msg.is-assistant');
    const changed = document.body.classList.contains('has-conversation') !== active;
    const moving = form.parentElement !== (active ? chat : hero);
    const focused = moving && form.contains(document.activeElement) ? document.activeElement : null;
    document.body.classList.toggle('has-conversation', active);
    if (active && form.parentElement !== chat) chat.append(form);
    if (!active && form.parentElement !== hero) placeholder.after(form);
    if (changed && active) show('assistant');
    // Reparenting drops native focus; restore only the field that lost it during this move.
    if (focused?.isConnected && !focused.matches(':disabled, [aria-disabled="true"]')
      && !focused.closest('[hidden], [inert]')
      && [document.body, document.documentElement, focused].includes(document.activeElement)) {
      focused.focus({ preventScroll: true });
    }
  };
  new MutationObserver(syncConversation).observe(log, { childList: true });
  syncConversation();
  // Match Synapse's Enter / Shift+Enter contract without disrupting IME input or stop actions.
  input.addEventListener('keydown', (event) => {
    if (event.defaultPrevented || event.key !== 'Enter' || event.shiftKey || event.isComposing || event.keyCode === 229) return;
    event.preventDefault();
    if (!input.disabled && !input.readOnly && submit?.getAttribute('aria-disabled') !== 'true') form.requestSubmit();
  });
  form.addEventListener('submit', () => show('assistant'));
}
