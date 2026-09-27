"""Contracts for the citizen composer and its nearby conversation."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from html.parser import HTMLParser

import pytest
from conftest import REPO_ROOT

STATIC = REPO_ROOT / "src" / "nabiz" / "console" / "static"
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


@dataclass(eq=False)
class Element:
    tag: str
    attrs: dict[str, str | None] = field(default_factory=dict)
    parent: Element | None = None
    order: int = 0
    children: list[Element] = field(default_factory=list)
    text: str = ""

    def classes(self) -> set[str]:
        return set((self.attrs.get("class") or "").split())


class Page(HTMLParser):
    def __init__(self, html: str) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Element("document")
        self.stack = [self.root]
        self.elements: list[Element] = []
        self.feed(html)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        parent = self.stack[-1]
        element = Element(tag, dict(attrs), parent, len(self.elements))
        parent.children.append(element)
        self.elements.append(element)
        if tag not in VOID_TAGS:
            self.stack.append(element)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        self.stack[-1].text += data

    def id(self, value: str) -> Element:
        found = [element for element in self.elements if element.attrs.get("id") == value]
        assert len(found) == 1, f"expected one #{value}, found {len(found)}"
        return found[0]


def page() -> Page:
    return Page((STATIC / "index.html").read_text(encoding="utf-8"))


def inside(element: Element, ancestor: Element) -> bool:
    current: Element | None = element
    while current is not None:
        if current is ancestor:
            return True
        current = current.parent
    return False


def text_of(element: Element) -> str:
    return " ".join(" ".join([element.text, *(text_of(child) for child in element.children)]).split())


def node_json(tmp_path, name: str, body: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    harness = tmp_path / f"{name}.mjs"
    harness.write_text(body, encoding="utf-8")
    result = subprocess.run([node, str(harness)], capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_the_hero_is_one_composer_with_one_primary() -> None:
    document = page()
    hero, form, input_field, submit = (document.id(value) for value in ("home-screen", "chat-form", "chat-input", "chat-submit"))
    assert form.tag == "form" and {"chat-form", "composer", "glass"} <= form.classes()
    assert inside(form, hero) and inside(input_field, form) and inside(submit, form)
    labels = [element for element in document.elements if element.tag == "label" and element.attrs.get("for") == "chat-input"]
    assert len(labels) == 1 and inside(labels[0], form) and labels[0].order < input_field.order
    assert inside(document.id("composer-tools"), form)
    primary = [element for element in document.elements if "btn-primary" in element.classes() and inside(element, hero)]
    assert primary == [submit] and submit.attrs.get("type") == "submit"

    pill = document.id("ask-pill")
    assert pill.tag == "button" and "btn-primary" in pill.classes() and "hidden" in pill.attrs
    assert not inside(pill, hero)
    home = (STATIC / "js" / "home.js").read_text(encoding="utf-8")
    assert "IntersectionObserver" in home and "scrollIntoView" in home
    assert not re.search(r"\.addEventListener\(\s*['\"]scroll['\"]", home)


def test_the_conversation_follows_the_composer() -> None:
    document = page()
    hero, chat, city = (document.id(value) for value in ("home-screen", "asistan", "city-cards"))
    assert hero.order < chat.order < city.order
    assert hero.parent is chat.parent and chat.parent is city.parent
    assert chat.parent.children.index(chat) == chat.parent.children.index(hero) + 1
    assert not any("workspace" in ancestor.classes() for ancestor in _ancestors(chat))
    assert inside(document.id("chat-log"), chat) and inside(document.id("chat-status"), chat)
    assert inside(document.id("convo-root"), chat)
    assert document.id("chat-log").attrs.get("aria-live") == "polite"


def _ancestors(element: Element):
    current = element.parent
    while current is not None:
        yield current
        current = current.parent


def test_secondary_hints_live_in_the_disclosure() -> None:
    document = page()
    disclosure = document.id("composer-more")
    assert disclosure.tag == "details" and "more" in disclosure.classes()
    assert disclosure.children and disclosure.children[0].tag == "summary"
    for element_id in ("chat-hint", "quota-strip", "chat-lang"):
        assert inside(document.id(element_id), disclosure)
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    chat_lang_line = (
        '<p id="chat-lang">Cevap dili: <button type="button" class="btn" '
        'id="chat-lang-en" aria-pressed="false">English</button></p>'
    )
    assert chat_lang_line in html


def test_no_split_header_and_one_eyebrow_in_view() -> None:
    document = page()
    hero = document.id("home-screen")
    assert not any("section-head" in element.classes() and inside(element, hero) for element in document.elements)
    eyebrows = [element for element in document.elements if "eyebrow" in element.classes()]
    assert len(eyebrows) <= 2
    assert document.id("home-eyebrow") in eyebrows and inside(document.id("home-eyebrow"), hero)


def test_every_hidden_section_keeps_its_id_and_label() -> None:
    document = page()
    for section_id in ("profilim", "hesap", "takip", "hafizam", "acik-veri", "compare"):
        section = document.id(section_id)
        labelled_by = section.attrs.get("aria-labelledby")
        assert labelled_by, section_id
        details = next((ancestor for ancestor in (section, *_ancestors(section)) if ancestor.tag == "details"), None)
        assert details is not None and "more" in details.classes(), section_id
        summary = next((child for child in details.children if child.tag == "summary"), None)
        assert summary is not None and inside(document.id(labelled_by), summary), section_id


def test_home_opens_the_details_that_holds_the_target(tmp_path) -> None:
    module = json.dumps((STATIC / "js" / "home.js").as_uri())
    result = node_json(tmp_path, "home_details", f"""
      globalThis.window = {{location: {{hash: '#profilim'}}}};
      let focused = false; const revealed = [];
      const heading = {{focus: () => {{ focused = true; }}, hasAttribute: () => false, setAttribute: () => {{}}}};
      const details = {{tagName: 'DETAILS', open: false}};
      const target = {{id: 'profilim', getAttribute: (name) => name === 'aria-labelledby' ? 'profile-title' : null,
        closest: (selector) => selector === 'details' ? details : null, focus: () => {{}}}};
      globalThis.document = {{dispatchEvent: (event) => revealed.push(event.detail.id),
        getElementById: (id) => ({{profilim: target, 'profile-title': heading}})[id] || null}};
      const {{openTargetDetails}} = await import({module});
      openTargetDetails();
      console.log(JSON.stringify({{open: details.open, focused, revealed}}));
    """)
    assert result == {"open": True, "focused": True, "revealed": ["profilim"]}


def test_quick_chips_show_three_and_keep_the_rest(tmp_path) -> None:
    module = json.dumps((STATIC / "js" / "quick_chips.js").as_uri())
    result = node_json(tmp_path, "quick_split", f"""
      globalThis.window = {{location: {{search: ''}}}};
      globalThis.document = {{querySelector: () => null}};
      const {{splitChips}} = await import({module});
      const chip = (id, english = true) => ({{id, text_tr: id, ...(english ? {{text_en: id}} : {{}})}});
      const categories = [
        {{id: 'transport', chips: [chip('a1'), chip('a2')]}},
        {{id: 'services', chips: [chip('b1', false), chip('b2'), chip('b3'), chip('b4')]}}
      ];
      const before = JSON.stringify(categories);
      const tr = splitChips(categories, 3, false);
      const en = splitChips(categories, 3, true);
      const view = (part) => ({{visible: part.visible.map((entry) => entry.chip.id),
        remaining: part.remaining.map((entry) => [entry.category.id, entry.chips.map((chip) => chip.id)])}});
      console.log(JSON.stringify({{tr: view(tr), en: view(en), unchanged: JSON.stringify(categories) === before}}));
    """)
    assert result == {
        "tr": {"visible": ["a1", "a2", "b1"], "remaining": [["services", ["b2", "b3", "b4"]]]},
        "en": {"visible": ["a1", "a2", "b2"], "remaining": [["services", ["b3", "b4"]]]},
        "unchanged": True,
    }


def test_voice_mounts_in_the_composer_without_growing() -> None:
    source = (STATIC / "js" / "voice.js").read_text(encoding="utf-8")
    assert len(source.splitlines()) <= 404
    assert "getElementById('composer-tools')" in source
    assert re.search(r"\bappend\(region\)", source)


def test_citizen_motion_is_guarded_and_colourless() -> None:
    css = (STATIC / "css" / "citizen.css").read_text(encoding="utf-8")
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgb|rgba|hsl|hsla|oklch|oklab|lab|lch)\s*\(", css)
    assert not re.search(r"text-transform\s*:\s*uppercase", css, flags=re.I)
    context: list[str] = []
    part = ""
    for token in re.split(r"([{};])", css):
        if token == "{":
            context.append(part.strip())
            part = ""
        elif token == "}":
            assert context, "unbalanced CSS block"
            context.pop()
            part = ""
        elif token == ";":
            if re.match(r"\s*(?:-webkit-)?(?:animation|transition)(?:-[\w-]+)?\s*:", part):
                assert any("@media" in rule and "(prefers-reduced-motion: no-preference)" in rule for rule in context), part
            part = ""
        else:
            part += token
    assert not context, "unbalanced CSS block"


def test_the_disclaimer_is_in_the_topbar() -> None:
    document = page()
    topbar = next(element for element in document.elements if element.tag == "header" and "topbar" in element.classes())
    role = next(element for element in document.elements if "topbar-role" in element.classes() and inside(element, topbar))
    assert "Resmî İBB hizmeti değildir" in text_of(role)
