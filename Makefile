# İstanbul Nabız — developer shortcuts.
#
# Every target runs through ./.venv, never through whatever python happens to be active,
# so a forgotten `source .venv/bin/activate` cannot silently test the wrong interpreter.
# `make lint`, `make test`, `make smoke`, `make guardrails` and `make authorship` are the
# gates CI runs; `make ci-local` runs all of them on a clean copy of what a push would
# publish, which is the only way to see what CI sees. See .github/workflows/README.md.
#
# Anything that talks to api.ibb.gov.tr is marked NETWORK below. That gateway is shared
# public infrastructure with a documented İETT budget of 100 requests/hour — run those
# targets deliberately, not in a loop.

PY       := ./.venv/bin/python
RUFF     := ./.venv/bin/ruff
SRC      := src/ scripts/ tests/ .github/scripts/
MCP_HOST ?= 127.0.0.1
MCP_PORT ?= 8000
WEB_PORT ?= 8080
# dev alone is not enough to run the suite: tests/test_web.py imports fastapi at module
# scope, so `[dev]` makes pytest abort during collection. CI installs the same pair.
EXTRAS   ?= dev,web
EVAL_ARGS ?=
# Empty means "what git push would send": @{upstream}..HEAD, else origin/main..HEAD.
AUTHORSHIP_RANGE ?=

.DEFAULT_GOAL := help
.PHONY: help venv install test lint fmt smoke guardrails authorship hooks ci-local mcp mcp-http web eval eval-live fixtures places sequences \
        collect collect-bg collect-supervise collect-status collect-stop collect-plan eta eta-diagnose eta-holdout warmup clean

help:  ## show this list
	@echo "İstanbul Nabız — make <target>:" && grep -hE '^[a-z][a-z0-9-]*:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

venv:  ## create .venv on python 3.12 (uv)
	uv venv -p 3.12 .venv

install:  ## install project + dev tools into .venv, editable (EXTRAS=dev,web,collector for a tier)
	UV_HTTP_TIMEOUT=180 uv pip install --python $(PY) -e ".[$(EXTRAS)]"

test:  ## run the test suite (offline, no upstream calls; the same NABIZ_OFFLINE=1 CI sets)
	NABIZ_OFFLINE=1 $(PY) -m pytest -q

lint:  ## ruff lint — the check CI gates on
	$(RUFF) check $(SRC)

fmt:  ## apply ruff format — advisory, CI only reports it
	$(RUFF) format $(SRC)

smoke:  ## build the MCP server offline: >= 12 tools, each with a real input schema
	NABIZ_OFFLINE=1 $(PY) .github/scripts/mcp_smoke.py

guardrails:  ## regression fences for incidents already had (plates, schemas, secrets, personal data, AI credit)
	NABIZ_OFFLINE=1 $(PY) scripts/guardrails.py

authorship:  ## check the commits a push would send: noreply identity, no AI trailer, no bot (AUTHORSHIP_RANGE=)
	$(PY) scripts/check_authorship.py $(AUTHORSHIP_RANGE)

hooks:  ## once per clone: use .githooks/, so git push runs the authorship gate before anything is public
	git config core.hooksPath .githooks

ci-local:  ## run every CI gate on a clean copy of what a push would publish (CI_LOCAL_DIR=)
	bash .github/scripts/ci_local.sh

mcp:  ## run the MCP server on stdio — the shape VS Code and Claude launch
	./.venv/bin/ibb-mcp

mcp-http:  ## run the MCP server on streamable HTTP — the shape Container Apps runs
	./.venv/bin/ibb-mcp --transport http --host $(MCP_HOST) --port $(MCP_PORT)

web:  ## serve the Nabız web UI on :8080 with reload (WEB_PORT=, needs the web extra)
	./.venv/bin/uvicorn nabiz.web.main:app --reload --no-access-log --port $(WEB_PORT)

eval:  ## run the journey eval harness against recorded fixtures (EVAL_ARGS='--mode agent')
	$(PY) eval/run_eval.py --offline $(EVAL_ARGS)

eval-live:  ## NETWORK same harness against live İBB — capped at 8 upstream calls, run rarely
	$(PY) eval/run_eval.py $(EVAL_ARGS)

fixtures:  ## NETWORK re-record tests/fixtures from İBB — spends İETT budget, run rarely
	$(PY) scripts/capture_fixtures.py

places:  ## rebuild data/reference/places.csv from the recorded fixtures (no network)
	$(PY) scripts/build_places.py

sequences:  ## rebuild the GTFS route stop-sequence cache from data/reference/gtfs
	$(PY) -c "from ibb_mcp.config import Settings; from ibb_mcp.gtfs import build_stop_sequences, save_stop_sequences; s = Settings.from_env(); print(save_stop_sequences(s, build_stop_sequences(s)))"

collect:  ## NETWORK run the collector in the foreground until Ctrl-C (the history İBB does not keep)
	$(PY) scripts/collect_forever.py

collect-bg:  ## NETWORK start the collector detached, logging to logs/collector.log
	@mkdir -p logs data/lake
	@nohup $(PY) scripts/collect_forever.py > logs/collector.log 2>&1 & echo "collector started, pid $$!"

collect-supervise:  ## NETWORK start the self-restarting collector supervisor (survives sleep and crashes)
	@nohup bash scripts/supervise_collector.sh > /dev/null 2>&1 & echo "supervisor started"

collect-status:  ## what the collector has gathered so far (no network)
	$(PY) scripts/collect_forever.py --status

collect-stop:  ## stop the supervisor and the collector
	@pkill -f supervise_collector.sh 2>/dev/null; pkill -f collect_forever.py && echo "collector stopped" || echo "no collector running"

collect-plan:  ## İETT arithmetic of the scheduled collector jobs: peak-hour requests vs the budget (no network)
	NABIZ_OFFLINE=1 $(PY) -m nabiz.collector.job --plan

eta:  ## measure arrival-estimate error against observed arrivals (no network)
	$(PY) scripts/eta_report.py

eta-diagnose:  ## is the arrival error the model's fault or the measurement's? (no network)
	$(PY) scripts/eta_report.py --diagnose

eta-holdout:  ## replay the calibrated ETA profile on predictions made after it was fitted (no network)
	NABIZ_OFFLINE=1 $(PY) scripts/eta_holdout.py

warmup:  ## NETWORK prime the caches before recording a demo
	$(PY) scripts/warmup.py

clean:  ## delete caches and reports — keeps .venv, data/reference and fixtures
	rm -rf .pytest_cache .ruff_cache reports dist build && find . -path ./.venv -prune -o -name __pycache__ -type d -print0 | xargs -0 rm -rf
