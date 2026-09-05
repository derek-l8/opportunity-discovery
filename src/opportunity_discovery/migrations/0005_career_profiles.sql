-- Migration 0005: normalized public career fields and deterministic routing.
-- Existing candidates remain stored and begin as unknown/research-needed until
-- the deterministic Python backfill runs; identity semantics do not change.
ALTER TABLE opportunities ADD COLUMN engagement_type TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE opportunities ADD COLUMN career_stage TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE opportunities ADD COLUMN required_degree TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE opportunities ADD COLUMN preferred_degree TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE opportunities ADD COLUMN experience_requirement_text TEXT;
ALTER TABLE opportunities ADD COLUMN experience_min_years INTEGER;
ALTER TABLE opportunities ADD COLUMN experience_max_years INTEGER;
ALTER TABLE opportunities ADD COLUMN active_profile TEXT NOT NULL DEFAULT 'student-early-career';
ALTER TABLE opportunities ADD COLUMN routing_state TEXT NOT NULL DEFAULT 'research_needed';
ALTER TABLE opportunities ADD COLUMN eligibility_confidence TEXT NOT NULL DEFAULT 'low';
ALTER TABLE opportunities ADD COLUMN profile_routes_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE opportunities ADD COLUMN routing_reason_codes_json TEXT NOT NULL DEFAULT '[]';

CREATE INDEX IF NOT EXISTS idx_opportunities_routing ON opportunities(active_profile, routing_state);
