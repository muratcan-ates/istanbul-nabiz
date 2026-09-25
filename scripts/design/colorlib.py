"""Small colour maths for the Nabız palette, standard library only.

What lives here, and why each piece is the version it is:

* OKLab / OKLCH <-> sRGB, from Björn Ottosson's published matrices (the same ones CSS Color 4
  uses for ``oklch()``), so a value written here renders identically when pasted into CSS.
* Gamut mapping by chroma reduction at fixed L and h (binary search). This is the simple half of
  the CSS Color 4 algorithm; it keeps lightness exact, which is what contrast depends on.
* WCAG 2.x relative luminance and contrast ratio (the 0.04045 threshold from the sRGB spec;
  WCAG's own text says 0.03928, the difference never changes a rounded ratio).
* Colour-vision-deficiency simulation with the Machado, Oliveira & Fernandes (2009) matrices at
  severity 1.0, applied in linear RGB, as DaltonLens recommends. Machado's tritanopia model is the
  least validated of the three; results for it are indicative, not clinical.
* CIEDE2000 on CIELAB (D65), the usual "can a person tell these apart" distance.

The design stage wrote this with numpy. It is ported to plain floats here so the token scripts run
from the project's own environment with no extra dependency. The port was compared on 2026-09-23
with that stage's saved outputs, which stay outside the repository: ``build_palette.py --css``
writes its palette CSS byte for byte, and the ``contrast.json`` of ``verify_tokens.py --report`` has the
same ratio (to two decimals, as stored), threshold and verdict for all 272 pair rows (96 palette and 40
added pairs per theme) and equal line-badge, marker and colour-vision tables. The Markdown report
differs only in layout (row order, and the threshold cell of information rows).
Inside the repository, ``build_final_tokens.py --check`` holds the committed ``tokens.css`` and its
annotated copy equal to what this code generates (``tests/test_web_design_tokens.py`` runs it).

``python scripts/design/colorlib.py`` runs the self-checks against published reference values.
"""

from __future__ import annotations

import math

Vector = tuple[float, float, float]
Matrix = tuple[Vector, Vector, Vector]


def _mul(m: Matrix, v: Vector) -> Vector:
    return (
        m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
        m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
        m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2],
    )


def _inverse(m: Matrix) -> Matrix:
    """The inverse by cofactors: exact enough for these well-conditioned 3x3 matrices."""
    (a, b, c), (d, e, f), (g, h, i) = m
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    return (
        ((e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det),
        ((f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det),
        ((d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det),
    )


# ----------------------------------------------------------------------------- sRGB transfer


def srgb_to_linear(c: Vector) -> Vector:
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c)  # type: ignore[return-value]


def linear_to_srgb(c: Vector) -> Vector:
    return tuple(12.92 * x if x <= 0.0031308 else 1.055 * max(x, 0.0) ** (1 / 2.4) - 0.055 for x in c)  # type: ignore[return-value]


def hex_to_rgb(h: str) -> Vector:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255)


def rgb_to_hex(rgb: Vector) -> str:
    # round() rounds half to even, as numpy's round does, so the port keeps every hex.
    return "#{:02x}{:02x}{:02x}".format(*(min(255, max(0, int(round(x * 255)))) for x in rgb))


# ----------------------------------------------------------------------------- OKLab (Ottosson)

_M1: Matrix = (
    (0.4122214708, 0.5363325363, 0.0514459929),
    (0.2119034982, 0.6806995451, 0.1073969566),
    (0.0883024619, 0.2817188376, 0.6299787005),
)
_M2: Matrix = (
    (0.2104542553, 0.7936177850, -0.0040720468),
    (1.9779984951, -2.4285922050, 0.4505937099),
    (0.0259040371, 0.7827717662, -0.8086757660),
)
_M1_INV = _inverse(_M1)
_M2_INV = _inverse(_M2)


def linear_to_oklab(rgb: Vector) -> Vector:
    lms = _mul(_M1, rgb)
    return _mul(_M2, (math.cbrt(lms[0]), math.cbrt(lms[1]), math.cbrt(lms[2])))


def oklab_to_linear(lab: Vector) -> Vector:
    lms_ = _mul(_M2_INV, lab)
    return _mul(_M1_INV, (lms_[0] ** 3, lms_[1] ** 3, lms_[2] ** 3))


def oklch_to_oklab(L: float, C: float, h: float) -> Vector:  # noqa: N803 - the colour science names
    r = math.radians(h)
    return (L, C * math.cos(r), C * math.sin(r))


def oklab_to_oklch(lab: Vector) -> tuple[float, float, float]:
    L, a, b = lab  # noqa: N806
    return float(L), float(math.hypot(a, b)), float(math.degrees(math.atan2(b, a)) % 360)


def hex_to_oklch(h: str) -> tuple[float, float, float]:
    return oklab_to_oklch(linear_to_oklab(srgb_to_linear(hex_to_rgb(h))))


def _in_gamut(lin: Vector, eps: float = 1e-6) -> bool:
    return all(-eps <= x <= 1 + eps for x in lin)


def _clip(lin: Vector) -> Vector:
    return (min(1.0, max(0.0, lin[0])), min(1.0, max(0.0, lin[1])), min(1.0, max(0.0, lin[2])))


def oklch_to_hex(L: float, C: float, h: float) -> tuple[str, float]:  # noqa: N803
    """Return (hex, chroma actually used). Out-of-gamut colours lose chroma, never lightness."""
    lin = oklab_to_linear(oklch_to_oklab(L, C, h))
    if _in_gamut(lin):
        return rgb_to_hex(linear_to_srgb(_clip(lin))), C
    lo, hi = 0.0, C
    for _ in range(40):
        mid = (lo + hi) / 2
        if _in_gamut(oklab_to_linear(oklch_to_oklab(L, mid, h))):
            lo = mid
        else:
            hi = mid
    lin = oklab_to_linear(oklch_to_oklab(L, lo, h))
    return rgb_to_hex(linear_to_srgb(_clip(lin))), lo


def max_chroma(L: float, h: float) -> float:  # noqa: N803
    return oklch_to_hex(L, 0.5, h)[1]


# ----------------------------------------------------------------------------- WCAG 2.x


def luminance(hex_: str) -> float:
    r, g, b = srgb_to_linear(hex_to_rgb(hex_))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(fg: str, bg: str) -> float:
    a, b = luminance(fg), luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def composite(fg_hex: str, alpha: float, bg_hex: str) -> str:
    """Alpha-composite in gamma-encoded sRGB, which is what browsers do for rgba()/color-mix(in srgb)."""
    f, b = hex_to_rgb(fg_hex), hex_to_rgb(bg_hex)
    return rgb_to_hex(tuple(x * alpha + y * (1 - alpha) for x, y in zip(f, b, strict=True)))  # type: ignore[arg-type]


def hsl_saturation(hex_: str) -> float:
    r, g, b = hex_to_rgb(hex_)
    mx, mn = max(r, g, b), min(r, g, b)
    lightness = (mx + mn) / 2
    if mx == mn:
        return 0.0
    return (mx - mn) / (1 - abs(2 * lightness - 1))


# ----------------------------------------------------------------------------- CVD (Machado 2009)

MACHADO: dict[str, Matrix] = {
    "protanopia": (
        (0.152286, 1.052583, -0.204868),
        (0.114503, 0.786281, 0.099216),
        (-0.003882, -0.048116, 1.051998),
    ),
    "deuteranopia": (
        (0.367322, 0.860646, -0.227968),
        (0.280085, 0.672501, 0.047413),
        (-0.011820, 0.042940, 0.968881),
    ),
    "tritanopia": (
        (1.255528, -0.076749, -0.178779),
        (-0.078411, 0.930809, 0.147602),
        (0.004733, 0.691367, 0.303900),
    ),
}


def simulate(hex_: str, kind: str) -> str:
    if kind == "normal":
        return hex_
    lin = srgb_to_linear(hex_to_rgb(hex_))
    return rgb_to_hex(linear_to_srgb(_clip(_mul(MACHADO[kind], lin))))


# ----------------------------------------------------------------------------- CIELAB + CIEDE2000

_RGB_TO_XYZ: Matrix = (
    (0.4124564, 0.3575761, 0.1804375),
    (0.2126729, 0.7151522, 0.0721750),
    (0.0193339, 0.1191920, 0.9503041),
)
_WHITE: Vector = (0.95047, 1.0, 1.08883)


def hex_to_lab(hex_: str) -> Vector:
    xyz = _mul(_RGB_TO_XYZ, srgb_to_linear(hex_to_rgb(hex_)))
    d = 6 / 29
    f = [math.cbrt(t) if t > d**3 else t / (3 * d * d) + 4 / 29 for t in (x / w for x, w in zip(xyz, _WHITE, strict=True))]
    return (116 * f[1] - 16, 500 * (f[0] - f[1]), 200 * (f[1] - f[2]))


def delta_e2000(lab1: Vector, lab2: Vector) -> float:  # noqa: PLR0915 - one published formula, kept in one piece
    L1, a1, b1 = lab1  # noqa: N806
    L2, a2, b2 = lab2  # noqa: N806
    C1, C2 = math.hypot(a1, b1), math.hypot(a2, b2)  # noqa: N806
    Cb = (C1 + C2) / 2  # noqa: N806
    G = 0.5 * (1 - math.sqrt(Cb**7 / (Cb**7 + 25**7)))  # noqa: N806
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = math.hypot(a1p, b1), math.hypot(a2p, b2)  # noqa: N806
    h1p = math.degrees(math.atan2(b1, a1p)) % 360 if (a1p or b1) else 0.0
    h2p = math.degrees(math.atan2(b2, a2p)) % 360 if (a2p or b2) else 0.0
    dLp = L2 - L1  # noqa: N806
    dCp = C2p - C1p  # noqa: N806
    if C1p * C2p == 0:
        dhp = 0.0
    elif abs(h2p - h1p) <= 180:
        dhp = h2p - h1p
    elif h2p - h1p > 180:
        dhp = h2p - h1p - 360
    else:
        dhp = h2p - h1p + 360
    dHp = 2 * math.sqrt(C1p * C2p) * math.sin(math.radians(dhp / 2))  # noqa: N806
    Lbp = (L1 + L2) / 2  # noqa: N806
    Cbp = (C1p + C2p) / 2  # noqa: N806
    if C1p * C2p == 0:
        hbp = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hbp = (h1p + h2p) / 2
    elif h1p + h2p < 360:
        hbp = (h1p + h2p + 360) / 2
    else:
        hbp = (h1p + h2p - 360) / 2
    T = (  # noqa: N806
        1
        - 0.17 * math.cos(math.radians(hbp - 30))
        + 0.24 * math.cos(math.radians(2 * hbp))
        + 0.32 * math.cos(math.radians(3 * hbp + 6))
        - 0.20 * math.cos(math.radians(4 * hbp - 63))
    )
    dtheta = 30 * math.exp(-(((hbp - 275) / 25) ** 2))
    Rc = 2 * math.sqrt(Cbp**7 / (Cbp**7 + 25**7))  # noqa: N806
    Sl = 1 + (0.015 * (Lbp - 50) ** 2) / math.sqrt(20 + (Lbp - 50) ** 2)  # noqa: N806
    Sc = 1 + 0.045 * Cbp  # noqa: N806
    Sh = 1 + 0.015 * Cbp * T  # noqa: N806
    Rt = -math.sin(math.radians(2 * dtheta)) * Rc  # noqa: N806
    return math.sqrt((dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2 + Rt * (dCp / Sc) * (dHp / Sh))


def de(hex1: str, hex2: str) -> float:
    return delta_e2000(hex_to_lab(hex1), hex_to_lab(hex2))


# ----------------------------------------------------------------------------- self-checks


def self_check() -> None:
    # OKLab: Ottosson's reference, sRGB red = oklch(0.6280 0.2577 29.23)
    L, C, h = hex_to_oklch("#ff0000")  # noqa: N806
    assert abs(L - 0.62796) < 1e-3 and abs(C - 0.25768) < 1e-3 and abs(h - 29.23) < 0.05, (L, C, h)
    L, C, h = hex_to_oklch("#ffffff")  # noqa: N806
    assert abs(L - 1) < 1e-4 and C < 1e-4
    for hx in ("#0e3b83", "#00afd9", "#c12637", "#f7f9fc", "#13a261"):  # round trip
        assert oklch_to_hex(*hex_to_oklch(hx))[0] == hx, hx
    # WCAG: #777777 on white is the textbook 4.48:1
    assert abs(contrast("#777777", "#ffffff") - 4.48) < 0.01
    assert abs(contrast("#000000", "#ffffff") - 21) < 1e-9
    # CIEDE2000: Sharma, Wu & Dalal (2005) test pairs 1, 7 and 17
    pairs = [
        ((50.0, 2.6772, -79.7751), (50.0, 0.0, -82.7485), 2.0425),
        ((50.0, 0.0, 0.0), (50.0, -1.0, 2.0), 2.3669),
        ((50.0, 2.5, 0.0), (73.0, 25.0, -18.0), 27.1492),
    ]
    for a, b, want in pairs:
        got = delta_e2000(a, b)
        assert abs(got - want) < 1e-3, (a, b, got, want)
    for kind in MACHADO:  # pure grey is invariant under every simulation
        assert simulate("#808080", kind) == "#808080", kind
    print("colorlib self-check: OK (OKLab ref, WCAG ref, CIEDE2000 Sharma pairs 1/7/17, Machado grey invariance)")


if __name__ == "__main__":
    self_check()
