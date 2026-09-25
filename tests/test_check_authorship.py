"""Tests for ``scripts/check_authorship.py``, the gate that keeps assistants out of the history.

Every case builds a throwaway repository in ``tmp_path`` and commits with an explicit
``-c user.name`` / ``-c user.email``, so neither the machine's git identity nor its global
config (signing, hooks, templates) can decide the outcome. Addresses other than the
owner's noreply one are assembled from parts on the reserved ``.invalid`` domain: this
file is public, and a literal address in it would be exactly what the gates forbid.
"""

from __future__ import annotations

import importlib.util
import os
import pathlib
import shutil
import subprocess
import sys

import pytest
from conftest import REPO_ROOT

SCRIPT = REPO_ROOT / "scripts" / "check_authorship.py"
_spec = importlib.util.spec_from_file_location("check_authorship", SCRIPT)
check_authorship = importlib.util.module_from_spec(_spec)
# Registered before it runs: @dataclass resolves the module's annotations through sys.modules.
sys.modules[_spec.name] = check_authorship
_spec.loader.exec_module(check_authorship)

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

OWNER = ("Muratcan Ateş", check_authorship.OWNER_EMAIL)
STRANGER_EMAIL = "someone" + "@" + "example.invalid"
ZEROS = "0" * 40


def git_env(home: pathlib.Path) -> dict[str, str]:
    """An environment with no user or system git config at all."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(HOME=str(home), GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    return env


@pytest.fixture
def repo(tmp_path: pathlib.Path) -> pathlib.Path:
    path = tmp_path / "repo"
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True, env=git_env(tmp_path))
    return path


def commit(
    repo: pathlib.Path,
    message: str,
    author: tuple[str, str] = OWNER,
    committer: tuple[str, str] | None = None,
) -> str:
    """Make one commit and return its SHA. ``committer`` defaults to the author."""
    env = git_env(repo.parent)
    if committer is not None:
        env.update(GIT_COMMITTER_NAME=committer[0], GIT_COMMITTER_EMAIL=committer[1])
    subprocess.run(
        [
            "git", "-C", str(repo), "-c", f"user.name={author[0]}", "-c", f"user.email={author[1]}",
            "-c", "commit.gpgsign=false", "commit", "-q", "--allow-empty", "-m", message,
        ],
        check=True,
        env=env,
    )
    out = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True, env=env)
    return out.stdout.strip()


def run_gate(repo: pathlib.Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=git_env(repo.parent),
        timeout=60,
    )


# --------------------------------------------------------------------------------------
# what passes
# --------------------------------------------------------------------------------------
def test_an_owner_commit_passes(repo: pathlib.Path) -> None:
    base = commit(repo, "Start")
    commit(repo, "Add the stop search\n\nThe index is built once per process.")
    result = run_gate(repo, f"{base}..HEAD")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 commit(s)" in result.stdout and "0 failed" in result.stdout


def test_a_web_ui_merge_committed_by_github_passes(repo: pathlib.Path) -> None:
    base = commit(repo, "Start")
    commit(repo, "Merge pull request #1", committer=("GitHub", check_authorship.WEB_FLOW_EMAIL))
    assert run_gate(repo, f"{base}..HEAD").returncode == 0


def test_prose_about_the_rule_is_not_a_trailer(repo: pathlib.Path) -> None:
    # The commit that introduces this gate has to be able to describe it.
    base = commit(repo, "Start")
    commit(
        repo,
        "Reject Co-Authored-By trailers and bot authors in CI\n\n"
        "The gate also refuses a 'Generated with' footer.\n"
        "Follow-up: the OpenAI client in the agent is unchanged.\n\n"
        "The fixture was generated with extract.py.",
    )
    result = run_gate(repo, f"{base}..HEAD")
    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize(
    "closing",
    [
        "Tested: VS Code Copilot and Claude Desktop both list the 15 tools.",
        "Note: the default deployment is Azure OpenAI gpt-4o-mini.",
        "Reviewed-by: A Person",
    ],
)
def test_a_closing_line_about_clients_or_the_model_backend_is_not_a_credit(repo: pathlib.Path, closing: str) -> None:
    # This project ships an MCP server for those clients and an agent on that backend, so a
    # closing paragraph naming them is ordinary; only a crediting trailer key is a credit.
    base = commit(repo, "Start")
    commit(repo, f"Register the three new tools\n\nThe smoke test counts them.\n\n{closing}")
    result = run_gate(repo, f"{base}..HEAD")
    assert result.returncode == 0, result.stdout


def test_a_person_whose_name_contains_an_assistant_name_passes() -> None:
    for name in ("Haider Ali", "Ayşe Yılmaz"):
        email = check_authorship.OWNER_EMAIL
        assert check_authorship.violations(check_authorship.Commit(ZEROS, name, email, name, email, "Fix it")) == [], name


def test_an_empty_range_passes(repo: pathlib.Path) -> None:
    commit(repo, "Start")
    result = run_gate(repo, "HEAD..HEAD")
    assert result.returncode == 0
    assert "0 commit(s)" in result.stdout


# --------------------------------------------------------------------------------------
# what fails
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("author", "committer", "reason"),
    [
        (("Muratcan Ateş", STRANGER_EMAIL), None, "author e-mail"),
        (OWNER, ("Muratcan Ateş", STRANGER_EMAIL), "committer e-mail"),
        (("GitHub", check_authorship.WEB_FLOW_EMAIL), None, "author e-mail"),
        (("Claude", check_authorship.OWNER_EMAIL), None, "author name"),
        (("dependabot[bot]", check_authorship.OWNER_EMAIL), None, "author name"),
        (OWNER, ("github-actions[bot]", check_authorship.OWNER_EMAIL), "committer name"),
        (("Copilot", check_authorship.OWNER_EMAIL), None, "author name"),
        # The owner's own e-mail with only the name changed, which is aider's default.
        (("Muratcan Ateş (aider)", check_authorship.OWNER_EMAIL), None, "author name"),
        (("Gemini CLI", check_authorship.OWNER_EMAIL), None, "author name"),
        (OWNER, ("Cursor Agent", check_authorship.OWNER_EMAIL), "committer name"),
    ],
)
def test_identity_violations_fail(repo: pathlib.Path, author, committer, reason: str) -> None:
    base = commit(repo, "Start")
    commit(repo, "Tidy the README", author=author, committer=committer)
    result = run_gate(repo, f"{base}..HEAD")
    assert result.returncode == 1, result.stdout
    assert reason in result.stdout


@pytest.mark.parametrize(
    ("message", "reason"),
    [
        ("Fix the loader\n\nCo-Authored-By: Claude <noreply" + "@" + "anthropic.invalid>", "Co-Authored-By"),
        ("Fix the loader\n\nco-authored-by: A Person <x" + "@" + "example.invalid>", "Co-Authored-By"),
        ("Fix the loader\n\n\U0001f916 Generated with [Claude Code](https://claude.invalid)", "robot emoji"),
        ("Fix the loader\n\nGenerated with [Claude Code](https://claude.invalid)", "Generated with"),
        ("Fix the loader\n\nGenerated by ChatGPT", "Generated with"),
        ("Fix the loader\n\nAssisted-by: GitHub Copilot", "trailer naming an assistant"),
        ("Fix the loader\n\nClaude-Session: https://claude.invalid/session", "trailer naming an assistant"),
        ("aider: fix the loader", "'aider:' prefix"),
    ],
)
def test_message_attribution_fails(repo: pathlib.Path, message: str, reason: str) -> None:
    base = commit(repo, "Start")
    commit(repo, message)
    result = run_gate(repo, f"{base}..HEAD")
    assert result.returncode == 1, result.stdout
    assert reason in result.stdout


def test_one_bad_commit_fails_the_whole_range(repo: pathlib.Path) -> None:
    base = commit(repo, "Start")
    commit(repo, "Good one")
    commit(repo, "Bad one", author=("Someone", STRANGER_EMAIL))
    commit(repo, "Good again")
    result = run_gate(repo, f"{base}..HEAD")
    assert result.returncode == 1
    assert "3 commit(s)" in result.stdout and "1 failed" in result.stdout


# --------------------------------------------------------------------------------------
# which commits are checked
# --------------------------------------------------------------------------------------
def test_only_the_pushed_range_is_checked_so_history_does_not_block_a_push(repo: pathlib.Path) -> None:
    """Early commits with a personal address are the owner's decision, not every push's."""
    commit(repo, "Historical commit", author=("Muratcan Ateş", STRANGER_EMAIL))
    before = commit(repo, "Last pushed commit")
    after = commit(repo, "New work")
    result = run_gate(repo, "--push", before, after)
    assert result.returncode == 0, result.stdout
    assert "1 commit(s)" in result.stdout


def test_a_push_that_creates_the_branch_checks_the_tip(repo: pathlib.Path) -> None:
    commit(repo, "Historical commit", author=("Muratcan Ateş", STRANGER_EMAIL))
    after = commit(repo, "New work")
    result = run_gate(repo, "--push", ZEROS, after)
    assert result.returncode == 0, result.stdout
    assert "created the branch" in result.stdout and "tip only" in result.stdout

    bad = commit(repo, "Bad tip", author=("Claude", check_authorship.OWNER_EMAIL))
    assert run_gate(repo, "--push", ZEROS, bad).returncode == 1


def test_a_force_push_whose_old_tip_is_gone_checks_the_tip(repo: pathlib.Path) -> None:
    after = commit(repo, "Rewritten work")
    result = run_gate(repo, "--push", "1" * 40, after)
    assert result.returncode == 0, result.stdout
    assert "not available" in result.stdout


def test_a_force_push_checks_every_rewritten_commit(repo: pathlib.Path) -> None:
    base = commit(repo, "Shared base")
    old_tip = commit(repo, "Old work")
    env = git_env(repo.parent)
    subprocess.run(["git", "-C", str(repo), "reset", "-q", "--hard", base], check=True, env=env)
    commit(repo, "Rewritten, bad", author=("Someone", STRANGER_EMAIL))
    new_tip = commit(repo, "Rewritten, good")
    result = run_gate(repo, "--push", old_tip, new_tip)
    assert result.returncode == 1
    assert "2 commit(s)" in result.stdout and "1 failed" in result.stdout


def test_an_unknown_pushed_commit_is_a_usage_error(repo: pathlib.Path) -> None:
    commit(repo, "Start")
    result = run_gate(repo, "--push", ZEROS, "2" * 40)
    assert result.returncode == 2
    assert "not in this repository" in result.stderr


def test_the_default_range_needs_an_upstream(repo: pathlib.Path) -> None:
    commit(repo, "Start")
    result = run_gate(repo)
    assert result.returncode == 2
    assert "no upstream" in result.stderr


# --------------------------------------------------------------------------------------
# the tracked pre-push hook: the same gate, before anything is public
# --------------------------------------------------------------------------------------
HOOKS_DIR = REPO_ROOT / ".githooks"


def push(repo: pathlib.Path, remote: pathlib.Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), "-c", f"core.hooksPath={HOOKS_DIR}", "push", "-q", str(remote), "main"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=git_env(repo.parent),
        timeout=60,
    )


def test_the_pre_push_hook_refuses_a_credited_commit_and_lets_a_clean_one_through(repo: pathlib.Path) -> None:
    remote = repo.parent / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True, env=git_env(repo.parent))
    commit(repo, "Start")
    first = push(repo, remote)
    assert first.returncode == 0, first.stdout + first.stderr

    commit(repo, "Fix the loader\n\nCo-Authored-By: Claude <noreply" + "@" + "anthropic.invalid>")
    refused = push(repo, remote)
    assert refused.returncode != 0, "the hook let an assistant credit reach the remote"
    assert "Co-Authored-By" in refused.stdout + refused.stderr
    remote_tip = subprocess.run(
        ["git", "-C", str(remote), "rev-parse", "main"], capture_output=True, text=True, env=git_env(repo.parent), check=True
    ).stdout.strip()
    local_parent = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD~1"], capture_output=True, text=True, env=git_env(repo.parent), check=True
    ).stdout.strip()
    assert remote_tip == local_parent, "the refused commit reached the remote anyway"


def push_refspec(repo: pathlib.Path, remote: pathlib.Path, refspec: str, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), "-c", f"core.hooksPath={HOOKS_DIR}", "push", "-q", str(remote), refspec],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=git_env(repo.parent) | env,
        timeout=60,
    )


@pytest.fixture
def remote(repo: pathlib.Path) -> pathlib.Path:
    """A bare remote holding one clean commit on main, and a local tag."""
    path = repo.parent / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(path)], check=True, env=git_env(repo.parent))
    commit(repo, "Start")
    subprocess.run(["git", "-C", str(repo), "tag", "v0.1.0"], check=True, env=git_env(repo.parent))
    return path


def remote_refs(remote: pathlib.Path) -> set[str]:
    out = subprocess.run(
        ["git", "-C", str(remote), "for-each-ref", "--format=%(refname)"],
        capture_output=True, text=True, env=git_env(remote.parent), check=True,
    )
    return set(out.stdout.split())


def test_the_pre_push_hook_sends_main_and_tags(repo: pathlib.Path, remote: pathlib.Path) -> None:
    for refspec in ("main", "refs/tags/v0.1.0"):
        result = push_refspec(repo, remote, refspec)
        assert result.returncode == 0, result.stdout + result.stderr
    assert remote_refs(remote) == {"refs/heads/main", "refs/tags/v0.1.0"}


def test_the_pre_push_hook_refuses_a_branch_on_the_public_remote(repo: pathlib.Path, remote: pathlib.Path) -> None:
    """A branch pushed as a backup is published work: the remote is public (AGENTS.md §3)."""
    refused = push_refspec(repo, remote, "main:refs/heads/backup")
    assert refused.returncode != 0, "the hook let a backup branch reach the public remote"
    assert "refs/heads/backup: public remote" in refused.stderr
    assert remote_refs(remote) == set()


def test_one_command_may_push_a_branch_on_purpose(repo: pathlib.Path, remote: pathlib.Path) -> None:
    """A pull request branch is pushed with NABIZ_ALLOW_BRANCH_PUSH=1 for that one command."""
    result = push_refspec(repo, remote, "main:refs/heads/pr-branch", NABIZ_ALLOW_BRANCH_PUSH="1")
    assert result.returncode == 0, result.stdout + result.stderr
    assert remote_refs(remote) == {"refs/heads/pr-branch"}


def test_deleting_a_stray_remote_branch_stays_possible(repo: pathlib.Path, remote: pathlib.Path) -> None:
    """A deletion publishes no commit, so the branch rule must not stand in the way of cleaning up."""
    push_refspec(repo, remote, "main:refs/heads/stray", NABIZ_ALLOW_BRANCH_PUSH="1")
    assert "refs/heads/stray" in remote_refs(remote)

    deleted = push_refspec(repo, remote, ":refs/heads/stray")

    assert deleted.returncode == 0, deleted.stdout + deleted.stderr
    assert remote_refs(remote) == set()


# --------------------------------------------------------------------------------------
# the pure rule, without git
# --------------------------------------------------------------------------------------
def test_violations_is_case_insensitive_on_addresses() -> None:
    upper = check_authorship.OWNER_EMAIL.upper()
    ok = check_authorship.Commit("a" * 40, "Muratcan Ateş", upper, "Muratcan Ateş", upper, "Subject\n")
    assert check_authorship.violations(ok) == []
