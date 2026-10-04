# Validation record

## Private workspace backups (2026-10-03)

Full backups include new workspace folders by default. Both backup modes include
`.agents/`, the dashboard launcher, and the two workspace-local collector settings
files. State-only backups retain their smaller, named scope. Generated caches,
Python environments, Git metadata, engine code, and previous workspace backup ZIPs
are excluded. Personal folders named `cache` or `temp` remain included.

| Check | Result |
| --- | --- |
| Native Windows Python 3.12.10, non-live suite | 303 passed; 8 symlink tests skipped for OS permissions; junction and PowerShell tests passed |
| Linux Python 3.12.3, non-live suite | 303 passed; 8 native-Windows tests skipped; all 36 applicable recovery tests passed |
| Production CLI rehearsal | Six commands on disposable workspaces; 55 byte-exact file round trips covering skills, arbitrary files, the launcher, settings, and pre-restore copies |
| Ruff format/lint, Mypy, configuration, wheel and sdist build | Passed; existing setuptools license-metadata warnings remain |
| Publication audit and diff whitespace | Passed; zero findings |

Regressions cover exact bytes, missing files, pre-restore recovery, archives
without skills, tampering, unsafe paths, arbitrary folders, ordinary ZIP
attachments, and symlink/junction protection. Restore checks every destination
for links before changing files. All 288 existing personal files were verified
unchanged. No live collection was run; Windows CI remains to be checked after a push.

## AI onboarding and dashboard launcher (2026-10-03)

Added a short setup guide with separate personal-information and board-review
prompts, concise workspace instructions, and a Windows dashboard launcher.
Existing user files are preserved. The original dashboard demo is unchanged.

| Check | Result |
| --- | --- |
| Linux Python 3.12.3, non-live suite | 284 passed; 7 native-Windows tests skipped |
| Native Windows Python 3.12.10, non-live suite | 286 passed; 5 symlink tests skipped for OS permissions |
| Ruff format/lint, Mypy, configuration, wheel build | Passed |
| Publication audit and diff whitespace | Passed; 160 files, zero findings before this record |
| Documentation links and PowerShell syntax | 31 relative links/anchors passed; installer and launcher parsed |

Native launcher tests cover spaces and punctuation in paths, engine relocation,
visible errors, and exit codes. Initialization tests cover existing-file
preservation. The installer was also executed in a disposable Windows checkout.
No AI intake or research session was executed; collector behavior is unchanged
and live collection was not rerun. Windows CI remains to be checked after a push.
The installed personal workspace was not changed.

## Curated Home and complete Explore (2026-09-29 UTC)

The uncommitted 32/8 Markdown packet remains a bounded input preview, not the
dashboard digest. Home now reads imported private review decisions, grouping
promoted active leads before reviewed leads needing investigation. Review
reasons, reported official-page check, unknowns, and a next action are visible;
public generic score does not order Home. Done/Delete, waiting, dismissed, and
application state still use the existing private board actions.

Explore reads the full current `review_queue.jsonl` only after checking its
hash against `export_manifest.json`. It searches title, organization, location,
and excerpts; filters by opportunity type, public route, and imported-review
status; and shows newly discovered leads first. Its counts distinguish imported
reviews from leads without one, not current verification. A missing or damaged
export is reported as unavailable. The synthetic walkthrough includes
an unreviewed lead that appears in Explore but not Home. No model is invoked.
Neither the packet nor delta export pages acknowledge AI work; batching across
sessions still needs a small private progress record for quick triage. This
change does not claim historical review coverage.

| Gate | Result |
| --- | --- |
| Full non-live Linux suite | 281 passed; 4 native PowerShell tests skipped |
| Ruff lint and format | Passed |
| Mypy | Passed, 43 source files |
| Wheel and sdist | Built under `/tmp/opdisc-review-build-Ax76My`; setuptools emitted license-metadata deprecation warnings |
| Configuration | 272 sources, 0 errors |
| Publication audit and diff whitespace | Passed; 160 publication-candidate files, 0 errors, 0 warnings |
| Isolated live `validate-sources` | 241 validated, 6 valid-empty, 1 failed, 24 quarantined |

Live source validation used only the isolated `/data/opdisc-sept29-review`
state. Its single failure remains the Amplitude HTTP 404. The installed Windows
workspace was not changed. Native Windows and Windows CI remain unverified; a
pushed PR needs all CI jobs, including Windows, checked before it is called
ready to merge.

## First-pass packet correction (2026-09-29 UTC)

Base: `f0a01f22a50f00b55c9f27055361613bf5c525c8`, matching
`origin/main` by `git ls-remote`. The mounted checkout began clean on branch
`simplify-documentation`; its Git metadata is read-only. Changes remain
uncommitted in `/workspace`.

The user's read-only analysis of the installed September 28 export found
22,130 candidates and 7,155 queue entries. They verified that a reconstruction
of the old score-first order matched the installed packet's first 40 IDs. Their
simulation of the proposed evidence-first order was **not** an execution of
this Linux diff:

| Top-40 measure | Old score-first | Simulated evidence-first |
| --- | ---: | ---: |
| Official-source observations | 13 | 40 |
| Excerpts present | 8 | 40 |
| `included` routes | 33 | 1 |
| Internships | 32 | 1 |
| Anduril | 4 | 29 |

Only eight leads overlapped. No queue entry had a stated deadline or known
application state, so deadline ordering added no value in that export. The
revised Markdown selector now takes up to 32 `included` leads by generic score
and reserves eight places for `research_needed`; unused places are filled from
the remaining queue. Stable ID breaks score ties. Registered official-source
observations, excerpts, and stated deadlines are displayed as evidence cues.
The 40-item and character budgets remain.
The exact revised top 40 IDs, source mix, and missing-evidence counts have not
been measured because the installed export is not mounted in this Linux
workspace. Given the user's confirmed old order of 33 `included` and seven
`research_needed` leads, the revised selector would retain 39 of those 40 IDs
on the same stored queue: it exchanges the lowest-ranked included lead for the
next research lead. This assumes the default character budget fits all 40 and
no collection updates the stored scores or routes. The revised selection would
have 32 included leads, 31–33 internships, 3–5 Anduril leads, 12–14 official
observations, and 7–9 excerpts. These are derived bounds, not measured counts.
The published JSON queue and candidate exports are unchanged by packet
selection.

The packet's official-source label now uses `provenance` joined to the source
registry, not `official_url`; an aggregator-supplied official-looking link alone
cannot earn that label. It calls current status unverified and labels application
status and deadlines as source-stated. A PhD-titled internship with no explicit
degree requirement routes to `research_needed`, not an invented exclusion;
"Director" is recognized as an experienced-stage title. Existing stored routes
update only after a successful re-observation, not an export-only refresh.

The Simplify GitHub list uses `↳` for the preceding company. A read-only live
payload saved under `/data/simplify-readme-sample.md` contained 770 such cells;
the corrected adapter parsed 2,020 records with zero `↳` organizations. A
successful future re-observation repairs a stored `↳` organization and records
a material change. The installed SQLite and private workspace were not edited.

| Gate | Result |
| --- | --- |
| Focused adapter, pipeline, export, and routing tests | 73 passed |
| Full non-live Linux suite | 274 passed; 4 native PowerShell tests skipped |
| Ruff lint and format | Passed |
| Mypy | Passed, 42 source files |
| Build | Wheel and sdist built under `/data/opdisc-sept29-review/build` |
| Configuration | 272 sources, 248 enabled, 0 errors |
| Publication audit and diff whitespace | Passed; 156 publication-candidate files, 0 errors, 0 warnings |
| Live `validate-sources` in isolated `/data/opdisc-sept29-review` | 241 validated, 6 valid-empty, 1 failed (Amplitude HTTP 404), 24 quarantined; Simplify validated with 2,020 records |

Live validation read the repository registry and wrote only under `/data`.
Native Windows and Windows CI remain unverified; a pushed PR needs all CI jobs,
including Windows, checked before it is called ready to merge.

## Bounded large-board collection and review coverage (2026-09-28 UTC)

Starting checkout: branch `decompression-fixes`, HEAD
`9d68afcb0259cc9830007fc1a85e34305d86219d`, with the earlier
double-decompression correction uncommitted. The global response limit remains
5 MB. Greenhouse documents no list pagination; its compact list omits the
descriptions and offices used by this adapter. Eight explicitly configured
boards therefore retain their complete `content=true` responses behind
measured, bounded per-board limits (8–50 MB). The adapter checks the returned
count against `meta.total` and rejects missing/duplicate IDs. Lever now uses
documented `skip`/`limit` pages of 100, with a 25-page cap. Any failed page,
duplicate ID, or page-cap hit fails the whole source check. The review packet
reports coverage only from the collection summary passed for the same run;
export-only refreshes say that collection health is unavailable.

| Source | Limit | Live validation |
| --- | ---: | --- |
| Accenture Federal Services (Greenhouse) | 16 MB | validated, 674 records |
| Agoda (Greenhouse) | 8 MB | validated, 291 records |
| Alo Yoga (Greenhouse) | 40 MB | validated, 941 records |
| Anduril (Greenhouse) | 50 MB | validated, 2,375 records |
| Anthropic (Greenhouse) | 12 MB | validated, 627 records |
| Cloudflare (Greenhouse) | 10 MB | validated, 399 records |
| Datadog (Greenhouse) | 8 MB | validated, 439 records |
| SpaceX (Greenhouse) | 40 MB | validated, 2,596 records |
| Palantir (Lever) | 5 MB per page | validated, 321 records |

The table reports a final focused re-probe of the nine sources (plus Amplitude)
against the finished code. Live record counts changed slightly between probes.
Validation used `/data/opdisc-nine-validation-20260928` for its database,
config, logs, and results; it read the registry from the checkout.
The full `opdisc --json validate-sources --concurrency 2` pass returned 192
validated, 1 valid-empty, 55 failed, and 24 quarantined. The nine sources above
all validated in that pass. Of the 55 failures, 54 were transient local DNS
resolution failures across Greenhouse, Ashby, and Lever hosts. A focused retry
of those exact 54 sources returned 49 validated and 5 valid-empty, with no
remaining DNS failure. These are two checks, not one coherent full-source
snapshot. The final focused re-probe returned nine validated and Amplitude
failed. Greenhouse Amplitude remains HTTP 404; its registry entry was neither
changed nor disabled because a replacement has not been verified.

| Gate | Command | Result |
| --- | --- | --- |
| Focused adapter, fetch, export, registry, pipeline, and exit tests | `/data/venv/bin/python -m pytest -q tests/test_adapters.py tests/test_http_client.py tests/test_export.py tests/test_exit_contract.py tests/test_pipeline.py tests/test_registry.py` | Passed |
| Full non-live suite | `PYTHONPATH=src /data/venv/bin/python -m pytest -o addopts='' -q -m 'not live' -ra` | 266 passed; four native PowerShell tests skipped on Linux |
| Ruff | `/data/venv/bin/ruff format --check src tests scripts/demo_workspace.py` and `/data/venv/bin/ruff check src tests scripts/demo_workspace.py` | Passed |
| Mypy | `/data/venv/bin/mypy` | Passed, 43 source files |
| Build | `uv build --out-dir /data/opdisc-nine-validation-20260928/build-final --quiet` | Wheel and sdist built; wheel contains both changed adapters |
| Configuration | `PYTHONPATH=src /data/venv/bin/python -m opportunity_discovery --json validate-config` | 272 sources, 248 enabled, 0 errors |
| Publication audit | `PYTHONPATH=src /data/venv/bin/python -m opportunity_discovery audit .` | Passed, 155 publication-candidate files, 0 errors, 0 warnings |
| Diff whitespace | `git diff --check` | Passed |

The live probe was validation only. It did not run collection, regenerate
installed exports, or write to the Windows private workspace. Native Windows
and PowerShell behavior remain unverified here.

## HTTP response decoding correction (2026-09-28 UTC)

The collector now removes `Content-Encoding` and the stale `Content-Length`
when it rebuilds a response from bytes already decoded by `httpx.iter_bytes()`.
Malformed compressed responses enter the normal failed-fetch/cache-fallback path.
Synthetic regressions cover a gzip JSON response, the decoded-body size limit,
and preservation of cached content after a decoding failure.

| Gate | Command | Result |
| --- | --- | --- |
| Focused HTTP tests | `/data/venv/bin/python -m pytest -q tests/test_http_client.py` | Passed, 18 tests; the new gzip regression reproduced the prior double-decode error before the fix |
| Full non-live suite | `/data/venv/bin/python -m pytest -q -m 'not live'` | Passed; four native PowerShell tests skipped on Linux |
| Ruff lint and format | `/data/venv/bin/ruff check src tests` and `/data/venv/bin/ruff format --check src tests` | Passed |
| Mypy | `/data/venv/bin/mypy` | Passed, 43 source files |
| Configuration | `PYTHONPATH=src /data/venv/bin/python -m opportunity_discovery --config /data/opdisc-http-validation-20260928/config/default.toml --json validate-config` | 272 sources, 248 enabled, 0 errors |
| Publication audit | `PYTHONPATH=src /data/venv/bin/python -m opportunity_discovery audit .` | 153 publication-candidate files, 0 errors, 0 warnings |
| Live source validation | `PYTHONPATH=src /data/venv/bin/python -m opportunity_discovery --config /data/opdisc-http-validation-20260928/config/default.toml --json validate-sources` | 232 validated, 6 valid-empty, 10 failed, 24 quarantined |
| Diff whitespace | `git diff --check` | Passed |

Live validation used an isolated database and output paths under
`/data/opdisc-http-validation-20260928`; its source registry was read from the
checkout without modification. None of the 10 failed probes reported a
decompression error. Nine Greenhouse/Lever feeds exceeded the configured
`max_response_bytes=5000000` limit, and one Greenhouse feed returned HTTP 404.
Those failures still limit source coverage; this validation did not rerun full
collection or regenerate the installed workspace's exports. Native Windows and
PowerShell remain unverified in this Linux environment.

## Corrected Phase 4–5 private workspace state and recovery (2026-09-12 UTC)

Environment: Linux, CPython 3.12.14, clean external integration checkout from
fetched `origin/main` `2b341d644280219756604818ef9aba6dad2c9f8a` using the
existing repository environment with `PYTHONPATH=src`. Requested scope was the
provider-neutral external private reviewer/adaptive knowledge layer and
recovery/backup/audit corrections. No live AI provider was added or invoked.

| Gate | Command | Actual result |
| --- | --- | --- |
| Focused correction suite | `PYTHONPATH=src .venv/bin/python -m pytest -o addopts='' -q tests/test_workspace_state.py tests/test_workspace_recovery.py tests/test_schemas.py` | 59 passed |
| Deterministic suite | `PYTHONPATH=src .venv/bin/python -m pytest -o addopts='' -q -m 'not live'` | 231 passed, 4 skipped |
| Ruff format | `.venv/bin/ruff format --check src tests` | 66 files already formatted after formatting 5 changed files |
| Ruff lint | `.venv/bin/ruff check src tests` | All checks passed |
| Mypy | `.venv/bin/mypy` | Success; no issues in 39 source files |
| Config/registry | `.venv/bin/opdisc --json validate-config` | OK; 272 sources, 248 enabled |
| Publication audit | `.venv/bin/python -m opportunity_discovery.audit .` | 133 publication-candidate files, 0 errors, 0 warnings |
| Diff whitespace | `git diff --check` | Passed |
| Package build | `.venv/bin/python -m build` | sdist and wheel built; existing setuptools license deprecation warnings only |
| Review patch | `git apply --check phases-4-and-5.patch` in a fresh clone at the fetched base | Passed against `2b341d644280219756604818ef9aba6dad2c9f8a` |

The focused regressions cover knowledge and source symlink containment, review
timestamp/input replay ordering, mutation preflight, proposal and nested custom
preservation, feedback schema/runtime parity, restore and backup failure
checkpoints and reruns, and Windows-unsafe archive names. The first formatter
check found five changed files and `ruff format` corrected them; the final gate
above is the post-format result.

The following live-source observations are retained from the earlier Phase 4–5
implementation validation and were not rerun as part of this deterministic
correction. The first `validate-sources` attempt used the existing ignored repository
database and stopped before probes: that database's historical migration
ledger numbers no longer match the current migration filenames, and migration
0005 attempted to add its already-present `engagement_type` column. The
database was preserved unchanged.

The required live check was then run against isolated temporary config and
storage at `/tmp/opdisc-phase45-validation.8PM9NS`:

```text
.venv/bin/opdisc --config <isolated>/config/default.toml --json validate-sources
```

The command completed with 34 `validated`, 4 `validated-empty-ok`, 210
`failed`, and 24 `quarantined`. Most failures were `httpx.DecodingError` with
`Error -3 while decompressing data: incorrect header check` on HTTP 200
responses across unrelated hosts. This is an unexpected live-environment or
HTTP decoding failure, not a passing source-health result; no registry entries
or source rules were rewritten in response. The Phase 4–5 deterministic paths
do not perform HTTP requests.

Native Windows and PowerShell were unavailable. CI still defines Windows
Python 3.11–3.14 deterministic jobs, but the new commands have not yet been run
on a native Windows host.

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

## Phase 6 prerequisite feedback integrity correction (2026-09-27 UTC)

The Phase 4/5 production CLI was exercised in three isolated synthetic
workspaces under `/data/phase6-review/`. An older feedback replay after a newer
Delete silently restored Done and moved the board timestamp backward. The
feedback importer now rejects stale or conflicting decisions before mutation,
and keeps board and preference timestamps monotonic. The existing demo has a
later synthetic feedback file for this regression. Per the Phase 6 instruction,
no dashboard backend was layered onto the faulty contract.

| Gate | Command | Result |
| --- | --- | --- |
| Focused review/recovery tests | `/data/venv/bin/python -m pytest -q tests/test_workspace_state.py tests/test_workspace_recovery.py` | Passed before the final global-timestamp regression was added; that regression passed in the full suite |
| Full deterministic suite | `/data/venv/bin/python -m pytest -q -m 'not live'` | Passed; four Windows-only tests skipped |
| Formatter | `/data/venv/bin/ruff format --check src tests` | 66 files already formatted |
| Linter | `/data/venv/bin/ruff check src tests` | All checks passed |
| Type checker | `/data/venv/bin/mypy` | No issues in 39 source files |
| Publication audit | `/data/venv/bin/opdisc audit .` | 134 publication-candidate files; 0 errors, 0 warnings |
| Diff whitespace | `git diff --check` | Passed |
| Production CLI replay | `opdisc workspace-apply-feedback` in rehearsal 2, after newer Delete | Stale replay rejected with exit 2; newer Delete retained |

Rehearsals also covered review, feedback, state/full backup, knowledge snapshot
listing/comparison/restore, full restore, and workspace audit. A full restore
recovered deliberately changed synthetic source and knowledge files. No live
collection, live source validation, AI provider, or personal data was used.
`validate-sources` was not run because the requested rehearsal and validation
scope was offline and source adapters were unchanged.

## Phase 6 dashboard-ready backend (2026-09-27 UTC)

After the prerequisite fix was reviewed, the user authorized Phase 6 to resume
on the same uncommitted checkout. The backend now reads a versioned private
board page, applies explicit user commands, and reads private history. The
collector and public export contracts were not changed. The Phase 6 synthetic
scenario extends the existing review/feedback demo; no visual dashboard or
AI-provider integration was added.

| Gate | Command | Result |
| --- | --- | --- |
| Focused board/state/recovery tests | `/data/venv/bin/python -m pytest -q tests/test_workspace_board.py tests/test_workspace_state.py tests/test_workspace_recovery.py` | Passed |
| Full deterministic suite | `/data/venv/bin/python -m pytest -q -m 'not live'` | Passed; four Windows-only tests skipped |
| Formatter | `/data/venv/bin/ruff format --check src tests` | 69 files already formatted |
| Linter | `/data/venv/bin/ruff check src tests` | All checks passed |
| Type checker | `/data/venv/bin/mypy` | No issues in 41 source files |
| Publication audit | `/data/venv/bin/opdisc audit .` | 140 publication-candidate files; 0 errors, 0 warnings |
| Configuration | `/data/venv/bin/opdisc --json validate-config` | 272 sources, 248 enabled, 0 errors |
| Diff whitespace | `git diff --check` | Passed |
| Production CLI rehearsal | `/data/venv/bin/python /data/phase6-review/rehearse_phase6.py` | 19 CLI calls passed in a fourth isolated synthetic workspace, including board lanes, actions, history, purge, state backup, and workspace audit |

The same 19-call rehearsal passed again in a fresh fifth synthetic workspace
after the final monotonic timestamp and history-read changes. A regression test
also applied a newer research response after a user action and verified that
the board and record update times, and user status, stayed intact.

No live collection, live source probe, AI provider, or personal applicant data
was used. Source adapters and scoring were unchanged, so `validate-sources`
was not applicable to this offline private-workspace increment. Native Windows
execution remains a platform check outside this Linux run.

## Phase 6 review corrections (2026-09-27 UTC)

Feedback preflight now compares incoming feedback against the latest direct
Done/Delete action and restore time as well as prior feedback. A synthetic
regression applies reasoned Done at 09:00, direct Delete at 10:00, and imported
feedback at 09:30; the import is rejected before the board, preferences, or
checkpoint changes. Done now goes to History even when the factual pipeline
state is submitted or an explicit waiting flag is active. Restore exposes the
underlying waiting state again.

| Gate | Command | Result |
| --- | --- | --- |
| Focused board/state/recovery tests | `/data/venv/bin/python -m pytest -q tests/test_workspace_board.py tests/test_workspace_state.py tests/test_workspace_recovery.py` | Passed, 48 tests |
| Full deterministic suite | `/data/venv/bin/python -m pytest -q -m 'not live'` | Passed; four Windows-only tests skipped |
| Formatter and linter | `/data/venv/bin/ruff format --check src tests` and `/data/venv/bin/ruff check src tests` | Passed, 69 files formatted |
| Type checker | `/data/venv/bin/mypy` | Passed, 41 source files |
| Publication audit | `/data/venv/bin/opdisc audit .` | 140 files, 0 errors, 0 warnings |
| Configuration | `/data/venv/bin/opdisc --json validate-config` | 272 sources, 248 enabled, 0 errors |
| Production CLI rehearsal | `/data/venv/bin/python /data/phase6-review/rehearse_phase6.py rehearsal-6` | 20 calls passed in a fresh synthetic workspace, including Done in History |

Native Windows execution and the four Windows-only tests still require CI or a
Windows checkout. No live source probe was run; source adapters and scoring did
not change.

## Phases 7 and 8 private dashboard and application handoff (2026-09-28 UTC)

Starting base was `339ad000d09976ead966b38c390c1c5d2dcd4fdd` (`origin/main`, PR #11 merged). The mounted `/workspace` Git directory was read-only, so implementation and validation ran in `/data/opportunity-discovery-phase7-8`. The mounted checkout stayed unchanged. Phase 7 was targeted-tested and checkpointed before Phase 8 began; the separate review packages are under `/data/opdisc-review/phase7` and `/data/opdisc-review/phase8`.

| Gate | Command | Result |
| --- | --- | --- |
| Phase 7 targeted | `PYTHONPATH=src /data/venv/bin/python -m pytest -q tests/test_workspace_dashboard.py tests/test_workspace_board.py tests/test_workspace_state.py` | Passed, 33 tests |
| Phase 8 targeted | `PYTHONPATH=src /data/venv/bin/python -m pytest -q tests/test_workspace_application.py tests/test_workspace_dashboard.py tests/test_demo_workspace.py` | Passed, 6 tests |
| Full non-live suite | `PYTHONPATH=src /data/venv/bin/python -m pytest -q -m 'not live' -ra` | Passed; 4 native PowerShell tests skipped on Linux |
| Ruff | `/data/venv/bin/ruff check src tests scripts/demo_workspace.py` and `/data/venv/bin/ruff format --check src tests scripts/demo_workspace.py` | Passed, 76 Python files formatted |
| Mypy | `/data/venv/bin/mypy` | Passed, 43 source files |
| Build | `uv build --out-dir /data/opdisc-review/build-final --quiet` | Wheel and sdist built; wheel includes dashboard CSS and both new modules |
| Configuration | `PYTHONPATH=src /data/venv/bin/python -m opportunity_discovery --json validate-config` | 272 sources, 248 enabled, 0 errors |
| Publication audit | `PYTHONPATH=src /data/venv/bin/python -m opportunity_discovery audit .` | 153 publication-candidate files; 0 errors, 0 warnings before this documentation addition |
| Diff integrity | `git diff --check` | Passed before this documentation addition |
| Synthetic demo | `PYTHONPATH=src /data/venv/bin/python scripts/demo_workspace.py /data/opdisc-review/synthetic-demo` | Created 1 active, 1 waiting, 2 dismissed, 1 history record and a fake request/response |

The end-to-end synthetic test additionally rendered all four HTTP lanes, changed pipeline state through the dashboard, created another manual application request, and checked the resulting files. The review importer processed fake structured decisions; no live AI call or real applicant data was used. No browser executable or native Windows host was available, so rendered visual inspection and native PowerShell validation remain unverified. CI defines Windows jobs for Python 3.11–3.14, but no new PR or CI run was started. `validate-sources` was not run because these changes do not alter source adapters, scoring, registry, or public collection behavior; the requested final verification was non-live.

## Full-description extraction and private screening (2026-10-04 UTC)

Implementation and validation ran on native Windows in the existing checkout,
starting from `07eacde01a82d0498ec5b8b4aa3282d965b6a4c8` on
`workspace-backups`. Changes remain local, uncommitted, and unpushed.

The existing ignored `.venv` launcher referenced a missing Python installation.
Validation used an isolated ignored `data/validation/venv` with Python 3.12.14
and the declared development dependencies. It did not replace the existing
environment. Commands below use executables from that validation environment.

| Gate | Command / evidence | Result |
| --- | --- | --- |
| Full native Windows suite | `python -m pytest -m 'not live' -o addopts='' -q -ra --basetemp <fresh-temp-dir> -o cache_dir=data/validation/pytest-cache` | 334 passed, 8 skipped in 54.68 seconds |
| Lint | `ruff check src tests scripts/demo_workspace.py` | Passed |
| Formatting | `ruff format --check src tests scripts/demo_workspace.py` | Passed, 82 files |
| Types | `mypy src/opportunity_discovery --cache-dir data/validation/mypy-cache` | Passed, 45 source files |
| Configuration | `opdisc validate-config` | Passed, 272 registered sources |
| Live source validation | `opdisc --config data/validation/live/config.toml --json validate-sources` | 241 validated with records, 5 validated empty, 2 failed, 24 quarantined |
| Publication audit | `opdisc --json audit .` | No findings before this documentation addition |
| Diff integrity | `git diff --check` | Passed before this documentation addition |
| Browser inspection | Synthetic external workspace, loopback dashboard, Explore | Existing navigation preserved; personal screening, official research, and unresolved questions displayed separately |

The eight skipped tests require symlink creation, which this Windows account
cannot perform. Windows PowerShell tests ran. No PR, remote CI run, commit,
push, or publication occurred; other Python versions remain unverified in this
cycle. Browser inspection used only fictional data; its temporary server was
stopped afterward.

Synthetic fixtures exercise nested escaped HTML, separate Lever lists,
requirements beyond a shortened display excerpt, requirement headings ahead of
company introductions, preferred experience, degree statements beyond the
requirements bound, explicit and ambiguous deadlines, exported facts, and
stable IDs after a qualification change. Private tests cover whole-collection
screening, region/context matching, unknown credentials, recoverable exclusions,
category balance and employer caps, carried-forward findings, profile/source
invalidation, official-check freshness, new/changed backlog priority,
evidence-quoted semantic imports, rejected stale/corrupt inputs, and board-decision
preservation. Profile, persisted state, and semantic-response schemas are checked
using fictional examples.

Live probes used a separate database, output directory, and cache below
`data/validation/live`. Amplitude's Greenhouse endpoint and Amigo's Ashby
endpoint returned HTTP 404. Those failures were recorded as failures, not empty
boards or closures; source registrations were not changed.

The current production collection was not recollected or backfilled. Richer
extracted fields arrive on subsequent successful fetches. Source coverage was
not expanded in this update. Workday remains limited to listing content;
SmartRecruiters only extracts detailed sections when the payload supplies them.
No per-job detail crawling, embedded model provider, or live AI research was
added. External private screening settings and cached findings are outside the
checkout and do not update collector data or official review decisions.

## Configurable private opportunity focus (2026-10-04)

The private profile now supports `early-opportunities`, `standard-internships`,
and `new-grad`, plus null for no preference. Onboarding asks for this choice.
Preferred leads precede secondary leads, with category balancing within each
tier. Early mode broadly prefers exploratory programs and dedicated first-two-year
roles, preserving unresolved requirements and recognized mismatches. Preferred
early programs are exempt from the employer cap and do not consume job slots.
New-grad mode prioritizes entry-level full-time job cues; broader programs and
contract roles remain secondary. Screening version 2 invalidates older cached
findings without changing candidate identity or application decisions.

Validation used the same native Windows checkout and ignored environment above.
All changes remain local, uncommitted, and unpushed.

| Gate | Evidence | Result |
| --- | --- | --- |
| Full native Windows suite | `python -m pytest -m 'not live' -o addopts='' -q -ra --basetemp <fresh-temp-dir> -o cache_dir=data/validation/pytest-cache` | 354 passed, 8 skipped in 65.24 seconds |
| Lint and formatting | Ruff, same commands as above | Passed; 82 files formatted |
| Types | Mypy, same command as above | Passed; 45 source files |
| Configuration | `opdisc --json validate-config` | 272 sources, 248 enabled, 0 errors |
| Live source validation | Separate ignored validation config and data paths | 241 with records, 5 valid empty, 2 HTTP 404 failures, 24 quarantined |
| Publication audit | `opdisc --json audit .` | 169 files scanned, 0 findings before this documentation addition |

The same eight symlink-dependent tests remain skipped for Windows privilege
limitations. PowerShell tests ran. Synthetic fixtures cover all three stage
preferences, unknown employment type, all-year versus dedicated early-year
internships, ordinary discovery/insights job titles, unresolved GPA/subject fit,
program cap exceptions, explicit mismatches, and invalidation after a preference
change. Public candidate bytes and stable IDs remain unchanged by private
screening. Existing dashboard navigation is preserved. No model calls or new
sources were added. The two live failures remain Amplitude and Amigo; no source
registrations or production collection data were changed.

## Collection refresh and configurable travel screening (2026-10-04)

A subsequent authorized production refresh completed as
`run-20261004T204511582690Z`: 248 sources attempted, 246 successful, and the
same two HTTP 404 failures. All 21,955 previous candidate identities survived;
85 new identities brought the collection to 22,040. No records were closed.
Source failures preserved previous successful state. The registry was unchanged.

Full collection requirements text is populated for 18,672 records. The generic
queue decreased from 6,976 to 6,234; unknown opportunity types decreased from
4,662 to 3,061, with requirements captured for 4,396 queue records. Graduation
language is populated for 442 queue records, but only 215 contain a year:
this is not evidence that every field contains an actionable graduation window.
Two queue records have explicit deadlines. Workday and generic HTML lists still
have substantial extraction gaps. Populated fields do not establish correctness
or personal eligibility.

The audit exposed false academic-year cues from employee benefits and graduate
school, experienced labels on internship titles, and substring inference from
Internal/International titles. Regression fixes now constrain academic cues,
separate dedicated early-year opportunities from sophomore-or-higher minimums,
and use word boundaries for internship inference in Greenhouse, Lever, Workday,
and pipeline normalization. Structured source labels remain authoritative;
conflicting older labels become private screening questions. These later public
classification corrections have not been backfilled into the production DB.

Private profiles support configurable location policies, with onboarding asking
whether regions are preferences or limits and whether funded short programs
elsewhere are acceptable. The travel exception requires a credible program,
explicit duration of at most 14 days, and source-backed travel coverage;
housing alone, conditional funding, and ordinary internship relocation do not
qualify. Explicit state/country mismatches are recoverable exclusions. Missing
city aliases, funding, duration, and personal credentials remain questions.
Multiple offices cannot borrow geographic context from each other. Version 6
invalidates earlier cached screening rules while preserving custom fields,
identities, and application decisions. Applicant settings and outcomes remain
outside this repository.

| Gate | Result |
| --- | --- |
| Final native Windows suite | 391 passed, 8 skipped in 70.34 seconds |
| Ruff lint and formatting | Passed; 81 files formatted |
| Mypy | Passed; 45 source files |
| Configuration validation | 272 sources, 248 enabled, 0 errors |
| Final isolated live source validation | 241 with records, 5 valid empty, 2 HTTP 404 failures, 24 quarantined |

The eight skips require Windows symlink privileges. Live validation uses separate
ignored data, output, and cache paths. Synthetic tests cover funded short
programs, event dates, unknown/conditional/contradictory travel funding,
internship relocation, older program labels, explicit foreign locations,
ambiguous same-state cities, and multi-office context. There are no embedded
model calls, additional sources, or changes to dashboard sections. Changes
remain local, uncommitted, and unpushed.

## Local publication-readiness check (2026-10-04)

Rechecked the current extraction, private screening, and source-research diff on
native Windows. This is an implementation/readiness check, not evidence that the
proposed program sources have been enabled. Registry coverage remains unchanged.

| Gate | Evidence | Result |
| --- | --- | --- |
| Full non-live suite | Validation Python; fresh OS temporary directory outside Git; existing ignored pytest cache | 391 passed, 8 skipped in 57.27 seconds |
| Ruff lint/format | `ruff check src tests scripts/demo_workspace.py`; `ruff format --check src tests scripts/demo_workspace.py` | Passed; 82 files formatted |
| Types | `mypy src/opportunity_discovery --cache-dir data/validation/mypy-cache` | Passed; 45 source files |
| Configuration | `opdisc --json validate-config` | 272 sources, 248 enabled, 0 errors |
| Publication audit | `opdisc --json audit .` | 171 files, 0 findings |
| Diff integrity | `git diff --check` | Passed |
| Packaging | Offline `uv build` using the ignored validation cache/environment, output under `data/validation/push-readiness-build` | Wheel and sdist built; wheel includes extraction/screening modules and dashboard CSS; both archives exclude runtime data/caches |

The eight skips require Windows symlink privileges. Synthetic private-workspace
tests require temporary paths outside any Git checkout; locating their test
workspaces inside this repository triggers the intended privacy guards.
Packaging retains the existing setuptools license-metadata deprecation warnings.
The latest saved isolated live validation was inspected, not rerun: 241 sources
with records, 5 valid empty, 2 existing HTTP 404 failures, 24 quarantined.
No new GitHub CI run was started, so its Linux/Windows Python-version matrix
remains unverified for this diff. No staging, commit, push or publication occurred.
