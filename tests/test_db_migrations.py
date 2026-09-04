import sqlite3

from opportunity_discovery import db as dbm
from opportunity_discovery.db import connect, current_version, migrate


def test_migrations_apply_and_are_idempotent(tmp_path):
    db_path = tmp_path / "db.sqlite3"
    conn = connect(db_path)
    applied_first = migrate(conn)
    assert applied_first, "first migrate should apply migrations"
    assert current_version(conn) >= 1
    applied_second = migrate(conn)
    assert applied_second == []
    # tables exist and are stable across re-open
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for expected in (
        "sources",
        "source_checks",
        "collection_runs",
        "opportunities",
        "observations",
        "provenance",
        "opportunity_source_state",
        "aliases",
        "duplicate_decisions",
        "changes",
        "export_checkpoints",
        "raw_cache",
    ):
        assert expected in tables
    source_check_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(source_checks)").fetchall()
    }
    assert {"changed_records", "pages_fetched", "reported_total", "truncated"} <= source_check_columns
    conn.close()
    conn2 = connect(db_path)
    assert migrate(conn2) == []
    conn2.close()


def test_baseline_database_upgrades_through_both_additive_migrations(tmp_path, monkeypatch):
    migrations = dbm._available_migrations()
    assert [version for version, _, _ in migrations] == [1, 2, 3, 4]
    conn = connect(tmp_path / "baseline-upgrade.sqlite3")

    monkeypatch.setattr(dbm, "_available_migrations", lambda: migrations[:2])
    assert migrate(conn) == [1, 2]
    assert current_version(conn) == 2

    monkeypatch.setattr(dbm, "_available_migrations", lambda: migrations)
    assert migrate(conn) == [3, 4]
    assert current_version(conn) == 4
    assert migrate(conn) == []

    opportunity_columns = {row["name"] for row in conn.execute("PRAGMA table_info(opportunities)").fetchall()}
    assert {
        "program_family_id",
        "cycle_id",
        "application_state",
        "last_change_events_json",
    } <= opportunity_columns
    source_check_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(source_checks)").fetchall()
    }
    assert {"changed_records", "pages_fetched", "reported_total", "truncated"} <= source_check_columns
    assert conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='opportunity_source_state'"
    ).fetchone()
    conn.close()


def test_foreign_keys_enforced(tmp_path):
    conn = connect(tmp_path / "fk.sqlite3")
    migrate(conn)
    try:
        with __import__("pytest").raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO source_checks (source_id, run_id, checked_at, state)"
                " VALUES ('missing-source', NULL, '2026-01-01', 'healthy')"
            )
    finally:
        conn.close()
