#!/usr/bin/env python3
"""Budgets and fences for the citizen-facing page (src/nabiz/web/static).

The page is vanilla HTML, CSS and ES modules with no build step, so nothing else stands between
an edit and what a phone downloads. The rules are the frontend half of the design spec's section 15
(FE-MOD, FE-OPT). Each check below is tied to its reason::

    payload          First-party bytes, raw and gzip -9 (the level Starlette's GZipMiddleware uses),
                     against HTML 20/6 KB, CSS 40/10 KB, JS 80/25 KB, total 140/40 KB. Tripwires for a
                     vendored library dropped into static/, not targets.
    render-blocking  First paint on a phone is round trips, not bytes: no third-party stylesheet, no
                     classic script without defer in <head>, at most 4 first-party stylesheets.
    third-party      Only the pinned MapLibre build from cdnjs, and only with an integrity hash: in the
                     page, and in a script that loads it later (js/map.js), which must then hold a
                     hash per file and set crossOrigin, or the browser skips the integrity check.
    fonts            Self-hosted woff2 only, font-display swap or optional, preloaded, at most 4 files
                     and 60 KB, or text is invisible while a font downloads.
    motion           Transitions and keyframes never animate layout (width, height, top, margin...),
                     which drops frames and moves content. Reduced motion is checked by structure,
                     not by the words "prefers-reduced-motion" appearing somewhere: either one
                     "@media (prefers-reduced-motion: reduce)" rule on * stops every animation and
                     transition, or each animation sits inside "(prefers-reduced-motion:
                     no-preference)". Scripted motion (a smooth scrollIntoView, element.animate, a
                     map camera easing) lives only in js/motion.js, which checks the preference.
    tokens           A colour literal lives only in css/tokens.css, so the palette has one source and
                     dark mode cannot miss a hard-coded colour. Scripts never hold one: MapLibre paint
                     reads the token with getComputedStyle. Counted in declarations, inline styles,
                     SVG colour attributes (fill, stroke, stop-color...) in the page and in script
                     strings, and CSS text inside script strings.
    file-size        300 lines per JS module and 350 per hand-written CSS file: a file over the cap does
                     more than one job. css/tokens.css is generated, so it is capped by bytes instead.
    js-modules       One module entry (/js/main.js) after the classic /config.js, modulepreload for its
                     direct imports, no cycle, no bare import. The pure modules never touch document,
                     window, fetch, storage or the clock, and import only pure modules, so node can
                     test them with no DOM.
    css-prefix       In the component stylesheets a selector stays inside one component's prefix;
                     one reaching into another component breaks when either is restyled.
    listeners        No addEventListener in cards/ or charts/: one delegated listener per region,
                     wired where the region's teardown lives.
    icons            Icons come from the vendored Tabler sprite (inside <!-- icons:start --> and
                     <!-- icons:end -->, or static/icons.svg; the favicon too). Every referenced name
                     exists, every symbol is used, and no SVG shape is hand-drawn outside those blocks
                     or js/charts/.
    contract-ids     The ids, elements and API calls the scripts and tests depend on (spec section 17)
                     exist, and every id a script looks up is in the page or written by a script.
    dashes           No em or en dash (U+2014, U+2013) in visible text: HTML text and attributes (a
                     button input's value too), JS string literals with their unicode escapes and HTML
                     entities (&mdash; written into innerHTML is a dash on screen), CSS content. The
                     charter's attribution line is the one allowlisted string (owner decision 1).
                     Server-generated text is tests/test_answer_text.py's half of the rule.

Targets. Findings the page had when these gates landed are listed in TARGETS_BY_CHECK, each with the step of
the design spec's plan (section 18) that removes it and, where it is a count, the count it may not
exceed. They print as TARGET and do not fail. Anything else fails; so does a count above its target,
and so does an entry whose finding is gone ("met: delete the entry"), so each redesign step has to
delete what it fixed. Nothing here compares the table with the committed one: raising or adding an
entry is a review matter, with its reason written beside the entry and in the commit.

Modes::

    .venv/bin/python scripts/check_web_budget.py            # the gate: FAIL on anything not a target
    .venv/bin/python scripts/check_web_budget.py --strict   # targets fail too: the enforcing mode
    .venv/bin/python scripts/check_web_budget.py --report   # print everything, always exit 0
    .venv/bin/python scripts/check_web_budget.py --only dashes,icons

Stdlib only, no network. Exit 1 on any FAIL (never with --report).
"""

from __future__ import annotations

import argparse
import fnmatch
import gzip
import html
import pathlib
import re
import sys
import urllib.parse
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from html.parser import HTMLParser

ROOT = pathlib.Path(__file__).resolve().parents[1]
STATIC = pathlib.Path("src/nabiz/web/static")
PASS, FAIL, TARGET = "PASS", "FAIL", "TARGET"

#: (raw bytes, gzip -9 bytes) per asset type, first party only.
BUDGETS = {"html": (20_000, 6_000), "css": (40_000, 10_000), "js": (80_000, 25_000), "total": (140_000, 40_000)}
JS_MODULE_MAX_LINES = 300
CSS_FILE_MAX_LINES = 350
TOKENS_CSS = "css/tokens.css"
TOKENS_MAX_BYTES = (16_000, 4_000)
MAX_FIRST_PARTY_STYLESHEETS = 4
FONT_BUDGET_BYTES = 60_000
MAX_FONT_FILES = 4
ALLOWED_THIRD_PARTY = (
    re.compile(r"^https://cdnjs\.cloudflare\.com/ajax/libs/maplibre-gl/\d+\.\d+\.\d+/maplibre-gl\.min\.(js|css)$"),
)
#: A script string naming a CDN file is a loader (js/map.js builds "<base>.css" and "<base>.js").
CDN_URL = re.compile(r"^https://cdnjs\.cloudflare\.com/")
SRI_HASH = re.compile(r"^sha(?:256|384|512)-[A-Za-z0-9+/]{43,86}={0,2}$")
ENTRY_MODULE = "/js/main.js"
CONFIG_SCRIPT = "/config.js"
#: FE-MOD-2. Node imports these in tests, so they get their time and data as arguments.
PURE_MODULES = ("js/format.js", "js/router.js", "js/provenance.js", "js/icons.js", "js/charts/*.js", "js/cards/*.js")
IMPURE = re.compile(
    r"(?<![\w$.])(?:document|window|globalThis|navigator|fetch|localStorage|sessionStorage)\b"
    r"|\bDate\s*\.\s*now\b|\bMath\s*\.\s*random\b|\bnew\s+Date\s*\(\s*\)"
)
NO_LISTENERS = ("js/cards/*.js", "js/charts/*.js")
#: FE-MOD-5. A class belongs to the component whose prefix it starts with.
COMPONENT_PREFIXES = (
    "topbar", "hero", "ask", "chip", "pulse", "ruler", "sheet", "row", "stamp", "badge", "scale", "ribbon",
    "callout", "skeleton", "map", "marker", "footer",
)
#: Classes that belong to no component: states, utilities and the class hooks scripts depend on (spec 17.1).
NEUTRAL_CLASSES = {"icon", "sr-only", "wrap", "spin", "ok", "warn", "bad", "card", "chip-label", "journey-tile", "icon-btn"}
NON_COMPONENT_CSS = {TOKENS_CSS, "css/base.css"}

#: Spec 17.1: ids present on 2026-09-23 that keep their name, and ids the redesign adds.
CONTRACT_IDS = (
    "live-pill", "live-pill-text", "theme-toggle", "hero-title", "ask-form", "q", "ask-submit", "ask-hint",
    "freshness-strip", "strip-title", "strip-meta", "freshness-refresh", "strip-rail", "alerts-panel",
    "alerts-title", "alerts-body", "results", "map-panel", "map-title", "map-source", "map", "map-fallback",
    "map-fallback-list", "map-legend", "reliability-panel", "reliability-title", "reliability-body",
    "attribution", "version", "map-attribution", "hero-pulse", "hero-readout", "answer-status", "hakkinda",
    "ruler-table",
)
#: Ids a script writes into the page instead of the markup holding them.
GENERATED_IDS = ("alerts-reset",)
#: Spec 17.3: every route the page calls today. A refactor that drops one drops a feature.
API_CALLS = (
    "/api/places", "/api/parking", "/api/route", "/api/stops", "/api/buses", "/api/arrivals", "/api/reliability",
    "/api/metro", "/api/metro/station", "/api/traffic", "/api/air", "/api/air/forecast", "/api/alerts/check",
    "/api/freshness",
)
DASHES = ("\u2014", "\u2013")
#: Owner decision 1: the charter's attribution line (docs/NABIZ.md, ibb_mcp.config.ATTRIBUTION) ships
#: verbatim until the owner changes it everywhere at once. Its dash is the only one allowed.
ALLOWED_DASH_TEXT = ("Kamu sektörü bilgilerini içerir \u2014 İBB Açık Veri Portalı",)
VISIBLE_ATTRIBUTES = {"title", "alt", "aria-label", "aria-description", "placeholder", "label"}
#: An <input> of these types shows its value as the button's label.
BUTTON_INPUTS = {"submit", "button", "reset"}
#: SVG presentation attributes that take a colour. currentColor and none are not literals.
COLOUR_ATTRIBUTES = {"fill", "stroke", "stop-color", "flood-color", "lighting-color", "color"}
SHAPE = re.compile(r"<(path|circle|rect|line|polyline|polygon|ellipse|symbol)\b", re.I)
HEX_COLOUR = r"#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b"
COLOUR_FUNCTION = r"\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\("
#: CSS named colours (CSS Color 4). One string, split below, because 148 quoted words read worse.
CSS_NAMED_COLOURS = (
    "aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue blueviolet brown burlywood "
    "cadetblue chartreuse chocolate coral cornflowerblue cornsilk crimson cyan darkblue darkcyan darkgoldenrod darkgray "
    "darkgreen darkgrey darkkhaki darkmagenta darkolivegreen darkorange darkorchid darkred darksalmon darkseagreen "
    "darkslateblue darkslategray darkslategrey darkturquoise darkviolet deeppink deepskyblue dimgray dimgrey dodgerblue "
    "firebrick floralwhite forestgreen fuchsia gainsboro ghostwhite gold goldenrod gray green greenyellow grey honeydew "
    "hotpink indianred indigo ivory khaki lavender lavenderblush lawngreen lemonchiffon lightblue lightcoral lightcyan "
    "lightgoldenrodyellow lightgray lightgreen lightgrey lightpink lightsalmon lightseagreen lightskyblue lightslategray "
    "lightslategrey lightsteelblue lightyellow lime limegreen linen magenta maroon mediumaquamarine mediumblue "
    "mediumorchid mediumpurple mediumseagreen mediumslateblue mediumspringgreen mediumturquoise mediumvioletred "
    "midnightblue mintcream mistyrose moccasin navajowhite navy oldlace olive olivedrab orange orangered orchid "
    "palegoldenrod palegreen paleturquoise palevioletred papayawhip peachpuff peru pink plum powderblue purple "
    "rebeccapurple red rosybrown royalblue saddlebrown salmon sandybrown seagreen seashell sienna silver skyblue "
    "slateblue slategray slategrey snow springgreen steelblue tan teal thistle tomato turquoise violet wheat white "
    "whitesmoke yellow yellowgreen"
)
NAMED_COLOURS = frozenset(CSS_NAMED_COLOURS.split())
CSS_COLOUR = re.compile(rf"{HEX_COLOUR}|{COLOUR_FUNCTION}|\b(?:{'|'.join(sorted(NAMED_COLOURS))})\b", re.I)
#: In a script only a string that is a colour, or a colour inside CSS text, counts: "#abc" alone could be
#: an id selector, and ids are not colours.
JS_COLOUR = re.compile(rf"^\s*{HEX_COLOUR}\s*$|[:(,]\s*{HEX_COLOUR}|{COLOUR_FUNCTION}", re.I)
#: Markup and CSS text inside a script string: fill="#f00" in an SVG template, "color: red" in a
#: style attribute. The value is then counted with CSS_COLOUR, named colours included.
JS_COLOUR_ATTRIBUTE = re.compile(r"""\b(?:fill|stroke|stop-color|flood-color|lighting-color)\s*=\s*["']([^"']*)""", re.I)
JS_CSS_DECLARATION = re.compile(
    r"(?<![\w-])(?:color|background(?:-color)?|border(?:-(?:top|right|bottom|left))?(?:-color)?|outline(?:-color)?"
    r"|fill|stroke|stop-color|box-shadow|text-shadow|caret-color|accent-color|text-decoration-color)\s*:\s*([^;\"'`}]*)",
    re.I,
)
#: FE-OPT-9: these move content from a script; only js/motion.js may call them, because it checks
#: prefers-reduced-motion first. fitBounds is allowed with duration: 0 (it then jumps).
MOTION_MODULE = "js/motion.js"
SCRIPTED_MOTION = re.compile(r"\.(?:animate|easeTo|flyTo|panTo|panBy|zoomTo|zoomIn|zoomOut|rotateTo)\s*\(")
SMOOTH_SCROLL = re.compile(r"""behavior\s*:\s*['"]smooth['"]""")
FIT_BOUNDS = re.compile(r"\.fitBounds\s*\(([^;]*)")
REDUCE = re.compile(r"prefers-reduced-motion\s*:\s*reduce")
NO_PREFERENCE = re.compile(r"prefers-reduced-motion\s*:\s*no-preference")
#: A duration this short is "off": the usual reduce block sets .001ms rather than none, so
#: animationend and transitionend still fire for scripts that wait on them.
NEAR_ZERO_MS = 10.0
UNGUARDED = " (wrap it in no-preference, or stop all motion with a reduce rule on *)"
#: Animating these recomputes layout on every frame; ``all`` includes them.
LAYOUT_PROPS = {
    "all", "width", "height", "min-width", "max-width", "min-height", "max-height", "top", "left", "right", "bottom",
    "inset", "margin", "margin-top", "margin-right", "margin-bottom", "margin-left", "padding", "padding-top",
    "padding-right", "padding-bottom", "padding-left", "font-size", "border-width", "flex-basis",
}


@dataclass(frozen=True)
class Target:
    """A finding the page is allowed to keep until ``step`` lands; ``limit`` caps a count."""

    step: str
    limit: int = 1


STEP7 = "step 7: answers"
STEP8 = "step 8: map"

#: Measured on the tree these gates landed on (2026-09-23, after the ES module split); steps are the
#: design spec's section 18. Grouped by check; each step deletes the entries it meets, and a met
#: entry left here fails.
TARGETS_BY_CHECK: dict[str, dict[str, Target]] = {
    # 19 modules gzipped one by one: 26,801 B against 20,647 B for the same code as one stream, and
    # 19,240 B for the old app.js. The 25 KB budget predates the split; it is the owner's to set.
    # Raised from 1,801 to 3,164 on 2026-09-23, in the open, for the review's fixes to the old
    # renderers (data age in the freshness strip and pill, focus kept on "Sor", Turkish map names
    # and marker labels, an hourly table for the traffic bars, badge ink, js/motion.js): 26,801 B
    # to 28,164 B. Step 7 replaces those renderers; eval/results/web-vitals.md has the numbers.
    # Raised again to 3,376 the same day for step 3 (+212 B): js/icons.js now knows which Tabler
    # glyphs are inline in the page and sends the rest to /icons.svg, and the call sites use
    # Tabler's names. Added "total" with steps 3 and 4: that JS overage, plus icons.svg (1,941 B
    # gzip, new), puts the page past 40 KB while HTML (5,056 of 6,000 B) and CSS (9,810 of
    # 10,000 B) stay inside their own budgets. 160 B of the CSS are base.css's rules for the old
    # renderers' two gauges, which step 7 deletes with them (unstyled, each drew as a black shape).
    # The type budgets add up to more than the total, so the total holds only once step 7 brings
    # the JS down.
    # Raised to 14,974 and 17,162 the same day for steps 5 and 6, in the open (JS 28,376 B to
    # 39,974 B gzip, +11,598 B): the pen line (charts/pulse-geometry.js 2,997 B, pulse-view.js
    # 2,658 B), the age ruler (charts/age-ruler.js 2,395 B) and hero.js (1,713 B) are 9,763 B;
    # the other 1,835 B are the lazy MapLibre loader with its hashes (map.js), the ruler's host
    # (freshness.js), the empty-question message and delegated listeners (main.js), the answer
    # announcement and the shared traffic payload (journeys.js), the theme button's label and
    # icon, and the stamp's verb and icon (provenance.js). The total adds the new markup (HTML
    # +328 B) and the ruler's rows (CSS +53 B). The raw JS is past 80 KB too (91,773 B).
    "payload": {
        "js": Target("owner: JS gzip budget for native modules", 14_974),
        "total": Target(f"owner: the JS budget above; {STEP7} replaces the renderers", 17_162),
    },
}
TARGETS: dict[str, Target] = {
    f"{check}:{subject}": target for check, entries in TARGETS_BY_CHECK.items() for subject, target in entries.items()
}


@dataclass
class Finding:
    key: str  # "<check>:<subject>", stable across edits; what TARGETS is keyed on
    message: str
    count: int = 1


@dataclass
class CheckResult:
    name: str
    summary: str
    findings: list[Finding] = field(default_factory=list)
    status: str = PASS
    lines: list[tuple[str, str]] = field(default_factory=list)


# --------------------------------------------------------------------------------------
# reading the page
# --------------------------------------------------------------------------------------
REGEX_AFTER = set("(,=:[!&|?{};+-*%<>~^")
#: An identifier or a number: either ends an expression, so a ``/`` after it divides.
WORD = re.compile(r"[A-Za-z_$][\w$]*|\d[\w.]*")
REGEX_KEYWORDS = {"return", "typeof", "case", "do", "else", "in", "instanceof", "new", "delete", "void", "throw",
                  "yield", "await", "of"}


class JsLexer:
    """Separate a script into code, comments, string literals and regex literals.

    Not a parser: enough of one to tell visible text (string and template literals) from comments
    and regexes, which is what the dash, colour, purity and listener checks need. A ``/`` is a regex
    when the previous code token cannot end an expression, the usual heuristic.
    """

    def __init__(self, text: str) -> None:
        self.text = text
        self.i = 0
        self.code = list(text)  # comments, strings and regexes blanked
        self.bare = list(text)  # comments blanked, literals kept (import specifiers live there)
        self.strings: list[tuple[int, str]] = []
        self.braces: list[int] = []  # one open-brace count per template substitution we are inside
        self.last = ""

    def run(self) -> JsLexer:
        text = self.text
        while self.i < len(text):
            char = text[self.i]
            if text.startswith("//", self.i) or text.startswith("/*", self.i):
                self.comment()
            elif char in "'\"":
                self.quoted(char)
            elif char == "`":
                self.i += 1
                self.template()
            elif char == "/" and (not self.last or self.last in REGEX_AFTER or self.last in REGEX_KEYWORDS):
                self.regex()
            elif char == "}" and self.braces and self.braces[-1] == 0:
                self.braces.pop()
                self.i += 1
                self.template()
            else:
                self.token(char)
        return self

    def blank(self, start: int, end: int, also_bare: bool = False) -> None:
        for k in range(start, end):
            if self.text[k] != "\n":
                self.code[k] = " "
                if also_bare:
                    self.bare[k] = " "

    def line(self, pos: int) -> int:
        return self.text.count("\n", 0, pos) + 1

    def comment(self) -> None:
        start = self.i
        if self.text.startswith("//", start):
            end = self.text.find("\n", start)
            end = len(self.text) if end < 0 else end
        else:
            end = self.text.find("*/", start + 2)
            end = len(self.text) if end < 0 else end + 2
        self.blank(start, end, also_bare=True)
        self.i = end

    def quoted(self, quote: str) -> None:
        start = self.i
        i = start + 1
        while i < len(self.text) and self.text[i] not in (quote, "\n"):
            i += 2 if self.text[i] == "\\" else 1
        self.strings.append((self.line(start), unescape(self.text[start + 1 : i])))
        self.blank(start + 1, i)
        self.i = i + 1
        self.last = "a"

    def template(self) -> None:
        """Read template text from ``self.i`` up to the closing backtick or the next ``${``."""
        start = i = self.i
        while i < len(self.text):
            if self.text[i] == "\\":
                i += 2
            elif self.text[i] == "`" or self.text.startswith("${", i):
                break
            else:
                i += 1
        self.strings.append((self.line(start), unescape(self.text[start:i])))
        self.blank(start, i)
        if self.text.startswith("${", i):
            self.braces.append(0)
            self.i, self.last = i + 2, "{"
        else:
            self.i, self.last = i + 1, "a"

    def regex(self) -> None:
        start = i = self.i + 1
        in_class = False
        while i < len(self.text) and self.text[i] != "\n":
            char = self.text[i]
            if char == "\\":
                i += 1
            elif char == "[" or char == "]":
                in_class = char == "["
            elif char == "/" and not in_class:
                break
            i += 1
        self.blank(start, i)
        i += 1
        while i < len(self.text) and self.text[i].isalpha():
            i += 1
        self.i, self.last = i, "a"

    def token(self, char: str) -> None:
        match = WORD.match(self.text, self.i)
        if match:
            self.last = match.group(0) if not match.group(0)[0].isdigit() else "0"
            self.i = match.end()
            return
        if char == "{" and self.braces:
            self.braces[-1] += 1
        elif char == "}" and self.braces:
            self.braces[-1] -= 1
        if not char.isspace():
            self.last = char
        self.i += 1


def unescape(literal: str) -> str:
    """Resolve \\uXXXX and \\u{...} escapes, so a dash written as an escape is still a dash."""
    literal = re.sub(r"\\u\{([0-9a-fA-F]+)\}", lambda m: chr(int(m.group(1), 16)), literal)
    return re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), literal)


@dataclass
class Script:
    path: str
    text: str
    code: str
    bare: str
    strings: list[tuple[int, str]]

    @classmethod
    def read(cls, static: pathlib.Path, path: pathlib.Path) -> Script:
        text = path.read_text(encoding="utf-8")
        lexer = JsLexer(text).run()
        return cls(rel(static, path), text, "".join(lexer.code), "".join(lexer.bare), lexer.strings)


class Document(HTMLParser):
    """Everything the checks read from index.html, in one pass."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_head = False
        self.raw_tag: str | None = None  # inside <script> or <style>
        self.generated = False  # between <!-- icons:start --> and <!-- icons:end -->
        self.elements: list[tuple[str, dict[str, str], bool]] = []  # (tag, attributes, in <head>)
        self.texts: list[tuple[int, str]] = []
        self.styles: list[str] = []
        self.shapes_outside = 0
        self.symbols: list[tuple[str, bool]] = []  # (id, inside a generated block)
        self.uses: list[str] = []
        self.colour_attributes: list[str] = []  # fill="..." and friends, outside the generated blocks
        self.drawn_favicons: list[str] = []  # SVG data-URI favicons written by hand, outside the generated blocks

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name: value or "" for name, value in attrs}
        self.in_head = self.in_head or tag == "head"
        self.elements.append((tag, attributes, self.in_head))
        if tag in {"script", "style"}:
            self.raw_tag = tag
        if tag == "symbol":
            self.symbols.append((attributes.get("id", ""), self.generated))
        if SHAPE.fullmatch(f"<{tag}") and not self.generated:
            self.shapes_outside += 1
        if tag == "link" and "icon" in attributes.get("rel", "").split() and not self.generated:
            self.drawn_favicons.append(attributes.get("href", ""))
        if tag == "use":
            self.uses.append(attributes.get("href") or attributes.get("xlink:href", ""))
        line = self.getpos()[0]
        self.texts += [(line, value) for name, value in attributes.items() if name in VISIBLE_ATTRIBUTES]
        if tag == "input" and attributes.get("type", "").lower() in BUTTON_INPUTS:
            self.texts.append((line, attributes.get("value", "")))
        if not self.generated:
            self.colour_attributes += [value for name, value in attributes.items() if name in COLOUR_ATTRIBUTES]
        if tag == "meta" and attributes.get("name") == "description":
            self.texts.append((line, attributes.get("content", "")))
        if "style" in attributes:
            self.styles.append(attributes["style"])

    def handle_endtag(self, tag: str) -> None:
        if tag == "head":
            self.in_head = False
        if tag == self.raw_tag:
            self.raw_tag = None

    def handle_data(self, data: str) -> None:
        if self.raw_tag == "style":
            self.styles.append(data)
        elif self.raw_tag is None and data.strip():
            self.texts.append((self.getpos()[0], data))

    def handle_comment(self, data: str) -> None:
        if data.strip() in {"icons:start", "icons:end"}:
            self.generated = data.strip() == "icons:start"

    def tags(self, name: str) -> list[dict[str, str]]:
        return [attributes for tag, attributes, _ in self.elements if tag == name]

    def ids(self) -> set[str]:
        return {attributes["id"] for _, attributes, _ in self.elements if attributes.get("id")}


@dataclass
class Page:
    static: pathlib.Path
    html: str
    doc: Document
    scripts: dict[str, Script]
    styles: dict[str, str]  # relative path -> CSS with comments removed

    @classmethod
    def read(cls, static: pathlib.Path) -> Page:
        html = (static / "index.html").read_text(encoding="utf-8")
        doc = Document()
        doc.feed(html)
        scripts = {rel(static, p): Script.read(static, p) for p in files(static, ".js")}
        styles = {rel(static, p): strip_css_comments(p.read_text(encoding="utf-8")) for p in files(static, ".css")}
        return cls(static, html, doc, scripts, styles)

    def matching(self, patterns: tuple[str, ...]) -> list[Script]:
        return [s for path, s in sorted(self.scripts.items()) if any(fnmatch.fnmatch(path, p) for p in patterns)]


def rel(static: pathlib.Path, path: pathlib.Path) -> str:
    return path.relative_to(static).as_posix()


def files(static: pathlib.Path, suffix: str) -> list[pathlib.Path]:
    """Every file of this type under static/. No directory is exempt: a vendored library is exactly
    what the payload budget is a tripwire for, and it is first party once it is served from here."""
    return sorted(static.rglob(f"*{suffix}"))


def strip_css_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)


def is_external(url: str | None) -> bool:
    return bool(url) and url.startswith(("http://", "https://", "//"))


def gz(data: bytes) -> int:
    return len(gzip.compress(data, compresslevel=9))


# --------------------------------------------------------------------------------------
# the checks
# --------------------------------------------------------------------------------------
def check_payload(page: Page) -> CheckResult:
    """First-party bytes per type, raw and gzip -9, against BUDGETS."""
    totals = {kind: [0, 0] for kind in ("html", "css", "js", "svg")}
    for kind in totals:
        for path in files(page.static, f".{kind}"):
            data = path.read_bytes()
            totals[kind][0] += len(data)
            totals[kind][1] += gz(data)
    totals["total"] = [sum(v[0] for v in totals.values()), sum(v[1] for v in totals.values())]
    # The count is the bytes over budget, so a recorded overrun may shrink but never grow.
    findings = [
        Finding(f"payload:{kind}", f"{kind}: {raw:,} B raw / {packed:,} B gzip, budget {limit[0]:,} / {limit[1]:,}", over)
        for kind, (raw, packed) in totals.items()
        if (limit := BUDGETS.get(kind)) and (over := max(raw - limit[0], packed - limit[1])) > 0
    ]
    summary = ", ".join(f"{k} {raw / 1000:.1f}/{packed / 1000:.1f} KB" for k, (raw, packed) in totals.items() if raw)
    return CheckResult("payload", summary + " (raw/gzip)", findings)


def check_render_blocking(page: Page) -> CheckResult:
    """No third-party render-blocking resource; at most N first-party stylesheets."""
    findings, own_css = [], 0
    for tag, attributes, in_head in page.doc.elements:
        url = attributes.get("href") if tag == "link" else attributes.get("src")
        if tag == "link" and attributes.get("rel") == "stylesheet" and attributes.get("media") in (None, "", "all", "screen"):
            own_css += not is_external(url)
            if is_external(url):
                findings.append(Finding(f"render-blocking:{url}", f"third-party stylesheet {url} blocks first paint"))
        blocking = not ({"defer", "async"} & attributes.keys() or attributes.get("type") == "module")
        if tag == "script" and url and in_head and blocking:
            findings.append(Finding(f"render-blocking:{url}", f"script {url} in <head> without defer, async or type=module"))
    if own_css > MAX_FIRST_PARTY_STYLESHEETS:
        message = f"{own_css} first-party stylesheets (max {MAX_FIRST_PARTY_STYLESHEETS})"
        findings.append(Finding("render-blocking:stylesheets", message))
    return CheckResult("render-blocking", f"{own_css} first-party stylesheet(s)", findings)


def check_third_party(page: Page) -> CheckResult:
    """Every absolute asset URL is an allowlisted, pinned build loaded with an integrity hash."""
    findings, seen = [], 0
    for tag, attributes in ((t, a) for t, a, _ in page.doc.elements if t in {"link", "script", "img", "iframe", "source"}):
        url = attributes.get("href") if tag == "link" else attributes.get("src")
        if not is_external(url) or attributes.get("rel") in {"preconnect", "dns-prefetch"}:
            continue
        seen += 1
        if not any(pattern.match(url) for pattern in ALLOWED_THIRD_PARTY):
            findings.append(Finding(f"third-party:{url}", f"not allowlisted: {url}"))
        elif not attributes.get("integrity") or "crossorigin" not in attributes:
            findings.append(Finding(f"third-party:sri:{url}", f"{url} has no integrity hash and crossorigin"))
    for path, css in page.styles.items():
        for url in re.findall(r"url\(\s*['\"]?((?:https?:)?//[^'\")\s]+)", css):
            findings.append(Finding(f"third-party:{url}", f"{path} loads {url}"))
    loaded, found = loader_findings(page)
    return CheckResult("third-party", f"{seen} third-party asset(s) in the page, {loaded} in scripts", findings + found)


def loader_findings(page: Page) -> tuple[int, list[Finding]]:
    """A script that loads a CDN file later (js/map.js builds "<base>.css" and "<base>.js"): the base is
    allowlisted, and the script holds an integrity hash per file and sets crossOrigin."""
    loaded, findings = 0, []
    for path, script in sorted(page.scripts.items()):
        urls = [text for _, text in script.strings if CDN_URL.match(text)]
        loaded += len(urls)
        for url in urls:
            if not any(pattern.match(url) or pattern.match(f"{url}.js") for pattern in ALLOWED_THIRD_PARTY):
                findings.append(Finding(f"third-party:{path}:{url}", f"{path} loads {url}, which is not allowlisted"))
        hashes = sum(1 for _, text in script.strings if SRI_HASH.match(text))
        if urls and (hashes < 2 or "crossOrigin" not in script.code):
            message = f"{path} loads a CDN file without an integrity hash per file ({hashes}) and crossOrigin"
            findings.append(Finding(f"third-party:sri:{path}", message))
    return loaded, findings


def check_fonts(page: Page) -> CheckResult:
    """Self-hosted woff2, font-display swap/optional, preloaded, inside the byte budget."""
    findings = []
    faces = [m.group(1) for css in page.styles.values() for m in re.finditer(r"@font-face\s*{([^}]*)}", css)]
    for n, face in enumerate(faces, 1):
        if not re.search(r"font-display\s*:\s*(swap|optional)", face):
            findings.append(Finding(f"fonts:display:{n}", f"@font-face #{n} without font-display: swap|optional"))
        if re.search(r"url\(\s*['\"]?(https?:)?//", face):
            findings.append(Finding(f"fonts:remote:{n}", f"@font-face #{n} loads from another origin; self-host it"))
    fonts = sorted(p for p in page.static.rglob("*") if p.suffix in {".woff2", ".woff", ".ttf", ".otf"})
    preloaded = {a.get("href", "") for a in page.doc.tags("link") if a.get("rel") == "preload" and a.get("as") == "font"}
    for path in fonts:
        name = rel(page.static, path)
        if path.suffix != ".woff2":
            findings.append(Finding(f"fonts:{name}", f"{name}: serve woff2 only"))
        elif f"/{name}" not in preloaded:
            findings.append(Finding(f"fonts:preload:{name}", f"{name} is not preloaded (<link rel=preload as=font crossorigin>)"))
    size = sum(p.stat().st_size for p in fonts)
    if size > FONT_BUDGET_BYTES or len(fonts) > MAX_FONT_FILES:
        message = f"{len(fonts)} font file(s), {size:,} B (max {MAX_FONT_FILES}, {FONT_BUDGET_BYTES:,} B)"
        findings.append(Finding("fonts:budget", message))
    return CheckResult("fonts", f"{len(faces)} @font-face, {len(fonts)} file(s), {size:,} B", findings)


def css_blocks(css: str) -> list[tuple[str, str]]:
    """Top-level ``(prelude, body)`` pairs of a stylesheet with comments removed, by brace depth."""
    blocks, depth, head, start, prelude = [], 0, 0, 0, ""
    for i, char in enumerate(css):
        if char == "{":
            if depth == 0:
                prelude, start = css[head:i].strip(), i + 1
            depth += 1
        elif char == "}" and depth:
            depth -= 1
            if depth == 0:
                blocks.append((prelude, css[start:i]))
                head = i + 1
        elif char == ";" and depth == 0:
            head = i + 1  # a statement at-rule such as @import
    return blocks


def style_rules(css: str, media: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], str, str]]:
    """Every style rule as ``(enclosing conditional at-rules, selector, declarations)``."""
    for prelude, body in css_blocks(css):
        lowered = prelude.lower()
        if lowered.startswith(("@media", "@supports", "@layer", "@container")):
            yield from style_rules(body, (*media, lowered))
        elif not lowered.startswith("@"):  # @keyframes and @font-face hold no style rules
            yield media, prelude, body


def declarations(body: str) -> dict[str, str]:
    return {name.lower(): value.strip().lower() for name, value in re.findall(r"([\w-]+)\s*:\s*([^;]+)", body)}


def is_off(value: str | None) -> bool:
    """none, or a duration so short nothing visibly moves."""
    if value is None:
        return False
    value = value.replace("!important", "").strip()
    match = re.fullmatch(r"(\d*\.?\d+)(ms|s)", value)
    return value == "none" or bool(match and float(match.group(1)) * (1 if match.group(2) == "ms" else 1000) <= NEAR_ZERO_MS)


def stops_all_motion(selector: str, body: str) -> bool:
    """A rule on ``*`` that turns every animation and transition off."""
    if "*" not in {part.split(":")[0].strip() for part in selector.split(",")}:
        return False
    found = declarations(body)
    animation = found.get("animation-duration") or found.get("animation") or found.get("animation-name")
    transition = found.get("transition-duration") or found.get("transition") or found.get("transition-property")
    return is_off(animation) and is_off(transition)


def unguarded_motion(page: Page) -> Counter[str]:
    """Per stylesheet, the animations and transform transitions with no reduced-motion path."""
    rules = [(path, *rule) for path, css in page.styles.items() for rule in style_rules(css)]
    if any(stops_all_motion(selector, body) for _, media, selector, body in rules if any(REDUCE.search(m) for m in media)):
        return Counter()
    loose: Counter[str] = Counter()
    for path, media, _, body in rules:
        found = declarations(body)
        moves = any(not is_off(found.get(name)) for name in ("animation", "animation-name") if name in found)
        moves = moves or bool(re.search(r"\b(?:transform|all)\b", found.get("transition", "")))
        if moves and not any(NO_PREFERENCE.search(m) for m in media):
            loose[path] += 1
    return loose


def scripted_motion(page: Page) -> Counter[str]:
    """Smooth scrolls, element and map-camera animations outside js/motion.js."""
    found: Counter[str] = Counter()
    for path, script in page.scripts.items():
        if path == MOTION_MODULE:
            continue
        found[path] += len(SCRIPTED_MOTION.findall(script.code)) + len(SMOOTH_SCROLL.findall(script.bare))
        found[path] += sum(1 for m in FIT_BOUNDS.finditer(script.bare) if not re.search(r"duration\s*:\s*0\b", m.group(1)))
    return +found


def check_motion(page: Page) -> CheckResult:
    """Animate transform, opacity and paint only; everything that moves has a reduced-motion path."""
    layout: Counter[tuple[str, str]] = Counter()
    moving = 0
    for path, css in page.styles.items():
        for m in re.finditer(r"transition(?:-property)?\s*:\s*([^;}]+)", css):
            moving += 1
            props = {part.split()[0] for part in m.group(1).split(",") if part.strip()}
            layout.update((path, f"transition:{p}") for p in props & LAYOUT_PROPS)
        for m in re.finditer(r"@keyframes\s+([\w-]+)\s*{(.*?)}\s*}", css, flags=re.S):
            moving += 1
            props = set(re.findall(r"([a-z-]+)\s*:", m.group(2)))
            layout.update((path, f"keyframes {m.group(1)}:{p}") for p in props & LAYOUT_PROPS)
    findings = [
        Finding(f"motion:{path}:{what}", f"{path}: {what.replace(':', ' animates ')} ({n}x)", n)
        for (path, what), n in sorted(layout.items())
    ]
    findings += [
        Finding(f"motion:reduced:{path}", f"{path}: {n} animation(s) with no reduced-motion path{UNGUARDED}", n)
        for path, n in sorted(unguarded_motion(page).items())
    ]
    findings += [
        Finding(f"motion:script:{path}", f"{path}: {n} scripted animation(s); move them into {MOTION_MODULE}", n)
        for path, n in sorted(scripted_motion(page).items())
    ]
    return CheckResult("motion", f"{moving} transition/keyframe rule(s)", findings)


def colour_literals(css: str) -> int:
    """Colours in declaration values only: selectors, strings, url() and custom-property names are not colours."""
    n = 0
    for block in re.findall(r"{([^{}]*)}", css):
        for declaration in block.split(";"):
            value = declaration.partition(":")[2]
            value = re.sub(r"(['\"]).*?\1|url\([^)]*\)|--[\w-]+", " ", value)
            n += len(CSS_COLOUR.findall(value))
    return n


def script_colours(text: str) -> int:
    """Colours in one script string: the string itself, SVG colour attributes, CSS declarations in it."""
    embedded = [m.group(1) for m in JS_COLOUR_ATTRIBUTE.finditer(text)] + [m.group(1) for m in JS_CSS_DECLARATION.finditer(text)]
    found = sum(len(CSS_COLOUR.findall(value)) for value in embedded)
    return found or int(bool(JS_COLOUR.search(text)))


def check_tokens(page: Page) -> CheckResult:
    """Colour literals only in css/tokens.css; none in scripts, inline styles or other stylesheets."""
    counts: Counter[str] = Counter()
    for path, css in page.styles.items():
        if path != TOKENS_CSS:
            counts[path] += colour_literals(css)
    counts["index.html"] += sum(colour_literals("{" + style + "}") for style in page.doc.styles)
    counts["index.html"] += sum(len(CSS_COLOUR.findall(value)) for value in page.doc.colour_attributes)
    for path, script in page.scripts.items():
        counts[path] += sum(script_colours(text) for _, text in script.strings)
    findings = [
        Finding(f"tokens:{path}", f"{path}: {n} colour literal(s) outside {TOKENS_CSS}", n)
        for path, n in sorted(counts.items())
        if n
    ]
    return CheckResult("tokens", f"{sum(counts.values())} colour literal(s) outside {TOKENS_CSS}", findings)


def check_file_size(page: Page) -> CheckResult:
    """300 lines per JS module, 350 per hand-written CSS file; tokens.css capped by bytes."""
    findings = []
    for path in files(page.static, ".js") + files(page.static, ".css"):
        name = rel(page.static, path)
        if name == TOKENS_CSS:
            continue
        lines = len(path.read_text(encoding="utf-8").splitlines())
        cap = JS_MODULE_MAX_LINES if path.suffix == ".js" else CSS_FILE_MAX_LINES
        if lines > cap:
            findings.append(Finding(f"file-size:{name}", f"{name}: {lines} lines > {cap}", lines))
    tokens = page.static / TOKENS_CSS
    if not tokens.is_file():
        findings.append(Finding(f"file-size:{TOKENS_CSS}:missing", f"{TOKENS_CSS} does not exist; its byte cap applies then"))
    elif len(data := tokens.read_bytes()) > TOKENS_MAX_BYTES[0] or gz(data) > TOKENS_MAX_BYTES[1]:
        raw_cap, gzip_cap = TOKENS_MAX_BYTES
        message = f"{TOKENS_CSS}: {len(data):,} B raw / {gz(data):,} B gzip, cap {raw_cap:,} / {gzip_cap:,}"
        findings.append(Finding(f"file-size:{TOKENS_CSS}", message))
    caps = f"JS module <= {JS_MODULE_MAX_LINES} lines, CSS file <= {CSS_FILE_MAX_LINES}, {TOKENS_CSS} <= 16/4 KB"
    return CheckResult("file-size", caps, findings)


def import_graph(page: Page) -> tuple[dict[str, set[str]], list[Finding]]:
    """Resolve every static and dynamic import; flag bare and unresolvable specifiers."""
    graph: dict[str, set[str]] = {}
    findings = []
    pattern = (
        r"""^\s*(?:import|export)\b[^'"`;]*?\bfrom\s*['"]([^'"]+)['"]"""  # import x from '...', export ... from '...'
        r"""|^\s*import\s*['"]([^'"]+)['"]"""  # import '...' for its side effects
        r"""|\bimport\(\s*['"]([^'"]+)['"]\s*\)"""  # import('...'), the lazy map loader
    )
    for path, script in page.scripts.items():
        graph[path] = set()
        for match in re.finditer(pattern, script.bare, flags=re.M):
            spec = next(group for group in match.groups() if group)
            if not spec.startswith(("./", "../", "/")):
                message = f"{path} imports {spec!r}: a bare specifier needs npm or a build step"
                findings.append(Finding(f"js-modules:bare:{path}:{spec}", message))
                continue
            base = page.static if spec.startswith("/") else (page.static / path).parent
            target = (base / spec.lstrip("/")).resolve()
            if not target.is_file() or not target.is_relative_to(page.static.resolve()):
                findings.append(Finding(f"js-modules:missing:{path}:{spec}", f"{path} imports {spec}, which does not exist"))
                continue
            graph[path].add(rel(page.static.resolve(), target))
    return graph, findings


def cycles(graph: dict[str, set[str]]) -> list[str]:
    found, done, stack = [], set(), []

    def walk(node: str) -> None:
        if node in stack:
            found.append(" -> ".join(stack[stack.index(node) :] + [node]))
            return
        if node in done:
            return
        stack.append(node)
        for nxt in sorted(graph.get(node, ())):
            walk(nxt)
        stack.pop()
        done.add(node)

    for node in sorted(graph):
        walk(node)
    return found


def entry_findings(page: Page, graph: dict[str, set[str]]) -> list[Finding]:
    """FE-MOD-1: /config.js (classic, defer) first, then the one module entry, with modulepreload."""
    scripts = [a for a in page.doc.tags("script") if a.get("src")]
    sources = [a["src"] for a in scripts]
    modules = [a["src"] for a in scripts if a.get("type") == "module"]
    findings = []
    if modules != [ENTRY_MODULE]:
        message = f"the page must load one module entry {ENTRY_MODULE}, found {modules or 'none'}"
        findings.append(Finding("js-modules:entry", message))
    elif CONFIG_SCRIPT not in sources or sources.index(CONFIG_SCRIPT) > sources.index(ENTRY_MODULE):
        message = f"{CONFIG_SCRIPT} must be a script before {ENTRY_MODULE}, so its globals exist at boot"
        findings.append(Finding("js-modules:config", message))
    preloaded = {a.get("href") for a in page.doc.tags("link") if a.get("rel") == "modulepreload"}
    for module in sorted(graph.get(ENTRY_MODULE.lstrip("/"), set()) | {ENTRY_MODULE.lstrip("/")}):
        if modules == [ENTRY_MODULE] and f"/{module}" not in preloaded:
            findings.append(Finding(f"js-modules:preload:{module}", f"no <link rel=modulepreload href=/{module}>"))
    return findings


def check_js_modules(page: Page) -> CheckResult:
    """Entry and preload, resolvable imports, no cycle, pure modules pure and importing only pure modules."""
    graph, findings = import_graph(page)
    findings += entry_findings(page, graph)
    findings += [Finding(f"js-modules:cycle:{c}", f"import cycle {c}") for c in cycles(graph)]
    pure = {script.path for script in page.matching(PURE_MODULES)}
    for path in sorted(pure):
        for n, line in enumerate(page.scripts[path].code.splitlines(), 1):
            for word in IMPURE.findall(line):
                findings.append(Finding(f"js-modules:pure:{path}:{word}", f"{path}:{n} uses {word}; pass it in instead"))
        for imported in sorted(graph[path] - pure):
            findings.append(Finding(f"js-modules:pure:{path}->{imported}", f"pure {path} imports {imported}, which is not pure"))
    return CheckResult("js-modules", f"{len(graph)} module(s), {len(pure)} pure", findings)


def component_of(name: str) -> str | None:
    """The component a class belongs to (longest matching prefix), '' for a neutral class, None if unknown."""
    if name in NEUTRAL_CLASSES or name.startswith(("is-", "has-")):
        return ""
    matches = [p for p in COMPONENT_PREFIXES if name == p or name.startswith((p + "-", p + "s"))]
    return max(matches, key=len) if matches else None


def check_css_prefix(page: Page) -> CheckResult:
    """In component stylesheets, every class has a component prefix and a selector stays in one component."""
    findings, rules = [], 0
    for path, css in sorted(page.styles.items()):
        if not path.startswith("css/") or path in NON_COMPONENT_CSS:
            continue
        for selectors in re.findall(r"([^{}@;]+)\{", css):
            for selector in (s.strip() for s in selectors.split(",") if s.strip() and not s.strip()[0].isdigit()):
                rules += 1
                owners = {name: component_of(name) for name in re.findall(r"\.(-?[_a-zA-Z][\w-]*)", selector)}
                strays = sorted(name for name, owner in owners.items() if owner is None)
                components = sorted({owner for owner in owners.values() if owner})
                if strays:
                    message = f"{path}: {selector!r} uses unprefixed .{', .'.join(strays)}"
                elif len(components) > 1:
                    message = f"{path}: {selector!r} reaches across {' and '.join(components)}"
                else:
                    continue
                findings.append(Finding(f"css-prefix:{path}:{selector}", message))
    return CheckResult("css-prefix", f"{rules} selector(s) in component stylesheets", findings)


def check_listeners(page: Page) -> CheckResult:
    """No listener or on* handler inside cards/ and charts/: renderers return strings."""
    findings = []
    for script in page.matching(NO_LISTENERS):
        n = len(re.findall(r"\baddEventListener\b|\.on[a-z]+\s*=(?!=)", script.code))
        if n:
            message = f"{script.path}: {n} listener(s); delegate from the region instead"
            findings.append(Finding(f"listeners:{script.path}", message, n))
    return CheckResult("listeners", f"{len(page.matching(NO_LISTENERS))} renderer module(s)", findings)


def icon_names(page: Page) -> set[str]:
    """Symbol ids the page asks for: <use href>, icon('x'), icon: 'x', and *_ICON maps."""
    names = {href.rsplit("#", 1)[-1] for href in page.doc.uses if "#" in href}
    for script in page.scripts.values():
        bare = script.bare
        found = re.findall(r"\bicon\(\s*['\"]([\w-]+)['\"]", bare)
        found += re.findall(r"\bicon\s*:\s*(?:[^,}\n'\"]*\|\|\s*)?['\"]([\w-]+)['\"]", bare)
        for block in re.findall(r"_ICONS?\s*=\s*{([^}]*)}", bare):
            found += re.findall(r":\s*['\"]([\w-]+)['\"]", block)
        found += re.findall(r"#(i-[\w-]+)['\"`]", bare)
        names |= {name if name.startswith("i-") else f"i-{name}" for name in found}
    return names


def check_icons(page: Page) -> CheckResult:
    """Vendored sprite only: names resolve, symbols are used, no hand-drawn shape outside the blocks."""
    external = page.static / "icons.svg"
    symbols = {sid for sid, _ in page.doc.symbols}
    if external.is_file():
        symbols |= set(re.findall(r"<symbol\b[^>]*\bid=['\"]([\w-]+)['\"]", external.read_text(encoding="utf-8")))
    names = icon_names(page)
    findings = [Finding(f"icons:unknown:{n}", f"icon {n} is referenced, no symbol defines it") for n in sorted(names - symbols)]
    findings += [Finding(f"icons:unused:{n}", f"symbol {n} is never referenced") for n in sorted(symbols - names)]
    drawn = page.doc.shapes_outside + sum(
        len(SHAPE.findall(urllib.parse.unquote(href))) for href in page.doc.drawn_favicons if href.startswith("data:image/svg")
    )
    if drawn:
        findings.append(Finding("icons:index.html", f"index.html: {drawn} SVG shape(s) outside the generated icon blocks", drawn))
    for script in page.scripts.values():
        shapes = sum(len(SHAPE.findall(text)) for _, text in script.strings)
        if shapes and not script.path.startswith("js/charts/"):
            message = f"{script.path}: {shapes} hand-drawn SVG shape(s); icons come from the sprite, drawings from js/charts/"
            findings.append(Finding(f"icons:{script.path}", message, shapes))
    return CheckResult("icons", f"{len(symbols)} symbol(s), {len(names)} referenced", findings)


def check_contract_ids(page: Page) -> CheckResult:
    """Spec 17: contract ids, the elements scripts hook onto, the ids scripts look up, the API calls."""
    ids = page.doc.ids()
    strings = {text for script in page.scripts.values() for _, text in script.strings}
    written = {m for text in strings for m in re.findall(r"\bid=['\"]([\w-]+)['\"]", text)}
    findings = [Finding(f"contract-ids:#{i}", f"#{i} is missing from index.html") for i in CONTRACT_IDS if i not in ids]
    findings += [Finding(f"contract-ids:#{i}", f"no script writes #{i}") for i in GENERATED_IDS if i not in written]
    looked_up = set()
    for script in page.scripts.values():
        for _, selector in re.findall(r"(?:\$|querySelector(?:All)?|closest)\(\s*(['\"])(.*?)\1", script.bare):
            looked_up |= set(re.findall(r"#([\w-]+)", selector))
        looked_up |= set(re.findall(r"getElementById\(\s*['\"]([\w-]+)['\"]", script.bare))
    findings += [
        Finding(f"contract-ids:lookup:#{i}", f"a script looks up #{i}, which neither the page nor a script has")
        for i in sorted(looked_up - ids - written)
    ]
    for label, ok in required_elements(page.doc):
        if not ok:
            findings.append(Finding(f"contract-ids:{label}", f"no element matches {label}"))
    findings += [Finding(f"contract-ids:{call}", f"no script calls {call}") for call in API_CALLS if call not in strings]
    return CheckResult("contract-ids", f"{len(CONTRACT_IDS)} ids, {len(API_CALLS)} API calls", findings)


def required_elements(doc: Document) -> list[tuple[str, bool]]:
    """Classes and attributes scripts depend on (spec 17.1, last paragraph)."""

    def has(tag: str | None, cls: str | None, predicate: Callable[[dict[str, str]], bool] = lambda a: True) -> bool:
        return any(
            (tag is None or t == tag) and (cls is None or cls in a.get("class", "").split()) and predicate(a)
            for t, a, _ in doc.elements
        )

    return [
        ('a.skip-link[href="#results"]', has("a", "skip-link", lambda a: a.get("href") == "#results")),
        (".chips", has(None, "chips")),
        (".chip[data-journey]", has(None, "chip", lambda a: "data-journey" in a)),
        (".chip-label", has(None, "chip-label")),
        (".journey-tile[data-journey]", has(None, "journey-tile", lambda a: "data-journey" in a)),
        ('#results[tabindex="-1"][aria-busy]', has(None, None, lambda a: a.get("id") == "results" and a.get("tabindex") == "-1")
         and has(None, None, lambda a: a.get("id") == "results" and "aria-busy" in a)),
    ]


def dash_count(text: str) -> int:
    text = " ".join(text.split())
    for allowed in ALLOWED_DASH_TEXT:
        text = text.replace(allowed, "")
    return sum(text.count(d) for d in DASHES)


def check_dashes(page: Page) -> CheckResult:
    """No U+2014 or U+2013 in visible text, except the allowlisted charter line."""
    counts = Counter({"index.html": sum(dash_count(text) for _, text in page.doc.texts)})
    for path, script in page.scripts.items():
        # Renderers build HTML for innerHTML, where &mdash; and &#8212; are dashes on screen.
        counts[path] = sum(dash_count(html.unescape(text)) for _, text in script.strings)
    for path, css in page.styles.items():
        counts[path] = sum(dash_count(value) for value in re.findall(r"content\s*:\s*([^;}]+)", css))
    findings = [
        Finding(f"dashes:{path}", f"{path}: {n} em/en dash(es) in visible text", n) for path, n in sorted(counts.items()) if n
    ]
    return CheckResult("dashes", f"{sum(counts.values())} dash(es) in visible text, 1 allowlisted string", findings)


CHECKS: tuple[Callable[[Page], CheckResult], ...] = (
    check_payload, check_render_blocking, check_third_party, check_fonts, check_motion, check_tokens,
    check_file_size, check_js_modules, check_css_prefix, check_listeners, check_icons, check_contract_ids,
    check_dashes,
)
CHECK_NAMES = tuple(fn.__name__.removeprefix("check_").replace("_", "-") for fn in CHECKS)


# --------------------------------------------------------------------------------------
# targets and output
# --------------------------------------------------------------------------------------
def judge(result: CheckResult, targets: dict[str, Target], strict: bool) -> CheckResult:
    """Mark each finding FAIL or TARGET, and fail on a target whose finding is gone."""
    for finding in result.findings:
        target = targets.get(finding.key)
        if target is None or strict:
            result.lines.append((FAIL, finding.message))
        elif finding.count > target.limit:
            result.lines.append((FAIL, f"{finding.message}: grew past its target of {target.limit}"))
        else:
            result.lines.append((TARGET, f"{finding.message} [{target.step}]"))
    present = {finding.key for finding in result.findings}
    for key in sorted(k for k in targets if k.startswith(result.name + ":") and k not in present):
        check, subject = key.split(":", 1)
        result.lines.append((FAIL, f"target met: delete TARGETS_BY_CHECK[{check!r}][{subject!r}] ({targets[key].step})"))
    statuses = {status for status, _ in result.lines}
    result.status = FAIL if FAIL in statuses else TARGET if TARGET in statuses else PASS
    return result


def run_checks(repo: pathlib.Path, only: list[str] | None = None, strict: bool = False,
               targets: dict[str, Target] | None = None) -> list[CheckResult]:
    page = Page.read(repo / STATIC)
    targets = TARGETS if targets is None else targets
    return [judge(fn(page), targets, strict) for fn, name in zip(CHECKS, CHECK_NAMES, strict=True) if not only or name in only]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="check_web_budget", description="Budgets and fences for the web UI.")
    parser.add_argument("--repo", type=pathlib.Path, default=ROOT, help="repository root (default: this checkout)")
    parser.add_argument("--only", help=f"comma-separated subset of: {', '.join(CHECK_NAMES)}")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--strict", action="store_true", help="recorded targets fail too (the enforcing mode)")
    mode.add_argument("--report", action="store_true", help="print everything and always exit 0 (baselines)")
    args = parser.parse_args(argv)
    only = [name.strip() for name in args.only.split(",")] if args.only else None
    if only and (unknown := sorted(set(only) - set(CHECK_NAMES))):
        parser.error(f"unknown check(s): {', '.join(unknown)}")

    results = run_checks(args.repo.resolve(), only, strict=args.strict)
    width = max(len(r.name) for r in results)
    for r in results:
        print(f"{r.name.ljust(width)}  {r.status:6}  {r.summary}")
        for status, line in r.lines:
            print(f"{' ' * width}    {status.lower():6}  {line}")
    tally = Counter(r.status for r in results)
    mode_name = "strict" if args.strict else "report" if args.report else "default"
    print(f"\n{len(results)} checks: {tally[PASS]} PASS, {tally[TARGET]} TARGET, {tally[FAIL]} FAIL (mode: {mode_name})")
    return 0 if args.report or not tally[FAIL] else 1


if __name__ == "__main__":
    sys.exit(main())
