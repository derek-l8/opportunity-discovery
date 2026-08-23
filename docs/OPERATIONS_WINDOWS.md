# Operations — native Windows

Production runs on native Windows Python. WSL is a development convenience
only; nothing at runtime depends on it.

## Install (PowerShell, one-time)

```powershell
cd path\to\opportunity-discovery
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\pip install -e .
.\scripts\install.ps1        # or run the above manually; validates the install
```

## Normal run

```powershell
.\.venv\Scripts\opdisc.exe init
.\.venv\Scripts\opdisc.exe validate-config
.\.venv\Scripts\opdisc.exe validate-sources     # one-time + after registry edits
.\scripts\run.ps1                               # scheduled-run entry point
```

`scripts/run.ps1`:

- runs `opdisc run --quiet`,
- appends output to `logs\run-YYYYMMDD.log`,
- maps exit codes: `0` ok, `1` partial source failures, `2` fatal,
  `3` already-running (lock),
- surfaces the code to Task Scheduler as the task result.

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
