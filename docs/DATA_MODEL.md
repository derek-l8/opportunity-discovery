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
`check-failed`, `rate-limited`, `format-changed`, `coverage-warning`), HTTP
status, detail, records seen/new/changed, conditional-request metadata, duration, pages fetched,
source-reported total, and known truncation. Health reporting reads the latest
row per source.

### `opportunities`
The canonical normalized lead store. Every plausible candidate ever collected stays here.
Key columns:

- Identity: `opportunity_id` (stable hash), `identity_basis` (human-readable evidence),
  `provider`, `provider_req_id`, `canonical_url` (normalized; tracking params stripped),
  `official_url`.
- Content: title + aliases, category, location components, remote/hybrid signal, season,
  employment type, posted/deadline dates (+tz), compensation/funding text,
  relocation text, bounded description excerpt + `description_hash`.
- Public career normalization: engagement type, career stage, required/preferred
  degree, and stated experience text plus conservative minimum/maximum years.
  Missing or ambiguous facts remain `unknown`/NULL.
- Optional recurring-program content: overview/application URLs, explicit
  program-family and cycle/session identifiers, exact event start/end dates,
  source-stated application state, and bounded requirements text. Application
  deadline remains separate from event dates.
- Explicit language captured verbatim-ish: class-year, graduation-window, major,
  work-authorization/sponsorship; requested application components.
- Source constraints: nullable `source_constraints_json` added by migration 6,
  exported as `source_constraints`. Bounded quotes record qualification modality,
  degree enrollment/completion, graduation alternatives, institution regions,
  authorization, clearance, program duration, and travel funding. NULL means
  unavailable extraction; `[]` means a successful extraction found no supported
  constraints. See the [integration contract](INTEGRATION_CONTRACT.md) for details.
- Deterministic evaluation: role-family tags, signals JSON, score components JSON,
  generic score, reason codes, effort estimate.
- Profile routing: decisions for all shipped profiles in `profile_routes_json`, plus
  the profile and route active when the row was last observed. Exports select the
  configured profile dynamically, so switching profiles does not require a refetch.
- Lifecycle: `lead_state` (always `unverified-lead` here), `change_type`, `active`,
  first/last seen, last changed, last successful check.

The latest granular change events are stored as a bounded JSON list on the
opportunity and each event is also appended to `changes`. Program-aware events
are `application-opened`, `application-closed`, `deadline-changed`,
`requirements-changed`, `dates-changed`, and `location-changed`. Page presence
(`active`) remains distinct from whether an application window is open.

Missing facts remain NULL or explicit `unknown` values, as defined by the export
schemas. A failed or incomplete source response preserves the last successful
facts; a complete description refresh can clear requirements removed by the source.

Greenhouse, Lever, Ashby, and available SmartRecruiters description content is
decoded and inspected before display excerpts are shortened. Separate Lever
lists and requirement headings take precedence over company introductions.
Bounded source language for student status, graduation, majors, authorization,
experience, compensation, and relocation is retained independently of the
display excerpt. Required/preferred degrees are normalized from the unbounded
transient requirement sections. Only explicit, unambiguous application dates
with a year become deadlines; missing or conflicting dates stay unknown.
Full descriptions are not stored. Existing rows acquire richer facts when
successfully fetched again; this code change does not backfill old exports.

## Career profiles

`routing.active_profile` selects one of three deterministic public-lead routes.
Routing changes review/export lanes only; it never deletes normalized history and
never determines whether a particular applicant is eligible.

- `student-early-career` includes internships, co-ops, student research,
  fellowships, programs, events, and early-career contracts. It excludes full-time
  and new-graduate roles, experienced roles, and postings that explicitly require
  a master's or doctorate. A posting open to multiple degree levels is not treated
  as graduate-degree-required.
- `new-grad` includes entry-level/new-graduate full-time roles whose stated
  experience ceiling is at most four years. It excludes internships, co-ops,
  student programs/events, experienced roles, and requirements of five years or
  more.
- `all-opportunities` includes every active broadly relevant opportunity type.

Ambiguous student/new-grad cases use `research_needed`, with low confidence,
instead of being silently excluded. `eligibility_confidence` is confidence in this
public-text routing classification—not applicant eligibility.

### `observations`
Immutable per-run snapshots of each raw record (run, source, opportunity, record JSON).

### `provenance`
Source-to-opportunity links with evidence level (`source-stated` /
`inferred-signal`), first/last seen. Multiple sources per opportunity preserved.

### `opportunity_source_state`

Per-opportunity, per-source closure evidence: consecutive complete-success
misses plus last-observed and last-checked timestamps. Failed, unattempted, and
known-truncated checks do not advance this state. Closure requires every
enabled, non-quarantined provenance source to reach the configured threshold.

### `aliases`
Alternate titles / prior values so renames do not lose history.

### `duplicate_decisions`
Audit log of reconciliations: kept id, merged id, basis
(`normalized-url-equal` today), detail, timestamp. Kept/merged ids are logical
references because a differently-keyed candidate may reconcile before insertion.

Possible duplicates are not stored in this table. Export computes a conservative,
deterministic same-organization title-overlap hint, keeps both stable records, and
emits reciprocal `possible_duplicate_ids` for external review.

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

For `program-page`, an explicitly configured `program_family_id` plus
cycle/session identifier becomes the provider requisition identity. This
keeps locations/cycles distinct even if an overview URL or title is shared.

IDs are SHA-256-prefixed hashes (`opp_…`) so they survive re-collection and
downstream dismissals persist across runs. Records with different identity keys
are never merged on title similarity; the only cross-key merge is an identical
normalized URL, logged in `duplicate_decisions`.

## Retention

Normalized history is retained indefinitely unless explicitly pruned. Raw cache
~30 days, logs ~14 days, source checks ~180 days (all configurable;
`opdisc prune` defaults to dry-run).
