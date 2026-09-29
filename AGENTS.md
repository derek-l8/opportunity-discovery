# AGENTS.md — instructions for future coding agents

Read this before changing anything in this repository.

## What this repository is

This repository contains the public deterministic collector and provider-neutral
tools for an explicitly selected private workspace. The collector collects,
normalizes, deduplicates, and exports broad public opportunity leads. A separate
private review workflow consumes selected leads and owns all applicant-specific
work: verification on official pages, eligibility analysis, ranking, the "Do now" /
"Prepare next" action view, application management, and drafting.

The workspace tools and schemas are code in this repository. Runtime private
state must remain below the selected workspace root and outside the Git
checkout; it never belongs in collector SQLite, collector exports, or fixtures.

## Hard rules

1. **Keep applicant state private.** Applicant data and personal eligibility
   decisions are forbidden in this public repository, collector SQLite,
   fixtures, and public exports. Generic provider-neutral tools may read and
   write those values only within an explicitly selected external private
   workspace. No personal data may be committed, and this engine must not add
   a model/LLM/API dependency.
2. **Generated live data must remain untracked.** `data/`, `output/`, `logs/`,
   SQLite files, fetched payloads, caches — never commit them. Run
   `opdisc audit` before publishing anything.
3. **Source failures must not become empty results or closures.** A failed
   check preserves the last successful state. A record missing from one failed
   or partial response is not "closed"; closure requires consecutive
   *successful* checks (`change_detection.closed_after_consecutive_successes`).
4. **New adapters require fixtures, provenance, source-health behavior, and
   tests.** No adapter may be added with only live-endpoint evidence.
   Adapters must distinguish a valid empty result from a failure.
5. **Architectural or scoring changes require validation.** Update fixtures,
   run the full suite, run `opdisc validate-sources`, and record results in
   `docs/VALIDATION.md`. Do not silently change identity, reconciliation, or
   scoring semantics — stable IDs must survive so downstream dismissals
   persist across runs.
6. **Automatic scheduled runs must not rewrite source rules, code, weights,
   or configuration.** The Task Scheduler task only runs `scripts/run.ps1`
   (i.e., `opdisc run`). Registry edits are human/agent actions, reviewed,
   never automated.
7. **No application submission or authenticated-source automation is allowed.**
   No logins, no CAPTCHA bypassing, no rate-limit abuse, no scraping of paid
   or account-gated boards, no submissions/messages/uploads anywhere.

## Non-negotiable design invariants

- Two-layer data contract: this repo may record what a *public source says*;
  it must never determine personal eligibility or priority. See
  `docs/INTEGRATION_CONTRACT.md`.
- Missing information is `unknown`, never invented.
- All collected candidates stay in SQLite; filtering controls review/export
  lanes only, never destructive deletion of normalized history.
- Stable candidate identity: provider requisition ID > normalized official
  URL > org+req > exact composite. Never merge records on fuzzy title
  similarity.
- Exports are atomic (temp file + `os.replace`) and deterministic (stable
  ordering, stable hashes for identical state).
- Everything must work natively on Windows (pathlib only, no POSIX-only APIs,
  atomic replace via `os.replace`).
- Use `Path` for filesystem operations. For relative paths written to JSON,
  manifests, or command responses, use forward slashes
  (`path.relative_to(root).as_posix()`), not `str(path.relative_to(root))`.
- WSL/Linux tests do not verify native Windows behavior. Before calling a PR
  ready to merge, inspect all CI jobs, including Windows; fix failing checks
  or explicitly report that they remain unverified.

## Routine audit checklist for future agents

Measure, using the DB and exports (see `docs/AUDITING_AND_IMPROVEMENT.md` for
exact queries):

- Source success and degradation rates; sources that repeatedly fail or
  produce no novel value.
- Novel candidate yield per source and per cycle.
- Duplicate rate and false-merge samples (audit `duplicate_decisions`).
- Stale-source rate (sources with no new records for long windows that are
  still healthy).
- Generic filtering errors (review-queue misses/false includes sampled by
  hand).
- Packet size and run duration trends.
- Change-detection correctness (sample `changes` rows against live pages).

Routine audits **propose** changes (code, routing, registry entries) as
reviewable diffs. They do not silently self-modify production behavior.

## Where things live

- `src/opportunity_discovery/` — engine (adapters, pipeline, scoring, export,
  CLI). Start with `pipeline.py` and `scoring.py`.
- `config/default.toml` — engine configuration (season, fetch politeness,
  scoring bonuses, export limits).
- `config/sources.toml` — the public source registry (human-editable).
- `schemas/` — JSON Schemas for every external artifact.
- `tests/fixtures/` — synthetic fixtures for every adapter and failure mode.
- `scripts/` — Windows PowerShell wrappers + Task Scheduler registration and
  the bash development helper.
- `docs/` — architecture, data model, adapters, policies, operations.
