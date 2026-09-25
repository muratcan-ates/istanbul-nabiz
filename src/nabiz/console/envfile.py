"""Load the repository's ``.env`` for the product app, with the standard library and nothing else.

Only :func:`nabiz.console.app.main` calls this, so only ``python -m nabiz.console`` (``make
console``) reads the file. The MCP server still never does: other people's clients launch it,
and a file that changes its behaviour by working directory is the trap ``.env.example``
describes. The rules:

- a variable already in the environment wins; the file never overrides it
- ``KEY=value``, ``export KEY=value``, ``# comments``, single or double quotes around a value,
  and a `` #`` comment after an unquoted value
- an empty value is skipped, so an unset knob keeps its default
- values are never logged, printed or returned; the caller gets the *names* that were set

``NABIZ_ENV_FILE`` points at another file.
"""

from __future__ import annotations

import logging
import os
import pathlib
import re
from collections.abc import MutableMapping

from ibb_mcp.config import REPO_ROOT

log = logging.getLogger("nabiz.console.env")

_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def env_file_path(environ: MutableMapping[str, str] | None = None) -> pathlib.Path:
    environ = os.environ if environ is None else environ
    override = (environ.get("NABIZ_ENV_FILE") or "").strip()
    return pathlib.Path(override) if override else REPO_ROOT / ".env"


def parse_env_line(line: str) -> tuple[str, str] | None:
    """``(key, value)`` for one assignment line, or None for a blank, comment or malformed line."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("export "):
        stripped = stripped[len("export ") :].lstrip()
    key, sep, value = stripped.partition("=")
    key = key.strip()
    if not sep or not _KEY.fullmatch(key):
        return None
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    elif " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    return key, value


def load_env_file(path: pathlib.Path | None = None, environ: MutableMapping[str, str] | None = None) -> list[str]:
    """Set the file's variables that the environment does not already have; return their names."""
    environ = os.environ if environ is None else environ
    path = path or env_file_path(environ)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError:
        log.warning("the .env file could not be read; continuing with the environment as it is")
        return []
    loaded: list[str] = []
    for line in text.splitlines():
        parsed = parse_env_line(line)
        if parsed is None:
            continue
        key, value = parsed
        if not value or key in environ:
            continue
        environ[key] = value
        loaded.append(key)
    log.info("loaded %d setting(s) from the .env file", len(loaded))
    return loaded
