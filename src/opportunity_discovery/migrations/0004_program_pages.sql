-- Migration 0004: additive public program-page fields and latest granular events.

ALTER TABLE opportunities ADD COLUMN overview_url TEXT;
ALTER TABLE opportunities ADD COLUMN application_url TEXT;
ALTER TABLE opportunities ADD COLUMN program_family_id TEXT;
ALTER TABLE opportunities ADD COLUMN cycle_id TEXT;
ALTER TABLE opportunities ADD COLUMN event_start_date TEXT;
ALTER TABLE opportunities ADD COLUMN event_end_date TEXT;
ALTER TABLE opportunities ADD COLUMN application_state TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE opportunities ADD COLUMN requirements_text TEXT;
ALTER TABLE opportunities ADD COLUMN last_change_events_json TEXT NOT NULL DEFAULT '[]';

CREATE INDEX IF NOT EXISTS idx_opportunities_program_cycle
    ON opportunities(program_family_id, cycle_id);
