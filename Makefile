# İstanbul Nabız — developer shortcuts.
#
# Every target runs through ./.venv, never through whatever python happens to be active,
# so a forgotten `source .venv/bin/activate` cannot silently test the wrong interpreter.
# `make lint`, `make test`, `make smoke`, `make guardrails`, `make architecture`,
# `make web-budget` and `make authorship` are the gates CI runs; `make ci-local` runs them
# on a clean copy of the working tree, and `make ci-commit` on HEAD exactly as a push
# publishes it, which is the only way to see what CI will see. See .github/workflows/README.md.
# `make lane-gates` is the sprint's shorter list for a lane branch (DECISIONS #26, until 2026-10-01):
# the ratchets and the web byte budget print WARN there and FAIL again at the integration merge.
#
# A target marked WRITES rewrites a tracked file: run it only when that file is yours to change.
#
# Anything that talks to api.ibb.gov.tr is marked NETWORK below. That gateway is shared
# public infrastructure with a documented İETT budget of 100 requests/hour — run those
# targets deliberately, not in a loop.

PY       := ./.venv/bin/python
RUFF     := ./.venv/bin/ruff
SRC      := src/ scripts/ tests/ .github/scripts/ eval/
MCP_HOST ?= 127.0.0.1
MCP_PORT ?= 8000
WEB_PORT ?= 8080
CONSOLE_PORT ?= 8090
# The free disk below which `make status` warns. The owner sets the real value.
STATUS_MIN_FREE_GB ?= 5
# dev alone is not enough to run the suite: tests/test_web.py imports fastapi at module
# scope, so `[dev]` makes pytest abort during collection. CI installs the same pair.
EXTRAS   ?= dev,web
EVAL_ARGS ?=
# Where `make eval` writes: gitignored, so verification never rewrites eval/results.
EVAL_OUT ?= reports/eval
# Empty means "what git push would send": @{upstream}..HEAD, else origin/main..HEAD.
AUTHORSHIP_RANGE ?=

.DEFAULT_GOAL := help
.PHONY: help status venv install test lint fmt smoke guardrails authorship hooks ci-local ci-commit lane-gates architecture \
        architecture-tighten perf-budgets perf-report web-budget mcp mcp-http web console eval eval-knowledge eval-record eval-live fixtures places \
        sequences collect collect-bg collect-supervise collect-status collect-stop collect-plan lake-backup eta eta-diagnose \
        eta-holdout warmup clean

help:  ## show this list
	@echo "İstanbul Nabız — make <target>:" && grep -hE '^[a-z][a-z0-9-]*:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

status:  ## what a new or resumed session must know first (read-only; no İBB call)
	@MCP_PORT=$(MCP_PORT) WEB_PORT=$(WEB_PORT) STATUS_MIN_FREE_GB=$(STATUS_MIN_FREE_GB) PY=$(PY) bash scripts/session_status.sh

venv:  ## create .venv on python 3.12 (uv)
	uv venv -p 3.12 .venv

install:  ## install project + dev tools into .venv, editable (EXTRAS=dev,web,collector for a tier)
	UV_HTTP_TIMEOUT=180 uv pip install --python $(PY) -e ".[$(EXTRAS)]"

test:  ## run the test suite (offline, no upstream calls, no Foundry Local probe; the same NABIZ_OFFLINE=1 CI sets)
	NABIZ_OFFLINE=1 NABIZ_LLM_NO_PROBE=1 $(PY) -m pytest -q

lint:  ## ruff lint — the check CI gates on
	$(RUFF) check $(SRC)

fmt:  ## WRITES every Python file: apply ruff format — advisory, CI only reports it
	$(RUFF) format $(SRC)

smoke:  ## build the MCP server offline: >= 12 tools, each with a real input schema
	NABIZ_OFFLINE=1 $(PY) .github/scripts/mcp_smoke.py

guardrails:  ## regression fences for incidents already had (plates, schemas, secrets, personal data, AI credit)
	NABIZ_OFFLINE=1 $(PY) scripts/guardrails.py

authorship:  ## check the commits a push would send: noreply identity, no AI trailer, no bot (AUTHORSHIP_RANGE=)
	$(PY) scripts/check_authorship.py $(AUTHORSHIP_RANGE)

architecture:  ## import layers, cycles, dependency sets; module, class and complexity ratchets (no network)
	$(PY) scripts/check_architecture.py

architecture-tighten:  ## WRITES scripts/architecture_baseline.json: lower the entries that shrank (never raises one)
	$(PY) scripts/check_architecture.py --tighten

perf-budgets:  ## upstream calls per tool, single flight, stale-on-error, work-once, cold start (no network)
	NABIZ_OFFLINE=1 $(PY) -m pytest -q tests/test_performance_budgets.py

perf-report:  ## the numbers behind the budgets, per tool: paste before and after with an optimisation (no network)
	NABIZ_OFFLINE=1 $(PY) scripts/perf_report.py

web-budget:  ## page bytes, render-blocking requests, fonts, motion, tokens, module sizes (no network)
	$(PY) scripts/check_web_budget.py

hooks:  ## once per clone: use .githooks/, so git push runs the authorship gate before anything is public
	git config core.hooksPath .githooks

ci-local:  ## run every CI gate on a clean copy of the working tree, untracked files included (CI_LOCAL_DIR=)
	bash .github/scripts/ci_local.sh

ci-commit:  ## run every CI gate on HEAD exactly as committed: what a push publishes (CI_LOCAL_DIR=)
	CI_LOCAL_REF=HEAD bash .github/scripts/ci_local.sh

lane-gates:  ## the sprint's gates for a lane branch (DECISIONS #26): tests, lint, architecture with ratchets as WARN, guardrails
	NABIZ_OFFLINE=1 NABIZ_LLM_NO_PROBE=1 NABIZ_SPRINT_MODE=1 $(PY) -m pytest -q -x
	$(RUFF) check $(SRC)
	NABIZ_SPRINT_MODE=1 $(MAKE) --no-print-directory architecture
	$(MAKE) --no-print-directory guardrails

mcp:  ## run the MCP server on stdio — the shape VS Code and Claude launch
	./.venv/bin/ibb-mcp

mcp-http:  ## run the MCP server on streamable HTTP — the shape Container Apps runs
	./.venv/bin/ibb-mcp --transport http --host $(MCP_HOST) --port $(MCP_PORT)

web:  ## serve the Nabız web UI on :8080 with reload (WEB_PORT=, needs the web extra)
	./.venv/bin/uvicorn nabiz.web.main:app --reload --no-access-log --port $(WEB_PORT)

console:  ## serve the product app: citizen face (/) and simulated-operator console (/console) on :8090 (CONSOLE_PORT=; reads .env)
	NABIZ_CONSOLE_PORT=$(CONSOLE_PORT) $(PY) -m nabiz.console

eval:  ## run the journey eval offline into reports/eval (gitignored); never writes eval/results (EVAL_ARGS='--mode agent')
	$(PY) eval/run_eval.py --offline --results-dir $(EVAL_OUT) $(EVAL_ARGS)

eval-knowledge:  ## validate the locked knowledge question set with fixed offline unknown answers
	$(PY) eval/run_knowledge_eval.py --questions eval/knowledge_questions.jsonl --offline

eval-record:  ## WRITES eval/results: an offline run kept as evidence (Integrator or owner only)
	$(PY) eval/run_eval.py --offline $(EVAL_ARGS)

eval-live:  ## NETWORK WRITES eval/results and latest.md: same harness against live İBB, capped at 8 upstream calls, run rarely
	$(PY) eval/run_eval.py $(EVAL_ARGS)

fixtures:  ## NETWORK WRITES tests/fixtures: re-record them from İBB — spends İETT budget, run rarely
	$(PY) scripts/capture_fixtures.py

places:  ## WRITES data/reference/places.csv: rebuild it from the recorded fixtures (no network)
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

collect-status:  ## what the collector has gathered so far, incl. the "ekipman" (Metro equipment) block (no network)
	$(PY) scripts/collect_forever.py --status

collect-stop:  ## OWNER stop the supervisor and the collector (pattern kill: stops every collector on this machine)
	@pkill -f supervise_collector.sh 2>/dev/null; pkill -f collect_forever.py && echo "collector stopped" || echo "no collector running"

collect-plan:  ## İETT arithmetic of the scheduled collector jobs: peak-hour requests vs the budget (no network)
	NABIZ_OFFLINE=1 $(PY) -m nabiz.collector.job --plan

# The laptop-era lake exists nowhere else. A worktree's data/lake is a symlink to the main tree's,
# and tar and find would archive and count the link, not the lake, so only a real directory is taken.
lake-backup:  ## OWNER archive data/lake and raw eval JSON to BACKUP_DIR and check the archive (no network)
	@test -n "$(BACKUP_DIR)" || { echo "set BACKUP_DIR to a private directory outside the repo and outside synced folders"; exit 2; }
	@[ -d data/lake ] && [ ! -L data/lake ] || { echo "data/lake is missing or a symlink: run this in the main checkout"; exit 2; }
	@dir=$$(cd "$(BACKUP_DIR)" 2>/dev/null && pwd -P) || { echo "BACKUP_DIR does not exist"; exit 2; }; \
	  here=$$(pwd -P); \
	  case "$$dir" in "$$here"|"$$here"/*) echo "BACKUP_DIR is inside the repository"; exit 2;; \
	    */Desktop|*/Desktop/*|*/Documents|*/Documents/*|*"Mobile Documents"*|*/Library/CloudStorage/*) \
	      echo "BACKUP_DIR is in a synced folder"; exit 2;; esac; \
	  archive="$$dir/nabiz-lake-$$(date -u +%Y%m%dT%H%MZ).tar.gz"; \
	  tar czf "$$archive" data/lake $$(ls eval/results/*.json 2>/dev/null) || exit 1; \
	  in_tar=$$(tar tzf "$$archive" | grep '^data/lake/' | grep -vc '/$$'); \
	  on_disk=$$(find data/lake -type f | wc -l | tr -d ' '); \
	  if [ "$$in_tar" = "$$on_disk" ]; then echo "lake-backup: $$archive ($$on_disk lake files)"; \
	  else echo "lake-backup: $$in_tar archived, $$on_disk on disk; the collector wrote meanwhile, run it again"; exit 1; fi

eta:  ## WRITES eval/results/eta.md: measure arrival-estimate error against observed arrivals (no network)
	$(PY) scripts/eta_report.py

eta-diagnose:  ## WRITES eval/results/eta.md: is the arrival error the model's fault or the measurement's? (no network)
	$(PY) scripts/eta_report.py --diagnose

eta-holdout:  ## replay the calibrated ETA profile on predictions made after it was fitted (no network)
	NABIZ_OFFLINE=1 $(PY) scripts/eta_holdout.py

warmup:  ## NETWORK prime the caches before recording a demo
	$(PY) scripts/warmup.py

clean:  ## delete caches and reports — keeps .venv, data/reference and fixtures
	rm -rf .pytest_cache .ruff_cache reports dist build && find . -path ./.venv -prune -o -name __pycache__ -type d -print0 | xargs -0 rm -rf
