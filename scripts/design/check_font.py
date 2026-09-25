#!/usr/bin/env python3
"""Coverage gate for the page's web font (``static/fonts/nabiz-sans-tr-v1.woff2``).

Checks the file that ships, not the script that built it:

* every character in ``build_font_subset.CODEPOINTS`` has a glyph in the cmap, the 12 Turkish
  letters and ``₺ µ ³ ₂ ₃ °`` included, so the browser never falls back to a second face for one
  character (the rule is one face, never "TL" or "NO2");
* the figures are tabular: the ten digits share one advance at every weight the page uses, read
  from ``hmtx`` at 400, 600 and 700. Tabular by default counts, and so does a ``tnum`` feature, but
  then the substituted glyphs are the ones measured. Source Sans 3 has no ``tnum`` and needs none;
* the weight axis is exactly the range the stylesheets use, 400 to 700;
* no name the font presents itself by carries "Source", the Reserved Font Name of its licence;
* the file is woff2 and inside the page's font budget (60 KB, ``check_web_budget.py``).

Usage (fontTools and brotli are needed to read woff2; they are build tools, not project dependencies)::

    /tmp/fontenv/bin/python scripts/design/check_font.py [FONT]

Exit 1 on any failure. No network.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from build_font_subset import AXIS, CODEPOINTS, OUT, SYMBOLS, TURKISH, WEIGHTS, fonttools  # noqa: E402

BUDGET = 60_000
DIGITS = "0123456789"
PRESENTED_NAMES = (1, 3, 4, 6, 16, 17, 25)


def digit_glyphs(font) -> list[str]:  # noqa: ANN001
    """The digit glyphs the browser draws: the cmap's, or tnum's substitutes when the font has tnum."""
    cmap = font.getBestCmap()
    glyphs = [cmap[ord(d)] for d in DIGITS]
    gsub = font["GSUB"].table if "GSUB" in font else None
    if gsub is None or not gsub.FeatureList:
        return glyphs
    for record in gsub.FeatureList.FeatureRecord:
        if record.FeatureTag != "tnum":
            continue
        for index in record.Feature.LookupListIndex:
            for sub in gsub.LookupList.Lookup[index].SubTable:
                mapping = getattr(sub, "mapping", {})
                glyphs = [mapping.get(g, g) for g in glyphs]
    return glyphs


def digit_advances(font) -> dict[int, set[int]]:  # noqa: ANN001
    """The set of digit advances at each weight; one member per set means tabular."""
    _, _, instancer = fonttools()
    out = {}
    for weight in WEIGHTS:
        static = instancer.instantiateVariableFont(font, {"wght": weight})
        out[weight] = {static["hmtx"][g][0] for g in digit_glyphs(static)}
    return out


def problems(path: pathlib.Path) -> list[str]:
    _, TTFont, _ = fonttools()  # noqa: N806
    font = TTFont(path)
    found = []
    if font.flavor != "woff2":
        found.append(f"flavor is {font.flavor!r}, not woff2")
    if (size := path.stat().st_size) > BUDGET:
        found.append(f"{size:,} B is over the {BUDGET:,} B font budget")
    cmap = font.getBestCmap()
    missing = [cp for cp in CODEPOINTS if cp not in cmap]
    found += [f"no glyph for U+{cp:04X} {chr(cp)!r}" for cp in missing]
    axis = next((a for a in font["fvar"].axes if a.axisTag == "wght"), None) if "fvar" in font else None
    if axis is None or (axis.minValue, axis.defaultValue, axis.maxValue) != AXIS:
        found.append(f"wght axis is {axis and (axis.minValue, axis.defaultValue, axis.maxValue)}, want {AXIS}")
        return found  # the advances below need the axis
    widths = digit_advances(font)
    found += [f"digits at {w} have {len(a)} advances {sorted(a)}: not tabular" for w, a in widths.items() if len(a) != 1]
    found += [f"name {r.nameID} carries the Reserved Font Name: {r.toUnicode()!r}" for r in font["name"].names
              if r.nameID in PRESENTED_NAMES and "source" in r.toUnicode().lower()]
    print(f"{path.name}: {size:,} B, {len(font.getGlyphOrder())} glyphs, {len(cmap)} characters, "
          f"wght {axis.minValue:g}..{axis.maxValue:g} (default {axis.defaultValue:g})")
    print(f"  Turkish {TURKISH} and {SYMBOLS}: {'all present' if not missing else 'MISSING some'}")
    tnum = "has tnum" if digit_glyphs(font) != [cmap[ord(d)] for d in DIGITS] else "no tnum feature (none needed)"
    print(f"  digit advance per weight: {', '.join(f'{w}: {sorted(a)}' for w, a in widths.items())} units; {tnum}")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("font", type=pathlib.Path, nargs="?", default=OUT)
    args = parser.parse_args(argv)
    found = problems(args.font)
    for problem in found:
        print("  FAIL", problem)
    print("font check:", "FAIL" if found else "PASS")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
