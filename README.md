# opportunity-discovery

A deterministic, local **opportunity-discovery engine** for technical students.
It collects broad public internship / research / program / event leads from
polite public sources, keeps every candidate in local SQLite storage,
reconciles duplicates, detects changes over time, applies transparent generic
relevance signals, and emits compact versioned packets for a later private
review layer.

**What it is not:** it is not an applicant tracker, not a dashboard, and never
makes applicant-specific eligibility or priority decisions. It produces
`unverified-lead` records only — see `docs/INTEGRATION_CONTRACT.md`.

## Outcome

After a normal run you get (in `output/`, regenerated atomically each run):

| Artifact | Purpose |
| --- | --- |
| `candidates.jsonl` | Complete normalized export of every retained lead |
| `review_queue.jsonl` | All currently plausible broadly relevant leads |
| `delta_packet.json` (+ `.pN.json` pages) | Compact packet of only new/materially-changed/reopened leads since the last successful export — designed for token-efficient downstream review |
| `run_summary.json` | Counts, exit code, artifact hashes |
| `source_health.json` | Per-source health: healthy / valid-empty / degraded / check-failed / rate-limited / format-changed / disabled / quarantined |

JSON Schemas for every external artifact are in `schemas/`.

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
.\scripts\install.ps1                 # normal install with checks, or manually:
py -3.14 -m venv .venv
.\.venv\Scripts\pip install -e .      # normal installation (runtime only)
.\scripts\run.ps1                     # normal scheduled run (logs + exit codes)
```

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
opdisc validate-config    validate configuration and registry files
opdisc validate-sources   live-probe enabled sources and record health
opdisc collect            one collection pass (no exports)
opdisc run                full deterministic workflow
opdisc export             rewrite export artifacts from stored state
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

- Local-only. No accounts, no API keys, no model inference, no submissions.
- No personal data is stored or exported; generated runtime data (`data/`,
  `output/`, `logs/`) is git-ignored and must stay untracked.
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
