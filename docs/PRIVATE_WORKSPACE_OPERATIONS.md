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
- **Explore** searches the complete current review queue, including leads with no imported review.
- **Waiting**, **Dismissed**, and **History** show your other board items.

Home can be empty before your first review. If Explore says its export is unavailable, run the collector and check `output/source_health.json`. To use a different export folder, pass `--manifest PATH/TO/export_manifest.json`.

Select a reviewed item to use **Done**, **Delete**, or **Restore**. Done means no further action is needed; Delete hides an unwanted item. You can add a reason to help your agent understand your preferences. Neither action removes the public lead from the collector.

**Forget Completely** requires typing `FORGET`. It deletes the current board record and its ID-named opportunity and application folders. The lead can appear again. Earlier reports, knowledge, source files, and backups remain; this is not complete erasure of every copy.

Run one dashboard per workspace and stop it before changing that workspace through CLI commands.

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

The 40-lead packet is a starting sample, not a complete review. For later sessions, ask your agent to select more leads from `review_queue.jsonl` or the new/changed-lead packets. Imported decisions do not track everything an agent has read, and the starter sample may repeat leads.

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
