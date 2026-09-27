# opportunity-discovery

A deterministic, local **opportunity-discovery engine** for technical students.
It collects broad public internship / research / program / event leads from
polite public sources, keeps every candidate in local SQLite storage,
reconciles duplicates, detects changes over time, applies transparent generic
relevance signals and configurable career-profile routing, and emits compact versioned packets for a later private
review layer.

**What the collector is not:** it is not an applicant tracker or dashboard and
never makes applicant-specific eligibility or priority decisions. It produces
`unverified-lead` records only. Optional provider-neutral commands can apply a
separately produced review to the external private workspace; they are not part
of collection and do not call an AI provider. See `docs/INTEGRATION_CONTRACT.md`.

## Outcome

After a normal run you get (in `output/`, regenerated atomically each run):

| Artifact | Purpose |
| --- | --- |
| `candidates.jsonl` | Complete normalized export of every retained lead |
| `review_queue.jsonl` | Active, non-excluded broadly relevant leads meeting `scoring.review_queue_threshold` |
| `review_packet.md` | Score-ordered, bounded human-readable subset of the review queue; never the complete state |
| `delta_packet.json` (+ `.pN.json` pages) | Compact packet of new and granularly changed leads since the last successful export — designed for token-efficient downstream review |
| `export_manifest.json` | Deterministic generation ID, exact current delta page names, artifact hashes, and config/registry hashes |
| `run_summary.json` | Counts, exit code, artifact hashes |
| `source_health.json` | Per-source health, including coverage/format drift, seen/new/changed counts, elapsed time, and known pagination completeness |

JSON Schemas for every external artifact are in `schemas/`.

The default `student-early-career` profile routes internships, co-ops, research,
fellowships, programs, events, and early-career contracts while excluding
full-time/new-graduate roles and explicit graduate-degree requirements. Set
`routing.active_profile` to `new-grad` or `all-opportunities` to change review
lanes without deleting or recollecting candidates. Ambiguous public facts route to
`research_needed`; this is not a decision about any applicant.
Similar same-organization titles with distinct identities are exported as
`possible_duplicate` hints and are never merged without strong identity evidence.

## Quick start

Linux/WSL:

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/opdisc init                 # create/migrate SQLite storage
.venv/bin/opdisc validate-config      # validate config + source registry
.venv/bin/opdisc run                  # collect -> reconcile -> score -> export
```

Native Windows (PowerShell) — the installer and the manual commands are
alternatives; either produces the same repository-local `.venv`:

```powershell
# Recommended: put the actual Git checkout inside the private workspace.
$documents = [Environment]::GetFolderPath("MyDocuments")
$workspace = Join-Path $documents "Opportunity-Workspace"
New-Item -ItemType Directory -Force (Join-Path $workspace "engine")
git clone https://github.com/derek-l8/opportunity-discovery.git `
  (Join-Path $workspace "engine\opportunity-discovery")
Set-Location (Join-Path $workspace "engine\opportunity-discovery")
.\scripts\install.ps1 -WorkspacePath $workspace

# Existing checkout / engine-only alternatives:
.\scripts\install.ps1                 # normal install with checks, or manually:
py -3.14 -m venv .venv
.\.venv\Scripts\pip install -e .      # normal installation (runtime only)
.\scripts\run.ps1                     # normal scheduled run (logs + exit codes)
```

The installer also asks where to create the separate private workspace and
offers `Documents\Opportunity-Workspace` by default. Pass `-WorkspacePath`
for unattended setup or `-SkipWorkspaceSetup` for an engine-only install.
Existing workspace instruction and manifest files are always preserved.
The installer never moves, copies, reclones, or duplicates its active checkout.
An existing checkout outside the workspace is supported and recorded, with a
warning that a local agent opened only at the workspace root may not reach it.

A **normal installation** (`pip install -e .`) is all scheduled runs need.
A **development installation** adds test/lint/type tooling:
`.\.venv\Scripts\pip install -e '.[dev]'`.

Python 3.14 is the recommended default for new installations. Python 3.11,
3.12, 3.13, and 3.14 are supported; the installer selects the newest compatible
installed interpreter, so users without 3.14 can use 3.13, 3.12, or 3.11.
Existing virtual environments keep the Python version with which they were
created and do not upgrade automatically.

Task Scheduler setup/removal (does not run automatically; you invoke these):

```powershell
.\scripts\register-task.ps1     # creates the scheduled task
.\scripts\unregister-task.ps1   # removes/disables it
```

## Useful commands

```
opdisc init               initialize/migrate storage, sync registry
opdisc init-workspace DIR initialize an external private workspace without overwriting user files
opdisc validate-config    validate configuration and registry files
opdisc validate-sources   live-probe enabled sources and record health
opdisc collect            one collection pass (no exports)
opdisc run                full deterministic workflow
opdisc export             rewrite export artifacts from stored state
opdisc import-review FILE validate a source-backed review response against the current export
opdisc workspace-apply-review DIR FILE apply a validated review to external private state
opdisc workspace-apply-feedback DIR FILE record reasoned Done/Delete feedback and soft signals
opdisc workspace-board DIR read filtered, paginated private board state
opdisc workspace-done DIR ID mark Done (optional reason and soft signals)
opdisc workspace-delete DIR ID hide as Delete (optional reason and soft signals)
opdisc workspace-restore DIR ID restore a Done/Delete record
opdisc workspace-purge DIR ID remove a board record and ID-named artifacts
opdisc workspace-pipeline DIR ID STATE set private application pipeline state
opdisc workspace-wait DIR ID --reason TEXT mark explicitly waiting
opdisc workspace-resume DIR ID end explicit waiting
opdisc workspace-history DIR read private operation and board-action history
opdisc knowledge-snapshots DIR list bounded private knowledge history
opdisc compare-knowledge DIR ID compare current knowledge with a snapshot
opdisc restore-knowledge DIR ID restore after creating a pre-restore snapshot
opdisc backup-workspace DIR ZIP create a full or state-only unencrypted backup
opdisc restore-workspace DIR ZIP verify, pre-backup, and restore named files
opdisc workspace-audit DIR audit private Git exposure and reference integrity
opdisc source-health      per-source health states
opdisc status             concise engine status
opdisc audit              repository publication-safety audit
opdisc add-source ...     append a source to config/sources.toml
opdisc prune              retention pruning (dry-run by default)
```

All commands accept the global `--quiet`, `--json`, and `--config` options.
Place global options before the subcommand, for example
`opdisc --json status` or `opdisc --quiet run`.
`opdisc run` / `opdisc collect` share one tolerant exit contract:
`0` no source failed, nothing was due, or at least one attempted source
succeeded (a partial run is tolerated; failed checks remain visible in
`source-health` and prior successful state is preserved);
`1` sources were attempted but all failed; `2` fatal/config error;
`3` another run already active (lock).

`opdisc import-review` is a provider-neutral file-boundary validator. It requires
the response's generation ID to match the current `export_manifest.json`, preserves
unknown metadata only inside `custom`, and atomically writes
`output/review_response.json`. It does not call an AI provider or mutate collector,
board, applicant, or application state. The command verifies the manifest-recorded
candidate artifact hash and decision IDs, but does not fetch evidence URLs,
authenticate sources, or independently prove factual claims.

`opdisc init-workspace` creates the fixed external folder layout, short
provider entry files, canonical `WORKSPACE.md`, empty knowledge entry points,
and a versioned source manifest. It does not inspect inbox contents, derive
knowledge, call an AI provider, or mutate private decisions. See
`docs/WORKSPACE_INITIALIZATION.md`.
Structured private review, adaptive feedback, backup, and recovery are described
literally in `docs/PRIVATE_WORKSPACE_OPERATIONS.md`.

## Source registry

`config/sources.toml` is human-editable. At build time it contained
**272 entries**: 248 enabled sources whose adapters and endpoints were
validated against the live public web (ATS boards discovered via public
aggregate feeds plus named official lanes), and 24 honestly quarantined or
disabled entries that could not be validated — each with the attempted URL,
failure reason, and validation date recorded. Validation details:
`docs/VALIDATION.md`. Adding sources: `docs/ADDING_A_SOURCE.md`.

The engine never treats an aggregator or inferred field as verified evidence;
all exported leads are `unverified-lead`.

## Privacy & scope

- Local-only. No accounts, no API keys, no built-in model inference, no submissions.
- The public collector stores or exports no personal data. Explicit workspace
  commands can read and write private state only under the selected external
  workspace. That workspace and its unencrypted backups must stay untracked.
- Generated collector runtime data (`data/`, `output/`, `logs/`) is git-ignored
  and must stay untracked.
- `opdisc audit` scans the tree for credentials, `.env` files, private keys,
  machine paths, databases/logs/live payloads before anything is published.
- See `docs/SECURITY_AND_PRIVACY.md`.

## Development

```bash
.venv/bin/pip install -e '.[dev]'
.venv/bin/ruff check src tests
.venv/bin/mypy
.venv/bin/python -m pytest -q            # deterministic suite, no network needed
.venv/bin/python -m pytest -q -m live    # opt-in live-endpoint tests
```

CI runs the suite on Ubuntu and Windows across supported Python versions.
Docs start at `docs/ARCHITECTURE.md`; future coding agents should read
`AGENTS.md` first.

## License

MIT. See `LICENSE`.
