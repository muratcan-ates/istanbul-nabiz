"""Context suggestions use the existing card consent boundary and never submit a draft."""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest
from test_chat_cards_static import DOM, STATIC

CHIPS = STATIC / "js" / "context_chips.js"
CATALOG = {
    "tr": {
        "ui.chips.group": "Öneriler", "ui.chips.open_route": "Rotayı aç",
        "ui.chips.add_calendar": "Takvime ekle", "ui.chips.follow_topic": "Bu konuyu takip et",
        "ui.chips.follow_draft": "Bunu takip et: {question}",
        "ui.chips.next_step": "Adım adım", "ui.chips.next_step_draft": "Bu konuda ilk ne yapmalıyım?",
    },
    "en": {
        "ui.chips.group": "Suggestions", "ui.chips.open_route": "Open route",
        "ui.chips.add_calendar": "Add to calendar", "ui.chips.follow_topic": "Follow this topic",
        "ui.chips.follow_draft": "Follow this: {question}",
        "ui.chips.next_step": "Step by step", "ui.chips.next_step_draft": "What should I do first about this?",
    },
}

HARNESS = DOM + r"""
Node.prototype.matches = function(selector) {
  return selector.split(',').some(part => {
    const value = part.trim();
    const tag = value.match(/^[a-z]+/i)?.[0];
    if (tag && this.tagName.toLowerCase() !== tag.toLowerCase()) return false;
    if ([...value.matchAll(/\.([\w-]+)/g)].some(match => !this.className.split(' ').includes(match[1]))) return false;
    if (value.startsWith('#')) return this.id === value.slice(1);
    return [...value.matchAll(/\[([\w-]+)(?:="([^"]*)")?\]/g)].every(([, name, expected]) => {
      const key = name.replace(/^data-/, '').replace(/-([a-z])/g, (_, char) => char.toUpperCase());
      const actual = name.startsWith('data-') ? this.dataset[key]
        : name === 'hidden' ? (this.hidden ? '' : undefined) : this.attrs[name];
      return expected === undefined ? actual !== undefined : actual === expected;
    });
  });
};
Node.prototype.replaceChildren = function(...nodes) { [...this.children].forEach(node => node.remove()); this.append(...nodes); };
Node.prototype.click = function() { if (!this.disabled) this.dispatchEvent({type: 'click', target: this}); };
Node.prototype.scrollIntoView = function(options) { this.scrolled = options; };
document.getElementById = id => document.querySelector('#' + id);
document.documentElement = new Node('html'); document.documentElement.lang = 'tr';
const mutations = [];
globalThis.MutationObserver = class { constructor(callback) { this.callback = callback; mutations.push(this); }
  observe() {} disconnect() {} };
const tick = () => mutations.forEach(observer => observer.callback([]));
const element = (tag, className = '') => { const node = new Node(tag); node.className = className; return node; };
const form = element('form'), inputRow = element('div', 'chat-row'), input = element('textarea');
input.value = ''; input.maxLength = 300; inputRow.append(input); form.append(inputRow); document.body.append(form);
const log = element('ol'); log.id = 'chat-log'; document.body.append(log);
const shell = element('li', 'chat-msg is-assistant'), host = element('div', 'chat-final');
shell.append(host); log.append(shell);
const card = (type, action) => {
  const article = element('article', 'chat-card'); article.dataset.cardType = type;
  if (action) { const button = element('button'); button.dataset.cardAction = action; article.append(button); }
  host.append(article); return article;
};
const final = (data = {citations: [{}]}, question = 'M2 durumu?') => document.dispatchEvent(
  new CustomEvent('nabiz:chat-final', {detail: {final: data, host, question}}));
const mounted = chips.mountContextChips(form, document);
const getChip = id => mounted.children.find(node => node.dataset.contextChip === id);
const ids = () => mounted.children.map(node => node.dataset.contextChip);
"""


def run_chips(tmp_path, code: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    script = tmp_path / "context_chips.mjs"
    script.write_text(
        f"import * as chips from {json.dumps(CHIPS.as_uri())};\n"
        f"import * as cards from {json.dumps((STATIC / 'js/chat_cards.js').as_uri())};\n"
        f"import {{setCatalogs}} from {json.dumps((STATIC / 'js/i18n_text.js').as_uri())};\n"
        + HARNESS + code, encoding="utf-8",
    )
    result = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_catalog_and_module_boundary() -> None:
    content = CHIPS.read_text()
    assert CATALOG["tr"].keys() == CATALOG["en"].keys()
    assert set(re.findall(r"t\('(ui\.chips\.[^']+)'", content)) == CATALOG["tr"].keys()
    assert len(content.splitlines()) <= 200
    for forbidden in ("registerCardType(", "requestSubmit", "innerHTML", "fetch(", "btn-primary"):
        assert forbidden not in content
    for catalog in CATALOG.values():
        for value in catalog.values():
            assert not re.search(r"[\u2013\u2014]|\b(?:canlı|live|sen)\b", value, flags=re.I)


def test_selection_requires_context_and_available_card_controls(tmp_path) -> None:
    result = run_chips(tmp_path, r"""
const empty = chips.chipsFor({final: {}, host});
const event = card('event');
const noAction = chips.chipsFor({final: {}, host});
const route = card('route', 'expand_map'), save = card('calendar_draft', 'save_calendar');
card('map', 'expand_map'); card('event', 'save_calendar');
const turn = {final: {citations: [{}]}, host};
const selected = chips.chipsFor(turn);
const original = selected[0].target === route.children[0] && selected[1].target === save.children[0];
const emergency = chips.chipsFor({...turn, final: {emergency: true, citations: [{}]}});
const refused = chips.chipsFor({...turn, final: {refused: true, citations: [{}]}});
host.replaceChildren(event); const button = element('button'); button.dataset.cardAction = 'save_calendar';
button.setAttribute('aria-disabled', 'true'); event.append(button);
const unavailable = chips.chipsFor({final: {}, host});
console.log(JSON.stringify({empty, noAction, selected: selected.map(chip => chip.id),
  original, emergency, refused, unavailable}));
""")
    assert result == {
        "empty": [], "noAction": [], "selected": ["open_route", "add_calendar", "next_step"],
        "original": True, "emergency": [], "refused": [], "unavailable": [],
    }


def test_calendar_chip_opens_real_consent_and_only_confirm_publishes(tmp_path) -> None:
    result = run_chips(tmp_path, r"""
let events = [];
document.addEventListener('nabiz:card-action', event => { events.push(event.detail); event.preventDefault(); });
cards.registerCardType('calendar_draft', () => element('p'));
const article = cards.appendCard(host, {v: 1, id: 'calendar-p26', type: 'calendar_draft', status: 'ready',
  title: 'Hafta sonu', body: {}, sources: [], actions: [{id: 'save_calendar', operation_id: 'op-p26'}]}, {messageId: 'm-p26'});
final({}); getChip('add_calendar').click();
const consent = article.querySelector('.chat-card-consent');
const before = {events: events.length, consent: !!consent, focus: document.activeElement === consent.querySelector('button')};
consent.querySelector('button').click();
console.log(JSON.stringify({before, after: events.length, action: events[0]?.action,
  consented: !!events[0]?.consented_at, operation: events[0]?.operation_id}));
""")
    assert result == {
        "before": {"events": 0, "consent": True, "focus": True}, "after": 1,
        "action": "save_calendar", "consented": True, "operation": "op-p26",
    }


def test_follow_draft_mount_order_and_lifecycle(tmp_path) -> None:
    result = run_chips(tmp_path, r"""
let submits = 0, inputs = 0;
form.addEventListener('submit', () => submits++); input.addEventListener('input', () => inputs++);
const once = chips.mountContextChips(form, document) === mounted;
final({citations: [{}], follow_suggestion: {topic: 'M2'}}); getChip('follow_topic').click();
const draft = {text: input.value, submits, inputs, hidden: mounted.hidden, focus: document.activeElement === input};
input.value = ''; final(); input.value = 'Başka soru'; input.dispatchEvent(new Event('input')); tick();
const typedHidden = mounted.hidden;
input.value = ''; final(); form.dispatchEvent(new Event('submit'));
const cleared = mounted.hidden && mounted.children.length === 0;
final(); final({emergency: true, citations: [{}]});
const emergency = mounted.hidden && mounted.children.length === 0;
final(); final({}); const unrelated = mounted.hidden && mounted.children.length === 0;
final(); shell.remove(); tick(); const history = mounted.hidden && mounted.children.length === 0;
console.log(JSON.stringify({once, order: form.children[0] === mounted, group: mounted.getAttribute('role'),
  label: mounted.getAttribute('aria-label'), noAnnouncement: mounted.getAttribute('aria-live') === null,
  draft, typedHidden, cleared, emergency, unrelated, history}));
""")
    assert result == {
        "once": True, "order": True, "group": "group", "label": "Öneriler", "noAnnouncement": True,
        "draft": {"text": "Bunu takip et: M2 durumu?", "submits": 0, "inputs": 1, "hidden": True, "focus": True},
        "typedHidden": True, "cleared": True, "emergency": True, "unrelated": True, "history": True,
    }


def test_late_controls_open_the_existing_step_offer(tmp_path) -> None:
    result = run_chips(tmp_path, r"""
final({}); const before = ids();
const save = card('calendar_draft', 'save_calendar'); tick(); const calendar = ids();
const offer = element('button', 'sv-offer'); let opened = 0;
offer.addEventListener('click', () => opened++); shell.append(offer); tick();
getChip('open_route').click();
const step = {ids: ids(), focus: document.activeElement === offer, opened, scroll: offer.scrolled.behavior};
save.children[0].setAttribute('aria-disabled', 'true'); tick(); const pending = ids();
log.append(element('li', 'chat-msg is-assistant')); tick();
console.log(JSON.stringify({before, calendar, step, pending, replaced: mounted.hidden}));
""")
    assert result == {
        "before": [], "calendar": ["add_calendar"],
        "step": {"ids": ["open_route", "add_calendar"], "focus": False, "opened": 1, "scroll": "instant"},
        "pending": ["open_route"], "replaced": True,
    }


def test_english_fallback_and_emergency_event(tmp_path) -> None:
    result = run_chips(tmp_path, r"""
setCatalogs('en', {}, {}); final({citations: [{}], follow_suggestion: {topic: 'M2'}});
const label = getChip('follow_topic').textContent; getChip('follow_topic').click();
const draft = input.value; input.value = ''; final();
document.dispatchEvent(new CustomEvent('nabiz:emergency', {detail: {}}));
console.log(JSON.stringify({label, draft, group: mounted.getAttribute('aria-label'), hidden: mounted.hidden}));
""")
    assert result == {"label": "Follow this topic", "draft": "Follow this: M2 durumu?", "group": "Suggestions", "hidden": True}


def test_other_workspace_does_not_hide_an_available_reply_action(tmp_path) -> None:
    result = run_chips(tmp_path, r"""
log.hidden = true;
const route = card('route', 'expand_map'); final({}); const away = ids();
log.hidden = false; tick(); const returned = ids();
route.hidden = true; tick(); const hiddenCard = ids();
console.log(JSON.stringify({away, returned, hiddenCard}));
""")
    assert result == {
        "away": ["open_route", "next_step"], "returned": ["open_route", "next_step"],
        "hiddenCard": ["next_step"],
    }


def test_step_help_is_a_question_draft_and_follow_requires_an_actual_offer(tmp_path) -> None:
    result = run_chips(tmp_path, r"""
let submits = 0;
form.addEventListener('submit', () => submits++);
final(); const initial = ids(); getChip('next_step').click();
const draft = {text: input.value, submits, focus: document.activeElement === input};
input.value = ''; final({citations: [{}], follow_suggestion: {topic: 'M2'}}); const offered = ids();
input.value = ''; final({mode: 'unknown', answer_text: 'Bilmiyorum.'}); const unavailable = ids();
console.log(JSON.stringify({initial, draft, offered, unavailable}));
""")
    assert result == {
        "initial": ["next_step"],
        "draft": {"text": "Bu konuda ilk ne yapmalıyım?", "submits": 0, "focus": True},
        "offered": ["next_step", "follow_topic"], "unavailable": [],
    }


def test_chips_have_solid_accessible_styles_and_no_new_sheet() -> None:
    content = (STATIC / "css/components.css").read_text()
    assert ".context-chips[hidden] { display: none; }" in content
    assert "@media (pointer: coarse) { .context-chip { min-height: var(--tap); } }" in content
    assert ".context-chip:focus-visible { outline: 2px solid var(--focus-ring)" in content
    assert "@media (prefers-reduced-transparency: reduce), (prefers-contrast: more)" in content
    assert ".context-chip { background: ButtonFace; color: ButtonText; border-color: ButtonText; }" in content
    assert "stylesheet" not in CHIPS.read_text()
