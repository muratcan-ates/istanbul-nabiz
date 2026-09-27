# Build from the reviewed, tracked-file context described in docs/deploy.md (web section).
FROM python:3.12-slim AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1 PIP_ROOT_USER_ACTION=ignore
WORKDIR /src
COPY pyproject.toml README.md LICENSE NOTICE.md ./
COPY src/ ./src/
COPY data/reference/ ./data/reference/
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir ".[web]" \
 && /opt/venv/bin/python -c "import fastapi, uvicorn, nabiz.console.app"

FROM python:3.12-slim AS runtime
RUN useradd --system --create-home --uid 10001 --shell /usr/sbin/nologin nabiz \
 && mkdir -p /app /var/lib/nabiz \
 && chown nabiz:nabiz /var/lib/nabiz
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
# REPO_ROOT resolves through /app/src in existing modules.
COPY src/ ./src/
COPY missions/ ./missions/
COPY data/ ./data/
COPY tests/fixtures/ ./tests/fixtures/
COPY LICENSE NOTICE.md ./
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NABIZ_ENV_FILE=/dev/null \
    NABIZ_HOST=0.0.0.0 \
    NABIZ_CONSOLE_PORT=8090 \
    NABIZ_OFFLINE=1 \
    NABIZ_LLM_NO_PROBE=1 \
    NABIZ_LADDER_LOCAL_ON_CAP=0 \
    NABIZ_LLM_DAILY_CALLS=0 \
    NABIZ_ARENA_DAILY_CALLS=0 \
    NABIZ_LLM_DAILY_USD=0 \
    NABIZ_ARENA_DAILY_USD=0 \
    NABIZ_FIXTURES_DIR=/app/tests/fixtures \
    NABIZ_GTFS_DIR=/app/tests/fixtures/gtfs_mini \
    NABIZ_PLACES_CSV=/app/data/reference/places.csv \
    NEXUS_MISSIONS_DIR=/app/missions \
    NEXUS_DB_PATH=/var/lib/nabiz/nexus/nexus.db \
    NABIZ_ACCOUNTS_DB=/var/lib/nabiz/accounts/accounts.sqlite \
    NABIZ_REQUESTS_DB_PATH=/var/lib/nabiz/nexus/citizen_requests.db \
    NABIZ_CHAT_PAUSE_PATH=/var/lib/nabiz/nexus/chat_paused.json \
    NABIZ_LLM_SPEND_FILE=/var/lib/nabiz/console/llm_spend.json \
    NABIZ_OUTBOX_DIR=/var/lib/nabiz/outbox \
    NABIZ_LAKE_DIR=/var/lib/nabiz/lake \
    NABIZ_KNOWLEDGE_DB=/var/lib/nabiz/knowledge/knowledge.db \
    NABIZ_AGENCIES_PATH=/app/data/agencies.json \
    NABIZ_HOW_ROOT=/app
USER nabiz
EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import json,urllib.request; r=json.load(urllib.request.urlopen('http://127.0.0.1:8090/healthz',timeout=2)); assert r['status']=='ok'"]
CMD ["python", "-m", "nabiz.console"]
