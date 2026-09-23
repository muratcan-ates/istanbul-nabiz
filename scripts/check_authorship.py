#!/usr/bin/env python3
"""Authorship gate: every commit being pushed carries the owner's identity and nobody else's.

AGENTS.md §2 is the rule: the owner is the author of every commit, under his GitHub
noreply address, with no AI trailer and no bot identity. Coding assistants default to
crediting themselves — a ``Co-Authored-By`` trailer, a "Generated with" footer, sometimes
the whole author line — and one unnoticed default puts an assistant in the public
contributor list for good, because history on a public repository is permanent. So this
runs on every push and pull request in CI, and before a push as ``make authorship``.

A commit fails when:

* its author e-mail is not the owner's noreply address, or its committer e-mail is neither
  that address nor ``noreply@github.com`` (GitHub commits web-UI merges as itself);
* its author or committer name looks like an assistant or a bot (``ASSISTANT_NAME``);
* its message has a ``Co-Authored-By:`` line, a "Generated with/by <assistant>" line, a
  crediting trailer in the closing paragraph that names an assistant (``Assisted-by: ...``),
  aider's ``aider:`` subject prefix, or the robot emoji those footers carry.

Only the commits being pushed or proposed are checked. 19 early commits carry the owner's
personal e-mail address; whether to rewrite that history is the owner's decision, and a
gate that failed on them would fail every push until then (``.github/workflows/README.md``).

Usage::

    .venv/bin/python scripts/check_authorship.py                     # @{upstream}..HEAD
    .venv/bin/python scripts/check_authorship.py origin/main..HEAD   # any rev-list range
    .venv/bin/python scripts/check_authorship.py --push BEFORE AFTER  # a push event (CI)

Exit status: 0 when every commit passes, 1 when any fails, 2 when the range is unusable.
Needs git and the commits themselves; never touches the network.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys
from dataclasses import dataclass

OWNER_EMAIL = "135648847+muratcan-ates@users.noreply.github.com"
#: GitHub's own identity. It is the *committer* of merges and squashes done in the web UI;
#: the author of those commits is still the person who clicked, so it is never an author.
WEB_FLOW_EMAIL = "noreply@github.com"
ALLOWED_AUTHOR_EMAILS = frozenset({OWNER_EMAIL})
ALLOWED_COMMITTER_EMAILS = frozenset({OWNER_EMAIL, WEB_FLOW_EMAIL})

#: The assistants and bots this gate knows, one list for names and messages alike. It was
#: two lists once, and the name check knew fewer: an assistant that kept the owner's e-mail
#: and changed only the name passed. Aider does exactly that by default, appending
#: " (aider)" to the author and committer name. The newer names are whole words so a
#: person called Haider is not an assistant; "ai" is a whole word so "Hawaii" is not either.
_ASSISTANTS = (
    r"(?:claude|anthropic|chatgpt|openai|gpt-?\d*|copilot|codex|\bgemini\b|\bcursor\b|\baider\b|\ban? ai\b|\bai\b)"
)
ASSISTANT_NAME = re.compile(rf"{_ASSISTANTS}|\[bot\]|dependabot", re.I)
#: What a pushed ``before`` looks like when the push created the branch.
ZERO_SHA = re.compile(r"^0+$")

MESSAGE_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Trailer form only: a subject such as "Reject Co-Authored-By trailers" is prose about
    # the rule, and the commit that adds this gate has to be able to say so.
    ("Co-Authored-By trailer", re.compile(r"^[ \t]*co-authored-by[ \t]*:", re.I | re.M)),
    ("'Generated with/by <assistant>' line", re.compile(rf"\bgenerated (?:with|by)\W{{0,3}}{_ASSISTANTS}", re.I)),
    ("robot emoji", re.compile("\U0001f916")),
    # Aider's optional commit-message attribution prefixes the subject.
    ("'aider:' prefix", re.compile(r"^aider:", re.I | re.M)),
)
#: "Assisted-by: Copilot", "Signed-off-by: Claude <...>", "Claude-Session: ...". Checked in
#: the closing paragraph only, where git and GitHub read trailers, and only in two shapes:
#: a crediting key ("<verb>-by", "<verb>-with", "<tool>-session") whose value names an
#: assistant, or a hyphenated key that is itself named after one ("Claude-Session",
#: "AI-Assisted"). A closing line such as "Tested: VS Code Copilot and Claude Desktop list
#: the tools" or "Note: the default deployment is Azure OpenAI" is prose about the MCP
#: clients and the model backend this project ships, not a credit.
_CREDIT_KEY = r"[A-Za-z]+(?:-[A-Za-z]+)*-(?:by|with|session)"
ASSISTANT_TRAILER = re.compile(
    rf"^[ \t]*(?:{_CREDIT_KEY}[ \t]*:.*{_ASSISTANTS}|{_ASSISTANTS}-[A-Za-z]+(?:-[A-Za-z]+)*[ \t]*:)", re.I | re.M
)

_FIELD, _RECORD = "\x1f", "\x1e"
_FORMAT = _FIELD.join(("%H", "%an", "%ae", "%cn", "%ce", "%B")) + _RECORD


@dataclass(frozen=True)
class Commit:
    sha: str
    author_name: str
    author_email: str
    committer_name: str
    committer_email: str
    message: str

    @property
    def subject(self) -> str:
        return self.message.strip().splitlines()[0] if self.message.strip() else ""


def violations(commit: Commit) -> list[str]:
    """Every reason this commit may not be published under the owner's name. Pure."""
    found: list[str] = []
    if commit.author_email.lower() not in ALLOWED_AUTHOR_EMAILS:
        found.append(f"author e-mail {commit.author_email!r} is not the owner's noreply address")
    if commit.committer_email.lower() not in ALLOWED_COMMITTER_EMAILS:
        found.append(f"committer e-mail {commit.committer_email!r} is not the owner's noreply address")
    for role, name in (("author", commit.author_name), ("committer", commit.committer_name)):
        if ASSISTANT_NAME.search(name):
            found.append(f"{role} name {name!r} is an assistant or a bot")
    for label, pattern in MESSAGE_RULES:
        if pattern.search(commit.message):
            found.append(f"message carries a {label}")
    paragraphs = [p for p in re.split(r"\n[ \t]*\n", commit.message.strip()) if p.strip()]
    if len(paragraphs) > 1 and ASSISTANT_TRAILER.search(paragraphs[-1]):
        found.append("message carries a trailer naming an assistant")
    return found


class RangeError(RuntimeError):
    """The commits to check could not be determined."""


def _git(repo: pathlib.Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", check=False)


def _is_commit(repo: pathlib.Path, rev: str) -> bool:
    return _git(repo, "cat-file", "-e", f"{rev}^{{commit}}").returncode == 0


def read_commits(repo: pathlib.Path, revisions: list[str]) -> list[Commit]:
    """``git log`` over ``revisions`` (rev-list syntax), parsed into :class:`Commit`."""
    proc = _git(repo, "log", "--no-color", f"--format={_FORMAT}", *revisions, "--")
    if proc.returncode != 0:
        raise RangeError(proc.stderr.strip() or f"git log {' '.join(revisions)} failed")
    commits: list[Commit] = []
    for record in proc.stdout.split(_RECORD):
        record = record.lstrip("\n")
        if not record:
            continue
        sha, an, ae, cn, ce, message = record.split(_FIELD, 5)
        commits.append(Commit(sha, an, ae, cn, ce, message))
    return commits


def push_revisions(repo: pathlib.Path, before: str, after: str) -> tuple[list[str], str | None]:
    """The rev-list arguments for a push event, plus a notice when the range had to shrink.

    ``before..after`` is exactly what the push introduced, force-pushes included: after a
    rewrite, the rewritten commits are the ones not reachable from the old tip. Two cases
    have no usable ``before``. A push that created the branch sends all zeros, and a
    force-push leaves the old tip unreachable, so a fresh clone may not have it (CI tries
    to fetch it by SHA first). Checking the whole history instead would fail every such push
    on the early commits the owner has not yet decided about, so the tip alone is checked
    and the log says so.
    """
    if not _is_commit(repo, after):
        raise RangeError(f"pushed commit {after!r} is not in this repository")
    if ZERO_SHA.match(before):
        return [after, "-1"], "the push created the branch; there is no previous tip, so only the pushed tip is checked"
    if not _is_commit(repo, before):
        return [after, "-1"], f"previous tip {before[:12]} is not available (force-push?); only the pushed tip is checked"
    return [f"{before}..{after}"], None


def default_revisions(repo: pathlib.Path) -> list[str]:
    """What ``git push`` would send: the upstream's range, else ``origin/main..HEAD``."""
    for base in ("@{upstream}", "origin/main"):
        if _git(repo, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}").returncode == 0:
            return [f"{base}..HEAD"]
    raise RangeError("no upstream and no origin/main to compare with; pass a range such as main..HEAD")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="check_authorship", description=__doc__.splitlines()[0])
    parser.add_argument("revisions", nargs="*", help="rev-list ranges to check (default: @{upstream}..HEAD)")
    parser.add_argument("--push", nargs=2, metavar=("BEFORE", "AFTER"), help="check a push event's commits")
    parser.add_argument("--repo", type=pathlib.Path, default=pathlib.Path.cwd(), help="repository (default: cwd)")
    args = parser.parse_args(argv)
    if args.push and args.revisions:
        parser.error("give either --push or ranges, not both")

    try:
        notice = None
        if args.push:
            revisions, notice = push_revisions(args.repo, *args.push)
        else:
            revisions = args.revisions or default_revisions(args.repo)
        commits = read_commits(args.repo, revisions)
    except RangeError as exc:
        print(f"check_authorship: {exc}", file=sys.stderr)
        return 2

    if notice:
        print(f"note: {notice}")
    label = " ".join(r for r in revisions if r != "-1") + (" (tip only)" if "-1" in revisions else "")
    failed = 0
    for commit in commits:
        problems = violations(commit)
        mark = "FAIL" if problems else "ok  "
        print(f"{mark} {commit.sha[:12]} {commit.author_name} <{commit.author_email}>  {commit.subject[:72]}")
        for problem in problems:
            print(f"       - {problem}")
        failed += bool(problems)

    print(f"{len(commits)} commit(s) in {label}: {failed} failed")
    if failed:
        print(
            "Fix it before pushing: `git commit --amend --reset-author` for the last commit, or an interactive "
            "rebase for older ones; drop any trailer that credits an assistant. See AGENTS.md §2."
        )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
