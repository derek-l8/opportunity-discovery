# Proposed program sources

Researched October 4, 2026. This is a public source-expansion proposal, not an
applicant eligibility assessment. No sources were enabled, registry rules changed,
or production records ingested during this research. All changes remain local.

The first additions should cover several opportunity categories. Adding only
quant-finance programs would preserve the current coverage imbalance in another
form. Recurring family overviews are useful monitoring records, but an interest
form must not be presented as an open application.

See [additional early opportunity sources](EARLY_OPPORTUNITY_SOURCE_CANDIDATES.md)
for further first-/second-year discovery, hackathons, campus research/founder
programs, conferences, pass costs and conditional travel-funding routes.

## First implementation batch

These ten source families offer useful public facts and readable HTML. Their
current status determines whether to emit an actionable cycle or a monitoring
record; inclusion here does not mean applications are currently open.

| Source family and official pages | Contribution | Verified facts and current status | Proposed ingestion |
| --- | --- | --- | --- |
| [Discover Citadel and Citadel Securities — US](https://www.citadel.com/careers/programs-and-events/discover-citadel/apply/) | Short exploratory program | An application is present for early April 2027 in New York. Deadline March 5, 2027; undergraduates age 18+, attending US/Canadian universities, graduating December 2028–June 2030. Airfare, ground transport, two hotel nights, and meals are included, subject to the published terms. | One explicit US 2027 cycle. Extract the introductory block, including eligibility after the long benefits paragraph; never collect application input values. Exact event dates remain unknown. |
| [Jane Street FTTP](https://www.janestreet.com/join-jane-street/programs-and-events/fttp/) | Dedicated first-year exploration | A few-day program for first-year undergraduates planning STEM study; finance knowledge is not required. Travel, housing, and meals are covered. The current page offers notification signup, not a dated application. | Family monitoring record with `notification-only`. Title is graphical, so configure a title plus canaries for the actual program text. Preserve qualitative duration and the nearest-location instruction. |
| [Jane Street Bridge](https://www.janestreet.com/join-jane-street/programs-and-events/bridge/) | Early technical-commercial exploration | A daylong program for first-/second-year university students. New York offers Strategy and Product; London also offers Institutional Sales and Trading. Travel, housing, and meals are provided. Current route is notification signup. | Separate family from FTTP. Keep track/location differences and the sales track's prior-learning wording. Do not invent session dates or transfer one track's requirements to another. |
| [HRT Inside HRT / early talent](https://www.hudsonrivertrading.com/student-opportunities/) | First-/second-year STEM exploration | Inside HRT is a three-day New York program with an express-interest route. Explore HRT has different graduation/location requirements. The page's paid travel/housing FAQ describes interns; it does not establish coverage for Inside HRT. | Initially capture Inside HRT as a monitoring family. Use its section only, remove responsive duplicate blocks, and keep travel funding unknown. Add siblings only with separate identities and section canaries. |
| [IPAM RIPS-LA 2027](https://www.ipam.ucla.edu/programs/student-research-programs/research-in-industrial-projects-for-students-rips-2027-los-angeles/) and [FAQ](https://www.ipam.ucla.edu/programs/student-research-programs/research-in-industrial-projects-for-students-rips-2027-los-angeles/?tab=faq) | Research with industry/public-sector sponsors | June 21–August 20, 2027. Undergraduate research teams receive stipend, travel allowance, housing, and meals. The overview gives February 2027 as the deadline month, not a day. The FAQ still contains a 2026 eligibility example. | One 2027 LA cycle. Preserve month-only deadline language; exact deadline stays unknown. Do not import a 2026 FAQ restriction into the 2027 cycle. This is a summer research program, not a short travel exception. |
| DOE SULI: [overview](https://science.osti.gov/wdts/suli), [eligibility](https://science.osti.gov/wdts/suli/Eligibility), [benefits](https://science.osti.gov/wdts/suli/Benefits), [dates](https://science.osti.gov/wdts/suli/Key-Dates) | Broad public-laboratory research | Spring 2027 is closed. The summer 2027 application opens October 14, 2026 and is due January 6, 2027 at 5 PM Eastern. Eligibility includes matriculated college coursework, GPA and citizenship/residency rules; pre-matriculation credits have explicit exclusions. Benefits are described separately. | Repair existing `prog-doe-suli`, which currently extracts navigation links. Join four exact pages by program/term. Keep fall, spring and summer dates in separate table columns; preserve the source's tentative-date wording. |
| [USC/ISI SRAII REU application information](https://reu.ant.isi.edu/apply/index.html) | AI/internet research | The visible cycle is June 1–August 7, 2026, with a February 12, 2026 deadline. It states stipend, housing, meals and travel reimbursement. Normally applicants have finished their second year; exceptional freshmen may be considered. | Monitor for the next cycle. Do not relabel the 2026 opportunity as summer 2027. Preserve the exceptional-freshman clause alongside the ordinary minimum, plus citizenship/residency restrictions. |
| [IEEE PES Scholarship Plus](https://ieee-pes.org/about-pes/awards-scholarships/pes-scholar/) and [FAQ](https://ieee-pes.org/about-pes/awards-scholarships/pes-scholar/frequently-asked-questions/) | Scholarships and power/energy career exposure | Undergraduate fields extend beyond EE. Published requirements include GPA, institution/accreditation, citizenship/residency, and planned/completed power-and-energy coursework. The overview gives an annual January 20–May 14 window without an unambiguous upcoming cycle year. | Family monitoring record until a specific cycle is verified. Preserve all conditions and ambiguous annual dates; do not derive a 2027 deadline from a yearless window or an old award announcement. |
| [SWE scholarship applications](https://swe.org/apply-for-a-swe-scholarship/) and [FAQ](https://swe.org/scholarship-faq/) | Scholarships at several undergraduate stages | The 2026–27 applications are explicitly closed; 2027–28 interest forms are available. Emerging First Year and Collegiate/Graduate have different academic-stage and GPA rules. India is a separate route. | Replace the quarantined `conf-swe-scholarships` route with this verified public page after fixtures and tests. Separate stage/region families; interest forms are `notification-only`. Retain scholarship-specific conditions rather than inferring them from the organization's name. |
| [Microsoft Student Ambassadors — official registration guidance](https://learn.microsoft.com/en-us/training/student-hub/become-a-student-ambassador) | Campus leadership, networking and technical communication | Current guidance offers registration without an application and welcomes degree fields/levels, part-/full-time students, and two-/four-year institutions. Benefits include tools, community and credits; this page does not describe a paid job. | An evergreen community-program record, with registration distinguished from competitive job applications. Read public guidance only; account registration is a manual handoff. Do not combine it with the separate paid Copilot Ambassador program. |

## Conditional additions and monitoring targets

These broaden coverage but require stronger restrictions, better cycle isolation,
or additional extraction work. They should not all become default actionable leads.

| Candidate | What the official source establishes | Treatment |
| --- | --- | --- |
| Caltech WAVE: [overview](https://sfp.caltech.edu/undergraduate-research/programs/wavefellows), [eligibility](https://sfp.caltech.edu/undergraduate-research/programs/wavefellows/eligibility), [application](https://sfp.caltech.edu/undergraduate-research/programs/wavefellows/application_information) | Ten-week research; sophomore/junior/non-graduating senior, 3.4 GPA, prior research, PhD interest, and citizenship/residency/DACA conditions. Application page announces WAVE 2027 opening November 1; overview benefits/dates are still labeled 2026. | Useful secondary research source, not a general freshman program. Isolate eligibility, cycle announcement and prior-cycle benefits; do not carry a 2026 award into 2027 as a verified amount. |
| [Leadership Alliance SR-EIP](https://theleadershipalliance.org/summer-research-early-identification-program) | Eight–ten weeks of paid research with travel/housing; GPA, enrollment, citizenship and graduate-study conditions. The page still advertises the 2026 deadline; research-site entries have their own requirements. | Monitor for 2027. Capture general rules separately from host-specific criteria; avoid treating the entire directory as one site's requirements. |
| [James H. Wyche First Year Research Experience](https://theleadershipalliance.org/james-h-wyche-first-year-research-experience) | Paid research specifically for first-year undergraduates from Leadership Alliance minority-serving partner institutions and HBCUs. | A dedicated early-year source for supported institutions. It is not an unrestricted national first-year opportunity; participation scope and current application route must be explicit. |
| [Optiver FutureFocus](https://www.optiver.com/join-us/students/programs/futurefocus/) and [2027 Amsterdam Quants application](https://prod-www.optiver.com/join-us/jobs/trading/amsterdam/futurefocus-quants-2027/) | Five-day discovery; the verified 2027 Amsterdam route requires graduation in 2029 and UK/Ireland/European university attendance. Travel and accommodation are covered, with separate session dates and deadlines by participant group. | Add as an international lane with exact session IDs. Do not advertise this European cycle as a US student program or transfer European funding claims to an unverified US cycle. |
| [D. E. Shaw campus experiences](https://campus.deshaw.com/) | Current page lists a one-day London Insight Programme, covered travel/accommodation, and closed applications with a notification route for students interested in summer 2028 internships. | International monitoring candidate. The old fellowship domain redirects here; stale search snippets for Discovery/Latitude/Momentum/Nexus are insufficient evidence of live US fellowship pages. |
| [NVIDIA Ignite overview](https://www.nvidia.com/en-us/about-nvidia/careers/university-recruiting/) | Twelve-week summer pre-internship for current freshmen/sophomores. No specific open cycle or travel package was established from this overview. | Early-year internship family; link verified requisitions later. It is not a short exploratory travel program. |
| [Microsoft Explore overview](https://careers.microsoft.com/v2/global/en/universityinternship) | Official overview describes a twelve-week internship for first-/second-year college students. Discovery is a different route for rising college freshmen/high-school graduates. | Collect a specific verified requisition before calling it open. The broad careers page mixes program content with unrelated jobs and needs a scoped section parser. |
| [Neo Scholars](https://neo.com/scholars) | Public search indexing describes the program, but the native fetch produced only the title in visible HTML. | Defer automatic ingestion until a supported public payload is verified. HTTP 200 is insufficient; do not emit an apparently complete opportunity from a JavaScript shell. |
| [Tapia Conference's current site](https://tapiaconference.cmd-it.org/) | The old domain redirects to the CMD-IT host. Current page advertises September 16–18, 2026 in Atlanta, now past. It describes computing-community/networking goals, not a verified upcoming funded scholarship. | Repair/monitor candidate rather than an open travel award. The current redirect host needs explicit validation and configuration; do not carry forward the old quarantined endpoint or assume scholarship funding. |
| [SMART scholarship](https://www.smartscholarship.org/) | The public root is largely a JavaScript shell; official documents describe scholarship-for-service obligations. | Defer the automatic source until public rules, current cycle and service commitments can be extracted together. Do not describe it as unrestricted grant funding. |

## Collector prerequisites exposed by this research

The existing `program-page` adapter is the starting point, but enabling these
pages without changes would repeat part of the original extraction problem:

1. It bounds requirements at 600 characters before extracting qualifications.
   Citadel places eligibility after a lengthy benefits paragraph. Inspect full
   scoped sections and extract source facts before shortening display text.
2. It currently reads most fields from one primary page. SULI and WAVE need
   explicit field provenance across a small configured set of pages. Do not
   concatenate different terms or different programs indiscriminately.
3. It accepts only ISO dates for date fields. Preserve source date text and
   normalize unambiguous dates; month-only, yearless and inconsistent dates stay
   unknown. Tables need term-aware parsing, including time and timezone.
4. Multiple programs/regions on one page need separate stable identities. Use
   explicit program/session IDs where the source provides them; define a
   reviewed identity contract for undated family records. Never invent an annual
   cycle or merge similar titles. Keep notification overviews separate from
   application cycles.
5. Configure canaries for eligibility/funding/status sections, not only titles.
   Static titles must not make empty pages pass validation. Detect responsive
   duplicate sections and JavaScript shells. Failure preserves the last success.

The first implementation batch should add synthetic fixtures for open,
notification-only, closed, upcoming and incomplete pages; missing sections;
different academic stages; cross-page cycles; table dates; redirect changes; and
funded versus conditional/unknown travel. Full suite, isolated live source
validation and publication audit are required before enabling registry entries.

## Evidence and scope

The native collector fetcher probed 22 exact public URLs with robots enabled,
three workers, normal throttle, bounded responses and normal redirect checks.
Twenty-one returned HTTP 200. Neo's response contained only 12 visible text
characters; the old Tapia URL failed because it redirected outside the configured
host set. The new Tapia host was separately inspected through web research.
Probe results and fetched payloads are ignored under
`data/source-research/20261004/`; they are not adapter fixtures or source
registrations. Readability probes do not constitute production-adapter validation.

The checked sources include job-board employers already in the registry, but
their dedicated program pages expose content that general requisition feeds can
miss. SULI and SWE are repairs to existing coverage, not claims of novel programs.
No personal profile, ranking, eligibility decision or application state is stored
in this proposal. No account-gated pages, registrations or submissions were used.
