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
    assert values == {"observed": ["chat-form", "chat-log"],
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


MEMORY_DISCLOSURE_DOM = r"""
const s = setup(), changes = [], languageListeners = [];
Node.prototype.before = function(node) {
  node.remove(); const parent = this.parentElement, index = parent.children.indexOf(this);
  parent.children.splice(index, 0, node); node.parentElement = parent;
};
s.doc.defaultView.CustomEvent = class { constructor(type, init) { this.type = type; this.detail = init.detail; } };
globalThis.MutationObserver = class { constructor(callback) { changes.push(callback); } observe() {} };
window.addEventListener = (name, callback) => { if (name === 'nabiz:lang') languageListeners.push(callback); };
const log = s.doc.createElement('ol'); s.doc.append(log);
const sync = () => changes.forEach(callback => callback());
const payload = (id = 'memory-1') => ({id, message_id:'m1', conversation_id:'c1', type:'memory',
  status:'awaiting_confirmation', title:'Hatırlayayım mı?', sensitive:false,
  body:{items:[{kind:'interest',key:'museum',label:'Müzeler'}]},
  actions:[{id:'remember_here'},{id:'remember_always'},{id:'change'}]});
const wrapOuter = root => { const outer = s.doc.createElement('article'); outer.className = 'chat-card';
  outer.dataset.cardType = 'memory'; const heading = s.doc.createElement('h4'); heading.textContent = 'Hatırlayayım mı?';
  const state = s.doc.createElement('span'); state.className = 'chat-card-status'; state.textContent = 'Onayınızı bekliyor';
  outer.append(heading, state, root); log.append(outer); return outer; };
"""


def test_memory_disclosure_preserves_real_controls_and_requires_explicit_remember(tmp_path):
    from test_memory_ui_static import run_ui

    values = run_ui(tmp_path, {"transcript": "js/transcript.js", "card": "js/memory_card.js"}, MEMORY_DISCLOSURE_DOM + r"""
let writes = 0; const emitted = [], savedScopes = [];
const store = {isForgotten:()=>false, list:async()=>[], add:async value=>{writes++;savedScopes.push(value.scope);return value;}};
const session = {activeId:()=> 'c1', activeRecord:()=>({turns:[{cards:[payload()]}]}),
  addCard:async()=>{}, refreshActive:async()=>{}};
await card.mountMemorySuggestions({store,session,registry:{registerCardType(){}},doc:s.doc}).ready;
s.doc.addEventListener('nabiz:card-action', event=>emitted.push(event.detail));
const root = card.renderMemoryCard(payload(), {document:s.doc}), outer = wrapOuter(root);
const check = root.querySelector('input[type="checkbox"]'), scope = root.querySelector('input[value="profile"]');
const remember = root.querySelector('button[data-cardAction]');
transcript.mountTranscript(log,s.doc); transcript.mountTranscript(log,s.doc); sync(); sync();
const details = log.querySelector('details.memory-disclosure'), summary = details.querySelector('summary');
const closedInitially = !details.open, uncheckedInitially = !check.checked;
const originalNodes = details.children[1]===outer && details.querySelector('.memory-card')===root;
click(summary); details.open=true; click(summary); details.open=false;
const afterToggles = writes;
details.open=true; check.checked=true; change(check);
root.querySelector('input[value="conversation"]').checked=false; scope.checked=true; change(scope);
const afterChoose = writes;
click(summary); details.open=false; click(summary); details.open=true;
const selectionsPreserved = root.querySelector('input[type="checkbox"]')===check && check.checked && scope.checked;
click(remember); await settle(); sync();
console.log(JSON.stringify({closedInitially,uncheckedInitially,originalNodes,afterToggles,afterChoose,selectionsPreserved,
  writes,savedScopes,wrappers:log.querySelectorAll('details.memory-disclosure').length,observerCount:changes.length,
  summary:summary.textContent,stillOpen:details.open,controlsLeft:root.querySelectorAll('button').length,
  actions:emitted.map(value=>[value.action,value.requires_consent,Boolean(value.consented_at)])}));
""")
    assert values == {
        "closedInitially": True, "uncheckedInitially": True, "originalNodes": True,
        "afterToggles": 0, "afterChoose": 0, "selectionsPreserved": True,
        "writes": 1, "savedScopes": ["profile"], "wrappers": 1, "observerCount": 1,
        "summary": "Seçtiğiniz bilgiler Hafızam bölümüne eklendi.", "stillOpen": True, "controlsLeft": 0,
        "actions": [["remember_always", True, True]],
    }


def test_memory_disclosure_handles_async_replacement_restoration_and_language(tmp_path):
    from test_memory_ui_static import run_ui

    values = run_ui(tmp_path, {"transcript": "js/transcript.js", "card": "js/memory_card.js"}, MEMORY_DISCLOSURE_DOM + r"""
transcript.mountTranscript(log,s.doc);
const legacy = s.doc.createElement('div'); legacy.className='chat-suggest'; log.append(legacy); sync();
const legacyUntouched = legacy.parentElement===log;
const root = card.renderMemoryCard(payload(),{document:s.doc}); legacy.replaceWith(root); sync();
const details=root.closest('details.memory-disclosure'); details.open=true;
const replacement=card.renderMemoryCard(payload(),{document:s.doc}); root.replaceWith(replacement); sync(); sync();
const replacementPreserved=details.open && replacement.closest('details.memory-disclosure')===details;
s.doc.documentElement.lang='en'; languageListeners.forEach(callback=>callback({detail:{lang:'en'}}));
const english=details.querySelector('summary').textContent;
const restored=card.renderMemoryCard(payload('restored'),{document:s.doc,restored:true}); log.append(restored); sync();
const restoredSummary=restored.closest('details.memory-disclosure').querySelector('summary').textContent;
const active=card.renderMemoryCard(payload('focused'),{document:s.doc}); log.append(active);
const check=active.querySelector('input[type="checkbox"]'); check.focus(); sync();
console.log(JSON.stringify({legacyUntouched,replacementPreserved,english,restoredSummary,
  restoredButtons:restored.querySelectorAll('button').length,focusedOpen:active.closest('details.memory-disclosure').open,
  sameFocus:s.doc.activeElement===check,wrappers:log.querySelectorAll('details.memory-disclosure').length,
  nested:log.querySelectorAll('details.memory-disclosure').some(node=>node.parentElement.closest('details.memory-disclosure'))}));
""")
    assert values == {
        "legacyUntouched": True, "replacementPreserved": True, "english": "Should I remember this?",
        "restoredSummary": "Bu öneri artık geçerli değil.", "restoredButtons": 0,
        "focusedOpen": True, "sameFocus": True, "wrappers": 3, "nested": False,
    }


def test_memory_failure_retry_dismiss_and_health_keep_original_state_and_actions(tmp_path):
    from test_memory_ui_static import run_ui

    values = run_ui(tmp_path, {"transcript": "js/transcript.js", "card": "js/memory_card.js"}, MEMORY_DISCLOSURE_DOM + r"""
let fail=true,writes=0; const healthEvents=[];
const store={isForgotten:()=>false,list:async()=>[],add:async value=>{if(fail)throw Error('failed');writes++;return value;}};
const session={activeId:()=> 'c1',activeRecord:()=>({turns:[{cards:[payload()]}]}),addCard:async()=>{},refreshActive:async()=>{}};
await card.mountMemorySuggestions({store,session,registry:{registerCardType(){}},doc:s.doc}).ready;
s.doc.addEventListener('nabiz:memory-health-form', event=>healthEvents.push(event.detail.card_id));
const root=card.renderMemoryCard(payload(),{document:s.doc}); log.append(root); transcript.mountTranscript(log,s.doc);
const details=root.closest('details.memory-disclosure'); details.open=true;
const check=root.querySelector('input[type="checkbox"]');check.checked=true;change(check);
const remember=root.querySelector('button[data-cardAction]');click(remember);await settle();sync();
const failed={label:details.querySelector('summary').textContent,open:details.open,writeCount:writes,
  sameForm:root.querySelector('input[type="checkbox"]')===check && check.checked};
fail=false;click(remember);await settle();sync();
const retrySummary=details.querySelector('summary').textContent;
const dismissed=card.renderMemoryCard(payload('dismissed'),{document:s.doc});log.append(dismissed);sync();
click(dismissed.querySelector('button[data-memoryDismiss]'));sync();
const dismissedSummary=dismissed.closest('details.memory-disclosure').querySelector('summary').textContent;
const health=card.renderMemoryCard({...payload('health'),sensitive:true,body:{kind:'health'},actions:[{id:'change'}]},
  {document:s.doc});wrapOuter(health);sync();
const healthDetails=health.closest('details.memory-disclosure');
const healthClosed=!healthDetails.open,healthSummary=healthDetails.querySelector('summary').textContent;
healthDetails.open=true;click(health.querySelector('button'));await settle();sync();
console.log(JSON.stringify({failed,retrySummary,dismissedSummary,writes,healthClosed,healthSummary,
  healthChecks:health.querySelectorAll('input').length,healthButtons:health.querySelectorAll('button').length,healthEvents}));
""")
    assert values == {
        "failed": {"label": "Kaydedilemedi. Yeniden deneyin.", "open": True, "writeCount": 0, "sameForm": True},
        "retrySummary": "Seçtiğiniz bilgiler Hafızam bölümüne eklendi.",
        "dismissedSummary": "Bu öneri artık geçerli değil.", "writes": 1, "healthClosed": True,
        "healthSummary": "Sağlık beyanı ekle Sağlık beyanı Hafızam bölümünde ayrı onayla eklenir.",
        "healthChecks": 0, "healthButtons": 1, "healthEvents": ["health"],
    }


ANSWER_DETAILS_DOM = CHAT_DOM + r"""
Object.defineProperties(Node.prototype, {
  parentNode: {get() { return this.parentElement; }},
  firstChild: {get() { return this.children[0] || null; }},
  firstElementChild: {get() { return this.children[0] || null; }},
  nextSibling: {get() { const rows=this.parentElement?.children || []; return rows[rows.indexOf(this)+1] || null; }},
  content: {get() { return this; }},
});
Node.prototype.insertBefore = function(node, reference) {
  if (!reference) return this.appendChild(node);
  node.remove(); node.parentElement=this; this.children.splice(this.children.indexOf(reference),0,node); return node;
};
const originalAttribute=Node.prototype.getAttribute;
Node.prototype.getAttribute=function(name) {
  return originalAttribute.call(this,name) ?? (['type','name','value'].includes(name) ? this[name] ?? null : null);
};
const storageValues = new Map(), requests = [], mutations = [];
window.localStorage = {getItem:key=>storageValues.get(key)||null,
  setItem:(key,value)=>storageValues.set(key,String(value))};
globalThis.fetch = async (url, options={}) => {
  requests.push([String(url),options.method||'GET']);
  if (String(url)==='/data/glossary_tr.json') return {ok:true,json:async()=>({terms:[]})};
  throw Error('Unexpected request');
};
globalThis.MutationObserver = class {
  constructor(callback) { this.callback=callback; mutations.push(this); }
  observe(target, options) { this.target=target; this.options=options; }
};
const flush = () => mutations.forEach(observer=>observer.callback([]));
const answerShell = (mode='answer', flags='') => {
  const shell=add(log,'li','','chat-msg is-assistant '+flags); shell.setAttribute('aria-busy','false');
  const final=add(shell,'div','','chat-final'), answer=add(final,'section','','answer-card');
  answer.dataset.card=mode;
  const text=add(answer,'p'); text.textContent='Cevap';
  const details=add(answer,'details','','ac-details'); add(details,'summary').textContent='Ayrıntılar';
  const content=add(details,'div','','ac-details-content');
  return {shell,final,answer,details,content};
};
"""


def test_answer_details_preserve_real_reading_and_feedback_controls():
    values = run_node("real answer utilities", ANSWER_DETAILS_DOM, f"""
const transcript=await import({json.dumps((STATIC / 'js/transcript.js').as_uri())});
const answerModule=await import({json.dumps((STATIC / 'js/answer_card.js').as_uri())});
const shell=add(log,'li','','chat-msg is-assistant'); shell.setAttribute('aria-busy','false');
const done=add(shell,'p','','chat-tool is-done'); done.textContent='Sorgu bitti.';
const running=add(shell,'p','','chat-tool is-running'); running.textContent='Soruluyor.';
const final=add(shell,'div','','chat-final');
final.innerHTML=answerModule.renderAnswerCard({{mode:'answer',answer_text:'Normal cevap.',author:'model'}},{{turnId:'p26'}});
const cardModule=await import({json.dumps((STATIC / 'js/memory_card.js').as_uri())});
const memory=cardModule.renderMemoryCard({{id:'memory',message_id:'m',type:'memory',title:'Hatırlayayım mı?',
  body:{{key:'museum',label:'Müzeler',kind:'interest'}},status:'awaiting_confirmation',actions:[]}});
const cards=add(final,'div','','chat-cards'); cards.append(memory);
await import({json.dumps((STATIC / 'js/easy_read.js').as_uri())});
await import({json.dumps((STATIC / 'js/feedback.js').as_uri())});
const bar=final.querySelector('.er-bar'), toggle=bar.querySelector('.er-toggle');
const feedback=final.querySelector('.feedback'), vote=feedback.querySelector('[data-vote="up"]');
const slot=final.querySelector('.feedback-slot'), why=feedback.querySelector('.feedback-why');
const details=final.querySelector('.ac-details'), content=final.querySelector('.ac-details-content');
transcript.syncAnswerDetails(log,document); transcript.syncAnswerDetails(log,document);
const originalNodes=[bar,feedback,slot,done].every(node=>node.parentElement===content);
const initiallyClosed=!details.open, preservedHidden=why.hidden;
details.open=true;
toggle.dispatchEvent({{type:'click'}}); const enabled=toggle.getAttribute('aria-pressed');
toggle.dispatchEvent({{type:'click'}});
vote.dispatchEvent({{type:'click'}});
await Promise.resolve(); await Promise.resolve();
console.log(JSON.stringify({{originalNodes,initiallyClosed,preservedHidden,enabled,
  disabledAgain:toggle.getAttribute('aria-pressed'),
  vote:vote.getAttribute('aria-pressed'),feedbackNote:feedback.querySelector('.feedback-note').textContent,
  counts:JSON.parse(storageValues.get('nabiz.feedback.v1')).up,
  feedbackCopies:log.querySelectorAll('.feedback').length,barCopies:log.querySelectorAll('.er-bar').length,
  memoryParent:memory.parentElement===cards,memoryUnchecked:!memory.querySelector('input[type="checkbox"]').checked,
  runningOutside:running.parentElement===shell,requests}}));
""")
    assert values == {
        "originalNodes": True, "initiallyClosed": True, "preservedHidden": True,
        "enabled": "true", "disabledAgain": "false", "vote": "true", "feedbackNote": "Teşekkürler.",
        "counts": 1, "feedbackCopies": 1, "barCopies": 1, "memoryParent": True,
        "memoryUnchecked": True, "runningOutside": True, "requests": [["/data/glossary_tr.json", "GET"]],
    }


def test_answer_details_wait_for_completion_and_collect_late_nodes_once():
    values = run_node("late answer utilities", ANSWER_DETAILS_DOM, f"""
const transcript=await import({json.dumps((STATIC / 'js/transcript.js').as_uri())});
const entry=answerShell(); entry.shell.setAttribute('aria-busy','true');
const tool=add(entry.shell,'p','','chat-tool is-done'), bar=add(entry.final,'div','','er-bar');
const button=add(bar,'button'); let clicks=0; button.addEventListener('click',()=>clicks++);
transcript.mountTranscript(log,document); flush();
const busyVisible=tool.parentElement===entry.shell && bar.parentElement===entry.final;
entry.shell.setAttribute('aria-busy','false'); flush();
const completedInside=tool.parentElement===entry.content && bar.parentElement===entry.content;
const feedback=add(entry.final,'div','','feedback'); flush(); flush();
entry.details.open=true; button.dispatchEvent({{type:'click'}}); flush();
const count=entry.content.children.length; flush(); flush();
const stable=entry.content.children.length===count && entry.details.open;
const restored=answerShell(); const restoredBar=add(restored.final,'div','','er-bar'); flush();
console.log(JSON.stringify({{busyVisible,completedInside,lateInside:feedback.parentElement===entry.content,
  clicks,stable,restoredInside:restoredBar.parentElement===restored.content,restoredClosed:!restored.details.open,
  observerCount:mutations.length,busyObserved:mutations[0].options.attributeFilter.includes('aria-busy')}}));
""")
    assert values == {"busyVisible": True, "completedInside": True, "lateInside": True,
                      "clicks": 1, "stable": True, "restoredInside": True, "restoredClosed": True,
                      "observerCount": 1, "busyObserved": True}


def test_answer_details_exclude_other_modes_cards_and_keep_existing_focus():
    values = run_node("answer utility boundaries", ANSWER_DETAILS_DOM, f"""
const transcript=await import({json.dumps((STATIC / 'js/transcript.js').as_uri())});
const excluded=[answerShell('unknown'),answerShell('refused'),answerShell('quote'),
  answerShell('answer','is-emergency'),answerShell('answer','is-refused'),answerShell('answer','is-error')];
const untouched=excluded.map(entry=>add(entry.final,'div','','er-bar'));
const entry=answerShell(), bar=add(entry.final,'div','','er-bar'), button=add(bar,'button');
const memory=add(entry.final,'article','','memory-card'), nested=add(memory,'div','','er-bar');
const suggestion=add(entry.final,'div','','ac-next');
button.focus();
const originalRemove=Node.prototype.remove;
Node.prototype.remove=function() {{ if (this.contains(document.activeElement)) document.activeElement=body;
  originalRemove.call(this); }};
transcript.syncAnswerDetails(log,document); transcript.syncAnswerDetails(log,document);
console.log(JSON.stringify({{untouched:untouched.every((node,index)=>node.parentElement===excluded[index].final),
  moved:bar.parentElement===entry.content,focus:document.activeElement===button,open:entry.details.open,
  memoryUnchanged:memory.parentElement===entry.final && nested.parentElement===memory,
  suggestionPreserved:suggestion.parentElement===entry.content,
  detailsCount:entry.answer.querySelectorAll('details').length}}));
""")
    assert values == {"untouched": True, "moved": True, "focus": True, "open": True,
                      "memoryUnchanged": True, "suggestionPreserved": True, "detailsCount": 1}


def test_citizen_text_only_removes_recognised_place_output():
    values = run_node("citizen text boundaries", CHAT_DOM, f"""
const {{citizenText:clean}}=await import({json.dumps((STATIC / 'js/transcript.js').as_uri())});
const point='• Beşiktaş İskele (Beşiktaş), 41,0422, 29,0053';
const signed=point+'\\nVeri: kayıtlı · 29.09 19:48.\\nKaynak: İBB Açık Veri (CC BY 4.0) · resmî bir servis değildir.';
const numeric='• İndirim oranları, 12.500, 15.750';
const warning='Bu iskelede erişim doğrulanmadı.';
console.log(JSON.stringify({{history:clean(signed),route:clean(signed,{{route:true}}),
  unproven:clean(numeric),unprovenRoute:clean(numeric,{{route:true}}),
  live:clean(point+'\\n'+warning,{{places:true,route:true}}),
  english:clean(signed,{{route:true,lang:'en'}}),unchanged:point.includes('41,0422')}}));
""")
    assert values == {
        "history": "• Beşiktaş İskele (Beşiktaş)",
        "route": "Bu yolculuğun güzergâhını henüz doğrulayamadım.",
        "unproven": "• İndirim oranları, 12.500, 15.750",
        "unprovenRoute": "• İndirim oranları, 12.500, 15.750",
        "live": "Bu yolculuğun güzergâhını henüz doğrulayamadım.\n\nBu iskelede erişim doğrulanmadı.",
        "english": "I could not verify the directions for this journey.", "unchanged": True,
    }


def test_citizen_live_and_restored_routes_are_honest_without_changing_payload():
    values = run_node("citizen live and history", ANSWER_DETAILS_DOM, f"""
body.classList.add('citizen-page');
const transcript=await import({json.dumps((STATIC / 'js/transcript.js').as_uri())});
const {{renderAnswerCard}}=await import({json.dumps((STATIC / 'js/answer_card.js').as_uri())});
const raw='• Beşiktaş İskele (Beşiktaş), 41,0422, 29,0053\\n'
  +'Veri: kayıtlı · 29.09 19:48.\\n'
  +'Kaynak: İBB Açık Veri (CC BY 4.0) · resmî bir servis değildir.';
const question='Kadıköy’den Beşiktaş’a nasıl giderim?';
const prior=add(log,'li','','chat-msg is-user'); add(prior,'p','','chat-text').textContent=question;
const restored=add(log,'li','','chat-msg is-assistant'); const saved=add(restored,'p','','chat-text'); saved.textContent=raw;
const entry=answerShell();
const payload={{mode:'answer',answer_text:raw,citations:[{{source:'gazetteer'}}]}};
const before=JSON.stringify(payload); entry.final.innerHTML=renderAnswerCard(payload);
transcript.mountTranscript(log,document);
document.dispatchEvent(new CustomEvent('nabiz:chat-final',{{detail:{{host:entry.final,final:payload,question}}}}));
flush(); flush();
console.log(JSON.stringify({{saved:saved.textContent,live:entry.final.querySelector('.ac-short').textContent,
  preserved:JSON.stringify(payload)===before,sourceCards:entry.final.querySelectorAll('.ac-sources').length}}));
""")
    assert values == {"saved": "Bu yolculuğun güzergâhını henüz doğrulayamadım.",
                      "live": "Bu yolculuğun güzergâhını henüz doğrulayamadım.",
                      "preserved": True, "sourceCards": 0}


def test_citizen_feedback_and_copy_still_work_without_exposing_evidence():
    values = run_node("citizen feedback and copy", ANSWER_DETAILS_DOM, f"""
body.classList.add('citizen-page');
const transcript=await import({json.dumps((STATIC / 'js/transcript.js').as_uri())});
const {{renderAnswerCard}}=await import({json.dumps((STATIC / 'js/answer_card.js').as_uri())});
const copied=[]; document.defaultView={{navigator:{{clipboard:{{writeText:async text=>copied.push(text)}}}}}};
const entry=answerShell(); entry.final.innerHTML=renderAnswerCard({{mode:'answer',answer_text:'İskeleye yürüyün.',
 citations:[{{source:'gazetteer',url:'https://example.test/evidence'}}]}});
const unknown=answerShell('unknown'); unknown.final.innerHTML=renderAnswerCard({{mode:'unknown'}});
await import({json.dumps((STATIC / 'js/feedback.js').as_uri())});
transcript.mountTranscript(log,document); flush();
for (const final of [entry.final,unknown.final]) final.querySelector('[data-citizen-copy]').dispatchEvent({{type:'click'}});
await Promise.resolve(); await Promise.resolve();
const feedback=entry.final.querySelector('.feedback');
feedback.querySelector('[data-vote="up"]').dispatchEvent({{type:'click'}});
await Promise.resolve();
console.log(JSON.stringify({{copied,feedbackInside:feedback.parentElement.classList.contains('ac-details-content'),
 unknownInside:unknown.final.querySelector('.feedback').parentElement.classList.contains('ac-details-content'),
 closed:!entry.final.querySelector('.ac-details').open,
 votes:JSON.parse(storageValues.get('nabiz.feedback.v1')).up,
 emptyMarker:entry.final.querySelector('.chat-foot').hidden && !entry.final.querySelector('.chat-foot').textContent}}));
""")
    assert values == {"copied": ["İskeleye yürüyün.", "Bu bilgiyi doğrulayamadım."],
                      "feedbackInside": True, "unknownInside": True, "closed": True,
                      "votes": 1, "emptyMarker": True}
