"""Local reference files, parsed once per file version: one caching idiom for every table.

The occupancy profile, the line-reliability table and the calibrated ETA profile are JSON
files the tools read on the request path, and they grow with the history the collector
keeps adding. Each is parsed at most once per process per file version: keyed by path and
invalidated by (mtime, size), so a rebuilt file is picked up without a restart and a
question never pays again for a parse already paid for (docs/ENGINEERING.md §14, OPT-4;
``tests/test_performance_budgets.py`` counts the parses). Until 2026-09-23 only the
occupancy profile was cached this way; the other two were parsed on every call, and the
alert engine kept a second cache of the reliability table.

Foundation layer: standard library only.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import Callable
from typing import Any

#: (path, kind) -> ((mtime_ns, size), parsed value). Public measurement tables only; no
#: user state ever reaches this cache.
_PARSED: dict[tuple[str, str], tuple[tuple[int, int], Any]] = {}


def parse_once[T](path: pathlib.Path, parse: Callable[[Any], T], *, kind: str) -> T:
    """``parse(json)`` of the file at ``path``, once per file version.

    Raises whatever ``stat``, the read, ``json.loads`` or ``parse`` raise
    (``FileNotFoundError`` for an absent file) and caches only a success, so each caller
    keeps its own policy for a missing or broken file. ``kind`` names the parser, so two
    readers of one path cannot hand each other the wrong type.
    """
    stat = path.stat()
    fingerprint = (stat.st_mtime_ns, stat.st_size)
    key = (str(path), kind)
    cached = _PARSED.get(key)
    if cached is not None and cached[0] == fingerprint:
        return cached[1]
    value = parse(json.loads(path.read_text(encoding="utf-8")))
    _PARSED[key] = (fingerprint, value)
    return value


def clear() -> None:
    """Forget every parsed file: for tests and measurements that need a cold parse."""
    _PARSED.clear()
