# Set up your profile and first board

Follow these steps after [installing](OPERATIONS_WINDOWS.md#new-installation).
Open your Opportunity-Workspace folder as a project in your AI tool. It needs
access to files and local commands; reviewing opportunities also needs web access.
The included AGENTS.md and CLAUDE.md point to WORKSPACE.md. With another tool,
ask it to read WORKSPACE.md.

## 1. Add your information

Put a résumé, notes, project descriptions, or other useful files in `inbox/`.
You can also give your AI text, images, links, or files directly. Writing samples
are optional. Start with what you have.

Send this prompt:

> Read WORKSPACE.md and set up my personal information from the material I've
> provided and anything in inbox. Preserve the original material, build a useful
> profile and catalog, and keep important unknowns visible. Finish with a short
> summary and any questions that would affect which opportunities suit me.

Your AI organizes the material in `sources/` and `knowledge/`.
Read `knowledge/PROFILE.md` to check what it understood.
`knowledge/CATALOG.md` points to useful supporting material.
You can customize WORKSPACE.md to suit how you want your AI to work.

To add something later, give it to your AI and ask it to update your profile
and catalog.

## 2. Create your first board

Send this prompt when you want recommendations:

> Read WORKSPACE.md and create my first opportunity board. Run collection,
> use my profile to choose leads to investigate, check their official pages,
> and save and import your findings. Confirm that the import worked, then open
> the dashboard in its own window. Tell me about source failures, unresolved
> questions, and how much of the collected list you reviewed.

Your AI needs web and command access to complete this step.

**Home** shows reviewed opportunities that need attention.
**Explore** lets you search the full current review queue, including unreviewed
leads. A first review covers a sample; ask your AI to review more when needed.
Some collected leads sit outside the queue because of the collector's settings.

## 3. Open and use it afterward

On Windows, double-click **Open Dashboard.cmd** in your workspace.
Keep its window open while using the dashboard. Close it or press Ctrl+C to stop.
If the browser does not open, visit [the dashboard](http://127.0.0.1:8765/).

Use **Done** when no further action is needed, **Delete** to hide an unwanted
item, and **Restore** to bring either back.

To refresh recommendations, stop the dashboard and ask your AI to collect and
review more leads using the same instructions. Collection runs separately from
AI review; daily collection does not refresh Home by itself.

For application drafts, select an opportunity's **Application preparation**
section and describe what you want. Give the resulting HANDOFF.md to your AI.
Review drafts yourself before applying.

See [workspace operations](PRIVATE_WORKSPACE_OPERATIONS.md) for manual commands
and backups, or [troubleshooting](TROUBLESHOOTING.md) if a step fails.
