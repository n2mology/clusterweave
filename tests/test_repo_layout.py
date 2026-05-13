from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]


class RepoLayoutTests(unittest.TestCase):
    def test_core_entrypoints_exist(self) -> None:
        for rel in [
            "accessions.txt",
            "prepare_genomes_from_accessions.sh",
            "install_ncbi_cli.sh",
            "run_clusterweave.sh",
            "run_figures.sh",
            "run_annotation_and_detection.sh",
            "run_bigscape.sh",
            "summarize_clusterweave.sh",
            "run_clinker.sh",
            "scripts/ncbi/download_ncbi_genomes.sh",
            "scripts/ncbi/rename_ncbi_genomes.sh",
            "scripts/ncbi/flatten_ncbi_genomes.sh",
            "bin/capture_external_artifacts.py",
        ]:
            self.assertTrue((REPO_ROOT / rel).exists(), rel)

    def test_release_metadata_exists(self) -> None:
        for rel in [
            "README.md",
            "BEGINNER_SETUP.md",
            "LICENSE",
            "CITATION.cff",
            "THIRD_PARTY.md",
            "DATA_SOURCES.md",
            "docs/REPRODUCIBILITY.md",
            "docs/WEB_RUNTIME.md",
            "pyproject.toml",
        ]:
            self.assertTrue((REPO_ROOT / rel).exists(), rel)

    def test_generic_example_paths_exist(self) -> None:
        self.assertTrue((REPO_ROOT / "profiles" / "example_project.env").exists())
        self.assertTrue((REPO_ROOT / "examples" / "example_project" / "README.md").exists())

    def test_no_plaintext_massive_password_default(self) -> None:
        text = (REPO_ROOT / "run_nplinker.sh").read_text(encoding="utf-8")
        self.assertIn('MASSIVE_PASSWORD="${MASSIVE_PASSWORD:-}"', text)

    def test_stage1_bootstrap_defaults_exist(self) -> None:
        text = (REPO_ROOT / "run_annotation_and_detection.sh").read_text(encoding="utf-8")
        self.assertIn('ANTISMASH_IMAGE_URI="${ANTISMASH_IMAGE_URI:-docker://antismash/standalone:8.0.4}"', text)
        self.assertIn('AUTO_BUILD_FUNBGCEX_SIF="${AUTO_BUILD_FUNBGCEX_SIF:-1}"', text)
        self.assertIn('FUNBGCEX_BOOTSTRAP="${FUNBGCEX_BOOTSTRAP:-0}"', text)
        self.assertIn('FUNBGCEX_DOCKER_IMAGE="${FUNBGCEX_DOCKER_IMAGE:-clusterweave-funbgcex:latest}"', text)
        self.assertIn('ensure_docker_image()', text)
        self.assertIn('antismash_exec()', text)
        self.assertIn("build_funbgcex_sif()", text)
        self.assertIn("ensure_primary_tooling", text)
        self.assertIn("normalize_gbk_record_headers_in_place()", text)

    def test_summary_stage_supports_optional_ecology_mode(self) -> None:
        text = (REPO_ROOT / "summarize_clusterweave.sh").read_text(encoding="utf-8")
        self.assertIn('RUN_ECOLOGY_ANALYSIS="${RUN_ECOLOGY_ANALYSIS:-0}"', text)
        self.assertIn("Skipped ecology-aware ranking", text)

    def test_summary_scaffold_normalization_handles_funbgcex_trailing_dot(self) -> None:
        text = (REPO_ROOT / "summarize_clusterweave.sh").read_text(encoding="utf-8")
        self.assertIn('re.sub(r"\\.\\d+$", "", scaf)', text)
        self.assertIn('return scaf.rstrip(".")', text)

    def test_summary_counts_hybrid_bgcs_once(self) -> None:
        text = (REPO_ROOT / "summarize_clusterweave.sh").read_text(encoding="utf-8")
        self.assertIn("def summary_bgc_class", text)
        self.assertIn('if len(primary) > 1: return "Hybrid"', text)
        self.assertIn("a_class[summary_bgc_class(classes)]+=1", text)
        self.assertIn("f_class[summary_bgc_class(classes)]+=1", text)
        self.assertNotIn("a_summary_class", text)
        self.assertNotIn("f_summary_class", text)

    def test_wrapper_supports_clinker_stage(self) -> None:
        text = (REPO_ROOT / "run_clusterweave.sh").read_text(encoding="utf-8")
        self.assertIn('RUN_STAGE_CLINKER="${RUN_STAGE_CLINKER:-auto}"', text)
        self.assertIn('CLINKER_MODE="${CLINKER_MODE:-auto}"', text)
        self.assertIn('RUN_CLINKER_STAGE="${PROJECT_DIR}/run_clinker.sh"', text)
        self.assertIn('RUN_STAGE_ANNOTATION="${RUN_STAGE_ANNOTATION:-${RUN_STAGE_NEW:-1}}"', text)
        self.assertIn("Stage 4/4: running run_clinker.sh", text)
        self.assertIn("SHOULD_RUN_CLINKER=1", text)

    def test_clinker_supports_metadata_fallback(self) -> None:
        text = (REPO_ROOT / "run_clinker.sh").read_text(encoding="utf-8")
        self.assertIn('CLINKER_MODE="${CLINKER_MODE:-auto}"', text)
        self.assertIn('CLINKER_USE_DOCKER_IMAGE="${CLINKER_USE_DOCKER_IMAGE:-0}"', text)
        self.assertIn("ensure_clinker_docker_image()", text)
        self.assertIn('REFRESH_FAMILY_ATLAS="${REFRESH_FAMILY_ATLAS:-1}"', text)
        self.assertIn('ATLAS_MIN_RECORDS="${ATLAS_MIN_RECORDS:-2}"', text)
        self.assertIn('AUTO_NORMALIZE_METADATA="${AUTO_NORMALIZE_METADATA:-1}"', text)
        self.assertIn('METADATA_TEMPLATE_TSV="${METADATA_TEMPLATE_TSV:-${RESULTS_ROOT}/summary_tables/ecofun_metadata_template.tsv}"', text)
        self.assertIn('EXPORT_FAMILY_ATLAS_PY="${EXPORT_FAMILY_ATLAS_PY:-${PROJECT_DIR}/bin/export_dataset_family_atlas.py}"', text)
        self.assertIn("ensure_metadata_tsv()", text)
        self.assertIn("infer_target_genome_from_existing_outputs()", text)
        self.assertIn("mode_includes_track()", text)
        self.assertIn("can_run_existing_panels_without_target()", text)

    def test_metadata_template_is_runtime_local_not_repo_rewritten(self) -> None:
        normalize_text = (REPO_ROOT / "bin" / "normalize_metadata.py").read_text(encoding="utf-8")
        summary_text = (REPO_ROOT / "summarize_clusterweave.sh").read_text(encoding="utf-8")
        self.assertIn('ecofun_metadata_template.tsv', normalize_text)
        self.assertIn('--template-out "${METADATA_TEMPLATE_TSV}"', summary_text)
        self.assertNotIn('template_default = project_root / "config" / "metadata_template.tsv"', normalize_text)

    def test_wrapper_writes_provenance_manifest(self) -> None:
        text = (REPO_ROOT / "run_clusterweave.sh").read_text(encoding="utf-8")
        self.assertIn("write_provenance_manifest()", text)
        self.assertIn("write_external_artifacts_manifest()", text)
        self.assertIn('REPRO_ROOT="${REPRO_ROOT:-${RESULTS_ROOT}/reproducibility}"', text)
        self.assertIn('CAPTURE_EXTERNAL_ARTIFACTS="${CAPTURE_EXTERNAL_ARTIFACTS:-1}"', text)
        self.assertIn("printf 'run_stage_annotation", text)
        self.assertIn("printf 'capture_external_artifacts", text)
        self.assertIn("printf 'clinker_mode", text)

    def test_bigscape_has_stage_specific_sif_source_aliases(self) -> None:
        text = (REPO_ROOT / "run_bigscape.sh").read_text(encoding="utf-8")
        self.assertIn('BIGSCAPE_SIF_PATH="${BIGSCAPE_SIF_PATH:-${BIGSCAPE_SOFTDIR}/bigscape_2.0.0-beta.6.sif}"', text)
        self.assertIn('BIGSCAPE_SIF_SOURCE="${BIGSCAPE_SIF_SOURCE:-docker://ghcr.io/medema-group/big-scape:2.0.0-beta.6}"', text)
        self.assertIn('SIF_PATH="${SIF_PATH:-${BIGSCAPE_SIF_PATH}}"', text)
        self.assertIn('SIF_SOURCE="${SIF_SOURCE:-${BIGSCAPE_SIF_SOURCE}}"', text)
        self.assertIn('BIGSCAPE_USE_DOCKER_IMAGE="${BIGSCAPE_USE_DOCKER_IMAGE:-0}"', text)
        self.assertIn('BIGSCAPE_DOCKER_IMAGE="${BIGSCAPE_DOCKER_IMAGE:-ghcr.io/medema-group/big-scape:2.0.0-beta.6}"', text)
        self.assertIn('local -a args=(--rm -i --user 0:0 --entrypoint "")', text)

    def test_web_lab_runtime_is_docker_gated(self) -> None:
        compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        public_compose = (REPO_ROOT / "clusterweave.yml").read_text(encoding="utf-8")
        self.assertIn("CLUSTERWEAVE_RUNTIME_MODE: lab-docker", compose)
        self.assertIn("CLUSTERWEAVE_ENABLE_DOCKER_SOCKET: \"1\"", compose)
        self.assertIn("ENGINE: docker", compose)
        self.assertIn('WORKER_CONCURRENCY: "${WORKER_CONCURRENCY:-1}"', compose)
        self.assertIn("/var/run/docker.sock:/var/run/docker.sock", compose)
        self.assertIn("CLUSTERWEAVE_RUNTIME_MODE: public-queue", public_compose)
        self.assertIn("CLUSTERWEAVE_ENABLE_DOCKER_SOCKET: \"0\"", public_compose)
        self.assertIn('WORKER_CONCURRENCY: "${WORKER_CONCURRENCY:-1}"', public_compose)
        self.assertNotIn("/var/run/docker.sock:/var/run/docker.sock", public_compose)

    def test_canonical_bridge_passes_runtime_env(self) -> None:
        text = (REPO_ROOT / "web" / "canonical_pipeline.py").read_text(encoding="utf-8")
        self.assertIn('"ENGINE": _cfg_str(settings, "engine", os.environ.get("ENGINE", ""))', text)
        self.assertIn('"reuse_existing_layout"', text)
        self.assertIn('"DOCKER_DATA_VOLUME"', text)
        self.assertIn('"FUNBGCEX_DOCKER_IMAGE"', text)
        self.assertIn('"CLINKER_USE_DOCKER_IMAGE"', text)
        self.assertIn('"NPLINKER_DOCKER_IMAGE"', text)
        self.assertIn('"RENDER_BIGSCAPE_NETWORK_PY"', text)

    def test_web_supports_in_place_stage_reruns(self) -> None:
        app_text = (REPO_ROOT / "web" / "app.py").read_text(encoding="utf-8")
        ui_text = (REPO_ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('route.startswith("/api/jobs/") and route.endswith("/rerun")', app_text)
        self.assertIn('"reuse_existing_layout"] = True', app_text)
        self.assertIn('"submission_settings"', app_text)
        self.assertIn("Rerun Selected Stages", ui_text)
        self.assertIn('class="summary-panel rerun-summary"', ui_text)
        self.assertIn("rerunActiveJob()", ui_text)
        self.assertIn("function rerunStageAllowed(key)", ui_text)

    def test_worker_supports_bounded_concurrency(self) -> None:
        text = (REPO_ROOT / "web" / "worker.py").read_text(encoding="utf-8")
        self.assertIn('WORKER_CONCURRENCY = max(1, int(os.environ.get("WORKER_CONCURRENCY", "1")))', text)
        self.assertIn("async def worker_loop()", text)
        self.assertIn("active_jobs", text)
        self.assertIn("payload = dict(read_job(job.id) or {})", text)

    def test_ui_stage_states_use_semantic_classes(self) -> None:
        text = (REPO_ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn(".stage-step.upcoming", text)
        self.assertIn(".stage-step.active", text)
        self.assertIn(".stage-step.done", text)
        self.assertIn(".stage-step.disabled", text)
        self.assertIn("function initializeStageState(job)", text)
        self.assertIn("function finalizeStageState(status)", text)

    def test_web_visualization_is_limited_to_figure_outputs(self) -> None:
        text = (REPO_ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn("function isFigureAsset(path)", text)
        self.assertNotIn("function renderOutputDiscovery(jobId, files, status)", text)
        self.assertNotIn('id="output-discovery"', text)
        self.assertIn("function figureCaption(path)", text)
        self.assertIn("function handleFigureWheel(event, wrap)", text)
        self.assertIn("function handleFigurePointerDown(event, wrap)", text)
        self.assertIn("function hydrateSvgFigures(jobId)", text)
        self.assertIn("function inlineResultMime(relPath", text)
        self.assertIn("figure-zoom-controls", text)
        self.assertIn("figure-svg-stage", text)
        self.assertIn("figure-svg-preview", text)
        self.assertIn("onwheel=\"handleFigureWheel(event,this)\"", text)
        self.assertIn('Data\\/Results\\/[^/]+\\/figures', text)
        self.assertIn("bgc_calls_by_tool_category.svg", text)
        self.assertIn("bigscape_network.svg", text)
        self.assertIn("const downloadHref = resultHref(jobId, f, { download: true })", text)
        self.assertIn("<th>Result Path</th>", text)
        self.assertNotIn("const htmlFiles = files.filter", text)

    def test_web_results_tabs_are_keyboard_accessible(self) -> None:
        text = (REPO_ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('role="tablist"', text)
        self.assertIn('button class="tab active"', text)
        self.assertIn('role="tab"', text)
        self.assertIn('aria-selected="true"', text)
        self.assertIn('role="tabpanel"', text)
        self.assertIn("function handleResultTabKeydown(event)", text)
        self.assertIn("tab.setAttribute('aria-selected'", text)
        self.assertIn("panel.hidden = !active", text)

    def test_web_files_tab_groups_results_into_collapsible_folders(self) -> None:
        text = (REPO_ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn("function buildFileTree(files)", text)
        self.assertIn("function renderFileFolder(jobId, node, depth = 0)", text)
        self.assertIn("function handleFileFolderToggle(detailsEl)", text)
        self.assertIn('<details class="file-folder"', text)
        self.assertIn('<summary class="file-folder-summary">', text)
        self.assertIn("data-rendered", text)
        self.assertIn("file-folder-count", text)
        self.assertIn("function defaultFolderOpen(path, depth)", text)
        self.assertIn("normalized === 'downloads'", text)
        self.assertIn('Data\\/Results\\/[^/]+\\/figures', text)
        self.assertIn("renderFileRows(jobId, node.files)", text)
        self.assertIn("renderFileRow(jobId, f)", text)
        self.assertIn('<span class="file-path-link">${escapeHtml(normalizedResultPath(f))}</span>', text)
        self.assertNotIn('<a class="file-path-link"', text)
        self.assertIn("resultHref(jobId, f, { download: true })", text)

    def test_web_upload_supports_manual_accession_entry(self) -> None:
        text = (REPO_ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="manual-accessions"', text)
        self.assertIn("function manualAccessionLines()", text)
        self.assertIn("const MANUAL_ACCESSIONS_FILENAME = 'manual_accessions.txt'", text)
        self.assertIn("manualLines.join('\\n') + '\\n'", text)
        self.assertIn("new File([manualAccessionText], MANUAL_ACCESSIONS_FILENAME", text)
        self.assertIn("input source(s) ready", text)

    def test_web_has_journey_first_navigation_and_hero(self) -> None:
        text = (REPO_ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="primary-nav"', text)
        self.assertIn('data-nav-target="overview"', text)
        self.assertIn('data-nav-target="intake"', text)
        self.assertIn('data-nav-target="runs"', text)
        self.assertIn('data-nav-target="outputs"', text)
        self.assertIn('data-nav-target="qa"', text)
        self.assertIn('data-nav-target="docs"', text)
        self.assertIn('id="runtime-status-chip"', text)
        self.assertIn('id="weavemap"', text)
        self.assertIn('class="helix-cross"', text)
        self.assertIn("function navigateToSection(event, target", text)
        self.assertIn("function loadDemoAccessions(event)", text)
        self.assertIn("const demoAccessions = ['GCA_000011425.1', 'GCA_030770425.1'];", text)
        self.assertIn("Start from NCBI accessions", text)
        self.assertIn("Load demo run", text)
        self.assertIn("Upload genomes or accessions, run biosynthetic gene cluster discovery stages", text)
        self.assertIn("If you have found ClusterWeave useful", text)
        self.assertIn("data-citation-link", text)
        self.assertNotIn("Methods, artifacts, logs, and runtime notes", text)
        self.assertNotIn('class="docs-links"', text)
        self.assertNotIn('href="#weavemap" data-nav-target="weavemap"', text)
        self.assertNotIn("hero-weavemap", text)

    def test_web_has_user_modes_and_section_hierarchy(self) -> None:
        text = (REPO_ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('data-ui-mode="guided"', text)
        self.assertNotIn('id="mode-panel"', text)
        self.assertNotIn('data-mode-option="guided"', text)
        self.assertNotIn('data-mode-option="lab"', text)
        self.assertNotIn('data-mode-option="advanced"', text)
        self.assertIn("function setUIMode(mode", text)
        self.assertIn("body[data-ui-mode=\"guided\"] #console-card", text)
        self.assertIn('id="workflow-controls"', text)
        self.assertIn("Workflow controls", text)
        self.assertIn('id="advanced-panel"', text)
        self.assertIn("Runs / Run History", text)
        self.assertIn("if (target === 'qa' && currentUIMode === 'guided') setUIMode('lab'", text)
        self.assertIn("if (accessMode === 'public' && mode !== 'guided') mode = 'guided'", text)

    def test_web_has_neumorphic_surface_system_tokens(self) -> None:
        text = (REPO_ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
        for token in [
            "--cw-surface-panel",
            "--cw-surface-well",
            "--cw-surface-control",
            "--cw-surface-output",
            "--cw-raise-panel",
            "--cw-raise-panel-strong",
            "--cw-inset-well",
            "--cw-inset-control",
            "--cw-bevel",
            "--cw-glow-soft",
            "--cw-terminal-shadow",
        ]:
            self.assertIn(token, text)
        self.assertIn(".card {", text)
        self.assertIn(".upload-zone {", text)
        self.assertIn(".stage-step {", text)
        self.assertIn(".job-card {", text)
        self.assertIn(".figure-panel {", text)
        self.assertIn("box-shadow: var(--cw-terminal-shadow), var(--cw-bevel);", text)
        self.assertIn("box-shadow: var(--cw-pressed), inset 3px 0 0 var(--accent)", text)

    def test_web_has_retrofuturist_weavemap_and_outputs_polish(self) -> None:
        text = (REPO_ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('class="weavemap-section section-anchor hidden" id="weavemap"', text)
        self.assertIn('id="workflow-progress-panel"', text)
        self.assertIn('id="results-workflow-host"', text)
        self.assertIn('id="stage-bar"', text)
        self.assertIn("weavemap-signal", text)
        self.assertIn('id="weavemap-helix"', text)
        self.assertIn("dna-active-ring", text)
        self.assertIn("dna-popover-trigger", text)
        self.assertIn(".dna-base-popover:hover .dna-popover-panel", text)
        self.assertIn("hover-restored", text)
        self.assertIn("renderWeaveHelix(activeJobMeta)", text)
        self.assertIn("publicStageNodes", text)
        self.assertIn("helix.dataset.renderKey", text)
        self.assertIn("scrollPositions", text)
        self.assertIn("shell-first controller", text)
        for stage in [
            'data-stage="prep"',
            'data-stage="annotation"',
            'data-stage="bigscape"',
            'data-stage="summary"',
            'data-stage="clinker"',
            'data-stage="figures"',
            'data-stage="nplinker"',
        ]:
            self.assertIn(stage, text)
        for label in [
            "Intake",
            "Prep",
            "Annotation / BGC detection",
            "BiG-SCAPE",
            "Summary",
            "clinker",
            "Figures",
            "NPLinker",
            "Outputs",
        ]:
            self.assertIn(label, text)
        self.assertNotIn("Prioritized BGC shortlist", text)
        self.assertNotIn("Gene cluster family context", text)
        self.assertNotIn("Synteny / clinker panel", text)
        self.assertNotIn("Artifacts / files", text)
        self.assertNotIn("Run a workflow to populate this panel.", text)
        self.assertNotIn("No artifacts available yet.", text)
        self.assertNotIn("NPLinker optional follow-up not enabled.", text)
        self.assertIn('body[data-ui-mode="guided"] #console-card .terminal-shell::before', text)
        self.assertIn(".weavemap-signal,", text)
        self.assertIn("function moveWorkflowProgressIntoResults()", text)
        self.assertNotIn('class="hero-weavemap section-anchor" id="weavemap"', text)
        self.assertNotIn("dna-status-strip", text)
        self.assertNotIn("Heartbeat", text)
        self.assertNotIn('<details class="dna-base-popover', text)

    def test_web_job_queue_clicks_guard_against_stale_result_loads(self) -> None:
        text = (REPO_ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn("let jobLoadSeq = 0", text)
        self.assertIn("function markActiveJobCard(jobId)", text)
        self.assertIn("let jobHistoryInFlight = false", text)
        self.assertIn("function renderJobHistory(jobs)", text)
        self.assertIn("function jobHistoryRenderKey(jobs)", text)
        self.assertIn("const seq = ++jobLoadSeq", text)
        self.assertIn("loadResults(jobId, job.status, seq, job)", text)
        self.assertIn("seq !== jobLoadSeq || jobId !== activeJobId", text)

    def test_web_api_calls_work_behind_path_prefixed_proxies(self) -> None:
        text = (REPO_ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn("function apiUrl(path)", text)
        self.assertIn("function defaultApiBaseUrl()", text)
        self.assertIn("window.CLUSTERWEAVE_API_BASE", text)
        self.assertIn("apiFetch('api/system/status'", text)
        self.assertIn("apiFetch('api/jobs'", text)
        self.assertIn("const base = apiUrl(`api/jobs/", text)
        self.assertNotIn("fetch('/api/", text)
        self.assertNotIn('fetch("/api/', text)

    def test_web_public_ui_restructure_gates_admin_surfaces(self) -> None:
        text = (REPO_ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('data-access="public"', text)
        self.assertIn('id="access-panel"', text)
        self.assertIn('id="submit-token"', text)
        self.assertIn('id="admin-token"', text)
        self.assertIn('id="existing-run-link"', text)
        self.assertIn('id="existing-run-token"', text)
        self.assertIn('id="opened-runs-select"', text)
        self.assertIn("sessionStorage.setItem", text)
        self.assertIn("function parseExistingRunInput()", text)
        self.assertIn("function rememberOpenedRun(jobId, token", text)
        self.assertIn("function authHeadersFor(kind, jobId = null)", text)
        self.assertIn("function handleResultLinkClick(event, jobId, relPath, download = false)", text)
        self.assertIn('body[data-access="public"] .admin-only', text)
        self.assertNotIn('class="mode-panel section-anchor admin-only"', text)
        self.assertIn('class="card section-anchor admin-only" id="jobs-card"', text)
        self.assertIn('class="card telemetry-card section-anchor admin-only" id="console-card"', text)
        self.assertIn('id="workflow-controls"', text)
        self.assertIn('workflow-controls admin-only', text)
        self.assertIn('id="advanced-panel"', text)
        self.assertIn('advanced-wrap admin-only', text)
        self.assertIn('id="rerun-panel" class="admin-only"', text)
        self.assertNotIn('id="output-discovery"', text)
        self.assertNotIn('results-intel admin-only', text)
        self.assertIn("Submit or load an existing run to see stage progress.", text)
        self.assertIn("body[data-access=\"public\"] .stage-step[data-stage=\"nplinker\"]", text)
        self.assertIn("const PUBLIC_FILE_EXTENSIONS = new Set(['gbk','gb','gbff','fasta','fa','fna','fsa','txt']);", text)
        self.assertNotIn("submit_token=", text)
        self.assertNotIn("admin_token=", text)

    def test_web_email_and_retention_slice_has_public_recovery_hooks(self) -> None:
        ui_text = (REPO_ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
        app_text = (REPO_ROOT / "web" / "app.py").read_text(encoding="utf-8")
        worker_text = (REPO_ROOT / "web" / "worker.py").read_text(encoding="utf-8")
        notifications_text = (REPO_ROOT / "web" / "notifications.py").read_text(encoding="utf-8")
        job_store_text = (REPO_ROOT / "web" / "job_store.py").read_text(encoding="utf-8")
        maintenance_text = (REPO_ROOT / "web" / "maintenance.py").read_text(encoding="utf-8")

        self.assertIn('id="email-notification-panel"', ui_text)
        self.assertIn('id="notify-email"', ui_text)
        self.assertIn("let smtpEnabled = false", ui_text)
        self.assertIn("smtpEnabled = !!payload.smtp_enabled", ui_text)
        self.assertIn("fd.append('notify_email', notifyEmail)", ui_text)
        self.assertIn('SMTP_ENABLED = env_bool("CLUSTERWEAVE_SMTP_ENABLED"', app_text)
        self.assertIn('"smtp_enabled": SMTP_ENABLED', app_text)
        self.assertIn('"notify_email"', app_text)
        self.assertIn("maybe_send_terminal_notification(job_id)", worker_text)
        self.assertIn("def build_job_email", notifications_text)
        self.assertIn("Suggested fixes:", notifications_text)
        self.assertIn("def sweep_expired_jobs", job_store_text)
        self.assertIn("CLUSTERWEAVE_ALLOW_NEVER_EXPIRE_JOBS", job_store_text)
        self.assertIn("sweep_expired_jobs()", maintenance_text)

    def test_web_ecology_label_table_uses_controlled_public_inputs(self) -> None:
        text = (REPO_ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="ecology-label-panel"', text)
        self.assertIn('id="run-ecology"', text)
        self.assertIn('<th>Input</th><th>Primary ecology</th><th>Secondary ecology</th>', text)
        self.assertIn("const ECOLOGY_LABELS = [", text)
        for label in [
            "soil",
            "plant_associated",
            "endophyte",
            "mycorrhiza",
            "plant_pathogen",
            "saprotroph",
            "marine",
            "freshwater",
            "lichen_associated",
            "insect_associated",
            "animal_associated",
            "human_associated",
            "food_fermentation",
            "unknown",
            "other",
        ]:
            self.assertIn(f"'{label}'", text)
        self.assertIn("function ecologyInputRows()", text)
        self.assertIn("manualAccessionLines().forEach(accession => addRow(accession, 'NCBI accession', accession));", text)
        self.assertIn("addRow(genomeStemFromName(file.name), 'Genome file', '')", text)
        self.assertIn("function syncEcologyMetadataPanel()", text)
        self.assertIn("function metadataProfileText()", text)
        self.assertIn("accession\\tgenome_id_current\\ttaxonomy_id\\tgenome_size_mb\\tgenome_id_original_if_different\\tecofun_primary\\tecofun_secondary", text)
        self.assertIn("unlabeled inputs may reduce ranking usefulness", text)
        self.assertIn('id="metadata-tsv"', text)
        self.assertIn('advanced-wrap admin-only', text)
        self.assertNotIn("Editable Ecology Metadata", text)
        self.assertNotIn("addMetadataRow()", text)

    def test_web_serves_result_assets_inline_unless_download_requested(self) -> None:
        text = (REPO_ROOT / "web" / "app.py").read_text(encoding="utf-8")
        self.assertIn('"image/svg+xml; charset=utf-8"', text)
        self.assertIn('"Cache-Control": "no-store"', text)
        self.assertIn("def result_file_mime(path: Path) -> str:", text)
        self.assertIn("def content_disposition(disposition: str, filename: str) -> str:", text)
        self.assertIn('"attachment" if parse_bool(query.get("download", ["0"])[0], False) else "inline"', text)
        self.assertIn('"Content-Disposition": content_disposition(disposition, full.name)', text)

    def test_figures_wrapper_detects_rscript_robustly(self) -> None:
        text = (REPO_ROOT / "run_figures.sh").read_text(encoding="utf-8")
        self.assertIn("resolve_r_bin()", text)
        self.assertIn('/mnt/c/Program Files/R/R-*/bin/Rscript.exe', text)
        self.assertIn('/c/Program Files/R/R-*/bin/Rscript.exe', text)
        self.assertIn('R_BIN="$(resolve_r_bin)"', text)
        self.assertIn('RENDER_BIGSCAPE_NETWORK_PY="${RENDER_BIGSCAPE_NETWORK_PY:-${SCRIPT_DIR}/bin/render_bigscape_network.py}"', text)
        self.assertIn("Skipping R summary figures; continuing to BiG-SCAPE network rendering", text)
        self.assertIn("skipping network figure", text)
        self.assertNotIn("FIGURES_TOP_N", text)

    def test_worker_image_includes_rscript_for_figures(self) -> None:
        text = (REPO_ROOT / "Dockerfile.worker").read_text(encoding="utf-8")
        self.assertIn("r-base-core", text)

    def test_render_summary_figures_focuses_on_core_summary_outputs(self) -> None:
        text = (REPO_ROOT / "bin" / "render_summary_figures.R").read_text(encoding="utf-8")
        self.assertIn("bgc_calls_by_tool_category.svg", text)
        self.assertIn("total ~ class_norm + genome + tool", text)
        self.assertIn("BGC calls by genome and tool", text)
        self.assertNotIn("shared_vs_unshared_bgc_calls", text)
        self.assertNotIn("plot_shared_unshared", text)
        self.assertNotIn("plot_priority_scores", text)
        self.assertNotIn("ranking_path", text)

    def test_clinker_postprocess_uses_repo_root(self) -> None:
        text = (REPO_ROOT / "bin" / "stage_clinker_panels.py").read_text(encoding="utf-8")
        self.assertIn('POSTPROCESS_PY=\\"${PROJECT_ROOT}/bin/postprocess_clinker_html.py\\"', text)
        self.assertIn("project_root.resolve().as_posix()", text)

    def test_clinker_postprocess_normalizes_augmented_labels(self) -> None:
        text = (REPO_ROOT / "bin" / "postprocess_clinker_html.py").read_text(encoding="utf-8")
        self.assertIn("def simplify_identifier", text)
        self.assertIn("def normalize_locus_name", text)
        self.assertIn('gene["label"] = preferred_gene_label(gene)', text)
        self.assertIn('locus["name"] = locus_name', text)

    def test_stage_clinker_supports_atlas_without_target(self) -> None:
        text = (REPO_ROOT / "bin" / "stage_clinker_panels.py").read_text(encoding="utf-8")
        self.assertIn("Leave unset for dataset-wide atlas staging.", text)
        self.assertIn('or row.get("atlas_rank")', text)
        self.assertNotIn('raise ValueError("--genome is required")', text)

    def test_dataset_family_atlas_exporter_exists(self) -> None:
        self.assertTrue((REPO_ROOT / "bin" / "export_dataset_family_atlas.py").exists())

    def test_funbgcex_build_recipe_exists(self) -> None:
        for rel in [
            "Software/funbgcex/build_funbgcex_sif.sh",
            "Software/funbgcex/Dockerfile",
            "Software/funbgcex/Singularity.def",
        ]:
            self.assertTrue((REPO_ROOT / rel).exists(), rel)

    def test_gitignore_unignores_funbgcex_text_recipes(self) -> None:
        text = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        for pattern in [
            "!Software/funbgcex/",
            "Software/funbgcex/**",
            "!Software/funbgcex/build_funbgcex_sif.sh",
            "!Software/funbgcex/Dockerfile",
            "!Software/funbgcex/Singularity.def",
        ]:
            self.assertIn(pattern, text)

    def test_ci_workflow_exists(self) -> None:
        self.assertTrue((REPO_ROOT / ".github" / "workflows" / "ci.yml").exists())

    def test_release_profile_exists(self) -> None:
        profile = REPO_ROOT / "profiles" / "release_v0.1.0.env"
        self.assertTrue(profile.exists())
        text = profile.read_text(encoding="utf-8")
        self.assertIn("PROJECT_NAME=clusterweave_smoke", text)
        self.assertIn("CAPTURE_EXTERNAL_ARTIFACTS=1", text)
        self.assertIn("AUTO_DOWNLOAD_PFAM=0", text)
        self.assertIn("AUTO_DOWNLOAD_FASTTREE=0", text)
        self.assertIn("INSTALL_CLINKER_SIF=0", text)


if __name__ == "__main__":
    unittest.main()
