import sqlite3

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
        "aliases",
        "duplicate_decisions",
        "changes",
        "export_checkpoints",
        "raw_cache",
    ):
        assert expected in tables
    conn.close()
    conn2 = connect(db_path)
    assert migrate(conn2) == []
    conn2.close()


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
