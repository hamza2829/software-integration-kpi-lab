import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from .models import Issue, Run

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    delivery TEXT NOT NULL,
    component TEXT NOT NULL,
    level TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    UNIQUE (delivery, component, level, timestamp)
);
CREATE TABLE IF NOT EXISTS results (
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    classname TEXT NOT NULL,
    name TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('passed', 'failed', 'blocked')),
    PRIMARY KEY (run_id, classname, name)
);
CREATE TABLE IF NOT EXISTS issues (
    key TEXT PRIMARY KEY,
    summary TEXT NOT NULL,
    severity TEXT NOT NULL,
    status TEXT NOT NULL,
    created TEXT NOT NULL,
    resolved TEXT,
    component TEXT NOT NULL,
    delivery TEXT NOT NULL
);
"""


@contextmanager
def connect(path: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(path)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SCHEMA)
        yield connection
    finally:
        connection.close()


def save_import(connection: sqlite3.Connection, runs: list[Run], issues: list[Issue]) -> None:
    with connection:
        for run in runs:
            identity = run.delivery, run.component, run.level, run.timestamp.isoformat()
            connection.execute(
                "DELETE FROM runs WHERE (delivery, component, level, timestamp) = (?, ?, ?, ?)",
                identity,
            )
            cursor = connection.execute(
                "INSERT INTO runs (delivery, component, level, timestamp) VALUES (?, ?, ?, ?)",
                identity,
            )
            connection.executemany(
                "INSERT INTO results VALUES (?, ?, ?, ?)",
                [(cursor.lastrowid, case.classname, case.name, case.outcome)
                 for case in run.results],
            )
        connection.executemany(
            """
            INSERT INTO issues (key, summary, severity, status, created, resolved,
                                component, delivery)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                summary = excluded.summary, severity = excluded.severity, status = excluded.status,
                created = excluded.created, resolved = excluded.resolved,
                component = excluded.component, delivery = excluded.delivery
            """,
            [(issue.key, issue.summary, issue.severity, issue.status, issue.created.isoformat(),
              issue.resolved.isoformat() if issue.resolved else None, issue.component,
              issue.delivery) for issue in issues],
        )


def read_snapshot(connection: sqlite3.Connection, as_of: date) -> tuple[list[sqlite3.Row],
                                                                        list[Issue]]:
    with connection:
        connection.execute("BEGIN")
        tests = connection.execute(
            """
            SELECT delivery, component, level, timestamp, classname, name, outcome
            FROM runs JOIN results ON results.run_id = runs.id
            WHERE substr(timestamp, 1, 10) <= ?
            ORDER BY timestamp, delivery, component, level, classname, name
            """,
            (as_of.isoformat(),),
        ).fetchall()
        issue_rows = connection.execute(
            "SELECT * FROM issues WHERE created <= ? ORDER BY key", (as_of.isoformat(),),
        ).fetchall()
    issues = [
        Issue(row["key"], row["summary"], row["severity"], row["status"],
              date.fromisoformat(row["created"]),
              date.fromisoformat(row["resolved"]) if row["resolved"] else None,
              row["component"], row["delivery"])
        for row in issue_rows
    ]
    return tests, issues
