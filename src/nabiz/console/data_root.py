"""Where the product app keeps the files it writes (P00 D2a, I).

On a laptop that is the repository's gitignored ``data/``; in the web app it is the Azure Files share mounted
at ``/var/lib/nabiz`` (``NABIZ_DATA_ROOT``), so a restart or a new revision finds the same accounts, quota,
sessions, plans and appeals. A store's own variable (``NABIZ_QUOTA_DB`` and the like) still wins, as before.
"""

from __future__ import annotations

import os
import pathlib
from collections.abc import Mapping

from ibb_mcp.config import REPO_ROOT

DATA_ROOT_ENV = "NABIZ_DATA_ROOT"


def data_root(env: Mapping[str, str] | None = None) -> pathlib.Path:
    """``NABIZ_DATA_ROOT`` when set (relative to the repository when not absolute), else ``<repo>/data``."""
    env = os.environ if env is None else env
    raw = (env.get(DATA_ROOT_ENV) or "").strip()
    if not raw:
        return REPO_ROOT / "data"
    root = pathlib.Path(raw).expanduser()
    return root if root.is_absolute() else REPO_ROOT / root


def store_path(variable: str, name: str, env: Mapping[str, str] | None = None) -> pathlib.Path:
    """The file for one store: its own ``variable`` when set, else ``name`` under the data root.

    ``name`` is relative to the root (``accounts/quota.sqlite``); a relative ``variable`` is relative to the
    repository, as every store read it before the root existed.
    """
    env = os.environ if env is None else env
    raw = (env.get(variable) or "").strip()
    if raw:
        path = pathlib.Path(raw).expanduser()
        return path if path.is_absolute() else REPO_ROOT / path
    return data_root(env) / name
