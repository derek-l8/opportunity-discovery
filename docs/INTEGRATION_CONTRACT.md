# Integration contract — public discovery layer ⇄ private AI workflow

## The division

### This repository (public lead layer) determines and exports:

- what a **public source says**;
- source provenance and health;
- record identity and duplicate relationships;
- generic category and role-family tags;
- posted dates and stated deadlines (+ timezone when stated);
- public program overview/application URLs, cycle/session identifiers, exact
  event start/end dates, source-stated application state, and bounded public
  requirements text;
- location text/components and remote/hybrid/in-person signals;
- explicit compensation/funding/relocation text as stated by the source;
- explicit class-year / graduation-window / major / work-authorization
  **language** quoted from the source (never an adjudicated status);
- generic technical relevance signals with inspectable components;
- normalized public engagement type, career stage, degree language, and stated
  experience range;
- deterministic career-profile routing and confidence in that public-text
  classification (never applicant eligibility);
- generic application-effort estimate (`quick`/`moderate`/`substantial`/`unknown`);
- change detection over time;
- nothing else.

Every exported candidate is an `unverified-lead`. Aggregator provenance is not
official verification. Inferred fields are labeled `inferred-signal`. Missing
data is `unknown`.

### The private downstream layer owns:

- verification of selected leads on canonical official pages before they are
  promoted to anything actionable;
- personal eligibility, fit, priority, ranking;
- the "Do now" / "Prepare next" action view;
- application pipeline status, outcomes, dismissal history;
- essays, resumes, drafts, and any model inference.

This repository must never store or export: personal eligibility, personal
priority, applicant work-authorization status, graduation date, academic
standing, pipeline status/outcomes, dismissals, or application materials.

## Artifacts (all atomic, versioned)

| Artifact | Schema |
| --- | --- |
| `output/candidates.jsonl` | `schemas/candidate.schema.json` (one JSON object per line) |
| `output/review_queue.jsonl` | `schemas/review-queue-entry.schema.json` |
| `output/delta_packet.json` + `.pN.json` pages | `schemas/delta-packet.schema.json` |
| `output/export_manifest.json` | `schemas/export-manifest.schema.json` |
| `output/run_summary.json` | `schemas/run-summary.schema.json` |
| `output/source_health.json` | `schemas/source-health.schema.json` |

## Delta packet semantics

- Contains only leads whose `change_type` is exportable (`new`, `reopened`,
  material, deadline, application-state, requirements, event-date, or location
  change) since the last successful export checkpoint.
- Omits unchanged candidates entirely; full state remains available in
  `candidates.jsonl`.
- Uses bounded excerpts plus description hashes so downstream tools can fetch
  or diff without bulk text.
- Includes counts before/after filtering and the final encoded character count
  in `estimated_chars` for each page.
- Never silently truncates: if content exceeds `export.packet_char_limit`,
  additional `.pN.json` pages are emitted with `pagination.next_file`
  continuation metadata. Every final encoded page must fit the limit; export
  fails rather than silently oversizing a single unpageable candidate.
- Publishing a new generation removes only stale files matching the bounded
  `delta_packet.pN.json` naming pattern. `export_manifest.json`, written after
  the packet set, lists the exact current filenames and their hashes.

## Review queue semantics

An active lead enters `review_queue.jsonl` only when it has at least one role
family tag, has an active-profile route of `included` or `research_needed`, has
no `exclude:` reason code, and its `generic_score` is greater than or equal to
`scoring.review_queue_threshold`. All leads remain in SQLite and
`candidates.jsonl` regardless of review-queue membership.

## Compatibility rules

- `schema_version = "1.0"` today. Future minor versions may add optional
  fields only; consumers must ignore unknown fields. Breaking changes bump the
  major version and rename artifacts (no in-place mutation).
- Program fields and `change_events` are optional schema-v1
  additions. Existing consumers that ignore unknown fields remain compatible.
- Stable `opportunity_id`s persist across runs so downstream dismissals stick;
  a new collection cycle or a materially different requisition legitimately
  reappears.

## Recommended consumption flow (private side)

1. Read `export_manifest.json`, then read the exact files listed in
   `delta_packet_files` (or begin with `delta_packet.json` and follow pagination).
2. For each lead: check `reason_codes`, restrictions language, deadline.
   Treat `routing_state = research_needed` as unresolved public information, not
   an eligibility judgment.
3. Verify shortlisted leads on their canonical official pages (this engine
   does not verify).
4. Persist your own decisions keyed by `opportunity_id`.
