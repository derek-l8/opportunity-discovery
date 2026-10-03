# opportunity-discovery

Collect public internship, research, program, and event leads. The local dashboard lets you search the current review queue. You can ask your own AI agent to investigate leads and import its findings; the app does not run AI or submit applications.

## Get started

On Windows, install Git and Python 3.11–3.14, then follow [Install on Windows](docs/OPERATIONS_WINDOWS.md#new-installation). Next, [add your information and create your first board](docs/AI_SETUP.md). Open it afterward by double-clicking **Open Dashboard.cmd** in your workspace. See [update instructions](docs/OPERATIONS_WINDOWS.md#update-an-existing-installation) when needed.

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

The [setup guide](docs/AI_SETUP.md) has two prompts: one to organize your personal material, and one to collect leads, investigate them, import findings, and open the dashboard. Your AI handles the files and commands. You can add material and ask for another review later.

Check an official page before acting on an opportunity. For manual review imports and Linux commands, see [workspace operations](docs/PRIVATE_WORKSPACE_OPERATIONS.md#import-an-agents-review).

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
