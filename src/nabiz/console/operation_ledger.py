"""Transactional idempotency records shared by calendar writes and provider delivery."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any


class OperationConflict(ValueError):
    """An operation key was reused for a different action or payload."""


@dataclass(frozen=True)
class Operation:
    owner_id: str
    operation_id: str
    action: str
    fingerprint: str
    target_id: str
    state: str
    result: dict[str, Any]


class OperationLedger:
    """Use the caller's SQLite transaction, so the operation and its plan commit together."""

    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    @staticmethod
    def create_schema(db: sqlite3.Connection) -> None:
        db.execute("""
            CREATE TABLE IF NOT EXISTS operation_ledger (
                owner_id TEXT NOT NULL,
                operation_id TEXT NOT NULL,
                action TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                target_id TEXT NOT NULL,
                state TEXT NOT NULL,
                result_json TEXT NOT NULL,
                PRIMARY KEY (owner_id, operation_id)
            )
        """)

    def get(self, owner_id: str, operation_id: str) -> Operation | None:
        row = self.db.execute(
            "SELECT owner_id, operation_id, action, fingerprint, target_id, state, result_json "
            "FROM operation_ledger WHERE owner_id = ? AND operation_id = ?",
            (owner_id, operation_id),
        ).fetchone()
        if row is None:
            return None
        return Operation(*row[:6], result=json.loads(row[6]))

    def require_same(self, owner_id: str, operation_id: str, action: str, fingerprint: str) -> Operation | None:
        existing = self.get(owner_id, operation_id)
        if existing and (existing.action != action or existing.fingerprint != fingerprint):
            raise OperationConflict("İşlem kimliği farklı bir işlemde kullanılmış.")
        return existing

    def record(
        self, owner_id: str, operation_id: str, action: str, fingerprint: str,
        target_id: str, state: str, result: dict[str, Any],
    ) -> None:
        self.db.execute(
            "INSERT INTO operation_ledger VALUES (?, ?, ?, ?, ?, ?, ?)",
            (owner_id, operation_id, action, fingerprint, target_id, state, json.dumps(result, ensure_ascii=False)),
        )

    def set_result(self, owner_id: str, operation_id: str, state: str, result: dict[str, Any]) -> None:
        self.db.execute(
            "UPDATE operation_ledger SET state = ?, result_json = ? WHERE owner_id = ? AND operation_id = ?",
            (state, json.dumps(result, ensure_ascii=False), owner_id, operation_id),
        )
