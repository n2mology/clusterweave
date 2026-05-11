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
- Next: Slice 6 - Results And Output Discovery.

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

### Slice 8: Final QA And Documentation

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
- Compare before/after screenshots.

Acceptance:

- First-time user story is clear:
  upload genomes/accessions -> run workflow -> track stages -> inspect outputs.
- Lab QA story remains clear:
  worker status -> job status -> logs/errors -> files/results.
- The page no longer reads as a generic dashboard.

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
operational vertical build slice. Work like a senior engineer: inspect the repository first,
preserve working behavior, then make a scoped implementation.

FIRST, INSPECT
1. Run `git status --short` and note unrelated changes.
2. Read `web/STYLE.md`.
3. Inspect the current `web/static/index.html` structure and the hooks used by the slice:
   IDs, event handlers, JS functions, API paths, tabs, buttons, and data attributes.
4. Check nearby tests, especially `tests/test_repo_layout.py`.
5. Identify the next incomplete slice in `web/STYLE.md`. If the user names a slice, do that
   slice only. If no slice is named, start with the earliest incomplete slice.

MISSION
Implement exactly one vertical slice from `web/STYLE.md`:
Slice <N>: <slice name>

ClusterWeave should feel like a woven fungal discovery command center: scientific,
bioinformatic, premium, readable, and credible. The redesign should move away from a generic
dark admin dashboard, but it must remain an operational research instrument.

NON-NEGOTIABLES
- Keep the app static; edit mainly `web/static/index.html`.
- Do not add a build system, framework, package manager, or external CDN dependency.
- Preserve backend integration, uploads, manual accessions, job queue behavior, worker status,
  logs, results, file Open/Download links, figure rendering, reruns, and all API endpoints.
- Preserve `apiUrl(...)` for proxied/path-prefixed hosting.
- Preserve `resultHref(...)`: Open/preview is inline, Download requests `?download=1`.
- Preserve Visualization as figure-only:
  `Data/Results/<project>/figures/*.{svg,png,jpg,jpeg,webp}`.
- Do not invent fake scientific results, counts, scores, candidates, or QA outcomes.
- Keep accessibility and responsive behavior in scope for every visual change.

PROCESS
1. Briefly state the slice, the hooks you will touch, and the hooks you will preserve.
2. Make the smallest coherent set of edits for that slice.
3. Use existing CSS/JS patterns unless the slice clearly requires a new local helper.
4. Add focused tests only for functional contracts or regression-prone selectors.
5. Run relevant checks. Prefer:
   - `python3 -m py_compile web/app.py web/worker.py web/canonical_pipeline.py`
   - `python3 -m unittest discover -s tests`
   - `docker compose -f docker-compose.yml config`
   - `docker compose -f clusterweave.yml config`
   - `git diff --check`
6. If a dev server/container rebuild is needed to inspect the UI, say exactly what you ran and
   what URL/port is active.

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
Keep the app static: edit mainly `web/static/index.html`.
Preserve every existing functional ID, JS hook, endpoint, upload behavior, job behavior,
result rendering behavior, and rerun behavior.

ClusterWeave should feel like a woven fungal discovery command center:
scientific, bioinformatic, premium, readable, and credible. Avoid a marketing landing page,
generic dark admin dashboard, fake metrics, heavy dependencies, and childish game language.

Before editing, inspect the current file and list the hooks this slice touches.
After editing, run the relevant checks, summarize exactly what changed, and name the next
slice to hand off.
```

## Final Visual Review Questions

Ask these after every major slice:

- Does the page explain the workflow without reading documentation?
- Are upload, pipeline, queue, console, and outputs visually connected?
- Does the palette resemble the manuscript workflow more than the old dark dashboard?
- Is the interface fun and alive without sacrificing scientific trust?
- Is the console still available but no longer the dominant visual object?
- Did any fake scientific result or unsupported promise sneak in?
- Did any functional ID, event hook, or API path change unintentionally?
