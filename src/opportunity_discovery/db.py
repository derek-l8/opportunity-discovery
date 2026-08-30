"""SQLite storage: connections, versioned idempotent migrations."""

from __future__ import annotations

import importlib.resources
import sqlite3
from pathlib import Path

_MIGRATIONS_PACKAGE = "opportunity_discovery.migrations"


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _available_migrations() -> list[tuple[int, str, str]]:
    """Return sorted (version, filename, sql) from the packaged migrations dir."""
    files: list[tuple[int, str]] = []
    pkg_files = importlib.resources.files(_MIGRATIONS_PACKAGE)
    for entry in pkg_files.iterdir():
        name = getattr(entry, "name", "")
        if name.endswith(".sql"):
            try:
                version = int(name.split("_", 1)[0])
            except ValueError as exc:
                raise RuntimeError(f"bad migration filename: {name}") from exc
            files.append((version, name))
    out: list[tuple[int, str, str]] = []
    for version, name in sorted(files):
        sql = (pkg_files / name).read_text(encoding="utf-8")
        out.append((version, name, sql))
    return out


def migrate(conn: sqlite3.Connection) -> list[int]:
    """Apply pending migrations. Idempotent. Returns applied versions."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        )
        """
    )
    conn.commit()
    applied = {row["version"] for row in conn.execute("SELECT version FROM schema_migrations")}
    newly_applied: list[int] = []
    for version, name, sql in _available_migrations():
        if version in applied:
            continue
        with conn:
            conn.executescript(sql)
            conn.execute("INSERT INTO schema_migrations (version, name) VALUES (?, ?)", (version, name))
        newly_applied.append(version)
    return newly_applied


def current_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
    except sqlite3.OperationalError:
        return 0
    return int(row["v"] or 0)
