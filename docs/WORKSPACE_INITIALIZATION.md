# Your private workspace

The installer creates a workspace for your own material and review decisions. On Windows, the suggested location is `Documents\Opportunity-Workspace`. You can choose another folder.

```text
Opportunity-Workspace/
|-- WORKSPACE.md
|-- AGENTS.md
|-- CLAUDE.md
|-- Open Dashboard.cmd
|-- engine/opportunity-discovery/   # Git checkout
|-- inbox/
|-- sources/
|-- knowledge/
|-- opportunities/
|-- applications/
`-- .opdisc/                       # local app state
```

Put reference files in `inbox/` and follow [personal setup](AI_SETUP.md#1-add-your-information).
Your AI preserves them in `sources/` and builds a profile and catalog in
`knowledge/`. The engine folder holds the public code; your personal material
belongs outside it.

`WORKSPACE.md` is the starting place for instructions to your AI agent. `AGENTS.md` and `CLAUDE.md` point compatible agents to it. You can change or remove these files. Running setup again leaves your existing files and instructions alone.

The Windows installer creates the workspace for you; see [Windows installation](OPERATIONS_WINDOWS.md#new-installation). Keep your private files outside the Git checkout. The initializer warns if you choose a folder inside one.

For review, backup, and restore commands, see [Private workspace operations](PRIVATE_WORKSPACE_OPERATIONS.md).
