-- Additive public-source facts; stable candidate identities are unchanged.
ALTER TABLE opportunities ADD COLUMN source_constraints_json TEXT;
