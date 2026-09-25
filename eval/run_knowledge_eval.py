#!/usr/bin/env python3
"""Validate the locked knowledge question set without retrieval or a model."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

BUCKETS = {
    "k-genel": 20,
    "k-ulasim": 20,
    "k-iski": 15,
    "k-ispark": 10,
    "k-acikveri": 10,
    "k-hassas": 15,
    "k-yanitsiz": 10,
}
FIELDS = {
    "id",
    "question",
    "answerable",
    "sensitive",
    "gold_urls",
    "required_quote_substrings",
    "forbidden_claims",
    "category",
    "lang",
}
ID_PATTERN = re.compile(r"^k-(?:genel|ulasim|iski|ispark|acikveri|hassas|yanitsiz)-\d{2}$")


def _read_questions(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            raise ValueError(f"line {line_number}: blank lines are not valid JSONL records")
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"line {line_number}: each record must be a JSON object")
        rows.append(row)
    return rows


def _schema_errors(row: dict[str, Any], number: int) -> list[str]:
    missing = FIELDS - row.keys()
    extra = row.keys() - FIELDS
    if missing or extra:
        return [f"line {number}: schema keys differ; missing={sorted(missing)}, extra={sorted(extra)}"]
    return []


def _record_errors(row: dict[str, Any], number: int) -> list[str]:
    errors = []
    if not isinstance(row["question"], str) or not row["question"].strip():
        errors.append(f"line {number}: question must be non-empty text")
    if type(row["answerable"]) is not bool or type(row["sensitive"]) is not bool:
        errors.append(f"line {number}: answerable and sensitive must be booleans")
    for field in ("gold_urls", "required_quote_substrings", "forbidden_claims"):
        values = row[field]
        if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
            errors.append(f"line {number}: {field} must be a list of strings")
    if not isinstance(row["category"], str) or not row["category"].strip():
        errors.append(f"line {number}: category must be non-empty text")
    if row["lang"] != "tr":
        errors.append(f"line {number}: first release supports Turkish records only")
    if (row["sensitive"] or row["answerable"] is False) and not row["forbidden_claims"]:
        errors.append(f"line {number}: sensitive and unanswered records need forbidden_claims")
    return errors


def _validate_row(row: dict[str, Any], number: int) -> tuple[list[str], str | None]:
    errors = _schema_errors(row, number)
    if errors:
        return errors, None
    record_id = row["id"]
    if not isinstance(record_id, str) or not ID_PATTERN.fullmatch(record_id):
        return [f"line {number}: invalid id {record_id!r}"], None
    errors.extend(_record_errors(row, number))
    return errors, "-".join(record_id.split("-")[:2])


def _validate(rows: list[dict[str, Any]]) -> list[str]:
    errors = []
    if len(rows) != 100:
        errors.append(f"expected 100 records, found {len(rows)}")
    ids = [row["id"] for row in rows if isinstance(row.get("id"), str)]
    if len(set(ids)) != len(ids):
        errors.append("record ids must be unique")

    counts: Counter[str] = Counter()
    for number, row in enumerate(rows, start=1):
        row_errors, bucket = _validate_row(row, number)
        errors.extend(row_errors)
        if bucket is not None:
            counts[bucket] += 1
    for bucket, expected in BUCKETS.items():
        if counts[bucket] != expected:
            errors.append(f"{bucket}: expected {expected}, found {counts[bucket]}")
    unexpected = set(counts) - set(BUCKETS)
    if unexpected:
        errors.append(f"unexpected buckets: {sorted(unexpected)}")
    return errors


def _offline_answer(_: dict[str, Any]) -> str:
    """Stand in for the future retrieval model; never makes a provider call."""
    return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--offline", action="store_true", help="validate with a fixed unknown response")
    args = parser.parse_args()
    if not args.offline:
        parser.error("this lane implements only --offline; real retrieval belongs to G14")

    try:
        rows = _read_questions(args.questions)
        errors = _validate(rows)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    if errors:
        print("FAIL: knowledge question set is invalid")
        for error in errors:
            print(f"- {error}")
        return 1

    counts = Counter("-".join(row["id"].split("-")[:2]) for row in rows)
    unknown_count = sum(_offline_answer(row) == "unknown" for row in rows)
    buckets = ", ".join(f"{name}={counts[name]}" for name in BUCKETS)
    print(f"PASS: {len(rows)} records; schema and forbidden-claim checks valid")
    print(f"Buckets: {buckets}")
    print(f"Offline mock: {unknown_count} fixed unknown responses; retrieval and citation metrics not measured")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
