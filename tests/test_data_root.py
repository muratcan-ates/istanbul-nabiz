"""P00 D2a (I): one data root for the files the app writes; a store's own variable still wins."""

from __future__ import annotations

import pathlib

from ibb_mcp.config import REPO_ROOT
from nabiz.console.data_root import data_root, store_path


def test_without_a_root_the_files_stay_in_the_repositorys_data() -> None:
    assert data_root({}) == REPO_ROOT / "data"
    assert store_path("NABIZ_QUOTA_DB", "accounts/quota.sqlite", {}) == REPO_ROOT / "data" / "accounts" / "quota.sqlite"


def test_the_root_moves_every_store_without_its_own_name(tmp_path: pathlib.Path) -> None:
    env = {"NABIZ_DATA_ROOT": str(tmp_path)}
    assert store_path("NABIZ_SESSIONS_DB", "accounts/sessions.sqlite", env) == tmp_path / "accounts" / "sessions.sqlite"
    assert data_root({"NABIZ_DATA_ROOT": "var/state"}) == REPO_ROOT / "var" / "state"


def test_a_stores_own_variable_wins_and_a_relative_one_is_the_repositorys(tmp_path: pathlib.Path) -> None:
    env = {"NABIZ_DATA_ROOT": str(tmp_path / "root"), "NABIZ_PLAN_DB_PATH": str(tmp_path / "plans.sqlite3")}
    assert store_path("NABIZ_PLAN_DB_PATH", "nexus/plans.sqlite3", env) == tmp_path / "plans.sqlite3"
    relative = {"NABIZ_APPEALS_DB": "data/x/appeals.sqlite"}
    assert store_path("NABIZ_APPEALS_DB", "accounts/appeals.sqlite", relative) == REPO_ROOT / "data" / "x" / "appeals.sqlite"
