# Operations — native Windows

Production runs on native Windows Python. WSL is a development convenience
only; nothing at runtime depends on it.

## Install (PowerShell, one-time)

The installer and the manual commands are **alternatives** — either produces
the same repository-local `.venv` for a **normal installation** (runtime
package only, which is all scheduled runs need). For a **development
installation** (tests, Ruff, Mypy) use the dev extra shown at the end.

```powershell
cd path\to\opportunity-discovery

# Option A: installer (selects the newest compatible installed Python via the
#           py launcher or python.exe, then performs the same steps as Option B)
.\scripts\install.ps1

# Option B: manual
py -3.14 -m venv .venv                       # recommended for new installs
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\pip install -e .             # normal installation
```

Python 3.14 is the current recommended/default version. Python 3.11, 3.12,
3.13, and 3.14 remain supported, and the installer tries them newest-first.
If 3.14 is unavailable, use 3.13, 3.12, or 3.11. An existing `.venv` does not
automatically upgrade its Python; recreate it explicitly to change versions.

Development installation (instead of the plain `-e .` above):

```powershell
.\.venv\Scripts\pip install -e '.[dev]'
```

## Normal run

```powershell
.\.venv\Scripts\opdisc.exe init
.\.venv\Scripts\opdisc.exe validate-config
.\.venv\Scripts\opdisc.exe validate-sources     # one-time + after registry edits
.\scripts\run.ps1                               # scheduled-run entry point
```

`scripts/run.ps1`:

- runs `opdisc --quiet run` (global CLI options precede the subcommand),
- appends output to `logs\run-YYYYMMDD.log`,
- maps exit codes (same contract as `opdisc collect`): `0` no failures /
  nothing due / at least one source succeeded, `1` all attempted sources
  failed, `2` fatal/config error, `3` already-running (lock),
- surfaces the code to Task Scheduler as the task result.

A partial source failure still returns `0` by design: successful sources are
exported, failed checks preserve their last successful state, and details are
available in `output\source_health.json`. An all-source or hard failure is
recorded in `output\run_summary.json` when export finalization was reached;
the dated log always records the process exit code.

## Scheduled task

Review, then run manually — nothing is installed automatically:

```powershell
.\scripts\register-task.ps1      # creates "OpportunityDiscovery" daily task
.\scripts\unregister-task.ps1    # removes it (or disable via Task Scheduler GUI)
```

The task only ever executes `scripts\run.ps1`. It never rewrites source rules,
code, weights, or configuration.

## Windows-specific guarantees

- pathlib everywhere; no hardcoded drive letters or user paths.
- Atomic exports via temp file + `os.replace` (atomic on NTFS).
- Run lock (`data\run.lock`) prevents overlapping mutations; stale locks are
  reclaimed safely.
- Logs and JSON outputs are ASCII/UTF-8 safe for Task Scheduler capture.

## Retention & pruning

```powershell
.\.venv\Scripts\opdisc.exe prune          # dry-run report
.\.venv\Scripts\opdisc.exe prune --apply  # actually delete expired cache rows
```

Normalized history is never deleted by pruning.

## Troubleshooting

See `docs/TROUBLESHOOTING.md`.
