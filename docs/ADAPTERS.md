# Adapters

Employer description extraction happens before display truncation for
Greenhouse, Lever, Ashby, and description content available in SmartRecruiters
payloads. Nested HTML entities are decoded; Lever's separate lists participate
in extraction. Requirement excerpts are bounded to 2,400 characters, with
separate bounded fact fields. Required and preferred degree normalization sees
all available requirement text. The extraction is conservative pattern matching,
not a complete interpretation of every employer's prose.

Workday's listing response still supplies limited content. SmartRecruiters
listing payloads may omit detailed sections. These changes do not add per-job
detail requests, authenticated access, or an embedded AI dependency; absent
content stays unknown. Source registry coverage is unchanged by this extraction
and screening update.

Adapters turn one fetched public payload into `RawOpportunity` records. They
are registered in `src/opportunity_discovery/adapters/` and selected by the
`adapter` field of a registry entry.

## Contract

Every adapter must:

1. **Distinguish valid empty from failure.** A 200 with zero records is
   `valid-empty`; an unparseable body is `format-changed`; transport failure is
   `check-failed` / `rate-limited`; a coverage-canary mismatch is
   `coverage-warning`. Never report a failed check as "0 opportunities".
2. **Preserve prior success on failure.** The pipeline ignores results from
   failed checks; conditional requests (ETag/Last-Modified) and the raw cache
   allow `degraded` fallback.
3. **Bound their work** (page caps, item caps) — no unbounded crawling.
4. **Emit bounded excerpts only**, never full copyrighted page copies.
5. Have synthetic fixtures + tests covering success, valid-empty, malformed
   response, and format drift before being added.

## Implemented adapters

| Adapter | Public endpoint pattern | Notes |
| --- | --- | --- |
| `greenhouse` | `boards-api.greenhouse.io/v1/boards/{org}/jobs?content=true` | Complete board response; explicit per-board size caps for large boards; bogus boards 404 → identity confirmable |
| `lever` | `api.lever.co/v0/postings/{org}?mode=json&skip=N&limit=100` | Pages until a short/empty page; page and duplicate-ID checks |
| `ashby` | `api.ashbyhq.com/posting-api/job-board/{org}` | |
| `smartrecruiters` | `api.smartrecruiters.com/v1/companies/{org}/postings` | Unknown company returns empty-200, so validation requires records>0 or documented identity |
| `workday` | `POST {tenant}.wdN.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs` | Only explicitly configured tenants/sites; no tenant discovery |
| `jsonfeed` | any public JSON array | Configurable `records_path` + per-field dot-path mapping |
| `csvfeed` | any public CSV | Configurable column names |
| `rss` | RSS/Atom via feedparser | |
| `githublist` | GitHub-hosted markdown tables/bullets/HTML tables | Used for community list READMEs |
| `htmllist` | explicit CSS selectors on one configured page | Selector must match ≥1 item else `format-changed` |
| `program-page` | exact configured overview/application URLs | Up to 8 pages; one explicit record per cycle/session; CSS selectors or JSON-LD paths; coverage canaries |
| `sitemap` | sitemap.xml with include/exclude regex | Titles inferred from slugs are flagged `inferred-signal`, bounded to 300 URLs |

The [Greenhouse Job Board API](https://github.com/grnhse/greenhouse-api-docs/blob/master/source/includes/job-board/_jobs.md)
does not document list pagination. Its smaller list omits descriptions and
offices needed for routing and change detection. The eight measured large
boards therefore retain `content=true` with explicit registry limits of
8–50 MB; the default remains 5 MB. The decoded body must fit its configured
limit and the reported `meta.total` must match the returned job count. A board
that grows beyond its bound fails visibly and cannot close prior leads.

The [Lever Postings API](https://github.com/lever/postings-api/blob/master/README.md)
documents `skip` and `limit`. Its adapter fetches at most 25 pages of 100,
retaining the normal 5 MB limit per page. A failed page, repeated posting ID,
or full final page at the cap fails the source check; no partial page set is
ingested.

## Recurring program pages

`program-page` addresses sites where a general overview may offer only a
notification list while a separate official cycle/location application is
open. It is deliberately not a crawler: every overview and application URL is
configured exactly, redirects must stay within the set of configured hosts,
and a source may fetch at most eight unique pages.

Each `programs` entry represents one explicit cycle/session. Pair
`program_family_id` with `cycle_id` (or the `session_id` alias) to create a
stable strong identity such as `family:harbor-2027`; do not reuse the same pair
for another location or cycle. When those fields are absent, identity falls
back to the normalized exact official URL. Similar titles are never merged.

Fields may be static configuration, CSS selector text, or a configured dot
path in an `application/ld+json` object. Supported public-source fields are:
title, location, application deadline, exact event start/end dates,
requirements text, and application state (`application-open`,
`notification-only`, `closed`, or `unknown`). State rules are explicit regexes;
the presence of an application URL alone never implies that applications are
open.

Every source should configure `coverage.min_results` / `max_results` and
expected URL/title regexes. A mismatch is `coverage-warning`, even if every
request returned HTTP 200. Missing required parse structure is
`format-changed`. Both states preserve prior successful opportunity state and
are excluded from closure evidence.

## Adding an adapter

1. Implement in a new module under `adapters/`, decorate with
   `@register_adapter("name")`, import it in `adapters/__init__.py`.
2. Add fixtures under `tests/fixtures/adapters/`.
3. Add tests: parse success, valid-empty, malformed JSON/XML, format drift,
   and isolation (a crash yields `check-failed`, not empty-ok).
4. Document the endpoint pattern here and add registry entries via
   `docs/ADDING_A_SOURCE.md`.

## What we deliberately do not do

No universal crawler, no browser automation, no anti-bot evasion, no paid or
account-gated boards, no authenticated endpoints of any kind.
