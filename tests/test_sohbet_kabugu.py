"""The citizen shell keeps one conversation surface, one composer and bounded history."""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest
from conftest import REPO_ROOT
from test_vatandas_composer import inside, page, text_of
from test_workspace_navigation import DOM as WORKSPACE_DOM

STATIC = REPO_ROOT / "src" / "nabiz" / "console" / "static"
JS = STATIC / "js"

CATALOG = {
    "tr": {
        "ui.shell.nav_assistant": "Asistan", "ui.shell.nav_calendar": "Takvim",
        "ui.shell.nav_account": "Hesabım", "ui.shell.nav_other": "Diğer bölümler",
        "ui.shell.nav_follow": "Takip", "ui.shell.more": "Daha fazla",
        "ui.shell.new_reply": "Yeni yanıt", "ui.shell.examples": "Neler sorabilirsiniz",
        "ui.shell.example_1": "Kadıköy'den Levent'e merdivensiz nasıl giderim?",
        "ui.shell.example_2": "M2'de asansör arızası var mı?",
        "ui.shell.example_3": "Bu hafta sonu ücretsiz bir kültür etkinliği var mı?",
        "ui.shell.example_4": "Sokağımdaki bozuk lambayı nasıl bildiririm?",
        "ui.shell.calendar_title": "Takvim",
        "ui.shell.calendar_note": "Kaydettiğiniz planlar burada görünür.",
        "ui.shell.calendar_empty": "Henüz kaydedilmiş plan yok. Sohbette bir etkinliği takvime eklediğinizde burada görünür.",
    },
    "en": {
        "ui.shell.nav_assistant": "Assistant", "ui.shell.nav_calendar": "Calendar",
        "ui.shell.nav_account": "My account", "ui.shell.nav_other": "Other sections",
        "ui.shell.nav_follow": "Follow", "ui.shell.more": "More",
        "ui.shell.new_reply": "New reply", "ui.shell.examples": "Things you can ask",
        "ui.shell.example_1": "How can I get from Kadıköy to Levent without stairs?",
        "ui.shell.example_2": "Is there a lift outage on the M2 line?",
        "ui.shell.example_3": "Is there a free cultural event this weekend?",
        "ui.shell.example_4": "How can I report a broken streetlight?",
        "ui.shell.calendar_title": "Calendar",
        "ui.shell.calendar_note": "Your saved plans appear here.",
        "ui.shell.calendar_empty": "No saved plans yet. When you add an event to your calendar in chat, it will appear here.",
    },
}


def run_node(name: str, setup: str, code: str) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    script = f"{setup}\n{code}\n"
    result = subprocess.run([node, "--input-type=module", "-e", script], cwd=REPO_ROOT,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, f"{name}: {result.stderr}"
    return json.loads(result.stdout)


def test_shell_markup_and_honest_text() -> None:
    document = page()
    topbar = next(item for item in document.elements if "topbar" in item.classes())
    role = next(item for item in document.elements if "topbar-role" in item.classes())
    assert inside(role, topbar) and "Resmî İBB hizmeti değildir" in text_of(role)

    nav = next(item for item in document.elements if "topbar-nav" in item.classes())
    primary = next(item for item in document.elements if "nav-primary" in item.classes())
    secondary = next(item for item in document.elements if "nav-secondary" in item.classes())
    assert inside(primary, nav) and inside(secondary, nav) and primary.order < secondary.order
    primary_links = [item.attrs.get("href") for item in document.elements if item.tag == "a" and inside(item, primary)]
    assert primary_links == ["#asistan", "#takvim", "#hesabim"]
    assert secondary.attrs.get("aria-label") == CATALOG["tr"]["ui.shell.nav_other"]

    calendar = document.id("takvim")
    assert calendar.tag == "section" and "hidden" in calendar.attrs
    assert calendar.attrs.get("aria-labelledby") == "takvim-title"
    assert inside(document.id("takvim-mount"), calendar)
    assert text_of(document.id("takvim-empty")) == CATALOG["tr"]["ui.shell.calendar_empty"]
    heading = document.id("takvim-title")
    assert heading.tag == "h2" and heading.attrs.get("tabindex") == "-1"
    assert heading.attrs.get("data-i18n") == "ui.shell.calendar_title"
    assert calendar.children[1].attrs.get("data-i18n") == "ui.shell.calendar_note"
    assert text_of(calendar.children[1]) == CATALOG["tr"]["ui.shell.calendar_note"]
    assert document.id("takvim-empty").attrs.get("data-i18n") == "ui.shell.calendar_empty"

    assistant = document.id("asistan")
    assistant_head = next(item for item in document.elements if "assistant-head" in item.classes())
    assert inside(assistant_head, assistant) and inside(document.id("convo-root"), assistant_head)
    for name in ("profilim", "hafizam", "takip", "map-workspace", "acik-veri"):
        assert document.id(name)


def test_four_examples_precede_category_chips_and_submit_one_question() -> None:
    document = page()
    examples, form, quick = (document.id(name) for name in ("capability-examples", "chat-form", "quick-cards"))
    assert examples.tag == "ul" and examples.order < quick.order
    assert form.order < examples.order
    assert examples.attrs.get("aria-label") == CATALOG["tr"]["ui.shell.examples"]
    assert "chip-example" in (STATIC / "css" / "citizen.css").read_text()

    values = run_node("examples", CHAT_DOM, f"""
    const main = add(body, 'main', 'main');
    const hero = add(main, 'section', 'home-screen'); main.append(chat);
    const exampleList = add(hero, 'ul', 'capability-examples');
    add(hero, 'div', 'quick-cards');
    const more = add(hero, 'details', 'quick-more'); add(more, 'div', 'quick-more-cards');
    const composerMore = add(hero, 'details', 'composer-more'); add(composerMore, 'summary');
    const pill = add(body, 'button', 'ask-pill', 'btn-primary'); pill.hidden = true;
    add(body, 'nav', '', 'topbar-nav');
    const {{ EXAMPLES, mountHome }} = await import({json.dumps((JS / 'home.js').as_uri())});
    const {{ setCatalogs }} = await import({json.dumps((JS / 'i18n_text.js').as_uri())});
    setCatalogs('tr', {{}}, {{}});
    const asked = []; form.requestSubmit = () => asked.push(input.value);
    mountHome({{form, input}});
    const trButtons = exampleList.querySelectorAll('button[data-example]');
    trButtons[0].dispatchEvent({{type: 'click'}});
    html.lang = 'en'; setCatalogs('en', {{}}, {{}});
    window.dispatchEvent(new CustomEvent('nabiz:lang', {{detail: {{lang: 'en'}}}}));
    const enButtons = exampleList.querySelectorAll('button[data-example]');
    enButtons[1].dispatchEvent({{type: 'click'}});
    observers[0].callback([{{isIntersecting: false}}]);
    const pillBeforeChat = pill.hidden;
    body.classList.add('has-conversation'); observers[0].callback([{{isIntersecting: false}}]);
    console.log(JSON.stringify({{list: EXAMPLES.map(item => [item.id, item.tr, item.en, item.icon]), asked,
      count: enButtons.length, english: enButtons[0].textContent, pillBeforeChat, pillAfterChat: pill.hidden}}));
    """)
    assert len(values["list"]) == 4
    for index, (key, tr, en, icon) in enumerate(values["list"], start=1):
        assert key == f"example_{index}"
        assert (tr, en) == (CATALOG["tr"][f"ui.shell.{key}"], CATALOG["en"][f"ui.shell.{key}"])
        assert icon in ("elevator", "info-circle", "external-link")
    assert values["count"] == 4
    assert values["asked"] == [CATALOG["tr"]["ui.shell.example_1"], CATALOG["en"]["ui.shell.example_2"]]
    assert values["english"] == CATALOG["en"]["ui.shell.example_1"]
    assert values["pillBeforeChat"] is False and values["pillAfterChat"] is True


def test_catalog_keys_and_static_sticky_guards() -> None:
    assert CATALOG["tr"].keys() == CATALOG["en"].keys()
    code = "\n".join((JS / name).read_text() for name in ("chat_scroll.js", "workspace_nav.js", "home.js"))
    literal = set(re.findall(r"t\(['\"](ui\.shell\.[a-z_0-9]+)['\"]", code))
    assert literal <= CATALOG["tr"].keys()
    assert {f"ui.shell.example_{number}" for number in range(1, 5)} <= CATALOG["tr"].keys()
    for translated in CATALOG.values():
        assert not any(mark in text for text in translated.values() for mark in ("\u2013", "\u2014"))
        assert not any(word in text.casefold() for text in translated.values() for word in ("canlı", "live"))

    css = (STATIC / "css" / "workspace.css").read_text()
    sticky = re.search(r"\.has-conversation #chat-form\s*\{([^}]+)\}", css)
    assert sticky is not None and "position: sticky" in sticky.group(1)
    assert "env(safe-area-inset-bottom)" in sticky.group(1) and "var(--z-sticky)" in sticky.group(1)
    assert ".has-conversation #asistan" in css and "--chat-composer-height" in css
    assert ".has-conversation #chat-log" in css and ".has-conversation #ask-pill { display: none" in css
    assert "#chat-new-reply" in css and "bottom: calc(100% + 8px)" in css
    assert "prefers-reduced-transparency" in css and "forced-colors: active" in css
    assert "background: var(--surface-raised)" in css
    assert "body:not(.has-conversation) #chat-form { position: sticky" not in css


def test_legacy_placement_changes_only_menu_not_destination() -> None:
    script = f"""
import * as workspace from {json.dumps((JS / 'workspace_nav.js').as_uri())};
{WORKSPACE_DOM}
const s = setup('#city-cards');
const original = workspace.LEGACY_PLACEMENT.map(item => [item.id, item.placement]);
const item = workspace.LEGACY_PLACEMENT[0];
const values = [];
for (const placement of ['nav', 'more', 'hash-only']) {{
  item.placement = placement;
  workspace.applyLegacyPlacement();
  const link = s.links[3];
  const row = link.parentElement;
  values.push({{placement, hidden: row.hidden, parent: row.parentElement.id,
    view: workspace.viewForTarget(s.doc.getElementById('city-cards'))}});
}}
workspace.mountWorkspace(s);
console.log(JSON.stringify({{original, values, hashView: s.body.dataset.view}}));
"""
    values = run_node("placement", "", script)
    assert len(values["original"]) == 7
    # Murat's 27 Sep decision (P01 integration): four under "Daha fazla", open data and follow by
    # address only, Kolay ekran in the top bar.
    assert dict(values["original"]) == {
        "city": "more", "travel": "more", "map": "more", "nearby": "more",
        "data": "hash-only", "follow": "hash-only", "easy": "topbar",
    }
    assert values["values"] == [
        {"placement": "nav", "hidden": False, "parent": "legacy-nav", "view": "city"},
        {"placement": "more", "hidden": False, "parent": "legacy-more-links", "view": "city"},
        {"placement": "hash-only", "hidden": True, "parent": "legacy-nav", "view": "city"},
    ]
    assert values["hashView"] == "city"


def test_primary_and_legacy_hashes_reveal_the_expected_workspace() -> None:
    targets = {
        "asistan": "assistant", "takvim": "calendar", "hesabim": "account",
        "profilim": "account", "hafizam": "account", "takip": "account",
        "harita": "map", "acik-veri": "data",
    }
    code = f"""
import * as workspace from {json.dumps((JS / 'workspace_nav.js').as_uri())};
{WORKSPACE_DOM}
const targets = {json.dumps(targets)};
const views = {{}};
for (const id of Object.keys(targets)) {{
  const s = setup(`#${{id}}`);
  workspace.mountWorkspace(s);
  views[id] = s.body.dataset.view;
}}
console.log(JSON.stringify(views));
"""
    assert run_node("hashes", "", code) == targets


CHAT_DOM = r"""
class Node {
  constructor(tag = 'div', doc = null) {
    this.tagName = tag; this.ownerDocument = doc || globalThis.document || this;
    this.children = []; this.parentElement = null; this.dataset = {}; this.attrs = {};
    this.listeners = {}; this.hidden = false; this.open = false; this.id = ''; this.className = '';
    this._text = ''; this._html = ''; this.style = {values: {}, setProperty(name, value) { this.values[name] = value; }};
    this.classList = {contains: name => this.className.split(' ').includes(name),
      add: (...names) => { this.className = [...new Set([...this.className.split(' '), ...names])].filter(Boolean).join(' '); },
      remove: name => { this.className = this.className.split(' ').filter(item => item !== name).join(' '); },
      toggle: (name, force) => { const has = this.classList.contains(name); if (force ?? !has) this.classList.add(name);
        else this.classList.remove(name); return this.classList.contains(name); }};
  }
  set textContent(value) { this.replaceChildren(); this._text = String(value); }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  set innerHTML(html) {
    this.replaceChildren(); this._text = ''; this._html = String(html);
    const stack = [this]; let cursor = 0;
    for (const match of String(html).matchAll(/<(\/?)((?:[A-Za-z][\w:-]*))([^>]*)>/g)) {
      stack.at(-1)._text += String(html).slice(cursor, match.index); cursor = match.index + match[0].length;
      if (match[1]) { if (stack.length > 1) stack.pop(); continue; }
      const node = new Node(match[2], this.ownerDocument);
      for (const attr of match[3].matchAll(/([\w:-]+)(?:="([^"]*)")?/g)) node.setAttribute(attr[1], attr[2] ?? '');
      stack.at(-1).append(node);
      if (!['br', 'hr', 'img', 'input', 'link', 'meta', 'source'].includes(node.tagName)) stack.push(node);
    }
    stack.at(-1)._text += String(html).slice(cursor);
  }
  get innerHTML() { return this._html; }
  setAttribute(name, value) {
    this.attrs[name] = String(value);
    if (name === 'class') this.className = String(value);
    if (name === 'id') this.id = String(value);
    if (name === 'hidden') this.hidden = true;
    if (name.startsWith('data-')) {
      this.dataset[name.slice(5).replace(/-([a-z])/g, (_, char) => char.toUpperCase())] = String(value);
    }
  }
  getAttribute(name) {
    if (name.startsWith('data-')) {
      return this.dataset[name.slice(5).replace(/-([a-z])/g, (_, char) => char.toUpperCase())] ?? null;
    }
    return this.attrs[name] ?? null;
  }
  removeAttribute(name) { delete this.attrs[name]; }
  matches(selector) {
    selector = selector.trim();
    const excluded = [...selector.matchAll(/:not\(([^)]+)\)/g)];
    if (excluded.some(match => this.matches(match[1]))) return false;
    selector = selector.replace(/:not\([^)]+\)/g, '');
    const tag = selector.match(/^[A-Za-z][\w-]*/);
    if (tag && this.tagName !== tag[0]) return false;
    const id = selector.match(/#([\w-]+)/);
    if (id && this.id !== id[1]) return false;
    for (const cls of selector.matchAll(/\.([\w-]+)/g)) if (!this.classList.contains(cls[1])) return false;
    for (const attr of selector.matchAll(/\[([\w-]+)(\^?=)?"?([^\]"]*)"?\]/g)) {
      const value = this.getAttribute(attr[1]);
      if (value === null || attr[2] === '=' && value !== attr[3]
        || attr[2] === '^=' && !value.startsWith(attr[3])) return false;
    }
    return Boolean(selector);
  }
  closest(selector) {
    return selector.split(',').some(item => this.matches(item)) ? this : this.parentElement?.closest(selector) || null;
  }
  contains(node) { return !!node && (node === this || this.children.some(child => child.contains(node))); }
  querySelectorAll(selector) {
    if (selector.includes(',')) return [...new Set(selector.split(',').flatMap(part => this.querySelectorAll(part.trim())))];
    const bits = selector.trim().split(/\s+/), leaf = bits.pop(), parent = bits.join(' ');
    return this.children.flatMap(child => [child, ...child.querySelectorAll('*')]).filter(child =>
      (leaf === '*' || child.matches(leaf)) && (!parent || child.parentElement?.closest(parent)));
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  append(...nodes) { nodes.forEach(node => { node.remove(); node.parentElement = this; this.children.push(node); }); }
  appendChild(node) { this.append(node); return node; }
  prepend(...nodes) {
    nodes.reverse().forEach(node => { node.remove(); node.parentElement = this; this.children.unshift(node); });
  }
  replaceChildren(...nodes) {
    this.children.forEach(node => { node.parentElement = null; }); this.children = []; this.append(...nodes);
  }
  insertAdjacentHTML(position, html) {
    const wrapper = new Node('div', this.ownerDocument); wrapper.innerHTML = html;
    for (const child of [...wrapper.children]) {
      if (position === 'beforebegin') this.before(child);
      if (position === 'afterend') this.after(child);
    }
  }
  before(node) { node.remove(); const rows = this.parentElement.children;
    node.parentElement = this.parentElement; rows.splice(rows.indexOf(this), 0, node); }
  after(node) { node.remove(); const rows = this.parentElement.children;
    node.parentElement = this.parentElement; rows.splice(rows.indexOf(this) + 1, 0, node); }
  remove() { if (this.parentElement) { const rows = this.parentElement.children;
    rows.splice(rows.indexOf(this), 1); } this.parentElement = null; }
  get isConnected() { return this === document || !!this.parentElement?.isConnected; }
  getBoundingClientRect() { return {top: 0, bottom: 200, height: 88}; }
  focus(options) { this.ownerDocument.activeElement = this; this.focusOptions = options; }
  scrollIntoView(options) { scrollCalls.push({node: this, options}); }
  addEventListener(type, listener) { (this.listeners[type] ||= []).push(listener); }
  dispatchEvent(event) { event.target ||= this; (this.listeners[event.type] || []).forEach(listener => listener(event));
    if (event.bubbles !== false) this.parentElement?.dispatchEvent(event); }
  showModal() { this.open = true; }
  close() { this.open = false; this.dispatchEvent({type: 'close', bubbles: false}); }
}
const scrollCalls = [];
const document = new Node('document'); globalThis.document = document;
document.createElement = tag => new Node(tag, document);
document.createComment = () => new Node('comment', document);
const html = document.createElement('html'), head = document.createElement('head'), body = document.createElement('body');
document.append(html); html.append(head, body);
document.documentElement = html; document.head = head; document.body = body; html.lang = 'tr';
html.scrollHeight = 2400; body.scrollHeight = 2400;
document.getElementById = id => document.querySelector(`#${id}`);
globalThis.CustomEvent = class { constructor(type, options = {}) { this.type = type; this.detail = options.detail;
  this.bubbles = options.bubbles ?? false; } };
const listeners = {};
const window = {scrollY: 1600, innerHeight: 800, location: new URL('https://nabiz.test/?mock=0&lang=tr'),
  addEventListener(type, listener) { (listeners[type] ||= []).push(listener); },
  dispatchEvent(event) { (listeners[event.type] || []).forEach(listener => listener(event)); },
  scrollTo(_x, y) { this.scrollY = y; },
  matchMedia(query) { return {matches: query.includes('max-width'), addEventListener() {}}; }};
globalThis.window = window; globalThis.location = window.location;
globalThis.MutationObserver = class { constructor(callback) { this.callback = callback; } observe() {} disconnect() {} };
const observers = [];
globalThis.IntersectionObserver = class { constructor(callback) { this.callback = callback; observers.push(this); }
  observe(node) { this.node = node; } disconnect() { this.node = null; } };
window.IntersectionObserver = globalThis.IntersectionObserver;
globalThis.requestAnimationFrame = callback => callback();
const add = (parent, tag, id = '', className = '') => { const node = document.createElement(tag);
  node.id = id; node.className = className; parent.append(node); return node; };
const chat = add(body, 'section', 'asistan');
const log = add(chat, 'ol', 'chat-log'), form = add(chat, 'form', 'chat-form', 'composer glass');
const input = add(form, 'textarea', 'chat-input'), submit = add(form, 'button', 'chat-submit');
const status = add(chat, 'p', 'chat-status'), tools = add(form, 'div', 'composer-tools');
add(form, 'p', '', 'field-error').hidden = true;
const sent = [], turns = [];
const finalCard = {v: 1, id: 'card-a', type: 'info', status: 'ready', title: 'A kartı',
  body: {text: 'A içeriği'}, sources: [], actions: ['listen']};
globalThis.fetch = async (url, options = {}) => {
  if (String(url).includes('/api/quick')) return new Response(JSON.stringify({categories: []}), {status: 200});
  const payload = JSON.parse(options.body); sent.push(payload);
  const number = sent.length;
  const events = [{event: 'session_started', data: {}},
    ...Array.from({length: 20}, (_, index) => ({event: 'token', data: {text: index === 0 ? `Yanıt ${number}` : ''}})),
    {event: 'final', data: {answer: `Yanıt ${number}`, answer_text: `Yanıt ${number}`,
      mode: 'answer', author: 'kural', citations: [], cards: number === 1 ? [finalCard] : []}}];
  const sse = events.map(item => `event: ${item.event}\ndata: ${JSON.stringify(item.data)}\n\n`).join('');
  return new Response(sse, {status: 200, headers: {'Content-Type': 'text/event-stream'}});
};
async function send(question) {
  input.value = question; form.dispatchEvent({type: 'submit', preventDefault() {}, bubbles: false});
  for (let index = 0; index < 30; index++) {
    await new Promise(resolve => setTimeout(resolve, 0));
    if (submit.getAttribute('aria-disabled') !== 'true') break;
  }
  if (submit.getAttribute('aria-disabled') === 'true') throw Error('reply did not finish');
}
"""


def run_chat(name: str, code: str) -> dict:
    imports = f"""
const {{ mountChat }} = await import({json.dumps((JS / 'chat.js').as_uri())});
const {{ HISTORY_TURNS }} = await import({json.dumps((JS / 'config.js').as_uri())});
const api = mountChat({{log, form, input, submit, status, getNeeds: () => [], onTurn: turn => turns.push(turn)}});
"""
    return run_node(name, CHAT_DOM, imports + code)


def test_scrolling_respects_reader_and_new_reply_focus() -> None:
    values = run_chat("scroll", """
window.scrollY = 0; window.dispatchEvent({type: 'scroll'});
await send('Eski mesajları okuyorum');
const firstAssistant = log.querySelector('.chat-msg.is-assistant');
const firstCount = scrollCalls.filter(call => call.node === firstAssistant).length;
const button = form.querySelector('#chat-new-reply');
const shown = !button.hidden;
button.dispatchEvent({type: 'click', bubbles: false});
const focused = document.activeElement === firstAssistant.querySelector('h3');
const clickedCount = scrollCalls.filter(call => call.node === document.activeElement).length;
window.scrollY = 1600; window.dispatchEvent({type: 'scroll'});
await send('Şimdi sondan okuyorum');
const assistants = log.querySelectorAll('.chat-msg.is-assistant');
const secondCount = scrollCalls.filter(call => call.node === assistants.at(-1)).length;
console.log(JSON.stringify({firstCount, shown, hiddenAfterClick: button.hidden, focused, clickedCount,
  secondCount, smooth: scrollCalls.some(call => call.options?.behavior === 'smooth')}));
""")
    assert values == {"firstCount": 0, "shown": True, "hiddenAfterClick": True, "focused": True,
                      "clickedCount": 1, "secondCount": 1, "smooth": False}


def test_new_chat_clears_history_and_previous_card() -> None:
    values = run_chat("fresh_chat", """
await send("Kadıköy'den Levent'e merdivensiz nasıl giderim?");
const prior = log.querySelector('.chat-card')?.dataset.cardId;
const priorIds = turns.map(turn => turn.message_id);
api.loadHistory([]);
const cleared = !log.querySelector('.chat-card');
await send('Hafta sonu etkinlik var mı?');
const second = sent[1];
console.log(JSON.stringify({prior, cleared, secondHistory: second.history,
  leaked: JSON.stringify(second).includes('Kadıköy') || JSON.stringify(second).includes('Levent'),
  cardAfter: !!log.querySelector('.chat-card'), priorIds,
  newIds: turns.slice(2).map(turn => turn.message_id)}));
""")
    assert values["prior"] == "card-a" and values["cleared"]
    assert values["secondHistory"] == [] and values["leaked"] is False and values["cardAfter"] is False
    assert len(set(values["priorIds"] + values["newIds"])) == 4


def test_invalid_version_in_final_cards_stays_inert_fallback() -> None:
    values = run_chat("invalid_final_card", """
finalCard.v = 2; finalCard.actions = ['listen'];
await send('Bir kart göster');
const card = log.querySelector('.chat-card');
console.log(JSON.stringify({fallback: !!card.querySelector('.chat-card-fallback'),
  actions: card.querySelectorAll('button').length}));
""")
    assert values == {"fallback": True, "actions": 0}


def test_thirty_restored_turns_show_all_three_cards_but_send_bounded_context() -> None:
    values = run_chat("restore", """
const restored = Array.from({length: 30}, (_, index) => ({role: index % 2 ? 'assistant' : 'user',
  content: `Tur ${index}`, message_id: `saved-${index}`}));
for (const index of [1, 9, 21]) restored[index].cards = [{v: 1, id: `saved-card-${index}`,
  type: 'info', status: 'ready', title: `Kart ${index}`, body: {text: 'Kayıtlı kart'}, sources: [],
  actions: ['listen', 'send', 'open_official']}];
api.loadHistory(restored);
const messages = log.querySelectorAll('.chat-msg:not(.is-notice)');
const cards = log.querySelectorAll('.chat-card');
const statuses = cards.map(card => card.dataset.cardStatus);
const actions = cards.map(card => card.querySelectorAll('button').map(button => button.dataset.cardAction));
await send('Yeni soru');
console.log(JSON.stringify({count: messages.length, first: messages[0].textContent, last: messages.at(-1).textContent,
  cards: cards.length, statuses, actions, context: sent[0].history.length, bound: HISTORY_TURNS * 2}));
""")
    assert values["count"] == 30
    assert "Tur 0" in values["first"] and "Tur 29" in values["last"]
    assert values["cards"] == 3 and values["statuses"] == ["ready"] * 3
    assert values["actions"] == [["listen"]] * 3
    assert values["context"] <= values["bound"]


def test_map_modal_returns_focus_scroll_and_assistant_view() -> None:
    from test_chat_cards_static import DOM as CARD_DOM

    values = run_node("map_shell", f"""
import * as cards from {json.dumps((JS / 'chat_cards.js').as_uri())};
import {json.dumps((JS / 'chat_card_map.js').as_uri())};
{CARD_DOM}
""", """
document.body.dataset.view = 'assistant';
const map = cards.appendCard(document.body, {v: 1, id: 'map-shell', type: 'map', status: 'ready',
  title: 'İki nokta', body: {points: [{lat: 41.01, lon: 29.02, label: 'Kadıköy'}]},
  sources: [], actions: ['expand_map']}, {messageId: 'message-1'});
observers.forEach(observer => observer.callback([{isIntersecting: true}]));
await Promise.resolve(); await Promise.resolve();
const trigger = map.querySelector('[data-card-action="expand_map"]');
trigger.dispatchEvent({type: 'click'});
const dialog = document.body.querySelector('dialog');
window.scrollY = 500;
dialog.querySelector('button').dispatchEvent({type: 'click'});
console.log(JSON.stringify({opened: !!dialog, closed: !document.body.querySelector('dialog'),
  focus: document.activeElement === trigger, y: window.scrollY, view: document.body.dataset.view}));
""")
    assert values == {"opened": True, "closed": True, "focus": True, "y": 137, "view": "assistant"}


def test_kolay_ekran_has_a_top_bar_slot_and_every_legacy_link_stays_in_markup() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    actions = html.split('<div class="topbar-actions">', 1)[1].split("</div>", 1)[0]
    assert 'id="legacy-topbar"' in actions
    for legacy in ("city", "travel", "map", "nearby", "data", "follow", "easy"):
        assert f'data-legacy="{legacy}"' in html
    code = (JS / "workspace_nav.js").read_text(encoding="utf-8")
    assert "getElementById('legacy-topbar')" in code
