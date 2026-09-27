# Operations — native Windows

Production runs on native Windows Python. WSL is a development convenience
only; nothing at runtime depends on it.

## Install (PowerShell, one-time)

The installer and the manual commands are **alternatives** — either produces
the same repository-local `.venv` for a **normal installation** (runtime
package only, which is all scheduled runs need). For a **development
installation** (tests, Ruff, Mypy) use the dev extra shown at the end.

```powershell
# Recommended canonical layout: create the private parent, then place the
# actual public Git checkout at engine\opportunity-discovery.
$documents = [Environment]::GetFolderPath("MyDocuments")
$workspace = Join-Path $documents "Opportunity-Workspace"
New-Item -ItemType Directory -Force (Join-Path $workspace "engine")
git clone https://github.com/derek-l8/opportunity-discovery.git `
    (Join-Path $workspace "engine\opportunity-discovery")
Set-Location (Join-Path $workspace "engine\opportunity-discovery")

# Option A: installer (selects the newest compatible installed Python via the
#           py launcher or python.exe, then performs the same steps as Option B)
.\scripts\install.ps1 -WorkspacePath $workspace

# Option B: manual
py -3.14 -m venv .venv                       # recommended for new installs
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\pip install -e .             # normal installation
```

During Option A, setup prompts for a private workspace location and offers
`Documents\Opportunity-Workspace`. For a noninteractive run, pass an explicit
path; for an engine-only installation, opt out:

```powershell
.\scripts\install.ps1 -WorkspacePath "D:\Opportunity-Workspace"
.\scripts\install.ps1 -SkipWorkspaceSetup
```

The installer operates on its active checkout in place. It never moves, copies,
reclones, or duplicates that checkout. The initializer preserves all existing
workspace files. If the chosen workspace is
inside a Git checkout it emits a privacy warning, but does not override the
user's choice. `.opdisc\workspace.json` records the resolved checkout path and
is authoritative. Existing installations may keep their engine elsewhere, but
setup warns that an agent opened only at the workspace root may not be able to
access an external checkout. External mode does not create an empty or
misleading `engine\opportunity-discovery` directory.

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
## Private workspace review and recovery

These commands are manual file-boundary operations. They do not contact an AI
provider or a public website:

```powershell
opdisc workspace-apply-review $workspace .\review.json --manifest .\output\export_manifest.json
opdisc workspace-apply-feedback $workspace .\feedback.json
opdisc knowledge-snapshots $workspace
opdisc compare-knowledge $workspace SNAPSHOT_ID
opdisc restore-knowledge $workspace SNAPSHOT_ID
opdisc backup-workspace $workspace D:\PrivateBackups\opportunity-full.zip --kind full
opdisc backup-workspace $workspace D:\PrivateBackups\opportunity-state.zip --kind state
opdisc workspace-audit $workspace
```

`restore-knowledge` first records a pre-restore knowledge snapshot.
`restore-workspace` verifies every archive path and content hash and creates a
full pre-restore backup before changing files. Workspace ZIPs are unencrypted
and contain private information; store them accordingly. A state-only backup
omits `sources/`, `inbox/`, caches, and the engine checkout. A full backup adds
`sources/` and `inbox/`; both omit the engine checkout and symlinks.
