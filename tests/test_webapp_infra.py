"""Offline contract checks for the proposed web image and Azure module."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BICEP = (ROOT / "infra/modules/webapp.bicep").read_text(encoding="utf-8")
DOCKERFILE = (ROOT / "infra/web/Dockerfile").read_text(encoding="utf-8")
IGNORE = (ROOT / "infra/web/.dockerignore").read_text(encoding="utf-8")


def missing_mount_parts(source: str) -> set[str]:
    """A fake provider contract: return missing storage bindings without calling Azure."""
    required = {
        "Microsoft.Storage/storageAccounts/fileServices/shares",
        "allowSharedKeyAccess: true",
        "Microsoft.App/managedEnvironments/storages",
        "accountKey: stateStorageKey",
        "storageType: 'AzureFile'",
        "storageName: stateMount.name",
        "mountPath: '/var/lib/nabiz'",
        "NEXUS_DB_PATH",
        "NABIZ_ACCOUNTS_DB",
        "NABIZ_REQUESTS_DB_PATH",
        "NABIZ_OUTBOX_DIR",
    }
    return {part for part in required if part not in source}


def test_fake_storage_provider_contract_catches_missing_mount() -> None:
    assert not missing_mount_parts(BICEP)
    assert "mountPath: '/var/lib/nabiz'" in missing_mount_parts(BICEP.replace("mountPath: '/var/lib/nabiz'", ""))
    assert "resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' =" in BICEP
    assert "accountName: storageAccount.name" in BICEP


def test_container_has_https_health_and_one_replica_limit() -> None:
    assert "Microsoft.App/containerApps@" in BICEP
    assert "external: true" in BICEP
    assert "allowInsecure: false" in BICEP
    assert "path: '/healthz'" in BICEP
    # tests/test_infra.py requires a literal scale-to-zero; one warm replica is a separate decision.
    assert "minReplicas: 0" in BICEP
    assert "param maxReplicas int = 1" in BICEP
    assert "maxReplicas: maxReplicas" in BICEP
    assert "@maxValue(1)" in BICEP


def test_budget_is_monthly_parameterized_and_advisory() -> None:
    assert "Microsoft.Consumption/budgets@" in BICEP
    assert "timeGrain: 'Monthly'" in BICEP
    assert "amount: budgetAmountUsd" in BICEP
    assert "budgetEarlyUsd * 100 / budgetAmountUsd" in BICEP
    assert "budgetLateUsd * 100 / budgetAmountUsd" in BICEP
    assert BICEP.count("contactRoles: ['Owner']") == 2
    assert "notifications" in BICEP
    # Microsoft.Consumption/budgets rejects a start date that is not the first of a month.
    assert "utcNow('yyyy-MM-01T00:00:00Z')" in BICEP


def test_model_and_operator_values_are_secret_references_only() -> None:
    assert BICEP.count("@secure()") == 5
    # No key is read by the template; without the operator-supplied key there is no web app.
    assert "listKeys" not in BICEP
    assert "resource web 'Microsoft.App/containerApps@2024-03-01' = if (hasStateKey)" in BICEP
    assert "NABIZ_CONSOLE_TOKEN', secretRef: 'operator-token'" in BICEP
    for key, secret in (
        ("NABIZ_LLM_BASE_URL", "model-base-url"),
        ("NABIZ_LLM_MODEL", "model-name"),
        ("NABIZ_LLM_API_KEY", "model-api-key"),
    ):
        assert f"{key}', secretRef: '{secret}'" in BICEP
        assert f"{key}', value:" not in BICEP
    assert "NABIZ_LLM_NO_PROBE" in BICEP
    assert "param offlineMode bool = true" in BICEP
    assert "NABIZ_LADDER_LOCAL_ON_CAP" in BICEP
    assert "param modelDailyCalls int = 0" in BICEP
    assert "param arenaDailyCalls int = 0" in BICEP
    assert "param modelDailyUsd string = '0'" in BICEP
    assert "param arenaDailyUsd string = '0'" in BICEP
    assert "NABIZ_ENV_FILE', value: '/dev/null'" in BICEP
    assert "localhost:5273" not in BICEP


def test_docker_image_is_product_app_with_safe_defaults() -> None:
    assert "FROM python:3.12-slim AS build" in DOCKERFILE
    assert 'pip install --no-cache-dir ".[web]"' in DOCKERFILE
    assert "COPY missions/ ./missions/" in DOCKERFILE
    assert "COPY tests/fixtures/ ./tests/fixtures/" in DOCKERFILE
    assert "USER nabiz" in DOCKERFILE
    assert "NABIZ_ENV_FILE=/dev/null" in DOCKERFILE
    assert "NABIZ_OFFLINE=1" in DOCKERFILE
    assert "NABIZ_LLM_NO_PROBE=1" in DOCKERFILE
    assert "NABIZ_LLM_DAILY_CALLS=0" in DOCKERFILE
    assert "NEXUS_DB_PATH=/var/lib/nabiz/" in DOCKERFILE
    assert 'CMD ["python", "-m", "nabiz.console"]' in DOCKERFILE
    assert "HEALTHCHECK" in DOCKERFILE


def test_build_context_denies_secrets_and_private_databases() -> None:
    assert IGNORE.splitlines()[1] == "*"
    for pattern in ("**/.env", "**/.env.*", "**/*.db", "**/*.sqlite", "**/*.sqlite3"):
        assert pattern in IGNORE
    assert "COPY ." not in DOCKERFILE


def test_release_remains_closed_without_account_approval() -> None:
    assert "param containerImage string" in BICEP
    assert "param operatorToken string = ''" in BICEP
    assert "param modelBaseUrl string = ''" in BICEP
    assert "param modelName string = ''" in BICEP
    assert "param modelApiKey string = ''" in BICEP
    assert "param stateStorageKey string = ''" in BICEP


def test_main_calls_the_web_module_only_when_switched_on_and_passes_no_model_value() -> None:
    """P00 D2a: the closed preparation. Off by default in main.bicep and in the azd parameters."""
    import json

    main = (ROOT / "infra/main.bicep").read_text(encoding="utf-8")
    params = json.loads((ROOT / "infra/main.parameters.json").read_text(encoding="utf-8"))["parameters"]
    assert "param deployWebApp bool = false" in main
    assert "var deployWeb = deployWebApp && deployContainerApp && !empty(webContainerImage)" in main
    assert "module webapp 'modules/webapp.bicep' = if (deployWeb) {" in main
    call = main[main.index("module webapp 'modules/webapp.bicep'"):]
    call = call[:call.index("\n}\n")]
    assert "stateStorageKey: webStateStorageKey" in call and "operatorToken: operatorToken" in call
    assert not any(name in call for name in ("modelBaseUrl", "modelName", "modelApiKey", "DailyCalls", "DailyUsd"))
    assert params["deployWebApp"] == {"value": "${DEPLOY_WEB_APP=false}"}
    assert params["webStateStorageKey"] == {"value": "${NABIZ_WEB_STATE_KEY=}"}
    deploy = (ROOT / "docs/deploy.md").read_text(encoding="utf-8")
    assert deploy.index("## Web app (closed preparation)") < deploy.index("## 9. Troubleshooting")


def test_every_file_the_app_writes_is_on_the_share() -> None:
    """P00 D2a (I): each store variable the console reads is set under /var/lib/nabiz, or is read-only data."""
    import re

    names = set()
    variable = re.compile(r"\"((?:NABIZ|NEXUS)_[A-Z_]*(?:_DB|_DB_PATH|_DIR|_PATH|_FILE))\"")
    for path in (ROOT / "src/nabiz/console").glob("*.py"):
        names |= set(variable.findall(path.read_text(encoding="utf-8")))
    shipped = {  # read-only data baked into the image, never written at run time
        "NABIZ_AGENCIES_PATH", "NABIZ_EVENTS_PATH", "NABIZ_IBB_PLACES_DIR", "NABIZ_SKILLS_DATA_DIR", "NABIZ_ENV_FILE",
        "NEXUS_MISSIONS_DIR",
    }
    for name in sorted(names - shipped):
        assert re.search(rf"name: '{name}', value: '/var/lib/nabiz/", BICEP), name
    assert "name: 'NABIZ_DATA_ROOT', value: '/var/lib/nabiz' }" in BICEP
