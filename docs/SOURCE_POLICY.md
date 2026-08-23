# Source policy

## What may be a source

Public, unauthenticated, politely fetchable pages/feeds that plausibly contain
opportunities relevant to a technical undergraduate: ATS boards, public JSON/CSV
feeds, RSS, GitHub-hosted lists, explicitly configured HTML list pages,
program/conference pages with stable structure, bounded sitemaps.

Explicitly out of scope: paid boards, LinkedIn/Handshake/12twenty/Intern
Insider or any account-gated system, anything requiring credentials, anything
behind CAPTCHAs or technical access controls.

## Validation contract

A source counts as **enabled and validated** only when a live probe confirms:

- organization/program identity is correct;
- the configured adapter and identifier are correct;
- the endpoint responds in the expected format;
- the adapter can distinguish valid-empty from failure (where the provider
  cannot — e.g. SmartRecruiters returns empty-200 for unknown companies — a
  non-empty probe is required);
- the validation date and result are recorded in `last_validated` /
  `validation_status` / `provenance_note`.

Candidates that cannot be validated stay **disabled/quarantined** in
`config/sources.toml` with the attempted URL, reason, and date. They are never
counted as validated and never break runs.

## Health states

| State | Meaning |
| --- | --- |
| `healthy` | Last check succeeded with records |
| `valid-empty` | Last check succeeded; genuinely zero records |
| `degraded` | Fetch failed; served from raw cache within retention |
| `check-failed` | Network/parser failure; prior state preserved |
| `rate-limited` | HTTP 429/503 after retries |
| `format-changed` | Response no longer matches expected shape |
| `disabled` | Turned off in registry |
| `quarantined` | Failed validation; reason recorded |

A network failure is never reported as zero opportunities. Closure of an
opportunity requires consecutive *successful* checks missing it
(`closed_after_consecutive_successes`, default 3).

## Politeness defaults

Bounded concurrency (6), per-domain minimum interval (1.5 s), conditional
requests, retries only for transient failures with exponential backoff +
jitter, robots.txt respected on HTML/RSS/sitemap lanes, transparent
User-Agent (`opportunity-discovery/{version} …`). All configurable in
`config/default.toml`.

## Registry layout conventions

```toml
[[sources]]
source_id = "greenhouse-acmesilicon"     # adapter-org, unique
display_name = "Acme Silicon"
organization = "Acme Silicon"
adapter = "greenhouse"
landing_url = "https://boards.greenhouse.io/acmesilicon"
endpoint_config = { board = "acmesilicon" }
categories = ["internship", "early-career"]
tags = ["ats", "official-board"]
official_source = true                   # fetched from the org's own ATS/page
cadence_hours = 24
validation_status = "validated"
last_validated = "2026-08-23"
provenance_note = "discovered via public aggregate feed; live probe …"
```

Aggregators carry `official_source = false`; their records are lead
provenance only. The current registry ships ~250 enabled validated sources and
a set of quarantined entries kept deliberately as honest records of what could
not be validated.
