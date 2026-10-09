import os
import sqlite3
from collections import defaultdict, deque
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from .statement import Movement, ReviewWarning, Statement, balance_warnings, format_date, format_money


class ImportUnavailable(Exception):
    pass


class ConsentRequired(Exception):
    pass


class WarningReviewRequired(Exception):
    pass


@dataclass(frozen=True)
class ImportedStatement:
    id: str
    filename: str
    imported_at: datetime
    statement: Statement
    new_count: int
    existing_count: int


@dataclass(frozen=True)
class Comparison:
    matches: list[int | None]
    overlap: bool
    linked_account: str | None
    warnings: list[ReviewWarning]

    @property
    def new_count(self) -> int:
        return self.matches.count(None)

    @property
    def existing_count(self) -> int:
        return len(self.matches) - self.new_count


@dataclass(frozen=True)
class RecordedMovement:
    movement: Movement
    origins: list[tuple[str, int]]


def movement_identity(movement: Movement) -> tuple[date, str, str, Decimal, Decimal]:
    return movement.date, movement.history, movement.description, movement.amount, movement.balance


class Storage:
    def __init__(self, path: Path):
        self.path = path

    def connect(self) -> sqlite3.Connection:
        self.path.mkdir(parents=True, exist_ok=True, mode=0o700)
        connection = sqlite3.connect(self.path / "lastro.sqlite3")
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS imports (
                id TEXT PRIMARY KEY, filename TEXT NOT NULL, imported_at TEXT NOT NULL,
                account TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL,
                balance TEXT NOT NULL, new_count INTEGER NOT NULL, existing_count INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS movements (
                id INTEGER PRIMARY KEY, import_id TEXT NOT NULL REFERENCES imports(id),
                source_line INTEGER NOT NULL, date TEXT NOT NULL, history TEXT NOT NULL,
                description TEXT NOT NULL, amount TEXT NOT NULL, balance TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS origins (
                import_id TEXT NOT NULL REFERENCES imports(id),
                source_line INTEGER NOT NULL,
                movement_id INTEGER NOT NULL REFERENCES movements(id),
                PRIMARY KEY (import_id, source_line),
                UNIQUE (import_id, movement_id)
            );
            CREATE TABLE IF NOT EXISTS import_contents (
                digest TEXT PRIMARY KEY,
                import_id TEXT NOT NULL UNIQUE REFERENCES imports(id)
            );
            CREATE TABLE IF NOT EXISTS confirmations (
                token TEXT PRIMARY KEY,
                import_id TEXT NOT NULL REFERENCES imports(id)
            );
        """)
        if connection.execute("PRAGMA user_version").fetchone()[0] == 0:
            try:
                connection.execute("BEGIN IMMEDIATE")
                if connection.execute("PRAGMA user_version").fetchone()[0] == 0:
                    connection.execute("INSERT INTO origins SELECT import_id, source_line, id FROM movements")
                    for row in connection.execute("SELECT id FROM imports"):
                        digest = sha256(self.original_path(row["id"]).read_bytes()).hexdigest()
                        connection.execute("INSERT INTO import_contents VALUES (?, ?)", (digest, row["id"]))
                    connection.execute("PRAGMA user_version = 1")
                connection.commit()
            except BaseException:
                connection.close()
                raise
        return connection

    def first(self) -> ImportedStatement | None:
        with closing(self.connect()) as connection:
            row = connection.execute("SELECT * FROM imports LIMIT 1").fetchone()
            return self._import(connection, row) if row is not None else None

    def _movement(self, row: sqlite3.Row) -> Movement:
        return Movement(date.fromisoformat(row["date"]), row["history"], row["description"], Decimal(row["amount"]), Decimal(row["balance"]), row["source_line"])

    def _import(self, connection: sqlite3.Connection, row: sqlite3.Row) -> ImportedStatement:
        movements = [self._movement(item) for item in connection.execute(
            "SELECT m.date, m.history, m.description, m.amount, m.balance, o.source_line FROM origins o JOIN movements m ON m.id = o.movement_id WHERE o.import_id = ? ORDER BY o.source_line", (row["id"],))]
        statement = Statement(row["account"], date.fromisoformat(row["start"]), date.fromisoformat(row["end"]), Decimal(row["balance"]), movements)
        return ImportedStatement(row["id"], row["filename"], datetime.fromisoformat(row["imported_at"]), statement, row["new_count"], row["existing_count"])

    def get(self, id: str) -> ImportedStatement | None:
        with closing(self.connect()) as connection:
            row = connection.execute("SELECT * FROM imports WHERE id = ?", (id,)).fetchone()
            return self._import(connection, row) if row is not None else None

    def confirmed(self, token: str) -> str | None:
        with closing(self.connect()) as connection:
            row = connection.execute("SELECT id FROM imports WHERE id = ? UNION ALL SELECT import_id AS id FROM confirmations WHERE token = ? LIMIT 1", (token, token)).fetchone()
            return row["id"] if row else None

    def identical(self, content: bytes) -> str | None:
        with closing(self.connect()) as connection:
            row = connection.execute("SELECT import_id FROM import_contents WHERE digest = ?", (sha256(content).hexdigest(),)).fetchone()
            return row["import_id"] if row else None

    def imports(self) -> list[ImportedStatement]:
        with closing(self.connect()) as connection:
            return [self._import(connection, row) for row in connection.execute("SELECT * FROM imports ORDER BY imported_at, id")]

    def movements(self) -> list[RecordedMovement]:
        with closing(self.connect()) as connection:
            return [RecordedMovement(self._movement(row), [(origin["import_id"], origin["source_line"]) for origin in connection.execute(
                "SELECT import_id, source_line FROM origins WHERE movement_id = ? ORDER BY import_id", (row["id"],))])
                for row in connection.execute("SELECT * FROM movements ORDER BY id")]

    def compare(self, statement: Statement) -> Comparison:
        with closing(self.connect()) as connection:
            connection.execute("BEGIN")
            return self._compare(connection, statement)

    def _compare(self, connection: sqlite3.Connection, statement: Statement) -> Comparison:
        account = connection.execute("SELECT account FROM imports LIMIT 1").fetchone()
        linked_account = account["account"] if account else None
        known: dict[tuple[date, str, str, Decimal, Decimal], deque[int]] = defaultdict(deque)
        equivalent: dict[tuple[date, str, str, Decimal], list[sqlite3.Row]] = defaultdict(list)
        for row in connection.execute("SELECT m.*, i.filename FROM movements m JOIN imports i ON i.id = m.import_id WHERE i.account = ? ORDER BY m.id", (statement.account,)):
            movement = self._movement(row)
            known[movement_identity(movement)].append(row["id"])
            equivalent[(movement.date, movement.history, movement.description, movement.amount)].append(row)
        matches: list[int | None] = []
        warnings: list[ReviewWarning] = []
        for movement in statement.movements:
            occurrences = known[movement_identity(movement)]
            matches.append(occurrences.popleft() if occurrences else None)
            if matches[-1] is None:
                for row in equivalent[(movement.date, movement.history, movement.description, movement.amount)]:
                    if Decimal(row["balance"]) != movement.balance:
                        warnings.append(ReviewWarning(
                            f"Linha {movement.source_line} — possível divergência: conta {statement.account}, "
                            f"{format_date(movement.date)}, {movement.history}, {movement.description}, valor {format_money(movement.amount)}. "
                            f"Saldo informado {format_money(movement.balance)}; registro conhecido em {row['filename']} "
                            f"(linha {row['source_line']}): {format_money(Decimal(row['balance']))}.",
                            "Pode representar uma movimentação legítima repetida. Confira o original e a importação anterior; não haverá mescla, exclusão ou sobrescrita automática.",
                            row["import_id"],
                        ))
        overlap = connection.execute("SELECT 1 FROM imports WHERE account = ? AND start <= ? AND end >= ? LIMIT 1",
                                     (statement.account, statement.end.isoformat(), statement.start.isoformat())).fetchone() is not None
        new_lines = {movement.source_line for movement, match in zip(statement.movements, matches) if match is None}
        return Comparison(matches, overlap, linked_account, balance_warnings(statement, new_lines) + warnings)

    def original_path(self, id: str) -> Path:
        return self.path / "originals" / f"{id}.csv"

    def confirm(self, id: str, filename: str, content: bytes, statement: Statement, *, keep_without_new: bool = False, acknowledged_warnings: set[str] | None = None) -> str:
        with closing(self.connect()) as connection:
            # Compare against current history while serializing all writes.
            connection.execute("BEGIN IMMEDIATE")
            try:
                previous = connection.execute("SELECT id FROM imports WHERE id = ?", (id,)).fetchone()
                if previous is not None:
                    return id
                digest = sha256(content).hexdigest()
                duplicate = connection.execute("SELECT import_id FROM import_contents WHERE digest = ?", (digest,)).fetchone()
                if duplicate is not None:
                    connection.execute("INSERT OR IGNORE INTO confirmations VALUES (?, ?)", (id, duplicate["import_id"]))
                    connection.commit()
                    return str(duplicate["import_id"])
                comparison = self._compare(connection, statement)
                if comparison.linked_account is not None and comparison.linked_account != statement.account:
                    raise ImportUnavailable
                if any(warning.key not in (acknowledged_warnings or set()) for warning in comparison.warnings):
                    raise WarningReviewRequired
                if comparison.new_count == 0 and not keep_without_new:
                    raise ConsentRequired
                original = self.original_path(id)
                original.parent.mkdir(exist_ok=True, mode=0o700)
                # No database reference exists until the complete original is durable.
                with original.open("wb") as file:
                    file.write(content)
                    file.flush()
                    os.fsync(file.fileno())
                for path in (original.parent, self.path):
                    directory = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(directory)
                    finally:
                        os.close(directory)
                connection.execute("INSERT INTO imports VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                   (id, filename, datetime.now(timezone.utc).isoformat(), statement.account, statement.start.isoformat(), statement.end.isoformat(), str(statement.balance), comparison.new_count, comparison.existing_count))
                connection.execute("INSERT INTO import_contents VALUES (?, ?)", (digest, id))
                for movement, movement_id in zip(statement.movements, comparison.matches):
                    if movement_id is None:
                        cursor = connection.execute("INSERT INTO movements (import_id, source_line, date, history, description, amount, balance) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                                    (id, movement.source_line, movement.date.isoformat(), movement.history, movement.description, str(movement.amount), str(movement.balance)))
                        movement_id = cursor.lastrowid
                    connection.execute("INSERT INTO origins VALUES (?, ?, ?)", (id, movement.source_line, movement_id))
            except BaseException:
                connection.rollback()
                original = self.original_path(id)
                try:
                    original.unlink(missing_ok=True)
                except OSError:
                    # An unreferenced file is never exposed as a confirmed import.
                    pass
                raise
            # A commit may succeed just before an interruption. Never remove its
            # original during commit failure cleanup; closing rolls back any
            # transaction that did not commit. Unreferenced files are not history.
            connection.commit()
        return id
