#!/usr/bin/env python3
"""Verify ``static/css/tokens.css``: parse it, resolve every custom property per theme, measure every pair.

Independent of ``build_final_tokens.py``: it reads the files that ship, not the script's variables.

1. Parses the served ``tokens.css`` and the review copy ``docs/design/tokens.annotated.css`` and asserts
   they resolve to identical values in light, OS-dark and ``data-theme="dark"``.
2. Asserts the OS-dark block and the ``data-theme="dark"`` block resolve identically (they cannot drift).
3. Re-runs the palette's own required pair list (``build_palette.pairs_for``) against the resolved
   values: the 178 palette pairs.
4. Measures every pair the design adds (signature, age ruler, route ribbons, badges, markers).
5. Colour-vision separation (Machado 2009, CIEDE2000) for the new sets.
6. Guards: no #000000 / #ffffff outside comments; accent HSL saturation under 80 %.

Usage::

    .venv/bin/python scripts/design/verify_tokens.py               # exit 1 if any required pair fails
    .venv/bin/python scripts/design/verify_tokens.py --report DIR  # also write contrast.md and contrast.json

Standard library only. No network.
"""

from __future__ import annotations

import argparse
import itertools
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import build_palette as bp  # noqa: E402  (the palette's own pair list and constants)
from build_final_tokens import ANNOTATED, SERVED  # noqa: E402
from colorlib import contrast, de, hsl_saturation, simulate  # noqa: E402

TEXT, UI = 4.5, 3.0
DECL = re.compile(r"--([A-Za-z0-9_-]+)\s*:\s*([^;]+);")


def strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def blocks(css: str) -> dict[str, dict[str, str]]:
    """{'base': the first ':root {', 'media': the OS-dark block, 'attr': the data-theme=dark block}."""
    css = strip_comments(css)
    patterns = {
        "base": r"^:root \{(.*?)^\}",
        "media": r'@media \(prefers-color-scheme: dark\) \{\s*:root:not\(\[data-theme="light"\]\) \{(.*?)\n  \}',
        "attr": r'^:root\[data-theme="dark"\] \{(.*?)^\}',
    }
    out = {}
    for name, pattern in patterns.items():
        m = re.search(pattern, css, flags=re.S | re.M)
        if not m:
            raise SystemExit(f"{name} block not found")
        out[name] = dict(DECL.findall(m.group(1)))
    return out


def resolve(decls: dict[str, str]) -> dict[str, str]:
    """Substitute var(--x) recursively (same element, as the browser does on :root)."""

    def val(name: str, depth: int = 0) -> str:
        if depth > 20:
            raise RuntimeError(f"var() cycle at --{name}")
        return re.sub(r"var\(--([A-Za-z0-9_-]+)\)", lambda m: val(m.group(1), depth + 1), decls[name].strip())

    return {k: val(k).strip().lower() if v.strip().startswith(("#", "var(")) else v.strip() for k, v in decls.items()}


def themes_of(css: str) -> dict[str, dict[str, str]]:
    b = blocks(css)
    return {"light": resolve(b["base"]), "dark-media": resolve({**b["base"], **b["media"]}),
            "dark-attr": resolve({**b["base"], **b["attr"]})}


# ------------------------------------------------------------------ pairs the design adds
S = ("surface", "surface-raised")  # where drawings sit: page (hero) and answer sheet
S3 = ("surface", "surface-raised", "surface-sunken")
DRAWN = (("pulse-ink-low", "pen ink, index 1"), ("pulse-ink-high", "pen ink, index 99"),
         ("pulse-ink-archive", "archive line"), ("chart-ref", "yesterday rule / ruler axis"),
         ("chart-now", "now mark"), ("chart-best", "best-hour ring"), ("occupancy-ink", "occupancy stroke"),
         ("route-foot", "walk leg"), ("route-transit", "transit leg"), ("route-drive", "drive leg"),
         ("badge-bus", "bus badge shape"), ("live-dot", "status dot (topbar sits on surface)"))


def added_pairs() -> list[bp.Pair]:
    out = [(f"{fg} vs {bg} ({why})", fg, bg, UI, "ui") for fg, why in DRAWN for bg in S]
    out.append(("badge-bus-ink on badge-bus (bus line code)", "badge-bus-ink", "badge-bus", TEXT, "text"))
    for bg in S3:
        out.append((f"line-casing vs {bg} (casing on line fills)", "line-casing", bg, UI, "ui"))
        out.append((f"text-subtle on {bg} (axis labels 12 px, stamps 14 px)", "text-subtle", bg, TEXT, "text"))
    out += [
        ("text on selected-row (row focused from a marker)", "text", "selected-row", TEXT, "text"),
        ("text-subtle on selected-row (stamp on a selected row)", "text-subtle", "selected-row", TEXT, "text"),
        ("focus-ring vs selected-row", "focus-ring", "selected-row", UI, "ui"),
        ("text-muted on skeleton (loading line over a block)", "text-muted", "skeleton", TEXT, "text"),
        ('text-muted on surface-sunken ("resmî değildir" label)', "text-muted", "surface-sunken", TEXT, "text"),
        ('border-strong vs surface-sunken ("resmî değildir" edge)', "border-strong", "surface-sunken", UI, "ui"),
        ('warn on surface-raised (cached stamp, "neredeyse dolu")', "warn", "surface-raised", TEXT, "text"),
        ("chart-now vs pulse-ink-low (now mark over the line end)", "chart-now", "pulse-ink-low", 1.0, "info"),
        ("pulse-ink-archive vs chart-guide (archive line over a guide)", "pulse-ink-archive", "chart-guide", 1.0, "info"),
    ]
    return out


MARKERS = [("kind-park", "kind-park-ink"), ("kind-bus", "kind-bus-ink"), ("kind-station", "kind-station-ink"),
           ("kind-place", "kind-place-ink"), ("kind-air", "kind-air-ink")]
#: Approximations of calmed raster tiles (NOT measured on real tiles; the browser check decides).
TILE_APPROX = {"light tile (approx. #eceff4)": "#eceff4", "dark tile (approx. #1b2536)": "#1b2536"}


def measure(t: dict[str, str], pairs: list[bp.Pair]) -> list[dict]:
    """One row per pair; ``pass`` is None for the kinds that only inform (edge, advisory, info)."""
    rows = []
    for label, fg, bg, need, kind in pairs:
        r = contrast(t[fg], t[bg])
        rows.append({"pair": label, "fg": t[fg], "bg": t[bg], "ratio": round(r, 2), "need": need, "kind": kind,
                     "pass": (r >= need) if kind in ("text", "ui") else None})
    return rows


def cvd_min(cols: dict[str, str]) -> list[dict]:
    rows = []
    for v in bp.VISIONS:
        sim = {k: simulate(c, v) for k, c in cols.items()}
        worst = min(((de(sim[a], sim[b]), a, b) for a, b in itertools.combinations(cols, 2)), key=lambda x: x[0])
        rows.append({"vision": v, "min_de2000": round(worst[0], 2), "closest": f"{worst[1]} / {worst[2]}"})
    return rows


def structure_problems(th: dict, th_ann: dict, served: str) -> list[str]:
    problems = []
    if th != th_ann:
        problems.append("served and annotated tokens resolve differently")
    if th["dark-media"] != th["dark-attr"]:
        diff = {k for k in th["dark-media"] if th["dark-media"].get(k) != th["dark-attr"].get(k)}
        problems.append(f"dark blocks drift: {sorted(diff)}")
    code = strip_comments(served).lower()
    problems += [f"banned literal {bad}" for bad in ("#000000", "#ffffff") if bad in code]
    return problems


def line_rows(name: str, t: dict[str, str]) -> list[dict]:
    """Metro line badges and the bus badge (fills are theme-independent, casing is not)."""
    rows = []
    for key in sorted(k for k in t if k.startswith("line-") and not k.endswith("-ink") and k != "line-casing"):
        fill, ink = t[key], t[f"{key}-ink"]
        r = contrast(ink, fill)
        rows.append({"theme": name, "line": key[5:], "fill": fill, "ink": ink, "ratio": round(r, 2),
                     "small_text_ok": r >= TEXT, "large_text_ok": r >= UI,
                     "fill_vs_raised": round(contrast(fill, t["surface-raised"]), 2),
                     "casing_vs_raised": round(contrast(t["line-casing"], t["surface-raised"]), 2)})
    return rows


def marker_rows(t: dict[str, str]) -> list[dict]:
    rows = []
    for fill, ink in MARKERS:
        row = {"marker": fill, "fill": t[fill], "glyph_ink": t[ink], "glyph_ratio": round(contrast(t[ink], t[fill]), 2),
               "ring_vs_fill": round(contrast(t["marker-ring"], t[fill]), 2)}
        for tl, hx in TILE_APPROX.items():
            row[f"fill vs {tl}"] = round(contrast(t[fill], hx), 2)
            row[f"edge vs {tl}"] = round(contrast(t["marker-edge"], hx), 2)
            row[f"ring vs {tl}"] = round(contrast(t["marker-ring"], hx), 2)
        rows.append(row)
    return rows


def measure_theme(name: str, t: dict[str, str], report: dict) -> list[str]:
    """Fill ``report`` for one theme; return its failures."""
    problems = []
    rows = {"palette": measure(t, bp.pairs_for({})), "added": measure(t, added_pairs())}
    report["themes"][name] = rows
    for key, found in rows.items():
        required = [r for r in found if r["kind"] in ("text", "ui")]
        report["counts"][f"{key}_required"] += len(required)
        report["counts"][f"{key}_pass"] += sum(1 for r in required if r["pass"])
        problems += [f"[{name}] {r['pair']}: {r['ratio']} < {r['need']}" for r in required if not r["pass"]]
    report["lines"] += line_rows(name, t)
    problems += [f"[{name}] line {r['line']}: ink {r['ratio']:.2f} < 3.0 even as large text" for r in line_rows(name, t)
                 if not r["large_text_ok"]]
    if name == "light":  # markers are theme-independent
        report["markers"] = marker_rows(t)
        weak = [r for r in report["markers"] if r["glyph_ratio"] < UI]
        problems += [f"marker glyph on {r['marker']}: {r['glyph_ratio']:.2f} < 3.0" for r in weak]
    report["cvd"][f"pen ends vs now mark ({name})"] = cvd_min(
        {"ink-low": t["pulse-ink-low"], "ink-high": t["pulse-ink-high"], "now": t["chart-now"]})
    report["cvd"][f"route legs ({name})"] = cvd_min(
        {"foot": t["route-foot"], "transit": t["route-transit"], "drive": t["route-drive"]})
    report["cvd"][f"live vs status ({name})"] = cvd_min(
        {"accent": t["accent"], "primary": t["primary"], "ok": t["ok"], "bad": t["bad"], "warn": t["warn"]})
    return problems


def verify(served: str, annotated: str) -> tuple[dict, dict[str, dict[str, str]]]:
    th, th_ann = themes_of(served), themes_of(annotated)
    final = {"light": th["light"], "dark": th["dark-media"]}
    counts = dict.fromkeys(("palette_required", "palette_pass", "added_required", "added_pass"), 0)
    report: dict = {"themes": {}, "lines": [], "markers": [], "cvd": {}, "counts": counts,
                    "problems": structure_problems(th, th_ann, served)}
    for name, t in final.items():
        report["problems"] += measure_theme(name, t, report)
    report["accent_hsl_saturation_pct"] = sat = {n: round(float(hsl_saturation(final[n]["accent"]) * 100), 1) for n in final}
    if max(sat.values()) >= 80:
        report["problems"].append(f"accent saturation {sat}")
    report["served_equals_annotated"] = th == th_ann
    report["dark_blocks_identical"] = th["dark-media"] == th["dark-attr"]
    return report, final


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--served", type=pathlib.Path, default=SERVED)
    parser.add_argument("--annotated", type=pathlib.Path, default=ANNOTATED)
    parser.add_argument("--report", type=pathlib.Path, help="write contrast.md and contrast.json into this directory")
    args = parser.parse_args(argv)
    report, final = verify(args.served.read_text(encoding="utf-8"), args.annotated.read_text(encoding="utf-8"))
    counts = report["counts"]
    print(f"palette pairs: {counts['palette_pass']}/{counts['palette_required']} pass; "
          f"added pairs: {counts['added_pass']}/{counts['added_required']} pass; "
          f"accent HSL-S {report['accent_hsl_saturation_pct']}")
    print("served == annotated:", report["served_equals_annotated"], "| dark blocks identical:", report["dark_blocks_identical"])
    for p in report["problems"]:
        print("  PROBLEM", p)
    if args.report:
        args.report.mkdir(parents=True, exist_ok=True)
        (args.report / "contrast.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
        (args.report / "contrast.md").write_text(render_md(report), encoding="utf-8")
        print(f"wrote contrast.md and contrast.json into {args.report}")
    return 1 if report["problems"] else 0


def _result(r: dict) -> str:
    if r["pass"] is not None:
        return "pass" if r["pass"] else "**FAIL**"
    if r["kind"] == "ui-edge":
        return "under 3:1: draw the 1 px -text edge" if r["ratio"] < 3 else "pass"
    return "info" if r["kind"] == "info" else "advisory: keep outline-offset 2 px"


def render_md(rep: dict) -> str:
    c = rep["counts"]
    out = ["# Token contrast table (generated by scripts/design/verify_tokens.py)", "",
           f"Result: palette pairs {c['palette_pass']}/{c['palette_required']}, "
           f"added pairs {c['added_pass']}/{c['added_required']}. "
           f"Accent HSL saturation: {rep['accent_hsl_saturation_pct']}. Problems: {rep['problems'] or 'none'}.", ""]
    for name in ("light", "dark"):
        for key, title in (("added", "Pairs the design adds"), ("palette", "Palette pairs")):
            out += [f"## {title}, {name}", "", "| pair | fg | bg | ratio | need | result |", "|---|---|---|---:|---:|---|"]
            out += [f"| {r['pair']} | `{r['fg']}` | `{r['bg']}` | {r['ratio']:.2f} | {r['need']} | {_result(r)} |"
                    for r in rep["themes"][name][key]]
            out.append("")
    out += ["## Line badges (19 px / 700 code = WCAG large text)", "",
            "| theme | line | fill | ink | ink ratio | small text 4.5 | large text 3.0 | fill vs raised | casing vs raised |",
            "|---|---|---|---|---:|---|---|---:|---:|"]
    out += [f"| {r['theme']} | {r['line']} | `{r['fill']}` | `{r['ink']}` | {r['ratio']:.2f} | "
            f"{'yes' if r['small_text_ok'] else 'no'} | {'yes' if r['large_text_ok'] else 'NO'} | "
            f"{r['fill_vs_raised']:.2f} | {r['casing_vs_raised']:.2f} |" for r in rep["lines"]]
    keys = list(rep["markers"][0])
    out += ["", "## Map markers (tile colours are approximations, not measurements)", "",
            "| " + " | ".join(keys) + " |", "|" + "---|" * len(keys)]
    out += ["| " + " | ".join(f"`{v}`" if str(v).startswith("#") else str(v) for v in r.values()) + " |" for r in rep["markers"]]
    out += ["", "## Colour-vision separation (Machado 2009 severity 1.0, CIEDE2000)", "",
            "| set | normal | protanopia | deuteranopia | tritanopia | closest (worst) |", "|---|---:|---:|---:|---:|---|"]
    for s, rows in rep["cvd"].items():
        worst = min(rows, key=lambda x: x["min_de2000"])
        values = " | ".join(f"{r['min_de2000']:.1f}" for r in rows)
        out.append(f"| {s} | {values} | {worst['closest']} ({worst['vision']}) |")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    sys.exit(main())
