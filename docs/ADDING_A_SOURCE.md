# Adding a source

## 1. Identify the endpoint

- Official ATS board: check the org's careers page for greenhouse.io /
  lever.co / ashbyhq.com / smartrecruiters.com / myworkdayjobs.com links.
  Use `opportunity_discovery.urlnorm.detect_ats` to extract provider + org
  from an application URL.
- Community lists: raw.githubusercontent URLs (CSV/JSON/Markdown).
- Program pages: only if a stable CSS selector lists items.

Never invent slugs, tenant names, or selectors — derive them from public
pages or aggregate feeds and validate live.

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

## 4. Test

If you added/changed an adapter (not just a registry entry), follow
`docs/ADAPTERS.md`: fixtures + tests for success, valid-empty, malformed,
format drift.

## 5. Commit rules

Commit the registry entry only. Never commit fetched payloads or the SQLite
database. Run `.venv/bin/opdisc audit` before publishing.
