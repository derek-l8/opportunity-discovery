# Private workspace review and recovery

These commands are deterministic file tools for an external private workspace.
They do not include an AI SDK, call a model, browse official pages, schedule AI
work, submit applications, or modify collector SQLite state.

## Apply structured review

An agent writes a `schemas/workspace-review.schema.json` response against the
current export generation. Apply it explicitly:

```text
opdisc workspace-apply-review WORKSPACE RESPONSE.json --manifest output/export_manifest.json
```

All input and generation checks finish before private files change. The command
also validates every existing board, knowledge, proposal, and operation-report
file it will touch. An older review cannot replace a newer review for the same
opportunity. At an equal `reviewed_at`, only the identical input (tracked by
SHA-256) is accepted as an idempotent replay.

The command
updates `.opdisc/board.json`, `knowledge/AUTOMATED.json`, a bounded generated
Markdown view, `.opdisc/proposals.json`, and a material-change report. It keeps
availability, deadline, private eligibility, reviewer disposition, user state,
and collector snapshot in separate fields. Existing `user_state` is never
inferred or overwritten by automatic review. Existing proposal status and
metadata are preserved. Supported nested `custom` metadata, including
response-level metadata in operation reports, is merged or preserved.

Promotion is guarded by the threshold in `docs/INTEGRATION_CONTRACT.md`.
Unresolved promotion attempts remain `research_needed`. Protected changes are
only proposals; there is no command here that applies them.

## Record reasoned feedback

`opdisc workspace-apply-feedback WORKSPACE FEEDBACK.json` accepts
`schemas/workspace-feedback.schema.json`. Done or Delete requires at least one
non-blank string reason. `preference_signals` is required but may be empty.
The command changes the explicitly selected record's private `user_state` and
updates only named soft preference counters in `knowledge/PREFERENCES.json`.
Feedback IDs make learning idempotent. No collector configuration or hard
filter changes.
Feedback for the same opportunity must advance past the latest feedback or
direct Done/Delete/restore action. An older input, or a different input at the
same decision time, is rejected before any files change. Replaying the exact
latest input remains safe. Each input may name an opportunity only once, and
the board's update time never moves backward when an older but valid decision
for another record is applied.

## Knowledge history

Before automated review changes generated knowledge, or feedback changes soft
preferences, the workspace records the selected files under
`.opdisc/history/knowledge/`. Each snapshot says which operation created it and
whether each file existed. Retention keeps the latest daily snapshot for 30
days and the latest snapshot per older month. The snapshot for the current
operation is always kept.

Use `knowledge-snapshots`, `compare-knowledge`, and `restore-knowledge` to list,
compare, and restore. Restore validates snapshot hashes and first captures the
current files as a pre-restore snapshot. Snapshot creation, comparison, and
restore reject a symlink in any knowledge path component. Restore records a
complete or failed checkpoint; a failure names the pre-restore snapshot and
the exact recovery command.

## Dashboard-ready board commands

`opdisc --json workspace-board WORKSPACE` returns the versioned private read
model defined by `schemas/workspace-board-page.schema.json`. It reads only the
selected external workspace. Records sort by stable opportunity ID and support
`--view active|waiting|dismissed|history|all`, `--board-state`, `--user-status`,
`--pipeline-state`, `--availability`, case-insensitive `--search` over ID/title/
organization, and `--offset`/`--limit` (1–200). The response includes total
matches and `next_offset`. It carries verified facts, reviewer provenance,
collector provenance, user state, and supported `custom` fields without copying
the full collector description into each page. Record and board update times
remain monotonic when a later research response has an earlier timestamp than
a user action.

Lane precedence is dismissed (user Delete, reviewer dismissal, or duplicate),
then history for Done, then waiting (explicit wait or submitted/interviewing
pipeline), then history for an outcome pipeline state, then active. Done leaves
the factual pipeline state in place but moves the item to history, including
when it was submitted or explicitly waiting. These lanes are a view of private
state; they do not change public collector routing or eligibility.

`workspace-done` and `workspace-delete` take a workspace and opportunity ID.
Without a reason, they only change the user-controlled status. With
`--reason-code` or `--reason-text`, they use the same validated feedback importer
as `workspace-apply-feedback`; optional `--prefer SIGNAL` and `--avoid SIGNAL`
learn only named soft preferences and require a reason. `workspace-restore`
clears Done/Delete to the prior user status when known (otherwise `unreviewed`).
It leaves verified facts, review, pipeline state, and custom metadata intact.

`workspace-pipeline WORKSPACE ID STATE` records one of `not-started`,
`preparing`, `submitted`, `interviewing`, `offer`, `rejected`, or `withdrawn`.
`workspace-wait WORKSPACE ID --reason TEXT [--until YYYY-MM-DD]` and
`workspace-resume WORKSPACE ID` manage an explicit waiting flag separately from
pipeline state. These commands never infer an application submission.

`workspace-history WORKSPACE [--opportunity-id ID] [--offset N] [--limit N]`
reads Phase 6 board actions and the existing Phase 4/5 operation reports. A
per-opportunity query shows Phase 6 actions; older reports did not record a
complete per-opportunity event trail. The JSON contract is
`schemas/workspace-history-page.schema.json`. Reasoned direct actions appear
once even though they also create a Phase 4 feedback report.

`workspace-purge WORKSPACE ID` removes the current board record, its Phase 6
board events, and ID-named folders under `opportunities/` and `applications/`.
This removes the current anti-rediscovery record, so the public lead may appear
again. Purge rejects symlinked artifact paths. Earlier operation reports,
knowledge, source evidence, and separately created backup ZIPs remain; purge
is not secure erasure of archives. The user must manage those copies separately.
Mutating commands should run serially in one workspace; board, report, event,
and checkpoint files are individually atomic but do not form one transaction.

## Backup and restore

`backup-workspace --kind full` includes instructions, inbox, sources,
knowledge, opportunities, applications, manifests, board state, reports, and
history. `--kind state` omits inbox and source binaries. Both exclude the
engine checkout, caches, backup folders, temporary files, and symlinks.

Backups are ordinary unencrypted ZIP files containing private information.
`restore-workspace` rejects unlisted, corrupt, non-portable, cache, engine, and
out-of-scope archive paths. It creates a full pre-restore ZIP before atomically
replacing named files. It does not delete unrelated current files. The target
workspace's machine-specific root and engine paths remain authoritative while
the backed-up workspace `custom` metadata is restored.

Restore also rejects colon-bearing names (including Windows alternate data
streams) and case-insensitive path collisions. A failed backup records the
error and an exact rerun action in the workspace checkpoint.

## Workspace audit and checkpoints

`workspace-audit` reports a workspace inside Git, every tracked private file,
missing, changed, or symlinked preserved sources, unavailable external references,
knowledge links to missing local sources, and a dirty engine checkout. A dirty
engine warning means an updater must stop before pulling.

Mutating operations update `.opdisc/checkpoint.json` with their status,
completed steps, input hash when applicable, and exact next action. Review and
feedback inputs are idempotent so the same file can be rerun after correcting a
reported failure.

## Current limitations

There is no encryption, cloud transport, live-provider integration, scheduled
AI review, automatic proposal approval, visual dashboard, or application
drafting/submission in these phases. Native Windows PowerShell
validation remains a platform check; the implementation itself uses `pathlib`,
`os.replace`, and Python's cross-platform ZIP support.
