// İşler (P00): the decision desk's first-screen counters under #desk-title. A counter at 0 is hidden and
// the list hides when none shows. A counter's link opens the closed disclosure that holds its table and
// gives focus to that table's heading. Nothing here is stored.

export function setWorkCounter(id, label, count, href, doc = globalThis.document) {
  const list = doc?.getElementById('work-counters');
  if (!list) return null;
  let item = [...list.children].find((li) => li.dataset.counter === id);
  if (!item) {
    item = doc.createElement('li');
    item.dataset.counter = id;
    const link = doc.createElement('a');
    link.href = href;
    link.addEventListener('click', (event) => openTarget(href, event, doc));
    item.append(link);
    list.append(item);
  }
  const n = Math.max(0, Math.trunc(Number(count)) || 0);
  item.firstElementChild.textContent = `${label}: ${n}`;
  item.hidden = n === 0;
  list.hidden = [...list.children].every((li) => li.hidden);
  return item;
}

export function openTarget(href, event, doc = globalThis.document) {
  const target = doc.querySelector(href);
  if (!target) return false;
  event?.preventDefault();
  const disclosure = target.closest('details');
  if (disclosure) disclosure.open = true;
  const heading = target.matches('h2, h3') ? target : target.querySelector('h2, h3');
  const focusable = heading || disclosure?.querySelector('summary') || target;
  if (focusable === heading && !heading.hasAttribute('tabindex')) heading.setAttribute('tabindex', '-1');
  focusable.focus();
  return true;
}

// The three counters (P00 G2), each from its panel's own endpoint; a failed read shows no counter, not a zero.
const COUNTERS = [
  ['timeline', 'Sizi bekleyen bildirim', '#report-timeline-console', '/api/console/report-timeline',
    (body) => (body.items || []).filter((item) => item.waiting_on === 'operator').length],
  ['escort', 'Yeni destek talebi', '#escort-console', '/api/console/escort',
    (body) => (body.items || []).filter((item) => item.status === 'received').length],
  ['poll', 'Yayın bekleyen anket taslağı', '#istanbula-sor-konsol', '/api/console/polls', (body) => (body.draft ? 1 : 0)],
];

export async function refreshWorkCounters(getJson, doc = globalThis.document) {
  await Promise.all(COUNTERS.map(async ([id, label, href, path, count]) => {
    try { setWorkCounter(id, label, count(await getJson(path)), href, doc); } catch { /* no counter */ }
  }));
}

if (typeof window !== 'undefined' && document.getElementById('work-counters')) {
  const { MOCK, get } = await import('./api.js');
  if (!MOCK) {
    refreshWorkCounters(get);
    window.addEventListener('nabiz:ledger-changed', () => refreshWorkCounters(get));
  }
}
