# opportunity-discovery

Collect public internship, research, program, and event leads. The local dashboard lets you search the current review queue. You can ask your own AI agent to investigate leads and import its findings; the app does not run AI or submit applications.

## Get started

On Windows, install Git and Python 3.11–3.14, then follow [Install on Windows](docs/OPERATIONS_WINDOWS.md#new-installation). That guide shows how to choose a folder, run the collector, open the dashboard, and [update later](docs/OPERATIONS_WINDOWS.md#update-an-existing-installation).

On Linux, use Python 3.11–3.14. From a checkout:

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/opdisc init
.venv/bin/opdisc validate-config
.venv/bin/opdisc run
.venv/bin/opdisc init-workspace /path/to/Opportunity-Workspace --engine-path .
.venv/bin/opdisc workspace-dashboard /path/to/Opportunity-Workspace
```

## What you get

The collector writes public leads to `output/`. Start with `source_health.json` to see which sources worked. The dashboard's **Explore** view searches the full current review queue, including leads no one has reviewed. **Home** shows only imported review decisions that need attention, so it can be empty even when Explore has leads.

`review_packet.md` is a sample of up to 40 leads for a first review, not the full queue. The complete queue is in `review_queue.jsonl`; `candidates.jsonl` also includes leads outside that queue. A link, score, or stated deadline does not prove that an opportunity is open or that you qualify.

## Review with your own AI

Open your private workspace in your agent so it can use your reference files. Give it `output/review_packet.md`, `output/source_health.json`, `output/export_manifest.json`, and `schemas/workspace-review.schema.json` from the project folder. Ask it to check selected leads against official pages and save a JSON response matching the schema as `review.json` in the private workspace.

Import the response using the same exports the agent reviewed. In PowerShell, from the project folder, set `$workspace` to your private workspace:

```powershell
$workspace = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "Opportunity-Workspace"
.\.venv\Scripts\opdisc.exe workspace-apply-review $workspace (Join-Path $workspace "review.json") --manifest .\output\export_manifest.json
.\.venv\Scripts\opdisc.exe workspace-dashboard $workspace
```

Change `$workspace` above if you chose a different folder. If collection generated new exports while the agent was reviewing, refresh the response against those exports before importing it. Explore remains available for leads that were not in the sample. Imported findings may become outdated as sources change; check an official page before acting.

On Linux, from the project folder, set `workspace` to the private folder you chose:

```bash
workspace="/path/to/Opportunity-Workspace"
.venv/bin/opdisc workspace-apply-review "$workspace" "$workspace/review.json" --manifest output/export_manifest.json
.venv/bin/opdisc workspace-dashboard "$workspace"
```

## Your files and settings

The repository contains the collector and dashboard code. Your profile, source documents, review decisions, and drafts belong in the private folder chosen during setup. Keep personal files out of the Git checkout. See [private workspace setup](docs/WORKSPACE_INITIALIZATION.md) and [review and backup commands](docs/PRIVATE_WORKSPACE_OPERATIONS.md) when you need them.

The default `student-early-career` profile selects student opportunities for review. Set `routing.active_profile` in `config/default.toml` to `new-grad` for new-graduate and entry-level full-time roles, or `all-opportunities` to include every career stage. Changing profiles does not delete collected leads. When updating, [keep your configuration edits](docs/OPERATIONS_WINDOWS.md#keep-your-settings-when-updating).

## Development

```bash
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest -m 'not live'
.venv/bin/ruff check src tests scripts/demo_workspace.py
.venv/bin/mypy
.venv/bin/opdisc audit .
```

Use `opdisc --help` for the full command list. For internals, see [architecture](docs/ARCHITECTURE.md), [data model](docs/DATA_MODEL.md), and [integration contract](docs/INTEGRATION_CONTRACT.md). Read `AGENTS.md` before changing the engine. MIT license; see `LICENSE`.
