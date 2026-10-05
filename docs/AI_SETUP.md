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

> Read WORKSPACE.md and the current profile instructions in the engine's
> docs/PRIVATE_WORKSPACE_OPERATIONS.md. Organize my supplied material and inbox
> into a profile and catalog, preserving the originals. Use documented answers
> first; ask concise questions about missing information that affects screening,
> including study stage, major, graduation, interests, and available locations.
> Ask whether I want early programs, standard internships, or entry-level jobs,
> and whether short programs elsewhere are acceptable with covered travel.
> Research surrounding metropolitan regions for my cities unless I request a
> narrower boundary. Save and import my private screening preferences, then
> summarize the regions, settings, and unresolved questions. Keep unknown
> credentials unknown.

Your AI organizes the material in `sources/` and `knowledge/`.
Read `knowledge/PROFILE.md` to check what it understood.
`knowledge/CATALOG.md` points to useful supporting material.
You can customize WORKSPACE.md to suit how you want your AI to work.

The AI also saves a structured screening profile under `.opdisc/`. It translates
your preferences into rules ordinary code can use, including metropolitan
regions and city aliases. You do not need to write JSON or choose an AI provider
inside the app. Check the AI's summary of the regions and other settings.
The selected opportunity focus sets which leads appear first. Early mode keeps
broadly related exploratory programs visible even when fit needs clarification.

To add something later, give it to your AI and ask it to update your profile
and catalog.

## 2. Create your first board

Send this prompt when you want recommendations:

> Read WORKSPACE.md and the current review instructions in the engine's
> docs/PRIVATE_WORKSPACE_OPERATIONS.md and docs/INTEGRATION_CONTRACT.md. Create my
> opportunity board: collect leads, screen the full collection, and investigate
> a recommended compact batch, including promising leads that need clarification.
> Reuse saved findings and documented profile answers. Prioritize new or changed
> leads, approaching deadlines, and stale useful findings. Interpret captured
> requirements when needed and check official pages before recommending action.
> Keep unresolved facts visible. Save and import your findings, confirm the import,
> then open the dashboard in its own window. Report source failures and coverage:
> screened, plausible, officially checked, awaiting investigation, and selected
> or deferred for later work.

Your AI needs web and command access to complete this step.

**Home** shows reviewed opportunities that need attention.
**Explore** shows personal screening across the full collection when a screening
profile exists. Screening is labeled separately from official-page research.
Category balancing and a per-employer display cap keep large boards from taking
over the feed. In early mode, preferred exploratory and early-year programs are
exempt from that cap. Its filters can recover low-relevance leads and show records
beyond the cap. Without a screening profile, Explore uses the public review
queue. You can select that public view explicitly at any time.

## 3. Open and use it afterward

On Windows, double-click **Open Dashboard.cmd** in your workspace.
Keep its window open while using the dashboard. Close it or press Ctrl+C to stop.
If the browser does not open, visit [the dashboard](http://127.0.0.1:8765/).

Use **Done** when no further action is needed, **Delete** to hide an unwanted
item, and **Restore** to bring either back.

To refresh recommendations, stop the dashboard and ask your AI to collect,
screen, and investigate using the same instructions. Deterministic screening
does not consume AI usage. Semantic screening and research use your chosen AI
only when you ask it to work; the app does not call a model. Daily collection
does not refresh Home by itself.

For application drafts, select an opportunity's **Application preparation**
section and describe what you want. Give the resulting HANDOFF.md to your AI.
Review drafts yourself before applying.

See [workspace operations](PRIVATE_WORKSPACE_OPERATIONS.md) for manual commands
and backups, or [troubleshooting](TROUBLESHOOTING.md) if a step fails.
