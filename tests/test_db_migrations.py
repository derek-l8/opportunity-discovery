import json
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
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(opportunities)")}
    assert {
        "engagement_type",
        "career_stage",
        "required_degree",
        "preferred_degree",
        "experience_min_years",
        "experience_max_years",
        "routing_state",
        "profile_routes_json",
    } <= columns
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


def test_baseline_database_upgrades_through_migrations_0003_0004_and_0005(tmp_path, monkeypatch):
    migrations = dbm._available_migrations()
    assert [version for version, _, _ in migrations] == [1, 2, 3, 4, 5]
    conn = connect(tmp_path / "baseline-upgrade.sqlite3")

    monkeypatch.setattr(dbm, "_available_migrations", lambda: migrations[:2])
    assert migrate(conn) == [1, 2]
    assert current_version(conn) == 2

    monkeypatch.setattr(dbm, "_available_migrations", lambda: migrations[:4])
    assert migrate(conn) == [3, 4]
    assert current_version(conn) == 4

    monkeypatch.setattr(dbm, "_available_migrations", lambda: migrations)
    assert migrate(conn) == [5]
    assert current_version(conn) == 5
    assert migrate(conn) == []

    opportunity_columns = {row["name"] for row in conn.execute("PRAGMA table_info(opportunities)").fetchall()}
    assert {
        "program_family_id",
        "cycle_id",
        "application_state",
        "last_change_events_json",
        "engagement_type",
        "profile_routes_json",
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


def test_migration_backfills_profile_routes_without_changing_identity(tmp_path):
    conn = connect(tmp_path / "backfill.sqlite3")
    migrate(conn)
    opportunity_id = "opp_stable_existing"
    conn.execute(
        "INSERT INTO opportunities (opportunity_id, identity_basis, title, canonical_url,"
        " employment_type, last_seen) VALUES (?, 'url', 'Firmware Intern', ?, 'internship', ?)",
        (opportunity_id, "https://example.test/jobs/1", "2026-01-01T00:00:00Z"),
    )
    conn.commit()

    assert migrate(conn) == []
    row = conn.execute("SELECT * FROM opportunities WHERE opportunity_id=?", (opportunity_id,)).fetchone()
    assert row["opportunity_id"] == opportunity_id
    assert row["engagement_type"] == "internship"
    assert row["routing_state"] == "included"
    assert set(json.loads(row["profile_routes_json"])) == {
        "student-early-career",
        "new-grad",
        "all-opportunities",
    }
    conn.close()
