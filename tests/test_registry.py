from datetime import UTC, datetime, timedelta

from opportunity_discovery.registry import due_sources, load_sources, sync_sources_to_db
from tests.helpers import make_db, write_sources_toml


def write(engine_config, sources):
    write_sources_toml(engine_config, sources)


def test_load_validates_required_fields(tmp_path, engine_config):
    write(
        engine_config,
        [
            {
                "source_id": "a",
                "display_name": "A",
                "organization": "Org A",
                "adapter": "greenhouse",
                "endpoint_config": {"board": "a"},
            },
            {"source_id": "b", "display_name": "B"},  # missing organization/adapter
            {
                "source_id": "c",
                "display_name": "C",
                "organization": "O",
                "adapter": "greenhouse",
                "endpoint_config": {"board": "c"},
                "unknown_key": 1,
            },
            {
                "source_id": "a",
                "display_name": "dup",
                "organization": "O",
                "adapter": "greenhouse",
                "endpoint_config": {"board": "a"},
            },
        ],
    )
    sources, errors = load_sources(engine_config.sources_file)
    ids = [s.source_id for s in sources]
    assert ids == ["a", "c"]  # b invalid (skipped), dup rejected; c usable despite warning
    joined = "\n".join(errors)
    assert "missing required keys" in joined
    assert "unknown key 'unknown_key'" in joined
    assert "duplicate source_id" in joined


def test_sync_and_due_cadence(tmp_path, engine_config):
    write(
        engine_config,
        [
            {
                "source_id": "fresh",
                "display_name": "Fresh",
                "organization": "F",
                "adapter": "greenhouse",
                "endpoint_config": {"board": "f"},
                "validation_status": "validated",
                "cadence_hours": 24,
            },
            {
                "source_id": "stale",
                "display_name": "Stale",
                "organization": "S",
                "adapter": "greenhouse",
                "endpoint_config": {"board": "s"},
                "validation_status": "validated",
                "cadence_hours": 24,
            },
            {
                "source_id": "unvalidated",
                "display_name": "U",
                "organization": "U",
                "adapter": "greenhouse",
                "endpoint_config": {"board": "u"},
                "validation_status": "pending",
            },
            {
                "source_id": "disabled",
                "display_name": "D",
                "organization": "D",
                "adapter": "greenhouse",
                "endpoint_config": {"board": "d"},
                "validation_status": "validated",
                "enabled": False,
            },
        ],
    )
    sources, errors = load_sources(engine_config.sources_file)
    assert not errors
    conn = make_db(tmp_path)
    sync_sources_to_db(conn, sources)

    def check(state: str, when: datetime) -> None:
        conn.execute("DELETE FROM source_checks")
        for sid in ("fresh", "stale"):
            conn.execute(
                "INSERT INTO source_checks (source_id, checked_at, state) VALUES (?, ?, ?)",
                (sid, when.isoformat(), state),
            )

    now = datetime.now(UTC)
    check("healthy", now)
    due = {s.source_id for s in due_sources(conn, sources)}
    assert "fresh" not in due and "stale" not in due

    check("healthy", now - timedelta(hours=25))
    due = {s.source_id for s in due_sources(conn, sources)}
    assert {"fresh", "stale"} <= due
    assert "unvalidated" not in due and "disabled" not in due

    # a failed recent check does NOT suppress a source whose last success is old
    conn.execute("DELETE FROM source_checks")
    conn.execute(
        "INSERT INTO source_checks (source_id, checked_at, state) VALUES ('fresh', ?, 'check-failed')",
        ((now - timedelta(hours=1)).isoformat(),),
    )
    conn.execute(
        "INSERT INTO source_checks (source_id, checked_at, state) VALUES ('stale', ?, 'healthy')",
        ((now - timedelta(hours=30)).isoformat(),),
    )
    due = {s.source_id for s in due_sources(conn, sources)}
    assert "fresh" in due and "stale" in due
