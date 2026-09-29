/* Native workspace and composer, adapted from DOU-Synapse ChatDraft (MIT).
 * Attribution and source revision: docs/design/synapse-adaptation.md. */
import { onLang, t } from './i18n_text.js';
import { markEntry, mountTranscript } from './transcript.js';

// Placement changes where a link appears; its destination always remains addressable.
// The operator area owns open data after integration, while this address stays available.
// placement: 'nav' | 'more' | 'account' | 'topbar' | 'operator' | 'hash-only'.
export const LEGACY_PLACEMENT = [
  { id: 'city', href: '#city-cards', i18n: 'design.nav_city', placement: 'more' },
  { id: 'travel', href: '#city-tools', i18n: 'design.nav_tools', placement: 'more' },
  { id: 'map', href: '#map-workspace', i18n: 'design.nav_map', placement: 'nav' },
  { id: 'nearby', href: '#explore-workspace', i18n: 'design.nav_nearby', placement: 'more' },
  { id: 'data', href: '#acik-veri', i18n: 'design.nav_data', placement: 'operator' },
  { id: 'follow', href: '#takip', i18n: 'ui.shell.nav_follow', placement: 'account' },
  { id: 'easy', href: '/kolay.html', i18n: 'ui.shell.easy_screen', placement: 'topbar' },
];

const VIEWS = {
  assistant: ['home-screen', 'asistan'], calendar: ['takvim'], city: ['city-cards'],
  travel: ['journey-workspace'], data: ['open-data-workspace'],
  map: ['map-workspace'], nearby: ['explore-workspace'], account: ['hesabim'],
};

export function applyLegacyPlacement() {
  const nav = document.getElementById('legacy-nav');
  const more = document.getElementById('assistant-more');
  const moreLinks = document.getElementById('legacy-more-links');
  if (!nav || !more || !moreLinks) return;
  const topbar = document.getElementById('legacy-topbar');
  const primary = document.querySelector('.nav-primary');
  const links = [...nav.querySelectorAll('a'), ...moreLinks.querySelectorAll('a'),
    ...(topbar ? topbar.querySelectorAll('a') : []), ...(primary ? primary.querySelectorAll('a') : [])];
  for (const item of LEGACY_PLACEMENT) {
    const link = links.find((node) => node.getAttribute('data-legacy') === item.id);
    if (!link) continue;
    link.setAttribute('href', item.href);
    if (item.i18n) link.setAttribute('data-i18n', item.i18n);
    const row = link.parentElement;
    row.hidden = ['hash-only', 'account', 'operator'].includes(item.placement);
    if (item.placement === 'operator') {
      row.setAttribute('data-moved-to', 'console');
      link.setAttribute('data-moved-to', 'console');
    } else {
      row.removeAttribute('data-moved-to');
      link.removeAttribute('data-moved-to');
    }
    if (item.id === 'map' && item.placement === 'nav' && primary) {
      link.setAttribute('data-primary', 'map');
      let label = link.querySelector('span');
      if (!label) {
        const icon = link.querySelector('svg');
        link.textContent = '';
        if (icon) link.append(icon);
        label = document.createElement('span'); link.append(label);
      }
      link.removeAttribute('data-i18n'); label.setAttribute('data-i18n', item.i18n);
      const calendar = [...primary.querySelectorAll('a')].find((node) => node.getAttribute('data-primary') === 'calendar')?.parentElement;
      if (calendar) {
        const rows = [...primary.children];
        if (rows[rows.indexOf(calendar) + 1] !== row) calendar.after(row);
      } else if (row.parentElement !== primary) primary.append(row);
      continue;
    }
    const home = item.placement === 'more' ? moreLinks : item.placement === 'topbar' && topbar ? topbar : nav;
    home.append(row);
  }
  nav.hidden = ![...nav.children].some((row) => !row.hidden);
  more.hidden = ![...moreLinks.children].some((row) => !row.hidden);
  const secondary = document.querySelector('.nav-secondary');
  if (secondary) secondary.hidden = nav.hidden;
}

function labelPrimaryNavigation(language) {
  const labels = {
    assistant: ['ui.shell.nav_assistant', 'Asistan', 'Assistant'],
    calendar: ['ui.shell.nav_calendar', 'Takvim', 'Calendar'],
    map: ['design.nav_map', 'Harita', 'Map'],
    account: ['ui.shell.nav_account', 'Hesabım', 'My account'],
  };
  for (const link of document.querySelectorAll('.nav-primary a')) {
    const [key, tr, en] = labels[link.getAttribute('data-primary')] || [];
    const name = link.querySelector('span');
    if (name && key) name.textContent = t(key, language === 'en' ? en : tr);
  }
  for (const back of document.querySelectorAll('.workspace-back')) {
    back.textContent = t('ui.shell.nav_assistant', language === 'en' ? 'Assistant' : 'Asistan');
  }
  const follow = document.querySelector('[data-legacy="follow"] span');
  if (follow) follow.textContent = t('ui.shell.nav_follow', language === 'en' ? 'Follow' : 'Takip');
  const other = document.querySelector('.nav-secondary');
  other?.setAttribute('aria-label', t('ui.shell.nav_other', language === 'en' ? 'Other sections' : 'Diğer bölümler'));
  const summary = document.querySelector('#assistant-more summary');
  if (summary) summary.textContent = t('ui.shell.more', language === 'en' ? 'More' : 'Daha fazla');
  const easy = document.querySelector('[data-legacy="easy"] span');
  if (easy) easy.textContent = t('ui.shell.easy_screen', language === 'en' ? 'Easy screen' : 'Kolay ekran');
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

const everydayForms = new WeakSet();
export function mountEverydayExamples(form, input) {
  if (!document.body.classList.contains('citizen-page') || everydayForms.has(form)) return;
  everydayForms.add(form);
  const list = document.getElementById('capability-examples');
  const examples = [
    ['map', 'Kadıköy’den Levent’e en hızlı nasıl giderim?', 'What is the fastest way from Kadıköy to Levent?'],
    ['train', 'Taksim’e metroyla nasıl giderim?', 'How can I get to Taksim by metro?'],
    ['bus', 'Beşiktaş’a sadece otobüsle nasıl giderim?', 'How can I get to Beşiktaş using only buses?'],
    ['external-link', 'Bu hafta sonu ücretsiz ne yapabilirim?', 'What can I do for free this weekend?'],
  ];
  const render = (language) => {
    const en = language === 'en';
    input.setAttribute('placeholder', en ? 'Ask something about Istanbul…' : 'İstanbul hakkında bir şey sorun…');
    const subtitle = document.getElementById('home-sub');
    if (subtitle) subtitle.textContent = en ? 'Ask about transport, events and city services.'
      : 'Ulaşım, etkinlikler ve şehir hizmetleri için sorun.';
    list?.querySelectorAll('button').forEach((button, index) => {
      const item = examples[index]; if (!item) return;
      button.dataset.example = `everyday_${index + 1}`; button.dataset.question = item[en ? 2 : 1];
      const label = button.querySelector('span'); if (label) label.textContent = button.dataset.question;
      button.querySelector('use')?.setAttribute('href', `/icons.svg#i-${item[0]}`);
    });
  };
  render(document.documentElement.lang); onLang(render);
  list?.addEventListener('click', (event) => {
    const button = event.target.closest('button');
    if (!button?.dataset.question || !list.contains(button)) return;
    input.value = button.dataset.question; form.requestSubmit();
  });
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
  const doc = document;
  mountTranscript(log, doc);
  // The Takvim tab's hour grid mounts itself (calendar_view.js, loaded by index.html) and refreshes when shown.
  const alignComposer = () => {
    const rect = log.getBoundingClientRect?.();
    if (!rect || rect.width <= 0) return;
    form.style.setProperty('--composer-left', `${rect.left}px`);
    form.style.setProperty('--composer-width', `${rect.width}px`);
  };
  import('./context_chips.js').then((m) => m.mountContextChips(form, doc)).catch(() => {});
  if (typeof ResizeObserver !== 'undefined') {
    new ResizeObserver(([entry]) => {
      const height = entry.borderBoxSize?.[0]?.blockSize || form.getBoundingClientRect().height;
      if (height > 0) doc.documentElement.style.setProperty('--chat-composer-height', `${Math.ceil(height)}px`);
    }).observe(form);
    new ResizeObserver(alignComposer).observe(log);
    window.addEventListener('resize', alignComposer, { passive: true });
  }
  applyLegacyPlacement();
  labelPrimaryNavigation(document.documentElement.lang);
  onLang(labelPrimaryNavigation);
  mountEverydayExamples(form, input);
  const placeholder = document.createComment('composer home');
  form.before(placeholder);
  const submit = document.getElementById('chat-submit');
  const bottom = form.querySelector('.composer-bottom');
  if (bottom && submit) bottom.append(submit);
  const show = (name, destination = null) => {
    const changed = document.body.dataset.view !== name;
    document.body.dataset.view = name;
    for (const [view, ids] of Object.entries(VIEWS)) {
      for (const id of ids) {
        const node = document.getElementById(id);
        if (!node) continue;
        node.hidden = view !== name;
        if (node.matches('details') && view === name) node.open = true;
        if (view === name && ['city', 'travel', 'map', 'nearby'].includes(name) && !node.querySelector('.workspace-back')) {
          const back = doc.createElement('a');
          back.classList.add('btn'); back.classList.add('btn-quiet'); back.classList.add('workspace-back');
          back.setAttribute('href', '#asistan');
          back.textContent = t('ui.shell.nav_assistant', doc.documentElement.lang === 'en' ? 'Assistant' : 'Asistan');
          const summary = node.matches('details') && node.querySelector('summary');
          if (summary) summary.after(back); else node.prepend(back);
        }
        if (changed && view === name && id !== 'home-screen') markEntry(node);
      }
    }
    const tools = main.querySelector('.workspace');
    if (tools) tools.hidden = !['travel', 'data', 'map', 'nearby'].includes(name);
    const footer = document.querySelector('footer');
    if (footer) footer.hidden = name !== 'about';
    const links = [...document.querySelectorAll('.topbar-nav a')];
    const primaryView = ['city', 'travel', 'nearby'].includes(name) ? 'assistant' : name;
    const current = links.find((link) => link.getAttribute('data-primary') === primaryView);
    links.forEach((link) => {
      if (link === current) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    });
    if (name === 'assistant') alignComposer();
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
      try {
        const id = decodeURIComponent(link.getAttribute('href').slice(1));
        reveal(id);
        if (link.closest('.nav-primary') && ['takvim', 'map-workspace', 'hesabim'].includes(id)) {
          const title = doc.getElementById(id === 'takvim' ? 'takvim-title' : id === 'hesabim' ? 'you-title' : id);
          title?.setAttribute('tabindex', '-1');
          title?.focus({ preventScroll: true });
        }
        if (link.closest('#assistant-more')) {
          const target = targetForId(id);
          if (target) {
            if (!target.hasAttribute('tabindex')) target.setAttribute('tabindex', '-1');
            target.focus({ preventScroll: true });
          }
        }
      } catch { /* Ignore malformed fragments. */ }
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
    alignComposer();
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
