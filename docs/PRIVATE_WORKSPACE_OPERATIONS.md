# Review and manage your workspace

Start with [profile and board setup](AI_SETUP.md) for the two AI prompts.
Use the dashboard for everyday actions. The commands below cover manual imports,
backups, and recovery.

Open PowerShell and run this setup, changing `$workspace` if you chose another location:

```powershell
$workspace = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "Opportunity-Workspace"
Set-Location -LiteralPath (Join-Path $workspace "engine\opportunity-discovery") -ErrorAction Stop
$opdisc = ".\.venv\Scripts\opdisc.exe"
```

If you installed the engine elsewhere, use that folder in `Set-Location`. On Linux, run commands from the engine folder using your actual workspace path and `.venv/bin/opdisc` in place of `& $opdisc`.

## Open the dashboard

On Windows, double-click **Open Dashboard.cmd** in your workspace. Keep its
window open while using the dashboard; close it or press Ctrl+C to stop.

For a manual launch from the project folder:

```powershell
& $opdisc workspace-dashboard $workspace
```

Open `http://127.0.0.1:8765/` if the browser does not open automatically. Stop the server with Ctrl+C.

- **Home** shows imported review decisions that still need attention, with reasons and a next action.
- **Explore** uses personal screening across the full collection when configured, with separate research labels. It otherwise searches the public review queue.
- **Waiting**, **Dismissed**, and **History** show your other board items.

Home can be empty before your first review. If Explore says its export is unavailable, run the collector and check `output/source_health.json`. To use a different export folder, pass `--manifest PATH/TO/export_manifest.json`.

Select a reviewed item to use **Done**, **Delete**, or **Restore**. Done means no further action is needed; Delete hides an unwanted item. You can add a reason to help your agent understand your preferences. Neither action removes the public lead from the collector.

**Forget Completely** requires typing `FORGET`. It deletes the current board record and its ID-named opportunity and application folders. The lead can appear again. Earlier reports, knowledge, source files, and backups remain; this is not complete erasure of every copy.

Run one dashboard per workspace and stop it before changing that workspace through CLI commands.

## Screening before research

Your chosen AI prepares the private profile during onboarding. It uses
[workspace-screening-profile.schema.json](../schemas/workspace-screening-profile.schema.json),
saves the input outside the checkout, and imports it with:

```powershell
& $opdisc workspace-profile $workspace (Join-Path $workspace "screening-profile.json")
& $opdisc workspace-screen $workspace
& $opdisc workspace-screening $workspace --limit 25
```

`workspace-profile` validates and saves `.opdisc/screening-profile.json`.
It never changes the public collector configuration. The profile contains major
aliases, interests, graduation month, enrollment status, year in the program,
and separately recorded unit-based class standing. Missing personal facts stay
null. The experience limit is optional; do not infer a limit of zero for students.

Set `opportunity_focus` to the user's chosen emphasis:

| Setting | First emphasis | Secondary leads |
| --- | --- | --- |
| `early-opportunities` | Exploratory programs and dedicated freshman/sophomore roles | Other programs, internships, and student research |
| `standard-internships` | Undergraduate internships, including junior-year roles | Dedicated early-year roles, programs, and research |
| `new-grad` | Entry-level full-time jobs; explicit job cues with unknown employment type remain questions | Broader jobs and programs |

Null preserves a feed without a stage preference. The AI asks the user rather
than inferring this choice from their graduation date. Preferred leads appear
before secondary leads, with category balancing within each preference tier.
In early mode, exploratory programs receive broad consideration without an
exact major/interest keyword match. Known mismatches still mean low relevance;
unknown GPA, coursework, and class-year eligibility remain questions. Stage
preference is separate from screening status and official-page verification.
Academic-year cues must describe students; first-year employee benefits,
company anniversaries, and graduate-school years do not establish an early
undergraduate opportunity. A sophomore-or-higher minimum is secondary rather
than a dedicated early-year cue. A generic public "program" label alone does
not establish an exploratory program. If an older experienced-role label
conflicts with an internship title, screening asks about role level instead
of treating that label as a proven mismatch. Other explicit mismatches remain.

For geographic preferences, the AI translates a natural-language region into
`location_regions`. Each region has a human-readable `label`, `match_terms`
(city, county, and regional names), and `context_terms` (state or country names
and abbreviations). For example, Greater Boston can include Boston, Cambridge,
and Somerville with Massachusetts/MA context. This is an explicit set of text
aliases, not geocoding or a distance calculation. If a posting omits context or
uses an unrecognized city, screening asks about it rather than declaring a
mismatch. The AI can revise the region when that interpretation is supported.
Do not apply one user's geographic settings to other installations.

Ask about `location_policy`: `prefer-local` (the backward-compatible default)
keeps other locations as questions; `local-only` filters explicit geographic
mismatches; `local-jobs-funded-programs` filters jobs and internships while
allowing short programs elsewhere with source-backed travel coverage. Short
means at most 14 days, established by event dates or an explicit program
duration. Housing alone is not travel coverage, and an internship's relocation
benefit does not bypass the region limit. Missing or conditional funding and
unresolved duration remain questions. Explicitly unfunded programs are low
relevance under this policy. All leads remain recoverable.

The current deterministic exclusion recognizes explicit US states and common
country names outside the configured contexts. A city in the same state but absent from the metro
aliases, incomplete location text, or other unresolved geography stays a
question for the optional AI pass. The AI can expand aliases when supported;
the collector does not call an AI or infer geographic boundaries.

`workspace-screen` processes every record in manifest-verified `candidates.jsonl`,
including records outside the generic queue. It saves private findings in
`.opdisc/screening.json`: worth investigating, needs clarification, or low
relevance, with evidence reasons and unresolved questions. It preserves
unchanged findings, removed records, and custom extensions. Changed candidate
facts, changed profile settings, or a new screening rules version invalidate
the relevant saved findings. It does not change the application board.

`workspace-screening` reads a bounded batch for your agent; it makes no AI calls
and writes nothing. Use `--state needs-clarification`, `--lane research`,
`--search TEXT`, `--offset N`, or `--uncapped` as needed. The employer cap defaults
to three matching records across the displayed results; it never deletes a lead.
Preferred exploratory and early-year programs in early mode are exempt and do
not consume ordinary-role slots, so distinct programs from one employer remain
visible. Ordinary internships and jobs still use the cap.
The cap and research staleness window are configurable in the private profile.
Explore previews unsaved/outdated screening with an explicit label; a dashboard
read does not silently persist screening.
Suggested results also respect existing dismissed, completed, and waiting board
decisions. Use `--state all --uncapped` to recover every matching collected lead.

For semantic interpretation of a small batch, the AI may prepare a
[workspace-screening-response.schema.json](../schemas/workspace-screening-response.schema.json)
response and run:

```powershell
& $opdisc workspace-apply-screening $workspace (Join-Path $workspace "screening-response.json")
```

The response must match the current export generation, normalized profile hash,
and each candidate's facts hash from `workspace-screening`. It quotes captured
candidate fields, applies at most 100 decisions, preserves unresolved personal
GPA/coursework/authorization/experience/class-standing questions, and cannot
promote an explicit deterministic mismatch. This is screening, not official
research: it neither creates a board record nor marks a page as checked.
Keep these passes small; normalizing shared preferences once is usually more
useful than asking an AI to read every lead.

Official-page findings still use `workspace-apply-review` below. Coverage counts
saved current screening, plausible screened leads, reported official checks,
and actionable leads awaiting investigation. A checked page can still require
investigation after a material source change, an approaching deadline (21 days),
an unresolved finding, or the configured staleness interval. Mere collection
timestamps do not invalidate a check. Imported findings and user decisions are
preserved until an explicit subsequent review or action changes them.
Unreviewed leads first seen or materially changed within seven days take
precedence over an unchanged backlog within each category. An approaching
deadline uses a 21-day window; neither window establishes official availability.

## Import an agent's review

The [board setup prompt](AI_SETUP.md#2-create-your-first-board) asks your AI to
review and import its findings. For a manual import of a saved `review.json`,
run:

```powershell
& $opdisc workspace-apply-review $workspace (Join-Path $workspace "review.json") --manifest .\output\export_manifest.json
```

A successful import makes the decisions available in the dashboard. If the command rejects a response, correct the reported problem before retrying. If collection has generated new exports, ask the agent to refresh its response against them.

On Linux, from the project folder:

```bash
workspace="/path/to/Opportunity-Workspace"
.venv/bin/opdisc workspace-apply-review "$workspace" "$workspace/review.json" --manifest output/export_manifest.json
.venv/bin/opdisc workspace-dashboard "$workspace"
```

The 40-lead packet is a starting sample, not a complete review. Prefer a bounded
personal screening batch for later research. Public queues and new/changed-lead
packets remain available. Imported decisions record successful findings, not
everything an agent has read; unsaved reading does not count as checked coverage.

## Prepare an application

Select a reviewed opportunity and use **Application preparation**. Choose the kind of work and describe what you want your agent to do. The dashboard shows the new request folder under `applications/OPPORTUNITY_ID/requests/`.

Open that folder's `HANDOFF.md` with your agent. It contains the request and references; the agent can save drafts in `drafts/` and later versions in `revisions/`. Review the result yourself before applying. Creating a request does not invoke an agent or submit an application.

For CLI requests, use `workspace-request --help`. Reference files must exist under the workspace's `sources/` or `knowledge/` folders.

## Backup and restore

Stop the dashboard and other workspace-changing commands before backing up or restoring.

Create a full backup outside your workspace:

```powershell
$backupFolder = Join-Path (Split-Path $workspace -Parent) "Opportunity-Backups"
$backup = Join-Path $backupFolder ("workspace-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".zip")
& $opdisc backup-workspace $workspace $backup --kind full
```

A full backup preserves your workspace files, including skills and folders you add. It also includes the dashboard launcher and `config/default.toml` and `config/sources.toml` from the engine folder inside your workspace. The command creates the backup folder if needed.

Engine code, Python environments, Git history, generated caches and temporary files, and earlier workspace backup ZIPs are excluded. Files linked from outside your workspace are not copied.

For a smaller backup, use `--kind state`. It keeps instructions, skills, knowledge, board state, applications, history, the launcher, and collector settings. It omits `inbox/`, `sources/`, and other custom folders.

Backups are **unencrypted ZIP files containing private information**. Store them accordingly and use a new filename for each backup.

On a new computer or after removing your workspace, [install the app](OPERATIONS_WINDOWS.md#new-installation) first. Then run the PowerShell setup at the top of this page with the workspace you want to restore.

Choose the backup ZIP and restore:

```powershell
$backup = Read-Host "Full path to the workspace backup ZIP"
& $opdisc restore-workspace $workspace $backup
```

Restore checks the archive and creates a full backup of your current workspace before replacing matching files. It leaves unrelated files in place and reports the pre-restore backup path. It is not an exact rollback that deletes newer files.

## Recover generated knowledge

Review imports and reasoned feedback save snapshots of the generated knowledge files they change. These are not backups of everything an agent edits; use a full workspace backup for that.

```powershell
& $opdisc knowledge-snapshots $workspace
```

Choose a snapshot ID from the output, compare it, and restore only if it contains the version you want:

```powershell
$snapshot = Read-Host "Snapshot ID"
& $opdisc compare-knowledge $workspace $snapshot
```

After inspecting the comparison:

```powershell
& $opdisc restore-knowledge $workspace $snapshot
```

Restore saves the current generated knowledge first. Retention keeps the latest daily snapshot for 30 days and one per older month.

## Try the fictional demo

From the project folder, create a new temporary workspace:

```powershell
$demo = Join-Path $env:TEMP ("Opportunity-Demo-" + [guid]::NewGuid().ToString("N"))
.\.venv\Scripts\python.exe scripts\demo_workspace.py $demo
```

After creation succeeds, open it using its synthetic exports:

```powershell
$demoManifest = Join-Path $demo ".opdisc\demo-generation\export_manifest.json"
& $opdisc workspace-dashboard $demo --manifest $demoManifest
```

The demo contains fictional leads, a profile, and an application request with a fake draft. It refuses an existing destination.

## CLI and file-format reference

Use `& $opdisc COMMAND --help` for arguments to a specific command. The [integration contract](INTEGRATION_CONTRACT.md) describes the review rules and formats.

- [Review responses](../schemas/workspace-review.schema.json) must match the selected export generation. Older reviews cannot replace newer ones. Repeating the same accepted response is safe. Promotion requires the official evidence and eligibility checks described in the contract.
- [Feedback responses](../schemas/workspace-feedback.schema.json) require a reason for Done/Delete and a `preference_signals` list, which can be empty. Older feedback cannot replace a later Done/Delete/restore action. Feedback learns named soft preferences, not collector configuration or hard filters.
- `workspace-board` and `workspace-history` provide filtered, paginated JSON for integrations. Per-opportunity history is incomplete for records created before board-action logging was added.
- `workspace-pipeline`, `workspace-wait`, and `workspace-resume` update application progress and waiting state. Done moves an item to History without changing its factual pipeline state.
- Application results can use the [application response schema](../schemas/workspace-application-response.schema.json). The profile and catalog are included as request references when present.
- `workspace-audit` checks for private files tracked in Git and missing or changed references. A dirty-engine warning means you should preserve local changes before updating.
- `.opdisc/checkpoint.json` records operation progress and recovery instructions. Files are replaced individually, not as one transaction; do not run concurrent workspace mutations.

Backup and recovery reject unsafe archive paths and symlinked files. These checks do not encrypt your data or control who can access your computer.
