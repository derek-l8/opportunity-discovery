# Private workspace initialization

`opdisc init-workspace PATH` creates the Phase 3 file boundary outside the
public engine checkout:

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
Phase 3 only establishes the contract. A later private workflow may process
`inbox/` by hashing each item, reusing an identical source, moving unchanged
content into `sources/`, recording its original name, stored relative path,
SHA-256, and import time, updating derived knowledge and `CATALOG.md`, and
leaving the inbox empty. None of those mutations is implemented in Phase 3.

Workspace content is private and may contain sensitive information. Keep the
workspace outside Git when practical. The command warns, but does not refuse,
when the selected location is already inside a Git checkout. External project
folders are not copied or modified by this phase.
