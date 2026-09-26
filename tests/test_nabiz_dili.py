"""Static contracts for the shared Nabız Dili layer and component skeletons."""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC = REPO_ROOT / "src" / "nabiz" / "console" / "static"
BASE = STATIC / "css" / "base.css"
COMPONENTS = STATIC / "css" / "components.css"
TOKENS = STATIC / "css" / "tokens.css"
DASHES = (chr(0x2014), chr(0x2013))


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def css_block(css: str, selector: str) -> str:
    """Return a selector's block with nested braces counted, as in the static CSS contracts."""
    match = re.search(re.escape(selector) + r"\s*\{", css)
    assert match, f"missing CSS selector: {selector}"
    start = match.end()
    depth = 1
    for pos in range(start, len(css)):
        if css[pos] == "{":
            depth += 1
        elif css[pos] == "}":
            depth -= 1
            if depth == 0:
                return css[start:pos]
    raise AssertionError(f"unclosed CSS block: {selector}")


def motion_guard_blocks(css: str) -> list[tuple[int, int]]:
    """Find complete no-preference media blocks, including their nested selector blocks."""
    spans = []
    for match in re.finditer(r"@media\s*\(prefers-reduced-motion:\s*no-preference\)\s*\{", css):
        depth = 1
        for pos in range(match.end(), len(css)):
            if css[pos] == "{":
                depth += 1
            elif css[pos] == "}":
                depth -= 1
                if depth == 0:
                    spans.append((match.start(), pos + 1))
                    break
        else:
            raise AssertionError("unclosed reduced-motion media block")
    return spans


def visible_html(html: str) -> str:
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    return re.sub(r'<svg class="sprite".*?</svg>', "", html, flags=re.S)


def json_strings(value: object):
    if isinstance(value, dict):
        for item in value.values():
            yield from json_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from json_strings(item)
    elif isinstance(value, str):
        yield value


def test_the_language_layer_names_every_fluent_value() -> None:
    css = read(BASE)
    expected = {
        "radius-medium": "4px", "radius-xlarge": "8px", "radius-2xlarge": "12px",
        "radius-3xlarge": "16px", "radius-circular": "10000px",
        "spacing-xxs": "2px", "spacing-xs": "4px", "spacing-s-nudge": "6px", "spacing-s": "8px",
        "spacing-m-nudge": "10px", "spacing-m": "12px", "spacing-l": "16px", "spacing-xl": "20px",
        "spacing-xxl": "24px", "spacing-xxxl": "32px",
        "font-size-200": "12px", "font-size-300": "14px", "font-size-400": "16px",
        "font-size-500": "20px", "font-size-600": "24px", "font-size-hero-700": "28px",
        "font-size-hero-800": "32px", "font-size-hero-900": "40px",
        "line-height-200": "16px", "line-height-300": "20px", "line-height-400": "22px",
        "line-height-500": "28px", "line-height-600": "32px", "line-height-hero-700": "36px",
        "line-height-hero-800": "40px", "line-height-hero-900": "52px",
        "duration-faster": "100ms", "duration-fast": "150ms", "duration-normal": "200ms",
        "duration-gentle": "250ms", "duration-slow": "300ms",
        "curve-decelerate-max": "cubic-bezier(0.1, 0.9, 0.2, 1)",
        "curve-decelerate-mid": "cubic-bezier(0, 0, 0, 1)",
        "curve-accelerate-mid": "cubic-bezier(1, 0, 1, 1)",
        "curve-easy-ease": "cubic-bezier(0.33, 0, 0.67, 1)",
        "stroke-thin": "1px", "stroke-thick": "2px",
    }
    for name, value in expected.items():
        assert re.search(rf"--fluent-{re.escape(name)}\s*:\s*{re.escape(value)}\s*;", css), name
    for marker in ("@fluentui/tokens", "MIT", "Fluent bileşeni değildir"):
        assert marker in css
    for alias in (
        "--nd-accent", "--nd-accent-hover", "--nd-accent-ink", "--nd-secondary-ink", "--nd-secondary-wash",
        "--nd-moment", "--nd-glow", "--nd-glass", "--nd-hero-wash", "--nd-line", "--nd-line-strong",
        "--nd-radius-control", "--nd-radius-surface", "--nd-radius-composer", "--nd-dur-press", "--nd-dur-hover",
        "--nd-dur-state", "--nd-dur-enter", "--nd-ease-enter", "--nd-ease-state", "--nd-ease-exit",
        "--nd-hero-size", "--nd-hero-leading", "--nd-eyebrow-size", "--nd-measure-chat",
    ):
        assert re.search(rf"{re.escape(alias)}\s*:", css), alias


def test_the_language_layer_holds_no_colour_literal() -> None:
    for path in (BASE, COMPONENTS):
        css = read(path)
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgb\s*\(|\bhsl\s*\(|\boklch\s*\(", css), path
        assert css.count("color-mix(") == css.count(", transparent)"), path


def test_role_radii_match_the_existing_tokens() -> None:
    base = read(BASE)
    tokens = read(TOKENS)
    for alias, fluent, pixels in (
        ("--nd-radius-control", "--fluent-radius-xlarge", "8px"),
        ("--nd-radius-surface", "--fluent-radius-2xlarge", "12px"),
        ("--nd-radius-composer", "--fluent-radius-3xlarge", "16px"),
    ):
        assert re.search(rf"{re.escape(alias)}\s*:\s*var\({re.escape(fluent)}\)", base)
        assert re.search(rf"{re.escape(fluent)}\s*:\s*{re.escape(pixels)}", base)
    assert re.search(r"--radius-control\s*:\s*8px", tokens)
    assert re.search(r"--radius-surface\s*:\s*12px", tokens)


def test_every_animation_is_guarded() -> None:
    for path in (BASE, COMPONENTS):
        css = read(path)
        spans = motion_guard_blocks(css)
        for start, end in reversed(spans):
            css = css[:start] + css[end:]
        assert not re.search(r"\b(?:animation|transition)\s*:", css), path


def test_no_infinite_decoration() -> None:
    for path in (BASE, COMPONENTS):
        css = read(path)
        for selector, declarations in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
            if re.search(r"\banimation\s*:[^;]*\binfinite\b", declarations):
                selector = selector.strip()
                assert '.btn[aria-busy="true"]' in selector or ".icon-btn.spin" in selector, selector
    assert re.search(r"\.fresh\.is-beat\s+\.fresh-dot\s*\{[^}]*animation:[^;]*\s1\s*;", read(COMPONENTS))


def test_button_states_are_defined() -> None:
    base = read(BASE)
    assert ".btn-quiet {" in base
    disabled = css_block(base, '.btn[aria-disabled="true"]')
    assert "opacity: 1" in disabled
    assert '.btn[aria-busy="true"]::after' in base
    busy_ring = css_block(base, '.btn[aria-busy="true"]::after')
    assert "position: static" in busy_ring and "display: inline-block" in busy_ring
    assert '.btn[aria-busy="true"] > .icon' in base
    assert ":focus-visible { outline: 2px solid var(--focus-ring); outline-offset: 2px; }" in base
    assert '.btn-primary:not([aria-disabled="true"]):hover' in base
    assert '.btn:not([aria-disabled="true"]):active' in base


def test_the_pulse_is_blue_not_red() -> None:
    dot = css_block(read(COMPONENTS), ".fresh-dot")
    assert "background: var(--nd-accent)" in dot or "background: var(--link)" in dot
    assert "width: 8px" in dot and "height: 8px" in dot
    assert not any(token in dot for token in ("--bad", "--ok", "--warn", "--moment"))


def test_eyebrow_is_not_uppercase() -> None:
    assert not re.search(r"text-transform\s*:\s*uppercase", read(COMPONENTS), flags=re.I)


def test_glass_has_every_fallback() -> None:
    components = read(COMPONENTS)
    no_support = css_block(components, "@supports not (backdrop-filter: blur(1px))")
    reduced_transparency = css_block(components, "@media (prefers-reduced-transparency: reduce)")
    more_contrast = css_block(components, ':root[data-contrast="more"] .glass')
    assert "background: var(--surface-raised)" in css_block(no_support, ".glass")
    assert "background: var(--surface-raised)" in css_block(reduced_transparency, ".glass")
    assert "backdrop-filter: none" in css_block(reduced_transparency, ".glass")
    assert "background: var(--surface-raised)" in more_contrast
    assert "backdrop-filter: none" in more_contrast


def test_no_dash_in_any_visible_copy() -> None:
    paths = (
        *STATIC.glob("*.html"), *STATIC.glob("js/*.js"), *STATIC.glob("css/*.css"), *STATIC.glob("mock/*.json"),
        REPO_ROOT / "data/knowledge/quick_questions.json", REPO_ROOT / "src/nabiz/agent/selamlar.toml",
    )
    for path in paths:
        text = read(path)
        if path.suffix == ".html":
            text = visible_html(text)
        assert not any(dash in text for dash in DASHES), path
    for language in ("tr", "en"):
        values = json_strings(json.loads(read(STATIC / "i18n" / f"{language}.json")))
        assert all(not any(dash in value for dash in DASHES) for value in values), language


def test_the_moment_colour_is_generated_not_typed() -> None:
    source = read(REPO_ROOT / "scripts/design/build_palette.py")
    assert "H_MOMENT = 352.8" in source
    assert "H_MOMENT_DARK = 348.9" in source
    assert "#a52a6b" not in source.lower() and "#e58ab8" not in source.lower()
    assert "--nd-moment: var(--moment, var(--accent))" in read(BASE)
    for path in (TOKENS, REPO_ROOT / "src/nabiz/web/static/css/tokens.css"):
        css = read(path)
        assert "--moment:" in css and "--moment-subtle:" in css
    assert re.search(r"--moment:\s*#a52a6b", read(TOKENS))
    assert re.search(r"--moment:\s*#e58ab8", read(TOKENS))


def test_state_colours_and_the_chevron_hold_without_motion() -> None:
    """Reduced motion removes movement only: hover colours and the open chevron stay outside the guard."""
    base = read(BASE)
    guarded = "".join(base[start:end] for start, end in motion_guard_blocks(base))
    outside = base
    for start, end in reversed(motion_guard_blocks(base)):
        outside = outside[:start] + outside[end:]
    assert "[open] > summary > .icon { transform: rotate(90deg); }" in outside
    assert ".btn:hover, .icon-btn:hover { background: var(--surface-sunken)" in outside
    assert "background: var(--nd-accent-hover)" in css_block(outside, ".btn-primary:hover")
    assert not re.search(r"(?:^|[;{\s])background\s*:", "".join(re.findall(r"\{([^{}]*)\}", guarded)))
    # The guard never raises specificity, so page stylesheets still win over .btn as before.
    assert ":root:not(" not in guarded.replace(":where(:root:not(", "")
