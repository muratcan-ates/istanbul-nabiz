"""The product app warms the GTFS tables in the background at start-up (``nabiz.console.gtfs_warm``).

The first arrival question of a fresh process then finds the stop index, the stop orders and the
departure tables loaded; a question that arrives mid-warm waits on the facade's lock instead of
loading a second copy. ``NABIZ_WARM_GTFS=0`` turns it off, and ``tests/conftest.py`` sets that for
every other test, so each test here switches it on itself.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

import ibb_mcp.timetables as timetables
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.tools import Nabiz
from nabiz.console import gtfs_warm
from nabiz.console.app import build_console_app


def loaded(nabiz: Nabiz) -> bool:
    return nabiz._gtfs is not None and nabiz._sequences is not None and nabiz._schedule_tables._tables is not None


def test_the_flag_is_on_unless_it_is_0() -> None:
    assert gtfs_warm.warm_gtfs_enabled({})
    assert gtfs_warm.warm_gtfs_enabled({"NABIZ_WARM_GTFS": ""})
    assert gtfs_warm.warm_gtfs_enabled({"NABIZ_WARM_GTFS": "1"})
    assert not gtfs_warm.warm_gtfs_enabled({"NABIZ_WARM_GTFS": "0"})
    assert not gtfs_warm.warm_gtfs_enabled({"NABIZ_WARM_GTFS": " 0 "})


def test_the_warm_up_fills_the_facades_own_caches(ctx: SourceContext) -> None:
    nabiz = Nabiz(ctx)

    async def run() -> None:
        assert not loaded(nabiz)
        await gtfs_warm.warm_gtfs(nabiz)
        assert loaded(nabiz)
        index = nabiz._gtfs
        assert await nabiz.gtfs() is index  # the tools read what the warm-up loaded

    asyncio.run(run())


def test_a_question_during_the_warm_up_waits_for_it_instead_of_loading_twice(
    ctx: SourceContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    loads: list[str] = []
    real = timetables._load

    def slow_load(settings: Any) -> Any:
        loads.append("departures")
        time.sleep(0.05)
        return real(settings)

    monkeypatch.setattr(timetables, "_load", slow_load)
    monkeypatch.setenv(gtfs_warm.WARM_GTFS_ENV, "1")
    nabiz = Nabiz(ctx)

    async def run() -> None:
        task = gtfs_warm.start_gtfs_warm(nabiz)
        assert task is not None
        await asyncio.sleep(0)
        tables = await nabiz._schedule_tables.get(nabiz.settings)  # what iett_next_arrivals awaits
        await task
        assert nabiz._schedule_tables._tables is tables

    asyncio.run(run())
    assert loads == ["departures"]


def test_a_failed_warm_up_is_logged_and_never_raised(caplog: pytest.LogCaptureFixture) -> None:
    class Broken:
        async def gtfs(self) -> None:
            raise OSError("stops.csv unreadable")

    with caplog.at_level(logging.WARNING, logger="nabiz.console"):
        asyncio.run(gtfs_warm.warm_gtfs(Broken()))  # type: ignore[arg-type]
    assert "GTFS warm-up failed" in caplog.text and "OSError" in caplog.text


@pytest.mark.parametrize(("flag", "calls"), [("1", 1), ("0", 0)])
def test_the_app_starts_the_warm_up_unless_it_is_switched_off(
    ctx: SourceContext, monkeypatch: pytest.MonkeyPatch, flag: str, calls: int
) -> None:
    started: list[Nabiz] = []

    async def spy(nabiz: Nabiz) -> None:
        started.append(nabiz)

    monkeypatch.setattr(gtfs_warm, "warm_gtfs", spy)
    monkeypatch.setenv(gtfs_warm.WARM_GTFS_ENV, flag)
    nabiz = Nabiz(ctx)
    with TestClient(build_console_app(nabiz=nabiz)) as client:
        assert client.get("/healthz").status_code == 200
    assert started == [nabiz] * calls


def test_the_app_start_up_does_not_wait_for_the_warm_up(ctx: SourceContext, monkeypatch: pytest.MonkeyPatch) -> None:
    release = asyncio.Event()

    async def never_done(nabiz: Nabiz) -> None:
        await release.wait()

    monkeypatch.setattr(gtfs_warm, "warm_gtfs", never_done)
    monkeypatch.setenv(gtfs_warm.WARM_GTFS_ENV, "1")
    with TestClient(build_console_app(nabiz=Nabiz(ctx))) as client:
        assert client.get("/healthz").status_code == 200  # answered while the warm-up is still pending
        assert len(gtfs_warm._RUNNING) == 1
