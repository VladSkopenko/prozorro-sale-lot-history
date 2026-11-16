"""Сховище SQLite: сирі версії, поточний стан кожної спроби, історія статусів і курсор стрічки."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from lot_history.models import Attempt

SCHEMA = """
CREATE TABLE IF NOT EXISTS procedure_versions (
    procedure_id  TEXT NOT NULL,
    date_modified TEXT NOT NULL,
    content_hash  TEXT NOT NULL,
    raw_json      TEXT NOT NULL,
    fetched_at    TEXT NOT NULL,
    PRIMARY KEY (procedure_id, date_modified)
);
CREATE TABLE IF NOT EXISTS attempts (
    procedure_id        TEXT PRIMARY KEY,
    auction_id          TEXT NOT NULL UNIQUE,
    previous_auction_id TEXT,
    attempt_number      INTEGER,
    status              TEXT NOT NULL,
    outcome             TEXT NOT NULL,
    selling_method      TEXT NOT NULL,
    title               TEXT NOT NULL,
    value_amount        TEXT,
    value_currency      TEXT,
    classification_id   TEXT,
    classification_name TEXT,
    property_kind       TEXT NOT NULL,
    region              TEXT,
    locality            TEXT,
    street_address      TEXT,
    ownership_type      TEXT,
    seller_name         TEXT,
    auction_start       TEXT,
    date_published      TEXT,
    date_modified       TEXT NOT NULL,
    content_hash        TEXT NOT NULL,
    source_api_url      TEXT NOT NULL,
    source_page_url     TEXT NOT NULL,
    lot_key             TEXT
);
CREATE INDEX IF NOT EXISTS attempts_lot_key ON attempts (lot_key);
CREATE INDEX IF NOT EXISTS attempts_previous ON attempts (previous_auction_id);
CREATE TABLE IF NOT EXISTS status_history (
    procedure_id  TEXT NOT NULL,
    status        TEXT NOT NULL,
    date_modified TEXT NOT NULL,
    PRIMARY KEY (procedure_id, status, date_modified)
);
CREATE TABLE IF NOT EXISTS unresolved_previous (
    auction_id TEXT PRIMARY KEY,
    checked_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cursors (
    name  TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

ATTEMPT_COLUMNS = (
    "procedure_id",
    "auction_id",
    "previous_auction_id",
    "attempt_number",
    "status",
    "outcome",
    "selling_method",
    "title",
    "value_amount",
    "value_currency",
    "classification_id",
    "classification_name",
    "property_kind",
    "region",
    "locality",
    "street_address",
    "ownership_type",
    "seller_name",
    "auction_start",
    "date_published",
    "date_modified",
    "source_api_url",
    "source_page_url",
)

UpsertResult = Literal["new", "changed", "unchanged", "stale"]


def iso(moment: datetime | None) -> str | None:
    """Один сталий запис, щоб збережені позначки часу порівнювалися як рядки."""
    if moment is None:
        return None
    return moment.astimezone(UTC).isoformat(timespec="microseconds")


def now() -> str:
    return iso(datetime.now(UTC))


class Store:
    def __init__(self, path: Path | str) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path))
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)

    def close(self) -> None:
        self._db.close()

    def cursor(self, name: str) -> str | None:
        row = self._db.execute("SELECT value FROM cursors WHERE name = ?", (name,)).fetchone()
        return row["value"] if row else None

    def set_cursor(self, name: str, value: str) -> None:
        with self._db:
            self._db.execute(
                "INSERT INTO cursors (name, value) VALUES (?, ?) "
                "ON CONFLICT (name) DO UPDATE SET value = excluded.value",
                (name, value),
            )

    def save_version(self, procedure_id: str, date_modified: str, content_hash: str, raw_json: str) -> bool:
        """Зберігає сиру відповідь один раз на пару (процедура, позначка зміни). False, якщо вона вже є:
        стрічка повторно віддає запис на межі курсора, а повторний запуск читає ті самі сторінки."""
        with self._db:
            inserted = self._db.execute(
                "INSERT OR IGNORE INTO procedure_versions "
                "(procedure_id, date_modified, content_hash, raw_json, fetched_at) VALUES (?, ?, ?, ?, ?)",
                (procedure_id, date_modified, content_hash, raw_json, now()),
            )
        return inserted.rowcount == 1

    def upsert_attempt(self, attempt: Attempt, content_hash: str) -> UpsertResult:
        values = attempt.model_dump()
        for field in ("auction_start", "date_published", "date_modified"):
            values[field] = iso(values[field])
        values["value_amount"] = None if attempt.value_amount is None else str(attempt.value_amount)
        stored = self._db.execute(
            "SELECT date_modified, content_hash, status FROM attempts WHERE procedure_id = ?",
            (attempt.procedure_id,),
        ).fetchone()
        with self._db:
            if stored is None:
                columns = (*ATTEMPT_COLUMNS, "content_hash")
                self._db.execute(
                    f"INSERT INTO attempts ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                    (*(values[column] for column in ATTEMPT_COLUMNS), content_hash),
                )
                self._record_status(attempt.procedure_id, attempt.status, values["date_modified"])
                return "new"
            # версія, старіша за збережену (дозбирання після стрічки), не має відкочувати стан
            if values["date_modified"] < stored["date_modified"]:
                return "stale"
            if content_hash == stored["content_hash"]:
                self._db.execute(
                    "UPDATE attempts SET date_modified = ? WHERE procedure_id = ?",
                    (values["date_modified"], attempt.procedure_id),
                )
                return "unchanged"
            assignments = ", ".join(f"{column} = ?" for column in ATTEMPT_COLUMNS[1:])
            self._db.execute(
                f"UPDATE attempts SET {assignments}, content_hash = ? WHERE procedure_id = ?",
                (*(values[column] for column in ATTEMPT_COLUMNS[1:]), content_hash, attempt.procedure_id),
            )
            if attempt.status != stored["status"]:
                self._record_status(attempt.procedure_id, attempt.status, values["date_modified"])
            return "changed"

    def _record_status(self, procedure_id: str, status: str, date_modified: str) -> None:
        self._db.execute(
            "INSERT OR IGNORE INTO status_history (procedure_id, status, date_modified) VALUES (?, ?, ?)",
            (procedure_id, status, date_modified),
        )

    def attempt(self, auction_id: str) -> sqlite3.Row | None:
        return self._db.execute("SELECT * FROM attempts WHERE auction_id = ?", (auction_id,)).fetchone()

    def attempts(self) -> list[sqlite3.Row]:
        return self._db.execute(
            "SELECT * FROM attempts ORDER BY lot_key, date_published, auction_id"
        ).fetchall()

    def status_history(self, procedure_id: str) -> list[sqlite3.Row]:
        return self._db.execute(
            "SELECT status, date_modified FROM status_history WHERE procedure_id = ? ORDER BY date_modified",
            (procedure_id,),
        ).fetchall()

    def links(self) -> dict[str, str | None]:
        """номер аукціону -> попередній аукціон, на який він посилається, для кожної збереженої спроби."""
        rows = self._db.execute("SELECT auction_id, previous_auction_id FROM attempts").fetchall()
        return {row["auction_id"]: row["previous_auction_id"] for row in rows}

    def missing_previous(self) -> list[str]:
        """Попередні аукціони, на які посилаються спроби, яких немає у сховищі і яких ще не шукали марно."""
        rows = self._db.execute(
            "SELECT DISTINCT a.previous_auction_id AS auction_id FROM attempts a "
            "WHERE a.previous_auction_id IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM attempts p WHERE p.auction_id = a.previous_auction_id) "
            "AND NOT EXISTS (SELECT 1 FROM unresolved_previous u WHERE u.auction_id = a.previous_auction_id) "
            "ORDER BY 1"
        ).fetchall()
        return [row["auction_id"] for row in rows]

    def mark_unresolved(self, auction_id: str) -> None:
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO unresolved_previous (auction_id, checked_at) VALUES (?, ?)",
                (auction_id, now()),
            )

    def set_lot_keys(self, lot_keys: dict[str, str]) -> None:
        with self._db:
            self._db.executemany(
                "UPDATE attempts SET lot_key = ? WHERE auction_id = ?",
                [(lot_key, auction_id) for auction_id, lot_key in lot_keys.items()],
            )

    def counts(self) -> dict[str, int]:
        queries = {
            "versions": "SELECT count(*) FROM procedure_versions",
            "attempts": "SELECT count(*) FROM attempts",
            "lots": "SELECT count(DISTINCT lot_key) FROM attempts WHERE lot_key IS NOT NULL",
            "unsuccessful": "SELECT count(*) FROM attempts WHERE outcome = 'unsuccessful'",
            "cancelled": "SELECT count(*) FROM attempts WHERE outcome = 'cancelled'",
            "repeated": "SELECT count(*) FROM attempts WHERE previous_auction_id IS NOT NULL",
            "unresolved_previous": "SELECT count(*) FROM unresolved_previous",
        }
        return {name: self._db.execute(query).fetchone()[0] for name, query in queries.items()}
