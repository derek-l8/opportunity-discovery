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
> profile and catalog, and keep important unknowns visible. Ask concise questions
> for missing information that affects screening: major, expected graduation,
> year in the degree program, any separately known unit-based standing, workable
> geographic regions, remote-work preferences, interests, and opportunity focus:
> early exploratory/freshman-sophomore programs, standard undergraduate internships,
> or entry-level full-time jobs. Interpret locations
> as the intended metropolitan regions rather than literal city-name filters;
> confirm material ambiguity. Ask whether locations are preferences or limits,
> and whether short programs elsewhere are acceptable when travel is covered.
> Normalize my answers into the private screening
> profile using docs/PRIVATE_WORKSPACE_OPERATIONS.md, and import it with
> workspace-profile. Do not invent GPA, coursework, experience, or eligibility.
> Finish with a short summary of what you saved and any unresolved questions.

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

> Read WORKSPACE.md and create my first opportunity board. Run collection,
> screen the full collection with workspace-screen, then read a bounded
> workspace-screening batch. Investigate plausible leads and specific unresolved
> requirements. Use a small semantic screening pass when captured text needs
> interpretation; use official-page research for availability and eligibility.
> Carry unchanged findings forward and prioritize new leads, material changes,
> approaching deadlines, and stale useful findings. Save and import your findings,
> confirm the import worked, then open the dashboard in its own window. Report
> source failures and coverage: screened, plausible, officially checked, and
> still awaiting investigation. State what remains unresolved.

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
