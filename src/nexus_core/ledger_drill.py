"""Run a ledger integrity drill against a short lived SQLite copy."""

from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import sqlite3
import tempfile

from pydantic import BaseModel, ConfigDict

from nexus_core.ledger import Ledger, canonical, entry_hash

DRILL_KINDS = ("detay", "silme", "sira", "hash")
KIND_LABEL = {
    "detay": "detay değiştirildi",
    "silme": "kayıt silindi",
    "sira": "iki kaydın yeri değişti",
    "hash": "detay değiştirildi, mühür yeniden hesaplandı",
}

_SWAP_COLUMNS = ("at", "signal_id", "entity_id", "actor", "kind", "detail", "prev_hash", "hash")


class DrillRefused(ValueError):
    """A drill cannot run for the requested kind or ledger size."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class OriginalState(BaseModel):
    model_config = ConfigDict(frozen=True)

    sha256_before: str
    sha256_after: str
    unchanged: bool
    verify_ok: bool
    entries: int


class DrillResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: str
    kind_label: str
    target_id: int
    caught: bool
    caught_at_id: int | None
    check: str
    check_label: str
    copy_entries: int
    sentence: str
    note: str
    original: OriginalState


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_database(source: pathlib.Path, target: pathlib.Path) -> None:
    source_uri = f"{source.resolve().as_uri()}?mode=ro"
    reader = sqlite3.connect(source_uri, uri=True, timeout=10)
    writer = sqlite3.connect(target, timeout=10)
    try:
        reader.backup(writer)
    finally:
        writer.close()
        reader.close()


def _entry_count(path: pathlib.Path) -> int:
    connection = sqlite3.connect(path, timeout=10)
    try:
        return int(connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0])
    finally:
        connection.close()


def _break_entry(path: pathlib.Path, kind: str, target_id: int) -> None:
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            if kind == "silme":
                connection.execute("DELETE FROM entries WHERE id = ?", (target_id,))
            elif kind == "sira":
                names = ", ".join(_SWAP_COLUMNS)
                rows = connection.execute(
                    f"SELECT {names} FROM entries WHERE id IN (?, ?) ORDER BY id", (target_id, target_id + 1)
                ).fetchall()
                first, second = rows
                assignments = ", ".join(f"{column} = ?" for column in _SWAP_COLUMNS)
                connection.execute(
                    f"UPDATE entries SET {assignments} WHERE id = ?",
                    (*(second[column] for column in _SWAP_COLUMNS), target_id),
                )
                connection.execute(
                    f"UPDATE entries SET {assignments} WHERE id = ?",
                    (*(first[column] for column in _SWAP_COLUMNS), target_id + 1),
                )
            else:
                row = connection.execute(
                    "SELECT id, at, signal_id, entity_id, actor, kind, detail, prev_hash FROM entries WHERE id = ?",
                    (target_id,),
                ).fetchone()
                detail = json.loads(row["detail"])
                detail["tatbikat"] = True
                text = canonical(detail)
                if kind == "hash":
                    digest = entry_hash(
                        (
                            row["id"], row["at"], row["signal_id"], row["entity_id"],
                            row["actor"], row["kind"], text, row["prev_hash"],
                        )
                    )
                    connection.execute("UPDATE entries SET detail = ?, hash = ? WHERE id = ?", (text, digest, target_id))
                else:
                    connection.execute("UPDATE entries SET detail = ? WHERE id = ?", (text, target_id))
    finally:
        connection.close()


def _check_label(problem: str | None) -> tuple[str, str]:
    if problem is None:
        return "yok", "doğrulama bozulmayı yakalamadı"
    if "missing" in problem:
        return "eksik_kayit", "kayıt eksik"
    if "prev_hash" in problem:
        return "bag", "önceki mühürle bağ kopuk"
    if "content" in problem or "hash does not match" in problem:
        return "icerik", "mühür içerikle tutmuyor"
    return "bilinmiyor", problem


def run_drill(
    ledger: Ledger,
    kind: str,
    *,
    work_dir: str | pathlib.Path | None = None,
) -> DrillResult:
    """Break one row in a SQLite backup, verify it, and report the untouched source state."""
    if kind not in DRILL_KINDS:
        raise DrillRefused("unknown_kind")

    source = pathlib.Path(ledger.path)
    sha256_before = _sha256(source)
    work_path = pathlib.Path(tempfile.mkdtemp(prefix="nabiz-drill-", dir=work_dir))
    try:
        copy_path = work_path / "copy.db"
        _copy_database(source, copy_path)
        count = _entry_count(copy_path)
        if count == 0:
            raise DrillRefused("empty")
        if kind != "detay" and count < 2:
            raise DrillRefused("too_few")

        target_id = max(1, count // 2)
        _break_entry(copy_path, kind, target_id)
        copied_verify = Ledger(copy_path).verify()
        caught = not copied_verify.ok
        check, check_label = _check_label(copied_verify.problem)
        if caught:
            sentence = (
                f"Kayıt #{target_id} bozuldu ({KIND_LABEL[kind]}) → doğrulama kayıt "
                f"#{copied_verify.first_bad_id} üzerinde yakaladı: {check_label}."
            )
        else:
            sentence = f"Kayıt #{target_id} bozuldu ({KIND_LABEL[kind]}) → doğrulama yakalamadı."

        original_verify = ledger.verify()
        sha256_after = _sha256(source)
        unchanged = sha256_before == sha256_after
        if unchanged:
            note = "tatbikat · gerçek defter değişmedi"
        elif original_verify.ok:
            note = "tatbikat · gerçek defter sağlam, bu sırada yeni kayıt eklendi"
        else:
            note = "tatbikat · gerçek defter doğrulanamadı"
        return DrillResult(
            kind=kind,
            kind_label=KIND_LABEL[kind],
            target_id=target_id,
            caught=caught,
            caught_at_id=copied_verify.first_bad_id,
            check=check,
            check_label=check_label,
            copy_entries=count,
            sentence=sentence,
            note=note,
            original=OriginalState(
                sha256_before=sha256_before,
                sha256_after=sha256_after,
                unchanged=unchanged,
                verify_ok=original_verify.ok,
                entries=original_verify.entries,
            ),
        )
    finally:
        shutil.rmtree(work_path, ignore_errors=True)
