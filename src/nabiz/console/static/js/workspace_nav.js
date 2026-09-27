/* Native workspace and composer, adapted from DOU-Synapse ChatDraft (MIT).
 * Attribution and source revision: docs/design/synapse-adaptation.md. */
const VIEWS = {
  assistant: ['home-screen', 'asistan'], city: ['city-cards'],
  travel: ['journey-workspace'], data: ['open-data-workspace'],
  map: ['map-workspace'], nearby: ['explore-workspace'], account: ['hesabim'],
};

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
    const candidates = links.filter((link) => {
      const href = link.getAttribute('href');
      const target = href?.startsWith('#') ? document.getElementById(href.slice(1)) : null;
      return target && viewForTarget(target) === name;
    });
    const current = candidates.find((link) => destination?.closest(link.getAttribute('href'))) || candidates[0];
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
