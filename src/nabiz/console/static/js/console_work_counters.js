// İşler (P00): the decision desk's first-screen counters, one line each under #desk-title.
// A counter at 0 is hidden, and the list hides when no counter shows: nothing irrelevant on the first
// screen. The full tables stay in the closed disclosures; a counter's link opens the one that holds
// its table and gives focus to that table's heading. The panels call setWorkCounter; this file
// fetches nothing and keeps no state of its own.

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
