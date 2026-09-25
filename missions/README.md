# Missions: readable if-then rules

A mission file is a small library of rules NEXUS runs: "EĞER asansör kullanılamıyor VE alternatif
varsa O ZAMAN vatandaş kartını yayımla". `nexus_core` reads every `missions/*.toml` with `tomllib`
and refuses a file it cannot trust before a single signal is routed. Nothing in a file is evaluated:
a condition is a field, one operator from a fixed list and a literal; a template is plain `{name}`
placeholders; an action must be in the reflex catalog.

## Shape

```toml
[mission]
id = "erisilebilir-yolculuk"        # lower case, digits, - and _
title = "Erişilebilir yolculuk"
intent = "..."                      # why the mission exists, one sentence
reviewed_on = 2026-09-25            # expires_days counts from here

[escalation]                        # when a rule-closable signal goes to a person anyway
window_hours = 336                  # the same entity seen repeat_threshold times in this window
repeat_threshold = 3                # counted per outage_id, not per snapshot
critical_kinds = ["hub_faults"]     # these kinds always go to a person

[[rules]]
id = "R-01"
path = "reflex"                     # reflex: the rule closes it; arena: drafted for a person
expires_days = 30                   # a rule stops matching after this; it never comes back silently

[rules.when]
kind = "equipment_fault"            # the signal kind
conditions = [{ field = "equipment_type", op = "eq", value = "elevator" }]

[rules.then]
action = "publish_alternative"      # must be in nexus_core's action catalog
card_kind = "alternative"           # one of the contract's Card kinds
title = "{station} istasyonunda asansör kullanılamıyor"
card_template = "..."               # {name} placeholders only; a missing value escalates, never prints blank
```

Operators: `eq`, `ne`, `in`, `not_in`, `gt`, `gte`, `lt`, `lte`, `present`, `absent`, `true`,
`false`. A missing field is false for every operator but `absent`: absent data never fires a rule.

Actions (the catalog, owned by `nexus_core`): `publish_card`, `publish_alternative`, `fold_repeat`,
`label_quality`, `schedule_mode`, `open_escalation`. Every one is reversible and stays inside Nabız.

## Signal fields the rules read

`ibb_mcp.accessibility.signal_candidates` and `stale_signal` build these from one equipment
snapshot; the console adds the time and the provenance and wraps them as `nexus_core` signals.

| Kind | Fields |
|---|---|
| `equipment_fault` | `equipment_type` (`elevator`, `escalator`, `moving_walkway`, `unknown`), `equipment_code`, `station`, `line`, `status_type` (İBB's word: Arıza, Revizyon, Çalıştırılmıyor), `status_class`, `outage_id`, `ibb_date`, `outage_hours`, `outage_hours_basis`, `date_semantics_unknown`, `text`; for a lift with an alternative also `alternative_station`, `alternative_line`, `extra_minutes`, `extra_minutes_text`, `alternative_reason` |
| `long_outage` | the same fields, emitted when `outage_hours` > 24 |
| `hub_faults` | `hub`, `fault_count`, `equipment_list`, `lines` |
| `source_stale` | `source`, `age_text`, `age_minutes`, `last_known_text` |

`outage_hours` counts from İBB's `Date`, whose meaning is undocumented (it may be when the fault
began or when service should resume), so `outage_hours_basis` is `ibb_date` and cards say so.

## Files

- [`erisilebilir_yolculuk.toml`](erisilebilir_yolculuk.toml): R-01 lift out, alternative found:
  citizen card (reflex). R-02 equipment data stale: last known state, "doğrulanamadı" (reflex).
  R-03 two or more faults at one interchange: Arena. R-04 more than 24 hours since İBB's recorded
  date: Arena.

Wording in every template: never "çalışıyor"; the most a card says is "İBB kaydında arıza yok".
