"""SQLite storage: connections, versioned idempotent migrations."""

from __future__ import annotations

import importlib.resources
import json
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
    _backfill_career_profiles(conn)
    return newly_applied


def _backfill_career_profiles(conn: sqlite3.Connection) -> None:
    """Normalize pre-0005 rows once without changing their stable identity."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(opportunities)")}
    if "profile_routes_json" not in columns:
        return
    rows = conn.execute(
        "SELECT opportunity_id, title, canonical_url, description_excerpt, employment_type,"
        " requirements_text"
        " FROM opportunities WHERE profile_routes_json='{}' OR profile_routes_json IS NULL"
    ).fetchall()
    if not rows:
        return

    from . import constants as c
    from .models import RawOpportunity
    from .routing import normalize_routing_fields, route_profiles

    for row in rows:
        fields = normalize_routing_fields(
            RawOpportunity(
                title=row[1] or "",
                canonical_url=row[2] or "",
                description_excerpt=row[3],
                employment_type=row[4],
                requirements_text=row[5],
            )
        )
        routes = route_profiles(fields)
        active = routes[c.PROFILE_STUDENT]
        conn.execute(
            "UPDATE opportunities SET engagement_type=?, career_stage=?, required_degree=?,"
            " preferred_degree=?, experience_requirement_text=?, experience_min_years=?,"
            " experience_max_years=?, active_profile=?, routing_state=?, eligibility_confidence=?,"
            " profile_routes_json=?, routing_reason_codes_json=? WHERE opportunity_id=?",
            (
                fields["engagement_type"],
                fields["career_stage"],
                fields["required_degree"],
                fields["preferred_degree"],
                fields["experience_requirement_text"],
                fields["experience_min_years"],
                fields["experience_max_years"],
                c.PROFILE_STUDENT,
                active.state,
                active.confidence,
                json.dumps({name: decision.to_dict() for name, decision in routes.items()}, sort_keys=True),
                json.dumps(active.reason_codes),
                row[0],
            ),
        )
    conn.commit()


def current_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
    except sqlite3.OperationalError:
        return 0
    return int(row["v"] or 0)
