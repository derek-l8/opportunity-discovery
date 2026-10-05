# Architecture

## Code and data boundary

```
┌──────────────────────── Git checkout: code and templates ────────────────────────┐
│ Collector: fetch → normalize → reconcile → score → export public leads           │
│ Provider-neutral workspace tools: initialize, validate, apply, inspect, recover │
└──────────────────────────┬─────────────────────────────┬─────────────────────────┘
                           │ public runtime data         │ explicit workspace path
                           ▼                             ▼
                collector SQLite and exports    private files outside checkout
                (no applicant state)            (applicant state and decisions)
                           │                             ▲
                           └── selected leads, manually ─┘
```

The collector owns: what public sources say, provenance, identity, generic
categories, dates, locations, explicit compensation/funding/class-year/major/
work-authorization *language*, duplicate relationships, change detection, and
source health. It never owns personal eligibility or priority. Workspace tools
are shipped here, but their private runtime files must remain outside the Git
checkout. Collection does not invoke review or transfer leads automatically.
Human or optional AI review of selected official pages happens in the private
workflow.

## Module map (`src/opportunity_discovery/`)

| Module | Responsibility |
| --- | --- |
| `config.py` | TOML configuration loading + validation |
| `db.py` / `migrations/` | Versioned idempotent SQLite schema |
| `models.py` | Typed dataclasses (`SourceSpec`, `RawOpportunity`, …) |
| `urlnorm.py` | URL normalization, tracking-param stripping, ATS detection |
| `identity.py` | Stable candidate IDs (priority ladder, no fuzzy merging) |
| `http_client.py` | Polite fetching: public-destination and redirect validation, response/redirect bounds, concurrency, per-domain throttle, retries, conditional requests, cache fallback, robots.txt |
| `adapters/` | One adapter per source format; each distinguishes valid-empty from failure; per-source isolation in `run_source` |
| `extraction.py` | Decode full available ATS descriptions and extract bounded source facts before display truncation |
| `source_constraints.py` | Parse quoted public requirements, alternatives, waivers, and funding conditions |
| `registry.py` | Load `config/sources.toml`, validate entries, cadence-based due selection |
| `pipeline.py` | Fetch → observe → reconcile → detect changes → score |
| `scoring.py` | Deterministic keyword families, signals, effort estimate, season inference |
| `export.py` | Atomic versioned artifacts incl. paginated delta packets |
| `review_contract.py` | Provider-neutral review-response validation and atomic boundary import |
| `workspace.py` | External private-workspace initialization; user-owned starters are preserved |
| `workspace_state.py` | Validated private review/feedback application below an external workspace root |
| `workspace_discovery.py` | Read-only curated Home and manifest-verified Explore |
| `workspace_screening.py` | External private profile, whole-collection screening, optional semantic imports, category balance, and research freshness |
| `workspace_constraints.py` | Compare source requirements with documented private facts and prepare compact review inputs |
| `workspace_recovery.py` | Private knowledge snapshots, ZIP backup/restore, and workspace audit |
| `runner.py` | The normal workflow behind `opdisc run` |
| `validate_sources.py` | Live probes that record validation status |
| `audit.py` | Repository publication-safety audit |
| `lock.py` | Cross-platform run lock |
| `prune.py` | Explicit dry-run-default retention pruning |

## Data flow of one run

1. `ensure_ready`: open DB, apply pending migrations, sync registry.
2. Acquire `data/run.lock` (exit code 3 if another run is active).
3. Select due sources (enabled + validated + cadence elapsed).
4. For each source (isolated): adapter fetches/parses → `source_checks` row
   with a health state → observations upserted into `opportunities`.
5. Reconciliation merges only on strong evidence (identical normalized URL or
   provider+req ID); decisions recorded in `duplicate_decisions`.
6. Change detection compares field-level snapshots; failed checks mutate
   nothing. Closure requires N consecutive successful checks without the
   record.
7. Deterministic scoring stores components and reason codes.
8. Exports written atomically; delta computed against the last export
   checkpoint; checkpoints updated.
9. Run summary persisted; `run`/`collect` apply the shared tolerant exit
   contract (`runner.workflow_exit_code`): 0 when nothing failed, nothing was
   due, or at least one source succeeded; 1 only when all attempted sources
   failed; 2 for fatal/config errors; 3 when another run holds the lock.

## Failure isolation

Every source is processed inside its own try/except boundary. A crashing
adapter becomes a `check-failed` health row, never an aborted run and never a
"0 opportunities" success. Network failures fall back to the raw cache marked
`degraded`.

## Determinism

- Stable IDs are content-derived hashes; identical input state yields
  identical exports (byte-for-byte) — verified by tests.
- Complete JSON candidates are ordered by `opportunity_id`; the Markdown
  review packet uses its documented route-and-score order. Delta pagination
  splits on a character budget with continuation metadata, never truncation.

The workspace modules are not part of the scheduled public collection path.
They require an explicit workspace path and never write applicant-specific
state to the collector database or public output directory.

During onboarding an external AI asks about missing preferences and turns the
user's intended geographic regions into explicit city/metro aliases and
state/country context. The engine validates and uses that private configuration;
it does not invoke an AI provider or geocoder. Screening reads all manifest-verified
candidates, independently of generic public review-queue routing. Optional
bounded AI interpretations quote captured text and carry separate provenance.
Only the official-review importer creates verified board decisions.
