-- Migration 0001: initial schema for opportunity discovery.

CREATE TABLE IF NOT EXISTS sources (
    source_id            TEXT PRIMARY KEY,
    display_name         TEXT NOT NULL,
    organization         TEXT NOT NULL,
    adapter              TEXT NOT NULL,
    landing_url          TEXT,
    endpoint_config_json TEXT NOT NULL DEFAULT '{}',
    categories_json      TEXT NOT NULL DEFAULT '[]',
    tags_json            TEXT NOT NULL DEFAULT '[]',
    cadence_hours        INTEGER NOT NULL DEFAULT 24,
    enabled              INTEGER NOT NULL DEFAULT 1,
    official_source      INTEGER NOT NULL DEFAULT 0,
    rate_limit_min_seconds REAL NOT NULL DEFAULT 0.0,
    last_validated       TEXT,
    validation_status    TEXT NOT NULL DEFAULT 'pending',
    provenance_note      TEXT,
    quarantine_reason    TEXT,
    created_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS collection_runs (
    run_id              TEXT PRIMARY KEY,
    started_at          TEXT NOT NULL,
    finished_at         TEXT,
    mode                TEXT NOT NULL,
    exit_code           INTEGER NOT NULL DEFAULT 0,
    sources_attempted   INTEGER NOT NULL DEFAULT 0,
    sources_succeeded   INTEGER NOT NULL DEFAULT 0,
    sources_failed      INTEGER NOT NULL DEFAULT 0,
    records_seen        INTEGER NOT NULL DEFAULT 0,
    opportunities_new   INTEGER NOT NULL DEFAULT 0,
    opportunities_changed INTEGER NOT NULL DEFAULT 0,
    opportunities_closed  INTEGER NOT NULL DEFAULT 0,
    summary_json        TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS source_checks (
    check_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id    TEXT NOT NULL REFERENCES sources(source_id),
    run_id       TEXT REFERENCES collection_runs(run_id),
    checked_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    state        TEXT NOT NULL,
    http_status  INTEGER,
    detail       TEXT,
    records_seen INTEGER NOT NULL DEFAULT 0,
    new_records  INTEGER NOT NULL DEFAULT 0,
    etag         TEXT,
    last_modified TEXT,
    duration_ms  INTEGER
);
CREATE INDEX IF NOT EXISTS idx_source_checks_source ON source_checks(source_id, checked_at);

CREATE TABLE IF NOT EXISTS opportunities (
    opportunity_id        TEXT PRIMARY KEY,
    identity_basis        TEXT NOT NULL,
    organization          TEXT,
    title                 TEXT,
    aliases_json          TEXT NOT NULL DEFAULT '[]',
    category              TEXT,
    canonical_url         TEXT,
    official_url          TEXT,
    provider              TEXT,
    provider_req_id       TEXT,
    location_text         TEXT,
    location_city         TEXT,
    location_state        TEXT,
    location_country      TEXT,
    remote_signal         TEXT,
    season                TEXT,
    employment_type       TEXT,
    posted_date           TEXT,
    deadline              TEXT,
    deadline_tz           TEXT,
    compensation_text     TEXT,
    relocation_text       TEXT,
    description_excerpt   TEXT,
    description_hash      TEXT,
    class_year_language   TEXT,
    graduation_window_language TEXT,
    major_language        TEXT,
    work_auth_language    TEXT,
    requested_components_json TEXT NOT NULL DEFAULT '[]',
    effort_estimate       TEXT,
    role_family_tags_json TEXT NOT NULL DEFAULT '[]',
    signals_json          TEXT NOT NULL DEFAULT '{}',
    score_components_json TEXT NOT NULL DEFAULT '{}',
    generic_score         REAL NOT NULL DEFAULT 0,
    reason_codes_json     TEXT NOT NULL DEFAULT '[]',
    lead_state            TEXT NOT NULL DEFAULT 'unverified-lead',
    change_type           TEXT NOT NULL DEFAULT 'new',
    active                INTEGER NOT NULL DEFAULT 1,
    first_seen            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    last_seen             TEXT NOT NULL,
    last_changed          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    last_successful_check TEXT
);

CREATE INDEX IF NOT EXISTS idx_opportunities_season ON opportunities(season);
CREATE INDEX IF NOT EXISTS idx_opportunities_change ON opportunities(change_type);

CREATE TABLE IF NOT EXISTS observations (
    observation_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL REFERENCES collection_runs(run_id),
    source_id       TEXT NOT NULL REFERENCES sources(source_id),
    opportunity_id  TEXT NOT NULL,
    observed_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    record_json     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_observations_opp ON observations(opportunity_id, observed_at);

CREATE TABLE IF NOT EXISTS provenance (
    provenance_id INTEGER PRIMARY KEY AUTOINCREMENT,
    opportunity_id TEXT NOT NULL REFERENCES opportunities(opportunity_id),
    source_id     TEXT NOT NULL REFERENCES sources(source_id),
    source_url    TEXT,
    evidence      TEXT NOT NULL DEFAULT 'source-stated',
    first_seen    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    last_seen     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(opportunity_id, source_id, source_url)
);

CREATE TABLE IF NOT EXISTS aliases (
    alias_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    opportunity_id TEXT NOT NULL REFERENCES opportunities(opportunity_id),
    alias_type     TEXT NOT NULL,
    value          TEXT NOT NULL,
    UNIQUE(opportunity_id, alias_type, value)
);

CREATE TABLE IF NOT EXISTS duplicate_decisions (
    decision_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    -- audit log only: kept/merged ids are logical references, not enforced FKs,
    -- because a differently-keyed candidate may be reconciled before insertion.
    kept_id      TEXT NOT NULL,
    merged_id    TEXT NOT NULL,
    basis        TEXT NOT NULL,
    detail       TEXT,
    decided_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(kept_id, merged_id)
);

CREATE TABLE IF NOT EXISTS changes (
    change_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    opportunity_id TEXT NOT NULL REFERENCES opportunities(opportunity_id),
    run_id        TEXT REFERENCES collection_runs(run_id),
    change_type   TEXT NOT NULL,
    changed_fields_json TEXT NOT NULL DEFAULT '{}',
    detected_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_changes_opp ON changes(opportunity_id, detected_at);

CREATE TABLE IF NOT EXISTS export_checkpoints (
    export_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    artifact     TEXT NOT NULL,
    exported_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    -- logical reference only; checkpoints may exist for runs finalized later
    run_id       TEXT,
    packet_hash  TEXT,
    counts_json  TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS raw_cache (
    url           TEXT PRIMARY KEY,
    fetched_at    TEXT NOT NULL,
    status        INTEGER,
    content_type  TEXT,
    content       BLOB,
    content_hash  TEXT,
    etag          TEXT,
    last_modified TEXT,
    expires_at    TEXT
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
