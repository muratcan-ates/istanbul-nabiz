/* The decision desk's section rail: reveal hidden targets, focus headings and mark the active place. */

const $ = (selector) => document.querySelector(selector);
let observer = null;
let systemObserver = null;
const targetsSeen = new Map();

function setActiveNav(id) {
  document.querySelectorAll('.console-nav a').forEach((link) => {
    if (link.hash === `#${id}`) link.setAttribute('aria-current', 'true');
    else link.removeAttribute('aria-current');
  });
}

function targetFromHash(hash) {
  return hash && hash.startsWith('#') ? document.getElementById(decodeURIComponent(hash.slice(1))) : null;
}

function revealTarget(target) {
  let disclosure = target.closest('details');
  while (disclosure) {
    disclosure.open = true;
    disclosure = disclosure.parentElement?.closest('details') || null;
  }
}

function focusSectionHeading(target) {
  const heading = target.matches('h2') ? target : target.querySelector('h2');
  if (!heading) return;
  heading.setAttribute('tabindex', '-1');
  heading.focus({ preventScroll: true });
}

function refreshObserver() {
  if (typeof IntersectionObserver === 'undefined') return;
  observer?.disconnect();
  targetsSeen.clear();
  const topbarHeight = $('.topbar')?.getBoundingClientRect().height || 0;
  const railHeight = window.matchMedia('(min-width: 1024px)').matches
    ? 0 : ($('.console-nav')?.getBoundingClientRect().height || 0);
  const offset = Math.ceil(topbarHeight + railHeight);
  observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => targetsSeen.set(entry.target, entry.isIntersecting
      ? entry.boundingClientRect.top : null));
    const visible = [...targetsSeen]
      .filter(([target, top]) => target.isConnected && top !== null)
      .sort((a, b) => Math.abs(a[1] - offset) - Math.abs(b[1] - offset));
    if (visible.length) setActiveNav(visible[0][0].id);
  }, { rootMargin: `-${offset}px 0px -65% 0px`, threshold: [0, 0.1] });
  document.querySelectorAll('.console-nav a').forEach((link) => {
    const target = targetFromHash(link.hash);
    if (target && !link.parentElement.hidden) {
      targetsSeen.set(target, null);
      observer.observe(target);
    }
  });
}

function syncNav(onSystemChange) {
  const targets = [];
  document.querySelectorAll('.console-nav a').forEach((link) => {
    const target = targetFromHash(link.hash);
    const hidden = !target;
    if (link.parentElement.hidden !== hidden) link.parentElement.hidden = hidden;
    if (target && !hidden) targets.push(target);
  });
  const changed = targets.length !== targetsSeen.size || targets.some((target) => !targetsSeen.has(target));
  if (changed) refreshObserver();
  const chatPanel = $('#chat-pause');
  if (chatPanel && !systemObserver) {
    systemObserver = new MutationObserver(onSystemChange);
    systemObserver.observe(chatPanel, { attributes: true, characterData: true, childList: true, subtree: true });
  }
  onSystemChange();
}

function openHashTarget() {
  const target = targetFromHash(window.location.hash);
  if (!target) return;
  revealTarget(target);
  setActiveNav(target.id);
  setTimeout(() => focusSectionHeading(target));
}

export function mountNav(onSystemChange = () => {}) {
  new ResizeObserver(([entry]) => {
    document.documentElement.style.setProperty('--console-topbar-h',
      `${Math.ceil(entry.borderBoxSize?.[0]?.blockSize ?? entry.target.offsetHeight)}px`);
    refreshObserver();
  }).observe($('.topbar'));
  syncNav(onSystemChange);
  new MutationObserver(() => syncNav(onSystemChange)).observe($('#main'), { childList: true, subtree: true });
  window.addEventListener('hashchange', openHashTarget);
  $('.console-nav').addEventListener('click', (event) => {
    const link = event.target.closest('a');
    const target = link && targetFromHash(link.hash);
    if (!target) return;
    revealTarget(target);
    setActiveNav(target.id);
    setTimeout(() => focusSectionHeading(target));
  });
  if (window.location.hash) openHashTarget();
}
