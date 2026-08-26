# Troubleshooting

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | No source failed, no sources were due, or at least one attempted source succeeded (partial source failures are tolerated and visible in `source-health`) |
| 1 | All attempted sources failed this run (prior state preserved) |
| 2 | Fatal: config/registry error or unexpected crash |
| 3 | Another run holds `data/run.lock` |

## Installation

**`install.ps1` reports "No Python 3.11+ interpreter found"**
The installer tried the Windows py launcher (`py -3.11` through `py -3.14`)
and `python.exe` on PATH; none provided a working Python ≥ 3.11. Install
Python 3.11+ from python.org (enable "Add python.exe to PATH") and re-run.
The installer and the manual commands in `docs/OPERATIONS_WINDOWS.md` are
alternatives — either produces the same `.venv`.

## Common issues

**`another run appears active`**
A previous run crashed leaving a stale lock. The lock self-heals if the pid is
dead; otherwise delete `data/run.lock` after confirming no `opdisc` process is
running.

**A source shows `format-changed`**
The live response no longer matches the adapter's expected shape. Re-run
`opdisc validate-sources --source-id …`; if confirmed, quarantine the source
with a reason and file an adapter fix (fixtures first).

**A source shows `rate-limited` repeatedly**
Increase its `cadence_hours` or the global per-domain interval in
`config/default.toml`. Never hammer endpoints.

**Records disappeared from review_queue but exist in candidates.jsonl**
They were excluded by deterministic reason codes (`exclude:*`). Inspect
`reason_codes` in `candidates.jsonl`; adjust suppression rules only via
reviewed code changes with tests.

**Second run shows new records that shouldn't be new**
Identity changed — usually a URL whose requisition parameter is being stripped
or an aggregator changing link format. Check `identity_basis`; add the param
to `PRESERVE_PARAMS` in `urlnorm.py` with a test.

**Windows: `os.replace` fails on exports**
Another process holds the target file open (editor/sync tool). Close it;
exports retry-safe because temp files remain until replace.

**Live validation DNS failures for specific hosts**
Record honestly as quarantined with the failure text. Do not disable robots or
retry aggressively.
