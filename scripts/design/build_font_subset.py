#!/usr/bin/env python3
"""Build the page's one web font: a Turkish subset of Source Sans 3, and its fallback face's metrics.

The owner chose Source Sans 3 (SIL Open Font License 1.1) on 2026-09-23 because it has every glyph
the page prints: Turkish letters, ₺ for tariffs, µ and ³ for µg/m³, the subscripts of NO₂ and O₃, and
its figures are tabular and lining by default (docs/design/DESIGN.md §4). One face, never mixed with
another, and never "TL" or "NO2" as a fallback.

What this does, and why each step is there:

* **Weight axis cut to 400..700**, default 400. The page uses 400, 600 and 700; the source file's
  axis runs 200..900 with its default at 200, which a browser without variable-font support would
  draw as ExtraLight.
* **Subset** to the characters in ``CODEPOINTS`` (every character the page and the server's display
  strings print, counted on 2026-09-23) and the layout features a browser applies by default.
* **Renamed** to "Nabiz Sans TR" in the name table. "Source" is a Reserved Font Name in the font's
  licence, and a subset is a Modified Version, which the OFL forbids to carry a Reserved Font Name.
  The copyright, trademark and licence records are kept as they are.
* **Fallback metrics.** The page shows text in a local fallback face until the web font arrives
  (``font-display: swap``). ``size-adjust`` and the three metric overrides make that face take the
  same space, so the swap moves nothing (CLS). They are computed from the subset's own tables and the
  fallback font's advance widths over ``SAMPLE`` (Turkish text the page prints), never guessed, and
  written into ``static/css/base.css`` between ``/* fallback-metrics:start */`` and ``:end */``.

Input: google/fonts ``ofl/sourcesans3/SourceSans3[wght].ttf`` at commit
4591e3457ab8be6d70167aa6818922b91e78ab2d (646,340 B, git blob d259aa494fe7117141a2752a998a52c172bbd42b,
version 3.052); the licence beside it is ``static/fonts/OFL.txt``, the same commit's ``OFL.txt`` (git blob
50ee76cf00fbfe42fb7c74a9b95c9508dec5bb8f) with its CRLF line endings turned into LF.

Usage (fontTools and brotli are build tools, not project dependencies: use a throwaway venv)::

    python3 -m venv /tmp/fontenv && /tmp/fontenv/bin/pip install fonttools brotli
    /tmp/fontenv/bin/python scripts/design/build_font_subset.py 'SourceSans3[wght].ttf' \\
        --fallback Arial.ttf --fallback-bold 'Arial Bold.ttf'
    /tmp/fontenv/bin/python scripts/design/check_font.py

No network.
"""

from __future__ import annotations

import argparse
import io
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "src/nabiz/web/static/fonts/nabiz-sans-tr-v1.woff2"
BASE_CSS = ROOT / "src/nabiz/web/static/css/base.css"
FAMILY = "Nabiz Sans TR"
POSTSCRIPT = "NabizSansTR"
AXIS = (400, 400, 700)  # (min, default, max) of wght: the weights the stylesheets use
WEIGHTS = (400, 600, 700)

TURKISH = "ÇçĞğİıÖöŞşÜü"
#: Glyphs the page prints that a Latin font may lack: tariffs, µg/m³, NO₂, O₃, degrees.
SYMBOLS = "₺µ³₂₃°"
#: What the page and the server's display strings print (counted over src/ on 2026-09-23): ASCII,
#: Latin-1 (Ç Ö Ü, µ ³ ° ·), the six Turkish letters outside it, quotes, the ellipsis, dashes (the
#: charter's attribution line keeps an em dash), the arrow and ≈ in route and reliability
#: sentences, ₺, the minus sign and the subscript digits. Left out on purpose: ↗ ▲ ▼ ■, which the
#: old renderers print as icons until step 7 replaces them with Tabler glyphs (spec §6); every
#: other character outside this list sits in a code comment.
CODEPOINTS = (
    *range(0x20, 0x7F), *range(0xA0, 0x100), 0x11E, 0x11F, 0x130, 0x131, 0x15E, 0x15F,
    0x2013, 0x2014, 0x2018, 0x2019, 0x201C, 0x201D, 0x2026, 0x2192, 0x2212, 0x2248, 0x20BA, *range(0x2080, 0x208A),
)
#: The layout features a browser turns on by default. The figures need no tnum: they are tabular by
#: default in this family (check_font.py measures it).
FEATURES = ("ccmp", "locl", "mark", "mkmk", "kern", "liga")
#: Name records kept: copyright, the names this script rewrites, version, trademark, licence.
NAME_IDS = (0, 1, 2, 3, 4, 5, 6, 7, 13, 14, 25)
#: Turkish text the page prints (the hero, the helper, a stamp, the disclaimer), for average widths.
SAMPLE = (
    "Şehrin verisi, yaşıyla birlikte. Otopark, otobüs, metro, trafik ve hava kalitesi, doğrudan İBB açık "
    "veri uçlarından. Her kart, gördüğünüz sayının ne zaman ölçüldüğünü söyler. Soru kutusu anahtar kelime "
    "eşlemesi yapar. Bu sayfada dil modeli yoktur; her yanıt doğrudan İBB uçlarından gelir. ölçüm 14 gün "
    "önce. Bağımsız öğrenci projesi. İBB, İETT, İSPARK ve Metro İstanbul ile bağlantısı yoktur."
)
MARKERS = ("/* fallback-metrics:start */", "/* fallback-metrics:end */")


def fonttools():  # noqa: ANN201 - the modules, imported late so --help works without them
    try:
        from fontTools import subset
        from fontTools.ttLib import TTFont
        from fontTools.varLib import instancer
    except ImportError:
        raise SystemExit("needs fontTools and brotli: pip install fonttools brotli (in a throwaway venv)") from None
    return subset, TTFont, instancer


def build(source: pathlib.Path):  # noqa: ANN201 - a fontTools TTFont
    subset, TTFont, instancer = fonttools()  # noqa: N806
    limited = io.BytesIO()
    instancer.instantiateVariableFont(TTFont(source, recalcTimestamp=False), {"wght": AXIS}).save(limited)
    # Reloaded from bytes: subsetting the instancer's in-memory result fails on its lazily loaded
    # gvar (fontTools 4.65.0, KeyError on a glyph with no deltas); a saved copy subsets cleanly.
    # The source's own timestamp is kept, so the same input builds the same bytes.
    limited.seek(0)
    font = TTFont(limited, recalcTimestamp=False)
    options = subset.Options()
    options.layout_features = list(FEATURES)
    options.name_IDs = list(NAME_IDS)
    subsetter = subset.Subsetter(options)
    subsetter.populate(unicodes=CODEPOINTS)
    subsetter.subset(font)
    rename(font, version=f"{font['head'].fontRevision:.3f}")
    font.flavor = "woff2"  # what save() writes; the subsetter's own flavor option is only read by pyftsubset
    return font


def rename(font, version: str) -> None:  # noqa: ANN001
    """Drop the Reserved Font Name from every name the font presents itself by."""
    names = font["name"]
    for name_id, value in ((1, FAMILY), (2, "Regular"), (3, f"{FAMILY};{version};nabiz-sans-tr-v1"), (4, FAMILY),
                           (6, f"{POSTSCRIPT}-Regular"), (25, POSTSCRIPT)):
        names.removeNames(nameID=name_id)
        names.setName(value, name_id, 3, 1, 0x409)
    names.removeNames(nameID=16)
    names.removeNames(nameID=17)
    for instance in font["fvar"].instances:
        instance.postscriptNameID = 0xFFFF


def average_width(font, text: str, weight: int) -> float:  # noqa: ANN001
    """Mean advance per character of ``text`` at ``weight``, in em."""
    _, _, instancer = fonttools()
    if "fvar" in font:
        font = instancer.instantiateVariableFont(font, {"wght": weight})
    cmap, hmtx, upm = font.getBestCmap(), font["hmtx"], font["head"].unitsPerEm
    return sum(hmtx[cmap[ord(ch)]][0] for ch in text) / len(text) / upm


def overrides(font, fallback: pathlib.Path, weight: int) -> dict[str, float]:  # noqa: ANN001
    """size-adjust and the metric overrides that make ``fallback`` occupy the web font's space."""
    _, TTFont, _ = fonttools()  # noqa: N806
    size_adjust = average_width(font, SAMPLE, weight) / average_width(TTFont(fallback), SAMPLE, weight)
    hhea, upm = font["hhea"], font["head"].unitsPerEm
    # The overrides are multiplied by size-adjust in the browser, so they are divided by it here.
    return {
        "size-adjust": size_adjust,
        "ascent-override": hhea.ascent / upm / size_adjust,
        "descent-override": -hhea.descent / upm / size_adjust,
        "line-gap-override": hhea.lineGap / upm / size_adjust,
    }


#: Arial by its full and PostScript names (Safari matches the latter), then Liberation Sans and Arimo,
#: which are metric-compatible with it, so the same overrides hold on Linux.
FALLBACK_SOURCES = {
    400: 'local("Arial"), local("ArialMT"), local("Liberation Sans"), local("Arimo")',
    700: 'local("Arial Bold"), local("Arial-BoldMT"), local("Liberation Sans Bold"), local("Arimo Bold")',
}


def fallback_css(regular: dict[str, float], bold: dict[str, float] | None) -> str:
    faces = [(400, FALLBACK_SOURCES[400], regular)]
    if bold:
        faces.append((700, FALLBACK_SOURCES[700], bold))
    out = [MARKERS[0]]
    for weight, src, values in faces:
        out.append(f'@font-face {{ font-family: "Nabız Sans Fallback"; font-weight: {weight}; font-display: swap; src: {src};')
        out.append("  " + " ".join(f"{k}: {v * 100:.2f}%;" for k, v in values.items()) + " }")
    out.append(MARKERS[1])
    return "\n".join(out)


def write_fallback(css_path: pathlib.Path, block: str) -> None:
    text = css_path.read_text(encoding="utf-8")
    pattern = re.escape(MARKERS[0]) + r".*?" + re.escape(MARKERS[1])
    if not re.search(pattern, text, flags=re.S):
        raise SystemExit(f"{css_path.name} has no {MARKERS[0]} ... {MARKERS[1]} block")
    css_path.write_text(re.sub(pattern, lambda _m: block, text, count=1, flags=re.S), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("source", type=pathlib.Path, help="SourceSans3[wght].ttf from google/fonts")
    parser.add_argument("--out", type=pathlib.Path, default=OUT)
    parser.add_argument("--fallback", type=pathlib.Path, help="Arial regular (or a metric-compatible face)")
    parser.add_argument("--fallback-bold", type=pathlib.Path, help="Arial bold, for the 700 fallback face")
    parser.add_argument("--css", type=pathlib.Path, default=BASE_CSS, help="stylesheet holding the fallback block")
    args = parser.parse_args(argv)
    font = build(args.source)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    font.save(args.out)
    print(f"wrote {args.out.name}: {args.out.stat().st_size:,} B, {len(font.getGlyphOrder())} glyphs")
    if args.fallback:
        _, TTFont, _ = fonttools()  # noqa: N806
        built = TTFont(args.out)
        bold = overrides(built, args.fallback_bold, 700) if args.fallback_bold else None
        block = fallback_css(overrides(built, args.fallback, 400), bold)
        write_fallback(args.css, block)
        print(block)
    return 0


if __name__ == "__main__":
    sys.exit(main())
