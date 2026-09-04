# Adding a source

## 1. Identify the endpoint

- Official ATS board: check the org's careers page for greenhouse.io /
  lever.co / ashbyhq.com / smartrecruiters.com / myworkdayjobs.com links.
  Use `opportunity_discovery.urlnorm.detect_ats` to extract provider + org
  from an application URL.
- Community lists: raw.githubusercontent URLs (CSV/JSON/Markdown).
- Program pages: use `program-page` only with exact official overview and/or
  application URLs for each configured cycle/session. Do not guess or crawl
  route patterns.

Never invent slugs, tenant names, or selectors — derive them from public
pages or aggregate feeds and validate live.

For a recurring program source, configure a bounded set of explicit records:

```toml
[[sources]]
source_id = "program-example-circuits"
display_name = "Example Circuits Sessions"
organization = "Example Organization"
adapter = "program-page"
official_source = true
enabled = false # enable only after a passing live validation
validation_status = "pending"

[sources.endpoint_config]
overview_url = "https://example.org/programs/circuits"
max_pages = 2

[sources.endpoint_config.selectors]
title = "h1"
application_state = ".status"
location_text = ".location"

[[sources.endpoint_config.state_rules]]
state = "application-open"
pattern = "(?i)applications open"

[sources.endpoint_config.coverage]
min_results = 1
max_results = 1
expected_url_patterns = ["/apply/circuits-harbor-2027$"]

[[sources.endpoint_config.programs]]
application_url = "https://example.org/apply/circuits-harbor-2027"
program_family_id = "circuits"
cycle_id = "harbor-2027"
```

The example is generic configuration, not organization-specific parsing.
JSON-LD extraction is available through `jsonld_type` plus `jsonld_fields`
dot paths. See `docs/ADAPTERS.md` and the neutral fixtures in
`tests/fixtures/adapters/` for complete deterministic examples.

## 2. Validate before enabling

```bash
# append the entry (or hand-edit config/sources.toml)
.venv/bin/opdisc add-source greenhouse-newco \
    --organization "NewCo" --adapter greenhouse \
    --endpoint-json '{"board": "newco"}' --category internship

# probe it live; this records status in the DB
.venv/bin/opdisc validate-sources --source-id greenhouse-newco
```

Only set `validation_status = "validated"` with a `last_validated` date after
a passing probe. Otherwise leave `enabled = false` with a `quarantine_reason`.

## 3. Confirm behavior expectations

- A source that currently has zero postings must still pass as
  `valid-empty` (verify the provider distinguishes missing boards).
- If the provider cannot distinguish (e.g. SmartRecruiters), require a
  non-empty probe at validation time and say so in `provenance_note`.
- A program-page source must pass its configured result-count and expected
  URL/title canaries. Treat `coverage-warning` or `format-changed` as a failed
  validation; do not weaken the canary merely to make a probe pass.

## 4. Test

If you added/changed an adapter (not just a registry entry), follow
`docs/ADAPTERS.md`: fixtures + tests for success, valid-empty, malformed,
format drift.

## 5. Commit rules

Commit the registry entry only. Never commit fetched payloads or the SQLite
database. Run `.venv/bin/opdisc audit` before publishing.
