"""Numeric faithfulness: every number the agent says must come from a tool result.

WHY this module exists. The whole claim of this project is "no invented numbers". A model
that has just been handed 249 car parks and 6,900 bus positions will cheerfully round, add
up, or simply make up a figure — and a citation printed next to a wrong number is worse
than no citation at all, because it borrows İBB's authority for something İBB never said.
So after the model writes its answer we read it back, pull out every quantity, and require
each one to appear in the JSON the tools actually returned.

The rules are written down here rather than left to taste, because they decide what counts
as a fabrication:

1. **Turkish formatting is the default reading.** ``12,5`` is 12.5 and ``1.250`` is 1250.
   Where a token is genuinely ambiguous (``1.250`` is also the English 1.25) *both*
   readings are tried and the number passes if either is supported. A repair loop over a
   decimal separator costs a model call and teaches the model nothing.
2. **Dates, clock times and list markers are not quantities.** ``2026-09-08``, ``08.09.2026``
   and ``09:15`` are masked out before extraction, as is a leading ``1.`` on a bullet line.
   Time *durations* ("13 dakika") are quantities and are checked.
3. **Rounding is allowed, invention is not.** A number written with ``d`` decimal digits is
   supported by a source value ``v`` when ``|v - n| <= 0.5 * 10**-d``. So a source 0.9 may
   be written ``1``, a source 12,47 may be written ``12,5`` — and a source 249 may never be
   written ``250``. The tolerance is exactly "n is a correct rounding of v at the precision
   the answer chose", which is the only rounding a careful writer would perform.
4. **Support is read from the whole tool-result tree**, numbers embedded in strings
   included (the İSPARK tariff text, the "4. LEVENT" stop name). Being generous about what
   counts as *available* keeps the check aimed at its real target: numbers that exist
   nowhere in the evidence. The one thing generosity may **not** cover is a timestamp:
   rule 2's masks are applied to source strings too, because every payload carries an
   ``observed_at`` and an unmasked ``2026-09-08T09:15`` would license 8, 9, 15 and 2026 —
   the exact sizes of the counts and minute figures a model invents.
5. **Tokens glued to letters are identifiers, not quantities.** ``M4``, ``T1``, ``E-5``,
   ``15F`` and ``500T`` are all skipped when they appear *in the answer* — line codes are
   names in this domain, and checking them produces noise, not safety. On the *source*
   side the digits are still harvested (``500T`` offers 500), because being generous about
   what is available costs nothing.

The checker is deliberately independent of the model and of the MCP server: it takes text
plus whatever the tools returned, so the eval harness can run it over recorded transcripts.
"""

from __future__ import annotations

import bisect
import contextlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

__all__ = ["CheckedNumber", "FaithfulnessReport", "check_faithfulness", "extract_numbers"]

# Anything that is a timestamp rather than a measurement. Masked with spaces so that the
# character offsets of everything else survive, which keeps the context snippets honest.
_MASKS: tuple[re.Pattern[str], ...] = (
    # ISO date, optionally with a time and an offset: 2026-09-08T05:10:17+03:00
    re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?"),
    # Turkish date, with or without a clock: 08.09.2026 05:10:17
    re.compile(r"\d{1,2}\.\d{1,2}\.\d{2,4}(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?"),
    # Bare clock time: 09:15, 09:15:30
    re.compile(r"\d{1,2}:\d{2}(?::\d{2})?"),
    # "8 Eylül", "8 September" — the day number is a date part, not a measurement.
    re.compile(
        r"\d{1,2}\.?\s+(?:Ocak|Şubat|Mart|Nisan|Mayıs|Haziran|Temmuz|Ağustos|Eylül|Ekim|Kasım|Aralık"
        r"|January|February|March|April|May|June|July|August|September|October|November|December)",
        re.IGNORECASE,
    ),
    # Road and line identifiers that carry a digit: E-5, D-100, TEM-2.
    re.compile(r"\b[A-ZÇĞİÖŞÜ]{1,4}-\d{1,3}\b"),
    # Enumeration markers at the start of a line: "1. Otopark ...", "2) ...".
    re.compile(r"(?m)^[ \t]*\d{1,2}[.)](?=\s)"),
    # The licence version in the attribution line every answer is required to carry. It is
    # boilerplate, not a measurement — and masking it is better than letting it *supply*
    # the values 4 and 0, which would make "4 otopark" unfalsifiable.
    re.compile(r"CC[ -]BY(?:[ -]\w{2})*[ -]\d(?:\.\d)?", re.IGNORECASE),
)

#: A quantity: optional leading sign (only when the token starts), then Turkish grouped
#: digits, a Turkish decimal, or a plain number. The lookarounds keep identifiers out.
_NUMBER_RE = re.compile(
    r"(?<![\w.,])(?:[-−])?"
    r"(?:\d{1,3}(?:\.\d{3})+(?:,\d+)?"  # 1.250 · 12.345,6
    r"|\d+,\d+"  # 12,5
    r"|\d+(?:\.\d+)?)"  # 45 · 3.5
    r"(?![\w]|\.\d)"
)

#: A looser pass used only to harvest *supported* values out of source strings.
_LOOSE_RE = re.compile(r"-?\d[\d.,]*\d|\d")


@dataclass(frozen=True)
class CheckedNumber:
    """One quantity found in the answer, with the verdict and the evidence for it."""

    text: str
    value: float
    supported: bool
    matched: float | None = None
    context: str = ""
    candidates: tuple[float, ...] = ()

    def describe(self) -> str:
        if self.supported:
            return f"{self.text} ← {self.matched:g}" if self.matched is not None else self.text
        return f"{self.text} (…{self.context}…)" if self.context else self.text


@dataclass
class FaithfulnessReport:
    """The verdict on one answer. ``passed`` is what the agent branches on."""

    passed: bool
    checked_numbers: list[CheckedNumber] = field(default_factory=list)
    unsupported: list[CheckedNumber] = field(default_factory=list)
    explanation: str = ""
    source_value_count: int = 0

    @property
    def unsupported_texts(self) -> list[str]:
        return [item.text for item in self.unsupported]

    def repair_instruction(self, lang: str = "tr") -> str:
        """The message handed back to the model for its single repair attempt."""
        if self.passed:
            return ""
        listed = ", ".join(dict.fromkeys(self.unsupported_texts))
        if lang == "en":
            return (
                f"These numbers do not appear in any tool result: {listed}. "
                "Rewrite the answer using only numbers that are present in the tool output. "
                "If a figure is not available, say it is not available instead of estimating it."
            )
        return (
            f"Şu sayılar araç sonuçlarında geçmiyor: {listed}. "
            "Cevabı yalnızca araç çıktısında bulunan sayıları kullanarak yeniden yaz. "
            "Bir değer yoksa tahmin etme, 'bu bilgi yok' de."
        )


def _mask(text: str) -> str:
    """Blank out timestamps and list markers, preserving offsets."""
    for pattern in _MASKS:
        text = pattern.sub(lambda m: " " * len(m.group(0)), text)
    return text


def _interpret(token: str) -> list[tuple[float, int]]:
    """Turn a written token into ``(value, decimals)`` candidates, best reading first.

    ``decimals`` is how many digits the writer put after the decimal separator; it sets the
    rounding tolerance, so it must follow the reading it belongs to and not the token.
    """
    token = token.replace("−", "-").strip()
    sign = -1.0 if token.startswith("-") else 1.0
    body = token.lstrip("+-")
    if not body:
        return []
    out: list[tuple[float, int]] = []
    if "," in body:
        # Unambiguous Turkish: dots group thousands, the comma is the decimal point.
        whole, _, frac = body.replace(".", "").partition(",")
        try:
            out.append((sign * float(f"{whole}.{frac}"), len(frac)))
        except ValueError:
            return []
        return out
    if "." in body:
        parts = body.split(".")
        if len(parts) > 1 and all(len(p) == 3 for p in parts[1:]) and 1 <= len(parts[0]) <= 3:
            # 1.250 -> 1250 (Turkish grouping) is the primary reading here…
            out.append((sign * float("".join(parts)), 0))
        if len(parts) == 2:
            # …and the English decimal reading stays as a fallback so a mixed-language
            # answer is not accused of inventing a number.
            with contextlib.suppress(ValueError):
                out.append((sign * float(body), len(parts[1])))
        return list(dict.fromkeys(out))
    try:
        return [(sign * float(body), 0)]
    except ValueError:
        return []


def extract_numbers(text: str) -> list[CheckedNumber]:
    """Every quantity written in ``text``, in order, before any support is considered."""
    masked = _mask(text)
    found: list[CheckedNumber] = []
    for match in _NUMBER_RE.finditer(masked):
        readings = _interpret(match.group(0))
        if not readings:
            continue
        start, end = match.span()
        found.append(
            CheckedNumber(
                text=text[start:end],
                value=readings[0][0],
                supported=False,
                context=" ".join(text[max(0, start - 28) : end + 28].split()),
                candidates=tuple(value for value, _ in readings),
            )
        )
    return found


def _string_values(text: str) -> set[float]:
    """Numbers hiding inside a source string: tariffs, stop names, prices.

    Timestamps are masked out with exactly the same patterns used on the answer, because a
    source that is generous about *dates* is not generous, it is broken: every payload
    carries ``observed_at``, so an unmasked ``2026-09-08T09:15:33`` would silently license
    the digits 8, 9, 15, 33 and 2026 as "supported" — and those are precisely the sizes of
    the counts, minute figures and free-space numbers the agent invents. The mask is
    symmetric with :func:`extract_numbers`, so nothing an answer may legitimately quote
    (a departure clock, an ISO instant, ``E-5``) loses its support: both sides drop it.
    """
    values: set[float] = set()
    for match in _LOOSE_RE.finditer(_mask(text)):
        token = match.group(0)
        for value, _ in _interpret(token):
            values.add(value)
        # Also every digit run on its own, so "4.LEVENT" supports 4 and a tariff line
        # "İlk 1 saat 30 TL" supports 1 and 30. Generous on purpose: rule 4 above.
        for run in re.findall(r"\d+", token):
            values.add(float(run))
    return values


def collect_values(obj: Any, *, _depth: int = 0) -> set[float]:
    """Walk a tool result — dicts, lists, pydantic models, JSON strings — for numbers."""
    if _depth > 24 or obj is None:
        return set()
    if isinstance(obj, bool):
        return set()
    if isinstance(obj, (int, float)):
        return {float(obj)}
    if isinstance(obj, str):
        stripped = obj.strip()
        if stripped[:1] in "{[":
            try:
                return collect_values(json.loads(stripped), _depth=_depth + 1)
            except (ValueError, TypeError):
                pass
        return _string_values(obj)
    if hasattr(obj, "model_dump"):  # pydantic: ToolResult and every model inside it
        return collect_values(obj.model_dump(mode="json"), _depth=_depth + 1)
    if isinstance(obj, dict):
        values: set[float] = set()
        for key, value in obj.items():
            values |= collect_values(key, _depth=_depth + 1) | collect_values(value, _depth=_depth + 1)
        return values
    if isinstance(obj, (list, tuple, set)):
        values = set()
        for item in obj:
            values |= collect_values(item, _depth=_depth + 1)
        return values
    return _string_values(str(obj))


def _nearest(values: list[float], target: float) -> float | None:
    """Closest supported value to ``target``; ``values`` must be sorted."""
    if not values:
        return None
    idx = bisect.bisect_left(values, target)
    best: float | None = None
    for candidate in (values[idx - 1] if idx else None, values[idx] if idx < len(values) else None):
        if candidate is None:
            continue
        if best is None or abs(candidate - target) < abs(best - target):
            best = candidate
    return best


def check_faithfulness(
    answer: str,
    tool_results: Any = None,
    *,
    question: str | None = None,
    extra_sources: Any = None,
) -> FaithfulnessReport:
    """Check that every number in ``answer`` appears in ``tool_results``.

    ``question`` is treated as a source too: a user who says "I arrive in 20 minutes" may
    be quoted back without that 20 counting as a fabrication. ``extra_sources`` is the same
    escape hatch for anything else the caller legitimately put in front of the model.
    """
    supported_values = collect_values(tool_results)
    if question:
        supported_values |= _string_values(question)
    if extra_sources is not None:
        supported_values |= collect_values(extra_sources)
    ordered = sorted(supported_values)

    checked: list[CheckedNumber] = []
    for number in extract_numbers(answer):
        matched: float | None = None
        for value, decimals in _interpret(number.text):
            tolerance = 0.5 * (10.0**-decimals) + 1e-9
            nearest = _nearest(ordered, value)
            if nearest is not None and abs(nearest - value) <= tolerance:
                matched = nearest
                break
        checked.append(
            CheckedNumber(
                text=number.text,
                value=number.value,
                supported=matched is not None,
                matched=matched,
                context=number.context,
                candidates=number.candidates,
            )
        )

    unsupported = [item for item in checked if not item.supported]
    passed = not unsupported
    if not checked:
        explanation = "Cevapta doğrulanacak sayı yok."
    elif passed:
        explanation = f"{len(checked)} sayının tamamı araç sonuçlarında bulundu."
    else:
        listed = "; ".join(item.describe() for item in unsupported)
        explanation = (
            f"{len(checked)} sayıdan {len(unsupported)} tanesi araç sonuçlarında bulunamadı: {listed}"
        )
    return FaithfulnessReport(
        passed=passed,
        checked_numbers=checked,
        unsupported=unsupported,
        explanation=explanation,
        source_value_count=len(ordered),
    )
