/* Suggestions open existing controls or fill a draft; the person still confirms. */
import { currentLang, onLang, t } from './i18n_text.js';

const mounted = new WeakMap();
const english = () => currentLang() === 'en';

function available(button) {
  if (button?.tagName?.toLowerCase() !== 'button' || button.disabled
    || button.getAttribute('aria-disabled') === 'true') return false;
  // A reply may complete while another workspace is open. Only the card's own hiding counts.
  for (let node = button; node && !node.matches('.chat-msg'); node = node.parentElement) {
    if (node.hidden || node.getAttribute('inert') !== null) return false;
  }
  return true;
}

export function chipsFor(turn = {}) {
  const { final, host } = turn;
  if (!final || !host || final.emergency || final.refused || final.sensitive
    || ['unknown', 'refused', 'emergency'].includes(final.mode)) return [];
  const cards = [...host.querySelectorAll('article.chat-card[data-card-type]')];
  const action = (id) => cards.flatMap((card) => [...card.querySelectorAll(`[data-card-action="${id}"]`)])
    .find(available);
  const shell = host.closest('.chat-msg') || host;
  const route = action('expand_map') || [...shell.querySelectorAll('button.sv-offer')].find(available);
  const calendar = action('save_calendar');
  const source = Array.isArray(final.citations) && final.citations.length > 0;
  const contextual = cards.some((card) => ['route', 'status'].includes(card.dataset.cardType));
  const chips = [];
  if (route) chips.push({ id: 'open_route', label: t('ui.chips.open_route', english() ? 'Open route' : 'Rotayı aç'), target: route });
  if (calendar) chips.push({ id: 'add_calendar', label: t('ui.chips.add_calendar', english() ? 'Add to calendar' : 'Takvime ekle'), target: calendar });
  if (source || contextual || String(final.answer_text || final.answer || '').trim()) {
    chips.push({ id: 'next_step', label: t('ui.chips.next_step', english() ? 'Step by step' : 'Adım adım'), target: null });
  }
  if (final.follow_suggestion) chips.push({ id: 'follow_topic', label: t('ui.chips.follow_topic', english() ? 'Follow this topic' : 'Bu konuyu takip et'), target: null });
  return chips.slice(0, 3);
}

export function mountContextChips(form, doc) {
  if (!form || !doc) return null;
  if (mounted.has(form)) return mounted.get(form);
  const input = form.querySelector('textarea');
  if (!input) return null;
  const row = doc.createElement('div');
  row.className = 'context-chips';
  row.setAttribute('role', 'group');
  row.hidden = true;
  (input.closest('.chat-row') || input).before(row);
  mounted.set(form, row);
  let turn = null, dismissed = false, previous = [];
  const clear = () => {
    turn = null; previous = [];
    row.replaceChildren(); row.hidden = true;
  };
  const log = doc.getElementById('chat-log');
  const latest = () => {
    if (!turn?.host?.isConnected) return false;
    const assistants = log?.querySelectorAll('.chat-msg.is-assistant');
    return !assistants?.length || assistants[assistants.length - 1] === turn.host.closest('.chat-msg');
  };
  const activate = (chip) => {
    if (!latest()) { clear(); return; }
    const current = chipsFor(turn).find((item) => item.id === chip.id && item.target === chip.target);
    if (!current) return;
    if (chip.id === 'follow_topic' || chip.id === 'next_step') {
      if (!turn.question) return;
      const draft = chip.id === 'next_step'
        ? t('ui.chips.next_step_draft', english() ? 'What should I do first about this?' : 'Bu konuda ilk ne yapmalıyım?')
        : t('ui.chips.follow_draft', english() ? 'Follow this: {question}' : 'Bunu takip et: {question}', { question: turn.question });
      input.value = draft.slice(0, input.maxLength > 0 ? input.maxLength : 300);
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.focus({ preventScroll: true });
      return;
    }
    // The card's own listener opens its consent row. Never publish an action here.
    const target = current.target;
    target.scrollIntoView?.({ block: 'nearest', behavior: 'instant' });
    target.click();
  };
  const render = () => {
    row.setAttribute('aria-label', t('ui.chips.group', english() ? 'Suggestions' : 'Öneriler'));
    if (!turn) return;
    if (!latest()) { clear(); return; }
    if (dismissed || input.value.trim()) { row.hidden = true; return; }
    const chips = chipsFor(turn).filter((chip) => !['follow_topic', 'next_step'].includes(chip.id) || turn.question);
    if (!chips.length) { previous = []; row.replaceChildren(); row.hidden = true; return; }
    if (previous.length === chips.length && chips.every((chip, index) =>
      chip.id === previous[index].id && chip.target === previous[index].target && chip.label === previous[index].label)) return;
    previous = chips;
    row.replaceChildren();
    for (const chip of chips) {
      const button = doc.createElement('button');
      button.type = 'button'; button.className = 'context-chip';
      button.dataset.contextChip = chip.id;
      button.textContent = chip.label;
      button.addEventListener('click', () => activate(chip));
      row.append(button);
    }
    row.hidden = chips.length === 0;
  };
  doc.addEventListener('nabiz:chat-final', (event) => {
    turn = event.detail || null; dismissed = false; previous = [];
    render();
  });
  doc.addEventListener('nabiz:emergency', clear);
  input.addEventListener('input', () => { dismissed = true; row.hidden = true; });
  form.addEventListener('submit', clear);
  // E50 can insert its offer after chat-final; history replacement detaches the old host.
  if (log && typeof MutationObserver !== 'undefined') new MutationObserver(render).observe(log,
    { childList: true, subtree: true, attributes: true, attributeFilter: ['aria-busy', 'aria-disabled', 'hidden'] });
  onLang(render);
  render();
  return row;
}
