"""SIGTERM stops the laptop collector within seconds, even in the middle of a slow tick.

``make collect-stop`` sends SIGTERM (pkill -f). The stop event used to be read only between
ticks, so a tick waiting on İBB kept the process alive and it needed kill -9. Each case runs the
real script in a child process with its sources replaced by a fake: no network, no İBB request,
and the lock, state and lake live in ``tmp_path``.
"""

from __future__ import annotations

import os
import pathlib
import select
import signal
import subprocess
import sys
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "collect_forever.py"
STOP_WITHIN_S = 10

WRAPPER = """
import asyncio, importlib.util, pathlib, sys
tmp = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("collect_forever_stop_test", sys.argv[2])
cf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cf)
cf.LOCK_PATH = tmp / ".collector.lock"
cf.STATE_PATH = tmp / ".collector_state.json"

class NoNetwork:
    async def aclose(self):
        pass

async def fake_tick(name, ctx, settings, state):
    print("tick " + name, flush=True)
    if sys.argv[3] == "slow":
        await asyncio.sleep(3600)  # a tick stuck on a slow upstream
    return 0

cf.build_collector_context = lambda settings: NoNetwork()
cf.tick = fake_tick
raise SystemExit(cf.main([]))
"""


def _wait_for_line(proc: subprocess.Popen[str], prefix: str, timeout_s: float) -> str:
    deadline = time.monotonic() + timeout_s
    assert proc.stdout is not None
    while time.monotonic() < deadline:
        ready, _, _ = select.select([proc.stdout], [], [], 0.2)
        if ready:
            line = proc.stdout.readline()
            if line.startswith(prefix):
                return line
            if not line and proc.poll() is not None:
                break
    raise AssertionError(f"no {prefix!r} line from the collector (exit {proc.poll()})")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
@pytest.mark.parametrize("mode", ["slow", "between"])
def test_sigterm_stops_the_collector_within_ten_seconds(tmp_path: pathlib.Path, mode: str) -> None:
    wrapper = tmp_path / "run_collector.py"
    wrapper.write_text(WRAPPER, encoding="utf-8")
    env = {
        **os.environ,
        "NABIZ_OFFLINE": "1",
        "NABIZ_ENV_FILE": os.devnull,
        "NABIZ_LAKE_DIR": str(tmp_path / "lake"),
        "NABIZ_LAKE_FORMAT": "json",
    }
    env.pop("AZURE_STORAGE_ACCOUNT", None)
    proc = subprocess.Popen(
        [sys.executable, str(wrapper), str(tmp_path), str(SCRIPT), mode],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env, cwd=tmp_path,
    )  # fmt: skip
    try:
        _wait_for_line(proc, "tick ", timeout_s=30)
        if mode == "between":
            time.sleep(0.5)  # every fake tick returned at once: the loop now waits for the next one
        proc.send_signal(signal.SIGTERM)
        started = time.monotonic()
        code = proc.wait(timeout=STOP_WITHIN_S)
        assert time.monotonic() - started < STOP_WITHIN_S
        assert code == 0
        assert not (tmp_path / ".collector.lock").exists(), "the lock is released on a clean stop"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
