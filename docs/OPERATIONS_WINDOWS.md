# Install and update on Windows

Use PowerShell. Install [Git for Windows](https://git-scm.com/install/windows) and [Python 3.11–3.14](https://www.python.org/downloads/windows/) first. These commands install into `Documents\Opportunity-Workspace` by default. Change `$workspace` if you prefer another location.

## New installation

```powershell
$workspace = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "Opportunity-Workspace"
$engine = Join-Path $workspace "engine\opportunity-discovery"
New-Item -ItemType Directory -Force (Split-Path $engine -Parent) | Out-Null
git clone https://github.com/derek-l8/opportunity-discovery.git $engine
```

After cloning succeeds, enter the project folder and install:

```powershell
Set-Location $engine
.\scripts\install.ps1 -WorkspacePath $workspace
```

The installer chooses an installed Python version, creates `.venv`, sets up collector storage, and initializes the private workspace. It leaves existing private files in place. If you already cloned the repository, skip `git clone` and run the installer from that checkout with your chosen workspace path.

If PowerShell blocks the script, see [Troubleshooting](TROUBLESHOOTING.md#installation).

## First run

Follow [Set up your profile and first board](AI_SETUP.md). It has prompts for
your AI to organize your information, run collection, review leads, and open the
dashboard.

Open the dashboard later by double-clicking **Open Dashboard.cmd** in your
workspace. Keep its window open while using it; close it or press Ctrl+C to stop.

To collect without AI, run these commands from the project folder:

```powershell
.\scripts\run.ps1
.\.venv\Scripts\opdisc.exe source-health
```

The collector writes results under `output\` and a dated log under `logs\`.
Open the dashboard to search them in **Explore**. **Home** fills after AI review.

## Update an existing installation

Use the same project folder and private workspace; do not clone a second copy. In a new PowerShell session, set `$workspace` to your existing workspace path:

```powershell
$workspace = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "Opportunity-Workspace"
Set-Location (Join-Path $workspace "engine\opportunity-discovery")
git status --short
```

If your project folder is elsewhere, use its actual path in `Set-Location`. If the status command prints files, preserve those changes before updating. For configuration edits, follow [Keep your settings when updating](#keep-your-settings-when-updating). With an empty status, run these commands one at a time:

```powershell
git switch main
git pull --ff-only
```

After both succeed, update the installed package and run the collector:

```powershell
.\scripts\install.ps1 -WorkspacePath $workspace
.\scripts\run.ps1
```

Re-running the installer leaves your private files in place. A daily task needs no change if the project folder has not moved.

### Keep your settings when updating

Use this procedure when your only edits are in `config/default.toml` or `config/sources.toml`. If other files appear in `git status --short`, preserve that work separately before proceeding.

From your project folder, check the branch:

```powershell
git branch --show-current
```

These steps assume it prints `main`. If you are working on another branch, finish that work before updating this installation.

Save your configuration edits temporarily in Git's stash:

```powershell
git stash push -m "opdisc settings before update" -- config/default.toml config/sources.toml
```

After that succeeds, download the update:

```powershell
git pull --ff-only
```

Only after the pull succeeds, bring your settings back:

```powershell
git stash pop
git diff -- config/default.toml config/sources.toml
```

Check that your settings are present, then rerun the installer and collector as shown above. If the pull fails, your settings remain in the stash. If `stash pop` reports a conflict, stop: the saved copy remains in the stash, and the affected files contain both versions. Resolve the conflict while keeping your settings and any new required options; your coding agent can help. Do not discard the files or drop the stash to bypass the problem.

## Optional daily collection

```powershell
.\scripts\register-task.ps1
```

This creates an `OpportunityDiscovery` task for 7:30 a.m. local time. It runs the collector, not AI review. To remove it, run `.\scripts\unregister-task.ps1`. Nothing is scheduled by the installer.

For failed runs, check the newest `logs\run-YYYYMMDD.log` and `output\source_health.json`. Some sources can fail while a run still succeeds; their earlier results are retained. See [Troubleshooting](TROUBLESHOOTING.md) for common errors. For private review, backup, and restore commands, see [Private workspace operations](PRIVATE_WORKSPACE_OPERATIONS.md).
