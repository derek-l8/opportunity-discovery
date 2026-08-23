# Adapters

Adapters turn one fetched public payload into `RawOpportunity` records. They
are registered in `src/opportunity_discovery/adapters/` and selected by the
`adapter` field of a registry entry.

## Contract

Every adapter must:

1. **Distinguish valid empty from failure.** A 200 with zero records is
   `valid-empty`; an unparseable body is `format-changed`; transport failure is
   `check-failed` / `rate-limited`. Never report a failed check as "0
   opportunities".
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
| `greenhouse` | `boards-api.greenhouse.io/v1/boards/{org}/jobs?content=true` | Bogus boards 404 → identity confirmable |
| `lever` | `api.lever.co/v0/postings/{org}?mode=json` | |
| `ashby` | `api.ashbyhq.com/posting-api/job-board/{org}` | |
| `smartrecruiters` | `api.smartrecruiters.com/v1/companies/{org}/postings` | Unknown company returns empty-200, so validation requires records>0 or documented identity |
| `workday` | `POST {tenant}.wdN.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs` | Only explicitly configured tenants/sites; no tenant discovery |
| `jsonfeed` | any public JSON array | Configurable `records_path` + per-field dot-path mapping |
| `csvfeed` | any public CSV | Configurable column names |
| `rss` | RSS/Atom via feedparser | |
| `githublist` | GitHub-hosted markdown tables/bullets/HTML tables | Used for community list READMEs |
| `htmllist` | explicit CSS selectors on one configured page | Selector must match ≥1 item else `format-changed` |
| `sitemap` | sitemap.xml with include/exclude regex | Titles inferred from slugs are flagged `inferred-signal`, bounded to 300 URLs |

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
