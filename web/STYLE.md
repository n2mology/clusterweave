# ClusterWeave Web UI Style Guide

This document is the current design and implementation handoff for future UI agents working on
`web/static/index.html` and closely related web helpers. It reflects the active board after
the Slice 26 run-surface/results restructure handoff, post-slice DNA popout and worker
runtime hardening, and the Slice 28 disclosure handoff through 2026-06-08.

ClusterWeave now has a public Results-first static SPA with server-side token gates, admin/local
lab QA tools, SMTP-ready result recovery, retention cleanup, a dynamic DNA WeaveMap, zoomable
figures, and download-only file rows.

## Vertical Slice Builder: Immersive Operational Web UI

Status: living board after the Slice 28 disclosure handoff. Slice 29 is the active closeout
slice. This section supersedes the
prototype redesign pass and the rigid neumorphism/retrofuturism layering guidance below wherever
they conflict.

Board hygiene:

- Treat `web/STYLE.md` as the living board for active and next web UI work, not as the long-term
  slice history. Keep the active slice, the next one or two planned slices, current constraints,
  and current verification/deployment instructions here.
- When a slice is completed and handed off, move its whole slice block from this file into
  `web/UI_SLICE_ARCHIVE.md`. Include any completion date, verification notes, and follow-up
  observations there. Do not leave completed slice task lists in `STYLE.md` unless a short
  pointer is needed to explain the current active slice.
- Keep `web/UI_SLICE_ARCHIVE.md` chronological enough for archaeology, but never treat archived
  slices as active direction when they conflict with this file or `web/STAN.md`.
- If a future agent is unsure whether a slice is complete, leave it in `STYLE.md` and mark the
  exact blocker or remaining verification. Once the blocker is cleared, archive it in the same
  handoff.

Baseline:

- Start from the Slice 19 functional contract, not the current prototype redesign. Treat the
  contract as a floor for backend behavior and access control, not as a visual or layout ceiling.
- Keep the web app zero-dependency: no build system, framework, package manager, or external CDN.
- Preserve the static SPA behavior and all existing IDs, input names, event handlers, JS
  functions, API paths, token flows, upload behavior, result rendering, rerun behavior, and
  admin/public access boundaries.
- Preserve `apiUrl(...)`, `apiFetch(...)`, `resultHref(...)`, `resultFetch(...)`, and
  `handleResultLinkClick(...)`.
- Existing IDs and JS hooks may be moved, wrapped, restyled, or state-gated to produce a cleaner
  product, but do not rename, delete, duplicate with conflicting behavior, or orphan them.

Design ambition and replacement posture:

- This builder is not a cosmetic polish queue. Future slices should produce a smooth, clean,
  sharp, functional, scientific, eye-catching frontend that is aware of the real backend runtime.
- Drastic layout, hierarchy, and interaction changes are encouraged when they simplify the user
  workflow, expose real options more clearly, reduce cognitive load, or replace weak structure
  instead of layering panels on top of it.
- Prefer replacing bad UI with a cleaner operational surface over preserving a poor arrangement to
  minimize diff size. Delete redundant visible surfaces before adding new ones.
- New option or layout functionality must be real: backed by existing inputs, API state, runtime
  capabilities, result metadata, or admin/public role gates. Do not invent knobs, metrics, stages,
  result categories, scientific scores, or backend states.
- Every screen should feel like a backend-aware research instrument: live service state, upload
  readiness, job-token state, progress state, result availability, and admin/public boundaries
  should drive what is visible.

Design direction:

- Build an immersive scientific operations UI, not a marketing page and not a rigid
  retro-futuristic command deck.
- Use the real ClusterWeave logo only at the top-left.
- Make the main visual a zero-dependency vertical DNA/helix spine running from the top to the
  bottom of the page. Do not slant it or make it auto-rotate. The current progress region should
  be bright; future progress should stay slightly transparent.
- Keep the teal/gold/rust palette, with the selected New Run state in orange/gold.
- Keep New Run enabled by default. New Run and Existing Run should be side tabs, not a desktop
  top rail. Existing Run hides the lower run-builder panel until valid existing-run information is
  entered.
- After submit, transition into a lift-off/progress state using real job status only, with
  `Initiating sequence. Launching ClusterWeave.` as the main confirmation copy.
- Results should be live: available artifacts appear from real job output state without a
  `Ready to see the results?` gate. Real tool outputs should branch beyond their corresponding
  workflow spine nodes; avoid a generic dashboard or CLI-output shoulder as the main results
  experience.
- Keep third-party tool and citation information in the compact disclosure/dropdown; do not
  restore a stale always-visible footer strip.
- Do not add fake metrics, public logs, public stage toggles, Files-tab Open links, stale footer
  rows, or new dependencies.

Runtime handoff:

- The hosted-analysis upload error seen during prototype review came from the ad-hoc 18082
  preview server, which was not wired to the shared Docker worker status/data runtime.
- The Docker port-80 stack had a healthy worker/runtime. Future runtime verification should use
  the actual user-facing URL, currently `http://10.64.195.209/`, after rebuilding/recreating the
  Docker `web` service.
- Do not treat port 18082 as a valid submission target unless a future slice explicitly wires it
  to the shared Docker `/data` runtime and worker status path.

After every web UI slice:

- Before final handoff, update the slice board. Completed slice specs must be moved out of
  `web/STYLE.md` and appended to `web/UI_SLICE_ARCHIVE.md`; `STYLE.md` should show only active,
  blocked, and next planned work. If the current slice remains blocked or incomplete, leave it in
  `STYLE.md` with a concrete blocker and do not archive it yet.
- Treat the slice as unfinished until both Docker services are rebuilt/recreated for the actual
  port-80 face, so `http://10.64.195.209/` shows the latest static UI and shares the current
  Docker-backed `/data` worker runtime.
- Rebuild/recreate both services, not only `web`, because `web` and `worker` must agree on runtime
  environment, shared job-data volume, and job-token secret. The repeatable dev handoff command is:

  ```bash
  export CLUSTERWEAVE_ADMIN_TOKEN=dev-admin
  export CLUSTERWEAVE_PUBLIC_BASE_URL=http://10.64.195.209/
  export HOST_PORT=80
  docker compose build --no-cache web worker
  docker compose up -d --force-recreate web worker
  ```

  Use `sudo` if the host requires it for Docker access. Every final handoff after a web UI slice
  must also show this as a copy/paste terminal command for the human operator to run, even if the
  agent already attempted the rebuild. If the build is blocked by a registry rate limit or other
  image-resolution failure, do not mark the port-80 UI as freshly rebuilt; tell the operator that
  the rebuild is blocked, provide the copy/paste command, and recommend `docker login` before
  rerunning it. A `--no-build --force-recreate` run is acceptable only to restore environment
  values such as `CLUSTERWEAVE_ADMIN_TOKEN=dev-admin`, not as proof that latest static assets are
  deployed.
- Before handing off, verify the public face and diagnostics token on port 80. `dev-admin` is the
  development diagnostics/admin access code for handoffs; do not replace it with an empty admin
  token on the dev port-80 stack.

  ```bash
  curl -fsS http://10.64.195.209/api/system/status
  curl -fsS -H 'Authorization: Bearer dev-admin' http://10.64.195.209/api/system/status
  docker compose ps web worker
  ```

- In the browser, open `http://10.64.195.209/`, use Reviewer access with `dev-admin`, and confirm
  diagnostics/admin surfaces unlock before final handoff. If the token fails, rebuild/recreate the
  port-80 stack with `CLUSTERWEAVE_ADMIN_TOKEN=dev-admin` and re-check; do not hand off a slice
  with stale frontend assets or a broken dev diagnostics token.

Skill routing for future slices:

- Use local skills only when they add leverage to the slice; do not turn every slice into a
  ceremony. The goal is faster, cleaner execution with fewer accidental regressions.
- Use `prototype` for slices with major visual, layout, or interaction uncertainty. Create
  throwaway UI variations close to the real static page, answer the design question, then delete or
  absorb the prototype before handoff.
- Use `tdd` for slices that change observable behavior, token flow, upload/result/rerun behavior,
  API payload interpretation, or public/admin gates. Add the narrowest behavior-level test or
  browser harness first, then implement one vertical tracer at a time.
- Use `diagnose` when a slice hits a runtime failure, browser breakage, stale port-80 asset,
  Docker/worker mismatch, token failure, upload failure, result-load failure, or performance
  regression. Build a deterministic loop before changing code.
- Use `improve-codebase-architecture` when a slice would otherwise add more tangled inline JS/CSS,
  duplicate state handling, or shallow helpers. Prefer small internal seams that improve locality
  while preserving the static SPA and public IDs/hooks.
- Use `zoom-out` at session start when the agent is unsure how a UI area connects to the backend,
  role model, token model, or `web/STAN.md` decisions.
- Use `grill-with-docs` only for ambiguous product/security decisions that should be resolved with
  the user and recorded in `web/STYLE.md`, `web/STAN.md`, or a future ADR-style note.

Current board:

- Completed reference: Slice 28 - Tool And Citation Disclosure.
- Active: Slice 29 - Full QA Closeout.
- Archived: completed Slice 20 through Slice 28 live in `web/UI_SLICE_ARCHIVE.md`.
- Recent hardening to preserve: the DNA-attached progress popout scrolls via real wheel events,
  remains draggable, keeps its dotted connector anchored to the popout top center, active worker
  startup recovers orphaned `running` jobs by requeueing them with `reuse_existing_layout`,
  generated tool HTML result pages keep their relative CSS/JS/image assets rendered through the
  existing token-aware `resultFetch(...)` path, live result output bubbles now render from real
  partial or complete `result_files` without a completed-run reveal gate, and the tool/citation
  credits now live in a compact in-flow disclosure.

### Slice 29 - Full QA Closeout

Goal: verify the redesigned vertical slices as one cohesive public/admin SPA.

Skill direction: use `diagnose` for any failing browser, port-80, upload, token, result, or worker
check. Use `tdd` to lock down any behavioral bug discovered during closeout before fixing it.

Tasks:

- Run the full static, unit, diff, and browser check set.
- Verify desktop, laptop/single-screen, widescreen, and mobile responsive layouts.
- Verify the actual port-80 upload flow against the Docker-backed runtime.
- Verify the full workflow has zero figure, panel, text, popover, branch-bubble, or primary-control
  collisions/layering regressions.
- Verify dev-admin management navigation after a previous run is selected, especially
  `Run History -> Results -> Intake`, at laptop/single-screen and widescreen sizes.
- Update `web/STYLE.md` and `web/STAN.md` only with observed deployment notes if behavior changed.

Preserve:

- No new dependencies.
- All functional contracts and public/admin boundaries from the Slice 19 baseline.

Acceptance:

- The redesign is visually cohesive, functionally equivalent where required, and usable on the
  actual user-facing URL.
- Public users cannot access admin-only logs, toggles, reruns, delete controls, or raw env data.
- Results, downloads, figure zoom, existing-run recovery, and rerun/admin behavior still work.
- Across workflow states, no important figure, panel, label, branch bubble, popover, CTA, nav, or
  form control is hidden behind another layer, visually colliding, or unreachable by pointer and
  keyboard.

2026-06-08 repair notes:

- Fixed dev-admin polling so `loadResults(...)` no longer forces the Results dashboard back open
  while Overview or Intake management view is intentionally open.
- Reworked result-open layout so the DNA spine stays in the left lane, output branches remain
  clickable, and the right-side result board is populated instead of a blank field.
- Limited Summary atlas to `family_atlas_shortlist.*` artifacts and renders the shortlist as a
  scrollable table/page instead of a multi-file summary browser.
- Extended the BiG-SCAPE launcher to preload the paired SQLite database into the bundled viewer
  through the existing authenticated `resultFetch(...)` path.
- Local verification passed for inline JS parse, `tests.test_repo_layout`, `git diff --check`, and
  mocked Playwright browser checks covering dev-admin Intake navigation during running-job polling,
  result branch clicks across widescreen/mobile, rendered tool HTML CSS assets, Summary atlas
  shortlist rows, and BiG-SCAPE DB autoload. The actual port-80 rebuild remains the operator
  handoff step.

Verification:

- JS parse for inline scripts in `web/static/index.html`.
- `python3 -m unittest tests.test_repo_layout`.
- `git diff --check`.
- Desktop, laptop/single-screen, widescreen, and mobile browser checks.
- Playwright screenshots plus DOM `elementFromPoint`/bounding-box checks for zero figure, panel,
  text, DNA spine, branch-bubble, popover, nav, and form-control collisions or unreachable layers
  across New Run, Existing Results, live Results, selected result bubble, figure zoom, Run
  History, Intake, and dev-admin diagnostics states.
- Explicit browser regression for `select previous job -> Results -> Intake` proving Intake is
  visible, focusable, clickable, and not hidden behind Run History in laptop/single-screen and
  widescreen layouts.
- Docker service status.
- Real port-80 submission and result recovery check.

## Corrected Agent Brief

You are an expert frontend engineer and visual designer working on ClusterWeave's static web
UI. Your task is to evolve the existing operational interface into a distinctive "woven fungal
discovery command center" while preserving every working backend integration.

ClusterWeave is a fungal biosynthetic gene cluster workflow that remains shell-first and
HPC/Singularity-aware. The web UI is now both a public hosted workflow surface and an admin/local
QA controller. Public users should understand: genomes/accessions enter the system, canonical
stages run, sanitized progress appears, and figures/files become available.

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
- Preserve token-aware `resultHref(...)`, `resultFetch(...)`, and `handleResultLinkClick(...)`.
  Figure Open/preview may be inline; Download requests `?download=1`.
- Preserve manual accession entry and submission as `manual_accessions.txt`.
- Preserve manual accession validation for NCBI assembly accessions such as
  `GCA_000011425.1` or `GCF_000001405.40`.
- Preserve same-job rerun behavior and metadata distinction between `submission_settings` and
  rerun settings.
- Visualization tab stays figure-only:
  `Data/Results/<project>/figures/*.{svg,png,jpg,jpeg,webp}`.
- Files tab keeps foldered rows with enough path context and Download only. Do not re-add
  Files-tab Open links; curated `.html` tool opens belong only in the Slice 27A/27B lollipop result
  surface.
- Console/logs remain available for lab QA, even if visually de-emphasized.
- Public/job-token views use sanitized stage events and failure summaries, not raw logs.
- Do not invent result counts, scientific scores, candidate names, or QA outcomes.

## Visual Direction

Design name: Woven Fungal Discovery Instrument.

Core idea:

- A live double-helix workflow map is the visual center.
- Upload/configuration is the input node.
- Jobs/runs move through the same canonical workflow.
- Results are the output node: progress, figures, downloadable files, and future priority
  interpretation.
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

## Current Implementation Snapshot

Public/default mode:

- Header/nav keeps the app single-page and operational with section links only; redundant
  `Start run` and `Results` header buttons are removed.
- Identity band is orientation copy only; submission and demo actions live in the entry panel.
- The entry panel has two public-facing tabs: `New run` and `Existing results`.
- `New run` is the default full-page workflow; `Existing results` opens a private
  result link or a `ClusterWeave job ID + result access code`.
- Data-use acknowledgment is required before a standard hosted submission.
- Accession intake is a draft-to-accepted workflow: users paste one accession per line, press
  `Add accessions`, and only accepted accession sources are submitted.
- Manual accessions and uploaded `.txt` accession lists are merged into one generated
  `manual_accessions.txt` workflow entry point; uploaded genome files remain separate inputs.
- Upload & Configure locks, greys, and collapses after submission.
- Results is the main run surface.
- Slice 27A replaced the completed-run dashboard/result bubbles with DNA-attached output
  lollipops for important web-facing artifacts; Slice 27B removes the remaining results gate and
  resolves branch/layout collisions.
- After submission, Results shows an inline confirmation panel with project name, job ID, visible
  result access code, private result link, copy actions, expiration, and email handoff copy when
  a completion email was supplied.
- `Workflow progress` lives inside Results above Visualization/Files.
- The active WeaveMap uses a vertical DNA spine with a DNA-attached progress popout. The popout
  receives real wheel/touch scrolling, is draggable, and keeps its dotted connector dynamically
  anchored to the popout top center. Public activity remains sanitized.
- Output discovery cards and redundant Results header panels are removed.
- Visualization is figure-only with crisp SVG zoom and raster pan/zoom.
- Files tab is foldered and download-only.
- Bottom docs ribbon is a third-party tool credit and citation prompt.

Admin/local mode:

- Run History, full logs, Lab QA console, worker telemetry, advanced knobs, stage toggles,
  rerun controls, delete, and diagnostics remain available.
- Reviewer-only access codes live behind a low-profile `Reviewer access` disclosure; public copy
  must not show `public`, `admin`, `submit token`, or `read token` labels.
- Local finalization uses two public-mode web faces over one shared backend:
  `docker-compose.local-faces.yml` runs `clusterweave-dev-web` on `18080` and
  `clusterweave-public-web` on `18081`, both mounting the original `clusterweave_job_data`,
  `clusterweave_antismash_db`, and `clusterweave_pfam_db` volumes. Do not run extra dev/public
  workers in that setup; keep `clusterweave-worker` as the single backend worker.
- Rerun Selected Stages is collapsed by default and visually separated from Results tabs.
- Admin views may show raw logs and worker state; public views must not.

Known runtime notes:

- Worker startup now recovers orphaned jobs persisted as `running` but missing from the worker
  `active_jobs` heartbeat by requeueing them with `reuse_existing_layout=1`. This prevents jobs
  from staying visually `running` forever after a worker restart. During static-only UI debugging,
  prefer recreating only `web` when an active worker job should not be interrupted; final slice
  handoff still provides the full port-80 rebuild command from this file.
- Clinker panels generated before the Docker `--workdir` fix can contain empty plot payloads.
  Rerun the clinker stage to regenerate them.
- Clinker panel readability defaults are applied by `bin/postprocess_clinker_html.py` after
  `clinker` writes `panel.html`. Standard/CLI pathing is preserved: generated `run_panel.sh`
  scripts first look for `${PROJECT_ROOT}/bin/postprocess_clinker_html.py`. Web-worker mode must
  pass the repository root separately via `run_clinker.sh --repo-root "${PROJECT_DIR}"`, allowing
  the generated script to fall back to `${REPO_ROOT}/bin/postprocess_clinker_html.py` when
  `${PROJECT_ROOT}` is a job directory such as `/data/jobs/<job_id>`.

## Public Release State After Slice 18

After browser visual review of Slice 11, the project direction changed from a lab-QA-first
controller to a public hosted web service with admin-only QA capabilities. Slices 13-18 and the
post-slice hardening pass implemented that pivot.

Implemented visual/product conclusions:

- The hero is orientation copy only; `Start from NCBI accessions` and `Load demo run` live in
  the `New run` entry panel to avoid duplicate routes.
- The static hero weave and top-level WeaveMap nav are gone.
- The live run timeline lives in Results as `Workflow progress`.
- The public Results surface is the run surface. Before a job is loaded it says:
  `Submit or load an existing run to see stage progress.`
- Once a job is submitted, Upload & Configure locks, greys, collapses, and hands the user to
  Results.
- `Run History`, full logs, reruns, worker telemetry, raw env overrides, stage toggles, and
  advanced runtime knobs are admin/local features.
- Output discovery cards are removed from Results.
- Files tab paths are text and each file row offers Download only.

Public release product/security decisions now live in `web/STAN.md`. Future agents must read it
alongside this style guide before editing.

## Public Release Product Requirements

The first public release should be a single-page scientific service, not an exposed ops console.

Public access model:

- Anonymous users may load the static UI, view redacted service status, load demo accessions
  locally, submit a new run when the server is configured for open submissions, and unlock an
  existing run by pasting a result link or `job_id + result access code`.
- Anonymous users must not list jobs, see unrelated job IDs, read logs, read files without a job
  access code, rerun jobs, or delete jobs.
- Job creation is open when `CLUSTERWEAVE_SUBMIT_TOKEN` is unset and submissions are open. If a
  submit token is configured, job creation requires that submission access code or reviewer
  diagnostics access.
- Every job gets a random per-job read token. Job details, progress, sanitized failure summaries,
  figures, files, and downloads require that read token or an admin token.
- Admin token unlocks Lab QA, job list, full logs, worker telemetry, rerun controls, delete, and
  diagnostics.
- Keep one static SPA. Role-gate the UI by token, but enforce every permission server-side.

Public workflow:

- Public pipeline is fixed and canonical. No public stage toggles.
- Public CPU/thread controls are not exposed; standard hosted submissions use the fixed
  canonical CPU budget of `8` unless the server operator changes the configured public limit.
- Public annotation strategy is not exposed. The hosted workflow submits `genefinding_mode=auto`
  with `funannotate` as the fallback order. GeneMark-dependent annotation paths are not exposed or
  enabled in the web portal.
- Standard hosted submissions require the data-use acknowledgment in the UI and server request.
- Job creation returns a private result link. The browser shows it plainly after submit and keeps
  the job ID/result access code copyable while that run is open in the tab.
- Accession sources must be one accession per non-empty line. Do not accept comma/semicolon
  separated rows, header rows, or multiple accessions on one line.
- Public intake supports:
  - manual NCBI accessions
  - one-accession-per-line `.txt` accession lists
  - genome uploads with `.fasta`, `.fa`, `.fna`, `.fsa`, `.gb`, `.gbk`, `.gbff`
  - UI-generated ecology metadata table only when ecology-aware analysis is enabled
- Do not expose NPLinker in the public WebUI for now.
- Do not expose raw env overrides in the public WebUI. Expert users who need those controls
  should run ClusterWeave locally.
- Keep `web/OPERATOR_AGREEMENT.md` current when the hosted portal adds or removes third-party
  tools, containers, or reference datasets.
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

## Retired Visual Strategy Note

The older neumorphism/retrofuturism target has been moved to `web/UI_SLICE_ARCHIVE.md`. Do not use
it as active direction when it conflicts with the immersive operational UI builder above.

## Current UI Contract
The journey-first work is implemented. Future agents should preserve this structure unless a
user explicitly requests a redesign.

Public/default hierarchy:

1. Header/nav.
2. Compact identity band and data-use/access copy.
3. Intake/configuration.
4. Results shell.
5. Results `Workflow progress` DNA spine and progress popout.
6. Live output lollipops for curated web-facing artifacts, replacing the transitional dashboard
   through Slice 27A and refined for live/collision-free layout in Slice 27B.
7. Residual downloads/full-package access.
8. Citation disclosure.

Admin/local hierarchy:

1. Public shell plus token/admin controls.
2. Run History.
3. Lab QA console and worker telemetry.
4. Workflow controls and advanced knobs.
5. Collapsible `Rerun Selected Stages`.

### Workflow Progress

The canonical workflow visual is the horizontal DNA-style WeaveMap inside Results.

It should keep:

- stage status semantics: complete, current, queued, failed, skipped
- stationary pulsing highlight on the current stage
- hover-only activity popovers
- sanitized public events from known script/log markers
- no heartbeat row
- no lower duplicate "current stage" ribbon
- no redundant input/output header cards once the helix is visible

### Results Outputs

Slice 27A replaced the transitional Visualization/Files dashboard with a lollipop output
surface. Slice 27B owns live-result display, left-rail DNA placement, and collision-free branch
layout refinements.

Figures:

- figure-only
- figure `Open` and `Download`
- scroll-wheel zoom
- keyboard zoom
- manual `-` / `+` / reset controls
- inline sanitized SVG with `viewBox` zoom

Files / fallback downloads:

- foldered/lazy tree only if still needed as fallback or admin context
- path context as text
- Download only
- no per-file Open action outside curated `.html` lollipop tool outputs

### Admin Reruns

`Rerun Selected Stages` is admin/local only, collapsed, and visually indented from the
Visualization/Files tabs.

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

Carry these constraints through future implementation passes:

- Security/API first, then UI. Do not hide an unsafe endpoint behind CSS.
- Keep server-side permission enforcement for anonymous/open-submit, invite-only submit-token,
  read-token, and admin roles.
- Keep anonymous `/api/system/status` redacted.
- Keep quotas and retention metadata aligned with public copy.
- Keep one static SPA.
- Keep public `Workflow progress` naming; reserve `WeaveMap` as an internal motif/class name.
- Keep Upload & Configure lock/collapse after submit.
- Keep public Run History, Lab QA, Advanced knobs, stage toggles, NPLinker, rerun, delete, and raw
  env overrides hidden unless admin/local mode unlocks them.
- Keep output discovery cards removed from public Results.
- Keep Existing Run loader and browser-session unlocked-run list.
- Keep ecology label table only when ecology-aware analysis is enabled.
- Keep Files tab download-only.
- Keep public copy explicit about accepted inputs, filename hygiene, retention, result-link
  privacy, and local Docker for sensitive work.
- Keep clinker Docker `--workdir "${SCRIPT_DIR}"` in generated panel scripts.

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

- Access/public auth: `access-panel`, `submit-token`, `admin-token`, `existing-run-link`,
  `existing-run-token`, `opened-runs-select`, `saveAccessTokens(...)`,
  `rememberOpenedRun(...)`.
- Upload: `drop-zone`, `file-input`, `file-list`, `manual-accessions`,
  `manual-accessions-status`, `run-btn`, `upload-status`, `data-use-ack`.
- Email: `email-notification-panel`, `notify-email`, `smtpEnabled`.
- Ecology table: `run-ecology`, `ecology-label-panel`, `metadata-table-body`,
  `ECOLOGY_LABELS`, `buildEcologyMetadataText(...)`.
- Core settings: `project-name`, `cpus`, `target-genome`, `genefinding-mode`.
- Admin/local stage toggles: `run-genome-prep`, `run-annotation`, `run-bigscape`,
  `run-summary`, `run-clinker`, `run-figures`, `run-ecology`, `run-nplinker`.
- Advanced controls: everything inside `advanced-panel`.
- Job queue: `job-history`, `loadJob(...)`, `refreshJobHistory(...)`,
  `renderJobHistory(...)`, `markActiveJobCard(...)`.
- Progress: `weavemap`, `weavemap-helix`, `stage-bar`, `.stage-step`,
  `initializeStageState(...)`, `renderStageState(...)`, `renderWeaveHelix(...)`,
  `publicStageNodes(...)`, `mergeWeaveActivityEvents(...)`.
- Logs: `log-terminal`, `system-console`, `pollSystemStatus(...)`.
- Results: `results-card`, `rerun-panel`, `viz-container`, `files-container`,
  `renderViz(...)`, `renderFileTable(...)`.
- Figure zoom: `figure-preview-wrap`, `figure-svg-stage`, `figure-svg-preview`,
  `figure-zoom-controls`, `handleFigureWheel(...)`, `zoomFigureControl(...)`,
  `hydrateSvgFigures(...)`.
- URL helpers: `apiUrl(...)`, `apiFetch(...)`, `resultHref(...)`, `resultFetch(...)`,
  `handleResultLinkClick(...)`, `normalizedResultPath(...)`.

## Historical Slice Archive

Old slice maps, completed slice specs, deployment verification notes, and retired prompt
templates now live in `web/UI_SLICE_ARCHIVE.md`. They are preserved for archaeology and
regression context only. Current UI handoffs should start from `Next Vertical Slice Builder:
Immersive Operational Web UI` above, plus `web/STAN.md` for public-service and deployment policy.
When a slice is completed, move its full block to the archive instead of leaving historical task
lists in this living board.
