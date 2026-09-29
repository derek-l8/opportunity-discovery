# Private workspace initialization

`opdisc init-workspace PATH` creates a private workspace outside the engine
Git checkout:

```text
Opportunity-Workspace/
|-- WORKSPACE.md
|-- AGENTS.md
|-- CLAUDE.md
|-- engine/
|   `-- opportunity-discovery/
|-- inbox/
|-- sources/
|-- knowledge/
|   |-- PROFILE.md
|   `-- CATALOG.md
|-- opportunities/
|-- applications/
`-- .opdisc/
    |-- workspace.json
    `-- source-manifest.json
```

`WORKSPACE.md` is the canonical standing policy. `AGENTS.md` and `CLAUDE.md`
only direct a compatible local agent to that file while allowing the user to
designate additional instructions. Every starter is created
only when missing. After initialization, rerunning setup never overwrites an
instruction file or recreates one the user deleted. The initializer records the
actual public engine checkout passed with `--engine-path` in
`.opdisc/workspace.json`; this machine-local record is authoritative and
preserves its `custom` metadata when the engine location changes.

The recommended Windows installation puts the actual checkout in the canonical
location before running the installer:

```powershell
$documents = [Environment]::GetFolderPath("MyDocuments")
$workspace = Join-Path $documents "Opportunity-Workspace"
New-Item -ItemType Directory -Force (Join-Path $workspace "engine")
git clone https://github.com/derek-l8/opportunity-discovery.git `
    (Join-Path $workspace "engine\opportunity-discovery")
Set-Location (Join-Path $workspace "engine\opportunity-discovery")
.\scripts\install.ps1 -WorkspacePath $workspace
```

The installer never moves, copies, reclones, or duplicates its active checkout.
An existing checkout outside the workspace is supported by `--engine-path` and
by `install.ps1`, which records the path and warns that an agent opened only at
the workspace root may not be able to access it. No empty canonical checkout
directory is created in external mode. A supplied engine path must already be
an existing directory.

The source manifest is versioned and has a `custom` object for user-defined
metadata. Its schema is `schemas/workspace-source-manifest.schema.json`.
Every `stored_path` uses forward slashes and is relative to the workspace below
`sources/`; absolute paths, backslashes, and parent traversal are rejected.
Optional `external_references` record a private path and label for read-only
projects that are intentionally not copied. `workspace-audit` warns when such a
path is unavailable. Older manifests without this optional array remain valid. Initialization does
not process inbox files or call AI. See
`docs/PRIVATE_WORKSPACE_OPERATIONS.md` for review, feedback, backups, and
restore.

Workspace content is private and may contain sensitive information. Keep its
runtime files outside the Git checkout; the recommended layout places the
checkout under the workspace root, beside private folders. The command warns,
but does not refuse, when the selected workspace is inside a Git checkout.
External project folders are not copied or modified by this phase.
