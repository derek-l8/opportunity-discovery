# opportunity-discovery

Collect public internship, research, program, and event leads. Search the full
review queue or ask an AI agent to investigate selected leads for your private
dashboard. Collection does not call an AI model or decide whether you qualify.

## Get started

Requires Python 3.11–3.14. On Linux or WSL, from the checkout:

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/opdisc init
.venv/bin/opdisc validate-config
.venv/bin/opdisc run
.venv/bin/opdisc source-health
```

On native Windows, run `.\scripts\install.ps1` in PowerShell, then
`.\scripts\run.ps1`. The installer asks where to keep your private workspace.
On Linux or WSL, create one separately:

```bash
.venv/bin/opdisc init-workspace /path/to/Opportunity-Workspace --engine-path .
```

See [Windows operations](docs/OPERATIONS_WINDOWS.md) for installation and
scheduling. A development install uses `pip install -e '.[dev]'`.

`opdisc run` writes these files under `output/`:

| File | Use |
| --- | --- |
| `source_health.json` | See which sources succeeded or failed. |
| `review_packet.md` | Up to 40 leads to start an AI or human review, not the complete queue or the dashboard Home. |
| `review_queue.jsonl` | Inspect every active lead in the selected career-profile review lane. |
| `candidates.jsonl` | Inspect every retained candidate, including those outside the queue. |
| `delta_packet.json` and `.pN.json` | Read all new or changed leads across bounded pages. |
| `export_manifest.json` | Check generation and artifact hashes before consuming exports. |

Check `source_health.json` before reviewing leads. The packet starts with up
to 32 leads in the active profile and reserves up to eight for further research.
It is only a starting sample; Explore can search the full current review queue.
To use AI review, give your chosen agent the packet, manifest, and
`schemas/workspace-review.schema.json`. Ask it to check selected leads on
official pages and write a response JSON file. The repository does not send
these files to an AI. Import the response, then open the dashboard, using the
workspace path you chose during setup:

```text
opdisc workspace-apply-review WORKSPACE RESPONSE.json --manifest output/export_manifest.json
opdisc workspace-dashboard WORKSPACE --manifest output/export_manifest.json
```

Dashboard **Home** shows imported review decisions that still call for
attention. Each card shows the reviewer's reasons, reported evidence, unknowns,
and a next step. **Explore** searches the full current review queue, with
type and route filters and newly discovered leads first. It includes leads
with no imported review. A missing or damaged export appears as
unavailable, not as an empty queue. Imported reviews may predate newer source
changes, so recheck official pages before acting. The dashboard does not run
AI review or turn collector scores into personal recommendations. See
[private workspace operations](docs/PRIVATE_WORKSPACE_OPERATIONS.md) for details.

The default `student-early-career` profile controls the review lane. Change
`routing.active_profile` in `config/default.toml` to `new-grad` or
`all-opportunities` if needed. Routing and scores classify public text only;
they are not verified availability, personal eligibility, or fit. Changing a
profile never deletes candidates. Similar titles may appear as possible
duplicate hints; only strong identity evidence merges records.
The packet shows official-source observations and excerpts as evidence cues;
they do not change its route-and-score order. Packet selection does not record
which leads an AI handled; Home reflects only decisions actually imported.

## Code and data boundary

This repository contains both collector code and provider-neutral tools for an
explicitly selected private workspace. Collector SQLite and public exports
contain public leads only. Applicant data, review decisions, drafts, and
application state belong in the external private workspace, outside the Git
checkout. The workspace tools do not call an AI provider. See the
[architecture](docs/ARCHITECTURE.md), [integration contract](docs/INTEGRATION_CONTRACT.md),
and [privacy rules](docs/SECURITY_AND_PRIVACY.md).

The source list in `config/sources.toml` is edited manually. A failed source
check does not mean its previously found leads have closed; check
`source_health.json`. The packet is incomplete, and a source link, score,
route, or stated deadline does not prove a role is open or that you qualify.
There are no logins, application submissions, or authenticated board automation.
Generated `data/`, `output/`, and `logs/` stay untracked; run `opdisc audit`
before publication.

## Development

```bash
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest -m 'not live'
.venv/bin/ruff check src tests scripts/demo_workspace.py
.venv/bin/mypy
.venv/bin/opdisc audit .
```

Use `opdisc --help` for all commands. Read `AGENTS.md` before changing the
engine. MIT license; see `LICENSE`.
