"""`make ci-local` and `make ci-commit` run one at a time per copy (.github/scripts/ci_local.sh).

A second run on the same ``CI_LOCAL_DIR`` would delete the tree the first one is testing, so the
script takes a lock first and refuses while its holder is alive. The refusal comes before anything
is copied or installed, which makes it cheap enough to prove on every run. The stale-lock path is
not exercised here: past the lock the script copies the tree and builds a venv.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

from conftest import REPO_ROOT

SCRIPT = REPO_ROOT / ".github" / "scripts" / "ci_local.sh"


def test_a_second_run_on_the_same_copy_refuses_before_touching_it(tmp_path: pathlib.Path) -> None:
    repo = tmp_path / "repo"
    # CI_LOCAL_REF=HEAD is set while `make ci-commit` runs this suite; inherited, it sent the script
    # to this empty repository's HEAD, which is not a commit, before it reached the lock.
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "CI_LOCAL_"))}
    env.update(HOME=str(tmp_path), GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    subprocess.run(["git", "init", "-q", str(repo)], check=True, env=env)
    dest = tmp_path / "copy"
    (dest / ".lock").mkdir(parents=True)
    # A live process whose command line names the script: what a first run looks like to `ps`.
    holder = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", "ci_local.sh"])
    try:
        (dest / ".lock" / "pid").write_text(str(holder.pid), encoding="utf-8")
        result = subprocess.run(
            ["bash", str(SCRIPT)],
            cwd=repo,
            env=env | {"CI_LOCAL_DIR": str(dest)},
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )
    finally:
        holder.kill()
        holder.wait()

    assert result.returncode == 2, result.stdout + result.stderr
    assert f"run {holder.pid} is using" in result.stdout
    assert sorted(path.name for path in dest.iterdir()) == [".lock"], "the refused run touched the copy"
    assert (dest / ".lock" / "pid").read_text(encoding="utf-8") == str(holder.pid), "the refused run took the lock"
