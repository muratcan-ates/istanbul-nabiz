"""The laptop collector's pid lock must tell a live collector from a reused pid.

After a reboot or a kill -9 the lock file survives with a pid that may now belong to an
unrelated process. Trusting ``os.kill(pid, 0)`` alone kept the collector down in that case.
"""

from __future__ import annotations

import importlib.util
import os
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def collect_forever():
    spec = importlib.util.spec_from_file_location("collect_forever_under_test", ROOT / "scripts" / "collect_forever.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_lock_records_pid_and_start_time(collect_forever, tmp_path):
    lock = tmp_path / ".collector.lock"
    with collect_forever.SingleInstance(lock):
        pid, start = lock.read_text().strip().split("\n")
        assert int(pid) == os.getpid()
        assert start == collect_forever._process_start(os.getpid())
    assert not lock.exists()


def test_live_owner_is_respected(collect_forever, tmp_path):
    lock = tmp_path / ".collector.lock"
    lock.write_text(f"{os.getpid()}\n{collect_forever._process_start(os.getpid())}\n")
    with pytest.raises(SystemExit, match="already running"):
        collect_forever.SingleInstance(lock).__enter__()


def test_reused_pid_with_another_start_time_is_stale(collect_forever, tmp_path):
    lock = tmp_path / ".collector.lock"
    lock.write_text(f"{os.getpid()}\nThu Jan  1 00:00:00 1970\n")
    with collect_forever.SingleInstance(lock):
        assert lock.read_text().startswith(f"{os.getpid()}\n")


def test_old_one_line_lock_falls_back_to_the_pid_check(collect_forever, tmp_path):
    lock = tmp_path / ".collector.lock"
    lock.write_text(f"{os.getpid()}\n")
    with pytest.raises(SystemExit, match="already running"):
        collect_forever.SingleInstance(lock).__enter__()
