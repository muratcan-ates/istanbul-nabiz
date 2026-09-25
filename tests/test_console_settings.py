"""The product app's two process-level pieces: the ``.env`` loader and the daily spend ceiling.

Every file here is written by the test into ``tmp_path``; no test reads the repository's own
``.env``, and none prints a value it loads.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import pathlib

import pytest

from nabiz.console.budget import DEFAULT_DAILY_CALLS, BudgetConfig, SpendGuard
from nabiz.console.envfile import env_file_path, load_env_file, parse_env_line

LOADED_VALUE = "dummy-value-kept-out-of-logs"


# --------------------------------------------------------------------------------------
# .env
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("line", "parsed"),
    [
        ("NABIZ_LLM_MODEL=gpt-x", ("NABIZ_LLM_MODEL", "gpt-x")),
        ("export NABIZ_OFFLINE=1", ("NABIZ_OFFLINE", "1")),
        ('NABIZ_A="quoted # not a comment"', ("NABIZ_A", "quoted # not a comment")),
        ("NABIZ_B='single'", ("NABIZ_B", "single")),
        ("NABIZ_C=value # trailing comment", ("NABIZ_C", "value")),
        ("  NABIZ_D = spaced  ", ("NABIZ_D", "spaced")),
        ("NABIZ_E=", ("NABIZ_E", "")),
        ("# NABIZ_F=commented", None),
        ("", None),
        ("not an assignment", None),
        ("1BAD=x", None),
    ],
)
def test_parse_env_line(line: str, parsed: tuple[str, str] | None) -> None:
    assert parse_env_line(line) == parsed


def test_the_environment_wins_empty_values_are_skipped_and_values_never_logged(
    tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"# model\nNABIZ_LLM_API_KEY={LOADED_VALUE}\nNABIZ_LLM_MODEL=from-file\nNABIZ_OFFLINE=\n", encoding="utf-8"
    )
    environ = {"NABIZ_LLM_MODEL": "from-shell"}
    caplog.set_level(logging.DEBUG)

    loaded = load_env_file(env_file, environ)

    assert loaded == ["NABIZ_LLM_API_KEY"]
    assert environ == {"NABIZ_LLM_MODEL": "from-shell", "NABIZ_LLM_API_KEY": LOADED_VALUE}
    assert LOADED_VALUE not in caplog.text


def test_a_missing_env_file_changes_nothing(tmp_path: pathlib.Path) -> None:
    environ: dict[str, str] = {}
    assert load_env_file(tmp_path / "absent.env", environ) == [] and environ == {}


def test_env_file_path_defaults_to_the_repository_and_can_be_pointed_elsewhere(tmp_path: pathlib.Path) -> None:
    assert env_file_path({}).name == ".env"
    assert env_file_path({"NABIZ_ENV_FILE": str(tmp_path / "other.env")}) == tmp_path / "other.env"


# --------------------------------------------------------------------------------------
# the spend ceiling
# --------------------------------------------------------------------------------------
class Clock:
    def __init__(self, moment: dt.datetime) -> None:
        self.moment = moment

    def __call__(self) -> dt.datetime:
        return self.moment


MORNING = dt.datetime(2026, 9, 25, 6, 0, tzinfo=dt.UTC)  # 09:00 in İstanbul


def test_budget_config_reads_the_knobs(tmp_path: pathlib.Path) -> None:
    config = BudgetConfig.from_env(
        {
            "NABIZ_LLM_DAILY_USD": "0,5",
            "NABIZ_LLM_PRICE_IN_PER_MTOK": "0.4",
            "NABIZ_LLM_PRICE_OUT_PER_MTOK": "1.6",
            "NABIZ_LLM_DAILY_CALLS": "40",
            "NABIZ_LLM_SPEND_FILE": str(tmp_path / "spend.json"),
        }
    )
    assert (config.daily_usd, config.price_in_per_mtok, config.price_out_per_mtok, config.daily_calls) == (0.5, 0.4, 1.6, 40)
    assert config.priced and config.state_path == tmp_path / "spend.json"


def test_budget_config_defaults_and_rejects_nonsense() -> None:
    config = BudgetConfig.from_env({"NABIZ_LLM_DAILY_USD": "lots", "NABIZ_LLM_PRICE_IN_PER_MTOK": "-1"})
    assert config.daily_usd == 1.0 and config.daily_calls == DEFAULT_DAILY_CALLS
    assert not config.priced, "without both prices the ceiling is a call count, never a guessed price"


def test_unpriced_ceiling_counts_calls() -> None:
    guard = SpendGuard(BudgetConfig(daily_calls=2, state_path=None), clock=Clock(MORNING))
    assert guard.allows("azure_openai")
    guard.record("azure_openai", {"prompt_tokens": 10_000, "completion_tokens": 500}, 2)
    assert not guard.allows("azure_openai")
    assert guard.today()["usd"] == 0.0 and guard.today()["ceiling"] == {"kind": "calls", "value": 2}


def test_priced_ceiling_counts_dollars() -> None:
    config = BudgetConfig(daily_usd=0.01, price_in_per_mtok=2.0, price_out_per_mtok=8.0, state_path=None)
    guard = SpendGuard(config, clock=Clock(MORNING))
    guard.record("openai_compatible", {"prompt_tokens": 2_000, "completion_tokens": 500}, 50)
    assert guard.today()["usd"] == pytest.approx(0.008)
    assert guard.allows("openai_compatible"), "call count does not matter once prices are set"
    guard.record("openai_compatible", {"prompt_tokens": 1_000, "completion_tokens": 0}, 1)
    assert not guard.allows("openai_compatible")


def test_a_local_model_is_never_counted_or_refused() -> None:
    guard = SpendGuard(BudgetConfig(daily_calls=0, state_path=None), clock=Clock(MORNING))
    guard.record("foundry_local", {"prompt_tokens": 99}, 5)
    assert guard.allows("foundry_local") and guard.today()["calls"] == 0


def test_the_count_survives_a_restart_and_resets_at_istanbul_midnight(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "console" / "llm_spend.json"
    clock = Clock(MORNING)
    first = SpendGuard(BudgetConfig(daily_calls=3, state_path=path), clock=clock)
    first.record("azure_openai", {"prompt_tokens": 7}, 3)
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored == {"day": "2026-09-25", "usd": 0.0, "calls": 3, "prompt_tokens": 7, "completion_tokens": 0}

    restarted = SpendGuard(BudgetConfig(daily_calls=3, state_path=path), clock=clock)
    assert not restarted.allows("azure_openai"), "a restart does not reset today's spend"

    clock.moment = dt.datetime(2026, 9, 25, 21, 0, tzinfo=dt.UTC)  # 00:00 on the 26th in İstanbul
    assert restarted.allows("azure_openai") and restarted.today()["day"] == "2026-09-26"


def test_an_unreadable_spend_file_starts_the_day_at_zero(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "llm_spend.json"
    path.write_text("{not json", encoding="utf-8")
    guard = SpendGuard(BudgetConfig(daily_calls=1, state_path=path), clock=Clock(MORNING))
    assert guard.allows("azure_openai") and guard.today()["calls"] == 0
