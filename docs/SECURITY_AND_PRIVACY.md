# Security & privacy

## Posture

- **Local-only**: SQLite + files under `data/`, `output/`, `logs/`.
- **No credentials**: no API keys, no logins, nothing authenticated. If a
  source requires an Authorization-Key (e.g. USAJOBS), it is out of scope.
- **No AI/model dependencies** and no telemetry.
- **No submissions**: the engine never applies, messages, uploads, or saves
  anything to any service.

## What is never stored

Personal data of any kind: applicant profiles, eligibility decisions,
resumes/transcripts/essays, application history or outcomes, demographic
data. The engine stores only what public sources state about opportunities.

## Git hygiene

Committed content is limited to code, config templates, the public registry,
schemas, fixtures, docs, tests, and safe scripts. `.gitignore` excludes
`data/`, `output/`, `logs/`, databases/journals, caches, virtualenvs, `.env`,
keys. Generated live data must never be tracked.

## Publication audit

`opdisc audit` (or `.venv/bin/python -m opportunity_discovery.audit`) scans
tracked files for:

- common credential patterns (AWS/GitHub/Slack/Google/OpenAI keys, generic
  secret assignments, private-key blocks, connection strings);
- `.env` / key / certificate files;
- Windows user paths (`C:\Users\…`), WSL user mounts (`/mnt/c/Users/…`),
  absolute `/home/<user>/` paths;
- databases, logs, caches, live payloads in generated directories;
- obvious personal application data (resume/cv/transcript filenames,
  application-status language) as warnings.

It exits non-zero on errors. Run it before every push/publish.

### Limitations (documented honestly)

- Pattern-based: novel secret formats can slip through; high-entropy scanning
  is deliberately conservative to avoid false positives.
- Only scans textual files; binary payloads are caught by filename/suffix
  rules only.
- The entire `tests/` tree and `examples/` are allow-listed because they
  deliberately contain synthetic examples of every detection rule; if you put
  real credentials or personal data under `tests/` the audit will not flag
  them — never do that.
- It inspects the working tree/tracked files at scan time; it cannot vouch for
  history already pushed elsewhere.
