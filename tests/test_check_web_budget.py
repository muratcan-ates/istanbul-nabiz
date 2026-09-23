"""Tests for ``scripts/check_web_budget.py``: each check must fail on the breakage it guards.

A gate that has never been seen failing is a gate nobody knows works (docs/ENGINEERING.md CI-6). So
the page in this checkout is copied into ``tmp_path``, the copy is shown to pass, and then each test
breaks the copy in one way and asserts that exactly the check guarding it turns red. The breakages
add files or edit around ``</head>``, ``</body>`` and the contract ids, which the redesign keeps, so
these tests outlive the steps that rewrite the page. Nothing reads the network.
"""

from __future__ import annotations

import base64
import importlib.util
import os
import pathlib
import re
import shutil
import sys
from collections.abc import Callable

import pytest
from conftest import REPO_ROOT

_spec = importlib.util.spec_from_file_location("check_web_budget", REPO_ROOT / "scripts" / "check_web_budget.py")
budget = importlib.util.module_from_spec(_spec)
# Registered before it runs: @dataclass resolves the module's annotations through sys.modules.
sys.modules[_spec.name] = budget
_spec.loader.exec_module(budget)

EM, EN = "—", "–"


@pytest.fixture
def repo(tmp_path: pathlib.Path) -> pathlib.Path:
    """A copy of the page as it is in this checkout, for one test to break."""
    shutil.copytree(REPO_ROOT / budget.STATIC, tmp_path / budget.STATIC)
    return tmp_path


def write(repo: pathlib.Path, name: str, text: str) -> None:
    path = repo / budget.STATIC / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def edit(repo: pathlib.Path, name: str, old: str, new: str) -> None:
    path = repo / budget.STATIC / name
    text = path.read_text(encoding="utf-8")
    assert old in text, f"{old!r} is not in {name}: the test no longer matches the page"
    path.write_text(text.replace(old, new), encoding="utf-8")


def results(repo: pathlib.Path, **kwargs: object) -> dict[str, budget.CheckResult]:
    return {r.name: r for r in budget.run_checks(repo, **kwargs)}


def failed(repo: pathlib.Path) -> set[str]:
    return {name for name, r in results(repo).items() if r.status == budget.FAIL}


def keys(repo: pathlib.Path, check: str) -> set[str]:
    return {f.key for f in results(repo)[check].findings}


# --------------------------------------------------------------------------------------
# the page as it is, and the target ratchet
# --------------------------------------------------------------------------------------
def test_the_page_in_this_checkout_passes_the_gate(capsys: pytest.CaptureFixture[str]) -> None:
    assert budget.main(["--repo", str(REPO_ROOT)]) == 0, capsys.readouterr().out


def test_a_clean_copy_passes_and_strict_mode_fails_on_the_recorded_targets(repo: pathlib.Path) -> None:
    assert failed(repo) == set()
    with_targets = {key.split(":", 1)[0] for key in budget.TARGETS}
    assert {name for name, r in results(repo, strict=True).items() if r.status == budget.FAIL} == with_targets


def test_report_mode_never_fails_even_on_a_broken_page(repo: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(repo, "js/zz.js", f"export const s = 'a {EM} b';\n")
    assert budget.main(["--repo", str(repo)]) == 1
    assert budget.main(["--repo", str(repo), "--report"]) == 0
    assert "fail" in capsys.readouterr().out


def test_a_recorded_count_may_shrink_but_never_grow() -> None:
    target = {"x:a": budget.Target("step n", 5)}

    def judged(count: int, strict: bool = False) -> str:
        return budget.judge(budget.CheckResult("x", "", [budget.Finding("x:a", "m", count)]), target, strict).status

    assert judged(5) == judged(3) == budget.TARGET
    assert judged(6) == budget.FAIL
    assert judged(3, strict=True) == budget.FAIL


def test_a_target_that_has_been_met_must_be_deleted(repo: pathlib.Path) -> None:
    stale = {**budget.TARGETS, "dashes:js/long-gone.js": budget.Target("step n", 3)}
    result = {r.name: r for r in budget.run_checks(repo, targets=stale)}["dashes"]
    assert result.status == budget.FAIL
    assert any("target met" in line for _, line in result.lines)


# --------------------------------------------------------------------------------------
# one breakage per check
# --------------------------------------------------------------------------------------
def random_text(n: int) -> str:
    """Bytes gzip cannot shrink, so the payload check sees the size a vendored library would add."""
    return base64.b64encode(os.urandom(n)).decode()


Breakage = Callable[[pathlib.Path], object]


def new_file(name: str, text: str) -> Breakage:
    return lambda r: write(r, name, text)


def replace(old: str, new: str, name: str = "index.html") -> Breakage:
    return lambda r: edit(r, name, old, new)


def in_head(html: str) -> Breakage:
    return replace("</head>", html + "</head>")


def in_body(html: str) -> Breakage:
    return replace("</body>", html + "</body>")


def script(function: str) -> Breakage:
    """A new, impure module that exports one arrow function."""
    return new_file("js/zz.js", f"export const f = {function};\n")


def drop_api_call(r: pathlib.Path) -> None:
    for path in (r / budget.STATIC).rglob("*.js"):
        if "'/api/freshness'" in path.read_text(encoding="utf-8"):
            edit(r, path.relative_to(r / budget.STATIC).as_posix(), "'/api/freshness'", "'/api/fresh'")


def drop_reduced_motion_rules(r: pathlib.Path) -> None:
    """Remove every @media (prefers-reduced-motion: reduce) block, in whichever stylesheet holds it."""
    for path in (r / budget.STATIC).rglob("*.css"):
        text = path.read_text(encoding="utf-8")
        while match := re.search(r"@media[^{]*prefers-reduced-motion\s*:\s*reduce[^{]*{", text):
            depth, i = 1, match.end()
            while depth:
                depth += {"{": 1, "}": -1}.get(text[i], 0)
                i += 1
            text = text[: match.start()] + text[i:]
        path.write_text(text, encoding="utf-8")


#: The reviewer's case of 2026-09-23: an infinite animation, and a no-preference block that guards
#: something else. The old check passed it because the words "prefers-reduced-motion" were there.
LOOSE_ANIMATION = (
    ".row-x { animation: zz 1s infinite; }\n@keyframes zz { to { opacity: .5; } }\n"
    "@media (prefers-reduced-motion: no-preference) { .chip { opacity: 1; } }\n"
)


def unguarded_animation(r: pathlib.Path) -> None:
    drop_reduced_motion_rules(r)
    write(r, "css/zz.css", LOOSE_ANIMATION)


def import_cycle(r: pathlib.Path) -> None:
    write(r, "js/zz-a.js", "import './zz-b.js';\n")
    write(r, "js/zz-b.js", "import './zz-a.js';\n")


ENTRY = '<script type="module" src="/js/main.js">'
UNKNOWN_ICON = "import { icon } from '../icons.js';\nexport const x = icon('no-such');\n"
UNUSED_SYMBOL = '<!-- icons:start --><svg><symbol id="i-zz-unused"></symbol></svg><!-- icons:end -->'

BREAKAGES: dict[str, list[tuple[str, Breakage]]] = {
    "payload": [
        ("a vendored library", new_file("js/vendor-ish.js", f"// {random_text(90_000)}\n")),
        ("a library under static/vendor/", new_file("vendor/lib.js", f"// {random_text(90_000)}\n")),
    ],
    "render-blocking": [
        ("a classic script in <head>", in_head('<script src="/x.js"></script>')),
        ("five stylesheets", in_head('<link rel="stylesheet" href="/a.css">' * 4)),
    ],
    "third-party": [
        ("a script from another CDN", in_head('<script defer src="https://cdn.example.com/x.js"></script>')),
        ("a remote url() in a stylesheet", new_file("css/zz.css", ".row-x { background: url(https://example.com/a.png); }\n")),
    ],
    "fonts": [
        ("a ttf", new_file("fonts/x.ttf", "0")),
        ("a woff2 that is not preloaded", new_file("fonts/zz.woff2", "0")),
        ("@font-face without font-display", new_file("css/zz.css", "@font-face { font-family: x; src: url(/fonts/x.woff2); }\n")),
    ],
    "motion": [
        ("a height transition", new_file("css/zz.css", ".row-x { transition: opacity .2s, height .2s; }\n")),
        ("keyframes that move margin", new_file("css/zz.css", "@keyframes zz { to { margin-left: 4px; } }\n")),
        ("an infinite animation with no reduced-motion path", unguarded_animation),
        ("a smooth scroll outside motion.js", script("(el) => el.scrollIntoView({ behavior: 'smooth' })")),
        ("an element animation outside motion.js", script("(el) => el.animate([{ opacity: 0 }], 300)")),
        ("a map camera easing outside motion.js", script("(map) => map.easeTo({ zoom: 3 })")),
        ("a fitBounds that animates", script("(map, b) => map.fitBounds(b, { padding: 48 })")),
    ],
    "tokens": [
        ("a hex colour in a stylesheet", new_file("css/zz.css", ".row-x { border-color: #1a2b3c; }\n")),
        ("a named colour in a stylesheet", new_file("css/zz.css", ".row-x { color: white; }\n")),
        ("rgb() in a script", new_file("js/cards/zz.js", "export const ink = 'rgb(1, 2, 3)';\n")),
        ("a hex colour in a script", new_file("js/cards/zz.js", "export const ink = '#0a0b0c';\n")),
        ("a fill colour on an SVG in the page", in_body('<svg fill="#ff0000"></svg>')),
        ("a fill colour in an SVG template", new_file("js/zz.js", 'export const s = (x) => `<svg fill="#ff0000">${x}</svg>`;\n')),
        ("a named colour in CSS text in a script", new_file("js/zz.js", "export const s = 'color: red';\n")),
    ],
    "file-size": [
        ("a 301-line module", new_file("js/zz.js", "// x\n" * 301)),
        ("a 351-line stylesheet", new_file("css/zz.css", "/* x */\n" * 351)),
        ("a tokens.css over its byte cap", new_file("css/tokens.css", f":root {{ --x: '{random_text(15_000)}'; }}\n")),
    ],
    "js-modules": [
        ("a pure module reading the DOM", new_file("js/cards/zz.js", "export const t = () => document.title;\n")),
        ("a pure module reading the clock", new_file("js/cards/zz.js", "export const t = () => Date.now();\n")),
        ("a pure module importing api.js", new_file("js/cards/zz.js", "import { api } from '../api.js';\nexport { api };\n")),
        ("an import cycle", import_cycle),
        ("a bare specifier", new_file("js/zz.js", "import maplibregl from 'maplibre-gl';\nexport { maplibregl };\n")),
        ("an import of a missing file", new_file("js/zz.js", "import { x } from './nope.js';\nexport { x };\n")),
        ("the entry loaded as a classic script", replace(ENTRY, '<script defer src="/js/main.js">')),
        ("the entry not preloaded", replace('<link rel="modulepreload" href="/js/main.js">', "")),
        ("/config.js gone", replace('<script defer src="/config.js"></script>', "")),
    ],
    "css-prefix": [
        ("a selector reaching into another component", new_file("css/zz.css", ".hero-title .chip-x { opacity: .5; }\n")),
        ("a class with no component prefix", new_file("css/zz.css", ".welcome-foot { opacity: .5; }\n")),
    ],
    "listeners": [
        ("addEventListener in a card", new_file("js/cards/zz.js", "export const f = (el) => el.addEventListener('click', f);\n")),
        ("an onclick handler in a chart", new_file("js/charts/zz.js", "export const f = (el) => { el.onclick = f; };\n")),
    ],
    "icons": [
        ("a hand-drawn path in the page", in_body('<svg><path d="M0 0h24"/></svg>')),
        ("an icon name no symbol defines", new_file("js/cards/zz.js", UNKNOWN_ICON)),
        ("a symbol nothing uses", in_body(UNUSED_SYMBOL)),
        ("a hand-drawn shape in a card", new_file("js/cards/zz.js", "export const s = '<circle r=\"3\"></circle>';\n")),
    ],
    "contract-ids": [
        ("a contract id removed", replace('id="strip-meta"', 'id="strip-meta-old"')),
        ("the skip link lost its target", replace('class="skip-link" href="#results"', 'class="skip-link" href="#main"')),
        ("a lookup of an id nobody has", new_file("js/zz.js", "export const el = () => document.querySelector('#nowhere');\n")),
        ("an API call dropped", drop_api_call),
    ],
    "dashes": [
        ("an em dash in the page", in_body(f"<p>a {EM} b</p>")),
        ("an en dash in a title attribute", in_body(f'<span title="0{EN}200"></span>')),
        ("an en dash in a script string", new_file("js/zz.js", f"export const s = '0{EN}200';\n")),
        ("an escaped em dash in a template", new_file("js/zz.js", "export const s = (x) => `${x} \\u2014 y`;\n")),
        ("an em dash in CSS content", new_file("css/zz.css", f'.row-x::before {{ content: "{EM}"; }}\n')),
        ("&mdash; in an innerHTML template", new_file("js/zz.js", "export const s = (x) => `<span>${x} &mdash; veri</span>`;\n")),
        ("a numeric entity dash in a script string", new_file("js/zz.js", "export const s = 'yok &#8212; veri';\n")),
        ("an em dash on a submit button", in_body(f'<input type="submit" value="Sor {EM} ara">')),
    ],
}


@pytest.mark.parametrize(
    ("check", "breakage"),
    [(check, b) for check, cases in BREAKAGES.items() for b in cases],
    ids=[f"{check}: {label}" for check, cases in BREAKAGES.items() for label, _ in cases],
)
def test_each_check_turns_red_on_the_breakage_it_guards(
    repo: pathlib.Path, check: str, breakage: tuple[str, Breakage]
) -> None:
    breakage[1](repo)
    result = results(repo)[check]
    # Red for the breakage itself, not only because it also happened to meet a recorded target.
    assert any(status == budget.FAIL and not line.startswith("target met") for status, line in result.lines), result.lines


def test_every_check_has_a_breakage_that_turns_it_red() -> None:
    assert set(BREAKAGES) == set(budget.CHECK_NAMES)


# --------------------------------------------------------------------------------------
# what must not count
# --------------------------------------------------------------------------------------
def test_dashes_in_comments_and_regexes_are_not_visible_text(repo: pathlib.Path) -> None:
    write(repo, "js/zz.js", f"// a {EM} b\n/* c {EN} d */\nexport const r = /[{EM}-]+/g;\nexport const q = (x) => x / 2 / 3;\n")
    edit(repo, "index.html", "</body>", f"<!-- e {EM} f --></body>")
    assert "dashes:js/zz.js" not in keys(repo, "dashes")
    assert "dashes" not in failed(repo)


def test_the_charter_attribution_line_is_the_one_allowed_dash() -> None:
    assert budget.dash_count("  Kamu sektörü bilgilerini içerir — İBB Açık Veri Portalı,\n  ") == 0
    assert budget.dash_count(f"Kamu sektörü bilgilerini içerir {EM} başka bir şey") == 1


def test_generated_icon_blocks_and_chart_drawings_are_not_hand_drawn_icons(repo: pathlib.Path) -> None:
    block = '<!-- icons:start --><svg><symbol id="i-zz"><path d="M0 0"/></symbol></svg><!-- icons:end -->'
    edit(repo, "index.html", "</body>", f'{block}<svg><use href="#i-zz"></use></svg></body>')
    write(repo, "js/charts/zz.js", "export const dot = (x) => `<circle cx=\"${x}\" r=\"3\"></circle>`;\n")
    assert "icons" not in failed(repo)


def test_colour_literals_are_allowed_in_tokens_css_and_ids_are_not_colours(repo: pathlib.Path) -> None:
    write(repo, "css/tokens.css", ":root { --surface: #ffffff; --text: oklch(0.2 0.02 260); }\n")
    write(repo, "js/zz.js", "export const el = () => document.querySelector('#results .card');\n")
    assert not {key for key in keys(repo, "tokens") if "tokens.css" in key or "zz.js" in key}


def test_currentcolor_and_none_are_not_colour_literals(repo: pathlib.Path) -> None:
    edit(repo, "index.html", "</body>", '<svg fill="none" stroke="currentColor"></svg></body>')
    write(repo, "js/zz.js", "export const s = (x) => `<svg fill=\"none\" stroke=\"currentColor\">${x}</svg>`;\n")
    assert not {key for key in keys(repo, "tokens") if key in {"tokens:index.html", "tokens:js/zz.js"}}


def test_animations_inside_no_preference_need_no_global_stop(repo: pathlib.Path) -> None:
    """The other way to honour reduced motion: every animation guarded where it is declared."""
    drop_reduced_motion_rules(repo)
    for path in (repo / budget.STATIC).rglob("*.css"):  # the page's own animations, guarded
        path.write_text(f"@media (prefers-reduced-motion: no-preference) {{\n{path.read_text(encoding='utf-8')}\n}}\n")
    write(repo, "css/zz.css", "@media (prefers-reduced-motion: no-preference) { .row-x { animation: zz 1s infinite; } }\n")
    assert not {key for key in keys(repo, "motion") if key.startswith("motion:reduced")}


def test_scripted_motion_belongs_in_motion_js_and_an_instant_fit_is_fine(repo: pathlib.Path) -> None:
    write(repo, "js/zz.js", "export const f = (map, b) => map.fitBounds(b, { padding: 48, duration: 0 });\n")
    write(repo, "js/motion.js", "export const smooth = (el) => el.scrollIntoView({ behavior: 'smooth' });\n")
    assert not {key for key in keys(repo, "motion") if key.startswith("motion:script")}


def test_component_classes_state_classes_and_contract_hooks_mix_freely(repo: pathlib.Path) -> None:
    selectors = ".sheet-head .card.is-focused, .row-title .icon, .chip[aria-pressed=true] .chip-label"
    write(repo, "css/zz.css", selectors + " { opacity: 1; }\n")
    assert "css-prefix" not in failed(repo)


def test_the_js_lexer_tells_strings_from_comments_and_regexes() -> None:
    source = (
        "const u = 'https://x/y'; // c — d\n"
        "const r = /[’'`]\\/—/g;\n"
        "const t = `a ${ `b ${'c—'}` } d`;\n"
        "const q = x / 2 / y;\n"
    )
    lexer = budget.JsLexer(source).run()
    assert [text for _, text in lexer.strings] == ["https://x/y", "a ", "b ", "c—", "", " d"]
    code = "".join(lexer.code)
    assert "—" not in code and "https" not in code
    assert "x / 2 / y" in code
    assert "https://x/y" in "".join(lexer.bare) and "// c" not in "".join(lexer.bare)
