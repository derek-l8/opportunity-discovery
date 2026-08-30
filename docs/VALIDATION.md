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
