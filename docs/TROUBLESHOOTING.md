# Troubleshooting

## Installation

**PowerShell says running scripts is disabled.** Run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, then retry the script in the same window. This setting lasts only for that PowerShell window.

**No compatible Python interpreter found.** Install Python 3.11, 3.12, 3.13, or 3.14, then rerun the installer. It chooses the newest compatible version it finds.

**The clone destination already exists.** Do not clone again over an existing checkout. Follow the [update steps](OPERATIONS_WINDOWS.md#update-an-existing-installation) instead.

**`git pull` stops because of local changes.** For configuration edits, follow [Keep your settings when updating](OPERATIONS_WINDOWS.md#keep-your-settings-when-updating). Preserve other edits separately; do not discard them to force an update. If Git reports a conflict, stop and resolve it before rerunning the installer.

## Running and viewing results

**`opdisc` is not recognized.** From the engine checkout, use `.\.venv\Scripts\opdisc.exe` (or rerun the installer if `.venv` is missing).

**Dashboard Home is empty.** Home needs imported review decisions. Check **Explore** for the current public queue. If Explore says its export is unavailable, run `.\scripts\run.ps1` and check `output\source_health.json`.

**A scheduled run failed.** Check the newest `logs\run-YYYYMMDD.log` and `output\source_health.json`. Result code `1` means all attempted sources failed; `2` means a configuration or workflow error; `3` means another run is active. A partial source failure can still return `0`; check the health file for details.

**`another run appears active`.** Confirm no collection process is running before removing `data\run.lock`. A stale lock normally clears itself after a crashed process exits.

**`unrecognized arguments: --quiet` or `--json`.** Put these options before the command: `opdisc --quiet run` or `opdisc --json source-health`.

For a source whose format or rate limit has changed, see [adapter and source diagnostics](ADAPTERS.md).
