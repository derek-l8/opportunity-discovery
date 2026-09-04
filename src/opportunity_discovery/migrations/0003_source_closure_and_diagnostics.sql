-- Migration 0003: closure evidence belongs to an opportunity/source pair,
-- and source checks retain bounded collection diagnostics.

CREATE TABLE opportunity_source_state (
    opportunity_id TEXT NOT NULL REFERENCES opportunities(opportunity_id),
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    consecutive_successful_misses INTEGER NOT NULL DEFAULT 0,
    last_observed_at TEXT,
    last_checked_at TEXT,
    PRIMARY KEY (opportunity_id, source_id)
);

INSERT INTO opportunity_source_state (opportunity_id, source_id, last_observed_at)
SELECT opportunity_id, source_id, MAX(last_seen)
FROM provenance
GROUP BY opportunity_id, source_id;

UPDATE opportunities
SET signals_json = json_remove(signals_json, '$."_consecutive_misses"')
WHERE json_valid(signals_json)
  AND json_type(signals_json, '$."_consecutive_misses"') IS NOT NULL;

ALTER TABLE source_checks ADD COLUMN changed_records INTEGER NOT NULL DEFAULT 0;
ALTER TABLE source_checks ADD COLUMN pages_fetched INTEGER;
ALTER TABLE source_checks ADD COLUMN reported_total INTEGER;
ALTER TABLE source_checks ADD COLUMN truncated INTEGER;
