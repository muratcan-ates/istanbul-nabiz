"""The two shapes every citizen answer shares: ``Provenance`` and ``Card`` (the API contract).

    Provenance = {source, url, observed_at, age_s, mode: live|recorded|schedule|unknown}
    Card       = {id, kind, title, body, status: ok|warning|stale|unverified, provenance, author}

``mode`` is what the page's source icon shows. A recorded answer (``NABIZ_OFFLINE=1``, a
fixture) is ``recorded`` and never ``live``: the product promise is that no card claims a live
reading it does not have. ``unknown`` means nothing was read at all, and its card says
"doğrulanamadı" rather than a number.
"""

from __future__ import annotations

import datetime as dt
import os
import re
from collections.abc import Mapping
from typing import Any, Literal

from ibb_mcp.config import ATTRIBUTION
from ibb_mcp.models import Provenance, utcnow

Mode = Literal["live", "recorded", "schedule", "unknown"]
Status = Literal["ok", "warning", "stale", "unverified"]

#: A card whose source was read longer ago than this is "stale". Six hundred seconds is the
#: freshness cap the web page's tests already hold line positions to; a guess to be measured,
#: like every threshold on these cards, so it is a knob.
CARD_STALE_DEFAULT_S = 600

_DASHES = re.compile(r"\s*[—]\s*|[–]")
_ETA = re.compile(r"\bETA\b")


def env_seconds(name: str, default: int, env: Mapping[str, str] | None = None) -> int:
    """A positive whole number of seconds from the environment, or ``default`` when unset or invalid."""
    raw = ((os.environ if env is None else env).get(name) or "").strip()
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def display_text(text: str) -> str:
    """Text as the page may show it: no em or en dash, no "ETA".

    The page's design rules forbid both dashes in anything a visitor reads, and the product
    rules forbid the English abbreviation (the page says "tahmini varış"). Tool text and
    model prose can carry either, so the server cleans what it hands over. The attribution
    sentence keeps its dash: it is the one the charter allows.
    """
    kept = text.split(ATTRIBUTION)
    cleaned = [_ETA.sub("tahmini varış", _DASHES.sub(lambda m: ", " if "—" in m.group() else "-", part)) for part in kept]
    return ATTRIBUTION.join(cleaned)


def number_tr(value: float | int) -> str:
    """A tool's number as a Turkish reader writes it: 25.0 is "25", 25.5 is "25,5"."""
    if isinstance(value, float) and not value.is_integer():
        return f"{value:.1f}".replace(".", ",")
    return str(int(value))


def mode_for(offline: bool) -> Mode:
    return "recorded" if offline else "live"


def provenance_view(prov: Provenance, *, offline: bool, mode: Mode | None = None) -> dict[str, Any]:
    """The contract's Provenance for a tool result's provenance.

    ``observed_at`` is the moment the data describes (İBB's own timestamp when it gives one,
    else when it was read or recorded) and ``age_s`` counts from it, the same age the web
    page prints (:meth:`~ibb_mcp.models.Provenance.describe_age`).
    """
    reference = prov.reported_at or prov.observed_at
    return {
        "source": prov.source,
        "url": prov.source_url or None,
        "observed_at": reference.isoformat(),
        "age_s": int(prov.age_seconds),
        "mode": mode or mode_for(offline),
    }


def unknown_provenance(source: str, url: str | None = None) -> dict[str, Any]:
    """Nothing was read: no time, no age, and the card must not show a value."""
    return {"source": source, "url": url, "observed_at": None, "age_s": None, "mode": "unknown"}


def read_age_s(prov: Provenance) -> float:
    """Seconds since the source was *read* (or recorded), which is what staleness is about.

    Not :attr:`Provenance.age_seconds`: a Metro notice may be weeks old and still be the
    current notice, read a minute ago.
    """
    return max(0.0, (utcnow() - prov.observed_at).total_seconds())


def freshness_status(prov: Provenance, *, stale_after_s: float, content: Status = "ok") -> Status:
    """``stale`` when the reading was served from cache after a failure or is older than the cap."""
    if prov.cached or read_age_s(prov) > stale_after_s:
        return "stale"
    return content


def card(
    kind: str,
    key: str,
    *,
    title: str,
    body: str,
    status: Status,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    """One home-page card. Every card here is written by a template, so its author is "kural"."""
    return {
        "id": f"{kind}:{key}",
        "kind": kind,
        "title": display_text(title),
        "body": display_text(body),
        "status": status,
        "provenance": provenance,
        "author": "kural",
    }


def iso_now() -> str:
    return utcnow().astimezone(dt.UTC).isoformat()
