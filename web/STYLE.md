# ClusterWeave Web UI Style Guide

This document is the design and implementation handoff for future UI agents working on
`web/static/index.html`. ClusterWeave already has a functional static web UI wired to the
canonical shell workflow. The next UI work should improve visual identity and user
comprehension without disrupting uploads, jobs, worker telemetry, reruns, file downloads,
or figure rendering.

## Corrected Agent Brief

You are an expert frontend engineer and visual designer working on ClusterWeave's static web
UI. Your task is to evolve the existing operational interface into a distinctive "woven fungal
discovery command center" while preserving every working backend integration.

ClusterWeave is a fungal biosynthetic gene cluster workflow that remains shell-first and
HPC/Singularity-aware. The web UI is first a lab QA controller and later a public hosted demo
for non-coding users. The interface should make the workflow understandable at a glance:
genomes/accessions enter the system, canonical stages run, logs remain inspectable, and
figure/files outputs become available.

The UI should feel like a polished research instrument: scientific, bioinformatic, woven,
slightly gamified, modern, and memorable. It should not feel like a generic dark SaaS admin
dashboard, a marketing landing page, or a childish game.

Use inspiration from:

- Dark scientific signal fields, dithered particles, sparse command labels, and subtle
  interactive controls.
- A compact cinematic identity band with one memorable motif, not a full landing-page hero.
- `manuscript/application_note/figures/ClusterWeave.svg`: light scientific modules, rounded
  cards, teal/mint/indigo/violet/amber palette, braided paths, DNA/BGC/family graph/synteny
  motifs.

## Non-Negotiable Functional Constraints

Do not break these behaviors or identifiers:

- Static app: keep changes in `web/static/index.html` unless a small backend helper is clearly
  required.
- No build system, framework, package manager, or external CDN dependency.
- Preserve all IDs, event handlers, input names, and endpoint behavior used by the current JS.
- Preserve `apiUrl(...)`; it keeps the app working behind SSH/web preview path prefixes.
- Preserve `resultHref(...)` behavior: Open/preview should be inline; Download should request
  `?download=1`.
- Preserve manual accession entry and submission as `manual_accessions.txt`.
- Preserve same-job rerun behavior and metadata distinction between `submission_settings` and
  rerun settings.
- Visualization tab stays figure-only:
  `Data/Results/<project>/figures/*.{svg,png,jpg,jpeg,webp}`.
- Files tab keeps direct file rows with enough path context, Open, and Download.
- Console/logs remain available for lab QA, even if visually de-emphasized.
- Do not invent result counts, scientific scores, candidate names, or QA outcomes.

## Visual Direction

Design name: Woven Fungal Discovery Command Center.

Core idea:

- A live workflow map is the visual center.
- Upload/configuration is the input node.
- Jobs/runs are selected missions through the same workflow.
- Results are the output node: figures, files, and future priority interpretation.
- Braided connectors communicate "weave" without clutter.

Tone:

- Scientific and premium.
- Dramatic but credible.
- Clear enough for a first-time non-coding user.
- Dense enough for lab QA users.

Avoid:

- Generic Tailwind/admin-dashboard look.
- Random gradients on every card.
- Heavy glassmorphism.
- Cyberpunk overload.
- Fake metrics.
- Full landing-page hero that hides the actual tool.

## Current UI Evaluation

Baseline screenshot reviewed after Slice 7:

- The app is functional and visually much stronger than the original dashboard. It now has a
  compact identity band, signal-field background, manuscript-inspired teal/violet/amber
  palette, denser run cards, and a polished telemetry console.
- The UI reads as a credible lab instrument, but it still leans more "flat dark HUD" than
  "Neumorphism + Retrofuturism."
- The first viewport is still panel-first: upload/configuration, job queue, and telemetry are
  strong, but the user journey is not yet the dominant visual story.
- The current `Intake / Pipeline / Outputs` pills are directionally useful but too passive and
  small to serve as product navigation.
- The hero strip introduces ClusterWeave, but it does not yet carry a memorable WeaveMap motif
  or direct users through "add sources -> run stages -> inspect outputs."
- The page has good operational density. Do not replace it with a landing page or oversized
  hero.
- The two-column intake/queue layout works well. The next polish should connect these modules
  visually rather than rearranging the workflow again.
- The console is visually improved but still competes strongly with the rest of the UI because
  its contrast and terminal texture are very strong.

Gaps to address before final QA:

- Surfaces are mostly flat dark cards with borders. They need a tactile depth system:
  raised panels, recessed wells, bevel highlights, inset selected states, and pressed controls.
- The current retrofuturist language is mostly background texture and neon accents. It needs
  clearer instrument-console cues: segmented labels, signal rails, subtle CRT/dither texture,
  status lamps, and deliberate teal/amber/violet routing.
- Upload, workflow, queue, telemetry, and outputs still feel like adjacent panels more than one
  physical control surface.
- Buttons and inputs need a stronger hierarchy: raised primary action, recessed text wells,
  pressed toggles, and unmistakable focus states.
- Guided users need a clearer public-demo path: Load demo, Start run, View workflow map, then
  inspect outputs.
- Lab QA users still need fast access to worker state, logs, failures, job IDs, and artifacts,
  but these should not dominate the default first impression.
- Neumorphism must not reduce contrast. Text, controls, checkboxes, badges, and focus rings must
  remain readable and accessible.

## Public Release Pivot After Slice 11

After browser visual review of the Slice 11 UI, the project direction changed from a lab-QA-first
controller to a public hosted web service with admin-only QA capabilities. This does not discard
the visual work; it changes which parts are public by default.

Key visual review conclusions:

- The hero became redundant after the live workflow graphic was added. It should be simplified
  to two actions: `Start from NCBI accessions` and `Load demo run`.
- The static hero weave and the top-level `WeaveMap` section repeat the same concept. Remove
  the static hero weave, remove top-level `WeaveMap` nav, and move the live run timeline into
  Results as `Workflow progress`.
- The public Results surface should be the run surface. Before a job is loaded it should say:
  `Submit or load an existing run to see stage progress.`
- Once a job is submitted, the Upload & Configure panel should visually lock, grey, collapse,
  and hand the user to Results.
- `Run History`, full logs, reruns, worker telemetry, raw env overrides, stage toggles, and
  advanced runtime knobs are admin/local features, not public defaults.
- The output discovery cards introduced in Slice 11 are now redundant with Results tabs and
  should be removed from public UI.
- File paths in the Files tab should be displayed relative to the selected job/project; internal
  prefixes such as `Data/Results/<project>` are implementation details.

Public release product/security decisions now live in `web/STAN.md`. Future agents must read it
alongside this style guide before editing.

## Public Release Product Requirements

The first public release should be a single-page scientific service, not an exposed ops console.

Public access model:

- Anonymous users may load the static UI, view redacted service status, load demo accessions
  locally, and unlock an existing run by pasting a result link or `job_id + read token`.
- Anonymous users must not list jobs, see job IDs, read logs, read files, submit jobs, rerun jobs,
  or delete jobs.
- Job creation requires a submit token or admin token.
- Every job gets a random per-job read token. Job details, progress, sanitized failure summaries,
  figures, files, and downloads require that read token or an admin token.
- Admin token unlocks Lab QA, job list, full logs, worker telemetry, rerun controls, delete, and
  diagnostics.
- Keep one static SPA. Role-gate the UI by token, but enforce every permission server-side.

Public workflow:

- Public pipeline is fixed and canonical. No public stage toggles.
- Public intake supports:
  - manual NCBI accessions
  - one-accession-per-line `.txt` accession lists
  - genome uploads with `.fasta`, `.fa`, `.fna`, `.fsa`, `.gb`, `.gbk`, `.gbff`
  - UI-generated ecology metadata table only when ecology-aware analysis is enabled
- Do not expose NPLinker in the public WebUI for now.
- Do not expose raw env overrides in the public WebUI. Expert users who need those controls
  should run ClusterWeave locally.
- Public failure messages should be sanitized summaries with suggested fixes, not raw logs.
- Public users cannot delete jobs early. Admins can delete jobs.
- Public users cannot rerun jobs. Rerun controls are admin-only.

Public quota defaults, all env-configurable:

- Max accessions per job: `25`
- Max genome files per job: `25`
- Max individual upload file: `250 MB`
- Max total upload per job: `1 GB`
- Max queued jobs: `50`
- Max CPU per job: `8`
- Worker concurrency default: `1`
- Completed/failed job retention: `30 days`

Public status:

- Anonymous status shows only service online/offline, submissions open/paused, and aggregate jobs
  processed.
- Queue depth, worker phases, capabilities, logs, internal paths, and job IDs are admin-only.

Optional email:

- Add optional completion/failure email only when SMTP is configured.
- Store email in job metadata only, never logs.
- Email the result link and expiration date.
- Delete email metadata when the job expires.

Sensitive data notice:

- Public submission must require a data-use acknowledgment:
  users understand the public service is for public or releasable data only and results are
  accessible to anyone with the private result link until expiration.
- Encourage users with sensitive data or expert runtime needs to pull the Dockerized release and
  run locally.

Ecology label UI:

- When ecology-aware analysis is enabled, generate editable rows from pasted accessions and
  uploaded genome filename stems.
- Columns: `Input`, `Primary ecology`, `Secondary ecology`.
- Use dropdowns with controlled vocabulary plus `Other`.
- Allow blanks, but warn that unlabeled inputs reduce ranking usefulness.
- Emit canonical `ecofun_metadata_normalized.tsv` behind the scenes.
- Controlled vocabulary:
  `soil`, `plant_associated`, `endophyte`, `mycorrhiza`, `plant_pathogen`, `saprotroph`,
  `marine`, `freshwater`, `lichen_associated`, `insect_associated`, `animal_associated`,
  `human_associated`, `food_fermentation`, `unknown`, `other`.

Input filename guidance:

- Public genome filenames should use letters, numbers, `.`, `_`, and `-`.
- Avoid spaces, slashes, parentheses, duplicate filenames, and very long names.
- Each genome file stem should identify one genome; that stem becomes the ecology-table key for
  direct uploads.

## Neumorphism + Retrofuturism Target

ClusterWeave's version of Neumorphism is not pale consumer-app skeuomorphism. It should feel
like tactile scientific hardware in a dark lab: soft raised modules, inset data wells, beveled
edges, and pressable controls. Use it sparingly and structurally.

ClusterWeave's version of Retrofuturism is not arcade cyberpunk. It should feel like a
high-end research console: orbital/signal rails, amber command labels, teal status lamps,
violet routing lines, faint scan/dither textures, and compact technical typography.

Blend rules:

- Use neumorphism for physical hierarchy: app shell, cards, upload node, form wells, buttons,
  toggles, run cards, and selected states.
- Use retrofuturism for information flow: workflow paths, status pips, telemetry headers,
  stage labels, background signal texture, and figure/file output framing.
- Prefer 2-3 reusable shadow/depth tokens over one-off card effects.
- Keep light text on dark surfaces high contrast. Avoid low-contrast "embossed" text.
- Raised components should have both a dark cast shadow and a subtle light edge.
- Inset components should look like data wells, not disabled fields.
- Active/running states may glow; idle states should be quieter.
- Preserve the scientific color semantics: green/teal success, amber running/warning, red
  failure, blue/violet upcoming/context.

Suggested additional depth tokens:

```css
:root {
  --cw-raise-1: 8px 8px 18px rgba(0,0,0,.34), -4px -4px 14px rgba(255,252,244,.035);
  --cw-raise-2: 14px 18px 36px rgba(0,0,0,.42), -5px -5px 18px rgba(236,254,251,.045);
  --cw-inset-1: inset 5px 5px 12px rgba(0,0,0,.36), inset -3px -3px 10px rgba(255,252,244,.035);
  --cw-edge: inset 0 1px 0 rgba(255,252,244,.08), inset 1px 0 0 rgba(91,230,208,.05);
  --cw-retro-glow: 0 0 18px rgba(91,230,208,.22);
}
```

## Journey-First Product Requirements

The current UI is operationally complete enough to become more productized. The next work should
shift the page from panel-first to journey-first:

1. Add fungal genomes or accessions.
2. Weave them through canonical BGC workflow stages.
3. Inspect prioritized BGC outputs, synteny, family context, logs, and artifacts.

### Top-Level Navigation Shell

Create a clearer product navigation system while keeping the app single-page:

- Brand/logo on the left.
- Primary navigation:
  - Overview
  - Intake
  - WeaveMap
  - Runs
  - Outputs
  - QA Console
  - Docs
- Right side actions/status:
  - Load demo
  - Start run
  - Runtime/status chip
  - Results

Navigation behavior:

- Anchor to sections or switch focus states; do not introduce routing unless needed.
- Use active states that update when a section is selected.
- Collapse into a clean menu on smaller screens.
- Translate high-end product-site navigation to ClusterWeave:
  - "Services" -> workflow stages/tools.
  - "Solutions" -> user modes: Guided Demo, Lab QA, Advanced/HPC.
  - "Resources" -> Docs, Artifacts, Logs, Methods.
  - CTA -> Start run or Load demo accession.

### Hero And Quick Start

Replace the compact strip with a memorable but still operational hero:

- Left side: strong headline and concise body copy.
- Right side: static or lightweight animated WeaveMap motif showing genomes entering, braided
  paths crossing, and priority outputs emerging.
- Hero actions:
  - Primary: Start from accessions
  - Secondary: Load demo run
  - Tertiary: View workflow map

Suggested headline:

> Upload genomes or accessions, run canonical discovery stages, and inspect every output from
> annotation to gene cluster family context.

The hero must lead directly into the app workflow. It should not become a detached marketing
landing page.

### User Modes

Add a visible mode switch without changing backend behavior:

- Guided Demo: minimizes noisy telemetry, emphasizes upload/start/stage progress/outputs.
- Lab QA: expands worker telemetry, job IDs, runtime state, logs, failures, artifacts.
- Advanced: exposes advanced knobs, NPLinker assets, annotation strategy, CPU threads, target
  genome, and stage switches.

Implementation guidance:

- This can be CSS/JS section emphasis in the existing single-page app.
- Do not remove controls. Modes may collapse, emphasize, or scroll to sections.
- Default mode may be Guided Demo if no job is active, and Lab QA when a run is selected or
  running.

### WeaveMap

Make the canonical workflow the central visual story:

- Intake
- Prep
- Annotation / BGC detection
- BiG-SCAPE family mapping
- Summary / crosswalk
- clinker synteny
- Figures
- NPLinker
- Outputs

Each stage module should show:

- stage number
- stage name
- real tool chips
- status: idle, ready, running, complete, failed, skipped
- small progress line
- hover/focus detail
- artifact count only if real data exists

Connect stages with braided orange/teal paths. Pulse only the active braid/stage when a run is
active.

### Section Hierarchy

Suggested page structure after the next polish passes:

1. Header/nav
2. Cinematic workflow hero
3. Three-step quick start:
   - Add sources
   - Configure workflow
   - Start / monitor run
4. WeaveMap pipeline
5. Intake/configuration panel
6. Runs / run history
7. Outputs preview
8. Collapsible QA console / telemetry
9. Footer or compact docs/methods links

### Outputs

Add or refine a clear Outputs section, even when empty:

- Prioritized BGC shortlist
- Gene cluster family context
- Synteny/clinker panel
- Figures
- Artifacts/files
- NPLinker follow-up

Use honest empty states:

- "Run a workflow to populate this panel."
- "No artifacts available yet."
- "NPLinker optional follow-up not enabled."

Do not invent fake scientific results.

### Copy Direction

Prefer approachable scientific labels:

- Genome / accession intake
- Canonical workflow stages
- Worker telemetry
- Run history
- Priority outputs
- Artifacts
- Synteny panel
- Family context
- Load demo run
- Start workflow

Avoid childish game copy, excessive cyberpunk language, fake achievement metrics, and "quest"
wording except in very subtle internal metaphors.

## Practical Refinement Checklist

Carry these deltas through the next implementation passes:

- Security/API first, then UI. Do not hide an unsafe endpoint behind CSS.
- Add submit-token, per-job read-token, and admin-token enforcement server-side.
- Redact anonymous `/api/system/status`.
- Add quotas and retention metadata before widening public access.
- Keep one static SPA, but role-gate public, job-token, submit-token, and admin surfaces.
- Remove public `WeaveMap` naming; use `Workflow progress`.
- Remove hero static weave and top-level `WeaveMap` nav.
- Collapse/lock Upload & Configure after submit, then route users to Results.
- Put the live stage timeline inside Results, above Visualization/Files.
- Remove public Run History; keep it admin/local only.
- Remove output discovery cards from public Results.
- Trim displayed result paths while preserving `resultHref(...)` direct Open/Download behavior.
- Remove public NPLinker controls, raw env overrides, public reruns, public delete, public stage
  toggles, and public Lab QA.
- Add Existing Run loader and browser-session list of unlocked runs.
- Add ecology label table only when ecology-aware analysis is enabled.
- Keep public copy explicit about acceptable input types, filename hygiene, retention, result-link
  privacy, and local Docker for sensitive work.

## Design Tokens

Use CSS custom properties in `:root`. Prefer a balanced palette, not a one-note purple or dark
blue page.

Suggested palette:

```css
:root {
  --cw-ink: #0B0B12;
  --cw-panel: #111827;
  --cw-panel-2: #171717;
  --cw-paper: #FFFCF4;
  --cw-ivory: #FFF6E7;
  --cw-mint-50: #ECFEFB;
  --cw-mint-100: #DFF7F2;
  --cw-mint-200: #CAE7E2;
  --cw-mint-400: #5BE6D0;
  --cw-teal-500: #14B8A6;
  --cw-teal-700: #0F766E;
  --cw-teal-900: #226258;
  --cw-indigo-50: #EEF2FF;
  --cw-violet-50: #F5F3FF;
  --cw-violet-200: #DEDBEE;
  --cw-indigo-600: #4F46E5;
  --cw-violet-500: #8B5CF6;
  --cw-violet-600: #9469F7;
  --cw-plum: #431D5B;
  --cw-amber: #F59E0B;
  --cw-amber-2: #F2B342;
  --cw-stroke: #BBBBBC;
  --cw-muted: #818689;
  --cw-muted-2: #707071;
}
```

## Current Functional Surface To Preserve

Before editing, inspect these selectors/functions in `web/static/index.html`:

- Upload: `drop-zone`, `file-input`, `file-list`, `manual-accessions`,
  `manual-accessions-status`, `run-btn`, `upload-status`.
- Core settings: `project-name`, `cpus`, `target-genome`, `genefinding-mode`.
- Stage toggles: `run-genome-prep`, `run-annotation`, `run-bigscape`, `run-summary`,
  `run-clinker`, `run-figures`, `run-ecology`, `run-nplinker`.
- Advanced controls: everything inside `advanced-panel`.
- Job queue: `job-history`, `loadJob(...)`, `refreshJobHistory(...)`,
  `renderJobHistory(...)`, `markActiveJobCard(...)`.
- Progress: `stage-bar`, `.stage-step`, `initializeStageState(...)`,
  `renderStageState(...)`.
- Logs: `log-terminal`, `system-console`, `pollSystemStatus(...)`.
- Results: `results-card`, `rerun-panel`, `viz-container`, `files-container`,
  `renderViz(...)`, `renderFileTable(...)`.
- URL helpers: `apiUrl(...)`, `resultHref(...)`, `normalizedResultPath(...)`.

## Ordered Vertical Slices

Progress:

- Completed: Slice 0 - Baseline Safeguards.
- Completed: Slice 1 - Design Tokens And Page Shell.
- Completed: Slice 2 - Workflow Map.
- Completed: Slice 3 - Upload And Configuration Input Node.
- Completed: Slice 4 - Runs / Job Queue.
- Completed: Slice 5 - Worker Telemetry / Lab Console.
- Completed: Slice 6 - Results And Output Discovery.
- Completed: Slice 7 - Responsive And Accessibility Pass.
- Completed: Slice 8 - Journey-First Navigation And Hero.
- Completed: Slice 9 - User Modes And Section Hierarchy.
- Completed: Slice 10 - Neumorphic Surface System.
- Completed: Slice 11 - Retrofuturist WeaveMap And Outputs Polish.
- Superseded/deferred: Slice 12 - Final QA And Documentation. A browser screenshot check was
  run after Slice 11, but public-release QA now belongs to Slice 18.
- Completed: Slice 13 - Public API Security Foundation.
- Completed: Slice 14 - Public Input Policy, Quotas, And Retention Metadata.
- Completed: Slice 15 - Public UI Restructure.
- Completed: Slice 16 - Ecology Label Table.
- Completed: Slice 17 - Email Notifications And Retention Sweeper.
- Completed: Slice 18 - Public Deployment QA.
- Current: No remaining numbered slice. Continue with hosting-specific deployment follow-up.

Complete these slices in order. Each slice should leave the app usable.

### Slice 0: Baseline Safeguards

Goal: understand and freeze current behavior before visual refactors.

Tasks:

- Run `git status --short` and note unrelated changes.
- Read the current `index.html` structure and list all functional IDs touched by the slice.
- Add or update small regression tests only when a functional contract is changed.
- Capture a before screenshot if a browser is available.

Acceptance:

- No functional markup is deleted.
- Upload, job queue, console, results, files, and rerun panels are still reachable.

### Slice 1: Design Tokens And Page Shell

Goal: establish the ClusterWeave identity without changing workflows.

Tasks:

- Replace generic dashboard variables with `--cw-*` tokens, then map existing `--bg`,
  `--surface`, `--accent`, etc. to the new system for compatibility.
- Add a subtle scientific background: signal grid, dithered field, or woven contour using CSS
  gradients or inline SVG.
- Keep the actual app in the first viewport. Add only a compact identity band, not a landing
  page.
- Add improved focus rings and `prefers-reduced-motion` handling.

Acceptance:

- Existing layout still works.
- Page has a distinct ClusterWeave identity before deeper component work begins.

### Slice 2: Workflow Map

Goal: make the canonical pipeline visible as a living map.

Tasks:

- Convert the existing stage bar into a richer workflow map while preserving `.stage-step`
  and `data-stage` semantics.
- Stages should map to current JS keys:
  `prep`, `annotation`, `bigscape`, `summary`, `clinker`, `figures`, `nplinker`.
- Show stage number, stage name, tool hints, status state, and a micro progress mark.
- Add braided connectors using inline SVG or CSS pseudo-elements.
- Pulse only the active/running path, and disable animation with `prefers-reduced-motion`.

Acceptance:

- Existing progress semantics remain:
  green/completed, amber/current, blue/upcoming, grey/disabled, red/failed.
- `renderStageState(...)` still controls stage state.

### Slice 3: Upload And Configuration Input Node

Goal: make the upload/config panel feel like the workflow input module.

Tasks:

- Restyle drag/drop as a genome/accession intake node.
- Keep `manual-accessions`, Add, Clear, and selected input list obvious.
- Keep core settings visible: project, target genome, CPU threads, annotation strategy.
- Keep stage toggles visible but calmer.
- Rename the advanced area visually to "Advanced knobs" only if IDs and behavior are
  preserved.

Acceptance:

- Drag/drop upload still works.
- Manual accessions still create an input source and enable Run.
- All settings still feed `startAnalysis()`.

### Slice 4: Runs / Job Queue

Goal: make jobs feel like scientific run cards instead of generic history rows.

Tasks:

- Restyle `job-history` cards as compact run cards.
- Show status, project name, job ID, current stage, and small stage pips.
- Make active selection obvious and fast.
- Keep delete behavior and `loadJob(...)` intact.
- Avoid fake "BGCs detected" counts unless real result data exists.

Acceptance:

- Clicking a job updates progress/results immediately.
- Sidebar does not visually churn during passive refresh.

### Slice 5: Worker Telemetry / Lab Console

Goal: keep logs available but reduce first-impression dominance.

Tasks:

- Restyle the progress/log area as "Worker telemetry" or "Lab console".
- Keep `log-terminal`, `system-console`, Clear, and Scroll buttons.
- Add polished terminal styling: readable monospace, restrained scanline/dither texture,
  strong error/warn/success contrast.
- If adding tabs/filters, do not hide real logs permanently or break append behavior.

Acceptance:

- Logs still stream.
- Errors are easier to scan.
- Console feels secondary to the workflow map.

### Slice 6: Results And Output Discovery

Goal: make completed outputs feel like the product, not a file dump.

Tasks:

- Keep Visualization figure-only and preserve `renderViz(...)`.
- Improve figure cards with better captions and open/download affordances.
- Keep Files tab folder grouping and lazy expansion.
- Add empty states for future output concepts:
  "Priority shortlist", "Family context", "Synteny panels", "Figure gallery".
- Mark future panels as empty/pending/preview. Do not invent data.

Acceptance:

- SVG/PNG figures render inline.
- Download links still download.
- Empty states are truthful.

### Slice 7: Responsive And Accessibility Pass

Goal: make the redesigned UI usable across desktop, laptop, tablet, and narrow screens.

Tasks:

- Verify text does not overflow buttons, cards, stage nodes, or badges.
- Ensure keyboard focus is visible.
- Use semantic controls where possible: real buttons, details/summary, labels.
- Add `aria-label` only where visible labels are insufficient.
- Collapse workflow map cleanly on smaller screens.
- Honor `prefers-reduced-motion`.

Acceptance:

- No incoherent overlap at common viewport widths.
- Keyboard users can operate upload, settings, queue, tabs, and results.

### Slice 8: Journey-First Navigation And Hero

Goal: make the first viewport read as a guided ClusterWeave product shell and workflow journey,
not a panel dashboard.

Tasks:

- Replace the passive `Intake` / `Pipeline` / `Outputs` section pills with a product navigation
  shell.
- Use primary nav items: `Overview`, `Intake`, `WeaveMap`, `Runs`, `Outputs`, `QA Console`,
  `Docs`.
- Add right-side actions/status: `Load demo`, `Start run`, runtime/status chip, and `Results`.
- Make nav items anchor to sections or switch focus states in the single-page app; add visible
  active states.
- Add a responsive collapsed navigation treatment for smaller screens.
- Strengthen the wordmark: spell out `ClusterWeave`, with a small orange/teal double-helix
  crossing between the `r` and `W`.
- Replace the current hero strip with a cinematic but app-connected hero: left headline, right
  WeaveMap motif.
- Use hero copy close to:
  `Upload genomes or accessions, run canonical discovery stages, and inspect every output from annotation to gene cluster family context.`
- Add hero actions: `Start from accessions`, `Load demo run`, `View workflow map`.
- Keep the first screen operational; do not turn it into a detached marketing landing page.

Acceptance:

- A new user understands `add sources -> weave stages -> inspect outputs` within a few seconds.
- Navigation works as single-page anchors/focus states and does not break existing controls.
- Header and hero feel uniquely ClusterWeave without fake metrics or heavy animation.

### Slice 9: User Modes And Section Hierarchy

Goal: let the same page serve public demo, lab QA, and advanced/HPC users without overwhelming
the default experience.

Tasks:

- Add a visible mode switch: `Guided Demo`, `Lab QA`, `Advanced`.
- Implement modes as CSS/JS emphasis and disclosure only; preserve all controls and backend
  hooks.
- In `Guided Demo`, collapse or minimize telemetry/logs and emphasize upload, start, stage
  progress, and outputs.
- In `Lab QA`, expand worker telemetry, logs, job IDs, runtime state, errors, and artifacts.
- In `Advanced`, expose advanced knobs, optional NPLinker assets, annotation strategy, CPU
  threads, target genome, and stage switches.
- Convert upload/configuration into a cleaner `Intake node`: dropzone first, manual accessions
  beside or below, run basics below, advanced drawers after.
- Group stage switches under `Workflow controls`.
- Rename the visual label `Job Queue` to `Runs` or `Run History` while preserving existing job
  selection/loading behavior.
- Reduce console/telemetry dominance in the default mode.

Acceptance:

- Default mode feels cleaner without removing lab QA capability.
- Lab QA users can still inspect status, logs, worker state, failures, and artifacts quickly.
- Advanced controls remain available but no longer compete with first-run essentials.

### Slice 10: Neumorphic Surface System

Goal: bring in the Neumorphism part of the target style without making controls low-contrast or
toy-like.

Tasks:

- Add depth tokens for raised, inset, beveled, pressed, and glowing states.
- Limit the UI to a small set of surface types: dark page background, elevated dark panels,
  light scientific workflow/output cards, and terminal surface for logs.
- Apply tactile depth to primary panels, stage cards, run cards, upload zone, and controls.
- Use pressed/inset states for selected jobs, active nav items, selected modes, toggles, and
  checked stage switches.
- Reduce nested borders where shadows, spacing, and section bands can provide hierarchy.
- Keep borders for true structure, error states, and keyboard focus.
- Verify contrast for text, badges, focus rings, disabled controls, and inset controls.

Acceptance:

- Controls still look clickable and readable.
- Neumorphic treatment improves hierarchy rather than becoming generic glassmorphism.
- The page feels tactile and premium while remaining a serious research instrument.

### Slice 11: Retrofuturist WeaveMap And Outputs Polish

Goal: make the pipeline visualization and outputs area carry the ClusterWeave identity.

Tasks:

- Move the pipeline visualization up and make it the central visual story.
- Build or refine a prominent `WeaveMap` section with stages: `Intake`, `Prep`,
  `Annotation / BGC detection`, `BiG-SCAPE`, `Summary`, `clinker`, `Figures`, `NPLinker`,
  `Outputs`.
- Use orange/teal braided connectors throughout the workflow.
- Pulse only the active/running braid or stage.
- Add subtle dither/signal motion only where it explains state.
- Keep `prefers-reduced-motion` support.
- Add or strengthen the real `Outputs` section with cards for `Prioritized BGC shortlist`,
  `Gene cluster family context`, `Synteny / clinker panel`, `Figures`, `Artifacts / files`, and
  `NPLinker follow-up`.
- Use honest empty states: `Run a workflow to populate this panel.`, `No artifacts available yet.`,
  `NPLinker optional follow-up not enabled.`
- Keep the Visualization tab figure-only and the Files tab direct/open.
- Make console/telemetry quieter visually while keeping polling and output behavior intact.

Acceptance:

- Upload, pipeline, runs, outputs, and QA console feel connected by one visual system.
- The woven/double-helix concept is visible in the wordmark, hero, and pipeline connectors.
- Outputs are discoverable without inventing scientific results.

### Slice 12: Final QA And Documentation

Goal: prove the visual refactor did not break lab QA workflows.

Tasks:

- Run:
  - `python3 -m py_compile web/app.py web/worker.py web/canonical_pipeline.py`
  - `python3 -m unittest discover -s tests`
  - `docker compose -f docker-compose.yml config`
  - `docker compose -f clusterweave.yml config`
  - `git diff --check`
- If possible, start/rebuild the web service and manually test:
  - `/api/system/status`
  - drag/drop upload
  - manual accessions
  - Run Analysis
  - job selection
  - log streaming
  - result figure rendering
  - file open/download
  - rerun panel
- Verify nav anchors/focus states, mode switching, intake drawers, output empty states, and
  console collapse/expand behavior.
- Compare before/after screenshots if browser tooling is available.
- If browser tooling is unavailable, record that clearly and use live HTML/API checks plus the
  provided screenshot as context.

Acceptance:

- First-time user story is clear:
  upload genomes/accessions -> run workflow -> track stages -> inspect outputs.
- Lab QA story remains clear:
  worker status -> job status -> logs/errors -> files/results.
- The page no longer reads as a generic dashboard.

### Slice 13: Public API Security Foundation

Goal: make the web/API safe enough to expose behind a public web server before changing public
UI affordances.

Tasks:

- Add environment-driven public mode and auth configuration:
  `CLUSTERWEAVE_PUBLIC_MODE=1`, submit token, admin token, job read-token secret handling.
- Generate a random per-job read token at job creation and store only what the server needs to
  validate it.
- Require authorization server-side:
  - job list: admin only
  - job details/logs/files/downloads: job read token or admin
  - submit/create job: submit token or admin
  - rerun/delete: admin only
- Add anonymous redacted `/api/system/status` with only service online/offline,
  submissions open/paused, and aggregate jobs processed.
- Keep full worker telemetry/capabilities behind admin auth.
- Remove wildcard public data access. CORS and auth headers should be explicit for the hosted
  model.
- Add focused tests for unauthorized, submit-token, job-token, and admin-token behavior.
- Update docs and `web/STAN.md` if any API names differ from the plan.

Acceptance:

- Anonymous users cannot list, read, rerun, delete, log, or download any job.
- A valid per-job read token unlocks only that job.
- Admin token unlocks existing Lab QA/data-management surfaces.
- Existing local/lab behavior can still be enabled with `CLUSTERWEAVE_PUBLIC_MODE=0`.

### Slice 14: Public Input Policy, Quotas, And Retention Metadata

Goal: make public submissions constrained, honest, and operationally bounded.

Tasks:

- Enforce public accepted inputs server-side:
  - manual accessions or one-accession-per-line `.txt`
  - genome files `.fasta`, `.fa`, `.fna`, `.fsa`, `.gb`, `.gbk`, `.gbff`
  - UI-generated ecology metadata only when ecology-aware mode is enabled
- Reject public `.tsv/.csv` accession tables until the parser truly supports tabular layouts.
- Reject public `.gff`, `.gff3`, `.faa`, `.json`, `.mgf`, generic `.zip`, and unclassified
  auxiliary uploads.
- Remove or disable public NPLinker submission handling.
- Remove raw env overrides from public requests unless an admin token is used and
  `CLUSTERWEAVE_ALLOW_ENV_OVERRIDES=1`.
- Enforce env-configurable quotas:
  max accessions `25`, max genome files `25`, max individual file `250 MB`, max total upload
  `1 GB`, max queued jobs `50`, max CPU per job `8`.
- Add retention metadata on jobs: created, completed/failed, expires_at, retention days.
- Keep completed/failed retention default at 30 days via `CLUSTERWEAVE_JOB_RETENTION_DAYS=30`.
- Add tests for input rejection, quota failures, CPU clamping, and retention metadata.

Acceptance:

- Public upload policy matches the canonical workflow instead of permissive staging plumbing.
- Bad inputs fail before reaching worker execution.
- Every public job exposes an expiration date to authorized readers.

### Slice 15: Public UI Restructure

Goal: reshape the SPA around public submission and existing-run retrieval.

Tasks:

- Remove hero static weave and top-level `WeaveMap` nav.
- Simplify hero/identity band to two actions:
  `Start from NCBI accessions` and `Load demo run`.
- Rename public workflow copy from `WeaveMap` to `Workflow progress`.
- Add access key handling using `sessionStorage`; never put submit/admin tokens in URLs.
- Add Existing Run loader accepting a full result link or `job_id + read token`.
- Store unlocked runs in browser-session state and provide an `Opened runs` switcher.
- Remove public Run History. Keep Run History admin/local only.
- Remove public Lab QA mode. Show Lab QA only when admin token is present or local public mode
  is disabled.
- Remove public Advanced knobs, public stage toggles, public NPLinker, public raw env overrides,
  public rerun controls, public delete controls, and public output discovery cards.
- Move the live stage timeline inside Results above Visualization/Files.
- Before a job is loaded, Results shows:
  `Submit or load an existing run to see stage progress.`
- After submit, grey/lock Upload & Configure, collapse it, and route to Results.
- Keep `apiUrl(...)`, `resultHref(...)`, Visualization figure-only behavior, and Files
  Open/Download behavior.

Acceptance:

- Anonymous users see a public shell, submit access entry, accepted input policy, and Existing Run
  loader without job leaks.
- A loaded job-token run shows progress/results but not admin logs.
- Admin token restores operational diagnostics without a second page.

### Slice 16: Ecology Label Table

Goal: make ecology-aware analysis usable without exposing raw TSV layout.

Tasks:

- Show the ecology table only when `Enable ecology-aware analysis` is checked.
- Generate rows from pasted NCBI accessions and uploaded genome filename stems.
- Columns: `Input`, `Primary ecology`, `Secondary ecology`.
- Use dropdowns with controlled vocabulary:
  `soil`, `plant_associated`, `endophyte`, `mycorrhiza`, `plant_pathogen`, `saprotroph`,
  `marine`, `freshwater`, `lichen_associated`, `insect_associated`, `animal_associated`,
  `human_associated`, `food_fermentation`, `unknown`, `other`.
- Show a short custom text field when `other` is selected.
- Allow blanks but warn that unlabeled inputs may reduce ranking usefulness.
- Emit `ecofun_metadata_normalized.tsv` behind the scenes using canonical columns.
- Keep advanced raw metadata path/upload admin-only.

Acceptance:

- Public users never need to understand TSV schema.
- Submitted metadata keys match accession-derived genome IDs or uploaded genome filename stems.
- Ecology metadata remains optional and truthful.

### Slice 17: Email Notifications And Retention Sweeper

Goal: add antiSMASH-like result recovery while keeping storage bounded.

Tasks:

- Add optional email field only when `CLUSTERWEAVE_SMTP_ENABLED=1`.
- Store email in job metadata only; do not write email into logs.
- On completion/failure, send result link, sanitized status summary, and expiration date.
- Use the ClusterWeave email templates recorded in `web/STAN.md`, based on the fungiSMASH
  precedent but tailored to project name, input summary, workflow stages, retention, and
  citation/docs link.
- For failures, send friendly common fixes and avoid raw logs, filesystem paths, commands, env
  vars, stack traces, and worker internals.
- Implement a retention sweeper or maintenance command that removes expired uploads, logs,
  work dirs, result files, emails, and read tokens.
- Keep only aggregate counters after deletion.
- Make retention configurable; `30` days is default. Setting retention to `0` or `never` should
  require deliberate admin documentation.
- Add tests for email gating, sanitized failure payloads, expiration, and cleanup boundaries.

Acceptance:

- Users can recover results after a browser crash if email is configured or they kept the link.
- Jobs do not live forever by default.
- Sensitive metadata is deleted with the job.

### Slice 18: Public Deployment QA

Goal: prove the public hosted mode is secure, comprehensible, and operationally bounded.

Tasks:

- Run the standard checks:
  - `python3 -m py_compile web/app.py web/worker.py web/canonical_pipeline.py`
  - `python3 -m unittest discover -s tests`
  - `docker compose -f docker-compose.yml config`
  - `docker compose -f clusterweave.yml config`
  - `git diff --check`
- Add API smoke tests for anonymous, submit token, job token, and admin token flows.
- Start the local web server and capture Playwright screenshots for anonymous, submit-token,
  job-token, and admin views at desktop and mobile sizes.
- Verify:
  - anonymous cannot list/read/download jobs
  - submit token can create a job within quotas
  - read token can view only its job
  - admin can list jobs, see logs, rerun, and delete
  - public status is redacted
  - result file Open/Download still uses `resultHref(...)`
  - Visualization remains figure-only
  - upload/config locks/collapses after submit
  - no horizontal overflow on mobile
- Update `web/STAN.md` with remaining deployment questions for the hosting collaborator.

Acceptance:

- The public UI can be safely shown without exposing job data or worker internals.
- The admin path remains usable for troubleshooting.
- The collaborator handoff is complete enough for another agent to continue.

## Prompt Template For A UI Agent

Use this universal project-stamped prompt when handing off the next vertical slice to a fresh
Codex session:

```text
PROJECT STAMP
- Project: ClusterWeave
- Repo: /home/cloud/clusterweave
- UI target: web/static/index.html
- Style guide: web/STYLE.md
- Product: fungal BGC discovery and prioritization web UI
- Runtime model: shell-first canonical workflow, web UI as controller

ROLE
You are an expert frontend/UI Codex and visual designer joining ClusterWeave for one
operational vertical build slice. Work like a senior engineer and product-minded UI designer:
inspect the repository first, preserve working behavior, then make one scoped implementation.

FIRST, INSPECT
1. Run `git status --short` and note unrelated changes.
2. Read `web/STYLE.md`.
3. Read the `Current UI Evaluation`, `Journey-First Product Requirements`, `Practical
   Refinement Checklist`, and `Ordered Vertical Slices` sections closely.
4. Inspect the current `web/static/index.html` structure and the hooks used by the slice:
   IDs, event handlers, JS functions, API paths, tabs, buttons, and data attributes.
5. Inspect the current header/nav, hero, workflow map/stage bar, intake panel, job history,
   results, telemetry, console, and mode/disclosure affordances before editing.
6. Check nearby tests, especially `tests/test_repo_layout.py`.
7. Identify the next incomplete slice in `web/STYLE.md`. If the user names a slice, do that
   slice only. If no slice is named, start with the earliest incomplete slice.
8. If browser tooling is available, capture or inspect the current UI before editing. If not,
   state that browser screenshot tooling is unavailable and continue using live HTML/API checks.

MISSION
Implement exactly one vertical slice from `web/STYLE.md`:
Slice <N>: <slice name>

The current direction is journey-first:
add fungal genomes or accessions -> weave through canonical BGC stages -> inspect outputs,
synteny, family context, logs, and artifacts.

ClusterWeave should feel like a woven fungal discovery instrument: scientific, bioinformatic,
premium, readable, lightly gamified, and credible. The UI should blend Neumorphism and
Retrofuturism only in service of clarity:
- Neumorphism = tactile, pressed/raised scientific controls with strong contrast.
- Retrofuturism = restrained signal lines, status lamps, dither texture, and orange/teal
  braided workflow paths.

Do not jump straight to surface effects before the product structure is clear. The intended
sequence is:
- Slice 8: journey-first product navigation and hero.
- Slice 9: Guided Demo / Lab QA / Advanced modes and section hierarchy.
- Slice 10: Neumorphic surface system.
- Slice 11: Retrofuturist WeaveMap and Outputs polish.
- Slice 12: final QA and documentation.

NON-NEGOTIABLES
- Keep the app single-page and lightweight; edit mainly `web/static/index.html`.
- Do not add a build system, framework, package manager, or external CDN dependency.
- Preserve backend integration, uploads, manual accessions, job queue behavior, worker status,
  logs, results, file Open/Download links, figure rendering, reruns, and all API endpoints.
- Preserve all functional IDs, names, event hooks, existing form behavior, polling behavior, and
  JS integration unless a slice explicitly requires a local helper.
- Preserve `apiUrl(...)` for proxied/path-prefixed hosting.
- Preserve `resultHref(...)`: Open/preview is inline, Download requests `?download=1`.
- Preserve Visualization as figure-only:
  `Data/Results/<project>/figures/*.{svg,png,jpg,jpeg,webp}`.
- Do not invent fake scientific results, counts, scores, candidates, or QA outcomes.
- Keep accessibility and responsive behavior in scope for every visual change.
- Keep console/telemetry available for Lab QA even when the default Guided Demo view minimizes it.
- Do not turn the first screen into a detached marketing landing page; it must remain an
  operational workflow surface.

PROCESS
1. Briefly state the slice, the hooks you will touch, and the hooks you will preserve.
2. Make the smallest coherent set of edits for that slice.
3. Use the new direction as the north star:
   product shell nav, central WeaveMap, mode switch, cleaner intake node, honest outputs, quieter
   QA console, orange/teal braid motif, fewer nested borders, and stateful signal motion.
4. Use existing CSS/JS patterns unless the slice clearly requires a new local helper.
5. Add focused tests only for functional contracts or regression-prone selectors.
6. Run relevant checks. Prefer:
   - `python3 -m py_compile web/app.py web/worker.py web/canonical_pipeline.py`
   - `python3 -m unittest discover -s tests`
   - `docker compose -f docker-compose.yml config`
   - `docker compose -f clusterweave.yml config`
   - `git diff --check`
7. If a dev server/container rebuild is needed to inspect the UI, say exactly what you ran and
   what URL/port is active.
8. If screenshot tooling is unavailable, say so explicitly instead of blocking the slice.

FINAL RESPONSE
Summarize:
- Slice completed.
- Files changed.
- Functional hooks preserved.
- Checks run and results.
- Any residual risk.
- The next slice to hand off, by number and name.
```

Use this shorter prompt only when the receiving Codex already has the repo and style-guide
context loaded:

```text
You are an expert frontend/UI Codex working on ClusterWeave.

Read `web/STYLE.md` and implement only Slice <N>: <slice name>.
Use the new direction: journey-first product shell, central WeaveMap, Guided Demo / Lab QA /
Advanced modes, cleaner intake node, honest outputs, quieter QA console, orange/teal braided
connectors, and a restrained Neumorphism + Retrofuturism blend.

Keep the app single-page and lightweight: edit mainly `web/static/index.html`.
Preserve every existing functional ID, JS hook, endpoint, upload behavior, job behavior,
result rendering behavior, and rerun behavior.

ClusterWeave should feel like a woven fungal discovery instrument:
scientific, bioinformatic, premium, readable, lightly gamified, and credible. Avoid a marketing
landing page, generic dark admin dashboard, fake metrics, heavy dependencies, and childish game
language.

Before editing, inspect the current file, `Current UI Evaluation`, `Practical Refinement
Checklist`, and list the hooks this slice touches. After editing, run the relevant checks,
summarize exactly what changed, and name the next slice to hand off.
```

## Final Visual Review Questions

Ask these after every major slice:

- Does the page explain the workflow without reading documentation?
- Are upload, pipeline, queue, console, and outputs visually connected?
- Does the palette resemble the manuscript workflow more than the old dark dashboard?
- Do neumorphic surfaces clarify hierarchy without lowering contrast?
- Do retrofuturist signal lines/status lamps connect the modules into one instrument?
- Is the interface fun and alive without sacrificing scientific trust?
- Is the console still available but no longer the dominant visual object?
- Did any fake scientific result or unsupported promise sneak in?
- Did any functional ID, event hook, or API path change unintentionally?
