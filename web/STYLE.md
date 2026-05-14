# ClusterWeave Web UI Style Guide

This document is the current design and implementation handoff for future UI agents working on
`web/static/index.html` and closely related web helpers. It reflects the state after Slice 18 plus
post-slice UI/runtime hardening on 2026-05-12.

ClusterWeave now has a public Results-first static SPA with server-side token gates, admin/local
lab QA tools, SMTP-ready result recovery, retention cleanup, a dynamic DNA WeaveMap, zoomable
figures, and download-only file rows.

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
  Files-tab Open links.
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
- The entry panel has two public-facing tabs: `NEW RUN` and `RESULTS FROM EXISTING RUN`.
- `NEW RUN` is the default full-page workflow; `RESULTS FROM EXISTING RUN` opens a private
  result link or a `ClusterWeave job ID + result access code`.
- Data-use acknowledgment is required before a standard hosted submission.
- Accession intake is a draft-to-accepted workflow: users paste one accession per line, press
  `Add accessions`, and only accepted accession sources are submitted.
- Manual accessions and uploaded `.txt` accession lists are merged into one generated
  `manual_accessions.txt` workflow entry point; uploaded genome files remain separate inputs.
- Upload & Configure locks, greys, and collapses after submission.
- Results is the main run surface.
- After submission, Results shows an inline confirmation panel with project name, job ID, visible
  result access code, private result link, copy actions, expiration, and email handoff copy when
  a completion email was supplied.
- `Workflow progress` lives inside Results above Visualization/Files.
- The public WeaveMap is a horizontal DNA-style double helix with sanitized hover activity nodes.
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

Known runtime note:

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
  the `NEW RUN` entry panel to avoid duplicate routes.
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

## Current UI Contract

The journey-first work is implemented. Future agents should preserve this structure unless a
user explicitly requests a redesign.

Public/default hierarchy:

1. Header/nav.
2. Compact identity band and data-use/access copy.
3. Intake/configuration.
4. Results shell.
5. Results `Workflow progress` double-helix map.
6. Visualization and Files tabs.
7. Citation strip.

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

### Visualization And Files

Visualization:

- figure-only
- figure `Open` and `Download`
- scroll-wheel zoom
- keyboard zoom
- manual `-` / `+` / reset controls
- inline sanitized SVG with `viewBox` zoom

Files:

- foldered/lazy tree
- path context as text
- Download only
- no per-file Open action

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
- Completed post-slice hardening:
  - SMTP/public-link env passthrough on both `web` and `worker`.
  - Manual accession validation in UI/API.
  - Non-retryable NCBI accession-not-found retry policy.
  - Public-safe DNA WeaveMap with hover activity popovers.
  - Redundant output/header cards removed from Results.
  - Crisp SVG figure zoom and fixed zoom controls.
  - Collapsible admin rerun panel.
  - Download-only Files tab.
  - Clinker Docker `--workdir "${SCRIPT_DIR}"` panel-generation fix.
  - Clinker HTML postprocess helper resolution for web-worker mode: `run_clinker.sh` passes
    `--repo-root "${PROJECT_DIR}"`, while generated `run_panel.sh` preserves
    `${PROJECT_ROOT}/bin/postprocess_clinker_html.py` as the first-choice CLI path and falls back
    to `${REPO_ROOT}/bin/postprocess_clinker_html.py`.
- Completed deployment verification:
  - Deployment Slice A - Fresh Canonical Run, verified locally on 2026-05-14.
  - Deployment Slice B - Existing Results / Recovery Pass, verified locally on 2026-05-14.
  - Deployment Slice C - Email / SMTP Pass, verified locally in SMTP outbox mode on 2026-05-14.
  - Deployment Slice D - Host Cutover, verified on the port-80 LAN face on 2026-05-14.
- Current: Deployment Slice E - Reverse Proxy / Security Envelope.

Historical slices are kept below for context. New work should use the current contract above and
the deployment verification queue here plus `web/STAN.md`, not restart old completed slices.

## Deployment Verification Queue

These are not new UI redesign slices. They are release-readiness handoff slices for Stan or a
future ClusterWeave web/deployment agent. Complete one at a time and update both `web/STYLE.md`
and `web/STAN.md` with any changed operational agreement.

### Deployment Slice A: Fresh Canonical Run

Status: completed locally on 2026-05-14.

Goal: validate the rebuilt one-backend/two-web-face system with a real public-mode canonical job.

Tasks:

- Submit a fresh public-mode job through `http://127.0.0.1:18081/` or the current public face.
- Exercise accession prep, canonical workflow execution, public WeaveMap activity, figure loading,
  SVG zoom, Files downloads, and private result-link retrieval.
- Confirm regenerated Clinker `panel.html` files open with readability-first defaults:
  scale factor `12`, vertical spacing `70`, hidden locus coordinates, visible gene labels,
  similarity-group colors, and visible link labels.
- Confirm the rebuilt `clusterweave-worker` is the only worker and that both local web faces share
  the original `clusterweave_job_data` backend volume.

Acceptance:

- The new run completes or fails with a sanitized, useful public failure summary.
- Result links and downloads work from the public face.
- Newly regenerated Clinker panels are readable by default.

Verification notes:

- Fresh public-mode accession run submitted through `http://127.0.0.1:18081/` completed
  successfully against the single `clusterweave-worker` backend and shared
  `clusterweave_job_data` volume.
- Public progress events covered accession fetch, antiSMASH, FunBGCeX, BiG-SCAPE, summary,
  clinker, and figures without exposing raw logs in the public result payload.
- Result-link loading, token-gated SVG figure fetch, SVG zoom, Files-tab Download-only behavior,
  and a small token-gated file download were verified.
- Regenerated clinker atlas panels were verified with scale factor `12`, spacing `70`, hidden
  locus coordinates, visible gene labels, similarity-group colors, and visible link labels.
- A compact Playwright-generated demo video and verification screenshots were produced under
  `/tmp` for operator review; do not treat those temporary artifacts as release assets.

### Deployment Slice B: Existing Results / Recovery Pass

Status: completed locally on 2026-05-14.

Goal: prove users can recover a run after leaving the initial browser state.

Tasks:

- Verify `RESULTS FROM EXISTING RUN` with private result links.
- Verify job ID plus result access code lookup.
- Verify `Recent results in this tab` behavior.
- Verify diagnostics/reviewer access unlocks admin controls without a page refresh.

Acceptance:

- A non-admin user can recover only authorized results.
- Diagnostics/admin controls unlock only with the configured admin token.
- Public copy avoids `public`, `admin`, `submit token`, and `read token` labels outside the
  low-profile reviewer access disclosure.

Verification notes:

- Browser verification against `http://127.0.0.1:18081/` used a temporary tiny recovery probe job
  with a normal result access code returned by the API; no result access code or private result
  link is recorded in this handoff.
- Fresh browser contexts recovered the run from both a full private result link and a
  `ClusterWeave job ID + result access code` lookup.
- `Recent results in this tab` populated after unlock, persisted across a same-tab reload through
  `sessionStorage`, and could reload the run from the selector.
- Anonymous reads, wrong result codes, and job-list requests with only a result access code were
  rejected; the valid result access code could read only its own job.
- Reviewer diagnostics access unlocked Run History and QA Console without a page refresh or URL
  change, while read-token-only recovery kept admin-only controls hidden.
- Closed public surface verification found no `admin token`, `submit token`, or `read token`
  wording; the low-profile Reviewer access disclosure keeps the expected submission and
  diagnostics access-code labels.

### Deployment Slice C: Email / SMTP Pass

Status: completed locally in SMTP outbox mode on 2026-05-14. Live-provider SMTP still needs final
provider, sender-policy, and public-URL confirmation.

Goal: verify result recovery by email before public release.

Tasks:

- First run SMTP in outbox mode if provider credentials are not ready.
- After Stan confirms provider, sender policy, and public URL, run one live-provider SMTP test.
- Confirm completion/failure emails include project name, job ID, result access code, private
  result link, expiration date, citation/help copy, and sanitized failure guidance when relevant.
- Confirm `CLUSTERWEAVE_PUBLIC_BASE_URL` matches the URL users actually open.

Acceptance:

- Email recovery works without leaking logs, paths, commands, env vars, stack traces, or worker
  internals.
- `web` and `worker` share the same stable `CLUSTERWEAVE_JOB_TOKEN_SECRET`.

Verification notes:

- Local `clusterweave-public-web` and the single `clusterweave-worker` were rebuilt and recreated
  with `CLUSTERWEAVE_SMTP_ENABLED=1`, `CLUSTERWEAVE_SMTP_OUTBOX_DIR=/data/smtp-outbox`,
  `CLUSTERWEAVE_PUBLIC_BASE_URL=http://127.0.0.1:18081/`, and the same local
  `CLUSTERWEAVE_JOB_TOKEN_SECRET`.
- Public status reported `smtp_enabled: true`; the optional completion email field was visible in
  the public UI.
- A successful outbox notification and a failed-job outbox notification were generated through the
  worker and verified in fresh browser contexts. Both private result links recovered the target
  run without diagnostics access.
- Success and failure emails included project name, job ID, explicit result access code, private
  result link, expiration/retention copy, and citation/help link.
- Failure email included sanitized failed stage, likely issue, and suggested fixes, without raw
  logs, filesystem paths, commands, env vars, stack traces, or worker internals.
- `web/notifications.py` now emits explicit `Recovery details` with the result access code and
  includes citation/help copy in failure emails as well as success emails.
- Live-provider SMTP was not run because the provider, sender policy, credentials, and final public
  URL have not been confirmed.

### Deployment Slice D: Host Cutover

Status: completed on the port-80 LAN face on 2026-05-14. DNS/TLS/reverse-proxy hardening remains
in Slice E.

Goal: move from local verification ports to the real public face.

Tasks:

- Restore the public face to port `80` / `http://10.64.195.209/` or the final DNS name.
- Keep one real backend worker and one shared `clusterweave_job_data` volume.
- Confirm `CLUSTERWEAVE_PUBLIC_BASE_URL` points at the final origin with a trailing slash.
- Confirm the public web face is internet/LAN-facing and the worker is not.

Acceptance:

- The final public URL loads the public UI and submits to the same backend validated locally.
- No extra public/dev worker or duplicate job-data volume is introduced.

Verification notes:

- `docker-compose.yml` now passes through the public-mode auth, quota, retention, CORS,
  public-base-URL, citation, and SMTP environment contract for the port-80 `web` service. The
  worker keeps the matching public base URL, job token secret, retention, citation, and SMTP
  notification env contract.
- The port-80 face was recreated from the current image with
  `CLUSTERWEAVE_PUBLIC_MODE=1`, `CLUSTERWEAVE_PUBLIC_BASE_URL=http://10.64.195.209/`, open
  submissions, SMTP disabled, and a matching local `CLUSTERWEAVE_JOB_TOKEN_SECRET` shared with the
  single backend worker.
- The temporary `18080`/`18081` local verification faces were stopped after cutover. Running
  containers were reduced to `clusterweave-web` on `0.0.0.0:80` and one `clusterweave-worker`.
- Docker mount verification confirmed both `clusterweave-web` and `clusterweave-worker` use the
  shared `clusterweave_job_data` volume. The worker has no published ports.
- Browser verification against `http://10.64.195.209/` confirmed the public UI loads, anonymous
  status remains redacted, diagnostics status sees an idle worker, and the email field is hidden
  while live SMTP is unconfigured.
- A tiny diagnostics-authenticated cutover probe submitted through `http://10.64.195.209/`
  completed successfully on the shared backend. The returned private result link used
  `http://10.64.195.209/#/job/...` and opened in a fresh public browser context.
- A full non-admin public canonical rerun was not repeated during cutover to avoid launching
  another heavy workload; that path was verified in Deployment Slice A.

### Deployment Slice E: Reverse Proxy / Security Envelope

Status: in progress; initial LAN probe on 2026-05-14 found this slice not yet acceptable.

Goal: align the host perimeter with ClusterWeave's public-service quotas and token model.

Tasks:

- Confirm DNS, TLS termination, and reverse-proxy target.
- Align reverse-proxy body-size limits with `CLUSTERWEAVE_MAX_UPLOAD_FILE_MB` and
  `CLUSTERWEAVE_MAX_UPLOAD_TOTAL_MB`.
- Add or confirm rate limits suitable for open submissions.
- Confirm secret injection method for admin token, job token secret, SMTP credentials, and any
  invite-only submit token.
- Launch temporarily disables anonymous open submission by using invite-only submit access.
  `web/STAN.md` must explain how to unlock anonymous open submission after Slice E passes.

Acceptance:

- Public requests are bounded before and inside the app.
- Secrets live in the host secret store/environment, not in source or handoff docs.

Verification notes:

- LAN probes against `http://10.64.195.209/` still reached the Python web app directly on host
  port `80`; the response advertised `ClusterWeaveHTTP/2.0 Python/3.11.15`, and host listener
  checks found no `443` listener.
- `https://10.64.195.209/` failed to connect, so DNS/TLS termination and HTTPS result-link
  behavior remain unverified.
- The public status endpoint was redacted, but still reported open submissions. Running
  environment probes showed `CLUSTERWEAVE_SUBMIT_TOKEN` empty, so the temporary invite-only launch
  posture is not active.
- Current app quotas are present in the container environment, but no reverse proxy is yet in
  front of the app to enforce matching request body limits or rate limits before requests reach
  Python.
- Do not mark Slice E complete until a host-managed reverse proxy terminates TLS, forwards to the
  web service, applies upload/rate limits aligned with the ClusterWeave quotas, and secrets are
  injected from the host secret store with open submissions temporarily gated by a submit access
  code.

### Deployment Slice F: Final Visual QA And Handoff

Goal: capture the release state and leave Stan with a trustworthy operational handoff.

Tasks:

- Capture desktop/mobile screenshots for public new run, existing-run lookup, loaded results,
  failed-job summary, and diagnostics/admin view.
- Replace the future citation placeholder with the final DOI/citation URL if available.
- Update `web/STAN.md` with final host URLs, environment expectations, known risks, and operator
  commands.
- Run the relevant focused tests and record what was actually verified.

Acceptance:

- The public UI can be handed off without hidden local-only assumptions.
- Remaining risks are explicit, dated, and owned.



Original UI adjustmentS below in numbered slices made to Stan's initial handoff (ALL COMPLETED):

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
- Keep public core settings to project and optional target genome. CPU threads, annotation
  strategy, and stage toggles are admin/local or diagnostics-unlocked controls only.
- Keep admin/local stage toggles visible but calmer.
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
- Keep Files tab folder grouping and lazy expansion. Current public contract is Download only.
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
- Keep right-side header status to runtime only. Start and Results actions are redundant with
  `NEW RUN` and the `Outputs` nav item.
- Make nav items anchor to sections or switch focus states in the single-page app; add visible
  active states.
- Add a responsive collapsed navigation treatment for smaller screens.
- Strengthen the wordmark: spell out `ClusterWeave`, with a small orange/teal double-helix
  crossing between the `r` and `W`.
- Replace the current hero strip with a cinematic but app-connected hero: left headline, right
  WeaveMap motif.
- Use hero copy close to:
  `Upload genomes or accessions, run canonical discovery stages, and inspect every output from annotation to gene cluster family context.`
- Keep the hero as orientation copy; avoid duplicate hero actions now that the entry panel owns
  `Start from NCBI accessions` and `Load demo run`.
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
- Keep the Visualization tab figure-only. Current Files tab contract is Download only.
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
  `CLUSTERWEAVE_PUBLIC_MODE=1`, optional submit token, admin token, job read-token secret
  handling.
- Generate a random per-job read token at job creation and store only what the server needs to
  validate it.
- Require authorization server-side:
  - job list: admin only
  - job details/logs/files/downloads: job read token or admin
  - submit/create job: open when no submit token is configured; otherwise submit token or admin
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
- Simplify hero/identity band to orientation copy only; keep `Start from NCBI accessions` and
  `Load demo run` in the `NEW RUN` entry panel.
- Rename public workflow copy from `WeaveMap` to `Workflow progress`.
- Add access key handling using `sessionStorage`; never put submit/admin tokens in URLs.
- Replace the old visible access-key panel with `NEW RUN` and `RESULTS FROM EXISTING RUN` tabs.
- Add Existing Run loader accepting a full result link or `job_id + result access code`.
- Store unlocked runs in browser-session state and provide a `Recent results in this tab`
  switcher.
- Keep submission and diagnostics codes behind a `Reviewer access` disclosure for hosted QA.
- Remove public Run History. Keep Run History admin/local only.
- Remove public Lab QA mode. Show Lab QA only when admin token is present or local public mode
  is disabled.
- Remove public Advanced knobs, public stage toggles, public NPLinker, public raw env overrides,
  public rerun controls, public delete controls, and public output discovery cards.
- Move the live stage timeline inside Results above Visualization/Files.
- Before a job is loaded, Results shows:
  `Submit or load an existing run to see stage progress.`
- After submit, grey/lock Upload & Configure, collapse it, and route to Results.
- Keep `apiUrl(...)`, `resultHref(...)`, Visualization figure-only behavior, figure
  Open/Download behavior, and Files Download-only behavior.

Acceptance:

- Anonymous users see accepted input policy, data-use acknowledgment, `NEW RUN`, and
  `RESULTS FROM EXISTING RUN` without job leaks or role/token labels.
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
- Add API smoke tests for anonymous/open-submit, invite-only submit-token, job token, and admin
  token flows.
- Start the local web server and capture Playwright screenshots for standard new-run,
  existing-run, job-token, and reviewer/admin views at desktop and mobile sizes.
- Verify:
  - anonymous cannot list/read/download jobs
  - open submission can create a job within quotas when no submit token is configured
  - invite-only submit token can create a job within quotas when configured
  - read token can view only its job
  - admin can list jobs, see logs, rerun, and delete
  - public status is redacted
  - figure Open/Download and Files Download still use `resultHref(...)`
  - Visualization remains figure-only
  - upload/config locks/collapses after submit
  - no horizontal overflow on mobile
- Update `web/STAN.md` with remaining deployment questions for the hosting collaborator.

Acceptance:

- The public UI can be safely shown without exposing job data or worker internals.
- The admin path remains usable for troubleshooting.
- The collaborator handoff is complete enough for another agent to continue.

## Prompt Template For A UI Agent

Use this prompt when handing off future ClusterWeave web work to a fresh Codex session:

```text
PROJECT STAMP
- Project: ClusterWeave
- Repo: /home/cloud/clusterweave
- UI target: web/static/index.html
- Style guide: web/STYLE.md
- Operational handoff: web/STAN.md
- Product: fungal BGC discovery and prioritization web UI
- Runtime model: shell-first canonical workflow, static SPA as controller

ROLE
You are an expert frontend/UI Codex and product-minded visual designer joining ClusterWeave.
Work like a senior engineer: inspect first, preserve working behavior, then make one scoped
implementation that matches the current public-service direction.

FIRST, INSPECT
1. Run `git status --short` and note unrelated changes.
2. Read `web/STYLE.md` and `web/STAN.md`.
3. Inspect the current `web/static/index.html` structure and any backend helper touched by the
   request.
4. Identify functional hooks involved: IDs, event handlers, JS functions, API paths, auth roles,
   tabs, buttons, and data attributes.
5. Check nearby tests, especially `tests/test_repo_layout.py`, `tests/test_web_api_auth.py`,
   `tests/test_public_stage_sanitizer.py`, and helper-specific tests.
6. If browser tooling is available, capture or inspect the current UI before editing. If not,
   state that browser screenshot tooling is unavailable and continue using live HTML/API checks.

MISSION
Implement exactly the requested change or the next explicit hosting/deployment follow-up from
`web/STAN.md`. There are no remaining numbered UI slices. If the user says "next slice" without
details, choose the highest-priority deployment follow-up documented in STAN, or ask one concise
question if the next step depends on host-specific information.

ClusterWeave should feel like a woven fungal discovery instrument: scientific, bioinformatic,
premium, readable, lightly gamified, and credible. The UI should blend Neumorphism and
Retrofuturism only in service of clarity:
- Neumorphism = tactile, pressed/raised scientific controls with strong contrast.
- Retrofuturism = restrained signal lines, status lamps, dither texture, and orange/teal
  braided workflow paths.

CURRENT UI CONTRACT
- Public/default UI is Results-first and hides Lab QA/admin surfaces.
- Server-side auth is the source of truth; never rely on CSS hiding for security.
- Public workflow is fixed and canonical.
- The Results `Workflow progress` surface uses the horizontal DNA double-helix WeaveMap.
- Public activity popovers use sanitized events only.
- Visualization is figure-only.
- Figure cards may Open/Download; Files tab is Download only.
- SVG figures hydrate inline and zoom by viewBox.
- Reruns are admin/local only and live in a collapsible panel.
- SMTP/email is optional and visible only when configured.
- Clinker Docker panel scripts must set `--workdir "${SCRIPT_DIR}"`.
- Clinker postprocessing must not break standard non-web usage: preserve
  `${PROJECT_ROOT}/bin/postprocess_clinker_html.py` as the first-choice generated path and add
  web-specific repo-root fallback behavior separately.

NON-NEGOTIABLES
- Keep the app single-page and lightweight; edit mainly `web/static/index.html`.
- Do not add a build system, framework, package manager, or external CDN dependency.
- Preserve `apiUrl(...)`, `apiFetch(...)`, auth headers, `resultHref(...)`, and `resultFetch(...)`.
- Preserve token handling in `sessionStorage`; do not put submit/admin tokens in URLs.
- Preserve public/server-side auth boundaries for anonymous/open-submit, invite-only
  submit-token, read-token, and admin.
- Preserve manual accessions as `manual_accessions.txt` and validate NCBI assembly format.
- Preserve public input policy, quotas, retention, email redaction, and sanitized failures.
- Preserve admin/local job history, logs, telemetry, reruns, delete, and advanced knobs.
- Preserve Visualization as figure-only:
  `Data/Results/<project>/figures/*.{svg,png,jpg,jpeg,webp}`.
- Do not re-add Files-tab Open links.
- Do not invent fake scientific results, counts, scores, candidates, or QA outcomes.
- Keep accessibility and responsive behavior in scope for every visual change.

PROCESS
1. Briefly state the change, the hooks you will touch, and the hooks you will preserve.
2. Make the smallest coherent set of edits.
3. Use existing CSS/JS patterns unless the change clearly requires a local helper.
4. Keep current public-service structure as the north star.
5. Add focused tests only for functional contracts or regression-prone selectors.
6. Run relevant checks. Prefer:
   - `python3 -m py_compile web/app.py web/worker.py web/canonical_pipeline.py`
   - `python3 -m py_compile bin/*.py scripts/ncbi/*.py`
   - `python3 -m unittest discover -s tests`
   - `docker compose -f docker-compose.yml config`
   - `docker compose -f clusterweave.yml config`
   - `git diff --check`
7. If a dev server/container rebuild is needed to inspect the UI, say exactly what you ran and
   what URL/port is active.
8. If screenshot tooling is unavailable, say so explicitly instead of blocking the slice.

FINAL RESPONSE
Summarize:
- What changed.
- Files changed.
- Functional hooks preserved.
- Checks run and results.
- Any residual risk.
- The next handoff item from STAN.
```

Use this shorter prompt only when the receiving Codex already has the repo and style-guide
context loaded:

```text
You are an expert frontend/UI Codex working on ClusterWeave.

Read `web/STYLE.md` and `web/STAN.md`, inspect the repo, and implement the requested single
change. Preserve the current public-service contract: token-gated API, Results-first UI, DNA
Workflow progress, figure-only Visualization, download-only Files tab, admin-only QA/reruns,
optional SMTP, retention, and sanitized public events.

Keep the app single-page and lightweight: edit mainly `web/static/index.html`.
Preserve every existing functional ID, JS hook, endpoint, upload behavior, job behavior,
result rendering behavior, and rerun behavior.

ClusterWeave should feel like a woven fungal discovery instrument:
scientific, bioinformatic, premium, readable, lightly gamified, and credible. Avoid a marketing
landing page, generic dark admin dashboard, fake metrics, heavy dependencies, and childish game
language.

Do not re-add Files Open links, output discovery cards, public logs, public stage toggles,
public NPLinker controls, fake metrics, or marketing-page structure. Run focused tests and
browser checks where relevant, then name the next deployment handoff item.
```

## Final Visual Review Questions

Ask these after every major UI change:

- Does the page explain the workflow without reading documentation?
- Does public mode hide admin/QA surfaces without relying on UI hiding for security?
- Are intake, workflow progress, Visualization, Files, and citation visually connected?
- Does the double-helix WeaveMap scale without overflow?
- Are hover popovers useful, stable, and sanitized?
- Do SVG and raster figure zoom both work?
- Does Files show Download only?
- Does the palette resemble the manuscript workflow more than the old dark dashboard?
- Do neumorphic surfaces clarify hierarchy without lowering contrast?
- Do retrofuturist signal lines/status lamps connect the modules into one instrument?
- Is the interface fun and alive without sacrificing scientific trust?
- Is the console still available but no longer the dominant visual object?
- Did any fake scientific result or unsupported promise sneak in?
- Did any functional ID, event hook, auth boundary, or API path change unintentionally?
