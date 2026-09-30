"""Native workspace transitions preserve the live composer and deliberate keyboard submission."""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest
from conftest import REPO_ROOT

STATIC = REPO_ROOT / "src" / "nabiz" / "console" / "static"

# Only browser primitives are doubled. The real workspace module owns every transition below.
DOM = r"""
class Node {
  constructor(tag = 'div', id = '', classes = '') {
    this.tagName = tag; this.id = id; this.children = []; this.parentElement = null;
    this.attrs = {}; this.dataset = {}; this.listeners = {}; this.hidden = false; this.open = false;
    const names = new Set(classes.split(' ').filter(Boolean));
    this.classList = {contains: name => names.has(name), add: name => names.add(name),
      toggle(name, state) { if (state) names.add(name); else names.delete(name); }};
  }
  matches(selector) {
    if (selector.includes(',')) return selector.split(',').some(part => this.matches(part.trim()));
    const excluded = selector.match(/:not\(([^)]+)\)/);
    if (excluded && this.matches(excluded[1])) return false;
    selector = selector.replace(/:not\([^)]+\)/g, '');
    if (selector === ':disabled') return !!this.disabled;
    if (selector === '[hidden]') return this.hidden;
    if (selector === '[inert]') return !!this.inert;
    if (selector === '[aria-disabled="true"]') return this.attrs['aria-disabled'] === 'true';
    if (selector === 'a[href^="#"]') return this.tagName === 'a' && (this.attrs.href || '').startsWith('#');
    if (selector.startsWith('#')) return this.id === selector.slice(1);
    if (selector.startsWith('.')) return selector.slice(1).split('.').every(name => this.classList.contains(name));
    return this.tagName === selector;
  }
  closest(selector) { return this.matches(selector) ? this : this.parentElement?.closest(selector) || null; }
  contains(node) { return !!node && (node === this || this.children.some(child => child.contains(node))); }
  get isConnected() { return this === document || !!this.parentElement?.isConnected; }
  querySelectorAll(selector) {
    if (selector.includes(',')) return [...new Set(selector.split(',').flatMap(part => this.querySelectorAll(part.trim())))];
    const parts = selector.split(' '), leaf = parts.pop(), ancestor = parts.join(' ');
    return this.children.flatMap(child => [child, ...child.querySelectorAll('*')])
      .filter(child => leaf === '*' || child.matches(leaf) && (!ancestor || child.parentElement?.closest(ancestor)));
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  append(...nodes) { nodes.forEach(node => { node.remove(); node.parentElement = this; this.children.push(node); }); }
  appendChild(node) { this.append(node); return node; }
  prepend(node) { node.remove(); node.parentElement = this; this.children.unshift(node); }
  remove() {
    if (this.contains(globalThis.document?.activeElement)) document.activeElement = document.body;
    if (this.parentElement) this.parentElement.children.splice(this.parentElement.children.indexOf(this), 1);
    this.parentElement = null;
  }
  before(node) {
    node.remove(); node.parentElement = this.parentElement;
    this.parentElement.children.splice(this.parentElement.children.indexOf(this), 0, node);
  }
  after(node) {
    node.remove(); node.parentElement = this.parentElement;
    this.parentElement.children.splice(this.parentElement.children.indexOf(this) + 1, 0, node);
  }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  getAttribute(key) { return this.attrs[key] ?? null; }
  hasAttribute(key) { return key in this.attrs; }
  removeAttribute(key) { delete this.attrs[key]; }
  isVisible() {
    for (let node = this; node; node = node.parentElement) {
      if (node.hidden || node.tagName === 'details' && !node.open) return false;
    }
    return true;
  }
  focus(options) { if (this.isVisible()) { document.activeElement = this; this.focusOptions = options; } }
  scrollIntoView() { this.scrollVisible = this.isVisible(); }
  addEventListener(type, listener) { (this.listeners[type] ||= []).push(listener); }
  dispatchEvent(event) {
    event.target ||= this;
    (this.listeners[event.type] || []).forEach(listener => listener(event));
    if (event.bubbles !== false) this.parentElement?.dispatchEvent(event);
  }
}
function event(type, extras = {}) {
  return {type, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, ...extras};
}
function setup(hash = '') {
  const doc = new Node('document'), body = new Node('body'), main = new Node('main', 'main');
  doc.append(body); body.append(main); doc.body = body;
  doc.documentElement = {lang: 'tr'};
  doc.getElementById = id => doc.querySelector(`#${id}`);
  doc.createComment = () => new Node('comment');
  doc.createElement = tag => new Node(tag);
  globalThis.document = doc; globalThis.window = new Node('window');
  globalThis.location = new URL('https://nabiz.test/?mock=1&lang=en'); location.hash = hash;
  window.location = location;
  const history = [location.href];
  window.history = {
    pushState(_state, _title, reference) { location.href = new URL(reference, location.href).href; history.push(location.href); },
    back() {
      if (history.length > 1) history.pop(); location.href = history.at(-1);
      window.dispatchEvent(event('popstate')); window.dispatchEvent(event('hashchange'));
    },
    get length() { return history.length; },
  };
  globalThis.CustomEvent = function(type, options) { return event(type, {bubbles: false, ...options}); };
  const observers = [];
  globalThis.MutationObserver = class {
    constructor(callback) { this.callback = callback; }
    observe(target) { this.target = target; observers.push(this); }
  };
  const add = (parent, tag, id, classes = '') => { const node = new Node(tag, id, classes); parent.append(node); return node; };
  const hero = add(main, 'section', 'home-screen'), chat = add(main, 'section', 'asistan');
  const assistantHead = add(chat, 'div', '', 'assistant-head');
  add(assistantHead, 'aside', 'convo-root');
  const assistantMore = add(assistantHead, 'details', 'assistant-more');
  add(assistantMore, 'summary'); add(assistantMore, 'ul', 'legacy-more-links');
  add(main, 'section', 'takvim');
  const log = add(chat, 'ol', 'chat-log'), form = add(hero, 'form', 'chat-form');
  const input = add(form, 'textarea', 'chat-input'), submit = add(form, 'button', 'chat-submit');
  const bottom = add(form, 'div', '', 'composer-bottom');
  add(hero, 'div', 'quick-cards'); const more = add(hero, 'details', 'quick-more');
  add(more, 'div', 'quick-more-cards'); add(add(hero, 'details', 'composer-more'), 'summary');
  add(main, 'section', 'city-cards');
  const tools = add(main, 'div', '', 'workspace');
  const nested = {'journey-workspace': 'city-tools', 'open-data-workspace': 'acik-veri',
    'map-workspace': 'harita', 'explore-workspace': 'kultur'};
  for (const [id, child] of Object.entries(nested)) add(add(tools, 'details', id), 'section', child);
  const account = add(main, 'section', 'hesabim');
  ['profilim', 'takip', 'hafizam', 'hesap'].forEach(id => add(add(account, 'details', `details-${id}`), 'section', id));
  const footer = add(body, 'footer', 'about'), nav = add(body, 'nav', '', 'topbar-nav');
  const primary = add(nav, 'ul', '', 'nav-primary'), secondary = add(nav, 'div', '', 'nav-secondary');
  const legacy = add(secondary, 'ul', 'legacy-nav');
  add(body, 'ul', 'legacy-topbar');
  const links = ['asistan', 'takvim', 'hesabim'].map((id, index) => {
    const link = add(add(primary, 'li'), 'a'); link.setAttribute('href', `#${id}`);
    add(link, 'span');
    link.setAttribute('data-primary', ['assistant', 'calendar', 'account'][index]); return link;
  });
  ['city-cards', 'city-tools', 'map-workspace', 'explore-workspace', 'acik-veri', 'takip', '/kolay.html']
    .forEach((id, index) => { const link = add(add(legacy, 'li'), 'a');
      link.setAttribute('href', id.startsWith('/') ? id : `#${id}`);
      link.setAttribute('data-legacy', ['city', 'travel', 'map', 'nearby', 'data', 'follow', 'easy'][index]);
      add(link, 'svg', '', 'icon');
      links.push(link); });
  let submissions = 0;
  form.requestSubmit = () => { submissions++; form.dispatchEvent(event('submit')); };
  return {doc, body, main, hero, chat, log, form, input, submit, bottom, tools, footer, links,
    submissions: () => submissions, flush: () => observers.forEach(observer => observer.callback([]))};
}
const visible = s => ['home-screen', 'asistan', 'takvim', 'city-cards', 'journey-workspace', 'open-data-workspace',
  'map-workspace', 'explore-workspace', 'hesabim'].filter(id => !s.doc.getElementById(id).hidden);
"""


def run_workspace(tmp_path, body: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    module = json.dumps((STATIC / "js" / "workspace_nav.js").as_uri())
    home = json.dumps((STATIC / "js" / "home.js").as_uri())
    script = tmp_path / "workspace_harness.mjs"
    script.write_text(f"import * as workspace from {module};\nimport * as home from {home};\n{DOM}\n{body}\n", encoding="utf-8")
    result = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize(("target", "view", "expected"), [
    ("", "assistant", ["home-screen", "asistan"]),
    ("takvim", "calendar", ["takvim"]),
    ("city-cards", "city", ["city-cards"]),
    ("city-tools", "travel", ["journey-workspace"]),
    ("acik-veri", "data", ["open-data-workspace"]),
    ("harita", "map", ["map-workspace"]),
    ("kultur", "nearby", ["explore-workspace"]),
    ("profilim", "account", ["hesabim"]),
    ("about", "about", []),
])
def test_initial_hash_opens_only_its_workspace(tmp_path, target, view, expected) -> None:
    values = run_workspace(tmp_path, f"""
const s = setup({json.dumps('#' + target if target else '')}); workspace.mountWorkspace(s);
console.log(JSON.stringify({{view: s.body.dataset.view, visible: visible(s), footer: !s.footer.hidden,
  tools: !s.tools.hidden, open: s.tools.children.filter(node => !node.hidden).every(node => node.open)}}));
""")
    assert values == {
        "view": view, "visible": expected, "footer": view == "about",
        "tools": view in {"travel", "data", "map", "nearby"}, "open": True,
    }


def test_links_hashes_and_programmatic_map_actions_reveal_their_destinations(tmp_path) -> None:
    values = run_workspace(tmp_path, """
const s = setup(); workspace.mountWorkspace(s);
const visit = () => ({view: s.body.dataset.view, visible: visible(s)});
s.doc.dispatchEvent(event('click', {target: s.links[4]})); const travel = visit();
location.hash = '#acik-veri'; window.dispatchEvent(event('hashchange')); const data = visit();
s.doc.dispatchEvent(event('nabiz:show-on-map')); const map = visit();
s.doc.dispatchEvent(event('nabiz:reveal', {detail: {id: 'hafizam'}})); const account = visit();
location.hash = ''; window.dispatchEvent(event('hashchange')); const assistant = visit();
console.log(JSON.stringify({travel, data, map, account, home: assistant}));
""")
    assert values == {
        "travel": {"view": "travel", "visible": ["journey-workspace"]},
        "data": {"view": "data", "visible": ["open-data-workspace"]},
        "map": {"view": "map", "visible": ["map-workspace"]},
        "account": {"view": "account", "visible": ["hesabim"]},
        "home": {"view": "assistant", "visible": ["home-screen", "asistan"]},
    }


def test_map_moves_after_calendar_once_and_keeps_its_icon_language_and_focus(tmp_path) -> None:
    values = run_workspace(tmp_path, """
const s = setup(), map = s.links.find(link => link.getAttribute('data-legacy') === 'map');
const icon = map.querySelector('svg'); workspace.mountWorkspace(s);
const primary = s.doc.querySelector('.nav-primary');
const turkish = map.querySelector('span').textContent;
map.focus(); workspace.applyLegacyPlacement(); workspace.applyLegacyPlacement();
const focused = s.doc.activeElement === map;
window.dispatchEvent(event('nabiz:lang', {detail: {lang: 'en'}}));
const english = map.querySelector('span').textContent;
window.dispatchEvent(event('nabiz:lang', {detail: {lang: 'tr'}}));
console.log(JSON.stringify({order: primary.querySelectorAll('a').map(link => link.getAttribute('data-primary')),
  count: s.doc.querySelectorAll('a').filter(link => link.getAttribute('data-legacy') === 'map').length,
  same: primary.querySelectorAll('a')[2] === map, icon: map.querySelector('svg') === icon,
  key: map.querySelector('span').getAttribute('data-i18n'), focused, turkish, english,
  restored: map.querySelector('span').textContent,
  more: s.doc.getElementById('legacy-more-links').querySelectorAll('a').map(link => link.getAttribute('data-legacy'))}));
""")
    assert values == {"order": ["assistant", "calendar", "map", "account"], "count": 1, "same": True, "icon": True,
                      "key": "design.nav_map", "focused": True, "turkish": "Harita", "english": "Map",
                      "restored": "Harita", "more": ["city", "travel", "nearby"]}


def test_map_click_hash_and_show_on_map_select_only_the_map_primary_link(tmp_path) -> None:
    values = run_workspace(tmp_path, """
const s = setup(); workspace.mountWorkspace(s);
const map = s.links.find(link => link.getAttribute('data-legacy') === 'map');
const selected = () => s.links.filter(link => link.hasAttribute('aria-current')).map(link =>
  [link.getAttribute('data-primary'), link.getAttribute('aria-current')]);
map.dispatchEvent(event('click'));
const click = {view: s.body.dataset.view, current: selected(), focus: s.doc.activeElement?.id,
  visible: s.doc.activeElement?.isVisible(), focusOptions: s.doc.activeElement?.focusOptions};
s.links[1].dispatchEvent(event('click')); const calendar = selected();
location.hash = '#map-workspace'; window.dispatchEvent(event('hashchange')); const hash = selected();
s.links[0].dispatchEvent(event('click'));
s.doc.dispatchEvent(event('nabiz:show-on-map')); const action = {view: s.body.dataset.view, current: selected()};
console.log(JSON.stringify({click, calendar, hash, action}));
""")
    assert values == {"click": {"view": "map", "current": [["map", "page"]], "focus": "map-workspace",
                               "visible": True, "focusOptions": {"preventScroll": True}},
                      "calendar": [["calendar", "page"]], "hash": [["map", "page"]],
                      "action": {"view": "map", "current": [["map", "page"]]}}


@pytest.mark.parametrize("citizen", [True, False])
def test_everyday_examples_submit_visible_questions_once_across_language_rerenders(tmp_path, citizen) -> None:
    values = run_workspace(tmp_path, f"""
const {{ setCatalogs }} = await import({json.dumps((STATIC / 'js' / 'i18n_text.js').as_uri())});
const matches = Node.prototype.matches;
Node.prototype.matches = function(selector) {{
  return selector === 'button[data-example]' ? this.tagName === 'button' && Boolean(this.dataset.example)
    : matches.call(this, selector);
}};
Node.prototype.replaceChildren = function(...nodes) {{
  [...this.children].forEach(node => node.remove()); this.append(...nodes);
}};
Object.defineProperty(Node.prototype, 'innerHTML', {{
  get() {{ return this._html || ''; }},
  set(value) {{
    this._html = value; this.replaceChildren();
    const href = value.match(/<use href="([^"]+)"/);
    if (href) {{ const svg = new Node('svg'), use = new Node('use');
      use.setAttribute('href', href[1]); svg.append(use); this.append(svg); }}
  }},
}});
const s = setup(), list = new Node('ul', 'capability-examples'); s.hero.append(list);
const subtitle = new Node('p', 'home-sub'); subtitle.textContent = 'Original subtitle'; s.hero.append(subtitle);
if ({json.dumps(citizen)}) s.body.classList.add('citizen-page');
s.input.setAttribute('placeholder', 'Original placeholder');
const asked = []; s.form.requestSubmit = () => asked.push(s.input.value);
home.mountHome(s); workspace.mountEverydayExamples(s.form, s.input); workspace.mountEverydayExamples(s.form, s.input);
const snapshot = () => list.querySelectorAll('button').map(button => ({{
  label: button.querySelector('span').textContent, question: button.dataset.question || null,
  icon: button.querySelector('use').getAttribute('href'), id: button.dataset.example,
}}));
const tr = snapshot(), trPlaceholder = s.input.getAttribute('placeholder'), trSubtitle = subtitle.textContent;
list.querySelectorAll('button').forEach(button => button.querySelector('span').dispatchEvent(event('click')));
s.doc.documentElement.lang = 'en';
setCatalogs('en', Object.fromEntries(home.EXAMPLES.map(item => [`ui.shell.${{item.id}}`, item.en])), {{}});
window.dispatchEvent(event('nabiz:lang', {{detail: {{lang: 'en'}}}}));
const en = snapshot(), enPlaceholder = s.input.getAttribute('placeholder'), enSubtitle = subtitle.textContent;
list.querySelectorAll('button').forEach(button => button.dispatchEvent(event('click')));
s.doc.documentElement.lang = 'tr'; setCatalogs('tr', {{}}, {{}});
window.dispatchEvent(event('nabiz:lang', {{detail: {{lang: 'tr'}}}}));
list.querySelectorAll('button')[0].dispatchEvent(event('click'));
console.log(JSON.stringify({{tr, en, asked, trPlaceholder, enPlaceholder, trSubtitle, enSubtitle,
  originals: home.EXAMPLES.map(item => ({{tr: item.tr, en: item.en, icon: item.icon}}))}}));
""")
    tr = ["Kadıköy’den Levent’e en hızlı nasıl giderim?", "Taksim’e metroyla nasıl giderim?",
          "Beşiktaş’a sadece otobüsle nasıl giderim?", "Bu hafta sonu ücretsiz ne yapabilirim?"]
    en = ["What is the fastest way from Kadıköy to Levent?", "How can I get to Taksim by metro?",
          "How can I get to Beşiktaş using only buses?", "What can I do for free this weekend?"]
    icons = ["map", "train", "bus", "external-link"]
    if not citizen:
        tr = [item["tr"] for item in values["originals"]]
        en = [item["en"] for item in values["originals"]]
        icons = [item["icon"] for item in values["originals"]]
    for language, labels in (("tr", tr), ("en", en)):
        assert values[language] == [
            {"label": label, "question": label if citizen else None, "icon": f"/icons.svg#i-{icons[index]}",
             "id": f"{'everyday' if citizen else 'example'}_{index + 1}"} for index, label in enumerate(labels)
        ]
    assert values["asked"] == tr + en + tr[:1]
    assert values["trPlaceholder"] == ("İstanbul hakkında bir şey sorun…" if citizen else "Original placeholder")
    assert values["enPlaceholder"] == ("Ask something about Istanbul…" if citizen else "Original placeholder")
    assert values["trSubtitle"] == ("Ulaşım, etkinlikler ve şehir hizmetleri için sorun." if citizen else "Original subtitle")
    assert values["enSubtitle"] == ("Ask about transport, events and city services." if citizen else "Original subtitle")


def test_composer_moves_as_one_live_form_and_preserves_draft_selection_and_listeners(tmp_path) -> None:
    values = run_workspace(tmp_path, """
const s = setup(), identity = s.form; let listenerCalls = 0;
s.input.value = 'Kartal\\nLevent'; s.input.selectionStart = 3; s.input.selectionEnd = 6;
s.form.addEventListener('submit', () => {
  listenerCalls++; if (listenerCalls === 1) s.log.append(new Node('li', '', 'chat-msg is-user'));
}); workspace.mountWorkspace(s);
s.input.focus(); s.input.dispatchEvent(event('keydown', {key: 'Enter'})); s.flush();
const moved = s.form.parentElement === s.chat && s.chat.children.at(-1) === identity;
const focusPreserved = s.doc.activeElement === s.input, focusOptions = s.input.focusOptions;
s.doc.getElementById('assistant-more').open = true;
s.doc.dispatchEvent(event('click', {target: s.links[3]})); s.links[3].focus();
s.log.append(new Node('li', '', 'chat-msg is-assistant')); s.flush();
const cityAfterStream = s.body.dataset.view;
const cityDestinationFocused = s.doc.activeElement === s.doc.getElementById('city-cards');
s.form.requestSubmit();
console.log(JSON.stringify({moved, focusPreserved, focusOptions, cityAfterStream, cityDestinationFocused,
  same: s.form === identity,
  draft: s.input.value, selection: [s.input.selectionStart, s.input.selectionEnd], listenerCalls,
  view: s.body.dataset.view, buttonMoved: s.submit.parentElement === s.bottom}));
""")
    assert values == {
        "moved": True, "focusPreserved": True, "focusOptions": {"preventScroll": True},
        "cityAfterStream": "city", "cityDestinationFocused": True, "same": True, "draft": "Kartal\nLevent",
        "selection": [3, 6], "listenerCalls": 2, "view": "assistant", "buttonMoved": True,
    }


def test_new_conversation_returns_composer_home_even_when_ai_notice_remains(tmp_path) -> None:
    values = run_workspace(tmp_path, """
const s = setup(); workspace.mountWorkspace(s);
const notice = new Node('li', '', 'chat-msg is-notice'), question = new Node('li', '', 'chat-msg is-user');
s.log.append(notice, question); s.flush(); s.input.focus(); question.remove(); s.flush();
console.log(JSON.stringify({atHome: s.form.parentElement === s.hero,
  active: s.body.classList.contains('has-conversation'), noticePreserved: notice.parentElement === s.log,
  focusPreserved: s.doc.activeElement === s.input}));
""")
    assert values == {"atHome": True, "active": False, "noticePreserved": True, "focusPreserved": True}


@pytest.mark.parametrize("during_move", ["disabled", "detached", "different-focus", "outside-form"])
def test_composer_move_does_not_restore_ineligible_or_unrelated_focus(tmp_path, during_move) -> None:
    values = run_workspace(tmp_path, f"""
const s = setup(), scenario = {json.dumps(during_move)}; workspace.mountWorkspace(s);
const append = s.chat.append.bind(s.chat);
s.chat.append = (...nodes) => {{
  append(...nodes);
  if (scenario === 'disabled') s.input.disabled = true;
  if (scenario === 'detached') s.input.remove();
  if (scenario === 'different-focus') s.links[3].focus();
}};
s.doc.getElementById('assistant-more').open = true;
if (scenario === 'outside-form') s.links[3].focus(); else s.input.focus();
s.log.append(new Node('li', '', 'chat-msg is-user')); s.flush();
console.log(JSON.stringify({{inputFocused: s.doc.activeElement === s.input,
  expectedFocused: s.doc.activeElement === (scenario.includes('focus') || scenario === 'outside-form' ? s.links[3] : s.body),
  restored: !!s.input.focusOptions?.preventScroll}}));
""")
    assert values == {"inputFocused": False, "expectedFocused": True, "restored": False}


def test_unsubscribe_hash_opens_follow_confirmation_without_changing_token(tmp_path) -> None:
    values = run_workspace(tmp_path, """
const hash = '#takibi-birak=fixture.token.123', s = setup(hash); home.mountHome(s);
console.log(JSON.stringify({view: s.body.dataset.view, hash: location.hash,
  visible: s.doc.getElementById('takip').isVisible(), resolved: home.openTargetDetails(),
  current: s.links.filter(link => link.hasAttribute('aria-current')).map(link => link.getAttribute('href'))}));
""")
    assert values == {
        "view": "account", "hash": "#takibi-birak=fixture.token.123", "visible": True,
        "resolved": True, "current": ["#hesabim"],
    }


@pytest.mark.parametrize("target", ["profilim", "takip", "hafizam"])
def test_account_navigation_announces_only_the_selected_link(tmp_path, target) -> None:
    values = run_workspace(tmp_path, f"""
const s = setup(); workspace.mountWorkspace(s);
workspace.revealTarget({json.dumps(target)});
console.log(JSON.stringify(s.links.filter(link => link.hasAttribute('aria-current')).map(link => link.getAttribute('href'))));
""")
    assert values == ["#hesabim"]


@pytest.mark.parametrize("has_conversation", [False, True])
def test_assistant_navigation_reveals_before_focus_and_scroll(tmp_path, has_conversation) -> None:
    values = run_workspace(tmp_path, f"""
const s = setup(); home.mountHome(s);
if ({json.dumps(has_conversation)}) {{ s.log.append(new Node('li', '', 'chat-msg is-user')); s.flush(); }}
workspace.revealTarget('harita');
s.links[0].dispatchEvent(event('click'));
console.log(JSON.stringify({{view: s.body.dataset.view, focused: s.doc.activeElement === s.input,
  scrollVisible: s.input.scrollVisible, parent: s.form.parentElement.id}}));
""")
    assert values == {
        "view": "assistant", "focused": True, "scrollVisible": True,
        "parent": "asistan" if has_conversation else "home-screen",
    }


def test_persona_and_voice_targets_open_all_ancestors_without_granting_consent(tmp_path) -> None:
    values = run_workspace(tmp_path, """
const s = setup(); workspace.mountWorkspace(s);
const disclosure = new Node('details', 'appearance-options'), picker = new Node('section', 'persona-picker');
s.doc.getElementById('hesabim').append(disclosure); disclosure.append(picker);
workspace.revealTarget('persona-picker'); const pickerVisible = picker.isVisible();
const voice = new Node('details', '', 'composer-voice'), optin = new Node('button', 'voice-optin');
let consents = 0; optin.addEventListener('click', () => consents++); voice.append(optin); s.form.append(voice);
workspace.revealTarget('voice-optin', {focus: true, block: 'center'});
console.log(JSON.stringify({pickerVisible, voiceVisible: optin.isVisible(), focused: s.doc.activeElement === optin,
  scrollVisible: optin.scrollVisible, view: s.body.dataset.view, consents}));
""")
    assert values == {
        "pickerVisible": True, "voiceVisible": True, "focused": True, "scrollVisible": True,
        "view": "assistant", "consents": 0,
    }
    personas = (STATIC / "js" / "personas.js").read_text(encoding="utf-8")
    assert "revealTarget('persona-picker')" in personas
    assert "revealTarget('voice-optin', { focus: true, block: 'center' })" in personas


def test_assistant_url_preserves_query_focus_and_back_destination(tmp_path) -> None:
    values = run_workspace(tmp_path, """
const s = setup('#map-workspace'); home.mountHome(s);
s.links[0].dispatchEvent(event('click'));
const href = location.href, focused = s.doc.activeElement === s.input;
s.links[0].dispatchEvent(event('click')); const entries = window.history.length;
window.history.back();
const back = {view: s.body.dataset.view, hash: location.hash, search: location.search};
const reloaded = setup(new URL(href).hash); home.mountHome(reloaded);
console.log(JSON.stringify({href, focused, entries, back, reloadView: reloaded.body.dataset.view}));
""")
    assert values == {
        "href": "https://nabiz.test/?mock=1&lang=en#asistan", "focused": True, "entries": 2,
        "back": {"view": "map", "hash": "#map-workspace", "search": "?mock=1&lang=en"},
        "reloadView": "assistant",
    }


@pytest.mark.parametrize(("key", "field", "button", "expected_submits", "expected_prevented"), [
    ({"key": "Enter"}, {}, {}, 1, True),
    ({"key": "Enter", "shiftKey": True}, {}, {}, 0, False),
    ({"key": "Enter", "isComposing": True}, {}, {}, 0, False),
    ({"key": "Enter", "keyCode": 229}, {}, {}, 0, False),
    ({"key": "Enter", "defaultPrevented": True}, {}, {}, 0, True),
    ({"key": "Escape"}, {}, {}, 0, False),
    ({"key": "Enter"}, {"readOnly": True}, {}, 0, True),
    ({"key": "Enter"}, {"disabled": True}, {}, 0, True),
    ({"key": "Enter"}, {}, {"aria-disabled": "true"}, 0, True),
])
def test_keyboard_submission_respects_composition_newlines_and_busy_state(
    tmp_path, key, field, button, expected_submits, expected_prevented,
) -> None:
    values = run_workspace(tmp_path, f"""
const s = setup(); workspace.mountWorkspace(s); Object.assign(s.input, {json.dumps(field)});
Object.entries({json.dumps(button)}).forEach(([key, value]) => s.submit.setAttribute(key, value));
const key = event('keydown', {json.dumps(key)}); s.input.dispatchEvent(key);
console.log(JSON.stringify({{submits: s.submissions(), prevented: key.defaultPrevented}}));
""")
    assert values == {"submits": expected_submits, "prevented": expected_prevented}


# P00 D2a placement plus the owner's Map promotion: four runtime primary entries, with Map after Calendar.
# The other city tools remain under More. Every old address still opens its destination.
OWNER_PLACEMENT = {
    "city": ("#city-cards", "more"), "travel": ("#city-tools", "more"), "map": ("#map-workspace", "nav"),
    "nearby": ("#explore-workspace", "more"), "data": ("#acik-veri", "operator"), "follow": ("#takip", "account"),
    "easy": ("/kolay.html", "topbar"),
}


def test_the_seven_placement_lines_are_the_owners_and_run_at_load() -> None:
    source = (STATIC / "js" / "workspace_nav.js").read_text(encoding="utf-8")
    table = source[source.index("export const LEGACY_PLACEMENT = ["):source.index("];", source.index("LEGACY_PLACEMENT"))]
    rows = re.findall(r"\{ id: '(\w+)', href: '([^']+)', i18n: '[^']+', placement: '(\w+)' \}", table)
    assert table.count("placement:") == 7
    assert {name: (href, placement) for name, href, placement in rows} == OWNER_PLACEMENT
    mount = source[source.index("export function mountWorkspace("):]
    assert mount.index("applyLegacyPlacement();") < mount.index("form.before(placeholder);")
    home = (STATIC / "js" / "home.js").read_text(encoding="utf-8")
    assert "mountWorkspace({ form, input });" in home


def test_every_placed_address_exists_on_the_page() -> None:
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    for address in [href for href, _ in OWNER_PLACEMENT.values()] + ["#profilim", "#hafizam"]:
        if address.startswith("#"):
            assert page.count(f'id="{address[1:]}"') == 1, address
        else:
            assert (STATIC / address.lstrip("/")).is_file(), address
    account = page[page.index('id="hesabim"'):]
    assert all(f'id="{anchor}"' in account for anchor in ("profilim", "takip", "hafizam"))


def test_owner_placement_hides_moved_rows_and_keeps_every_destination(tmp_path) -> None:
    values = run_workspace(tmp_path, """
const s = setup(); workspace.mountWorkspace(s);
const rows = Object.fromEntries(s.links.filter(link => link.getAttribute('data-legacy')).map(link => [
  link.getAttribute('data-legacy'), {parent: link.parentElement.parentElement.id, hidden: link.parentElement.hidden,
    moved: link.getAttribute('data-moved-to')}]));
const reach = {};
for (const hash of ['#city-cards', '#city-tools', '#map-workspace', '#explore-workspace', '#acik-veri', '#takip',
  '#profilim', '#hafizam']) {
  location.hash = hash; window.dispatchEvent(event('hashchange')); reach[hash] = s.body.dataset.view;
}
console.log(JSON.stringify({rows, reach}));
""")
    assert values["rows"] == {
        "city": {"parent": "legacy-more-links", "hidden": False, "moved": None},
        "travel": {"parent": "legacy-more-links", "hidden": False, "moved": None},
        "map": {"parent": "", "hidden": False, "moved": None},
        "nearby": {"parent": "legacy-more-links", "hidden": False, "moved": None},
        "data": {"parent": "legacy-nav", "hidden": True, "moved": "console"},
        "follow": {"parent": "legacy-nav", "hidden": True, "moved": None},
        "easy": {"parent": "legacy-topbar", "hidden": False, "moved": None},
    }
    assert values["reach"] == {
        "#city-cards": "city", "#city-tools": "travel", "#map-workspace": "map", "#explore-workspace": "nearby",
        "#acik-veri": "data", "#takip": "account", "#profilim": "account", "#hafizam": "account",
    }
