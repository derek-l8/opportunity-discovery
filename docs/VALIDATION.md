# Validation record

Every architectural/scoring/adapter change must append its commands and
actual results here. Results below were produced during the initial build on
2026-08-23 (WSL Ubuntu, Python 3.12.3). Windows CI is configured; native
Windows steps still to run after cloning are listed at the end.

## Environment

- Linux (WSL2), Python 3.12.3, repository-local `.venv`
- Install: `python3 -m venv --without-pip .venv && .venv/bin/python get-pip.py && .venv/bin/pip install -e '.[dev]'`

## Deterministic quality gates (actual results)

| Gate | Command | Result |
| --- | --- | --- |
| Linter | `.venv/bin/ruff check src tests` | All checks passed (0 findings) |
| Type checker | `.venv/bin/mypy` | Success: no issues in 33 source files |
| Test suite | `.venv/bin/python -m pytest -q` | 84 passed, 0 failed, no network required |
| Coverage | `pytest --cov=opportunity_discovery` | ~82% total; pipeline 95%, export/scoring/adapters ≥90% |
| Package build | `.venv/bin/python -m build` | sdist + wheel built successfully |
| Export schemas | `tests/test_schemas.py` | candidates/review-queue/delta-packet/run-summary/source-health all validate against `schemas/*.schema.json` |

## Synthetic end-to-end determinism

`tests/test_e2e.py::test_synthetic_end_to_end_twice` (file:// synthetic source):

- Run 1: 3 records → 3 new opportunities, review queue excludes the school-term co-op with reason code.
- Run 2 (identical): **0 new, 0 changed**, empty delta packet — no false delta.

## Publication audit

`.venv/bin/opdisc audit .` → scanned 97 tracked files, 0 errors.
(Before the first commit the working-tree preview correctly flags generated
`data/` and `output/` content; after committing only safe files it reports
0 errors. Re-run before every push.)

## Live validation of sources (bounded, polite)

Command: `.venv/bin/opdisc --json validate-sources` (concurrency 6, per-domain throttle).

Result: **248 validated** (all enabled sources probed live on 2026-08-23 and
responded in expected format), **24 quarantined/disabled** with recorded
reasons (attempted URL + failure detail preserved in `config/sources.toml`).
Zero enabled sources failed validation. Quarantine reasons include: Workday
tenant/site identifiers that could not be validated (NVIDIA/AMD/Capital One/
Goldman/Citadel/IMC), custom career portals without stable public feeds
(Google/Microsoft/Apple/Meta/Uber/Two Sigma/Jane Street/D.E. Shaw/Salesforce/
TikTok), JS-rendered program pages (USAJOBS/SWE/GHC), TLS/certificate mismatch
(Tapia), HTTP 403 access control respected (NSF GRFP), DNS failure from this
environment (UCLA URC).

## Live end-to-end smoke runs (2026-08-23)

Commands: `.venv/bin/opdisc init && .venv/bin/opdisc --json run --force` twice.

| Metric | Run 1 | Run 2 |
| --- | --- | --- |
| Sources attempted / succeeded / failed | 248 / 248 / 0 | 248 / 248 / 0 |
| Records seen | 18,878 | 18,878 |
| Opportunities new | 18,642 | **0** |
| Opportunities changed | 215 | **0** |
| Delta packet candidates | 18,642 (paginated) | **0** |
| Review queue | 11,046 | 11,046 |
| Source health after | healthy 248, disabled 24 | healthy 248, disabled 24 |
| Wall time | ~5 min | ~4 min |

The second identical live run emitted **no new records and an empty delta
packet**, satisfying the false-delta acceptance criterion.

## Defects found and fixed during validation

1. 304 Not-Modified responses were misclassified as `format-changed`.
2. 304 responses skipped parsing the cached body, causing phantom misses and
   mass false closures/reopenings; adapters now parse cached payloads.
3. Aggregator-vs-official field variants ping-ponged each run; fixed with a
   field-ownership policy (migration 0002) — first writer wins, official
   sources override aggregators.
4. Same-source duplicate URLs within one batch caused A↔B oscillation; fixed
   with intra-batch dedupe.
   Each fix has a regression test.

## Remaining limitations

- SmartRecruiters cannot distinguish unknown companies from genuinely empty
  boards; those sources were only validated with non-empty probes.
- Workday coverage is limited to Intel until more tenant/site identifiers are
  publicly confirmable.
- Windows-native execution has not been run in this environment; CI covers
  Windows for tests, but Task Scheduler scripts need one manual verification
  after cloning (see below).

## Native Windows steps to run after cloning

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\pip install -e '.[dev]'
.\.venv\Scripts\ruff check src tests
.\.venv\Scripts\mypy
.\.venv\Scripts\pytest -q
.\.venv\Scripts\opdisc init
.\.venv\Scripts\opdisc validate-config
.\.venv\Scripts\opdisc validate-sources     # live, ~10 min
.\scripts\run.ps1                            # normal run; check logs\ and output\
# review, then optionally:
.\scripts\register-task.ps1                  # installs nothing by itself
```

## Operational re-validation (Linux sandbox; runs on 2026-08-25 UTC = 2026-08-24 evening America/Los_Angeles)

Environment: Debian Linux (non-WSL), CPython 3.12.14 (uv-managed), fresh `.venv`.
All run timestamps below are recorded in UTC from `collection_runs` / run summaries.

### Deterministic gates (all reproduced, no drift)

| Gate | Command | Result |
| --- | --- | --- |
| Linter | `ruff check src tests` | All checks passed |
| Type checker | `mypy` | Success: no issues in 33 source files |
| Test suite | `pytest -q -m "not live" --cov=opportunity_discovery` | 84 passed, ~82% total coverage |
| Publication audit | `opdisc audit .` | 92 tracked files scanned, 0 errors, 0 warnings |

### First live operational run

`opdisc init` (migrations [1,2], 272 sources synced) → `validate-config` OK →
`opdisc --json validate-sources` → 248 validated / 24 quarantined (unchanged
from build-time validation; zero new failures) → `opdisc --json run`
(run `run-20260825T030725044909Z`, started 2026-08-25T03:07:25Z, finished
2026-08-25T03:12:06Z, wall clock 4m41s, exit 0).

- Sources attempted/succeeded/failed: **248 / 248 / 0** — all `healthy`,
  no rate-limiting observed from a datacenter egress IP.
- Records seen: 18,989; opportunities new: **18,742**, changed: 230,
  closed: 0 (first run, so everything is new).
- Review queue: 11,112 entries (`include:broad-relevance`; 7,517 also carry
  `downrank:unpaid-generic`). Pass-through ratio ≈ 59% — high, as expected on
  a first ingest of full ATS boards; to be re-measured once delta cycles start.
- Duplicates: 176 merges, all on the legitimate `normalized-url-equal` basis;
  no fuzzy or title-based merges.
- Novel-yield concentration: top sources are full corporate Greenhouse boards
  (`greenhouse-andurilindustries` 2,221; `greenhouse-spacex` 2,171) — ~23% of
  all stored records from two boards. Not actionable now; flagged for the next
  audit cycle (candidate-yield vs review-noise trade-off).
- Every enabled source contributed ≥1 new lead this cycle; zero-record and
  stale-source lists are empty.
- Artifacts validated against `schemas/*.schema.json`: `run_summary.json` and
  `source_health.json` fully valid; 4,000 sampled JSONL lines across
  `candidates.jsonl` / `review_queue.jsonl` all valid.
- Delta packet: 420 pages × ~143 KB (first-run artifact; steady-state packets
  should shrink to near-empty per the false-delta criterion).

### Skipped cadence-window run

A normal `opdisc --json run` inside the cadence window
(run `run-20260825T043441173620Z`, 2026-08-25T04:34:41Z–04:34:43Z) correctly
skipped collection: sources attempted 0, delta 0, exit 0. This confirms
cadence gating but is not a determinism test (no collection occurred).

### Forced second live run (near-empty live delta)

Command: `opdisc run --force` (run `run-20260825T043603512490Z`, started
2026-08-25T04:36:03Z, finished 2026-08-25T04:41:10Z, exit 0).

| Metric | Value |
| --- | --- |
| Sources attempted / succeeded / failed | 248 / 248 / 0 |
| Records seen | 18,982 |
| Opportunities new | **20** |
| Opportunities changed | **0** |
| Opportunities closed | **0** |
| Delta before filtering / after filtering | 20 / 20 |
| Total candidates in store | 18,762 |
| Review queue | 11,120 |

Interpretation:

- The forced second collection produced a **near-empty live delta**: the 20 new
  leads are ≈0.1% of the 18,762-candidate store and are consistent with public
  boards changing between runs ~90 minutes apart.
- Zero changed opportunities → no false material changes.
- Zero closed opportunities → no false closures.
- All 248 enabled sources succeeded on both live collections.

## CI portability repair (2026-08-25 UTC)

The first public GitHub Actions run failed in all four matrix jobs
(Ubuntu/Windows × Python 3.11/3.12) during test collection with
`ModuleNotFoundError: No module named 'tests'`: test modules imported reusable
utilities from `tests.conftest`, which only resolved because of
environment-specific implicit-namespace-package behavior in the dev checkout,
not from a clean clone. Fix:

- Reusable utilities (`MockFetcher`, `make_db`, `source`, `load_fixture`,
  `write_sources_toml`) moved from `tests/conftest.py` to `tests/helpers.py`;
  `conftest.py` now holds only pytest fixtures and imports shared helpers from
  `tests.helpers`.
- Added `tests/__init__.py` so the tests package is explicit in a clean checkout.
- Test imports updated `tests.conftest` → `tests.helpers`.
- CI workflow: bare `pytest` replaced with `python -m pytest`;
  `actions/checkout` v4→v6, `actions/setup-python` v5→v6; matrix, no-network
  marker, coverage, Ruff, Mypy, and publication-audit steps preserved.

Windows TOML path defect found behind the collection failure: the
`engine_config` fixture interpolated Windows paths directly into TOML
double-quoted strings, so `\U` was parsed as a unicode escape
(`tomllib.TOMLDecodeError: Invalid hex value`). All generated TOML now goes
through a shared JSON-escaping serializer (`tests.helpers.toml_str`), with a
deterministic regression test using Windows-style paths
(`tests/test_toml_serialization.py`), valid on Linux and Windows alike.

### Deterministic gates after repair (reproduced on CPython 3.11.2 and 3.12.14, uv)

| Gate | Command | Result |
| --- | --- | --- |
| Linter | `ruff check src tests` | All checks passed |
| Type checker | `mypy` | Success: no issues in 33 source files |
| Test suite | `python -m pytest -q -m "not live" --cov=opportunity_discovery --cov-report=term-missing` | 88 passed (84 prior + 4 new regression tests), ~82% total coverage |
| Clean-checkout discovery | full suite re-run in a fresh copy of tracked files | 88 passed — imports of `tests.helpers` resolve without any dev-environment state |
| Publication audit | `opdisc audit .` | 92 tracked files scanned, 0 errors, 0 warnings |
| Package build | `python -m build` | sdist + wheel built successfully |
### Remaining limitations after this cycle

- GitHub Actions passed the deterministic suite on Ubuntu and Windows under
  Python 3.11 and 3.12 (see the current-publication validation section below
  for the commit context). Native Windows PowerShell scripts (`scripts/run.ps1`,
  `install.ps1`, Task Scheduler registration) remain unverified on a real
  Windows host; CI coverage of the deterministic suite is not equivalent.
- Review-queue pass-through ratio remains to be re-measured once steady-state
  delta cycles accumulate.

## Current-publication validation snapshot

Date: 2026-08-25 UTC, after commit `b7ad544` ("Fix tests on clean Linux and
Windows environments (#1)"). Environment: Debian Linux, CPython 3.11.2,
repository `.venv`. This section records the state verified for public
release; it does not alter any historical result above.

| Gate | Command | Result |
| --- | --- | --- |
| Linter | `ruff check src tests` | All checks passed |
| Type checker | `mypy` | Success: no issues in 33 source files |
| Test suite | `python -m pytest -q -m "not live" --cov=opportunity_discovery --cov-report=term-missing` | 107 passed, ~82% total coverage |
| Publication audit | `opdisc audit .` | 95 tracked files scanned, 0 errors, 0 warnings |
| Package build | `python -m build` | sdist + wheel built successfully |
| Registry validation | `opdisc validate-config` | 272 sources loaded, no errors |

Still unverified at publication time:

- Native Windows PowerShell scripts (`install.ps1`, `run.ps1`,
  `register-task.ps1`) and Task Scheduler operation have never been exercised
  on a native Windows host.
- The GitHub Actions matrix status could not be re-inspected from this audit
  environment; see the repository's Actions tab for current results.
- No live collection was performed during this final audit; the recorded live
  results from 2026-08-25 above remain the latest live evidence.

## Public-readiness hardening cycle (2026-08-26 UTC)

Scope: tolerant exit-code contract for `opdisc run`/`opdisc collect` via a
shared helper (`runner.workflow_exit_code`), hardened publication audit
(blanket `tests//examples/` exemption removed), least-privilege CI workflow
permissions, and repaired Windows installer Python detection. No changes to
adapters, registry entries, identity, scoring, or export semantics.

### Environment

Debian Linux (sandbox), CPython 3.12.14 (uv-managed), repository-local
`.venv`, no network-dependent tests; dependency installation used the normal
public package index.

### Deterministic gates (actual results)

| Gate | Command | Result |
| --- | --- | --- |
| Linter | `.venv/bin/ruff check src tests` | All checks passed |
| Type checker | `.venv/bin/mypy` | Success: no issues in 33 source files |
| Test suite | `.venv/bin/python -m pytest -q -m "not live" --cov=opportunity_discovery --cov-report=term-missing` | **121 passed** (107 prior + 10 new exit-contract + 4 reworked/new audit tests), ~84% total coverage |
| Package build | `.venv/bin/python -m build` | sdist + wheel built successfully |
| Publication audit | `.venv/bin/opdisc audit .` | 95 tracked files scanned, 0 errors, 0 warnings |
| Registry validation | `.venv/bin/opdisc --json validate-config` | ok; 272 total sources, 248 enabled, 24 disabled — unchanged |
| Clean checkout | full suite + audit in a fresh copy of all current files | 121 passed; audit 0 errors |

### Exit-contract verification (tests/test_exit_contract.py)

New focused tests lock in the shared tolerant contract for both
`opdisc run` and `opdisc collect`: no-due-sources → 0; all attempted sources
failed → 1; partial failure → 0; configuration error → 2; registry fatal → 2;
held `run.lock` → 3. Helper unit tests cover `workflow_exit_code` directly.

### Audit hardening verification

- The old `_is_allowed` blanket exemption for `tests/` and `examples/` is
  gone; every rule now applies to every tracked file.
- Detection-shaped values in test source are constructed from runtime
  fragments, so no scan-matching credential or personal-path literal is
  tracked (`tests/test_audit.py`, `tests/test_cli.py`).
- New regression tests prove a prohibited credential under
  `tests/fixtures/`, a banned `.env` under `tests/fixtures/`, and a machine
  path under `examples/` are all still detected.
- A repository guard test runs the real audit against this checkout inside
  the suite, so any future scan-matching literal fails CI.

### CI workflow permissions

`.github/workflows/ci.yml` now declares top-level
`permissions: contents: read`. GitHub-owned Actions (`actions/checkout@v6`,
`actions/setup-python@v6`) and the OS/Python matrix are unchanged. The CodeQL
alert about missing explicit workflow permissions can only be confirmed
resolved on GitHub after the next push; it could not be verified from this
environment.

### Remaining limitations after this cycle

- **Native Windows execution was NOT verified in this environment** — there
  is no PowerShell host or Windows system available here. Specifically:
  `scripts/install.ps1` was rewritten (py-launcher candidates 3.11–3.14, then
  `python.exe` on PATH; each candidate must self-report ≥ 3.11; precise error
  when none qualify) but has never been executed; `scripts/run.ps1` behavior
  and Task Scheduler registration remain unexercised. These need one manual
  pass on a real Windows checkout before that claim can be made. CI's
  Windows matrix covers the Python package only, not the PowerShell scripts.
- No live collection or live `validate-sources` run occurred in this cycle;
  the 2026-08-25 live results above remain the latest live evidence.
- The publication-audit file count reflects currently tracked files (95);
  committing the new test file raises it to 96 with no expected findings.

## Python 3.14, Windows-installer, CI, and formatting repair (2026-08-30 UTC)

Scope: make Python 3.14 the recommended installation default while retaining
Python 3.11-3.14 support, prevent failed interpreter probes from terminating
the Windows installer, add deterministic native-Windows regression tests,
expand CI, and apply Ruff's formatter. No schema, scoring, identity,
collection, or exit-code semantic changes were made.

### Validation obtained on this host

Environment: Debian Linux, existing CPython 3.12.14 repository environment,
plus a fresh uv-managed CPython 3.14.7 environment. This host has no native
Windows or PowerShell runtime.

| Gate | Command | Result |
| --- | --- | --- |
| Initialize | `.venv/bin/opdisc init` | storage ready; no pending migrations; 272 sources synced |
| Configuration | `.venv/bin/opdisc --json validate-config` | ok; 272 total, 248 enabled, 24 disabled |
| Formatter | `.venv/bin/ruff format --check src tests` | 53 files already formatted |
| Linter | `.venv/bin/ruff check src tests` | All checks passed |
| Type checker | `.venv/bin/mypy` | Success: no issues in 33 source files |
| Deterministic tests (3.12) | `.venv/bin/python -m pytest -m "not live"` | 125 passed, 4 native-Windows tests skipped |
| Publication audit | `.venv/bin/opdisc audit .` | 97 tracked files scanned, 0 errors, 0 warnings |
| Whitespace check | `git diff --check` | passed with no output |
| Python 3.14 install | `UV_CACHE_DIR=/workspace/.tools/py314-cache .tools/uv pip install --python /workspace/.tools/py314-venv/bin/python -e '.[dev]'` | runtime and development dependencies installed successfully under CPython 3.14.7 |
| Python 3.14 formatter | `.tools/py314-venv/bin/ruff format --check src tests` | 53 files already formatted |
| Python 3.14 linter | `.tools/py314-venv/bin/ruff check src tests` | All checks passed |
| Python 3.14 deterministic tests | `.tools/py314-venv/bin/python -m pytest -m "not live"` | 125 passed, 4 native-Windows tests skipped |

`ruff format src tests` reported 47 reformatted files. One was the functionally
updated Windows test module; the other 46 files contain formatting-only
changes.

### Not obtained on this host

- A fresh native-Windows installer smoke test was not possible because no
  native Windows host is available.
- The native fallback, PATH fallback, no-compatible-interpreter, and fatal
  venv-creation cases are implemented as Windows-only PowerShell subprocess
  tests. They were collected but skipped on Linux and therefore still require
  execution by the expanded Windows CI matrix or a native Windows checkout.
- GitHub Actions was not run because this worktree was neither committed nor
  pushed.

## Package A collector/export correctness (2026-09-01, native Windows)

Scope: per-source multi-provenance closure evidence, configured review-queue
threshold enforcement, final-document delta pagination and stale-page cleanup,
complete derived-score refresh after material changes, bounded per-source
collection diagnostics, and a deterministic export generation manifest. No
live collection or live source validation was run.

Environment: Windows 10 (`10.0.26200`), PowerShell 7.6.4, bundled CPython
3.12.13, repository-local `.venv`. Neither `python.exe` nor `py.exe` was on the
shell PATH, so the bundled interpreter created the venv; declared `.[dev]`
dependencies were then installed into it.

| Gate | Command | Result |
| --- | --- | --- |
| Focused regressions | `.venv\Scripts\python.exe -m pytest -q tests\test_db_migrations.py tests\test_pipeline.py tests\test_export.py tests\test_adapters.py tests\test_schemas.py` | **45 passed** |
| Full deterministic suite | `.venv\Scripts\python.exe -m pytest -q -m "not live" --cov=opportunity_discovery --cov-report=term` | **134 passed**, 84% total coverage |
| Native PowerShell tests | `.venv\Scripts\python.exe -m pytest -q tests\test_windows_scripts.py -v` | **8 passed** |
| Initialize/migrate | `.venv\Scripts\python.exe -m opportunity_discovery init` | migrations `[1, 2, 3]` applied; 272 sources synced |
| Configuration | `.venv\Scripts\python.exe -m opportunity_discovery --json validate-config` | ok; 272 total, 248 enabled, 24 disabled |
| Formatter | `.venv\Scripts\python.exe -m ruff format --check src tests` | 53 files already formatted |
| Linter | `.venv\Scripts\python.exe -m ruff check src tests` | All checks passed |
| Type checker | `.venv\Scripts\python.exe -m mypy` | Success: no issues in 33 source files |
| Publication audit | temporary alternate Git index containing the complete uncommitted package, then `.venv\Scripts\python.exe -m opportunity_discovery audit .` | 99 files scanned, 0 errors, 0 warnings; real index remained clean |
| Whitespace | `git diff --check` | passed; only Git LF→CRLF checkout notices |

The focused closure regression proves that misses accumulate independently by
source: repeated complete misses from one source do not close a multi-source
record while another source is failed or unattempted; an observation resets
only its own counter; closure occurs only after every enabled,
non-quarantined provenance source reaches the configured threshold. The export
regressions verify the configured queue threshold, final encoded page limits,
bounded stale-page removal, exact manifest filenames/hashes, and schema-valid
diagnostics. The tolerant exit-code contract was unchanged and remains covered
by the full non-live suite.

## Review Package C combined integration (2026-09-01, native Windows)

Scope: integrate the independently validated collector/export correctness and
generic recurring-program changes from baseline
`bc0a45a2a1deea926dcc066eda0ac113e1d1ef83`. The additive migrations are ordered
as `0003_source_closure_and_diagnostics.sql` then `0004_program_pages.sql`.
Cross-package regressions cover coverage warnings as non-authoritative closure
checks, program records across delta pages and the export manifest, baseline
upgrades through both migrations, and combined optional-field schema validation.

Environment: native Windows, PowerShell 7.6.4, CPython 3.12.13 in the
repository-local `.venv`.

| Gate | Command | Result |
| --- | --- | --- |
| Formatter | `.venv\Scripts\python.exe -m ruff format --check src tests` | 56 files already formatted |
| Linter | `.venv\Scripts\python.exe -m ruff check src tests` | All checks passed |
| Type checker | `.venv\Scripts\python.exe -m mypy` | No issues in 34 source files |
| Non-live core + coverage | `.venv\Scripts\python.exe -m pytest -q -m "not live" --ignore=tests\test_windows_scripts.py --cov=opportunity_discovery --cov-report=term` | 141 passed; 84% coverage |
| Native Windows tests | `.venv\Scripts\python.exe -m pytest -q tests\test_windows_scripts.py -v` | 8 passed |
| Aggregate non-live suite | `.venv\Scripts\python.exe -m pytest -o addopts="" -q -m "not live"` | 149 passed |
| Initialize/migrate | `.venv\Scripts\python.exe -m opportunity_discovery init` | migrations `[1, 2, 3, 4]`; 272 sources synced |
| Configuration | `.venv\Scripts\python.exe -m opportunity_discovery --json validate-config` | ok; 272 total, 248 enabled, 0 errors |
| Schema tests | `.venv\Scripts\python.exe -m pytest -q tests\test_schemas.py` | candidate, delta, run-summary, source-health, and manifest artifacts valid, including program fields |
| PowerShell syntax | parser over `scripts/*.ps1` | 5 scripts parsed; 0 errors |
| Publication audit | `.venv\Scripts\python.exe -m opportunity_discovery audit .` | 108 tracked/intent-to-add files; 0 errors, 0 warnings |
| Whitespace | `git diff --check` | passed; line-ending advisories only |

No live collection, `validate-sources`, `scripts/run.ps1`, Task Scheduler
operation, GitHub Action, commit, push, PR, release, or repository setting
change was performed.

## Phase 1 integrated career profiles (2026-09-05 UTC)

Scope: integrate deterministic career normalization and the
`student-early-career`, `new-grad`, and `all-opportunities` routing profiles on
top of Phase 0 commit `3b9550bea380a9789b4d82c660d8834a0079c20c` without
replacing its program-page, closure-evidence, diagnostics, change-ID,
manifest, threshold, packet-limit, or HTTP-safety behavior. Phase 1 is migration
`0005_career_profiles.sql`, after Phase 0 migrations 0003 and 0004.

Environment: Debian Linux, CPython 3.12.14 from the existing development
environment. The integration checkout is
`/agent/scratch/opportunity-discovery-phase1-integration`.

| Gate | Command | Result |
| --- | --- | --- |
| Formatter | `PYTHONPATH=src /workspace/.venv/bin/ruff format --check src tests` | 58 files already formatted |
| Linter | `PYTHONPATH=src /workspace/.venv/bin/ruff check src tests` | All checks passed |
| Type checker | `PYTHONPATH=src /workspace/.venv/bin/mypy` | Success: no issues in 35 source files |
| Full deterministic suite | `PYTHONPATH=src /workspace/.venv/bin/python -m pytest -m 'not live' -ra` | 155 passed, 4 native-Windows tests skipped |
| Full suite with coverage | `PYTHONPATH=src /workspace/.venv/bin/python -m pytest -q -m 'not live' --cov=opportunity_discovery --cov-report=term` | 155 passed, 4 skipped; 84% total coverage |
| Migration/init | `PYTHONPATH=src /workspace/.venv/bin/opdisc init` | migrations through 0005 present; 272 sources synced; no pending migration in the validation DB |
| Configuration | `PYTHONPATH=src /workspace/.venv/bin/opdisc --json validate-config` | ok; 272 sources, 248 enabled, no errors |
| Package build | `PYTHONPATH=src /workspace/.venv/bin/python -m build` | sdist and wheel built; existing setuptools license-deprecation warnings only |
| Publication audit | audit of a clean `origin/main` archive overlaid with all 14 proposed product files | 123 files scanned; 0 errors, 0 warnings |
| Whitespace | `git diff --check` | passed with no output |
| Publication audit | intent-to-add the four new paths, then `PYTHONPATH=src /workspace/.venv/bin/opdisc audit .` | 112 tracked/intent-to-add files scanned, 0 errors, 0 warnings; index restored afterward |
| Whitespace | `git diff --check` | passed with no output |

The combined count retains the complete Phase 0 Linux suite (141 passing plus
4 Windows-only skips at the baseline) and adds 14 passing Phase 1 tests.
Focused coverage verifies upgrades through migrations 0003, 0004, and 0005;
stable-ID backfill; every profile decision; review threshold plus profile
routing; final packet-size enforcement; manifest/change-ID behavior; ordinary
job routing; and program-page routing with profile changes applied at export
without recollection.

### Live source validation result

`PYTHONPATH=src /workspace/.venv/bin/opdisc validate-sources` ran against all
272 registry entries. This host/proxy returned widespread decompression errors
(`DecodingError: incorrect header check`): 35 validated, 2
validated-empty-ok, 211 failed, and 24 remained configured quarantines. Two
large sources were separately and correctly rejected by Phase 0's
`max_response_bytes=5000000` control. The registry file remained unchanged.
The deterministic HTTP, adapter, source-health, and failure-preservation tests
all pass; no live-success claim is made from this run.

### Not obtained on this host

- Native Windows/PowerShell execution was unavailable. Four Windows-only test
  functions were collected and skipped; the baseline's prior native-Windows
  evidence remains recorded above.
- GitHub Actions was not run because no commit or push was made.

## Phase 2 provider-neutral review contract (2026-09-06 UTC)

Scope: retain Phase 1 routing and existing paginated delta exports while adding
a bounded Markdown review view, non-merging possible-duplicate hints, and a
provider-neutral source-backed review-response validator. The importer validates
the current export generation, manifest-listed candidate hash, and membership of
every decision ID before writing an atomic boundary artifact. Review Markdown
escapes source-controlled structure and labels it untrusted. The importer does not
mutate collector or private user state.

Environment: Debian Linux, CPython 3.12.14 in the existing repository-local
development environment. Base commit:
`390da1760babd62e1da8eb070783bfd2ede8b0f3`.

| Gate | Command | Result |
| --- | --- | --- |
| Formatter | `.venv/bin/ruff format --check src tests` | 60 files already formatted |
| Linter | `.venv/bin/ruff check src tests` | All checks passed |
| Type checker | `.venv/bin/mypy` | Success: no issues in 36 source files |
| Full deterministic suite + coverage | `.venv/bin/python -m pytest -m 'not live' -ra --cov=opportunity_discovery --cov-report=term` | 167 passed, 4 native-Windows tests skipped; 84% coverage |
| Configuration | `.venv/bin/opdisc --json validate-config` | ok; 272 sources, 248 enabled, no errors |
| Package build | `.venv/bin/python -m build` | sdist and wheel built; existing setuptools license-deprecation warnings only |
| Publication audit | temporary writable checkout with all product changes visible to `opdisc audit .` | 118 tracked/intent-to-add files scanned; 0 errors, 0 warnings |
| Whitespace | `git diff --check` | passed with no output |

### Live source validation result

The first `.venv/bin/opdisc --json validate-sources` attempt stopped before any
network validation because the pre-existing ignored `data/opdisc.sqlite3` has an
inconsistent migration ledger: the Phase 1 columns exist but migration 0005 is
not recorded. That user runtime database was not changed. The command was rerun
with a fresh temporary database and the unchanged repository registry. It
completed with 35 validated, 2 validated-empty-ok, 211 failed, and 24 configured
quarantines. As in Phase 1, this host/proxy produced widespread decompression
errors (`incorrect header check`), so no broad live-health claim is made and the
registry remains unchanged.

This correction pass did not repeat the live probe because the registry is
unchanged and the same host/proxy limitation remains. The deterministic suite
revalidated source-failure preservation and all revised Phase 2 behavior.

### Not obtained on this host

- Native Windows/PowerShell execution was unavailable; four Windows-only tests
  were collected and skipped.
- GitHub Actions and live AI-provider testing were not run. Phase 2 has no AI SDK,
  API key, or live-provider dependency.

## Phase 3 Windows workspace initialization (2026-09-08 UTC)

Scope: reintegrate external private-workspace scaffolding directly onto merged
Phase 2, correct canonical/external engine-path handling, retain the Windows
Documents-based location prompt and non-overwriting user instructions, and
tighten portable source-manifest paths. The engine does not inspect inbox
contents, mutate knowledge or board state, call an AI provider, or implement
Phase 4 behavior. Authoritative base commit:
`80a9b3c8b31f0e60b12fe53e15c831082162f020`.

Environment: Linux integration checkout at
`/agent/scratch/opportunity-discovery-phase3-integration`, using the existing
development environment from `/workspace/.venv` with `PYTHONPATH=src`.

| Gate | Command | Result |
| --- | --- | --- |
| Targeted Phase 3 suite | `PYTHONPATH=src /workspace/.venv/bin/python -m pytest -ra tests/test_workspace.py tests/test_windows_scripts.py tests/test_cli.py tests/test_schemas.py` | 32 passed, 4 native-Windows tests skipped |
| Full deterministic suite | `PYTHONPATH=src /workspace/.venv/bin/python -m pytest -ra` | 183 passed, 4 native-Windows tests skipped |
| Formatter | `PYTHONPATH=src /workspace/.venv/bin/ruff format --check src tests` | 62 files already formatted |
| Linter | `PYTHONPATH=src /workspace/.venv/bin/ruff check src tests` | All checks passed |
| Type checker | `PYTHONPATH=src /workspace/.venv/bin/mypy` | Success: no issues in 37 source files |
| Configuration | `PYTHONPATH=src /workspace/.venv/bin/opdisc validate-config` | ok; 272 sources, 248 enabled, no errors |
| Package build | `PYTHONPATH=src /workspace/.venv/bin/python -m build` | sdist and wheel built; existing setuptools license-deprecation warnings only |

Live source validation was not repeated: `config/sources.toml` is unchanged and
the same host/proxy decompression condition is already documented in the Phase
1 and Phase 2 results above.

### Not obtained on this host

- Native Windows execution of the updated location prompt was unavailable.
  Source-level installer assertions passed, but they are not native execution;
  four native-Windows tests were skipped.
- GitHub Actions was not run because no commit or push was made.
- Phase 3 has no AI provider integration; no provider smoke test applies.
