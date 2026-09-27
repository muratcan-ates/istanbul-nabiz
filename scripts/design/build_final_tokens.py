#!/usr/bin/env python3
"""Write ``static/css/tokens.css`` and its annotated review copy from the palette.

Input: the palette's colour blocks, built in memory by ``build_palette.py`` (every colour there is
generated from OKLCH and contrast-checked by that script). This script never types a hex value. It
only:

1. replaces the palette's file header with the served one,
2. injects the non-colour tokens and the role aliases (docs/design/DESIGN.md §3) into the light
   ``:root`` block, and the dark role aliases into BOTH dark blocks (the OS-dark media block and the
   ``data-theme="dark"`` block) from ONE list, so the two dark blocks cannot drift.

``verify_tokens.py`` then parses the written files on its own and measures every pair. The served
file drops the per-line OKLCH comments so it fits its byte cap (16 KB raw, 4 KB gzip:
``scripts/check_web_budget.py``); the annotated copy keeps them.

Usage::

    .venv/bin/python scripts/design/build_final_tokens.py && .venv/bin/python scripts/design/verify_tokens.py
    .venv/bin/python scripts/design/build_final_tokens.py --out DIR   # write both files into DIR instead
    .venv/bin/python scripts/design/build_final_tokens.py --check     # exit 1 if the committed files differ

Standard library only. No network.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from build_palette import palette_css  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
SERVED = ROOT / "src/nabiz/web/static/css/tokens.css"
ANNOTATED = ROOT / "docs/design/tokens.annotated.css"

HEADER = """/* Nabız tokens: the project's own native-CSS token system (docs/design/DESIGN.md §3).
 *
 * Honest label: not Fluent, not Material, not Carbon, not an İBB asset. The page is vanilla
 * HTML/CSS/JS with no build step, so the design system is these custom properties plus the
 * scripts that generate and verify them (scripts/design/build_palette.py for every colour value,
 * scripts/design/build_final_tokens.py for the aliases and non-colour tokens,
 * scripts/design/verify_tokens.py for the contrast table).
 *
 * Colour theory, in five lines:
 *  - Base hue 246 (OKLCH): restrained civic blue inspired by the İBB portal. These values are
 *    Nabız's own: no logo, no emblem and no official partnership claim.
 *  - Ramps step evenly in OKLab lightness (0.075 per step), so 400 -> 500 looks as far as 700 -> 800.
 *  - Neutrals share hue 246 at very low chroma: near-white light surfaces and slate dark surfaces.
 *  - Firuze at 210 degrees is an analogous supporting accent, 36 degrees from the blue.
 *    The separate tulip moment colour (h 352.8 light, 348.9 dark) is restricted to NABIZ-DILI.md §3.5.
 *  - Lightness encodes quantity (the pulse line's pen pressure); hue encodes only categories a
 *    source defines (Metro line colours, AQI bands). Warm hues are reserved for warn, bad and AQI.
 *
 * Rules for whoever uses this file:
 *  - This is the ONLY file in static/ allowed to contain a colour literal (check_web_budget.py tokens).
 *  - Every value is sRGB hex, the value that was contrast-checked; its OKLCH source is in the
 *    annotated copy. This file is generated: edit the scripts, never this file by hand. It is
 *    exempt from the 350-line CSS cap and capped by bytes instead (check_web_budget.py).
 *  - Light is the default. Dark = near-neutral slate. No #000000 and no #ffffff anywhere.
 *  - Role aliases below point at ramp steps; they add no new colour.
 */"""

# ---------------------------------------------------------------- non-colour tokens (theme-free)
NON_COLOUR = """
  /* ==== Final spec additions: non-colour tokens (theme-independent) ==== */
  /* type: platform-native system face; 8 sizes, 3 weights; no font request for the interface */
  --font-sans: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  --text-xs: .75rem;     /* 12: chart axis labels and legends only, never sentences */
  --text-sm: .875rem;    /* 14: stamps, meta, helper, table cells; the smallest size a data age may use */
  --text-md: 1rem;       /* 16: body, input text (16 avoids iOS zoom) */
  --text-lg: 1.1875rem;  /* 19: row titles, hero subtext, line badges at 700 (WCAG large text >= 18.66px bold) */
  --text-xl: 1.375rem;   /* 22: h2 result heads, band word */
  --text-2xl: 1.75rem;   /* 28: the one metric per row */
  --text-3xl: 2.25rem;   /* 36: hero readout under 768 px */
  --text-4xl: 3rem;      /* 48: hero readout, h1 upper bound */
  --text-display: clamp(2rem, 1.2rem + 2.6vw, 3rem); /* h1 only: 32 px at 390, 48 px at 1440 */
  --weight-regular: 400; --weight-semibold: 600; --weight-bold: 700;
  --leading-tight: 1.08; --leading-snug: 1.3; --leading-body: 1.5;
  --measure: 65ch;

  /* space: 4 px base, 8 steps */
  --space-1: .25rem; --space-2: .5rem; --space-3: .75rem; --space-4: 1rem;
  --space-5: 1.5rem; --space-6: 2rem; --space-7: 3rem; --space-8: 4rem;

  /* shape lock: surfaces 12, controls and labels 8, round only for dots,
     markers, roundels and the live dot. Nothing else is rounded. */
  --radius-control: 8px; --radius-surface: 12px; --radius-round: 999px;

  /* layout; breakpoints (not expressible as custom properties): 640, 768, 1024, 1280 */
  --maxw: 80rem; --gutter: var(--space-5); --topbar-h: 64px; --tap: 44px;

  /* motion: transform, opacity and stroke-dashoffset only; everything gated by reduced motion */
  --ease-out: cubic-bezier(.16, 1, .3, 1);
  --ease-in-out: cubic-bezier(.65, 0, .35, 1);
  --dur-press: 120ms; --dur-ui: 200ms; --dur-enter: 320ms; --dur-advance: 600ms;
  --dur-draw: 1400ms; --dur-breathe: 2400ms; --stagger: 40ms;

  /* drawing: one pen for icons and data ("tek kalem") */
  --stroke-pen: 1.75px; --stroke-guide: 1px; --stroke-occupancy: 4px;
  --icon-size: 20px; --icon-size-sm: 16px; --icon-stroke: 2; /* 2 of 24 units = 1.67 px at 20 px */

  /* layers: the whole z-index scale */
  --z-map-marker: 3; --z-sticky: 10; --z-topbar: 40; --z-popover: 50; --z-skip: 60;
"""

# ---------------------------------------------------------------- role aliases
#: (name, light value, dark value or None when the light alias already resolves correctly in dark
#: because it points at a semantic token that the dark block switches, why)
ROLES = [
    # signature: Nabız çizgisi (pen line from /api/traffic?window=24h)
    ("pulse-ink-low", "var(--primary-600)", "var(--primary-300)", "pen ink at index 1"),
    ("pulse-ink-high", "var(--primary-900)", "var(--primary-100)", "pen ink at index 99 (pressure ramp)"),
    ("pulse-ink-archive", "var(--neutral-500)", "var(--neutral-400)", "line older than 24 h, model inputs"),
    ("chart-guide", "var(--border)", None, "threshold hairlines; decorative, words carry meaning"),
    ("chart-ref", "var(--border-strong)", None, "yesterday rule, age gap, scale hairline, ruler axis"),
    ("chart-now", "var(--accent)", None, 'the one "latest current reading" mark per drawing'),
    ("chart-halo", "var(--surface)", None, "knockout ring; components on a sheet set it to --surface-raised"),
    ("chart-best", "var(--primary)", None, "best forecast hour ring"),
    ("live-dot", "var(--accent)", None, "status pill dot, rings once per successful poll"),
    ("occupancy-ink", "var(--primary)", None, "4 px occupancy stroke over a 1 px scale hairline"),
    # route ribbons (Leg.kind): style differs by dash pattern too, colour is the second cue
    ("route-foot", "var(--neutral-500)", "var(--neutral-400)", "walk, wait, transfer, park legs"),
    ("route-transit", "var(--primary-600)", "var(--primary-400)", "rail and bus legs"),
    ("route-drive", "var(--primary-800)", "var(--primary-200)", "drive and delay legs"),
    # line badges (Metro fills come from --line-X / API colour; bus lines use this role)
    ("badge-bus", "var(--primary-800)", "var(--primary-400)", "bus line badge fill (500T)"),
    ("badge-bus-ink", "var(--neutral-0)", "var(--neutral-1000)", "bus line badge code"),
    ("line-casing", "var(--border-strong)", None, "1 px casing on every line-colour fill"),
    # map markers (fills are the palette's theme-independent --kind-X; glyph ink per fill)
    ("kind-park-ink", "var(--neutral-1000)", None, "glyph on --kind-park"),
    ("kind-bus-ink", "var(--neutral-0)", None, "glyph on --kind-bus"),
    ("kind-station-ink", "var(--neutral-1000)", None, "glyph on --kind-station"),
    ("kind-place-ink", "var(--neutral-0)", None, "glyph on --kind-place"),
    ("kind-air-ink", "var(--neutral-1000)", None, "glyph on --kind-air (fallback when no AQI band)"),
    ("marker-edge", "var(--primary-900)", None, "1 px outer edge outside the 2 px --marker-ring"),
    ("map-wash", "var(--neutral-100)", "var(--neutral-975)", "MapLibre background layer under calmed tiles"),
    # surfaces and states
    ("sheet-bg", "var(--surface-raised)", None, "the one raised answer sheet"),
    ("skeleton", "var(--surface-sunken)", None, "loading blocks (opacity pulse only)"),
    ("selected-row", "var(--accent-subtle)", None, "row focused from a map marker (fades out)"),
    ("topbar-bg", "var(--surface)", None, "opaque topbar, 1 px --border bottom edge, no blur"),
]
BANNED = ("#000000", "#ffffff", "#000;", "#fff;")


def inject(block_text: str, addition: str) -> str:
    """Insert ``addition`` before the final closing brace of a CSS block body."""
    idx = block_text.rstrip().rfind("}")
    return block_text[:idx].rstrip() + "\n" + addition.rstrip() + "\n" + block_text[idx:]


def dark_roles(indent: str) -> str:
    dark_list = [(n, dv, why) for n, _lv, dv, why in ROLES if dv]
    return (f"\n{indent}/* ==== Final spec additions: dark role aliases (same list for both dark blocks) ==== */\n"
            + "\n".join(f"{indent}--{n}: {dv}; /* {why} */" for n, dv, why in dark_list))


def splice(css: str, pattern: str, indent: str) -> str:
    """Append the dark role aliases to the dark block ``pattern`` matches (groups: open, body, close)."""
    m = re.search(pattern, css, flags=re.S | re.M)
    if not m:
        raise SystemExit(f"block not found: {pattern}")
    return css[: m.start()] + m.group(1) + m.group(2).rstrip() + "\n" + dark_roles(indent) + "\n" + m.group(3) + css[m.end() :]


def annotated_css(palette: str) -> str:
    """The palette plus header, non-colour tokens and role aliases, with every OKLCH comment kept."""
    css = re.sub(r"\A/\*.*?\*/", lambda _m: HEADER, palette, count=1, flags=re.S)
    light_roles = "\n  /* ==== Final spec additions: role aliases (light; no new hex) ==== */\n" + "\n".join(
        f"  --{n}: {lv}; /* {why} */" for n, lv, _dv, why in ROLES
    )
    m = re.search(r"^:root \{\n.*?^\}\n", css, flags=re.S | re.M)
    if not m:
        raise SystemExit("light :root block not found")
    css = css[: m.start()] + inject(m.group(0), NON_COLOUR + light_roles) + css[m.end() :]
    css = splice(css, r'(  :root:not\(\[data-theme="light"\]\) \{\n)(.*?)(^  \}\n)', "    ")
    css = splice(css, r'(^:root\[data-theme="dark"\] \{\n)(.*?)(^\}\n)', "  ")
    css = css.rstrip() + "\n\n@media (max-width: 767px) {\n  :root { --gutter: var(--space-4); --topbar-h: 56px; }\n}\n"
    code = re.sub(r"/\*.*?\*/", "", css, flags=re.S).lower()  # comments may name the banned values
    for bad in BANNED:
        if bad in code:
            raise SystemExit(f"banned literal {bad} found")
    return css


#: The served file's header. The long one (colour theory, the rules) stays in the annotated copy:
#: every phone downloads this file, and that header was about a fifth of its gzip bytes (the same
#: declarations under it: 3,659 B gzip -9; under this one: 2,850 B; measured 2026-09-23).
SERVED_HEADER = """/* Nabız tokens, generated by scripts/design/build_final_tokens.py: edit the scripts, never this file.
 * The only file in static/ with colour literals. Rules and the OKLCH source of every value:
 * docs/design/tokens.annotated.css. */"""


def served_css(annotated: str) -> str:
    """The same declarations with a short header and the per-line comments dropped."""
    header_end = annotated.index("*/") + 2
    body = annotated[header_end:]
    body = re.sub(r";[ \t]*/\*[^\n]*?\*/", ";", body)  # trailing comment after a declaration
    body = re.sub(r"\n[ \t]*/\*.*?\*/[ \t]*(?=\n)", lambda m: m.group(0) if "====" in m.group(0) else "", body, flags=re.S)
    body = re.sub(r"[ \t]+\n", "\n", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    return SERVED_HEADER + body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--out", type=pathlib.Path, help="write tokens.css and tokens.annotated.css into this directory")
    parser.add_argument("--check", action="store_true", help="write nothing; exit 1 if the committed files differ")
    args = parser.parse_args(argv)
    served_path, annotated_path = (
        (args.out / SERVED.name, args.out / ANNOTATED.name) if args.out else (SERVED, ANNOTATED)
    )
    annotated = annotated_css(palette_css())
    served = served_css(annotated)
    if args.check:
        # A hand edit of the generated file, or a script change nobody re-ran, shows up here.
        stale = [p.name for p, text in ((annotated_path, annotated), (served_path, served))
                 if not p.is_file() or p.read_text(encoding="utf-8") != text]
        print("token files match the scripts" if not stale else f"differs from the scripts: {', '.join(stale)}")
        return 1 if stale else 0
    for path, text in ((annotated_path, annotated), (served_path, served)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path.name}: {len(text.encode())} bytes, {text.count(chr(10))} lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
