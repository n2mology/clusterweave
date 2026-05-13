# ClusterWeave Web Handoff For STAN

This file is an internal collaborator and AI-agent handoff for the ClusterWeave web UI and public
deployment. It is written for the web-hosting/bioinformatics collaborator who originally
scaffolded the web UI and for future agents continuing deployment or maintenance work.

Do not store secrets here. Do not commit real tokens, SMTP credentials, VM IPs, private URLs, or
submitted job links. Use environment variable names and deployment notes only.

## Why This File Exists

The original web UI was built as a functional shell-first controller for ClusterWeave. During the
most recent UI work, the interface was substantially improved visually and ergonomically, but the
project direction also changed:

- Earlier work optimized for lab QA and local operator visibility.
- Slices 13-18 pivoted the app to a public hosted service with admin-only QA.
- Post-slice work hardened public progress UX, file downloads, accession validation, SMTP wiring,
  NCBI retry behavior, and clinker panel generation.

`web/STYLE.md` records the UI contract. This file records the operational decisions, security
model, deployment wire, and handoff notes.

## What Changed Since The Original Scaffold

The current `web/static/index.html` is no longer a plain dashboard. Current behavior includes:

- A ClusterWeave wordmark and stronger visual identity.
- A product-style header and single-page navigation.
- Manual NCBI accession entry as a first-class input path.
- A cleaner genome/accession intake panel.
- Public/admin access controls and Existing Run loader.
- Neumorphic depth tokens and tactile controls.
- A Results-first `Workflow progress` map rendered as a DNA-style double helix.
- Sanitized public activity popovers derived from known workflow markers.
- More readable run cards, console styling, result tabs, figure rendering, file grouping, and
  download links.
- Inline SVG figure preview/zoom that stays crisp.
- Download-only Files tab.
- Collapsible admin rerun controls.
- Optional SMTP completion/failure notifications.
- Expired-job retention cleanup.
- Manual accession format validation.
- Non-retryable NCBI datasets failures for missing/invalid accessions.
- Clinker Docker panel scripts now run with `--workdir "${SCRIPT_DIR}"`.

Important runtime note: existing clinker `panel.html` files generated before the Docker workdir
fix may contain `clusters: []` and show no synteny plot. Rerun the clinker stage to regenerate
those panels.

## Repo And QA State Notes

Playwright/browser checks are useful for UI changes. Keep `node_modules/` ignored. If Playwright
remains official QA tooling, keep `package.json` and `package-lock.json` committed and document
the screenshot commands used for public/admin views.

## Locked Public Release Decisions

### Access Model

ClusterWeave should use a two-token, no-account model for first public release:

- Submit token: allows job creation.
- Per-job read token: allows reading one job's status, sanitized summary, figures, and files.
- Admin token: unlocks job list, full logs, worker telemetry, reruns, delete, diagnostics, and
  admin-only controls.

No user accounts or passwords in the first public release.

### Anonymous Users

Anonymous users may:

- Load the static UI.
- View redacted service status.
- See whether submissions are open or paused.
- See aggregate jobs processed.
- Load demo accessions locally into the form.
- Paste an existing result link or `job_id + read token` to unlock one job.
- Read public docs/help/citation copy.

Anonymous users must not:

- List jobs.
- Submit jobs.
- Upload files.
- Poll job logs or results.
- Download artifacts.
- Rerun or delete jobs.
- See worker telemetry, queue depth, capabilities, internal paths, or job IDs.

### Token-Gated Reads

All job-specific reads must be token-gated server-side:

- `/api/jobs`
- `/api/jobs/<id>`
- `/api/jobs/<id>/logs`
- `/api/jobs/<id>/files`
- `/api/jobs/<id>/files/<path>`

Job read token unlocks only that job. Admin token unlocks all jobs.

### Result Links

Result links should be bookmarkable and email-friendly without putting tokens in normal server
logs.

Recommended browser format:

```text
https://clusterweave.example.org/#/job/<job_id>/<read_token>
```

The SPA reads the fragment and sends the token as an `Authorization: Bearer ...` header.

The Existing Run loader should accept either:

- a full result link
- `job_id + read token`

The browser may keep a session-only "Opened runs" list in `sessionStorage`. This is not a server
job list; it only contains jobs the user explicitly unlocked.

### Public Retention

Match antiSMASH-like public behavior: public results are retained for one month.

Default policy:

- Completed and failed jobs expire after 30 days.
- Configure with `CLUSTERWEAVE_JOB_RETENTION_DAYS=30`.
- Delete uploads, logs, work dirs, result files, email, and read tokens on expiration.
- Keep only aggregate counters after deletion.
- No public early delete.
- Admin can delete jobs.

Users should be told the expiration date in the UI and completion/failure emails.

### Public Submission Safety

Public submission must require a data-use acknowledgment:

```text
I understand this public service is for public or releasable data only. Results are accessible to
anyone with the private result link until expiration.
```

Recommended public copy:

- Submit only public or releasable data.
- Sensitive/private work should be run locally with the Dockerized ClusterWeave release.
- Keep the result link private.

### Public Status

Anonymous status should show:

- Service online/offline.
- Submissions open/paused.
- Jobs processed aggregate.

Do not show:

- queue depth
- running jobs
- worker phase/detail
- worker logs
- runtime capabilities
- job IDs
- filesystem paths
- resource diagnostics

Admin status may show those details.

### Public Inputs

Public intake should be narrow and truthful.

Allowed:

- Manual NCBI accessions.
- Plain `.txt` accession list, one accession per line.
- Genome uploads:
  `.fasta`, `.fa`, `.fna`, `.fsa`, `.gb`, `.gbk`, `.gbff`.
- UI-generated ecology metadata when ecology-aware analysis is enabled.

Not public for first release:

- `.tsv` or `.csv` accession tables. The staging layer recognizes these today, but the NCBI
  download script reads one accession per line, so true tabular support is not safe to advertise.
- `.gff`, `.gff3`, `.faa`, `.json`, `.mgf`, generic `.zip`, and unclassified auxiliary uploads.
- NPLinker inputs.
- Raw metadata TSV/CSV upload unless/until the layout is documented and validated.

### Genome Filename Hygiene

For direct genome uploads, tell users:

- Use simple filenames with letters, numbers, `.`, `_`, and `-`.
- Avoid spaces, slashes, parentheses, duplicate filenames, and very long names.
- Each genome file stem should identify one genome.
- The stem becomes the ecology-table key for direct uploads.

Example:

```text
Aspergillus_fumigatus_Af293.fna
```

### Quotas

Public defaults, all env-configurable:

- Max accessions per job: `25`
- Max genome files per job: `25`
- Max individual upload file: `250 MB`
- Max total upload per job: `1 GB`
- Max queued jobs: `50`
- Max CPU per job: `8`
- Worker concurrency default: `1`
- Retention: `30 days`

### Public Workflow

Public workflow should be fixed and canonical:

```text
Accessions/genomes -> optional ecology labels -> submit -> workflow progress -> results
```

Do not expose public stage toggles, public Advanced knobs, public raw env overrides, public
NPLinker, public rerun controls, or public delete controls.

Admin/local deployments may still expose those controls.

### Lab QA

`web` and `worker` are not public/admin roles:

- `web` serves the browser UI and API.
- `worker` executes queued jobs and should not be internet-exposed.
- Lab QA is an admin/debug surface inside the web UI that displays worker/backend state.

Public default UI should hide Lab QA. Admin token unlocks it.

### Reruns

Reruns are admin-only.

Reason: reruns primarily support debugging/troubleshooting and stage-level QA. Public users should
not see stage selection or force-overwrite controls.

Failed public jobs should show/send sanitized failure summaries with common fixes, especially for
bad accession IDs or unsupported file types.

### Failure Messages

Public/job-token view:

- Show failed stage.
- Show sanitized explanation.
- Show common fixes.
- Show retry-new-submission/contact-support path.

Do not show:

- raw logs
- filesystem paths
- command lines
- env vars
- container internals
- stack traces

Admin view may show full logs and rerun controls.

### Optional Email

Add email notification only if SMTP is configured.

Rules:

- Hide or disable email field unless `CLUSTERWEAVE_SMTP_ENABLED=1`.
- Email is optional.
- Store email only in job metadata, never logs.
- Send completion/failure notification with result link and expiration date.
- Failure email uses sanitized summary, not raw logs.
- Delete email metadata when job expires.

The official fungiSMASH completion email is a good precedent: it states the job ID, submitted
timestamp, filename/input context, final status, result link, one-month retention, and citation
pointer. ClusterWeave should use that structure but tailor it to a multi-stage workflow.

Recommended completion subject:

```text
ClusterWeave job <job_id> finished: <status>
```

Recommended completion body:

```text
Dear ClusterWeave user,

The ClusterWeave job <job_id> submitted on <submitted_at> for project <project_name> has finished
with status <status>.

Input summary:
- Accessions: <n_accessions>
- Genome files: <n_genome_files>
- Ecology-aware analysis: <enabled_or_disabled>

Workflow summary:
- Prep / NCBI retrieval: <status>
- Annotation / BGC detection: <status>
- BiG-SCAPE: <status>
- Summary: <status>
- clinker: <status>
- Figures: <status>

You can find the results here:
<result_link>

Results will be kept for one month and then deleted automatically on <expires_at>.

If you found ClusterWeave useful, please cite the project using the citation instructions here:
<citation_or_docs_link>
```

Recommended failure body uses the same header and result link, but replaces the workflow summary
with a sanitized failure summary:

```text
The job did not complete successfully.

Failed stage: <public_stage_name>
Likely issue: <sanitized_reason>
Suggested fixes:
- Check that NCBI accessions are valid and one per line.
- Check that uploaded genomes use supported extensions: .fasta, .fa, .fna, .fsa, .gb, .gbk, .gbff.
- Submit only public or releasable data; for sensitive or advanced troubleshooting, run
  ClusterWeave locally with Docker.

The private result link below may include partial outputs and the public failure summary:
<result_link>

Results will be kept for one month and then deleted automatically on <expires_at>.
```

Email must not include raw logs, command lines, filesystem paths, environment variables, container
details, stack traces, admin tokens, submit tokens, or read tokens except as part of the private
fragment result link.

### Ecology-Aware Analysis

Ecology UI should be table-driven and controlled.

When `Enable ecology-aware analysis` is checked:

- Generate rows from pasted accessions and uploaded genome filename stems.
- Columns: `Input`, `Primary ecology`, `Secondary ecology`.
- Dropdown vocabulary:
  `soil`, `plant_associated`, `endophyte`, `mycorrhiza`, `plant_pathogen`, `saprotroph`,
  `marine`, `freshwater`, `lichen_associated`, `insect_associated`, `animal_associated`,
  `human_associated`, `food_fermentation`, `unknown`, `other`.
- If `other` is selected, show a short custom text field.
- Blanks are allowed, but warn that unlabeled inputs reduce ranking usefulness.
- Submit canonical `ecofun_metadata_normalized.tsv` behind the scenes.

Do not expose raw TSV/CSV metadata upload in the first public UI.

### Results Layout

Public Results should become the main run surface.

Before any job is loaded:

```text
Submit or load an existing run to see stage progress.
```

After submit:

- Upload & Configure locks, greys, collapses.
- App routes/focuses to Results.
- `Workflow progress` double-helix timeline appears above Visualization/Files.
- Stage labels:
  - Intake
  - Prep / NCBI retrieval
  - Annotation / BGC detection
  - BiG-SCAPE
  - Summary
  - clinker
  - Figures
  - Outputs
- Annotation stage may show antiSMASH/FunBGCeX per-genome progress only when sanitized events
  provide real signal. Do not fake counts.

Remove public output discovery cards. Visualization remains figure-only. Figure cards may keep
Open/Download. Files tab is download-only and displays paths as text.

## Implementation Ledger

Slice 13 added an opt-in public API security boundary:

- `CLUSTERWEAVE_PUBLIC_MODE=1` switches the API from local/lab permissive mode to token-gated
  public mode.
- Job creation requires `CLUSTERWEAVE_SUBMIT_TOKEN` or `CLUSTERWEAVE_ADMIN_TOKEN`.
- Job list, rerun, delete, and full worker telemetry require `CLUSTERWEAVE_ADMIN_TOKEN`.
- Job details, logs, files, and downloads require that job's read token or the admin token.
- Job read tokens are returned once at submission and only a digest is stored in job metadata.
- Anonymous `/api/system/status` is redacted to online/offline, submissions open/paused, and
  aggregate jobs processed.
- Public-mode CORS no longer emits wildcard access unless an allowed origin is explicitly
  configured.

Slice 14 added public submission policy, quotas, and retention metadata:

- Public submissions accept only `.txt` one-accession-per-line lists, genome files
  `.fasta`, `.fa`, `.fna`, `.fsa`, `.gb`, `.gbk`, `.gbff`, and generated
  `ecofun_metadata_normalized.tsv` when ecology-aware analysis is enabled.
- Public `.tsv/.csv` accession tables, auxiliary formats, generic archives, raw metadata paths,
  NPLinker submission settings, and non-admin raw environment overrides are rejected before a job
  workspace is created.
- Public quotas are enforced with env-configurable defaults for accessions, genome files,
  per-file upload size, total upload size, queued jobs, and CPU count.
- Public CPU requests are clamped to `CLUSTERWEAVE_MAX_CPUS_PER_JOB`; related thread/worker
  settings are clamped to the accepted CPU count.
- Jobs now carry `retention_days` and `expires_at`; terminal jobs also get `completed_at` or
  `failed_at` and refresh expiration from that terminal timestamp.

Slice 15 added the public UI shell:

- The hero now offers only public accession start and demo-load actions; the static hero weave and
  top-level WeaveMap nav are gone.
- Access keys live in `sessionStorage`; submit/admin tokens stay out of URLs.
- Existing runs can be opened from a full result fragment link or a job ID plus read token, and
  unlocked runs are tracked in the browser session.
- Run history, Lab QA, advanced knobs, stage toggles, rerun/delete controls, raw env overrides,
  output discovery, and NPLinker controls are admin/local-only.
- The live stage timeline moves into Results. Public result file/figure fetches use saved read
  tokens through request headers.

Slice 16 added controlled ecology labels:

- Public users can enable ecology-aware analysis without seeing the TSV schema.
- Ecology rows are generated from pasted NCBI accessions and uploaded genome filename stems.
- Primary and secondary labels use the controlled vocabulary, with short custom text only when
  `other` is selected.
- Blank labels are allowed, but the UI warns that unlabeled inputs may reduce ranking usefulness.
- The browser emits canonical `ecofun_metadata_normalized.tsv` only when ecology-aware analysis
  is enabled; raw metadata TSV paths remain admin/local-only.

Slice 17 added optional email recovery and retention cleanup:

- SMTP-enabled deployments expose an optional completion email field through redacted system
  status; disabled deployments reject submitted emails.
- Notification emails are sent only on terminal job status, contain a private fragment result link
  and expiration date, and avoid raw logs, paths, commands, env vars, stack traces, and worker
  internals.
- Email addresses stay in job metadata and are redacted from job API payloads.
- Email result links use one-time read tokens whose digests are stored with the job.
- `python3 web/maintenance.py sweep-expired-jobs` deletes expired job uploads, logs, work dirs,
  result files, email metadata, and read-token hashes while retaining only aggregate counters.
- `CLUSTERWEAVE_JOB_RETENTION_DAYS=0` or `never` now requires explicit
  `CLUSTERWEAVE_ALLOW_NEVER_EXPIRE_JOBS=1` documentation.

Slice 18 added public deployment QA coverage:

- Added a consolidated public deployment smoke test covering anonymous, submit-token, read-token,
  and admin API behavior in one role-matrix flow.
- Confirmed anonymous status is redacted and anonymous users cannot list, read, log, file, rerun,
  or delete jobs.
- Confirmed submit tokens can create jobs within public quotas but cannot list jobs.
- Confirmed read tokens can read only their job and can download result files through the
  token-aware result file API.
- Confirmed admin tokens can list jobs, see full status/logs, rerun, and delete.
- Captured Playwright screenshots for anonymous, submit-token, job-token, and admin views at
  desktop and mobile sizes using a temporary public-mode server.
- Browser QA confirmed SMTP field visibility, submit lock/collapse after submission,
  figure-only Visualization rendering, `resultHref(...)`-shaped figure Open/download links, and
  no horizontal overflow on mobile.

Post-slice hardening after Slice 18:

- Docker Compose declares SMTP/public-link env passthroughs on both `web` and `worker`.
- Manual accessions and uploaded accession lists reject malformed NCBI assembly accessions before
  job creation in both public and local modes.
- NCBI datasets "no genome assemblies match" and invalid accession errors are non-retryable, so a
  failing accession no longer burns through repeated attempts.
- The public Results workflow visualization is now a horizontal DNA-style WeaveMap with sanitized
  hover popovers and no stale heartbeat row.
- Redundant Results output-discovery panels and lower current-stage ribbon are removed.
- Figure previews are zoomable. SVG figures are hydrated inline and zoom by `viewBox` to stay
  sharp; raster figures use transform/pan.
- Files tab rows are download-only.
- `Rerun Selected Stages` is admin-only, collapsible, and visually separated from Results tabs.
- Generated clinker Docker panel scripts now set `--workdir "${SCRIPT_DIR}"`. This fixes empty
  clinker HTML payloads caused by relative `inputs/...` paths resolving from `/` inside Docker.

Existing clinker panels generated before this fix need a clinker-stage rerun to regenerate
non-empty `panel.html` plots.

Remaining public-release risks:

- The live host still needs final DNS/TLS/reverse-proxy confirmation.
- Live deployment secrets still need to be injected through the host secret store, not committed
  into Compose or handoff docs.
- Reverse-proxy body-size and rate-limit settings still need to be aligned with ClusterWeave
  quotas.
- SMTP needs one live-provider end-to-end test after provider, sender policy, and public URL are
  confirmed.
- A fresh public-mode canonical run should verify result links, email delivery, WeaveMap activity,
  figure zoom, Files downloads, and regenerated clinker `panel.html` plots.
- The citation strip still points at a future DOI/citation target.

Keep server-side security ahead of UI hiding in all future deployment and maintenance work.

## Follow-Up Queue

See `web/STYLE.md` for the UI contract and historical slice ledger.

- Completed: Slice 13 - Public API Security Foundation.
- Completed: Slice 14 - Public Input Policy, Quotas, And Retention Metadata.
- Completed: Slice 15 - Public UI Restructure.
- Completed: Slice 16 - Ecology Label Table.
- Completed: Slice 17 - Email Notifications And Retention Sweeper.
- Completed: Slice 18 - Public Deployment QA.
- Completed: Post-slice hardening - SMTP compose wire, accession validation, NCBI retry policy,
  WeaveMap polish, SVG zoom, download-only Files, collapsible reruns, clinker Docker workdir.
- Current: No remaining numbered slice. Continue with hosting-specific deployment follow-up.

Recommended next work:

- Final DNS/TLS/reverse-proxy smoke test on the real host.
- Live SMTP provider test with the final `CLUSTERWEAVE_PUBLIC_BASE_URL`.
- Fresh public-mode demo run that exercises accession prep, WeaveMap public events, figures,
  Files downloads, email, retention metadata, and clinker panel regeneration.
- Replace the future citation placeholder with the final DOI or citation URL.
- Capture desktop/mobile screenshots for anonymous, submit-token, read-token, and admin views.

## SMTP Deployment Wire

`docker-compose.yml` now declares the optional SMTP/public-link contract on both `web` and
`worker`. The values are host-environment pass-throughs so credentials do not live in source.

For local dry runs, set `CLUSTERWEAVE_SMTP_ENABLED=1` and
`CLUSTERWEAVE_SMTP_OUTBOX_DIR=/data/smtp-outbox`; notifications will be written as `.eml` files
inside the shared job-data volume instead of being sent to a mail provider.

Once the public URL and SMTP service are confirmed, the web-hosting collaborator should update the
deployment environment or secret store, not this file:

- Set `CLUSTERWEAVE_PUBLIC_BASE_URL` to the final HTTPS origin with a trailing slash.
- Set a long stable `CLUSTERWEAVE_JOB_TOKEN_SECRET` shared by `web` and `worker`.
- Set `CLUSTERWEAVE_SMTP_ENABLED=1`.
- Set `CLUSTERWEAVE_SMTP_HOST`, `CLUSTERWEAVE_SMTP_PORT`, provider credentials, and
  `CLUSTERWEAVE_SMTP_FROM`.
- Keep `CLUSTERWEAVE_SMTP_OUTBOX_DIR` empty for live SMTP delivery.
- Recreate both services so the UI advertises SMTP and the worker sends terminal notifications.

## Local Docker Operation Notes

For local/public-mode dry runs, `HOST_PORT=18080` maps the web service to
`http://127.0.0.1:18080/` unless the host/reverse proxy exposes another address.

Useful patterns:

```bash
sudo HOST_PORT=18080 docker compose up -d --force-recreate web worker
sudo HOST_PORT=18080 docker compose up -d --no-deps --force-recreate web
sudo docker compose build --no-cache web
sudo docker compose build --no-cache worker
```

If Docker reports permission denied on `/var/run/docker.sock`, the operator either needs `sudo`
or must re-login after being added to the `docker` group.

If `0.0.0.0:18080` is already in use, an older container/process is still bound to that port.
Use `docker compose ps` and recreate/stop the old web service, or choose a different `HOST_PORT`.

When testing email links, set `CLUSTERWEAVE_PUBLIC_BASE_URL` to the URL users actually open. For
SSH-forwarded browser tests that may be `http://127.0.0.1:18080/`; for LAN/public tests it should
be the host/domain URL.

Code copied into running containers is only a live hotfix. Rebuild images before treating a
change as deployed.

## Questions For The Hosting Collaborator

Ask these before final public deployment:

- What VM provider and OS image is hosting ClusterWeave?
- How much disk is available for `/data`, Docker volumes, databases, and job workspaces?
- Is there a separate persistent volume for job data?
- Are backups enabled? If yes, do backups retain expired public jobs accidentally?
- What reverse proxy is in front of the Python web service: nginx, Caddy, Apache, Cloudflare, or
  something else?
- Who terminates TLS?
- Is there a domain name already assigned?
- Can the reverse proxy enforce body-size limits matching ClusterWeave quotas?
- Can the reverse proxy add rate limiting?
- Is SMTP available? If yes, provider, from-address policy, and credential injection method?
- Should submissions be invite-only via submit token at first, or open after rate limits are in
  place?
- Who holds the admin token and how is it rotated?
- Where should aggregate `jobs_processed` counters live after job deletion?
- Are there institutional data-use or privacy notices that must be linked from the UI?

## Suggested Environment Variables

These are the current deployment contract names:

```text
CLUSTERWEAVE_PUBLIC_MODE=1
CLUSTERWEAVE_SUBMIT_TOKEN=...
CLUSTERWEAVE_ADMIN_TOKEN=...
CLUSTERWEAVE_JOB_TOKEN_SECRET=...
CLUSTERWEAVE_SUBMISSIONS_OPEN=1
CLUSTERWEAVE_JOB_RETENTION_DAYS=30
CLUSTERWEAVE_MAX_ACCESSIONS=25
CLUSTERWEAVE_MAX_GENOME_FILES=25
CLUSTERWEAVE_MAX_UPLOAD_FILE_MB=250
CLUSTERWEAVE_MAX_UPLOAD_TOTAL_MB=1024
CLUSTERWEAVE_MAX_QUEUED_JOBS=50
CLUSTERWEAVE_MAX_CPUS_PER_JOB=8
CLUSTERWEAVE_ALLOW_ENV_OVERRIDES=0
CLUSTERWEAVE_PUBLIC_BASE_URL=https://clusterweave.example.org/
CLUSTERWEAVE_SMTP_ENABLED=0
CLUSTERWEAVE_SMTP_HOST=...
CLUSTERWEAVE_SMTP_PORT=587
CLUSTERWEAVE_SMTP_USERNAME=...
CLUSTERWEAVE_SMTP_PASSWORD=...
CLUSTERWEAVE_SMTP_FROM=ClusterWeave <no-reply@example.org>
CLUSTERWEAVE_SMTP_TLS=1
CLUSTERWEAVE_SMTP_OUTBOX_DIR=
```

## Agent Rules For Future Work

- Read `web/STYLE.md` and this file before editing.
- Implement exactly one requested change or one deployment follow-up at a time.
- Security/API hardening comes before UI hiding.
- Preserve `apiUrl(...)`, `resultHref(...)`, token-aware result fetches, figure Open/Download,
  Files Download-only behavior, and Visualization figure-only behavior.
- Preserve server-side auth boundaries for anonymous, submit-token, read-token, and admin flows.
- Preserve manual accession validation and non-retryable NCBI missing-accession behavior.
- Preserve generated clinker Docker `--workdir "${SCRIPT_DIR}"`.
- Do not invent scientific results, counts, scores, candidates, or QA outcomes.
- Keep public copy honest about accepted inputs, retention, and sensitivity.
- Keep admin/local QA capable, but do not expose it anonymously.
- Run relevant tests and browser screenshots before declaring public UI slices done.
