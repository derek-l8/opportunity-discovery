# Integration contract — public discovery ⇄ private workspace

## The division

The repository ships both the public collector and provider-neutral private
workspace commands. The boundary is between public collector data and private
runtime state, not between code repositories. Private workspace files must be
outside the Git checkout; selected leads move there only through explicit
human or tool actions. Collection never invokes AI review.

### The collector determines and exports:

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

### The private downstream workflow owns:

- a user-configurable screening profile and preliminary personal feed based on
  captured source text, before official research;
- verification of selected leads on canonical official pages before they are
  promoted to anything actionable;
- personal eligibility, fit, priority, ranking;
- the "Do now" / "Prepare next" action view;
- application pipeline status, outcomes, dismissal history;
- essays, resumes, drafts, and any model inference.

Collector SQLite, public exports, and Git-tracked files must never store or
export personal eligibility, personal priority, applicant work-authorization
status, graduation date, academic standing, pipeline status/outcomes,
dismissals, or application materials.

## Artifacts (all atomic, versioned)

| Artifact | Schema |
| --- | --- |
| `output/candidates.jsonl` | `schemas/candidate.schema.json` (one JSON object per line) |
| `output/review_queue.jsonl` | `schemas/review-queue-entry.schema.json` |
| `output/review_packet.md` | compact, bounded view; intentionally not a complete-state artifact |
| `output/delta_packet.json` + `.pN.json` pages | `schemas/delta-packet.schema.json` |
| `output/export_manifest.json` | `schemas/export-manifest.schema.json` |
| `output/run_summary.json` | `schemas/run-summary.schema.json` |
| `output/source_health.json` | `schemas/source-health.schema.json` |
| review response input / `output/review_response.json` | `schemas/review-response.schema.json` |
| private workspace `.opdisc/source-manifest.json` | `schemas/workspace-source-manifest.schema.json` |
| private workspace review input | `schemas/workspace-review.schema.json` |
| reasoned private feedback input | `schemas/workspace-feedback.schema.json` |
| private workspace `.opdisc/screening-profile.json` | `schemas/workspace-screening-profile.schema.json` |
| private workspace `.opdisc/screening.json` | `schemas/workspace-screening-state.schema.json` |
| optional private semantic screening input | `schemas/workspace-screening-response.schema.json` |

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

`review_packet.md` is a bounded first-pass AI or human review input, not the
private dashboard digest or a record of completed review. It selects up to 32
`included` leads by generic score and reserves eight places for
`research_needed` leads when available. Unused places are filled from the
remaining queue. Stable ID breaks score ties; official-source
observations, excerpts, and stated deadlines are displayed as evidence cues.
It shows at most 40 entries, includes why each surfaced, unknown
fields, source type, bounded excerpts and provenance links, and stops at
`export.packet_char_limit`.
Its footer states how many records were omitted. It is a convenience view, not a
pagination mechanism or a replacement for the JSON artifacts. A prominent warning
marks all source-controlled fields as untrusted data. Markdown-significant source
text is escaped so titles and excerpts cannot create packet structure; normalized
HTTP(S) links remain directly usable.

For a normal collection run, the packet header reports attempted, succeeded,
and failed source counts from that exact run and warns when coverage is partial.
An export-only refresh has no current collection health; its header says so
and treats any existing `run_summary.json` as an earlier run. In both cases,
read `source_health.json` for individual source checks.

The private dashboard Home reads imported workspace review decisions, not the
collector packet. With a configured private screening profile, Explore reads
all manifest-verified `candidates.jsonl` records, including leads excluded from
the generic queue. Screening status and official research status are separate.
The private opportunity focus prioritizes early programs, standard internships,
or entry-level full-time jobs without deciding eligibility. Suggested results
balance categories within those preference tiers and cap each employer, except
preferred exploratory and early-year programs in early mode. Explicit filters
and the uncapped view recover hidden leads. User decisions remain on the board.
Without that profile, or when public-queue mode is selected, Explore reads the
complete current review queue. Counts describe the current export generation,
not historical coverage across missed generations. Neither view runs AI review
automatically.

## Duplicate review hints

Exact normalized-URL duplicates continue to merge under the stable identity
rules. Distinct records from the same organization whose normalized title-token
sets overlap by at least 80% are instead exported with
`duplicate_state = possible_duplicate` and reciprocal stable IDs. This is a
review hint only: it creates no `duplicate_decisions` row and never merges data.

## Provider-neutral review response

`schemas/review-response.schema.json` defines advisory `promote`, `defer`,
`dismiss`, and `duplicate` dispositions backed by a current official URL and
check timestamp. A `duplicate` response additionally requires one of the stable
identity evidence classes; title similarity is not accepted as merge evidence.

`opdisc import-review RESPONSE.json` checks the contract and the current export
generation ID. It locates `candidates.jsonl` through the manifest, verifies the
recorded SHA-256, rejects malformed or duplicate candidate IDs, and requires every
decision ID (including `duplicate_of`) to belong to that generation. Only after all
checks pass does it atomically write `output/review_response.json`; a rejected
response cannot replace a prior valid file. It does not update SQLite or any private
board. The dispositions describe proposed handling by the later private workflow
and are not applicant decisions owned by this repository. Unknown extension
metadata is accepted and preserved only under a top-level or per-decision `custom`
object; unexpected sibling fields fail validation.

The importer validates structure, generation membership, artifact integrity, and
the syntax of claimed evidence fields. It does **not** fetch an evidence URL,
authenticate its publisher, compare page contents with the response, or
independently prove any factual claim. `reviewed_at` and evidence `checked_at` use
ISO-8601 timestamps with an offset or `Z`; an exact deadline uses an ISO-8601 date
or timestamp.

## Private workspace application

`opdisc workspace-apply-review WORKSPACE RESPONSE --manifest MANIFEST` is a
separate external-workspace operation. Its response includes the public review
fields plus an official-source classification, a private eligibility
conclusion, source-backed knowledge updates, and protected-change proposals.
The command validates the common fields through the same Phase 2 production
validator and verifies the candidate generation before writing private state.
It preflights every existing structured state file it will touch. Per
opportunity, `reviewed_at` cannot move backward; equal timestamps require the
same recorded input SHA-256 and are treated as exact replays.

A `promote` becomes an active private board item only when the official source
supports the current opportunity or upcoming cycle, availability is `open` or
`future-cycle`, no known hard eligibility failure remains, the response marks
the lead profile-relevant, and the public candidate has no deterministic hard
exclusion. Otherwise it stays `research_needed`. This threshold consumes a
private reviewer assertion; it does not fetch or authenticate the evidence
page itself. Defer, dismiss, and duplicate remain separate board states, and a
duplicate response does not rewrite public identity.

Verified availability, exact deadline, and private eligibility facts may
change. Existing `user_state`, proposal status and metadata, and nested
`custom` objects are preserved or merged. Response-level `custom` is retained
in the operation report. Engine code, source rules, schemas, hard filters, and
standing instructions are never changed: requested changes are stored as
non-binding proposals.

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
5. If returning structured review, copy the current manifest `generation_id` to
   `packet_generation_id`, validate with `opdisc import-review`, and consume the
   resulting file in private tooling.
