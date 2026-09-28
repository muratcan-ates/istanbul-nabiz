"""P26 entries describe real events, honor preferences and leave restored text still."""

from __future__ import annotations

import json
import re

import pytest
from conftest import REPO_ROOT
from test_sohbet_kabugu import CHAT_DOM, run_node
from test_workspace_navigation import run_workspace

STATIC = REPO_ROOT / "src/nabiz/console/static"
CATALOG = {
    "tr": {"ui.identity.name": "Şehir Asistanı"},
    "en": {"ui.identity.name": "City Assistant"},
}


def declarations(css: str):
    stack, part = [], ""
    for token in re.split(r"([{};])", re.sub(r"/\*.*?\*/", "", css, flags=re.S)):
        if token == "{":
            stack.append(part.strip())
            part = ""
        elif token == "}":
            if part.strip():
                yield tuple(stack), part.strip()
            stack.pop()
            part = ""
        elif token == ";":
            yield tuple(stack), part.strip()
            part = ""
        else:
            part += token
    assert not stack


@pytest.mark.parametrize("name", ["citizen.css", "workspace.css"])
def test_all_citizen_motion_has_system_root_and_surface_guards(name: str) -> None:
    css = (STATIC / "css" / name).read_text()
    found = 0
    for stack, declaration in declarations(css):
        if not re.match(r"(?:animation|transition)(?:-[\w-]+)?\s*:", declaration):
            continue
        found += 1
        assert any("(prefers-reduced-motion: no-preference)" in rule for rule in stack)
        for selector in re.split(r",(?![^()]*\))", stack[-1]):
            assert '.citizen-page' in selector
            assert ':not([data-motion="reduce"]):not([data-simple="on"])' in selector
        if declaration.startswith("transition:"):
            assert re.fullmatch(r"transition:\s*(?:opacity|transform)\s+[^,]+", declaration)
    assert found > 0


@pytest.mark.parametrize(("event", "selector", "animation"), [
    ("A11", "[data-enter]", "nd-view-in"),
    ("A12", ".nav-primary a::after", "transition: transform"),
    ("A16", ".chip-example", "transition: transform"),
    ("A25", ".citizen-page.has-conversation #chat-form", "nd-dock"),
    ("A30", ".chat-final[data-answer-enter]", "nd-rise"),
    ("A41", ".chat-card[data-card-enter]", "nd-rise"),
    ("A42", ".chat-card-consent", "nd-rise"),
    ("A47", ".more[open] > :not(summary)", "nd-disclose"),
])
def test_every_required_event_uses_the_motion_dictionary(event, selector, animation) -> None:
    css = (STATIC / "css/workspace.css").read_text()
    rules = [(stack[-1], value) for stack, value in declarations(css) if stack]
    assert any(selector in rule and animation in value for rule, value in rules), event


def test_keyframes_change_only_compositor_properties_and_sources_stay_still() -> None:
    for name in ("citizen.css", "workspace.css"):
        for stack, value in declarations((STATIC / "css" / name).read_text()):
            if any(rule.startswith("@keyframes") for rule in stack):
                assert value.split(":", 1)[0] in {"opacity", "transform"}
    css = (STATIC / "css/workspace.css").read_text()
    assert "@supports (animation-timeline: scroll())" in css
    assert "animation-range: 0 96px" in css
    assert "animation-delay: calc(var(--i, 0) * 40ms)" in css
    assert not re.search(r"animation:\s*[^;]*\binfinite\b", css)
    for stack, value in declarations(css):
        if value.startswith(("animation:", "transition:")):
            assert not any(part in stack[-1] for part in (".citation-card", ".ac-quote", ".chat-card-body"))
    assert "animation:" not in (STATIC / "css/answer_card.css").read_text()
    assert "transition:" not in (STATIC / "css/answer_card.css").read_text()


def test_workspace_entries_clean_up_and_repeat_navigation_does_not_restart(tmp_path) -> None:
    values = run_workspace(tmp_path, """
const s = setup(); workspace.mountWorkspace(s);
const calendar = s.doc.getElementById('takvim');
s.doc.dispatchEvent(event('nabiz:reveal', {detail: {id: 'takvim'}}));
const entered = calendar.hasAttribute('data-enter');
calendar.dispatchEvent(event('animationend', {target: new Node('span'), bubbles: false}));
const childIgnored = calendar.hasAttribute('data-enter');
calendar.dispatchEvent(event('animationend', {bubbles: false}));
const ended = !calendar.hasAttribute('data-enter');
s.doc.dispatchEvent(event('nabiz:reveal', {detail: {id: 'takvim'}}));
const sameStill = !calendar.hasAttribute('data-enter');
s.doc.dispatchEvent(event('nabiz:reveal', {detail: {id: 'asistan'}}));
s.doc.dispatchEvent(event('nabiz:reveal', {detail: {id: 'takvim'}}));
await new Promise(resolve => setTimeout(resolve, 450));
console.log(JSON.stringify({entered, childIgnored, ended, sameStill,
  fallback: !calendar.hasAttribute('data-enter'),
  current: s.links.filter(link => link.hasAttribute('aria-current')).map(link => link.getAttribute('aria-current'))}));
""")
    assert values == {"entered": True, "childIgnored": True, "ended": True, "sameStill": True,
                      "fallback": True, "current": ["page"]}


def test_transcript_restoration_signature_live_entries_and_capped_stagger() -> None:
    module = json.dumps((STATIC / "js/transcript.js").as_uri())
    values = run_node("transcript entries", CHAT_DOM, f"""
const {{ mountTranscript }} = await import({module});
const removeAttribute = Node.prototype.removeAttribute;
Node.prototype.removeAttribute = function(name) {{
  removeAttribute.call(this, name);
  if (name.startsWith('data-')) delete this.dataset[name.slice(5).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase())];
}};
const mutations = [];
globalThis.MutationObserver = class {{ constructor(callback) {{ mutations.push(callback); }} observe() {{}} }};
const appendMessage = (role, busy = false) => {{
  const shell = add(log, 'li', '', `chat-msg is-${{role}}`);
  add(shell, 'p', '', 'chat-who').textContent = role === 'assistant' ? 'Asistan' : 'Siz';
  if (busy) shell.setAttribute('aria-busy', 'true');
  return shell;
}};
for (let i = 0; i < 30; i++) appendMessage(i % 2 ? 'assistant' : 'user');
mountTranscript(log, document); mountTranscript(log, document);
const restoredStill = !log.querySelector('[data-message-enter]') && !log.querySelector('[data-answer-enter]');
const signatureCount = log.querySelectorAll('.assistant-signature').length;
const user = appendMessage('user'), assistant = appendMessage('assistant', true);
const final = add(assistant, 'div', '', 'chat-final');
const cards = Array.from({{length: 4}}, () => add(final, 'article', '', 'chat-card'));
mutations.forEach(fn => fn());
const userEntered = user.getAttribute('data-message-enter') !== null;
document.dispatchEvent(new CustomEvent('nabiz:chat-final', {{detail: {{host: final, final: {{}}}}}}));
const answerEntered = final.getAttribute('data-answer-enter') !== null;
const stagger = cards.map(card => card.style.values['--i']);
const enteredCards = cards.filter(card => card.getAttribute('data-card-enter') !== null).length;
const emergency = add(assistant, 'div', '', 'chat-final');
document.dispatchEvent(new CustomEvent('nabiz:chat-final', {{detail: {{host: emergency, final: {{emergency: true}}}}}}));
const emergencyStill = emergency.getAttribute('data-answer-enter') === null;
html.lang = 'en'; window.dispatchEvent(new CustomEvent('nabiz:lang', {{detail: {{lang: 'en'}}}}));
const english = log.querySelector('.assistant-signature').textContent;
await new Promise(resolve => setTimeout(resolve, 450));
const cleared = !log.querySelector('[data-message-enter]') && !log.querySelector('[data-answer-enter]')
  && !log.querySelector('[data-card-enter]');
log.replaceChildren(); const next = appendMessage('assistant'); mutations.forEach(fn => fn());
console.log(JSON.stringify({{restoredStill, signatureCount, mounted: mutations.length, userEntered, answerEntered,
  stagger, enteredCards, emergencyStill, english, cleared,
  resetSignature: !!next.querySelector('.assistant-signature')}}));
""")
    assert values == {"restoredStill": True, "signatureCount": 1, "mounted": 1, "userEntered": True,
                      "answerEntered": True, "stagger": ["0", "1", "2", "2"], "enteredCards": 4,
                      "emergencyStill": True, "english": "City Assistant", "cleared": True,
                      "resetSignature": True}


def test_layout_readability_material_and_root_scroll_contracts() -> None:
    citizen = (STATIC / "css/citizen.css").read_text()
    workspace = (STATIC / "css/workspace.css").read_text()
    assert '.chat-text:empty::before' not in citizen.replace('.chat-msg[aria-busy="true"] > .chat-text:empty::before', '')
    assert ':root:lang(en)' in citizen and 'Writing the answer' in citizen
    assert ':root[data-motion="reduce"]:has(.citizen-page)' in citizen
    assert ':root[data-simple="on"]:has(.citizen-page)' in citizen
    assert ':root:has(.citizen-page.has-conversation)' in workspace
    assert 'box-shadow: 0 0 0 2px var(--focus-ring)' in workspace
    assert 'border-radius: var(--nd-radius-composer)' in workspace
    assert '.citizen-page:not(.has-conversation) .composer.glass' in workspace
    assert 'prefers-color-scheme: dark' in workspace
    assert 'border-end-end-radius: var(--space-1)' in workspace
    assert CATALOG['tr'].keys() == CATALOG['en'].keys()


def test_composer_measurement_updates_scroll_reserve_when_chips_or_voice_grow(tmp_path) -> None:
    values = run_workspace(tmp_path, """
const observed = [], heights = [], s = setup();
s.doc.documentElement.style = {setProperty: (name, value) => heights.push([name, value])};
globalThis.ResizeObserver = class {
  constructor(callback) { this.callback = callback; }
  observe(target) { observed.push(target.id); this.callback([{borderBoxSize: [{blockSize: 210}]}]);
    this.callback([{borderBoxSize: [{blockSize: 326.5}]}]); }
};
workspace.mountWorkspace(s);
console.log(JSON.stringify({observed, heights}));
""")
    assert values == {"observed": ["chat-form"],
                      "heights": [["--chat-composer-height", "210px"], ["--chat-composer-height", "327px"]]}


def test_primary_heading_focus_and_city_return_preserve_native_summary(tmp_path) -> None:
    values = run_workspace(tmp_path, """
const s = setup();
s.doc.getElementById('takvim').append(new Node('h2', 'takvim-title'));
s.doc.getElementById('hesabim').append(new Node('h2', 'you-title'));
const map = s.doc.getElementById('map-workspace'), summary = new Node('summary'); map.prepend(summary);
workspace.mountWorkspace(s);
s.links[1].dispatchEvent(event('click')); const calendarFocus = s.doc.activeElement.id;
s.links[2].dispatchEvent(event('click')); const accountFocus = s.doc.activeElement.id;
workspace.revealTarget('harita'); workspace.revealTarget('harita');
const back = map.querySelector('.workspace-back');
s.doc.documentElement.lang = 'en'; window.dispatchEvent(event('nabiz:lang', {detail: {lang: 'en'}}));
const label = back.textContent, count = map.querySelectorAll('.workspace-back').length;
back.dispatchEvent(event('click'));
console.log(JSON.stringify({calendarFocus, accountFocus, label, count,
  summaryFirst: map.children[0] === summary, view: s.body.dataset.view}));
""")
    assert values == {"calendarFocus": "takvim-title", "accountFocus": "you-title",
                      "label": "Assistant", "count": 1, "summaryFirst": True, "view": "assistant"}
