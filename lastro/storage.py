import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from .statement import Movement, Statement


class ImportUnavailable(Exception):
    pass


@dataclass(frozen=True)
class ImportedStatement:
    id: str
    filename: str
    imported_at: datetime
    statement: Statement


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
        """)
        return connection

    def first(self) -> ImportedStatement | None:
        with closing(self.connect()) as connection:
            row = connection.execute("SELECT * FROM imports LIMIT 1").fetchone()
            if row is None:
                return None
            movements = [Movement(date.fromisoformat(item["date"]), item["history"], item["description"], Decimal(item["amount"]), Decimal(item["balance"]), item["source_line"])
                         for item in connection.execute("SELECT * FROM movements WHERE import_id = ? ORDER BY id", (row["id"],))]
            statement = Statement(row["account"], date.fromisoformat(row["start"]), date.fromisoformat(row["end"]), Decimal(row["balance"]), movements)
            return ImportedStatement(row["id"], row["filename"], datetime.fromisoformat(row["imported_at"]), statement)

    def original_path(self, id: str) -> Path:
        return self.path / "originals" / f"{id}.csv"

    def confirm(self, id: str, filename: str, content: bytes, statement: Statement) -> str:
        with closing(self.connect()) as connection:
            # Serialize the first-import check and all writes, including the file.
            connection.execute("BEGIN IMMEDIATE")
            try:
                previous = connection.execute("SELECT id FROM imports LIMIT 1").fetchone()
                if previous is not None:
                    if previous["id"] == id:
                        return id
                    raise ImportUnavailable
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
                                   (id, filename, datetime.now(timezone.utc).isoformat(), statement.account, statement.start.isoformat(), statement.end.isoformat(), str(statement.balance), len(statement.movements), 0))
                connection.executemany("INSERT INTO movements (import_id, source_line, date, history, description, amount, balance) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                       [(id, movement.source_line, movement.date.isoformat(), movement.history, movement.description, str(movement.amount), str(movement.balance)) for movement in statement.movements])
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
