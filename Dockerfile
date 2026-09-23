# İstanbul Nabız — one image, two uses on Azure Container Apps:
#
#   * the `ibb-mcp` MCP server (the CMD below): streamable HTTP on :8000, scale to zero;
#   * the collector jobs (DECISIONS #10), which run the same image with the command
#     `python -m nabiz.collector.job --sources ...` set in infra/modules/collectorjobs.bicep.
#
#     azd deploy mcp                                    # builds in ACR; no local daemon
#     docker build -t ibb-mcp .                         # local build, native architecture
#     docker build --platform linux/amd64 -t ibb-mcp .  # local build of what Azure runs
#
# ONE IMAGE rather than two, because the collector is the same code base reading the same
# reference data, and azd builds one image per service: a second image would mean a second
# service and a second remote build of the same tree on every deploy. The price is the Azure
# Storage and ADX client libraries in the MCP server's image, which it never imports.
#
# ARCHITECTURE. Nothing here pins a platform, and that is the decision rather than an
# omission. `azure.yaml` sets `remoteBuild: true`, so azd builds this file inside Azure
# Container Registry on a linux/amd64 agent and the image comes out right without anyone
# declaring it. `FROM --platform=linux/amd64 …` would instead fix the platform for every
# build including that remote one, and would push a laptop build through QEMU emulation
# for no reason. The arm64 hazard is the opposite one and it is real: a plain `docker build`
# on an arm64 laptop produces an arm64 image that Container Apps accepts and then cannot
# start ("exec format error"), so pass `--platform` on the command line when you build
# locally for Azure.
#
# TWO STAGES, because the build needs pip, hatchling and the source tree, and the running
# containers need none of them. The first stage installs the project into a virtualenv; the
# second copies that virtualenv and the reference data, and nothing else. What is not in
# the image cannot be exploited and does not have to be patched.
#
# Not verified by building: no Docker daemon exists on the development machine and `azd` is
# not installed there, so the first real build is the owner's `azd deploy mcp`
# (docs/deploy.md §4). tests/test_collector_job.py checks, offline, the parts of this file
# the collector jobs depend on.

# --------------------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------------------
FROM python:3.12-slim AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore

WORKDIR /src

# Manifest first, source second: the layer cache then survives every edit to the Python
# that does not also change the dependency list.
#
# README.md, LICENSE and NOTICE.md are build inputs rather than documentation here:
# pyproject.toml names README.md as `readme`, and hatchling fails a build that cannot find
# a file the metadata names. So is data/reference/: the wheel force-includes the gazetteer,
# the occupancy profile, the ETA profile and the line-reliability table
# (pyproject.toml), so leaving it out fails the build before a dependency is downloaded.
# Those packaged copies are what ibb_mcp.config.reference_path falls back to inside the
# installed package, where no checkout exists.
COPY pyproject.toml README.md LICENSE NOTICE.md ./
COPY src/ ./src/
COPY data/reference/ ./data/reference/

# Into a virtualenv rather than the system interpreter, so the runtime stage can take the
# whole installation as one directory.
#
# `.[job]` is the project plus the optional `job` extra: the Azure identity, Blob Storage
# and ADX client libraries the collector writes with. Without them a collector job starts,
# reads İBB, and then fails every write — so the import below fails the BUILD instead,
# which is the cheaper place to find out. (pip only warns about an unknown extra, which is
# why the explicit import check is needed at all.)
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir ".[job]" \
 && /opt/venv/bin/python -c "import azure.identity, azure.storage.blob, azure.kusto.data, azure.kusto.ingest"

# --------------------------------------------------------------------------------------
# runtime
# --------------------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# A system user with no login shell. Neither the server nor a collector job needs root:
# they read reference files, speak HTTP, and authenticate to Azure with a managed identity.
RUN useradd --system --create-home --uid 10001 --shell /usr/sbin/nologin nabiz

# NABIZ_GTFS_DIR and NABIZ_PLACES_CSV are the values infra/modules/containerapps.bicep also
# sets on the MCP app. The collector jobs set neither and rely on these: the ETA prediction
# log (nabiz.collector.eta_log) loads the GTFS index from NABIZ_GTFS_DIR, and inside an
# installed package the default path would point into site-packages, where there is no
# GTFS. Everything else read at startup (NABIZ_OFFLINE, NABIZ_RADIUS_KM, NABIZ_MAX_RESULTS,
# NABIZ_FIXTURES_DIR) has a working default in ibb_mcp.config.Settings.
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NABIZ_GTFS_DIR=/app/data/reference/gtfs \
    NABIZ_PLACES_CSV=/app/data/reference/places.csv

COPY --from=build /opt/venv /opt/venv

WORKDIR /app

# places.csv (the gazetteer), occupancy_profile.json (the parking history İBB does not
# publish) and the other committed reference files come in with this line. So does
# data/reference/gtfs/ when it exists — and that is the part worth being honest about:
#
# GTFS is gitignored and large: 176 MB on the development machine, of which the server and
# the ETA log read about 2.4 MB — stops.csv, routes.csv and the pre-built
# route_sequences.json.gz. .dockerignore keeps stop_times.txt, stop_times.csv and trips.csv
# out of the build context; they are inputs to `make sequences`, and excluding them also
# means a scale-to-zero container can never fall into ibb_mcp.gtfs.build_stop_sequences
# and start parsing a 150 MB file.
#
# Remote build uploads the local working tree, so the image has GTFS only if the machine
# running `azd deploy` has it. Without it the server still starts and serves every tool
# except the two GTFS-backed ones, and the collector jobs still record positions — but the
# ETA prediction log stays empty and every `lines` execution logs an ERROR saying so. The
# build step below says which image you got.
#
# Taken from the build stage rather than from the context a second time, so the files the
# wheel was built against and the files read at runtime are the same bytes.
COPY --from=build /src/data/reference/ ./data/reference/

RUN if [ -f /app/data/reference/gtfs/stops.csv ] && [ -f /app/data/reference/gtfs/routes.csv ]; then \
        echo "GTFS reference present in the image"; \
    else \
        echo "WARNING: no GTFS reference under /app/data/reference/gtfs - iett_stops_search, iett_next_arrivals and the collector's ETA log will not work"; \
    fi

USER nabiz

# 8000 because that is the ingress targetPort in infra/modules/containerapps.bicep
# (`var containerPort = 8000`). The collector jobs have no ingress and ignore it.
EXPOSE 8000

# A liveness probe for `docker run` and any runtime that honours HEALTHCHECK. Container
# Apps does not read this instruction (it has its own `probes`, declared on the ibb-mcp
# app in infra/modules/containerapps.bicep against the same path), and it never applies to
# the jobs. /healthz answers from process state alone and never calls İBB — a probe every
# 30 s against a gateway that 503s after ~15 rapid calls would be a self-inflicted outage.
# tests/test_server_security.py checks that this path is the one the server serves.
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).read()"]

# `ibb-mcp` is the console script declared in pyproject.toml [project.scripts]; exec form,
# so the server is PID 1 and receives the platform's SIGTERM directly instead of through a
# shell that would swallow it and turn every scale-to-zero into a 30 s kill. The collector
# jobs replace this with their own command and arguments.
CMD ["ibb-mcp", "--transport", "http", "--host", "0.0.0.0", "--port", "8000"]
