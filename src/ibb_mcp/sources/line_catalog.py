"""The rail lines Metro İstanbul's own station record names, and a line a question names that it does not (A6).

``metro_status`` answers from ``GetServiceStatuses``, which lists only the lines that carry a notice. A line
that is not in that list is therefore "no notice"; but a line that does not exist ("M99", "M0", "T9") is not
in it either, and "M99 için bildirilmiş bir arıza/çalışma duyurusu yok" reads as if M99 ran. The station
record (``GetStations``, the same source) names every line it has a station on, so it is the known line set:
nothing here is typed by hand, and a line Metro İstanbul adds appears with its first station.

Pure functions over :class:`~ibb_mcp.models.MetroStation` rows; the caller fetches them through the metro
source and its cache (no extra upstream call beyond the station list the source already caches). The words
people use for a mode ("teleferik", "füniküler") name the line prefixes the record uses (TF, F).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any, Protocol

from ibb_mcp.models import MetroStation
from ibb_mcp.text import normalize_tr


class StationRecord(Protocol):
    """What :func:`no_notice_note` needs of the metro source (``MetroSource.stations``): sources never import
    each other, so the shape is named here instead."""

    async def stations(self) -> tuple[list[MetroStation], Any]: ...


#: Mode words, folded, and the line prefix the station record gives that mode.
MODE_PREFIXES: dict[str, str] = {"teleferik": "TF", "funikuler": "F", "tramvay": "T", "cable car": "TF", "funicular": "F"}
_LINE = re.compile(r"^(?:M\d{1,2}[AB]?|TF\d|T\d{1,2}|F\d)$")


def normal_line(line: str | None) -> str:
    """``" m1a "`` → ``"M1A"``: the spelling the station record uses."""
    return "".join((line or "").split()).upper().replace("İ", "I")


def known_lines(stations: Iterable[MetroStation]) -> frozenset[str]:
    """Every line the station record names."""
    return frozenset(normal_line(station.line_name) for station in stations if station.line_name)


def unknown_line(line: str | None, stations: Iterable[MetroStation]) -> str | None:
    """``line`` in the record's spelling when it looks like a rail line code the record does not name; else
    ``None``. A name that is not a line code ("Marmaray", a bus code) is not judged here, and an empty
    record (the source failed) judges nothing: "bilinmiyor" never becomes "yok"."""
    wanted = normal_line(line)
    known = known_lines(stations)
    if not wanted or not known or not _LINE.match(wanted) or wanted in known:
        return None
    return wanted


def unknown_line_note(line: str, stations: Iterable[MetroStation]) -> str:
    """The sourced sentence for a line the record does not name, with the lines it does name."""
    listed = ", ".join(sorted(known_lines(stations), key=_line_order))
    return (
        f"{line} adında bir hat Metro İstanbul'un istasyon kaydında yok; hat adını kontrol eder misin? "
        f"Kayıttaki hatlar: {listed}."
    )


async def no_notice_note(source: StationRecord, line: str) -> str:
    """``metro_status``'s note for a named line without a notice: "no notice" for a line the record names,
    the unknown-line sentence for one it does not. The station list comes from the source's cache (a day)."""
    stations, _ = await source.stations()
    unknown = unknown_line(line, stations)
    return unknown_line_note(unknown, stations) if unknown else f"{line.upper()} için bildirilmiş bir arıza/çalışma duyurusu yok."


def lines_for_mode(text: str, stations: Iterable[MetroStation]) -> tuple[str, ...]:
    """The record's lines for a mode word in ``text`` ("Teleferik çalışıyor mu?" → ``("TF1", "TF2")``)."""
    folded = f" {normalize_tr(text)} "
    prefixes = {prefix for word, prefix in MODE_PREFIXES.items() if f" {word}" in folded}
    known = known_lines(stations)
    return tuple(sorted((line for line in known if any(_prefix(line) == p for p in prefixes)), key=_line_order))


def _prefix(line: str) -> str:
    match = re.match(r"[A-Z]+", line)
    return match.group() if match else ""


def _line_order(line: str) -> tuple[str, int, str]:
    number = re.search(r"\d+", line)
    return (_prefix(line), int(number.group()) if number else 0, line)
