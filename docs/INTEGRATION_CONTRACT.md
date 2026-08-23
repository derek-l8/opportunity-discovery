# Integration contract — public discovery layer ⇄ private AI workflow

## The division

### This repository (public lead layer) determines and exports:

- what a **public source says**;
- source provenance and health;
- record identity and duplicate relationships;
- generic category and role-family tags;
- posted dates and stated deadlines (+ timezone when stated);
- location text/components and remote/hybrid/in-person signals;
- explicit compensation/funding/relocation text as stated by the source;
- explicit class-year / graduation-window / major / work-authorization
  **language** quoted from the source (never an adjudicated status);
- generic technical relevance signals with inspectable components;
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
| `output/run_summary.json` | `schemas/run-summary.schema.json` |
| `output/source_health.json` | `schemas/source-health.schema.json` |

## Delta packet semantics

- Contains only leads whose `change_type` ∈ {`new`, `materially-changed`,
  `deadline-changed`, `reopened`} since the last successful export checkpoint.
- Omits unchanged candidates entirely; full state remains available in
  `candidates.jsonl`.
- Uses bounded excerpts plus description hashes so downstream tools can fetch
  or diff without bulk text.
- Includes counts before/after filtering and an `estimated_chars`
  token-cost proxy per page.
- Never silently truncates: if content exceeds `export.packet_char_limit`,
  additional `.pN.json` pages are emitted with `pagination.next_file`
  continuation metadata.

## Compatibility rules

- `schema_version = "1.0"` today. Future minor versions may add optional
  fields only; consumers must ignore unknown fields. Breaking changes bump the
  major version and rename artifacts (no in-place mutation).
- Stable `opportunity_id`s persist across runs so downstream dismissals stick;
  a new collection cycle or a materially different requisition legitimately
  reappears.

## Recommended consumption flow (private side)

1. Read `delta_packet.json`; follow pagination if present.
2. For each lead: check `reason_codes`, restrictions language, deadline.
3. Verify shortlisted leads on their canonical official pages (this engine
   does not verify).
4. Persist your own decisions keyed by `opportunity_id`.
