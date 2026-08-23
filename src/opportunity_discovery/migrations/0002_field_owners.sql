-- Migration 0002: track which source class owns each material field so
-- aggregator/official description variants do not ping-pong every run.
ALTER TABLE opportunities ADD COLUMN field_owner_json TEXT NOT NULL DEFAULT '{}';
