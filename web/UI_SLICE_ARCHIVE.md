# ClusterWeave Web UI Slice Archive

This file preserves historical ClusterWeave web UI slice maps, deployment verification notes,
and old handoff prompts that used to live in `web/STYLE.md`.

For current frontend work, read `web/STYLE.md` first. Treat this archive as reference material
only when investigating why an older UI or deployment decision was made. Do not use archived
visual strategies as active direction when they conflict with `web/STYLE.md`.

## Superseded Neumorphism + Retrofuturism Target

This section is historical context from earlier UI slices. For future work, follow the
`Vertical Slice Builder: Immersive Operational Web UI` section in `web/STYLE.md` whenever
guidance conflicts. Do not reintroduce rigid retro-futuristic layering as the primary direction.

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
- Completed: Slice 19 - Logo-Led Frontend Polish With Contract Lock, verified locally on
  2026-06-04.
- Completed immersive UI slices:
  - Slice 20 - Reset And Redeploy Runtime, archived on 2026-06-05.
  - Slice 21 - STYLE.md Handoff Builder, archived on 2026-06-05.
  - Slice 22 - Launch Layout, archived on 2026-06-05.
  - Slice 23 - DNA Progress Spine, archived on 2026-06-05.
  - Slice 24 - Submit Lift-Off State, archived on 2026-06-05.
  - Slice 25 - Results Dashboard, archived on 2026-06-05.
  - Slice 26 - Run Surface And Results Restructure, archived on 2026-06-05.
  - Slice 27A - Results Lollipop Tool Output Surface, archived on 2026-06-08.
  - Slice 27B - Results Flow Layout And Live Completion Surface, archived on 2026-06-08.
  - Slice 28 - Tool And Citation Disclosure, archived on 2026-06-08.
- Completed immersive UI slices through Slice 28 are archived below. Active/next work lives in `web/STYLE.md`.
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

Historical slices are kept below for context. New work should use `web/STYLE.md`, the
deployment verification queue here, and `web/STAN.md`, not restart old completed slices.

## Slice 25 - Results Dashboard

Status: completed and archived on 2026-06-05.

Goal: make completed runs open into a clear dashboard where users choose real result categories.

Completed work:

- Completed runs now keep Visualization/Files tucked away until the `Ready to see the results?`
  reveal opens the dashboard.
- Result bubbles are generated from real result file paths and show derived file counts only.
- Category selection filters the download-only Files tree for antiSMASH, summary, synteny, other,
  and all-file views while preserving path context and Download-only rows.
- Partial/failed runs with real files can show the category dashboard honestly without the
  completed-run reveal gate.
- Figure previews, SVG hydration/zoom, result-token fetches, Files-tab Download behavior, and
  admin/public boundaries were preserved.

Verification notes:

- Inline JS parse passed for `web/static/index.html`.
- Browser checks passed with a mocked API for a completed run, failed/partial run, full private
  result-link recovery, and mobile dashboard. Screenshots were written to `/tmp` during handoff.
- `python3 -m unittest tests.test_repo_layout` passed before archive update; final handoff checks
  were rerun after the archive update.
- `git diff --check` passed before archive update; final handoff checks were rerun after the
  archive update.

## Slice 26 - Run Surface And Results Restructure

Status: completed and archived on 2026-06-05.

Goal: make active and completed runs feel less redundant by separating run status from result
inspection, moving admin QA surfaces out of the DNA path, and keeping complete-run reveal centered
before the dashboard opens.

Completed work:

- The launch command panel disappears once a run leaves idle state instead of sliding beside the
  DNA spine.
- The right run-status rail now keeps Job ID/access information and Workflow progress only; result
  inspection moved into a separate dashboard surface.
- Completed runs show a centered `Ready to see the results?` overlay with the page blanketed until
  the user opens the dashboard.
- Opening results compacts the DNA spine left and renders real artifact-category bubble strings for
  figures, antiSMASH output, summaries/tables, synteny, other artifacts, and the full package.
- Run History, Worker telemetry, Lab console, and admin rerun controls moved into a left admin ops
  panel so they do not overlap the DNA in admin/reviewer mode.
- The web UI exposes a token-gated full package ZIP download through
  `/api/jobs/<job_id>/archive`, while keeping file rows download-only and preserving read-token or
  admin authorization.

Follow-up:

- The current dashboard still groups visible Web UI results from real file paths. The operator will
  provide the exact important files/categories to show after this restructure lands.

Verification notes:

- Inline JS parse passed for `web/static/index.html`.
- `python3 -m unittest tests.test_repo_layout` passed.
- `git diff --check` passed.
- Focused archive auth coverage passed through
  `tests.test_web_api_auth.WebApiAuthTests.test_read_token_unlocks_only_its_job_logs_and_files`.
- Browser checks passed with a mocked API for public completed-run overlay/dashboard reveal,
  read-token archive download, admin ops-panel geometry, and mobile overlay fit. Screenshots were
  written to `/tmp/clusterweave-slice26-public-dashboard.png`,
  `/tmp/clusterweave-slice26-admin-dashboard.png`, and
  `/tmp/clusterweave-slice26-mobile-ready.png` during handoff.

## Slice 27A - Results Lollipop Tool Output Surface

Status: completed and archived on 2026-06-08.

Goal: replace the transitional completed-run dashboard with artifact-backed output lollipops while
preserving token-aware result readers and download behavior.

Completed work:

- Built lollipop output categories from real `result_files` only: antiSMASH, FunBGCeX, BiG-SCAPE,
  Summary, Figures, downloads, and fallback files.
- Kept full package ZIP download visible and token-aware, but secondary to curated artifacts.
- Preserved public/job-token/admin result boundaries, existing IDs, API paths, upload behavior,
  result fetch/download behavior, rerun behavior, and the zero-dependency static SPA constraint.
- Added a token-aware generated-HTML opener that rewrites same-result relative assets to object
  URLs before opening the blob page; BiG-SCAPE keeps its database blob contract and shares the
  same asset-aware wrapper.

Verification notes:

- Inline JS parse for `web/static/index.html` passed.
- `python3 -m unittest tests.test_repo_layout` passed.
- `git diff --check` passed.
- Focused browser harness covered generic tool HTML and BiG-SCAPE-shaped HTML with cache-busted
  relative CSS assets.

## Slice 27B - Results Flow Layout And Live Completion Surface

Status: completed and archived on 2026-06-08.

Goal: remove the completed-run confirmation gate and make Results a live operational surface where
real artifacts appear as soon as they are indexed.

Completed work:

- Removed the `Ready to see the results?` reveal as a visible blocker while preserving the
  `ready-results-btn` hook as an inert compatibility entry point into the live output flow.
- Results now opens the live output surface for loaded jobs regardless of pending, running,
  failed, or completed status; partial outputs render from real `result_files` without invented
  categories, scores, candidates, or scientific claims.
- DNA-attached output bubbles now render for partial and completed files, branch farther outside
  the workflow spine lane, and use the ClusterWeave teal/mint, indigo/violet, amber/gold, and pale
  neutral palette.
- Laptop and desktop result mode uses a fixed left DNA rail and a right-side result board/reader
  lane; selected result readers keep the right-side majority of the viewport.
- Dev-admin management navigation now closes the live result surface for Overview/Intake, restores
  the run-builder deck, dims the DNA spine behind it, and keeps Run History from covering the
  Intake panel on single-screen desktop layouts.
- Slice 27A token-aware generated-HTML readers for antiSMASH, FunBGCeX, and BiG-SCAPE were
  preserved, along with full-package download, figure rendering, Files download-only behavior, and
  admin/public boundaries.

Verification notes:

- Inline JS parse for `web/static/index.html` passed.
- `python3 -m unittest tests.test_repo_layout` passed.
- `git diff --check` passed.
- Browser harness covered live partial-results rendering, completed-run auto-results, selected
  generated-tool readers, and dev-admin `Results -> Intake` visibility at desktop/laptop/mobile
  viewports.

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

- Verify `Existing results` with private result links.
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
  `New run` and the `Outputs` nav item.
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
  `Load demo run` in the `New run` entry panel.
- Rename public workflow copy from `WeaveMap` to `Workflow progress`.
- Add access key handling using `sessionStorage`; never put submit/admin tokens in URLs.
- Replace the old visible access-key panel with `New run` and `Existing results` tabs.
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

- Anonymous users see accepted input policy, data-use acknowledgment, `New run`, and
  `Existing results` without job leaks or role/token labels.
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

### Slice 19: Logo-Led Frontend Polish With Contract Lock

Status: completed locally on 2026-06-04 and rebuilt with the repo-local
`skills/taste-skill/SKILL.md` on 2026-06-04 after handoff clarification. The implementation uses
`web/static/assets/clusterweave-logo.png`, replaces the synthetic header wordmark with the real
logo asset, rebalances the UI around logo teal/gold/rust, removes visible emoji section markers,
keeps the Results-first flow and protected frontend/backend hooks intact, and updates
`tests/test_repo_layout.py` for the logo-led/taste-skill contract. The rebuild shortens the first
viewport into a compact instrument deck, adds route cues and logo caption chips, changes the entry
panel into a control rail, enables a desktop intake/output work-surface split, drops Inter as the
CSS default font family, and locks desktop button labels to a single line while allowing mobile
wrapping. Verification included inline JavaScript parse, `git diff --check`,
`tests.test_repo_layout`, Docker rebuild/recreate checks, and Playwright desktop/mobile screenshot
plus DOM layout checks against the live port-80 surface.

Goal: improve `web/static/index.html` using the local taste-skill references and the new
transparent logo asset while preserving every existing frontend/backend contract.

Source material:

- Local ignored taste-skill references live in `skills/`, especially
  `skills/taste-skill/SKILL.md`. Treat it as the named agent-skill lens for this slice even though
  it is repo-local rather than a globally registered Codex skill. `skills/redesign-skill/SKILL.md`
  is background context only if present.
- Brand asset:
  `manuscript/application_note/figures/cw_logo_noback.png`.
- Adjacent logo SVGs establish the useful brand palette:
  amber/gold `#fcb31b`, teal `#00bfa5`, deep teal `#006a61`, and burnt orange `#c36735`.

Design read:

- Existing-product redesign of a public fungal genomics workflow instrument.
- Audience: researchers, reviewers, and hosted-service operators.
- Vibe: scientific, bioinformatic, premium, readable, lightly gamified, credible.
- Use `skills/taste-skill/SKILL.md` as the primary guide, but apply it selectively because the
  skill itself warns that it is not meant for dashboards or multi-step product UI. Use its design
  read, theme lock, copy audit, shape consistency, button/input contrast, non-generic layout, and
  pre-flight discipline; do not force landing-page hero rules onto the operational SPA.
- Suggested dials: `DESIGN_VARIANCE 5`, `MOTION_INTENSITY 3`, `VISUAL_DENSITY 6`.

Non-negotiable contract lock:

- Preserve all existing functional IDs, input names, event handlers, JS functions, API paths,
  token flows, result rendering behavior, upload behavior, same-job rerun behavior, admin/public
  access boundaries, and endpoint semantics.
- Preserve `apiUrl(...)`, `apiFetch(...)`, `resultHref(...)`, `resultFetch(...)`, and
  `handleResultLinkClick(...)`.
- Preserve manual accession submission as `manual_accessions.txt`.
- Preserve Visualization as figure-only:
  `Data/Results/<project>/figures/*.{svg,png,jpg,jpeg,webp}`.
- Preserve Files tab as foldered, path-context rows with Download only. Do not re-add Files-tab
  Open links.
- Preserve public sanitized stage events/failure summaries and admin-only raw logs/reruns.
- Do not add a framework, build system, package manager, or external CDN dependency.
- Do not invent fake scientific metrics, result counts, candidate names, scores, or QA outcomes.

Tasks:

- Create a web-appropriate logo derivative under `web/static/assets/` from
  `manuscript/application_note/figures/cw_logo_noback.png` if needed for file size/layout.
- Replace the synthetic `CW` badge and hand-built header wordmark with the real logo asset while
  keeping the existing `logo` anchor, nav behavior, and `aria-label`.
- Use the real logo as a first-viewport brand signal in the compact identity band without turning
  the app into a marketing landing page.
- Keep first-viewport copy short: one compact headline, one support sentence, and operational
  route cues. Do not return to a long hero paragraph.
- Rebalance CSS variables around logo teal and amber; reduce violet/purple glow to a secondary
  accent instead of the dominant brand read.
- Tune WeaveMap strand, active, completed, and signal colors to echo the logo teal/gold
  relationship.
- Remove obvious generic/AI UI tells where low-risk:
  emoji section markers, repeated all-caps labels, excessive nested card surfaces, and
  decorative gradients that compete with the logo.
- Keep the Results-first structure: public entry tabs, Upload & Configure, Workflow progress,
  Visualization, Files, and citation ribbon remain the operational flow.
- Improve responsive logo/header behavior so text and controls never wrap awkwardly or overlap.
- Keep `prefers-reduced-motion` behavior intact and avoid new motion-heavy effects.

Acceptance:

- The first viewport clearly feels branded by the new ClusterWeave logo.
- The page still reads as a scientific workflow instrument, not a landing page or generic admin
  dashboard.
- Existing public/admin workflows still work by selector and by behavior.
- No protected functional IDs, JS hooks, API paths, auth behavior, file filtering, or download
  behavior changed.
- Visualization remains figure-only and Files remains Download only.
- Mobile header, entry tabs, Results tabs, WeaveMap, figure controls, and file rows do not
  overflow or overlap.
- Checks include at minimum:
  - JavaScript parse check for inline scripts in `web/static/index.html`
  - `git diff --check`
  - browser or screenshot review when tooling is available

#### Slice 19 Handoff Prompt

Use this prompt for the next Codex session when the goal is to review or extend this rebuilt
frontend slice:

```text
You are joining ClusterWeave after Slice 19 was rebuilt with the repo-local taste skill.

First read `web/STYLE.md` and `web/STAN.md`. Then read
`skills/taste-skill/SKILL.md` and treat it as the named agent-skill lens for frontend taste. It is
repo-local and landing/redesign oriented, so apply it selectively: use its design read, theme lock,
copy audit, shape consistency, button/input contrast, non-generic layout, explicit responsive
collapse, and pre-flight discipline. Do not force a marketing landing-page structure onto this
operational SPA.

Inspect `web/static/index.html`, `web/app.py`, `tests/test_repo_layout.py`, and the logo asset at
`web/static/assets/clusterweave-logo.png`. Preserve all existing functional IDs, input names,
event handlers, JS functions, API paths, token flows, upload behavior, result rendering behavior,
same-job rerun behavior, admin/public access boundaries, and endpoint semantics. Preserve
`apiUrl(...)`, `apiFetch(...)`, `resultHref(...)`, `resultFetch(...)`, and
`handleResultLinkClick(...)`.

Design read: existing-product redesign of a public fungal genomics workflow instrument for
researchers, reviewers, and hosted-service operators. The UI should feel scientific,
bioinformatic, premium, readable, lightly gamified, and credible. Dials: `DESIGN_VARIANCE 5`,
`MOTION_INTENSITY 3`, `VISUAL_DENSITY 6`.

Current Slice 19 visual contract:
- Real logo asset is the primary brand signal.
- The first viewport is a compact instrument deck, not a long landing-page hero.
- Identity copy stays short, with route cues for Input / Weave / Output.
- Entry tabs behave as a control rail on desktop and collapse explicitly on mobile.
- Desktop work surface may split intake/output columns; mobile remains single-column.
- Palette stays anchored in logo teal/gold/rust, with violet/purple only secondary if used.
- Desktop button labels stay on one line; mobile may wrap when needed.
- No fake metrics, fake scientific results, public logs, public stage toggles, Files-tab Open
  links, framework/build-system/CDN dependencies, or generic emoji section markers.

Keep Results-first behavior intact: public entry tabs, Upload & Configure, Workflow progress,
Visualization, Files, and citation ribbon remain the operational flow. Visualization stays
figure-only under `Data/Results/<project>/figures/*.{svg,png,jpg,jpeg,webp}`. Files stays foldered
and Download only.

Before editing, name the hooks you will preserve. After editing, run the inline JavaScript parse
check for `web/static/index.html`, `python3 -m unittest tests.test_repo_layout`,
`git diff --check`, and browser/screenshot review if tooling is available. If you rebuild Docker,
verify the actual user-facing host/port and that `/assets/clusterweave-logo.png` returns 200.
In the final response, summarize files changed, functional hooks preserved, checks run, active
URL/port, and residual risk.
```

## Immersive Operational Web UI Slices

These completed slices were moved out of `web/STYLE.md` on 2026-06-05 so that STYLE remains
a living board for the active and next UI handoffs. Keep them here as implementation and
verification history, not as active direction when they conflict with `web/STYLE.md` or
`web/STAN.md`.

### Slice 20 - Reset And Redeploy Runtime

Status: completed/archived on 2026-06-05. The port-80 Docker runtime was diagnosed as the
valid verification surface; the ad-hoc 18082 preview server is not a valid submission target
unless it is explicitly wired to the shared Docker `/data` runtime. Final operator handoff
still uses the rebuild command in `web/STYLE.md` before treating the live face as fresh.

Goal: restore the Slice 19 baseline on the actual user-facing Docker web service and prove the
backend runtime is healthy from the public URL.

Skill direction: use `diagnose` as the primary workflow because the slice is about stale assets,
runtime wiring, upload behavior, and worker health. Use `tdd` only if a backend helper or status
contract changes.

Tasks:

- Revert only the recent prototype redesign edits in `web/static/index.html`; preserve unrelated
  user changes.
- Rebuild/recreate the Docker port-80 `web` service so `http://10.64.195.209/` serves the repo UI.
- Verify submissions against port 80, not the 18082 preview server.
- Document any changed operational notes in `web/STYLE.md` or `web/STAN.md`.

Preserve:

- All SPA/API/token/upload/result/rerun/admin-public behavior listed in the baseline above.
- The real logo asset and the Slice 19 public Results-first contract.

Acceptance:

- `http://10.64.195.209/` no longer shows stale frontend assets after rebuild.
- A real submission reaches the Docker-backed runtime instead of returning the 18082 hosted
  analysis outage message.
- The root cause is recorded as preview-runtime wiring, not a worker capability failure.

Verification:

- JS parse for inline scripts in `web/static/index.html`.
- `python3 -m unittest tests.test_repo_layout`.
- `git diff --check`.
- Docker service status for `web` and `worker`.
- Browser check of the actual port-80 URL.
- A small real port-80 submission check.

### Slice 21 - STYLE.md Handoff Builder

Status: completed/archived on 2026-06-05. `web/STYLE.md` now acts as the living board and
`web/UI_SLICE_ARCHIVE.md` stores completed slice specs and historical handoff material.

Goal: make this vertical slice builder the source of truth for delegating future web UI work.

Skill direction: use `zoom-out` when historical guidance conflicts or the next agent cannot tell
which instructions are current. Use `grill-with-docs` only when a product/security decision needs
user resolution and durable documentation.

Tasks:

- Add and maintain this `Next Vertical Slice Builder` section.
- Mark older retro-futuristic/neumorphic instructions as historical or superseded where they
  conflict.
- Keep the Slice 19 contract as the functional baseline for future UI work.

Preserve:

- Historical slice notes that are still useful for context.
- `web/STAN.md` as the source of operational/public-release decisions.

Acceptance:

- A new session can start from this section and know the next slice, constraints, acceptance
  criteria, and verification commands without reading the full conversation.
- Conflicting historical visual guidance is explicitly lower priority than this builder.

Verification:

- `git diff --check`.
- Optional: `python3 -m unittest tests.test_repo_layout` if implementation code changed in the
  same session.

### Slice 22 - Launch Layout

Status: completed/archived on 2026-06-05. The first-screen structure now centers the
operational run builder around the page-level DNA motif, keeps New Run primary, preserves
Existing Results recovery, and removes the old empty DNA-panel gap.

Goal: build the new first-screen experience around a full-height DNA spine and a right-side run
builder.

Skill direction: use `prototype` before implementation if the first-screen composition, side tabs,
or mobile collapse are still visually uncertain. Use `improve-codebase-architecture` if moving
intake/results panels reveals duplicated layout state or brittle CSS/JS coupling.

Tasks:

- Place the real logo only at the top-left.
- Put the zero-dependency vertical DNA spine on the left, running top to bottom.
- Put the bold run-builder panel on the right with `Run Fungal...` content at the top.
- Make New Run active by default.
- Convert New Run and Existing Run into side tabs; selected New Run uses orange/gold.
- Make Existing Run hide the lower run-builder controls until valid existing-run information is
  entered.

Preserve:

- Every functional ID, input name, event handler, and submission/load behavior.
- Desktop intake/output split and explicit mobile single-column collapse.

Acceptance:

- First-time users see the active New Run path immediately.
- Existing Run is visually available but does not expose lower run-builder controls before valid
  lookup details are present.
- The layout feels like an operational tool, not a landing page.

Verification:

- JS parse.
- `python3 -m unittest tests.test_repo_layout`.
- `git diff --check`.
- Desktop and mobile browser checks, including narrow-width tab collapse.

### Slice 23 - DNA Progress Spine

Status: completed/archived on 2026-06-05. The progress motif is a large page-background
vertical helix with teal/gold/orange/violet treatment, real stage-state mapping, active
timing copy, completed glow, running pulse, and future-stage fade/gray behavior.

Goal: replace the prototype slanted/rotating DNA with the preferred full-height progress helix.

Skill direction: use `improve-codebase-architecture` to keep stage-state mapping, timers, labels,
and rendering local instead of scattering conditional DOM updates. Use `tdd` or a browser harness
for active, queued, completed, failed, skipped, and reduced-motion behavior.

Tasks:

- Restore the previous DNA/helix progress style as a vertical page-height spine.
- Show past, current, future, failed, skipped, and complete stage states with clear visual
  differences.
- Keep current progress bright and future progress slightly transparent.
- Add a current-stage timer and labeled expected run-time ranges between stages, using real
  workflow stages only.
- Respect reduced-motion preferences.

Preserve:

- Sanitized public progress events and admin-only raw logs.
- Existing stage-state functions and data flow unless a small internal refactor is necessary.

Acceptance:

- The helix is stable, readable, and informative without slant or automatic rotation.
- Timing copy is clearly an estimate and never presented as a fake guarantee.
- Public users do not see logs, raw worker paths, or stage toggles.

Verification:

- JS parse.
- `python3 -m unittest tests.test_repo_layout`.
- `git diff --check`.
- Browser checks for active, queued, completed, failed, and reduced-motion states.

### Slice 24 - Submit Lift-Off State

Status: completed/archived on 2026-06-05. Submission now transitions the intake into a
compact/disabled sidebar-like state, brings the DNA progress object forward, keeps result
link/access-code actions available, adds a slim output rail, and includes queue-position
transparency for pending jobs without exposing admin-only worker internals.

Goal: make submission feel like the start of the run while keeping the real upload and polling
flow intact.

Skill direction: use `tdd` for submit, failed-submit, token-copy, reload/recover, and polling
transitions because this slice touches real user flow. Use `diagnose` immediately if upload,
worker status, or result-token behavior diverges from the existing contract.

Tasks:

- On upload/submit, collapse or transform the intake box into a compact package/scaffold state.
- Show `CLUSTERWEAVE HAS BEGUN!` while polling real job status.
- Make the compact package become the first scaffold in the main vertical DNA progress spine.
- Keep the result-link confirmation and copy actions available.

Preserve:

- `manual_accessions.txt` generation and upload behavior.
- Data-use acknowledgment, optional email behavior, job tokens, rerun behavior, and polling.

Acceptance:

- A successful submit visibly moves the user from intake to live progress.
- Failed submission still shows a sanitized actionable error and does not fake progress.
- The user can still copy the result link/access code after submit.

Verification:

- JS parse.
- `python3 -m unittest tests.test_repo_layout`.
- `git diff --check`.
- Browser checks for successful submit, failed submit, and reload/recover behavior.


## Prompt Template For A UI Agent

Use this prompt when handing off future ClusterWeave web work to a fresh Codex session:

```text
PROJECT STAMP
- Project: ClusterWeave
- Repo: /home/cloud/clusterweave
- UI target: web/static/index.html
- Style guide: web/STYLE.md
- Operational handoff: web/STAN.md
- Repo-local frontend taste skill: skills/taste-skill/SKILL.md
- Product: fungal BGC discovery and prioritization web UI
- Runtime model: shell-first canonical workflow, static SPA as controller

ROLE
You are an expert frontend/UI Codex and product-minded visual designer joining ClusterWeave.
Work like a senior engineer: inspect first, preserve working behavior, then make one scoped
implementation that matches the current public-service direction.

FIRST, INSPECT
1. Run `git status --short` and note unrelated changes.
2. Read `web/STYLE.md`, `web/STAN.md`, and `skills/taste-skill/SKILL.md` for frontend work.
3. Inspect the current `web/static/index.html` structure and any backend helper touched by the
   request.
4. Identify functional hooks involved: IDs, event handlers, JS functions, API paths, auth roles,
   tabs, buttons, and data attributes.
5. Check nearby tests, especially `tests/test_repo_layout.py`, `tests/test_web_api_auth.py`,
   `tests/test_public_stage_sanitizer.py`, and helper-specific tests.
6. If browser tooling is available, capture or inspect the current UI before editing. If not,
   state that browser screenshot tooling is unavailable and continue using live HTML/API checks.

MISSION
Implement exactly the requested change, the next explicit build slice in this style guide, or the
next explicit hosting/deployment follow-up from `web/STAN.md`. If the user says "next slice"
without details and no later unimplemented numbered UI slice has been added, continue with the
current hosting/deployment follow-up from `web/STAN.md`, or ask one concise question if the next
step depends on host-specific information.

ClusterWeave should feel like a woven fungal discovery instrument: scientific, bioinformatic,
premium, readable, lightly gamified, and credible. For frontend visual work, treat
`skills/taste-skill/SKILL.md` as the local taste lens, applied selectively to this operational SPA.
The UI should blend Neumorphism and Retrofuturism only in service of clarity:
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

### Slice 28 - Tool And Citation Disclosure

Status: complete on 2026-06-08. The bottom citation/tool strip is now a compact in-flow disclosure pill; the approved tool credits, public citation prompt, licenses, links, and operator-alignment note remain available when opened.

Goal: move third-party tool and citation information out of the always-visible bottom row.

Skill direction: use a light `prototype` pass only if the disclosure placement competes with
mobile controls or results. Use `tdd` only if required citation/operator copy, links, or public
visibility behavior changes.

Tasks:

- Replace the bottom citation/tool strip with a compact disclosure or dropdown.
- Keep tool names, citation prompts, and operator-agreement alignment available on inspection.
- Avoid stale always-visible footer content.

Preserve:

- Any required citation/operator copy and links already approved for public release.
- Public copy boundaries around third-party tools and hosted-service data policy.

Acceptance:

- The bottom of the page is cleaner, while users can still inspect tool/citation details.
- The disclosure works on desktop and mobile without covering controls or results.

Verification:

- JS parse.
- `python3 -m unittest tests.test_repo_layout`.
- `git diff --check`.
- Browser checks for disclosure open/closed states on desktop and mobile.

Completion notes:

- Restyled the existing `#docs` `<details>` block from a full-width bottom ribbon into a compact disclosure control.
- Preserved the existing citation hook, tool-credit links, license labels, public copy boundaries, and zero-dependency static SPA behavior.
- Browser checks covered closed/open states on desktop and mobile, including no horizontal overflow and no overlay positioning.

Verification completed for Slice 28:

- Inline JS parse for `web/static/index.html`.
- `python3 -m unittest tests.test_repo_layout`.
- `git diff --check`.
- Playwright layout checks for disclosure open/closed states on 1440px desktop and 390px mobile viewports.

