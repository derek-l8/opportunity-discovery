# Data model

SQLite database at `data/opdisc.sqlite3` (WAL mode, foreign keys on). Schema
is created by versioned SQL migrations in
`src/opportunity_discovery/migrations/` applied idempotently by `db.migrate`.

## Tables

### `sources`
Registry mirror of `config/sources.toml`: identity (source_id), display/organization,
adapter name, landing page, endpoint config JSON, categories, tags, cadence hours,
enabled flag, official-source flag, rate-limit policy, validation status/date,
provenance note, quarantine reason.

### `collection_runs`
One row per workflow run: timestamps, mode, exit code, source success/failure counts,
record and opportunity counters, summary JSON.

### `source_checks`
One row per adapter invocation: state (`healthy`, `valid-empty`, `degraded`,
`check-failed`, `rate-limited`, `format-changed`), HTTP status, detail, records seen/new,
conditional-request metadata, duration. Health reporting reads the latest row per source.

### `opportunities`
The canonical normalized lead store. Every plausible candidate ever collected stays here.
Key columns:

- Identity: `opportunity_id` (stable hash), `identity_basis` (human-readable evidence),
  `provider`, `provider_req_id`, `canonical_url` (normalized; tracking params stripped),
  `official_url`.
- Content: title + aliases, category, location components, remote/hybrid signal, season,
  employment type, posted/deadline dates (+tz), compensation/funding text,
  relocation text, bounded description excerpt + `description_hash`.
- Explicit language captured verbatim-ish: class-year, graduation-window, major,
  work-authorization/sponsorship; requested application components.
- Deterministic evaluation: role-family tags, signals JSON, score components JSON,
  generic score, reason codes, effort estimate.
- Lifecycle: `lead_state` (always `unverified-lead` here), `change_type`, `active`,
  first/last seen, last changed, last successful check, `_consecutive_misses` counter
  inside signals JSON driving conservative closure.

Missing information is stored as NULL and exported as `"unknown"` — never invented.

### `observations`
Immutable per-run snapshots of each raw record (run, source, opportunity, record JSON).

### `provenance`
Source-to-opportunity links with evidence level (`source-stated` /
`inferred-signal`), first/last seen. Multiple sources per opportunity preserved.

### `aliases`
Alternate titles / prior values so renames do not lose history.

### `duplicate_decisions`
Audit log of reconciliations: kept id, merged id, basis
(`normalized-url-equal` today), detail, timestamp. Kept/merged ids are logical
references because a differently-keyed candidate may reconcile before insertion.

### `changes`
Field-level change log: opportunity, run, change type, changed-fields JSON
(old/new pairs), detected time.

### `export_checkpoints`
Per-artifact export history (timestamp, run, packet hash, counts) used to compute
the next delta packet.

### `raw_cache`
Raw successful responses with ETag/Last-Modified and expiry for conditional
requests and degraded-mode fallback. Pruned by `opdisc prune`.

## Stable identity ladder

1. `prov:{provider}:{req_id}` — official ATS requisition ID (strongest).
2. `url:{normalized_url}` — stable official application URL.
3. `orgreq:{org}:{req_id}` — org plus explicit requisition ID.
4. `comp:{org}|{exact normalized title}|{location}` — conservative composite.

IDs are SHA-256-prefixed hashes (`opp_…`) so they survive re-collection and
downstream dismissals persist across runs. Records with different identity keys
are never merged on title similarity; the only cross-key merge is an identical
normalized URL, logged in `duplicate_decisions`.

## Retention

Normalized history is retained indefinitely unless explicitly pruned. Raw cache
~30 days, logs ~14 days, source checks ~180 days (all configurable;
`opdisc prune` defaults to dry-run).
