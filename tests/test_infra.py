"""Offline assertions over `infra/` and `azure.yaml` — the mistakes that cost money.

Nothing here contacts Azure, and nothing here needs `az`, `azd` or the Bicep compiler:
none of the three is installed on the development machine, and the compiler only runs in
CI. That leaves a gap this file fills. `az bicep build` proves a template *compiles*; it
has no opinion about whether the thing it compiles is affordable, reachable by azd, or
allowed on an Azure for Students subscription. Those are the failures that hurt here — a
Container App without ``minReplicas: 0`` bills for 168 idle hours a week, an AI Search
Basic account is ~$2.42/day whether or not anybody queries it (NABIZ.md §1.6), and a
service azd cannot find by tag is a service that silently never gets deployed.

The Bicep reader below is deliberately small: enough structure to answer the questions
these tests ask, and no attempt at being a compiler. Where it cannot decide something it
says so by skipping rather than by guessing, because a checker that passes for the wrong
reason is worse than no checker. The same goes for `azure.yaml`: PyYAML is not a
dependency of this project and adding one to read eleven lines would be a poor trade, so
the service names are read with an indentation-aware scan that asserts the shape it
expects instead of assuming it.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
INFRA_DIR = REPO_ROOT / "infra"
MAIN_BICEP = INFRA_DIR / "main.bicep"
PARAMETERS_JSON = INFRA_DIR / "main.parameters.json"
AZURE_YAML = REPO_ROOT / "azure.yaml"

# `uniqueString()` always returns thirteen characters of lowercase base-32. Every
# globally-unique name in this template is built from it, so the longest name a
# deployment can produce is computable without deploying anything.
UNIQUE_STRING_LENGTH = 13

# `@maxLength(24)` on main.bicep's environmentName. Asserted below rather than trusted,
# because the resource-group name is the one name derived from it.
ENVIRONMENT_NAME_MAX = 24


# ---------------------------------------------------------------------------------------
# A very small Bicep reader
# ---------------------------------------------------------------------------------------


def strip_comments(text: str) -> str:
    """Blank out `//` and `/* */` comments, leaving string literals and offsets intact.

    Offsets are preserved (comments become spaces, newlines survive) so a match found in
    the stripped text still points at the right line of the original. Stripping matters
    more than it looks: `infra/main.bicep` *documents* Azure AI Search and Stream
    Analytics in a comment explaining why they are not deployed, and a test that grepped
    the raw file for forbidden services would fail on the very comment that promises they
    are absent.
    """
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "'":
            # Bicep strings are single-quoted; `\'` escapes a quote inside one.
            out.append(ch)
            i += 1
            while i < n and text[i] != "'":
                if text[i] == "\\" and i + 1 < n:
                    out.append(text[i])
                    i += 1
                out.append(text[i])
                i += 1
            if i < n:
                out.append(text[i])
                i += 1
            continue
        if text.startswith("//", i):
            while i < n and text[i] != "\n":
                out.append(" ")
                i += 1
            continue
        if text.startswith("/*", i):
            while i < n and not text.startswith("*/", i):
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
            out.append("  ")
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def matching_brace(text: str, open_index: int) -> int:
    """Index of the `}` closing the `{` at ``open_index``, ignoring braces in strings."""
    assert text[open_index] == "{", text[open_index : open_index + 20]
    depth, i, n = 0, open_index, len(text)
    while i < n:
        ch = text[i]
        if ch == "'":
            i += 1
            while i < n and text[i] != "'":
                i += 2 if text[i] == "\\" else 1
            i += 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise AssertionError(f"unbalanced braces from offset {open_index}")


def top_level_entries(block: str) -> dict[str, str]:
    """Split the inside of a `{ ... }` block into its depth-0 `key: value` pairs."""
    entries: dict[str, str] = {}
    depth, i, n = 0, 0, len(block)
    key: str | None = None
    start = 0
    while i < n:
        ch = block[i]
        if ch == "'":
            i += 1
            while i < n and block[i] != "'":
                i += 2 if block[i] == "\\" else 1
            i += 1
            continue
        if ch in "{[(":
            depth += 1
        elif ch in "}])":
            depth -= 1
        elif ch == ":" and depth == 0 and key is None:
            key = block[start:i].strip()
            start = i + 1
        elif ch == "\n" and depth == 0 and key is not None:
            entries[key] = block[start:i].strip()
            key, start = None, i + 1
        i += 1
    if key is not None and block[start:].strip():
        entries[key] = block[start:].strip()
    return {k: v for k, v in entries.items() if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k)}


PARAM_RE = re.compile(r"^param\s+([A-Za-z_][A-Za-z0-9_]*)\s+(\w+)(\s*=)?", re.MULTILINE)
OUTPUT_RE = re.compile(r"^output\s+([A-Za-z_][A-Za-z0-9_]*)\s+(\w+)\s*=", re.MULTILINE)
MODULE_RE = re.compile(r"^module\s+([A-Za-z_][A-Za-z0-9_]*)\s+'([^']+)'\s*=", re.MULTILINE)
RESOURCE_RE = re.compile(r"^resource\s+([A-Za-z_][A-Za-z0-9_]*)\s+'([^']+)'\s*(existing\s*)?=", re.MULTILINE)


class Bicep:
    """One `.bicep` file, read far enough to answer the questions below."""

    def __init__(self, path: pathlib.Path) -> None:
        self.path = path
        self.raw = path.read_text(encoding="utf-8")
        self.code = strip_comments(self.raw)
        # name -> declared type, and the subset that has no default (so: required).
        self.params: dict[str, str] = {}
        self.required: set[str] = set()
        for match in PARAM_RE.finditer(self.code):
            name, kind, default = match.group(1), match.group(2), match.group(3)
            self.params[name] = kind
            if not default:
                self.required.add(name)
        self.outputs: dict[str, str] = {m.group(1): m.group(2) for m in OUTPUT_RE.finditer(self.code)}

    def module_calls(self) -> dict[str, tuple[str, dict[str, str]]]:
        """symbol -> (module path, {parameter name: argument expression})."""
        calls: dict[str, tuple[str, dict[str, str]]] = {}
        for match in MODULE_RE.finditer(self.code):
            body_start = self.code.index("{", match.end())
            body = self.code[body_start + 1 : matching_brace(self.code, body_start)]
            params_expr = top_level_entries(body).get("params", "")
            args: dict[str, str] = {}
            if params_expr.startswith("{"):
                # Locate the params block by offset in the whole file, not in the slice, so
                # brace matching sees balanced text either side of it.
                inner_start = body_start + 1 + body.index("{", body.index("params"))
                args = top_level_entries(self.code[inner_start + 1 : matching_brace(self.code, inner_start)])
            calls[match.group(1)] = (match.group(2), args)
        return calls

    def resources(self) -> list[tuple[str, str, str]]:
        """(symbol, type@apiVersion, name expression) for every resource actually deployed."""
        found: list[tuple[str, str, str]] = []
        for match in RESOURCE_RE.finditer(self.code):
            if match.group(3):  # `existing` — a reference, not a deployment
                continue
            body_start = self.code.index("{", match.end())
            body = self.code[body_start + 1 : matching_brace(self.code, body_start)]
            found.append((match.group(1), match.group(2), top_level_entries(body).get("name", "")))
        return found


def bicep_files() -> list[pathlib.Path]:
    return sorted(INFRA_DIR.rglob("*.bicep"))


@pytest.fixture(scope="module")
def templates() -> dict[pathlib.Path, Bicep]:
    files = bicep_files()
    assert files, "infra/ holds no .bicep files — this suite would pass vacuously"
    return {path: Bicep(path) for path in files}


@pytest.fixture(scope="module")
def main(templates: dict[pathlib.Path, Bicep]) -> Bicep:
    return templates[MAIN_BICEP]


# ---------------------------------------------------------------------------------------
# azd wiring: a service azd cannot find is a service that never deploys
# ---------------------------------------------------------------------------------------


def azure_yaml_services() -> list[str]:
    """Service names under `services:` in azure.yaml, read without a YAML parser.

    Small on purpose — PyYAML is not a dependency and this file has one nested mapping.
    The scan asserts the shape it relies on instead of quietly returning nothing when
    azure.yaml is reorganised.
    """
    lines = AZURE_YAML.read_text(encoding="utf-8").splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.rstrip() == "services:")
    except StopIteration:  # pragma: no cover - defended by the assertion in the test
        return []
    names: list[str] = []
    for line in lines[start + 1 :]:
        if line.strip() and not line.startswith((" ", "\t")):
            break  # back to column 0: the services block is over
        match = re.fullmatch(r"  ([A-Za-z0-9_-]+):\s*", line)
        if match:
            names.append(match.group(1))
    return names


def test_every_azure_yaml_service_has_a_matching_bicep_tag(templates: dict[pathlib.Path, Bicep]) -> None:
    """azd maps a service to its resource by the `azd-service-name` tag, and only by that.

    Miss the tag and `azd deploy` fails with "resource not found for service", after
    `azd provision` has already created everything — the most annoying possible time.
    """
    services = azure_yaml_services()
    assert services, "no services parsed out of azure.yaml — the parser or the file changed shape"

    tagged: dict[str, pathlib.Path] = {}
    for path, template in templates.items():
        for value in re.findall(r"'azd-service-name'\s*:\s*'([^']+)'", template.code):
            tagged[value] = path

    missing = sorted(set(services) - set(tagged))
    assert not missing, f"azure.yaml services with no azd-service-name tag in infra/: {missing}"

    # And the other direction: a tag naming a service azure.yaml does not declare is a
    # resource azd will never deploy to, which reads as "the deploy silently did nothing".
    orphans = sorted(set(tagged) - set(services))
    assert not orphans, f"azd-service-name tags with no matching service in azure.yaml: {orphans}"


# ---------------------------------------------------------------------------------------
# Cost: the assertions that keep a student subscription alive
# ---------------------------------------------------------------------------------------


def test_container_app_scales_to_zero(templates: dict[pathlib.Path, Bicep]) -> None:
    """`minReplicas: 0` is the whole reason Container Apps was chosen over App Service.

    One replica pinned at 0.5 vCPU / 1 GiB runs 168 hours a week whether or not anyone
    calls it. At zero, the idle week is free (the Consumption free grant covers the rest)
    and a caller pays a cold start instead.
    """
    apps = [
        (path, template)
        for path, template in templates.items()
        for _symbol, kind, _name in template.resources()
        if kind.startswith("Microsoft.App/containerApps@")
    ]
    assert apps, "no Microsoft.App/containerApps resource found — has the MCP server moved hosts?"
    for path, template in apps:
        assert re.search(r"\bminReplicas\s*:\s*0\b", template.code), (
            f"{path.name} declares a container app without minReplicas: 0 — it would bill while idle"
        )


# (pattern, why it must never appear). The rules come from NABIZ.md §1.6 and from the
# cost table in docs/deploy.md §7 — a student subscription that runs out of credit is
# disabled outright, so "expensive" here means "ends the project", not "is untidy".
FORBIDDEN: list[tuple[str, str]] = [
    (r"Microsoft\.Search/", "AI Search Basic is ~$2.42/day even idle, and there is no retrieval layer to justify it"),
    (r"Microsoft\.StreamAnalytics/", "Stream Analytics has no free tier; the scheduled collector jobs do the same job"),
    (r"Microsoft\.DataFactory/", "Data Factory data flows bill per vCore-hour"),
    (r"Microsoft\.Kusto/", "the ADX free cluster has no ARM provider, so a Microsoft.Kusto resource is a real billed cluster"),
    (r"Microsoft\.DocumentDB/", "Cosmos DB provisioned throughput bills hourly and nothing here needs it"),
    # SKU names rather than resource types: the same resource at the wrong tier is the
    # easier mistake to make and the harder one to notice.
    (r"name\s*:\s*'(Premium|Standard)'", "a container registry above Basic, which is already the largest line item"),
    (r"name\s*:\s*'(B[1-3]|S[1-3]|P[0-3]v[1-4]|EP[1-3]|Y1)'", "an App Service or Elastic Premium plan billed per hour"),
    (r"name\s*:\s*'CapacityReservation'", "a Log Analytics daily commitment; PerGB2018 stays inside the 5 GB free grant"),
    (r"name\s*:\s*'Standard_(GRS|RAGRS|GZRS|RAGZRS)'", "geo-redundancy doubles the bill to replicate a cache of public data"),
    (r"name\s*:\s*'Premium_[A-Z]+'", "premium storage is provisioned capacity, billed whether or not it is used"),
    (r"workloadProfileType", "a Container Apps workload profile bills per hour; Consumption-only is what the free grant covers"),
]


@pytest.mark.parametrize(("pattern", "why"), FORBIDDEN, ids=[p[:28] for p, _ in FORBIDDEN])
def test_no_forbidden_service_or_sku_anywhere_in_infra(templates: dict[pathlib.Path, Bicep], pattern: str, why: str) -> None:
    """Comments are stripped first — main.bicep names these services to explain their absence."""
    hits = [
        f"{path.name}:{template.code[: match.start()].count(chr(10)) + 1}"
        for path, template in templates.items()
        for match in re.finditer(pattern, template.code)
    ]
    assert not hits, f"{hits}: {why}"


def test_no_key_or_sas_is_ever_read_by_a_template(templates: dict[pathlib.Path, Bicep]) -> None:
    """ "No secret in the template" is a checked property here, not a stated intention.

    Every component authenticates with a managed identity, and the storage account has
    shared-key access disabled. A `listKeys()` that crept in would put an account key into
    a deployment output and therefore into `.azure/<env>/.env` — in a public repository.
    """
    for path, template in templates.items():
        for call in ("listKeys", "listAccountSas", "listServiceSas", "listConnectionStrings"):
            assert call not in template.code, f"{path.name} calls {call}() — that puts a live secret in a template output"
        assert not re.search(r"adminUserEnabled\s*:\s*true", template.code), (
            f"{path.name} enables the registry admin user, which creates a registry password"
        )


# ---------------------------------------------------------------------------------------
# Wiring between main.bicep and its modules
# ---------------------------------------------------------------------------------------


def test_module_calls_satisfy_the_module_contract(main: Bicep, templates: dict[pathlib.Path, Bicep]) -> None:
    """Every module call passes each required parameter, and invents none.

    `az bicep build` catches this too — but only in CI, on a push, minutes later. Here it
    is a second of pytest, which is where a wiring mistake is cheapest to find.
    """
    problems: list[str] = []
    for symbol, (relative, args) in main.module_calls().items():
        module_path = (MAIN_BICEP.parent / relative).resolve()
        assert module_path in templates, f"module {symbol} points at {relative}, which does not exist"
        module = templates[module_path]
        for missing in sorted(module.required - set(args)):
            problems.append(f"{symbol}: required parameter '{missing}' of {relative} is never passed")
        for unknown in sorted(set(args) - set(module.params)):
            problems.append(f"{symbol}: passes '{unknown}', which {relative} does not declare")
    assert not problems, problems


def test_every_module_output_reference_resolves(main: Bicep, templates: dict[pathlib.Path, Bicep]) -> None:
    """`<module>.outputs.<name>` must name an output the module actually declares."""
    modules = {symbol: (MAIN_BICEP.parent / relative).resolve() for symbol, (relative, _) in main.module_calls().items()}
    problems: list[str] = []
    for symbol, output in re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\.outputs\.([A-Za-z_][A-Za-z0-9_]*)", main.code):
        if symbol not in modules:
            problems.append(f"'{symbol}.outputs.{output}' refers to no module declared in main.bicep")
        elif output not in templates[modules[symbol]].outputs:
            problems.append(f"{modules[symbol].name} declares no output '{output}' (read as {symbol}.outputs.{output})")
    assert not problems, problems


ARRAY_PRODUCING = ("concat(", "union(", "array(", "split(", "range(", "skip(", "take(", "items(", "filter(", "map(", "sort(")


def split_ternary(expression: str) -> tuple[str, str] | None:
    """Return the two branches of a depth-0 `cond ? a : b`, or None if it is not one."""
    depth, i, n = 0, 0, len(expression)
    question = -1
    while i < n:
        ch = expression[i]
        if ch == "'":
            i += 1
            while i < n and expression[i] != "'":
                i += 2 if expression[i] == "\\" else 1
        elif ch in "{[(":
            depth += 1
        elif ch in "}])":
            depth -= 1
        elif depth == 0 and ch == "?" and question < 0:
            question = i
        elif depth == 0 and ch == ":" and question >= 0:
            return expression[question + 1 : i].strip(), expression[i + 1 :].strip()
        i += 1
    return None


def looks_like_array(expression: str, main: Bicep, templates: dict[pathlib.Path, Bicep]) -> bool | None:
    """True / False / None, where None means "this reader cannot tell" — never a guess."""
    expression = expression.strip()
    branches = split_ternary(expression)
    if branches is not None:
        verdicts = [looks_like_array(branch, main, templates) for branch in branches]
        if None in verdicts:
            return None
        return all(verdicts)
    if expression.startswith("["):
        return True
    if expression.startswith(ARRAY_PRODUCING):
        return True
    reference = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)\.outputs\.([A-Za-z_][A-Za-z0-9_]*)", expression)
    if reference:
        symbol, output = reference.groups()
        calls = main.module_calls()
        if symbol in calls:
            module = templates.get((MAIN_BICEP.parent / calls[symbol][0]).resolve())
            if module and output in module.outputs:
                return module.outputs[output] == "array"
        return None
    if expression in main.params:
        return main.params[expression] == "array"
    return None


def test_array_parameters_are_passed_array_expressions(main: Bicep, templates: dict[pathlib.Path, Bicep]) -> None:
    """A ternary that yields a bare string for an `array` parameter does not compile.

    The shape to watch for is `cond ? module.outputs.someId : []`: it reads naturally, and
    both `az bicep build` and every reviewer's eye slide over it, because the `[]` branch
    looks like it settles the type. It does not — Bicep checks both branches, so the
    template fails to compile whatever the flag is set to, and nothing downstream of the
    compile ever runs. Unknown expressions are skipped rather than assumed correct; the
    count of what was actually checked is asserted so this cannot decay into a no-op.
    """
    checked = 0
    problems: list[str] = []
    for symbol, (relative, args) in main.module_calls().items():
        module = templates[(MAIN_BICEP.parent / relative).resolve()]
        for name, expression in args.items():
            if module.params.get(name) != "array":
                continue
            verdict = looks_like_array(expression, main, templates)
            if verdict is None:
                continue
            checked += 1
            if not verdict:
                problems.append(f"{symbol}.{name} = `{expression}` is not an array, but {relative} declares it `array`")
    assert not problems, problems
    assert checked, "no array-typed module argument was checked — the reader stopped understanding this template"


#: Log Analytics' free grant, GB per billing account per month, and the longest month.
LOG_FREE_GRANT_GB = 5
LONGEST_MONTH_DAYS = 31


def test_the_default_log_cap_fits_the_free_grant_even_when_hit_every_day() -> None:
    """A cap that is hit every day must still land inside the 5 GB/month grant.

    The first version capped ingestion at 0.5 GB/day and called that "under the free grant":
    15.5 GB in a 31-day month, about $31 past the grant at $2.99/GB (West Europe, Azure
    Retail Prices API, 2026-09-23) — as much as the collector jobs' own ceiling, and in no
    cost table. Both the Bicep default and the azd default are checked, since either wins.
    """
    bicep_default = re.search(r"^param dailyLogCapGb string = '([0-9.]+)'", MAIN_BICEP.read_text(encoding="utf-8"), re.M)
    assert bicep_default, "main.bicep no longer declares dailyLogCapGb with a literal default"
    azd_value = json.loads(PARAMETERS_JSON.read_text(encoding="utf-8"))["parameters"]["dailyLogCapGb"]["value"]
    azd_default = re.fullmatch(r"\$\{NABIZ_DAILY_LOG_CAP_GB=([0-9.]+)\}", azd_value)
    assert azd_default, f"main.parameters.json dailyLogCapGb is {azd_value!r}, expected an azd default"
    for where, cap in (("main.bicep", bicep_default.group(1)), ("main.parameters.json", azd_default.group(1))):
        monthly = float(cap) * LONGEST_MONTH_DAYS
        assert monthly <= LOG_FREE_GRANT_GB, f"{where}: {cap} GB/day is {monthly:.2f} GB in a 31-day month, past the 5 GB grant"


def test_parameters_file_covers_main_bicep_exactly(main: Bicep) -> None:
    """`main.parameters.json` must supply every required parameter and invent none.

    A missing one makes `azd provision` prompt interactively half way through; an invented
    one is rejected by ARM only after the resource group has already been created.
    """
    supplied = set(json.loads(PARAMETERS_JSON.read_text(encoding="utf-8"))["parameters"])
    assert not main.required - supplied, f"main.parameters.json never supplies: {sorted(main.required - supplied)}"
    invented = sorted(supplied - set(main.params))
    assert not invented, f"main.parameters.json supplies parameters main.bicep does not declare: {invented}"


# ---------------------------------------------------------------------------------------
# Generated names: the length limits that only fail at deployment time
# ---------------------------------------------------------------------------------------

# type prefix -> (maximum name length, characters Azure allows)
NAME_RULES: dict[str, tuple[int, str]] = {
    "Microsoft.Storage/storageAccounts": (24, r"[a-z0-9]"),
    "Microsoft.ContainerRegistry/registries": (50, r"[a-zA-Z0-9]"),
    "Microsoft.App/containerApps": (32, r"[a-z0-9-]"),
    "Microsoft.App/managedEnvironments": (32, r"[a-zA-Z0-9-]"),
    "Microsoft.Web/sites": (60, r"[a-zA-Z0-9-]"),
    "Microsoft.Web/serverfarms": (40, r"[a-zA-Z0-9-]"),
    "Microsoft.OperationalInsights/workspaces": (63, r"[a-zA-Z0-9-]"),
    "Microsoft.ManagedIdentity/userAssignedIdentities": (128, r"[a-zA-Z0-9-_]"),
    "Microsoft.Maps/accounts": (98, r"[a-zA-Z0-9-._()]"),
    "Microsoft.Insights/components": (255, r"[a-zA-Z0-9-._()]"),
    "Microsoft.Resources/resourceGroups": (90, r"[a-zA-Z0-9-._()]"),
}

#: Longest value each interpolated symbol can take. Anything else makes a name
#: unmeasurable, and the test says so instead of passing.
SYMBOL_LENGTHS = {"resourceToken": UNIQUE_STRING_LENGTH, "environmentName": ENVIRONMENT_NAME_MAX}


def test_environment_name_is_still_bounded(main: Bicep) -> None:
    """The resource-group name is derived from it, so its ceiling has to be a real one."""
    assert re.search(rf"@maxLength\({ENVIRONMENT_NAME_MAX}\)\s*\n@description\([^\n]*\)\s*\nparam environmentName", main.code), (
        f"main.bicep no longer caps environmentName at {ENVIRONMENT_NAME_MAX} characters; the name lengths below assume it does"
    )


def test_generated_names_cannot_exceed_azure_limits(templates: dict[pathlib.Path, Bicep]) -> None:
    """Worst-case length of every name this template generates, against Azure's rules.

    The failure this prevents is nasty out of proportion to its size: a storage account
    name one character over 24 is rejected by ARM *after* the resource group exists, and a
    name that changes between deployments orphans the whole lake behind it.
    """
    measured = 0
    for path, template in templates.items():
        for symbol, kind, expression in template.resources():
            rule = NAME_RULES.get(kind.split("@", 1)[0])
            if rule is None or not expression.startswith("'"):
                continue
            limit, charset = rule
            literal = expression.strip().strip("'")
            interpolations = re.findall(r"\$\{([^}]+)\}", literal)
            if any(name not in SYMBOL_LENGTHS for name in interpolations):
                continue  # a name this reader cannot bound; not the same as a name that is fine
            kind_only = kind.split("@", 1)[0]
            fixed = re.sub(r"\$\{[^}]+\}", "", literal)
            worst = len(fixed) + sum(SYMBOL_LENGTHS[name] for name in interpolations)
            measured += 1
            assert worst <= limit, f"{path.name}: {symbol} can generate a {worst}-character name; {kind_only} allows {limit}"
            legal = re.fullmatch(f"{charset}*", fixed)
            assert legal, f"{path.name}: {symbol} name '{literal}' has characters {kind_only} forbids"
    assert measured >= len(NAME_RULES) - 2, f"only {measured} names could be measured; the reader has lost track of this template"
