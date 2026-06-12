import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]


def frontend_text() -> str:
    static_dir = REPO_ROOT / "web" / "static"
    parts = [
        static_dir / "index.html",
        static_dir / "assets" / "clusterweave.css",
        static_dir / "assets" / "clusterweave.js",
    ]
    return "\n".join(path.read_text(encoding="utf-8") for path in parts)


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
            "bin/render_bigscape_multipanel.py",
        ]:
            self.assertTrue((REPO_ROOT / rel).exists(), rel)

    def test_ncbi_rename_is_idempotent_for_already_renamed_package_dir(self) -> None:
        fungus_id = "Amanita_muscaria_2016PMI152"
        report = {
            "organism": {
                "organismName": "Amanita muscaria strain 2016PMI152",
                "taxId": 41956,
            },
            "assemblyStats": {"totalSequenceLength": 2},
        }
        with tempfile.TemporaryDirectory() as tmp:
            genome_root = Path(tmp) / "genomes"
            data_dir = genome_root / fungus_id / "ncbi_dataset" / "data"
            package_dir = data_dir / fungus_id
            package_dir.mkdir(parents=True)
            (data_dir / "assembly_data_report.jsonl").write_text(json.dumps(report) + "\n", encoding="utf-8")
            (package_dir / f"{fungus_id}.fna").write_text(">seq\nAC\n", encoding="utf-8")
            (package_dir / f"{fungus_id}.gff").write_text("##gff-version 3\n", encoding="utf-8")
            (package_dir / f"{fungus_id}.gbff").write_text("LOCUS       seq 2 bp DNA\n", encoding="utf-8")

            env = dict(os.environ)
            env["GENOME_ROOT"] = str(genome_root)
            env["PYTHON_BIN"] = sys.executable
            subprocess.run(
                ["bash", str(REPO_ROOT / "scripts" / "ncbi" / "rename_ncbi_genomes.sh")],
                cwd=str(REPO_ROOT),
                env=env,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertTrue(package_dir.exists())
            self.assertFalse((package_dir / fungus_id).exists())

    def test_ncbi_flatten_skips_accession_alias_when_canonical_files_exist(self) -> None:
        accession = "GCA_017499595.2"
        fungus_id = "Psilocybe_cubensis_MGC-MH-2018"
        with tempfile.TemporaryDirectory() as tmp:
            genome_root = Path(tmp) / "genomes"
            genome_root.mkdir(parents=True)
            for ext in ["fna", "gff", "gbff"]:
                (genome_root / f"{fungus_id}.{ext}").write_text(f"canonical {ext}\n", encoding="utf-8")
            (genome_root / "accessions_fungusID_taxonomyID.txt").write_text(
                f"{accession}\t{fungus_id}\t181762\t46.39\n",
                encoding="utf-8",
            )
            package_dir = genome_root / accession / "ncbi_dataset" / "data" / accession
            package_dir.mkdir(parents=True)
            for ext in ["fna", "gff", "gbff"]:
                (package_dir / f"{accession}.{ext}").write_text(f"alias {ext}\n", encoding="utf-8")

            env = dict(os.environ)
            env["GENOME_ROOT"] = str(genome_root)
            result = subprocess.run(
                ["bash", str(REPO_ROOT / "scripts" / "ncbi" / "flatten_ncbi_genomes.sh")],
                cwd=str(REPO_ROOT),
                env=env,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertIn("skipping accession alias flatten", result.stderr)
            self.assertFalse((genome_root / f"{accession}.fna").exists())
            self.assertFalse((genome_root / f"{accession}.gff").exists())
            self.assertFalse((genome_root / f"{accession}.gbff").exists())
            self.assertTrue((package_dir / f"{accession}.fna").exists())

    def test_annotation_discovery_filters_accession_aliases(self) -> None:
        text = (REPO_ROOT / "run_annotation_and_detection.sh").read_text(encoding="utf-8")
        self.assertIn("mapped_canonical_stem()", text)
        self.assertIn("should_skip_discovered_stem", text)
        self.assertIn("skipping accession alias genome stem", text)

    def test_antismash_done_requires_complete_browseable_output(self) -> None:
        text = (REPO_ROOT / "run_annotation_and_detection.sh").read_text(encoding="utf-8")
        block = text.split("antismash_done() {", 1)[1].split("funbgcex_done()", 1)[0]
        self.assertIn("[[ -s \"${outdir}/index.html\" ]] || return 1", block)
        self.assertIn("-name \"regions.js\"", block)
        self.assertIn("-name \"*.antismash.json\"", block)
        self.assertNotIn("*region*.gbk", block)
        self.assertNotIn("##antiSMASH-Data-START##", block)

    def test_release_metadata_exists(self) -> None:
        for rel in [
            "README.md",
            "BEGINNER_SETUP.md",
            "LICENSE",
            "CITATION.cff",
            "THIRD_PARTY.md",
            "DATA_SOURCES.md",
            "web/OPERATOR_AGREEMENT.md",
            "docs/REPRODUCIBILITY.md",
            "docs/WEB_RUNTIME.md",
            "pyproject.toml",
        ]:
            self.assertTrue((REPO_ROOT / rel).exists(), rel)

    def test_private_web_handoff_docs_are_ignored(self) -> None:
        gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        dockerignore = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8")
        for rel in [
            "web/STAN.md",
            "web/STYLE.md",
            "web/UI_SLICE_ARCHIVE.md",
            "web/GLOSSARY.md",
            "web/UPSTREAM_MAINTAINER_NOTE.md",
        ]:
            with self.subTest(rel=rel):
                self.assertIn(rel, gitignore)
                self.assertIn(rel, dockerignore)

    def test_generic_example_paths_exist(self) -> None:
        self.assertTrue((REPO_ROOT / "profiles" / "example_project.env").exists())
        self.assertTrue((REPO_ROOT / "examples" / "example_project" / "README.md").exists())

    def test_lowercase_runtime_roots_exist(self) -> None:
        for rel in [
            "data/genomes/fungi/.gitkeep",
            "data/results/.gitkeep",
            "software/.gitkeep",
            "software/funbgcex/Dockerfile",
            "software/funbgcex/Singularity.def",
        ]:
            self.assertTrue((REPO_ROOT / rel).exists(), rel)
        self.assertFalse((REPO_ROOT / "Data").exists())
        self.assertFalse((REPO_ROOT / "Software").exists())

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
        self.assertIn('local genome_dir="${DATA_ROOT}/genomes/fungi/${PROJECT_NAME}"', text)
        self.assertIn("generating a blank normalized scaffold from genome files", text)
        self.assertIn('--genome-dir "${genome_dir}"', text)
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
        self.assertIn('CLUSTERWEAVE_PUBLIC_MODE: "${CLUSTERWEAVE_PUBLIC_MODE:-1}"', public_compose)
        self.assertIn('CLUSTERWEAVE_JOB_TOKEN_SECRET: "${CLUSTERWEAVE_JOB_TOKEN_SECRET:-}"', public_compose)
        self.assertIn('WORKER_CONCURRENCY: "${WORKER_CONCURRENCY:-1}"', public_compose)
        self.assertNotIn("/var/run/docker.sock:/var/run/docker.sock", public_compose)

    def test_public_release_files_do_not_contain_private_handoff_markers(self) -> None:
        release_files = [
            "README.md",
            "DATA_SOURCES.md",
            "THIRD_PARTY.md",
            "docs/RELEASE_CHECKLIST.md",
            "docs/WEB_RUNTIME.md",
            "manuscript/application_note/outline.md",
            "examples/example_project/clusterweave_smoke_derived_outputs/README.md",
            "examples/example_project/clusterweave_smoke_derived_outputs/summary/family_atlas_shortlist.md",
            "docker-compose.yml",
            "clusterweave.yml",
            "web/OPERATOR_AGREEMENT.md",
        ]
        forbidden = [
            "OneDrive",
            "10.64.195.209",
            "dev-admin",
            "dev-change-me",
            "/home/cloud",
            "/mnt/c/Users",
        ]
        for rel in release_files:
            text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")
            for marker in forbidden:
                with self.subTest(file=rel, marker=marker):
                    self.assertNotIn(marker, text)

    def test_frontend_static_assets_are_extracted_without_new_dependencies(self) -> None:
        static_dir = REPO_ROOT / "web" / "static"
        index_text = (static_dir / "index.html").read_text(encoding="utf-8")
        css_text = (static_dir / "assets" / "clusterweave.css").read_text(encoding="utf-8")
        js_text = (static_dir / "assets" / "clusterweave.js").read_text(encoding="utf-8")

        self.assertLess(len(index_text.splitlines()), 1000)
        self.assertIn('href="assets/clusterweave.css?v=20260612-ncbi-preflight"', index_text)
        self.assertIn('src="assets/clusterweave.js?v=20260612-ncbi-preflight"', index_text)
        self.assertNotIn("<style>", index_text)
        self.assertNotIn("<script>\n", index_text)
        self.assertIn("function apiUrl(path)", js_text)
        self.assertIn("function handleResultLinkClick(event, jobId, relPath, download = false)", js_text)
        self.assertIn("function resultLollipopItems", js_text)
        self.assertIn("resultCategoryLabel('synteny')", js_text)
        self.assertIn('body[data-access="public"] .admin-only', css_text)
        self.assertNotIn("https://cdn", index_text + css_text + js_text)
        self.assertNotIn("unpkg.com", index_text + css_text + js_text)

    def test_web_results_run_switch_keeps_dashboard_spine_open(self) -> None:
        ui_text = frontend_text()
        self.assertIn("function shouldPreserveResultsDashboardForJobLoad(jobId, options = {})", ui_text)
        self.assertIn("runHasKnownResultFiles(historyJob)", ui_text)
        self.assertIn("const preferResultsDashboard = shouldPreserveResultsDashboardForJobLoad(jobId, options);", ui_text)
        self.assertIn("document.body.dataset.resultsDashboard = preferResultsDashboard ? 'open' : 'closed';", ui_text)
        self.assertIn("shouldOpenResultDashboardDuringRefresh(normalizedFiles, activeJobMeta)", ui_text)
        self.assertIn("width: min(64rem, calc(100vw - var(--result-focus-width", ui_text)
        self.assertNotIn("body[data-access=\"admin\"][data-results-dashboard=\"open\"] .spine-field,\n    body[data-access=\"local\"][data-results-dashboard=\"open\"] .spine-field {\n      left: clamp(3.25rem", ui_text)

    def test_web_result_focus_and_archive_state_are_run_scoped(self) -> None:
        ui_text = frontend_text()
        self.assertIn("let resultArchiveRequestSeq = 0;", ui_text)
        self.assertIn("let activeArchiveDownload = null;", ui_text)
        self.assertIn("function cancelActiveArchiveDownload()", ui_text)
        self.assertIn("const requestJobId = activeJobId;", ui_text)
        self.assertIn("const requestId = ++resultArchiveRequestSeq;", ui_text)
        self.assertIn("activeArchiveDownload = { jobId: requestJobId, requestId, controller };", ui_text)
        self.assertIn("if (activeJobId !== requestJobId || activeArchiveDownload?.requestId !== requestId) return false;", ui_text)
        self.assertIn("cancelActiveArchiveDownload();", ui_text)
        self.assertIn("function renderResultFileSurface(jobId, files)", ui_text)
        self.assertIn("if (resultFocusMode === 'focused')", ui_text)
        self.assertIn("renderFocusedResultCategory(activeResultCategory);", ui_text)
        self.assertIn("renderResultFileSurface(jobId, normalizedFiles);", ui_text)

    def test_web_results_access_panel_is_side_collapsible(self) -> None:
        ui_text = frontend_text()
        self.assertIn('data-results-panel="collapsed"', ui_text)
        self.assertIn('id="results-panel-toggle"', ui_text)
        self.assertIn("function setResultsPanelCollapsed(collapsed)", ui_text)
        self.assertIn("function toggleResultsPanel()", ui_text)
        self.assertIn('body[data-results-dashboard="open"][data-results-panel="collapsed"] #results-card', ui_text)
        self.assertIn('body[data-results-dashboard="open"][data-results-panel="open"] #results-card', ui_text)
        self.assertIn(".results-panel-toggle", ui_text)
        self.assertNotIn('body[data-results-dashboard="open"] #results-card { display: none !important; }', ui_text)

    def test_web_synteny_labels_skip_track_folders(self) -> None:
        ui_text = frontend_text()
        self.assertIn("atlas|priority|prioritized?|shared[-_]?family|shared|family|track|tracks", ui_text)
        self.assertIn("compound = titleCaseArtifactLabel(parts[i], 'clinker');", ui_text)
        self.assertIn("`${compound} - ${artifact}`", ui_text)

    def test_web_dna_spine_uses_continuous_ribbons(self) -> None:
        ui_text = frontend_text()
        self.assertIn("data-ribbon=\"continuous\"", ui_text)
        self.assertIn("stroke-width: 32;", ui_text)
        self.assertIn("stroke-width: 44;", ui_text)
        self.assertNotIn("data-segment=", ui_text)
        self.assertNotIn("Math.ceil(span * Number(layout.turns || 3) * 10)", ui_text)

    def test_frontend_opens_generated_html_for_private_result_users(self) -> None:
        ui_text = frontend_text()
        self.assertIn("function canOpenRichHtmlArtifacts(jobId = activeJobId)", ui_text)
        self.assertIn("return canUseAdminSurfaces() || !!readTokenForJob(jobId);", ui_text)
        self.assertIn("if (canOpenRichHtmlArtifacts(jobId)) return openHtmlResultWithAssets(event, jobId, relPath);", ui_text)
        self.assertIn("if (isHtmlAsset(path) && !canOpenRichHtmlArtifacts(jobId))", ui_text)

    def test_frontend_job_fetches_prefer_job_read_token_over_stale_admin_token(self) -> None:
        ui_text = frontend_text()
        self.assertIn("function authHeadersFor(kind, jobId = null)", ui_text)
        self.assertIn("if (kind === 'job' && jobId)", ui_text)
        self.assertIn("const token = readTokenForJob(jobId);", ui_text)
        self.assertIn("if (token) {", ui_text)
        self.assertIn("return headers;", ui_text)
        job_branch = ui_text.split("if (kind === 'job' && jobId)", 1)[1].split("if (admin)", 1)[0]
        self.assertIn("readTokenForJob(jobId)", job_branch)

    def test_canonical_bridge_passes_runtime_env(self) -> None:
        text = (REPO_ROOT / "web" / "canonical_pipeline.py").read_text(encoding="utf-8")
        self.assertIn('"ENGINE": _cfg_str(settings, "engine", os.environ.get("ENGINE", ""))', text)
        self.assertIn('"reuse_existing_layout"', text)
        self.assertIn('"DOCKER_DATA_VOLUME"', text)
        self.assertIn('"FUNBGCEX_DOCKER_IMAGE"', text)
        self.assertIn('"CLINKER_USE_DOCKER_IMAGE"', text)
        self.assertIn('"NPLINKER_DOCKER_IMAGE"', text)
        self.assertIn('"RENDER_BIGSCAPE_NETWORK_PY"', text)
        self.assertIn("def _resolve_target_genome_alias", text)
        self.assertIn("accessions_fungusID_taxonomyID.txt", text)
        self.assertIn('env["TARGET_GENOME"] = target_after', text)

    def test_web_supports_in_place_stage_reruns(self) -> None:
        app_text = (REPO_ROOT / "web" / "app.py").read_text(encoding="utf-8")
        ui_text = frontend_text()
        self.assertIn('route.startswith("/api/jobs/") and route.endswith("/rerun")', app_text)
        self.assertIn('"reuse_existing_layout"] = True', app_text)
        self.assertIn('"submission_settings"', app_text)
        self.assertIn("def validate_ncbi_accession_preflight", app_text)
        self.assertIn("NCBI_FUNGAL_TAXON_ID = 4751", app_text)
        self.assertIn("accession_preflight=not request_is_admin(handler)", app_text)
        self.assertIn("Rerun Selected Stages", ui_text)
        self.assertIn('class="summary-panel rerun-summary"', ui_text)
        self.assertIn("rerunActiveJob()", ui_text)
        self.assertIn("function rerunJobFromHistory(event, jobId)", ui_text)
        self.assertIn('class="job-rerun"', ui_text)
        self.assertIn("function rerunPayloadFromStages(stageKeys", ui_text)
        self.assertIn("function queueJobRerun(jobId, payload)", ui_text)
        self.assertIn("function rerunStageAllowed(key)", ui_text)
        self.assertIn("Reuses this job workspace and existing staged inputs/results", ui_text)
        self.assertIn("failed after preserving earlier outputs", ui_text)

    def test_web_progress_popout_uses_ordered_stage_overview(self) -> None:
        text = frontend_text()
        self.assertIn("function workflowStageOverviewNodes", text)
        self.assertIn("function stageTimelineLabel", text)
        self.assertIn("data-node-stage", text)
        self.assertIn("failure-context", text)
        self.assertIn('.dna-node-item[data-node-kind^=\"stage-\"]', text)
        self.assertIn(".dna-stage-pointer.active { animation: none;", text)
        self.assertIn(".dna-active .dna-base-dot { animation: none;", text)

    def test_dev_admin_ops_panel_stays_available_on_outputs(self) -> None:
        static_dir = REPO_ROOT / "web" / "static"
        index_text = (static_dir / "index.html").read_text(encoding="utf-8")
        css_text = (static_dir / "assets" / "clusterweave.css").read_text(encoding="utf-8")
        js_text = (static_dir / "assets" / "clusterweave.js").read_text(encoding="utf-8")
        self.assertIn('data-ops-panel="open"', index_text)
        self.assertIn('id="ops-panel-toggle"', index_text)
        self.assertIn('aria-controls="ops-side-panel"', index_text)
        self.assertIn("function toggleOpsPanel()", js_text)
        self.assertIn("function setOpsPanelCollapsed(collapsed)", js_text)
        self.assertIn('body[data-access="admin"] .ops-side-panel.admin-only', css_text)
        self.assertIn('body[data-ops-panel="collapsed"] .ops-side-panel', css_text)
        self.assertIn('.ops-side-panel #rerun-panel:not(:empty)', css_text)
        self.assertNotIn('body[data-results-dashboard="open"][data-management-view="closed"] .ops-side-panel { display: none !important; }', css_text)

    def test_worker_supports_bounded_concurrency(self) -> None:
        text = (REPO_ROOT / "web" / "worker.py").read_text(encoding="utf-8")
        self.assertIn('WORKER_CONCURRENCY = max(1, int(os.environ.get("WORKER_CONCURRENCY", "1")))', text)
        self.assertIn("async def worker_loop()", text)
        self.assertIn("active_jobs", text)
        self.assertIn("payload = dict(read_job(job.id) or {})", text)

    def test_ui_stage_states_use_semantic_classes(self) -> None:
        text = frontend_text()
        self.assertIn(".stage-step.upcoming", text)
        self.assertIn(".stage-step.active", text)
        self.assertIn(".stage-step.done", text)
        self.assertIn(".stage-step.disabled", text)
        self.assertIn("function initializeStageState(job)", text)
        self.assertIn("function finalizeStageState(status)", text)

    def test_web_visualization_is_limited_to_figure_outputs(self) -> None:
        text = frontend_text()
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
        self.assertIn('data\\/results\\/[^/]+\\/figures', text)
        self.assertIn("big_scape_multipanel.svg", text)
        self.assertNotIn("gcf_calls_by_tool_category.svg", text)
        self.assertNotIn("bgc_calls_by_tool_category.svg", text)
        self.assertNotIn("bigscape_network.svg", text)
        self.assertIn("const downloadHref = resultHref(jobId, f, { download: true })", text)
        self.assertIn("<th>File / Result path</th>", text)
        self.assertNotIn("const htmlFiles = files.filter", text)

    def test_web_results_tabs_are_keyboard_accessible(self) -> None:
        text = frontend_text()
        self.assertIn('role="tablist"', text)
        self.assertIn('button class="tab active"', text)
        self.assertIn('role="tab"', text)
        self.assertIn('aria-selected="true"', text)
        self.assertIn('role="tabpanel"', text)
        self.assertIn("function handleResultTabKeydown(event)", text)
        self.assertIn("tab.setAttribute('aria-selected'", text)
        self.assertIn("panel.hidden = !active", text)

    def test_web_files_tab_groups_results_into_collapsible_folders(self) -> None:
        text = frontend_text()
        self.assertIn("function buildFileTree(files)", text)
        self.assertIn("function renderFileFolder(jobId, node, depth = 0)", text)
        self.assertIn("function handleFileFolderToggle(detailsEl)", text)
        self.assertIn('<details class="file-folder"', text)
        self.assertIn('<summary class="file-folder-summary">', text)
        self.assertIn("data-rendered", text)
        self.assertIn("file-folder-count", text)
        self.assertIn("function defaultFolderOpen(path, depth)", text)
        self.assertIn("normalized === 'downloads'", text)
        self.assertIn('data\\/results\\/[^/]+\\/figures', text)
        self.assertIn("renderFileRows(jobId, node.files)", text)
        self.assertIn("renderFileRow(jobId, f)", text)
        self.assertIn("function fileRowLabel(path)", text)
        self.assertIn('<span class="file-display-name">${escapeHtml(label)}</span>', text)
        self.assertIn('<span class="file-path-link">${escapeHtml(path)}</span>', text)
        self.assertNotIn('<a class="file-path-link"', text)
        self.assertIn("resultHref(jobId, f, { download: true })", text)

    def test_web_upload_supports_manual_accession_entry(self) -> None:
        text = frontend_text()
        self.assertIn('id="manual-accessions"', text)
        self.assertIn("function manualAccessionLines()", text)
        self.assertIn("const MANUAL_ACCESSIONS_FILENAME = 'manual_accessions.txt'", text)
        self.assertIn("manualLines.join('\\n') + '\\n'", text)
        self.assertIn("new File([manualAccessionText], MANUAL_ACCESSIONS_FILENAME", text)
        self.assertIn("input source(s) ready", text)

    def test_web_has_journey_first_navigation_and_hero(self) -> None:
        text = frontend_text()
        self.assertIn('id="primary-nav"', text)
        self.assertIn('data-nav-target="overview"', text)
        self.assertIn('data-nav-target="intake"', text)
        self.assertIn('data-nav-target="runs"', text)
        self.assertIn('data-nav-target="outputs"', text)
        self.assertIn('data-nav-target="qa"', text)
        self.assertIn('id="runtime-status-menu"', text)
        self.assertIn('id="runtime-status-chip"', text)
        self.assertIn('id="runtime-server-status"', text)
        self.assertIn('id="runtime-running-jobs"', text)
        self.assertIn('id="runtime-queued-jobs"', text)
        self.assertIn('id="runtime-jobs-processed"', text)
        self.assertIn('runtime-diagnostics-only', text)
        self.assertIn('body[data-access="public"] .runtime-diagnostics-only', text)
        self.assertNotIn("Reviewer access required", text)
        self.assertNotIn("Queue depth unlocks with reviewer access.", text)
        self.assertIn("function updateRuntimeStatusPanel(system = null, counts = {})", text)
        self.assertIn('id="weavemap"', text)
        self.assertIn('class="logo-mark"', text)
        self.assertIn('src="assets/clusterweave-logo.png"', text)
        self.assertIn('class="identity-brand-mark"', text)
        self.assertIn("function navigateToSection(event, target", text)
        self.assertIn("function loadDemoAccessions(event)", text)
        self.assertIn("const demoAccessions = ['GCA_000011425.1', 'GCA_030770425.1'];", text)
        self.assertIn("Use demo accessions", text)
        self.assertIn('name="description" content="ClusterWeave runs fungal biosynthetic gene cluster discovery', text)
        self.assertIn('name="robots" content="index, follow"', text)
        self.assertIn('class="accession-label-row"', text)
        self.assertIn('href="https://www.ncbi.nlm.nih.gov/datasets/genome/"', text)
        self.assertIn('NCBI Genome</a>', text)
        self.assertIn("const NCBI_ASSEMBLY_ACCESSION_HELP = 'Use current fungal NCBI assembly accessions", text)
        self.assertIn('class="run-entry-tabs-panel" id="access-panel"', text)
        self.assertIn('class="card run-entry-card" id="upload-card"', text)
        self.assertNotIn('id="entry-input-source-select"', text)
        self.assertIn('id="drop-zone" tabindex="0" role="button" aria-label="Upload genome or accession files"', text)
        self.assertIn('id="file-input" multiple accept=', text)
        self.assertIn('aria-label="Upload genome or accession files"', text)
        self.assertIn("fileInput.click();", text)
        self.assertIn("Public fungal BGC workflow", text)
        self.assertIn("Run fungal BGC discovery.", text)
        self.assertIn("Submit public assemblies, track canonical stages, and return with a private result link.", text)
        self.assertNotIn('class="journey-cues"', text)
        self.assertNotIn('class="journey-cue"', text)
        self.assertNotIn('class="journey-cue-label"', text)
        self.assertIn('id="docs"', text)
        self.assertIn('class="status-chip docs-summary"', text)
        self.assertIn('aria-haspopup="dialog"', text)
        self.assertIn('aria-label="Tool credits and citations"', text)
        self.assertIn('class="docs-chip-label">Citations</span>', text)
        self.assertIn('class="citation-lamp"', text)
        self.assertIn('role="dialog" aria-modal="true" aria-label="Tool credits and citations"', text)
        self.assertLess(text.index('id="docs"'), text.index('id="runtime-status-menu"'))
        self.assertIn('class="identity-brand-caption"', text)
        self.assertIn("width: min(100%, 62rem);", text)
        self.assertIn('body[data-results-dashboard="open"] .upload-section', text)
        self.assertNotIn('body[data-entry-mode="existing"] #upload-card > .card-header', text)
        self.assertNotIn('Inputs and run settings', text)
        self.assertNotIn('onclick="toggleCard(\'upload-card\')"', text)
        self.assertLess(text.index('id="entry-tab-new"'), text.index('id="entry-panel-new"'))
        self.assertLess(text.index('id="entry-panel-new"'), text.index('Input sources'))
        self.assertLess(text.index('Input sources'), text.index('id="manual-accessions"'))
        self.assertLess(text.index('<!-- end upload-section -->'), text.index('id="weavemap"'))
        self.assertLess(text.index('<!-- end upload-section -->'), text.index('id="ops-side-panel"'))
        self.assertLess(text.index('<!-- end upload-section -->'), text.index('id="result-dashboard-section"'))
        self.assertNotIn('class="access-panel section-anchor" id="access-panel"', text)
        self.assertNotIn('body[data-entry-mode="existing"]:not([data-existing-run-loaded="true"]) .upload-section', text)
        self.assertIn("white-space: nowrap", text)
        self.assertNotIn("--font:      'Inter'", text)
        self.assertIn('id="submission-confirmation"', text)
        self.assertIn('id="submitted-result-link"', text)
        self.assertIn("function copySubmittedResultLink()", text)
        self.assertNotIn("focusRunAction(event)", text)
        self.assertNotIn("nav-action", text)
        self.assertIn("ClusterWeave is a portal to public, open-access biosynthetic discovery tools.", text)
        self.assertIn("data-citation-link", text)
        self.assertNotIn("Methods, artifacts, logs, and runtime notes", text)
        self.assertNotIn('class="docs-links"', text)
        self.assertNotIn('href="#weavemap" data-nav-target="weavemap"', text)
        self.assertNotIn("hero-weavemap", text)

    def test_web_has_user_modes_and_section_hierarchy(self) -> None:
        text = frontend_text()
        self.assertIn('data-ui-mode="guided"', text)
        self.assertNotIn('id="mode-panel"', text)
        self.assertNotIn('data-mode-option="guided"', text)
        self.assertNotIn('data-mode-option="lab"', text)
        self.assertNotIn('data-mode-option="advanced"', text)
        self.assertIn("function setUIMode(mode", text)
        self.assertIn("body[data-ui-mode=\"guided\"] #console-card", text)
        self.assertIn('id="workflow-controls"', text)
        self.assertIn("Run options", text)
        self.assertIn('id="advanced-panel"', text)
        self.assertIn("Run history", text)
        self.assertIn("if (target === 'qa' && currentUIMode === 'guided') setUIMode('lab'", text)
        self.assertIn("if (accessMode === 'public' && mode !== 'guided') mode = 'guided'", text)

    def test_web_lab_console_scroll_bottom_targets_visible_log_viewport(self) -> None:
        text = frontend_text()
        self.assertIn("function scrollElementToBottom(el)", text)
        self.assertIn("const lastLine = term.lastElementChild;", text)
        self.assertIn("lastLine.scrollIntoView({ block: 'end', inline: 'nearest' });", text)
        self.assertIn("requestAnimationFrame(() => {", text)
        self.assertIn("const body = term.closest('.lab-console-body');", text)
        self.assertIn(".ops-side-panel #progress-card:not(.hidden) { flex: 2 1 20rem; }", text)
        self.assertIn(".ops-side-panel .lab-console-body .terminal-run {", text)
        self.assertIn(".ops-side-panel .lab-console-body .terminal-run .log-terminal {", text)
        self.assertIn("flex: 1 1 auto;", text)
        self.assertIn("min-height: 0;", text)

    def test_web_has_neumorphic_surface_system_tokens(self) -> None:
        text = frontend_text()
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
        text = frontend_text()
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
        self.assertIn("real job state", text)
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
        text = frontend_text()
        self.assertIn("let jobLoadSeq = 0", text)
        self.assertIn("function markActiveJobCard(jobId)", text)
        self.assertIn("let jobHistoryInFlight = false", text)
        self.assertIn("function renderJobHistory(jobs)", text)
        self.assertIn("function jobHistoryRenderKey(jobs)", text)
        self.assertIn("const seq = ++jobLoadSeq", text)
        self.assertIn("loadResults(jobId, job.status, seq, job)", text)
        self.assertIn("seq !== jobLoadSeq || jobId !== activeJobId", text)

    def test_web_api_calls_work_behind_path_prefixed_proxies(self) -> None:
        text = frontend_text()
        self.assertIn("function apiUrl(path)", text)
        self.assertIn("function defaultApiBaseUrl()", text)
        self.assertIn("window.CLUSTERWEAVE_API_BASE", text)
        self.assertIn("apiFetch('api/system/status'", text)
        self.assertIn("apiFetch('api/jobs'", text)
        self.assertIn("const base = apiUrl(`api/jobs/", text)
        self.assertNotIn("fetch('/api/", text)
        self.assertNotIn('fetch("/api/', text)

    def test_web_public_ui_restructure_gates_admin_surfaces(self) -> None:
        text = frontend_text()
        self.assertIn('data-access="public"', text)
        self.assertIn('id="access-panel"', text)
        self.assertIn('id="submit-token"', text)
        self.assertIn('id="admin-token"', text)
        self.assertIn('id="existing-run-link"', text)
        self.assertIn('id="existing-run-token"', text)
        self.assertIn('<details class="reviewer-access" id="reviewer-access">', text)
        self.assertIn('      <details class="reviewer-access" id="reviewer-access">', text)
        self.assertIn('input[type=password]', text)
        self.assertIn('id="opened-runs-select"', text)
        self.assertIn("sessionStorage.setItem", text)
        self.assertIn("function parseExistingRunInput()", text)
        self.assertIn("function rememberOpenedRun(jobId, token", text)
        self.assertIn("let pendingReadTokens = new Map()", text)
        self.assertIn("const pending = pendingReadTokens.get(id)", text)
        self.assertIn("if (options.readToken) pendingReadTokens.set(String(jobId), options.readToken)", text)
        self.assertIn("const deferResultsShell = !!options.deferResultsShell", text)
        self.assertIn("if (!deferResultsShell) showResultsShell()", text)
        self.assertIn("deferResultsShell: true", text)
        self.assertIn("pendingReadTokens.delete(String(jobId))", text)
        self.assertIn("source: 'opened-run-select'", text)
        self.assertIn("That remembered result could not be opened. Enter its result access code again.", text)
        self.assertNotIn("rememberOpenedRun(parsed.jobId, parsed.token);", text)
        self.assertNotIn("rememberOpenedRun(hashRun.jobId, hashRun.token);", text)
        self.assertIn("function authHeadersFor(kind, jobId = null)", text)
        self.assertIn("function handleResultLinkClick(event, jobId, relPath, download = false)", text)
        self.assertIn("return !!adminToken() || (accessMode === 'public' && !!readTokenForJob(jobId));", text)
        self.assertIn('body[data-access="public"] .admin-only', text)
        self.assertNotIn('class="mode-panel section-anchor admin-only"', text)
        self.assertIn('class="card section-anchor admin-only" id="jobs-card"', text)
        self.assertIn('class="card telemetry-card section-anchor admin-only" id="console-card"', text)
        self.assertIn('id="workflow-controls"', text)
        self.assertIn('class="stage-toggle-panel workflow-controls" id="workflow-controls" open', text)
        self.assertNotIn('workflow-controls admin-only', text)
        self.assertIn('id="advanced-panel"', text)
        self.assertIn('advanced-wrap admin-only', text)
        self.assertIn('PUBLIC_LOCKED_CHECKBOX_DEFAULTS', text)
        self.assertIn('stage-lock-control', text)
        self.assertIn('Required for hosted runs', text)
        self.assertIn('form-group-inline admin-only"><input type="checkbox" id="run-nplinker"', text)
        self.assertIn('id="rerun-panel" class="admin-only"', text)
        self.assertNotIn('id="output-discovery"', text)
        self.assertNotIn('results-intel admin-only', text)
        self.assertIn("Submit or load an existing run to see stage progress.", text)
        self.assertIn('body[data-workflow-state="idle"] #results-card', text)
        self.assertIn("body[data-access=\"public\"] .stage-step[data-stage=\"nplinker\"]", text)
        self.assertIn("const PUBLIC_FILE_EXTENSIONS = new Set(['gbk','gb','gbff','fasta','fa','fna','fsa','txt']);", text)
        self.assertIn('id="input-checker"', text)
        self.assertIn('id="input-checker-list"', text)
        self.assertIn("Annotation and protein readiness", text)
        self.assertIn("Drop translated GenBank, nucleotide FASTA, or accession lists", text)
        self.assertIn("GenBank needs CDS /translation= entries unless paired with same-stem FASTA", text)
        self.assertIn("funannotate before BGC tools", text)
        self.assertIn("same-stem FASTA", text)
        self.assertIn("translated GenBank", text)
        self.assertIn("function renderInputChecker()", text)
        self.assertIn("function cacheGenomeFileCheck(file)", text)
        self.assertIn("function publicGenomeUploadKind(fileExt)", text)
        self.assertIn("raw_fasta_requires_annotation", text)
        self.assertIn("annotated_genbank_ready", text)
        self.assertIn("genbank_requires_fallback_or_translations", text)
        self.assertIn("Tool credits and citations", text)
        self.assertIn("ClusterWeave is a portal to public, open-access biosynthetic discovery tools.", text)
        self.assertNotIn("BRAKER", text)
        self.assertNotIn("GeneMark", text)
        self.assertNotIn("submit_token=", text)
        self.assertNotIn("admin_token=", text)

    def test_web_human_language_contract_keeps_public_and_admin_purpose_clear(self) -> None:
        text = frontend_text()
        for copy in [
            "Start",
            "Inputs",
            "Results",
            "Genomes and accessions",
            "Target genome / accession ID (optional)",
            "Private result lookup",
            "Save access for this tab",
            "Start run",
            "Initiating sequence. Launching ClusterWeave.",
            "Result outputs",
            "Choose an output",
        ]:
            self.assertIn(copy, text)
        for admin_copy in [
            "Run history",
            "Diagnostics",
            "Run options",
            "Advanced runtime settings",
            "Diagnostics panels",
            "Show diagnostics panel",
        ]:
            self.assertIn(admin_copy, text)
        self.assertIn('class="ops-panel-nav" aria-label="Reviewer management navigation"', text)
        self.assertIn('class="ops-nav-button" type="button" data-nav-target="runs"', text)
        self.assertIn('class="ops-nav-button" type="button" data-nav-target="qa"', text)
        self.assertNotIn('class="nav-link admin-only" href="#jobs-card"', text)
        self.assertNotIn('class="nav-link admin-only" href="#console-card"', text)
        self.assertNotIn("QA Console", text)
        self.assertNotIn("CLUSTERWEAVE HAS BEGUN", text)
        self.assertNotIn("shell-first controller", text)
        self.assertNotIn("Current scaffold", text)
        self.assertNotIn("Advanced knobs", text)
        self.assertNotIn("Workflow controls", text)

    def test_web_email_and_retention_slice_has_public_recovery_hooks(self) -> None:
        ui_text = frontend_text()
        app_text = (REPO_ROOT / "web" / "app.py").read_text(encoding="utf-8")
        worker_text = (REPO_ROOT / "web" / "worker.py").read_text(encoding="utf-8")
        notifications_text = (REPO_ROOT / "web" / "notifications.py").read_text(encoding="utf-8")
        job_store_text = (REPO_ROOT / "web" / "job_store.py").read_text(encoding="utf-8")
        maintenance_text = (REPO_ROOT / "web" / "maintenance.py").read_text(encoding="utf-8")
        compose_text = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn('id="email-notification-panel"', ui_text)
        self.assertIn('id="notify-email"', ui_text)
        self.assertIn('class="form-group project-name-panel"', ui_text)
        self.assertIn('id="project-name" autocomplete="off"', ui_text)
        self.assertIn('autocapitalize="none" autocorrect="off" spellcheck="false" placeholder="fungal_survey"', ui_text)
        self.assertIn('class="form-group email-notification-panel hidden" id="email-notification-panel"', ui_text)
        self.assertLess(ui_text.index('id="project-name"'), ui_text.index('id="email-notification-panel"'))
        self.assertLess(ui_text.index('id="email-notification-panel"'), ui_text.index('id="target-genome"'))
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
        self.assertIn("CLUSTERWEAVE_PUBLIC_MODE", compose_text)
        self.assertIn("CLUSTERWEAVE_ADMIN_TOKEN", compose_text)
        self.assertIn('CLUSTERWEAVE_JOB_TOKEN_SECRET: "${CLUSTERWEAVE_JOB_TOKEN_SECRET:-}"', compose_text)
        self.assertNotIn("dev-change-me", compose_text)
        self.assertIn("CLUSTERWEAVE_PUBLIC_BASE_URL", compose_text)

    def test_web_ecology_label_table_uses_controlled_public_inputs(self) -> None:
        text = frontend_text()
        html_text = (REPO_ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="ecology-label-panel"', text)
        self.assertIn('class="summary-panel ecology-label-panel hidden" id="ecology-label-panel"', text)
        self.assertIn('id="run-ecology"', text)
        self.assertIn('id="run-summary-content" aria-hidden="true"', text)
        self.assertLess(html_text.index('id="run-ecology"'), html_text.index('id="ecology-label-panel"'))
        self.assertLess(html_text.index('id="ecology-label-panel"'), html_text.index('id="data-use-ack-panel"'))
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
        self.assertIn('function syncEcologyMetadataPanel()', text)
        self.assertIn("panel.classList.toggle('hidden', !enabled)", text)
        self.assertIn('advanced-wrap admin-only', text)
        self.assertNotIn("Editable Ecology Metadata", text)
        self.assertNotIn("addMetadataRow()", text)

    def test_web_serves_result_assets_inline_unless_download_requested(self) -> None:
        text = (REPO_ROOT / "web" / "app.py").read_text(encoding="utf-8")
        self.assertIn('"image/svg+xml; charset=utf-8"', text)
        self.assertIn('"Cache-Control": "no-store"', text)
        self.assertIn('STATIC_ASSET_DIR = STATIC_DIR / "assets"', text)
        self.assertIn('if route.startswith("/assets/"):', text)
        self.assertIn("full.relative_to(asset_root)", text)
        self.assertIn('"Cache-Control": "public, max-age=86400"', text)
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
        self.assertIn('RENDER_BGC_OVERLAP_PY="${RENDER_BGC_OVERLAP_PY:-${SCRIPT_DIR}/bin/render_bgc_overlap.py}"', text)
        self.assertIn('RENDER_BIGSCAPE_NETWORK_PY="${RENDER_BIGSCAPE_NETWORK_PY:-${SCRIPT_DIR}/bin/render_bigscape_network.py}"', text)
        self.assertIn('RENDER_BIGSCAPE_MULTIPANEL_PY="${RENDER_BIGSCAPE_MULTIPANEL_PY:-${SCRIPT_DIR}/bin/render_bigscape_multipanel.py}"', text)
        self.assertIn('RUN_SUMMARY_FIGURES="${RUN_SUMMARY_FIGURES:-0}"', text)
        self.assertIn('RUN_BGC_OVERLAP_FIGURE="${RUN_BGC_OVERLAP_FIGURE:-1}"', text)
        self.assertIn('RUN_BIGSCAPE_MULTIPANEL_FIGURE="${RUN_BIGSCAPE_MULTIPANEL_FIGURE:-1}"', text)
        self.assertIn('BGC_OVERLAP_FORMATS="${BGC_OVERLAP_FORMATS:-svg,png}"', text)
        self.assertIn('BIGSCAPE_NETWORK_FORMATS="${BIGSCAPE_NETWORK_FORMATS:-graphml}"', text)
        self.assertIn('BIGSCAPE_MULTIPANEL_FORMATS="${BIGSCAPE_MULTIPANEL_FORMATS:-svg,png}"', text)
        self.assertIn("bgc_overlap_outputs_ready", text)
        self.assertIn("cleanup_redundant_figure_outputs", text)
        self.assertIn("--no-standalone-chart", text)
        self.assertIn("--no-warnings-file", text)
        self.assertIn("--no-fungal-id-legend", text)
        self.assertIn("python_candidate_works", text)
        self.assertIn("Skipping R summary figures because RUN_SUMMARY_FIGURES", text)
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
        self.assertIn('POSTPROCESS_FALLBACK_PY=\\"${REPO_ROOT}/bin/postprocess_clinker_html.py\\"', text)
        self.assertIn("project_root.resolve().as_posix()", text)
        self.assertIn("repo_root.resolve().as_posix()", text)
        run_clinker = (REPO_ROOT / "run_clinker.sh").read_text(encoding="utf-8")
        self.assertIn('--repo-root "${PROJECT_DIR}"', run_clinker)

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
            "software/funbgcex/build_funbgcex_sif.sh",
            "software/funbgcex/Dockerfile",
            "software/funbgcex/Singularity.def",
        ]:
            self.assertTrue((REPO_ROOT / rel).exists(), rel)

    def test_gitignore_unignores_funbgcex_text_recipes(self) -> None:
        text = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        for pattern in [
            "!software/funbgcex/",
            "software/funbgcex/**",
            "!software/funbgcex/build_funbgcex_sif.sh",
            "!software/funbgcex/Dockerfile",
            "!software/funbgcex/Singularity.def",
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
