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
