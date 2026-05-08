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

    def test_web_supports_in_place_stage_reruns(self) -> None:
        app_text = (REPO_ROOT / "web" / "app.py").read_text(encoding="utf-8")
        ui_text = (REPO_ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('route.startswith("/api/jobs/") and route.endswith("/rerun")', app_text)
        self.assertIn('"reuse_existing_layout"] = True', app_text)
        self.assertIn("Rerun Selected Stages", ui_text)
        self.assertIn("rerunActiveJob()", ui_text)

    def test_worker_supports_bounded_concurrency(self) -> None:
        text = (REPO_ROOT / "web" / "worker.py").read_text(encoding="utf-8")
        self.assertIn('WORKER_CONCURRENCY = max(1, int(os.environ.get("WORKER_CONCURRENCY", "1")))', text)
        self.assertIn("async def worker_loop()", text)
        self.assertIn("active_jobs", text)

    def test_ui_stage_states_use_semantic_classes(self) -> None:
        text = (REPO_ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn(".stage-step.upcoming", text)
        self.assertIn(".stage-step.active", text)
        self.assertIn(".stage-step.done", text)
        self.assertIn(".stage-step.disabled", text)
        self.assertIn("function initializeStageState(job)", text)
        self.assertIn("function finalizeStageState(status)", text)

    def test_figures_wrapper_detects_rscript_robustly(self) -> None:
        text = (REPO_ROOT / "run_figures.sh").read_text(encoding="utf-8")
        self.assertIn("resolve_r_bin()", text)
        self.assertIn('/mnt/c/Program Files/R/R-*/bin/Rscript.exe', text)
        self.assertIn('/c/Program Files/R/R-*/bin/Rscript.exe', text)
        self.assertIn('R_BIN="$(resolve_r_bin)"', text)
        self.assertNotIn("FIGURES_TOP_N", text)

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
