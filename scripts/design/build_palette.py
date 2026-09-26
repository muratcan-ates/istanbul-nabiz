#!/usr/bin/env python3
"""Every colour of the Nabız palette: written in OKLCH, converted to the sRGB hex that ships, checked.

One source of truth for colour (docs/design/DESIGN.md §2 and §3). Nothing in
``src/nabiz/web/static/css/tokens.css`` is typed by hand: this script turns the OKLCH values below
into the palette's colour blocks, ``build_final_tokens.py`` adds the role aliases and the non-colour
tokens, and ``verify_tokens.py`` re-measures the file that ships. The numbers are the design stage's,
unchanged; its review pages (preview, palette tables, the audit of the old stylesheet) stay outside
the repository, so only the part that produces and checks tokens is here.

Usage::

    .venv/bin/python scripts/design/build_palette.py            # the checks; exit 1 on a failed pair
    .venv/bin/python scripts/design/build_palette.py --css PATH # also write the palette-stage CSS

Standard library only (``colorlib.py`` beside it). No network.
"""

from __future__ import annotations

import argparse
import itertools
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from colorlib import contrast, de, hex_to_oklch, hex_to_rgb, hsl_saturation, oklch_to_hex, simulate  # noqa: E402

# ============================================================================ 1. anchors
# Measured 2026-09-23. The primary hue is not a taste call: every İBB web blue sampled
# (ibb.istanbul blue-600..900, iett.istanbul #1d428a / #102657) sits between OKLCH 259.3 and 263.4
# degrees. The Nabız primary is fixed at 260.
H_PRIMARY = 260.0
# Analogous accent: ibb.istanbul's own cyan (blue-400 / blue-500) sits at 221.2-223.0 degrees,
# 38 degrees from the navy. Same step, same direction, so the pairing is İBB's, the values are ours.
H_ACCENT = 222.0
H_MOMENT = 352.8
H_MOMENT_DARK = 348.9
MOMENT_LIGHT = (0.497, 0.169, H_MOMENT)
MOMENT_DARK = (0.742, 0.124, H_MOMENT_DARK)
MOMENT_SUBTLE_LIGHT = (0.965, 0.018, H_MOMENT)
MOMENT_SUBTLE_DARK = (0.280, 0.040, H_MOMENT_DARK)

# ============================================================================ 2. ramps (OKLCH)
STEPS = (50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950)

# Lightness is equal-step in OKLab (0.075 per step from 950 to 100): OKLab L is built to be
# perceptually uniform, so equal L steps read as equal visual steps. 50 is a compressed tint step.
# The grid is placed so step 500 lands at L 0.620, the lightest a mid tone can sit and still make
# 3:1 as a graphic on every light surface (a first pass at 0.635 missed the sunken surface).
L_RAMP = {50: 0.965, 100: 0.920, 200: 0.845, 300: 0.770, 400: 0.695, 500: 0.620,
          600: 0.545, 700: 0.470, 800: 0.395, 900: 0.320, 950: 0.245}

# Chroma peaks mid-ramp and tapers at both ends, the shape the sRGB gamut allows for blue anyway.
# The peak (0.150) matches ibb.istanbul blue-600 (#2157ad, C 0.149): as vivid as İBB, not more.
C_PRIMARY = {50: 0.014, 100: 0.030, 200: 0.055, 300: 0.085, 400: 0.115, 500: 0.140,
             600: 0.150, 700: 0.145, 800: 0.130, 900: 0.110, 950: 0.085}

# The accent is quieter than İBB's cyan (#00afd9 is C 0.130 at HSL-S 100%): capped so the fill
# step stays under 80% HSL saturation while still reading as cyan.
C_ACCENT = {50: 0.018, 100: 0.035, 200: 0.060, 300: 0.085, 400: 0.100, 500: 0.100,
            600: 0.090, 700: 0.076, 800: 0.066, 900: 0.056, 950: 0.046}

# Cool neutral: same hue as the primary, low chroma, so greys are "blue ink on paper", never warm.
# Light end anchored on ibb.istanbul slate-50 / slate-100 (#fbfcfe L .991, #f4f7fc L .975 C .007).
# The dark end carries more chroma (0.040) so the dark theme is deep navy, not charcoal.
NEUTRAL = {  # step: (L, C)
    0: (0.992, 0.003), 50: (0.975, 0.007), 100: (0.950, 0.010), 200: (0.910, 0.014),
    300: (0.850, 0.018), 400: (0.730, 0.024), 500: (0.620, 0.028), 600: (0.525, 0.031),
    700: (0.445, 0.034), 800: (0.360, 0.036), 900: (0.280, 0.038), 950: (0.235, 0.040),
    975: (0.200, 0.040), 1000: (0.170, 0.038),
}

# ============================================================================ 3. semantic hues
# Status colours. Hues sit away from the brand blue and from each other; lightness is staggered so
# ok / warn / bad stay apart for red-green colour blindness too (ok is a bluish green on purpose:
# the Okabe-Ito trick, bluish green maps to blue-grey for protan/deutan, red and amber to brown).
STATUS = {
    # name: (light text L, C, h), (dark text L, C, h), light wash (L, C), dark wash (L, C)
    # light: warn sits at the lightest L that still makes 4.5:1 on its wash; bad is pushed darker
    # (0.43) so warn/bad stay apart for deuteranopia (7.9 -> 10.9 dE2000 when bad went .46 -> .43).
    # dark: ok is lifted to 0.86 so the cyan accent (0.695) and ok never meet for tritanopia.
    "ok": ((0.500, 0.110, 162.0), (0.860, 0.120, 165.0), (0.955, 0.030), (0.265, 0.045)),
    "warn": ((0.530, 0.115, 70.0), (0.830, 0.130, 75.0), (0.960, 0.035), (0.270, 0.045)),
    "bad": ((0.430, 0.155, 25.0), (0.700, 0.150, 25.0), (0.955, 0.025), (0.265, 0.055)),
}

# AQI bands: chosen by the design stage's search (maximise the smallest CIEDE2000 distance over
# normal, protan, deutan and tritan vision inside hue/lightness windows that keep the standard meaning).
AQI_KEYS = ("good", "moderate", "unhealthy_sensitive", "unhealthy", "very_unhealthy", "hazardous")
AQI_TR = {"good": "İyi", "moderate": "Orta", "unhealthy_sensitive": "Hassas gruplar için sağlıksız",
          "unhealthy": "Sağlıksız", "very_unhealthy": "Kötü", "hazardous": "Tehlikeli"}
AQI_LIGHT = {
    "good": (0.690, 0.103, 166.0),
    "moderate": (0.890, 0.157, 100.0),
    "unhealthy_sensitive": (0.680, 0.157, 48.0),
    "unhealthy": (0.490, 0.169, 26.0),
    "very_unhealthy": (0.450, 0.157, 318.0),
    "hazardous": (0.310, 0.105, 14.0),
}
AQI_DARK = {
    "good": (0.770, 0.153, 158.0),
    "moderate": (0.910, 0.163, 104.0),
    "unhealthy_sensitive": (0.720, 0.157, 52.0),
    "unhealthy": (0.580, 0.190, 26.0),
    "very_unhealthy": (0.560, 0.190, 318.0),
    "hazardous": (0.460, 0.133, 8.0),
}

# Metro İstanbul line colours, exactly as the operator publishes them (not tuned: riders know them).
# Source: inline `background-color: rgb(...)` on www.metro.istanbul (home + /Hatlarimiz/TumHatlarimiz),
# read 2026-09-23. M7 also matches the GetServiceStatuses payload recorded in tests/fixtures/.
LINES_OFFICIAL = {
    "M1A": "#ee3124", "M1B": "#ee3124", "M2": "#009944", "M3": "#00a8e1", "M4": "#e91e76",
    "M5": "#683064", "M6": "#caa977", "M7": "#f89aba", "M8": "#447abe", "M9": "#f0e514",
    "T1": "#004f7d", "T3": "#a86528", "T4": "#f47e46", "T5": "#7c72b3",
    "TF1": "#68bcb0", "TF2": "#68bcb0", "F1": "#7c7358", "F4": "#7c7358",
}
# Not a Metro İstanbul line, so not on its site: community value from Wikipedia's
# Module:Adjacent stations/Istanbul Metro. Marked approximate in the CSS comment.
LINES_COMMUNITY = {"M11": "#a1609b"}

VISIONS = ("normal", "protanopia", "deuteranopia", "tritanopia")


# ============================================================================ build
def ok(L: float, C: float, h: float) -> str:  # noqa: N803 - the colour science names
    return oklch_to_hex(L, C, h)[0]


def build_ramps() -> dict[str, dict]:
    ramps: dict[str, dict] = {"primary": {}, "accent": {}, "neutral": {}}
    for s in STEPS:
        for name, cmap, h in (("primary", C_PRIMARY, H_PRIMARY), ("accent", C_ACCENT, H_ACCENT)):
            hx, used = oklch_to_hex(L_RAMP[s], cmap[s], h)
            ramps[name][s] = {"hex": hx, "L": L_RAMP[s], "C": round(used, 4), "h": h, "clipped": used < cmap[s] - 1e-4}
    for s, (L, C) in NEUTRAL.items():  # noqa: N806
        hx, used = oklch_to_hex(L, C, H_PRIMARY)
        ramps["neutral"][s] = {"hex": hx, "L": L, "C": round(used, 4), "h": H_PRIMARY, "clipped": used < C - 1e-4}
    return ramps


def themes(r: dict) -> dict[str, dict[str, str]]:
    P = {s: r["primary"][s]["hex"] for s in STEPS}  # noqa: N806
    A = {s: r["accent"][s]["hex"] for s in STEPS}  # noqa: N806
    N = {s: v["hex"] for s, v in r["neutral"].items()}  # noqa: N806
    ink_dark = N[1000]
    light = {
        # surfaces: page is İBB-slate off-white, cards a touch lighter, wells a touch darker
        "surface": N[50], "surface-raised": N[0], "surface-sunken": N[100], "surface-inverse": N[950],
        "border": N[200], "border-strong": N[500],
        "text": N[950], "text-muted": N[700], "text-subtle": N[600], "text-inverse": N[50],
        "primary": P[700], "primary-hover": P[800], "primary-active": P[900], "on-primary": N[0],
        "primary-subtle": P[50], "primary-subtle-hover": P[100], "on-primary-subtle": P[800],
        "link": P[700], "link-hover": P[800],
        "accent": A[500], "accent-strong": A[700], "accent-subtle": A[50], "on-accent": ink_dark,
        "focus-ring": A[600],
        "moment": ok(*MOMENT_LIGHT), "moment-subtle": ok(*MOMENT_SUBTLE_LIGHT),
        "info": P[700], "info-wash": P[50],
    }
    dark = {
        "surface": N[975], "surface-raised": N[950], "surface-sunken": N[1000], "surface-inverse": N[50],
        "border": N[800], "border-strong": N[500],
        "text": N[50], "text-muted": N[300], "text-subtle": N[400], "text-inverse": N[950],
        "primary": P[500], "primary-hover": P[400], "primary-active": P[300], "on-primary": ink_dark,
        "primary-subtle": P[950], "primary-subtle-hover": P[900], "on-primary-subtle": P[200],
        "link": P[300], "link-hover": P[200],
        # accent one step below the ring and 0.075 L above the primary fill (tritan separation)
        "accent": A[400], "accent-strong": A[300], "accent-subtle": A[950], "on-accent": ink_dark,
        "focus-ring": A[300],
        "moment": ok(*MOMENT_DARK), "moment-subtle": ok(*MOMENT_SUBTLE_DARK),
        "info": P[300], "info-wash": P[950],
    }
    for name, (lt, dk, lw, dw) in STATUS.items():
        light[name] = ok(*lt)
        light[f"{name}-wash"] = ok(lw[0], lw[1], lt[2])
        dark[name] = ok(*dk)
        dark[f"{name}-wash"] = ok(dw[0], dw[1], dk[2])
    add_aqi(light, AQI_LIGHT, ink_dark, N[0], dark=False)
    add_aqi(dark, AQI_DARK, ink_dark, N[0], dark=True)
    return {"light": light, "dark": dark}


def add_aqi(theme: dict[str, str], spec: dict, ink_dark: str, ink_light: str, dark: bool) -> None:
    for k in AQI_KEYS:
        fill = ok(*spec[k])
        theme[f"aqi-{k}"] = fill
        # chip label: whichever of the two extreme neutrals reads better on the fill
        theme[f"aqi-{k}-ink"] = ink_dark if contrast(ink_dark, fill) >= contrast(ink_light, fill) else ink_light
        theme[f"aqi-{k}-text"] = aqi_text(spec[k], theme["surface"], theme["surface-raised"], theme["surface-sunken"], dark=dark)


def aqi_text(lch: tuple[float, float, float], *bgs: str, dark: bool) -> str:
    """Band colour usable as text / as the edge of a chip or gauge arc: same hue, lightness walked
    until it reaches 4.5:1 on every surface. Darker in light theme, lighter in dark theme."""
    L, C, h = lch  # noqa: N806
    step = 0.005 if dark else -0.005
    for _ in range(200):
        hx = ok(L, C, h)
        if all(contrast(hx, b) >= 4.5 for b in bgs):
            return hx
        L = min(0.98, max(0.05, L + step))  # noqa: N806
    raise RuntimeError(f"no text variant for {lch}")


def line_tokens(ink_dark: str, ink_light: str) -> dict[str, dict]:
    out = {}
    for name, fill in {**LINES_OFFICIAL, **LINES_COMMUNITY}.items():
        cd, cl = contrast(ink_dark, fill), contrast(ink_light, fill)
        out[name] = {"fill": fill, "ink": ink_dark if cd >= cl else ink_light, "ratio": round(max(cd, cl), 2),
                     "official": name in LINES_OFFICIAL}
    return out


# ============================================================================ checks
TEXT, LARGE, UI = 4.5, 3.0, 3.0
SURFACES = ("surface", "surface-raised", "surface-sunken")
Pair = tuple[str, str, str, float, str]


def pairs_for(t: dict[str, str]) -> list[Pair]:
    """(label, fg token, bg token, minimum, kind) for every pairing the UI actually renders.

    ``t`` is unused: the list depends on token names only, which is why verify_tokens.py can pass ``{}``.
    """
    return _text_pairs() + _control_pairs() + _status_pairs()


def _text_pairs() -> list[Pair]:
    out = [(f"{fg} on {bg}", fg, bg, TEXT, "text") for fg in ("text", "text-muted", "text-subtle")
           for bg in (*SURFACES, "primary-subtle")]
    for w in ("ok-wash", "warn-wash", "bad-wash", "info-wash", "accent-subtle"):
        out.append((f"text on {w} (callout body)", "text", w, TEXT, "text"))
        out.append((f"text-muted on {w}", "text-muted", w, TEXT, "text"))
    for bg in SURFACES:
        out.append((f"link on {bg}", "link", bg, TEXT, "text"))
        out.append((f"link-hover on {bg}", "link-hover", bg, TEXT, "text"))
    return out


def _control_pairs() -> list[Pair]:
    out = [(f"on-primary on {bg} (button label)", "on-primary", bg, TEXT, "text")
           for bg in ("primary", "primary-hover", "primary-active")]
    out.append(("on-primary-subtle on primary-subtle (selected chip)", "on-primary-subtle", "primary-subtle", TEXT, "text"))
    out.append(("on-primary-subtle on primary-subtle-hover", "on-primary-subtle", "primary-subtle-hover", TEXT, "text"))
    for bg in SURFACES:
        out.append((f"primary fill vs {bg} (button shape)", "primary", bg, UI, "ui"))
        out.append((f"border-strong vs {bg} (input / chip edge)", "border-strong", bg, UI, "ui"))
        out.append((f"focus-ring vs {bg}", "focus-ring", bg, UI, "ui"))
        out.append((f"accent vs {bg} (live pulse, highlight stroke)", "accent", bg, UI, "ui"))
        out.append((f"accent-strong on {bg} (accent text / icon)", "accent-strong", bg, TEXT, "text"))
    out.append(("on-accent on accent (label on accent fill)", "on-accent", "accent", TEXT, "text"))
    out.append(("focus-ring vs primary (ring touching a button)", "focus-ring", "primary", UI, "ui-advisory"))
    return out


def _status_pairs() -> list[Pair]:
    out = [(f"{st} on {bg}", st, bg, TEXT, "text") for st in ("ok", "warn", "bad", "info") for bg in (*SURFACES, f"{st}-wash")]
    for k in AQI_KEYS:
        out.append((f"aqi-{k}-ink on aqi-{k} (chip label)", f"aqi-{k}-ink", f"aqi-{k}", TEXT, "text"))
        out += [(f"aqi-{k}-text on {bg} (band as text / edge)", f"aqi-{k}-text", bg, TEXT, "text") for bg in SURFACES]
        out.append((f"aqi-{k} fill vs surface-raised (gauge arc, marker)", f"aqi-{k}", "surface-raised", UI, "ui-edge"))
    return out


def run_checks(th: dict[str, dict[str, str]]) -> list[dict]:
    rows = []
    for name, t in th.items():
        for label, fg, bg, need, kind in pairs_for(t):
            r = contrast(t[fg], t[bg])
            rows.append({"theme": name, "pair": label, "fg": t[fg], "bg": t[bg], "ratio": round(r, 2),
                         "need": need, "kind": kind, "pass": r >= need})
    return rows


def cvd_sets(th: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    sets = {}
    for name, t in th.items():
        sets[f"AQI bands ({name})"] = {k: t[f"aqi-{k}"] for k in AQI_KEYS}
        sets[f"status text ({name})"] = {k: t[k] for k in ("ok", "warn", "bad", "info")}
        sets[f"live vs status ({name})"] = {"accent": t["accent"], "primary": t["primary"], "ok": t["ok"], "bad": t["bad"]}
    return sets


def cvd_report(sets: dict[str, dict[str, str]]) -> list[dict]:
    """Per set and vision, the closest pair after Machado simulation, in CIEDE2000."""
    rows = []
    for set_name, cols in sets.items():
        for v in VISIONS:
            sim = {k: simulate(c, v) for k, c in cols.items()}
            worst = min(((de(sim[a], sim[b]), a, b) for a, b in itertools.combinations(cols, 2)), key=lambda x: x[0])
            rows.append({"set": set_name, "vision": v, "min_de2000": round(worst[0], 2), "closest": f"{worst[1]} / {worst[2]}"})
    return rows


# ============================================================================ emit
CSS_HEADER = """/* Nabız colour tokens.
 *
 * A native-CSS token system, labelled honestly: not Fluent, not Material, not an İBB asset.
 * The app is vanilla HTML/CSS/JS with no build step and a map, i.e. product UI; a design-system
 * package would bring a component runtime this page does not use. So the system is these custom
 * properties plus the verification script that generated them (build_palette.py).
 *
 * Colour theory, in four lines:
 *  - Base hue 260 (OKLCH): every İBB web blue measured sits at 259-263 degrees. Palette is
 *    inspired by İBB, identity is Nabız: no logo, no emblem, no İBB red.
 *  - Ramps step evenly in OKLab lightness (0.075 per step), so 400 -> 500 looks as far as 700 -> 800.
 *  - Neutrals share hue 260 at low chroma: cool blue-ink greys, never warm.
 *  - ONE accent, analogous at 222 degrees (38 degrees from the base, the same step İBB pairs its
 *    navy with its cyan). It carries "live / focus / attention" through lightness, not hue
 *    opposition, so it reads alive without the alarm that warm complements carry; warm hues stay
 *    reserved for warn, bad and the AQI scale.
 *
 * Every value is sRGB hex (what was contrast-checked); the OKLCH it came from is in the comment.
 * Light is the default look. Dark = deep navy, never black. No #000000, no #ffffff anywhere.
 */"""


def fmt_lch(hx: str) -> str:
    L, C, h = hex_to_oklch(hx)  # noqa: N806
    return f"oklch({L:.3f} {C:.3f} {h:.1f})"


def emit_css(r: dict, th: dict, lines: dict) -> str:
    out: list[str] = [CSS_HEADER, "", ":root {", "  color-scheme: light;", "", "  /* ---- ramps (theme-independent) ---- */"]
    w = out.append
    for ramp, label in (("primary", "primary: İBB-blue family, h 260"), ("accent", "accent: analogous cyan, h 222"),
                        ("neutral", "neutral: cool slate, h 260, low chroma")):
        w(f"  /* {label} */")
        for s, v in r[ramp].items():
            note = " (gamut-clipped)" if v["clipped"] else ""
            w(f"  --{ramp}-{s}: {v['hex']}; /* oklch({v['L']:.3f} {v['C']:.3f} {v['h']:.0f}){note} */")
        w("")
    w("  /* Metro İstanbul line colours, official values from metro.istanbul (read 2026-09-23).")
    w("     Fixed meaning: never tuned. -ink is the label colour with the higher contrast; lines whose")
    w("     best ink is under 4.5:1 must use the large-text badge (>= 18.66px bold) or the outline badge. */")
    for name, v in lines.items():
        flag = "" if v["official"] else " approximate: community value (Wikipedia), not published by Metro İstanbul"
        small = "" if v["ratio"] >= 4.5 else " large-text or outline badge only"
        w(f"  --line-{name}: {v['fill']};{' /*' + flag + ' */' if flag else ''}")
        w(f"  --line-{name}-ink: {v['ink']}; /* {v['ratio']:.2f}:1{';' + small if small else ''} */")
    w(f"  --line-unknown: {r['neutral'][600]['hex']};")
    w(f"  --line-unknown-ink: {r['neutral'][0]['hex']};")
    w("")
    w("  /* ---- semantic tokens: light theme (default) ---- */")
    emit_semantic(w, th["light"], r, "light")
    w("}")
    w("")
    w("/* Dark theme, reachable two ways that must agree: the OS setting (unless the user forced light)")
    w("   and the manual toggle, which sets data-theme on <html>. */")
    w("@media (prefers-color-scheme: dark) {")
    w('  :root:not([data-theme="light"]) {')
    w("    color-scheme: dark;")
    emit_semantic(lambda s: w("  " + s if s else s), th["dark"], r, "dark")
    w("  }")
    w("}")
    w("")
    w(':root[data-theme="dark"] {')
    w("  color-scheme: dark;")
    emit_semantic(w, th["dark"], r, "dark")
    w("}")
    w("")
    return "\n".join(out)


GROUPS = [
    ("surfaces", ["surface", "surface-raised", "surface-sunken", "surface-inverse", "border", "border-strong"]),
    ("text", ["text", "text-muted", "text-subtle", "text-inverse"]),
    ("primary (actions, links, selected state)", ["primary", "primary-hover", "primary-active", "on-primary",
                                                  "primary-subtle", "primary-subtle-hover", "on-primary-subtle",
                                                  "link", "link-hover"]),
    ("accent: the one accent. live pulse, focus, highlight stroke. Never body text; use accent-strong",
     ["accent", "accent-strong", "accent-subtle", "on-accent", "focus-ring"]),
    ("moment: tulip event colour, restricted to NABIZ-DILI.md §3.5",
     ["moment", "moment-subtle"]),
    ("status: text/icon colour + tinted wash. Always paired with an icon and a word, never colour alone",
     ["ok", "ok-wash", "warn", "warn-wash", "bad", "bad-wash", "info", "info-wash"]),
]


def emit_semantic(w, t: dict[str, str], r: dict, theme: str) -> None:  # noqa: ANN001 - list.append or a wrapper of it
    rev: dict[str, str] = {}
    for ramp in ("primary", "accent", "neutral"):
        for s, v in r[ramp].items():
            rev.setdefault(v["hex"], f"{ramp}-{s}")
    for title, keys in GROUPS:
        w(f"  /* {title} */")
        for k in keys:
            ref = rev.get(t[k])
            w(f"  --{k}: {('var(--' + ref + ')') if ref else t[k]};" + ("" if ref else f" /* {fmt_lch(t[k])} */"))
        w("")
    w("  /* air quality: standard band meaning (green > yellow > orange > red > purple > maroon),")
    w("     lightness tuned for contrast and colour-blind separation. aqi-X = fill (chip, gauge arc,")
    w("     marker); -ink = label on the fill; -text = the band as text, and the 1px edge a fill needs")
    w("     when it is under 3:1 against the surface. */")
    for k in AQI_KEYS:
        w(f"  --aqi-{k}: {t[f'aqi-{k}']}; /* {AQI_TR[k]}, {fmt_lch(t[f'aqi-{k}'])} */")
        w(f"  --aqi-{k}-ink: {t[f'aqi-{k}-ink']};")
        w(f"  --aqi-{k}-text: {t[f'aqi-{k}-text']};")
    w("")
    w("  /* map marker kinds: a glyph carries the kind; colour is a second cue, not the only one.")
    w("     Theme-independent (markers sit on map tiles); the ring keeps them off any tile colour. */")
    rev = {v["hex"]: f"{ramp}-{s}" for ramp in ("primary", "neutral") for s, v in r[ramp].items()}
    for k, v in kind_tokens(r).items():
        w(f"  --kind-{k}: var(--{rev[v]});")
    w("  --kind-selected: var(--focus-ring);")
    w("  --marker-ring: var(--neutral-0);")
    w("")
    w("  /* elevation: shadows tinted with the navy ink, never pure black */")
    for k, v in shadow_tokens(r, theme).items():
        w(f"  --{k}: {v};")


def kind_tokens(r: dict) -> dict[str, str]:
    """Marker fills. Markers sit on map tiles, not on the page surface, so they are the same in both
    themes and always carry a --marker-ring. Steps chosen by a small search for the largest
    colour-blind separation inside the blue family: kind reads as a lightness ladder
    (place 0.245 < bus 0.395 < station 0.620 < park 0.695 < air 0.850), which survives every CVD type.
    Air markers normally take the reading's --aqi-* fill; --kind-air is the no-reading fallback.
    A line-specific station marker takes that line's --line-* colour."""
    P = {s: r["primary"][s]["hex"] for s in STEPS}  # noqa: N806
    N = {s: v["hex"] for s, v in r["neutral"].items()}  # noqa: N806
    return {"park": P[400], "bus": P[800], "station": N[500], "place": N[950], "air": N[300]}


def shadow_tokens(r: dict, theme: str) -> dict[str, str]:
    if theme == "light":
        rgb = " ".join(str(int(round(x * 255))) for x in hex_to_rgb(r["neutral"][950]["hex"]))
        return {"shadow-1": f"0 1px 2px rgb({rgb} / .06)",
                "shadow-2": f"0 1px 2px rgb({rgb} / .06), 0 8px 24px -12px rgb({rgb} / .20)",
                "shadow-3": f"0 2px 6px rgb({rgb} / .08), 0 24px 48px -20px rgb({rgb} / .30)"}
    rgb = " ".join(str(int(round(x * 255))) for x in hex_to_rgb(ok(0.12, 0.03, H_PRIMARY)))
    return {"shadow-1": f"0 1px 2px rgb({rgb} / .55)",
            "shadow-2": f"0 1px 2px rgb({rgb} / .55), 0 10px 26px -12px rgb({rgb} / .75)",
            "shadow-3": f"0 2px 8px rgb({rgb} / .60), 0 24px 50px -22px rgb({rgb} / .85)"}


def palette() -> tuple[dict, dict, dict]:
    """Ramps, the two themes and the line badges: everything the CSS is written from."""
    r = build_ramps()
    return r, themes(r), line_tokens(r["neutral"][1000]["hex"], r["neutral"][0]["hex"])


def palette_css() -> str:
    """The palette stage's tokens.css, the input of build_final_tokens.py."""
    return emit_css(*palette())


def report(th: dict, checks: list[dict]) -> list[str]:
    """The palette's own failures (a required pair under its threshold, pure black or white), and a summary."""
    required = [c for c in checks if c["kind"] in ("text", "ui")]
    fails = [c for c in required if not c["pass"]]
    banned = [(k, v) for t in th.values() for k, v in t.items() if v.lower() in ("#000000", "#ffffff")]
    print(f"required contrast pairs: {len(required) - len(fails)}/{len(required)} pass")
    for c in fails:
        print(f"  FAIL [{c['theme']}] {c['pair']}: {c['ratio']:.2f} < {c['need']}  ({c['fg']} on {c['bg']})")
    edge = [(c["theme"], c["pair"].split()[0]) for c in checks if c["kind"] == "ui-edge" and not c["pass"]]
    print(f"AQI fills under 3:1 vs raised surface (edge required): {edge}")
    accent_s = {n: round(hsl_saturation(t["accent"]) * 100, 1) for n, t in th.items()}
    print(f"accent HSL saturation %: {accent_s}   pure black/white found: {banned or 'none'}")
    worst: dict[str, float] = {}
    for row in cvd_report(cvd_sets(th)):
        worst[row["set"]] = min(worst.get(row["set"], 99.0), row["min_de2000"])
    for s, v in worst.items():
        print(f"  CVD {s}: min dE2000 across visions = {v:.1f}")
    return [c["pair"] for c in fails] + [k for k, _ in banned]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--css", type=pathlib.Path, help="also write the palette-stage CSS here")
    args = parser.parse_args(argv)
    r, th, lines = palette()
    if args.css:
        args.css.write_text(emit_css(r, th, lines), encoding="utf-8")
        print(f"wrote {args.css}")
    return 1 if report(th, run_checks(th)) else 0


if __name__ == "__main__":
    sys.exit(main())
