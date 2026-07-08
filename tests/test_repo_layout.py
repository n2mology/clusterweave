import csv
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


    def test_ncbi_rename_enriches_mapping_with_taxonomy_lineage_when_datasets_available(self) -> None:
        accession = "GCA_999999999.1"
        report = {
            "organism": {
                "organismName": "Rhizopus delemar RA 99-880",
                "taxId": 4827,
            },
            "assemblyStats": {"totalSequenceLength": 2000000},
        }
        taxonomy_payload = {
            "reports": [
                {
                    "taxonomy": {
                        "tax_id": 4827,
                        "parents": [1, 131567, 2759, 33154, 4751, 112252, 1913637, 451507, 2212703],
                        "classification": {
                            "kingdom": {"id": 4751, "name": "Fungi"},
                            "phylum": {"id": 1913637, "name": "Mucoromycota"},
                            "class": {"id": 2212703, "name": "Mucoromycetes"},
                            "order": {"id": 4827, "name": "Mucorales"},
                        },
                        "current_scientific_name": {"name": "Mucorales"},
                    }
                }
            ],
            "total_count": 1,
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            datasets = bin_dir / "datasets"
            datasets.write_text(
                "#!/usr/bin/env python3\n"
                "import json\n"
                f"print({json.dumps(taxonomy_payload)!r})\n",
                encoding="utf-8",
            )
            datasets.chmod(0o755)

            genome_root = tmp_path / "genomes"
            package_dir = genome_root / accession / "ncbi_dataset" / "data" / accession
            package_dir.mkdir(parents=True)
            (genome_root / accession / "ncbi_dataset" / "data" / "assembly_data_report.jsonl").write_text(
                json.dumps(report) + "\n",
                encoding="utf-8",
            )
            (package_dir / f"{accession}.fna").write_text(">seq\nAC\n", encoding="utf-8")

            env = dict(os.environ)
            env["GENOME_ROOT"] = str(genome_root)
            env["PYTHON_BIN"] = sys.executable
            env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
            subprocess.run(
                ["bash", str(REPO_ROOT / "scripts" / "ncbi" / "rename_ncbi_genomes.sh")],
                cwd=str(REPO_ROOT),
                env=env,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            mapping = (genome_root / "accessions_fungusID_taxonomyID.txt").read_text(encoding="utf-8").strip()
            fields = mapping.split("\t")
            self.assertGreaterEqual(len(fields), 7)
            self.assertEqual(fields[0], accession)
            self.assertEqual(fields[2], "4827")
            self.assertEqual(fields[4], "Rhizopus delemar RA 99-880")
            self.assertIn("1913637", fields[5])
            self.assertIn("4827", fields[5])
            self.assertIn("Mucoromycota", fields[6])
            self.assertIn("Mucorales", fields[6])

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

    def test_annotation_uses_per_genome_funannotate_lineage_policy(self) -> None:
        text = (REPO_ROOT / "run_annotation_and_detection.sh").read_text(encoding="utf-8")
        self.assertIn("resolve_funannotate_policy()", text)
        self.assertIn("funannotate_mapping_row()", text)
        self.assertIn("funannotate_busco_env_value()", text)
        self.assertIn("FUNANNOTATE_RESOLVED_BUSCO_DB", text)
        self.assertIn("FUNANNOTATE_RESOLVED_SPECIES", text)
        self.assertIn("taxonomy:ascomycota", text)
        self.assertIn("fallback:no-taxonomy", text)
        self.assertIn('local species_name="${FUNANNOTATE_RESOLVED_SPECIES%.}"', text)
        self.assertIn('local busco_db="${FUNANNOTATE_RESOLVED_BUSCO_DB}"', text)
        self.assertIn('ANNOTATION_FALLBACK_METHOD="funannotate"', text)
        self.assertIn('fallback_method="${ANNOTATION_FALLBACK_METHOD:-annotation}"', text)
        self.assertNotIn("ANNOTATION_LINEAGE_POLICY_PY", text)
        self.assertNotIn("annotation_lineage_policy.py", text)
        self.assertNotIn('fallback_method="$(annotate_genome_with_fallbacks', text)

    def test_funannotate_busco_db_is_validated_before_predict(self) -> None:
        text = (REPO_ROOT / "run_annotation_and_detection.sh").read_text(encoding="utf-8")
        self.assertIn("funannotate_busco_db_available()", text)
        self.assertIn("validate_funannotate_busco_db()", text)
        self.assertIn("auto-selected BUSCO db", text)
        self.assertIn("explicit FUNANNOTATE_BUSCO_DB", text)
        self.assertIn("FUNANNOTATE_BUSCO_DB_DEFAULT", text)
        self.assertLess(text.index("validate_funannotate_busco_db"), text.index("funannotate predict"))

    def test_funannotate_retries_without_default_protein_evidence_when_p2g_fails(self) -> None:
        text = (REPO_ROOT / "run_annotation_and_detection.sh").read_text(encoding="utf-8")
        self.assertIn('FUNANNOTATE_RETRY_WITHOUT_PROTEIN_EVIDENCE="${FUNANNOTATE_RETRY_WITHOUT_PROTEIN_EVIDENCE:-1}"', text)
        self.assertIn("funannotate_predict_failed_in_p2g()", text)
        self.assertIn(r"protein_alignments\.gff3", text)
        self.assertIn("funannotate_no_protein_alignments.gff3", text)
        self.assertIn("printf '%s\\n' '##gff-version 3'", text)
        self.assertIn("retrying without default UniProt protein-to-genome evidence", text)
        self.assertIn('funannotate_predict_attempt "no-protein-evidence" --protein_alignments "${no_protein_alignments}"', text)

    def test_funannotate_sif_bake_path_installs_busco_databases_at_build_time(self) -> None:
        script = REPO_ROOT / "software" / "funannotate" / "build_funannotate_sif.sh"
        dockerfile = REPO_ROOT / "software" / "funannotate" / "Dockerfile"
        definition = REPO_ROOT / "software" / "funannotate" / "Singularity.def"
        readme = REPO_ROOT / "software" / "funannotate" / "README.md"
        installer = REPO_ROOT / "software" / "funannotate" / "install_busco_db.py"
        cache_keep = REPO_ROOT / "software" / "funannotate" / "busco_cache" / ".gitkeep"
        worker_dockerfile = REPO_ROOT / "Dockerfile.worker"
        dockerignore = REPO_ROOT / ".dockerignore"

        self.assertTrue(script.exists())
        self.assertTrue(dockerfile.exists())
        self.assertTrue(definition.exists())
        self.assertTrue(readme.exists())
        self.assertTrue(installer.exists())
        self.assertTrue(cache_keep.exists())

        script_text = script.read_text(encoding="utf-8")
        dockerfile_text = dockerfile.read_text(encoding="utf-8")
        definition_text = definition.read_text(encoding="utf-8")
        readme_text = readme.read_text(encoding="utf-8")
        installer_text = installer.read_text(encoding="utf-8")
        worker_text = worker_dockerfile.read_text(encoding="utf-8")
        dockerignore_text = dockerignore.read_text(encoding="utf-8")
        combined = script_text + dockerfile_text + definition_text + readme_text

        self.assertIn("FUNANNOTATE_BUSCO_DBS", script_text)
        self.assertIn("ascomycota basidiomycota microsporidia dikarya fungi", script_text)
        self.assertIn("COPY install_busco_db.py", dockerfile_text)
        self.assertIn("COPY busco_cache/", dockerfile_text)
        self.assertIn("install_from_cache", dockerfile_text)
        self.assertIn("/venv/bin/python /opt/clusterweave-install-busco-db.py", dockerfile_text)
        self.assertIn("--cache-dir /opt/clusterweave-busco-cache", dockerfile_text)
        self.assertIn("for db in ${FUNANNOTATE_BUSCO_DBS}", dockerfile_text)
        self.assertIn('--db "${db}"', dockerfile_text)
        self.assertIn("%files", definition_text)
        self.assertIn("install_busco_db.py /opt/clusterweave-install-busco-db.py", definition_text)
        self.assertIn("busco_cache /opt/clusterweave-busco-cache", definition_text)
        self.assertIn("install_from_cache", definition_text)
        self.assertIn("/venv/bin/python /opt/clusterweave-install-busco-db.py", definition_text)
        self.assertIn("--cache-dir /opt/clusterweave-busco-cache", definition_text)
        self.assertIn("for db in ${FUNANNOTATE_BUSCO_DBS}", definition_text)
        self.assertIn('--db "${db}"', definition_text)
        self.assertIn("validate_funannotate_busco_db_inventory", script_text)
        self.assertIn("assert_funannotate_predict_accepts_busco_dbs", script_text)
        self.assertIn("docker)", script_text)
        self.assertIn("sif)", script_text)
        self.assertIn("COPY software/funannotate/", worker_text)
        self.assertIn("/clusterweave/software/funannotate/*.sh", worker_text)
        self.assertIn("!software/funannotate/", dockerignore_text)
        self.assertIn("!software/funannotate/build_funannotate_sif.sh", dockerignore_text)
        self.assertIn("!software/funannotate/install_busco_db.py", dockerignore_text)
        self.assertIn("Redirect308Handler", installer_text)
        self.assertIn("resources.busco_links", installer_text)
        self.assertIn("safe_extract", installer_text)
        self.assertNotIn("auto-lineage", combined)
        self.assertNotIn("_odb10", combined)
        self.assertIn("Public jobs must not download BUSCO DBs", readme_text)

    def test_funannotate_sif_bake_is_not_a_job_time_download_path(self) -> None:
        pipeline = (REPO_ROOT / "run_annotation_and_detection.sh").read_text(encoding="utf-8")
        self.assertIn("AUTO_BUILD_FUNANNOTATE_SIF", pipeline)
        self.assertIn("AUTO_BUILD_FUNANNOTATE_DOCKER", pipeline)
        self.assertIn("FUNANNOTATE_BUILD_SCRIPT", pipeline)
        self.assertIn("ensure_funannotate_docker_runtime()", pipeline)
        self.assertIn("ensure_funannotate_sif_runtime()", pipeline)
        self.assertIn("clusterweave-funannotate:v1.8.17-busco", pipeline)
        self.assertNotIn("funannotate setup", pipeline)
        self.assertNotIn("download_buscos", pipeline)

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
            "visuals/ClusterWeave.svg",
            "visuals/logo.svg",
            "visuals/logo_black.svg",
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
            "web/STYLE_ARCHIVE.md",
            "web/PRODUCTION_LAUNCH_SLICE_MAP.md",
            "web/PRODUCTION_LAUNCH_SLICE_ARCHIVE.md",
            "web/GLOSSARY.md",
            "web/UPSTREAM_MAINTAINER_NOTE.md",
        ]:
            with self.subTest(rel=rel):
                self.assertIn(rel, gitignore)
                self.assertIn(rel, dockerignore)

    def test_generic_example_paths_exist(self) -> None:
        self.assertTrue((REPO_ROOT / "profiles" / "example_project.env").exists())
        for rel in [
            "examples/README.md",
            "examples/accessions.txt",
            "examples/accessions_fungusID_taxonomyID.txt",
            "examples/summary/README.md",
            "examples/summary/family_atlas_shortlist.md",
            "examples/figures/big_scape_multipanel.svg",
            "examples/figures/bgc_overlap.svg",
        ]:
            self.assertTrue((REPO_ROOT / rel).exists(), rel)

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

    def test_summary_maps_funbgcex_locus_truncation_to_full_accession(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            project = "truncated_locus_project"
            genome = "Genome_one"
            results_root = tmp_root / "data" / "results" / project
            antismash_dir = results_root / "antismash" / genome
            funbgcex_dir = results_root / "funbgcex" / genome
            input_gbks_dir = results_root / "input_gbks"
            antismash_dir.mkdir(parents=True)
            funbgcex_dir.mkdir(parents=True)
            input_gbks_dir.mkdir(parents=True)

            (input_gbks_dir / f"{genome}.gbk").write_text(
                "LOCUS       tig00000001_RagT     1000 bp    DNA     linear   UNA 01-JAN-1980\n"
                "ACCESSION   tig00000001_RagTag\n"
                "VERSION     tig00000001_RagTag\n"
                "//\n",
                encoding="utf-8",
            )
            (antismash_dir / f"{genome}.antismash.json").write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "id": "tig00000001_RagTag",
                                "modules": {},
                                "areas": [
                                    {
                                        "start": 99,
                                        "end": 200,
                                        "products": ["NRPS"],
                                        "protoclusters": {},
                                    }
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (funbgcex_dir / "allBGCs.csv").write_text(
                "BGC no.,Scaffold,Start position,End position,Core enzymes,Metabolite from similar BGC,Similar BGC,Similarity score\n"
                "BGC1,tig00000001_RagT,120,180,NRPS,-,-,-\n",
                encoding="utf-8",
            )
            noop_script = tmp_root / "noop.py"
            noop_script.write_text("import sys\n", encoding="utf-8")

            env = dict(os.environ)
            env.update(
                {
                    "PROJECT_NAME": project,
                    "PROJECTS_ROOT": str(REPO_ROOT),
                    "DATA_ROOT": str(tmp_root / "data"),
                    "RESULTS_ROOT": str(results_root),
                    "INPUT_GBKS_ROOT": str(input_gbks_dir),
                    "BGC_GCF_CROSSWALK_PY": str(noop_script),
                    "TARGETED_ANALYSIS_PY": str(noop_script),
                    "RUN_ECOLOGY_ANALYSIS": "0",
                    "PYTHON_BIN": sys.executable,
                }
            )
            result = subprocess.run(
                ["bash", str(REPO_ROOT / "summarize_clusterweave.sh")],
                cwd=str(REPO_ROOT),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
            )

            output = result.stdout + result.stderr
            with (results_root / "summary" / "all_tools_bgc_comparison.csv").open(encoding="utf-8") as fh:
                bgc_rows = list(csv.DictReader(fh))
            self.assertEqual(len(bgc_rows), 1, output)
            self.assertEqual(bgc_rows[0]["scaffold"], "tig00000001_RagTag")
            self.assertEqual(bgc_rows[0]["overlap_bp"], "61")
            self.assertEqual(bgc_rows[0]["antismash_bgc_id"], "tig00000001_RagTag.region001")
            self.assertEqual(bgc_rows[0]["funbgcex_bgc_id"], "BGC1")

            with (results_root / "summary" / "all_tools_shared_unshared_summary.csv").open(encoding="utf-8") as fh:
                summary_rows = list(csv.DictReader(fh))
            counts = {(row["tool"], row["entity_type"], row["class_norm"]): row for row in summary_rows}
            for key in [("antismash", "BGC", "NRPS"), ("funbgcex", "BGC", "NRPS")]:
                self.assertEqual(counts[key]["shared_count"], "1")
                self.assertEqual(counts[key]["unshared_count"], "0")

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

    def test_wrapper_stops_before_grouping_when_annotation_drops_every_genome(self) -> None:
        text = (REPO_ROOT / "run_clusterweave.sh").read_text(encoding="utf-8")
        self.assertIn("require_annotation_stage_outputs()", text)
        self.assertIn("annotation_manifest_usable_count()", text)
        self.assertIn("Annotation stage produced zero usable genomes", text)
        self.assertIn("stopping before grouping", text)
        stage_block = text.split('log "Stage 1/4: running run_annotation_and_detection.sh"', 1)[1].split('if [[ "${RUN_STAGE_BIGSCAPE}" == "1" ]]', 1)[0]
        self.assertIn('bash "${RUN_ANNOTATION_STAGE}"', stage_block)
        self.assertIn("require_annotation_stage_outputs", stage_block)

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

    def test_clinker_normalizes_legacy_web_panel_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            env = dict(os.environ)
            env.update(
                {
                    "PROJECT_NAME": "legacy_clinker_defaults",
                    "PROJECTS_ROOT": str(REPO_ROOT),
                    "DATA_ROOT": str(tmp_root / "data"),
                    "RESULTS_ROOT": str(tmp_root / "data" / "results" / "legacy_clinker_defaults"),
                    "SOFTWARE_ROOT": str(REPO_ROOT / "software"),
                    "CLINKER_MODE": "docker",
                    "PANEL_TARGET_SET": "atlas",
                    "STAGE_PANELS": "0",
                    "RUN_CLINKER": "0",
                    "REFRESH_FAMILY_ATLAS": "0",
                    "REFRESH_REVIEWER_SHORTLIST": "0",
                    "REFRESH_PRIORITY_SHORTLIST": "0",
                    "REFRESH_SHARED_FAMILY_SHORTLIST": "0",
                }
            )
            result = subprocess.run(
                ["bash", str(REPO_ROOT / "run_clinker.sh")],
                cwd=str(REPO_ROOT),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
            )

        output = result.stdout + result.stderr
        self.assertIn("CLINKER_MODE=docker is a runtime backend value; using CLINKER_MODE=auto", output)
        self.assertIn("PANEL_TARGET_SET=atlas is a legacy atlas selector; using PANEL_TARGET_SET=both", output)
        self.assertIn("CLINKER_MODE=auto", output)
        self.assertIn("PANEL_TARGET_SET=both", output)
        self.assertIn("run_clinker.sh complete.", output)

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
        self.assertIn('WORKER_CONCURRENCY: "${WORKER_CONCURRENCY:-5}"', compose)
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
            "visuals/ClusterWeave.svg",
            "visuals/logo.svg",
            "visuals/logo_black.svg",
            "examples/README.md",
            "examples/accessions.txt",
            "examples/accessions_fungusID_taxonomyID.txt",
            "examples/summary/README.md",
            "examples/summary/family_atlas_shortlist.md",
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
        self.assertIn('href="/favicon.ico"', index_text)
        self.assertTrue((static_dir / "favicon.ico").exists())
        self.assertIn('href="assets/clusterweave.css?v=20260629-input-validation"', index_text)
        self.assertIn('src="assets/clusterweave.js?v=20260629-input-validation"', index_text)
        self.assertNotIn("<style>", index_text)
        self.assertNotIn("<script>\n", index_text)
        self.assertIn("function apiUrl(path)", js_text)
        self.assertIn("function handleResultLinkClick(event, jobId, relPath, download = false)", js_text)
        self.assertIn("const WORKFLOW_DNA_MODULE_PATH", js_text)
        self.assertIn("function bootBgcWorkflowDna()", js_text)
        self.assertIn('id="input-station-limit"', index_text)
        self.assertIn('id="upload-limit-note"', index_text)
        self.assertNotIn('input-method-tag standard', index_text)
        self.assertNotIn('input-method-tag secondary', index_text)
        self.assertNotIn('Local file input', index_text)
        self.assertIn('.setup-panel { grid-area: setup; overflow: hidden; align-self: start; }', css_text)
        self.assertIn('.brutal-accession-card {', css_text)
        self.assertIn('align-items: start;\n    margin-bottom: .7rem;', css_text)
        self.assertIn('grid-template-columns: minmax(0, 1fr) minmax(16rem, 1fr);', css_text)
        self.assertIn('background: white;\n    min-height: 0;', css_text)
        self.assertIn('box-shadow: 0 5px 0 var(--line);', css_text)
        self.assertIn('background: var(--blue-soft);\n  }\n  .brutal-accession-card label', css_text)
        self.assertNotIn('.input-method-tag', css_text)
        self.assertIn('background: #1155cc;\n    color: white;', css_text)
        self.assertIn('#target-genome-toggle { background: var(--yellow-soft); color: var(--ink); }', css_text)
        self.assertIn('.upload-card .dropbox', css_text)
        self.assertIn('max-height: min(22vh, 118px);', css_text)
        self.assertIn("PUBLIC_WEB_FAQ_URL", js_text)
        self.assertIn('id="bgc-tool-activity-chip"', index_text)
        self.assertIn(".tool-activity-chip", css_text)
        self.assertIn("function bgcActivityChipPayload", js_text)
        self.assertNotIn("data-progress-label", index_text)
        self.assertNotIn(".dna-panel::after", css_text)
        self.assertIn('body[data-access="public"] .admin-only', css_text)
        self.assertIn('body[data-job-state="complete"] .state-grid', css_text)
        self.assertNotIn("https://cdn", index_text + css_text + js_text)
        self.assertNotIn("unpkg.com", index_text + css_text + js_text)
        self.assertNotIn("tmp/node_geometry_render", index_text + css_text + js_text)

    def test_public_fasta_validation_streams_large_lines(self) -> None:
        app_text = (REPO_ROOT / "web" / "app.py").read_text(encoding="utf-8")
        self.assertIn("for raw_line in io.BytesIO(content):", app_text)
        self.assertIn("sequence_char_count += 1", app_text)
        self.assertNotIn("sequence_chars: list", app_text)
        self.assertNotIn("sequence_chars.extend", app_text)
        self.assertIn('route == "/favicon.ico"', app_text)

    def test_public_upload_parser_does_not_read_entire_body_before_multipart_parse(self) -> None:
        app_text = (REPO_ROOT / "web" / "app.py").read_text(encoding="utf-8")
        self.assertIn("cgi.FieldStorage", app_text)
        self.assertIn("content_length=content_length", app_text)
        self.assertIn("parse_multipart_form_data", app_text)
        self.assertIn("self.rfile", app_text)
        self.assertNotIn("body = self.rfile.read(content_length)", app_text)
        self.assertNotIn("BytesParser", app_text)

    def test_motion_vendor_policy_is_local_and_narrow(self) -> None:
        vendor_root = REPO_ROOT / "web" / "static" / "vendor"
        three_root = vendor_root / "three-0.184.0"
        gsap_root = vendor_root / "gsap-3.15.0"
        self.assertTrue((three_root / "three.module.min.js").exists())
        self.assertTrue((three_root / "LICENSE").exists())
        self.assertTrue((gsap_root / "gsap.min.js").exists())
        self.assertTrue((gsap_root / "STANDARD-LICENSE.md").exists())
        self.assertTrue((vendor_root / "VENDOR_NOTES.md").exists())
        vendored = sorted(path.relative_to(vendor_root).as_posix() for path in vendor_root.rglob("*") if path.is_file())
        self.assertEqual(vendored, [
            "VENDOR_NOTES.md",
            "gsap-3.15.0/STANDARD-LICENSE.md",
            "gsap-3.15.0/gsap.min.js",
            "three-0.184.0/LICENSE",
            "three-0.184.0/three.core.min.js",
            "three-0.184.0/three.module.min.js",
        ])
        notes = (vendor_root / "VENDOR_NOTES.md").read_text(encoding="utf-8")
        self.assertIn("three@0.184.0", notes)
        self.assertIn("build/three.module.min.js", notes)
        self.assertIn("build/three.core.min.js", notes)
        self.assertIn("same-package core module", notes)
        self.assertIn("5bca0a3851eea5345e4c205567b40dfa49b791b5", notes)
        self.assertIn("gsap@3.15.0", notes)
        self.assertIn("dist/gsap.min.js", notes)
        self.assertIn("7851baaffc77642f2db3b1749d3634f9b5a19d14", notes)
        self.assertIn("No GSAP plugins", notes)
        self.assertIn("public, same-origin runtime dependencies", notes)
        self.assertIn("local reference media", notes)
        self.assertNotIn("Retired DNA reference assets", notes)
        self.assertNotIn("gn_dna_tutorial_sharing.blend", notes)
        self.assertNotIn("Recording 2026-06-13 184339.mp4", notes)

    def test_web_retired_motion_controls_are_absent_with_safe_fallbacks(self) -> None:
        text = frontend_text()
        self.assertIn("function richMotionDisabled() {\n  return false;\n}", text)
        self.assertIn("const GSAP_BROWSER_PATH = 'vendor/gsap-3.15.0/gsap.min.js'", text)
        self.assertIn("function loadGsapMotion", text)
        self.assertIn("function teardownGsapMotion", text)
        self.assertNotIn('id="disable-rich-motion"', text)
        self.assertNotIn('id="enable-three-weavemap"', text)
        self.assertNotIn("Disable rich motion", text)
        self.assertNotIn("Enable 3D layer", text)
        self.assertIn("const RETIRED_MOTION_STORAGE_KEYS = [", text)
        self.assertIn("'clusterweave.richMotionDisabled'", text)
        self.assertIn("'clusterweave.threeWeavemapEnabled'", text)
        self.assertIn("function clearRetiredMotionSettings", text)
        self.assertIn("function initializeRetiredMotionControls", text)
        self.assertIn("document.body.dataset.threeWeavemap = 'disabled';", text)
        self.assertIn("document.body.dataset.threeWeavemapOptIn = 'disabled';", text)
        self.assertIn("function wireMotionLifecycleGuards", text)
        self.assertIn("document.addEventListener('visibilitychange'", text)
        self.assertIn("window.addEventListener('pagehide'", text)
        self.assertIn("helix.replaceChildren(weaveShell)", text)
        for removed in [
            "const THREE_WEAVEMAP_MODULE_PATH",
            "function scheduleThreeWeavemapRender",
            "function threeWeaveFallbackReason",
            "function threeWeavemapOptInEnabled",
            "function syncThreeWeavemapControl",
            "function webglAvailable",
            "function startThreeWeaveAnimationLoop",
            "function updateThreeWeaveAnimationFrame",
            "function probeThreeWeaveCanvasPixels",
            "function renderThreeWeavemap",
            "function buildThreeWeaveScene",
            "function wireThreeCanvasContextGuards",
            "new THREE.PerspectiveCamera",
            "new THREE.WebGLRenderer",
            "renderer.setAnimationLoop",
            "threeWeaveLayer",
            "threeHost.className = 'three-weavemap-layer'",
            "const threeRenderKey = JSON.stringify",
            "helix.dataset.threeRenderKey",
            "helix.replaceChildren(threeHost, weaveShell)",
            "host.dataset.threeWeavemap = 'animated'",
            "document.body.dataset.threeWeavemap = 'enabled'",
            "markThreeWeaveFallback('vendor-load-failed'",
            ".three-weavemap-layer",
            "three-weavemap-canvas",
            "powerPreference: 'low-power'",
        ]:
            self.assertNotIn(removed, text)
        self.assertNotIn("https://cdn", text)
        self.assertNotIn("unpkg.com", text)
        self.assertNotIn("jsdelivr", text.lower())

    def test_web_molecular_renderer_is_removed_from_results_workbench(self) -> None:
        ui_text = frontend_text()
        self.assertIn('id="result-dashboard-section"', ui_text)
        self.assertIn('id="download-package-btn"', ui_text)
        for removed in [
            'id="results-render-switch"',
            'id="results-render-workbench"',
            'id="results-render-molecular"',
            'id="molecular-renderer-panel"',
            'id="molecular-canvas-host"',
            'id="molecular-stage-legend"',
            "onclick=\"setResultsRenderMode('molecular')\"",
            "let resultsRenderMode = 'workbench';",
            'const THREE_MOLECULAR_MODULE_PATH',
            'function setResultsRenderMode(mode)',
            'function syncResultsRenderControls()',
            'function syncMolecularRenderer()',
            'function molecularFallbackToWorkbench(reason =',
            'function molecularRendererContextLost(renderer)',
            'function buildMolecularScene(THREE, layout, models)',
            'function renderMolecularRenderer(THREE, host, models, renderKey)',
            '.results-render-control',
            '.render-mode-button',
            '.molecular-renderer-canvas',
            '.molecular-stage-chip',
            '.molecular-output-button',
            'data-results-render-mode="molecular"',
            'dataset.molecularRenderer',
        ]:
            self.assertNotIn(removed, ui_text)
        self.assertNotIn('https://cdn', ui_text)
        self.assertNotIn('unpkg.com', ui_text)

    def test_web_results_run_switch_keeps_dashboard_spine_open(self) -> None:
        ui_text = frontend_text()
        self.assertIn("function shouldPreserveResultsDashboardForJobLoad(jobId, options = {})", ui_text)
        self.assertIn("runHasKnownResultFiles(historyJob)", ui_text)
        self.assertIn("const preferResultsDashboard = shouldPreserveResultsDashboardForJobLoad(jobId, options);", ui_text)
        self.assertIn("document.body.dataset.resultsDashboard = preferResultsDashboard ? 'open' : 'closed';", ui_text)
        self.assertIn("shouldOpenResultDashboardDuringRefresh(normalizedFiles, activeJobMeta)", ui_text)
        self.assertIn("panel.classList.remove('hidden');", ui_text)
        self.assertIn("resultDashboardOpen", ui_text)
        self.assertNotIn("spine.classList.toggle('spine-field', !loaded)", ui_text)
        self.assertNotIn("launch.insertBefore(spine, command)", ui_text)

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
        self.assertIn("function defaultFocusedResultCategory(counts)", ui_text)
        self.assertIn("resultCategoryAvailable('antismash', counts)", ui_text)
        self.assertIn("const completed = String(status || activeJobMeta?.status || '').toLowerCase() === 'success';", ui_text)
        self.assertIn("if (completed && resultFocusMode !== 'focused')", ui_text)
        self.assertIn("activeResultCategory = defaultFocusedResultCategory(counts);", ui_text)
        self.assertIn("setResultFocusMode('focused');", ui_text)
        self.assertIn("setResultFocusMode(completed ? 'focused' : 'overview');", ui_text)
        self.assertIn("if (completed) renderFocusedResultCategory(activeResultCategory);", ui_text)
        self.assertIn("function renderResultFileSurface(jobId, files)", ui_text)
        self.assertIn("if (resultFocusMode === 'focused')", ui_text)
        self.assertIn("renderFocusedResultCategory(activeResultCategory);", ui_text)
        self.assertIn("renderResultFileSurface(jobId, normalizedFiles);", ui_text)

    def test_web_results_access_panel_is_side_collapsible(self) -> None:
        ui_text = frontend_text()
        self.assertIn('data-results-panel="collapsed"', ui_text)
        self.assertIn('id="run-setup-access-panel"', ui_text)
        self.assertIn('id="run-setup-access-toggle"', ui_text)
        self.assertIn("function setRunSetupAccessCollapsed(collapsed)", ui_text)
        self.assertIn("function toggleRunSetupAccessPanel()", ui_text)
        self.assertIn('body:not([data-job-state="idle"]) .setup-access-head', ui_text)
        self.assertIn('id="result-access-toggle"', ui_text)
        self.assertIn('id="submission-confirmation-details"', ui_text)
        self.assertIn('data-result-access-collapsed="false"', ui_text)
        self.assertIn("let resultAccessCollapsed = false;", ui_text)
        self.assertIn("function setResultAccessCollapsed(collapsed)", ui_text)
        self.assertIn("function toggleResultAccessCard()", ui_text)
        self.assertIn('id="results-panel-toggle"', ui_text)
        self.assertIn('.results-panel-toggle { display: none !important; }', ui_text)
        self.assertNotIn('body[data-results-dashboard="open"] #results-card { display: none !important; }', ui_text)

    def test_web_workflow_progress_move_is_stable_during_results_refresh(self) -> None:
        ui_text = frontend_text()
        self.assertIn("const placement = loaded ? 'results' : 'idle';", ui_text)
        self.assertIn("const previousPlacement = spine.dataset.progressPlacement || '';", ui_text)
        self.assertIn("let moved = false;", ui_text)
        self.assertIn("spine.dataset.progressPlacement = placement;", ui_text)
        self.assertIn("spine.classList.toggle('hidden', !loaded);", ui_text)
        self.assertIn("const modeChanged = previousPlacement !== placement;", ui_text)
        self.assertIn("if (moved || modeChanged) {", ui_text)
        move_block = ui_text.split("function moveWorkflowProgressIntoResults(loaded = true)", 1)[1].split("function setResultsLoaded", 1)[0]
        self.assertIn("if (helix) delete helix.dataset.rendered;", move_block)
        self.assertIn("if (loaded) renderWeaveHelix(activeJobMeta);", move_block)
        self.assertNotIn("launch.insertBefore(spine, command)", move_block)
        self.assertNotIn("spine.classList.toggle('spine-field', !loaded)", move_block)
        self.assertNotIn("const helix = document.getElementById('weavemap-helix');\n  if (helix) delete helix.dataset.rendered;\n  renderWeaveHelix(activeJobMeta);", move_block)
        rerender_block = ui_text.split("function rerenderWorkflowSpineForResults(options = {})", 1)[1].split("function closeResultDashboardForManagementTarget", 1)[0]
        self.assertIn("if (options.force) {", rerender_block)
        self.assertNotIn("function rerenderWorkflowSpineForResults()", ui_text)

    def test_web_synteny_labels_skip_track_folders(self) -> None:
        ui_text = frontend_text()
        self.assertIn("atlas|priority|prioritized?|shared[-_]?family|shared|family|track|tracks", ui_text)
        self.assertIn("compound = titleCaseArtifactLabel(parts[i], 'clinker');", ui_text)
        self.assertIn("`${compound} - ${artifact}`", ui_text)

    def test_web_dna_spine_uses_continuous_ribbons(self) -> None:
        ui_text = frontend_text()
        dna_text = (REPO_ROOT / "web" / "static" / "assets" / "workflow-dna-progress.js").read_text(encoding="utf-8")
        self.assertIn('id="bgc-dna-canvas"', ui_text)
        self.assertIn('id="bgc-dna-progress-region"', ui_text)
        self.assertIn("import * as THREE from '../vendor/three-0.184.0/three.module.min.js';", dna_text)
        self.assertIn("appliedAs: 'color-fade-only'", dna_text)
        self.assertIn("motionPaused: state === 'failed'", ui_text)
        self.assertIn("this.motionPaused = Boolean(payload.motionPaused);", dna_text)
        self.assertIn("profileForState(payload.state)", dna_text)
        self.assertIn("const SEGMENTS = 192;", dna_text)
        self.assertIn("const BACKBONE_OVERLAP = 1.08;", dna_text)
        self.assertIn("new THREE.CylinderGeometry(0.055, 0.055, 1, 18, 1, true)", dna_text)
        self.assertIn("length * axialScale", dna_text)
        self.assertIn("workflow-dna-progress.js?v=20260628-dna-smooth", ui_text)
        self.assertNotIn("tmp/node_geometry_render", ui_text + dna_text)
        self.assertNotIn("data-segment=", ui_text)

    def test_frontend_opens_generated_html_for_private_result_users(self) -> None:
        ui_text = frontend_text()
        self.assertIn("function canOpenRichHtmlArtifacts(jobId = activeJobId)", ui_text)
        self.assertIn("return canUseAdminSurfaces() || !!readTokenForJob(jobId);", ui_text)
        self.assertIn("if (canOpenRichHtmlArtifacts(jobId)) return openHtmlResultWithAssets(event, jobId, relPath);", ui_text)
        self.assertIn("if (isHtmlAsset(path) && !canOpenRichHtmlArtifacts(jobId))", ui_text)

    def test_frontend_generated_html_preview_handles_relative_page_links(self) -> None:
        ui_text = frontend_text()
        self.assertIn("const RESULT_PREVIEW_NAVIGATOR_SCRIPT = String.raw", ui_text)
        self.assertIn("data-clusterweave-result-preview", ui_text)
        self.assertIn("data-clusterweave-result-href", ui_text)
        self.assertIn("function textDataUrl(text, mime)", ui_text)
        self.assertIn("reader.readAsDataURL(blob)", ui_text)
        self.assertIn("event.target.closest('a[href],area[href]')", ui_text)
        self.assertIn("openRelativeResult(rawUrl)", ui_text)
        self.assertIn("scriptEl.setAttribute('data-authorization', authHeadersFor('job', jobId).Authorization || '')", ui_text)

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
        self.assertIn('env["CLUSTERWEAVE_JOB_ID"] = job.id', text)
        self.assertIn('env["CLUSTERWEAVE_CANCEL_FILE"] = str(_job_cancel_path(job))', text)
        self.assertIn("start_new_session=True", text)
        self.assertIn("os.killpg(proc.pid, signal.SIGTERM)", text)
        self.assertIn("except asyncio.CancelledError", text)
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
        self.assertIn("Rerun scope", ui_text)
        self.assertIn('class="summary-panel rerun-summary rerun-scope-card"', ui_text)
        self.assertIn("rerunActiveJob()", ui_text)
        self.assertIn("function rerunJobFromHistory(event, jobId)", ui_text)
        self.assertIn("function toggleJobRerunScope(event, jobId)", ui_text)
        self.assertIn("class=\"job-rerun${rerunOpen ? \' active\' : \'\'}\"", ui_text)
        self.assertIn("function rerunPayloadFromStages(stageKeys", ui_text)
        self.assertIn("function queueJobRerun(jobId, payload)", ui_text)
        self.assertIn("function rerunStageAllowed(key)", ui_text)
        self.assertIn("Selected stages rerun inside this job workspace and reuse staged inputs/results.", ui_text)
        self.assertIn("Select a submitted job, then use its Rerun button to open job-scoped rerun options.", ui_text)
        self.assertIn("Rerun unavailable while active.", ui_text)

    def test_web_progress_popout_uses_ordered_stage_overview(self) -> None:
        text = frontend_text()
        self.assertIn("function bgcWorkflowStages", text)
        self.assertIn("function bgcStageStatus", text)
        self.assertIn("function bgcWorkflowPayload", text)
        self.assertIn("steps: stages.map(stage => ({", text)
        self.assertIn("currentStepId: currentKey || ''", text)
        self.assertIn("motionPaused: state === 'failed'", text)
        self.assertIn("activityText: activityChip.text", text)
        self.assertIn("function latestJobPublicWorkflowEvent", text)
        self.assertIn("function latestToolActivityParts", text)
        self.assertIn("pieces.join(' | ')", text)
        self.assertIn("activityElapsedFromMeta", text)
        self.assertIn("const WORKFLOW_PROGRESS_WEIGHTS", text)
        self.assertIn("function annotationGenomeProgress", text)
        self.assertIn("function weightedWorkflowProgress", text)
        self.assertIn("Genome\\s+(\\d+)\\s+of\\s+(\\d+)", text)
        self.assertIn("stationDetailText: state === 'running' ? '' : detail", text)
        self.assertIn("progressLabel: stageProgress?.label || ''", text)
        self.assertIn("if (payload.progressLabel) return payload.progressLabel;", text)
        self.assertIn("detail.hidden = !stationDetail;", text)
        self.assertNotIn("const currentWeight = status === 'failed' ? 0.5 : 0.5", text)
        self.assertIn("function renderBgcWorkflowStageStrip(payload)", text)
        self.assertIn('data-bgc-stage="${escapeHtml(step.id)}"', text)
        self.assertNotIn("function workflowStageOverviewNodes", text)
        self.assertNotIn("dna-popover-connector-layer", text)

    def test_dev_admin_ops_panel_stays_available_on_outputs(self) -> None:
        static_dir = REPO_ROOT / "web" / "static"
        index_text = (static_dir / "index.html").read_text(encoding="utf-8")
        css_text = (static_dir / "assets" / "clusterweave.css").read_text(encoding="utf-8")
        js_text = (static_dir / "assets" / "clusterweave.js").read_text(encoding="utf-8")
        self.assertIn('data-ops-panel="collapsed"', index_text)
        self.assertIn('data-ops-tab="jobs"', index_text)
        self.assertNotIn('id="ops-panel-toggle"', index_text)
        self.assertIn("toggle.id = 'ops-panel-toggle';", js_text)
        self.assertIn("document.body.insertBefore(toggle, panel);", js_text)
        self.assertIn("function ensureOpsPanelToggle()", js_text)
        self.assertIn("function removeOpsPanelToggle()", js_text)
        self.assertIn("function setOpsPanelCollapsed(collapsed)", js_text)
        self.assertIn('role="tablist" aria-label="Diagnostics navigation"', index_text)
        for tab in ["ops-tab-jobs", "ops-tab-worker", "ops-tab-qa", "ops-tab-rerun"]:
            self.assertIn(f'id="{tab}"', index_text)
        self.assertIn('body[data-access="public"] .admin-only', css_text)
        self.assertIn('body[data-ops-panel="collapsed"] .ops-side-panel', css_text)
        self.assertIn('.ops-panel-toggle', css_text)
        self.assertIn('.ops-side-panel.admin-drawer', css_text)
        self.assertNotIn('body[data-results-dashboard="open"][data-management-view="closed"] .ops-side-panel { display: none !important; }', css_text)

    def test_worker_supports_bounded_concurrency(self) -> None:
        text = (REPO_ROOT / "web" / "worker.py").read_text(encoding="utf-8")
        self.assertIn('WORKER_CONCURRENCY = max(1, int(os.environ.get("WORKER_CONCURRENCY", "1")))', text)
        self.assertIn("async def worker_loop()", text)
        self.assertIn("active_jobs", text)
        self.assertIn("payload = dict(read_job(job.id) or {})", text)
        self.assertIn("job_cancel_requested(job_id)", text)
        self.assertIn("task.cancel()", text)
        self.assertIn("def stop_job_containers(job_id: str)", text)
        self.assertIn("finalize_cancelled_job(job_id", text)
        self.assertIn("label=clusterweave.job_id={job_id}", text)

    def test_stage_docker_containers_are_labeled_for_cancellation(self) -> None:
        for rel in [
            "run_annotation_and_detection.sh",
            "run_bigscape.sh",
            "run_nplinker.sh",
            "run_clinker.sh",
            "bin/stage_clinker_panels.py",
        ]:
            text = (REPO_ROOT / rel).read_text(encoding="utf-8")
            self.assertIn("clusterweave.job_id=${CLUSTERWEAVE_JOB_ID}", text, rel)
            self.assertIn("clusterweave.project=${PROJECT_NAME:-}", text, rel)

    def test_ui_stage_states_use_semantic_classes(self) -> None:
        text = frontend_text()
        self.assertIn(".stage-card", text)
        self.assertIn(".bgc-stage-card.complete", text)
        self.assertIn(".bgc-stage-card.running", text)
        self.assertIn(".bgc-stage-card.error", text)
        self.assertIn("function initializeStageState(job)", text)
        self.assertIn("function finalizeStageState(status)", text)
        self.assertIn("function renderBgcWorkflowStageStrip(payload)", text)
        self.assertIn('class="stage-card bgc-stage-card ${escapeHtml(step.status)}"', text)

    def test_web_stage_elapsed_uses_stable_stage_timing_snapshots(self) -> None:
        text = frontend_text()
        self.assertIn("startedAtSource", text)
        self.assertIn("endedAtSource", text)
        self.assertIn("appliedEvents: new Set()", text)
        self.assertIn("lastEventMs: null", text)
        self.assertIn("function stageTimestampFromLogLine", text)
        self.assertIn("function applyStageTimingFromPublicEvents(job)", text)
        self.assertIn("function terminalStageTimeMs(status)", text)
        self.assertIn("function shouldApplyJobStageSnapshot(key)", text)
        self.assertIn("parseTimestampMs(job?.stage_updated_at || job?.started_at || job?.created_at || job?.updated_at)", text)
        self.assertIn("const eventId = `snapshot:${job?.id || ''}:${job?.rerun_count || 0}:${status}:${key}:${snapshotMs}`;", text)
        self.assertIn("const eventId = `log:${activeJobId || ''}:${logCursor}:${key}`;", text)

        start_block = text.split("function setStageStartTime(key, ms, source = 'snapshot', options = {})", 1)[1].split("function setStageEndTime", 1)[0]
        self.assertIn("const sourceRank = stageTimingSourceRank(source);", start_block)
        self.assertIn("const sameSourceEarlier = sourceRank === currentRank && ms < current;", start_block)
        self.assertNotIn("ms < current || (betterSource && ms <= current)", start_block)

        snapshot_block = text.split("function shouldApplyJobStageSnapshot(key)", 1)[1].split("function applyJobStageSnapshot", 1)[0]
        self.assertIn("return currentIdx < 0 || snapshotIdx < 0 || snapshotIdx >= currentIdx;", snapshot_block)

        elapsed_block = text.split("function stageElapsedText(key, visualCls)", 1)[1].split("function currentWorkflowStage", 1)[0]
        self.assertIn("formatDuration(Date.now() - start)", elapsed_block)
        self.assertIn("formatDuration(end - start)", elapsed_block)
        self.assertNotIn("jobElapsedText(activeJobMeta)", elapsed_block)

        transition_block = text.split("function advanceToStage(key, options = {})", 1)[1].split("function sanitizeWeaveLogTitle", 1)[0]
        self.assertIn("if (eventId && activeStageState.appliedEvents.has(eventId)) return;", transition_block)
        self.assertIn("if (isRestart) clearStageTimingFrom(key);", transition_block)
        self.assertIn("setStageStartTime(key, eventMs, source, { force: isRestart });", transition_block)
        self.assertIn("setStageEndTime(activeStageState.current, eventMs, source);", transition_block)

        final_block = text.split("function finalizeStageState(status)", 1)[1].split("function renderStageState", 1)[0]
        self.assertIn("if (activeStageState.current) setStageEndTime(activeStageState.current, terminalMs, 'terminal');", final_block)
        self.assertIn("setStageEndTime(failedKey, terminalMs, 'terminal');", final_block)

        public_block = text.split("function publicStageTimingEvent(event)", 1)[1].split("async function deleteJob", 1)[0]
        self.assertIn("const markerMeta = /^canonical workflow stage$/i.test(marker.meta || '');", public_block)
        self.assertIn("const eventTimeMs = stageTimestampFromClock(marker.time || marker.meta, job, activeStageState.lastEventMs);", public_block)

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

    def test_web_results_output_chips_are_accessible_without_legacy_subtabs(self) -> None:
        text = frontend_text()
        self.assertIn('id="result-bubble-panel" role="tablist"', text)
        self.assertIn('role="tab" data-output-key=', text)
        self.assertIn('aria-selected="${selected ? \'true\' : \'false\'}"', text)
        self.assertIn('aria-controls="result-focus-panel"', text)
        self.assertIn('onclick="focusResultCategory', text)
        self.assertIn("function setResultReaderSurface(surface)", text)
        self.assertNotIn('button class="tab active"', text)
        self.assertNotIn("function handleResultTabKeydown(event)", text)
        self.assertNotIn("function switchTab(name", text)
        self.assertNotIn('role="tabpanel" aria-labelledby="tab-control-viz"', text)
        self.assertNotIn('role="tabpanel" aria-labelledby="tab-control-files"', text)

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
        self.assertIn("setBrutalInputNotice('submission', '')", text)
        self.assertIn("setBrutalInputNotice('submission', message)", text)

    def test_web_has_journey_first_navigation_and_hero(self) -> None:
        text = frontend_text()
        self.assertIn('data-job-state="idle"', text)
        self.assertIn('class="state-grid" id="state-grid"', text)
        self.assertIn('aria-label="Discover the hidden potential of fungi"', text)
        self.assertIn('<span>Discover</span><span>the</span><span>hidden</span><span>potential</span><span>of</span><span>fungi</span>', text)
        self.assertIn('class="logo-mark" role="img" aria-label="ClusterWeave"', text)
        self.assertIn('<strong>INPUT STATION</strong>', text)
        self.assertIn('id="entry-tab-new"', text)
        self.assertIn('id="entry-tab-existing"', text)
        self.assertIn('id="brutal-accession-rows"', text)
        self.assertIn('href="https://www.ncbi.nlm.nih.gov/datasets/genome/"', text)
        self.assertIn('NCBI genomes</a>', text)
        self.assertIn('id="drop-zone" tabindex="0" role="button" aria-label="Upload genome or accession files"', text)
        self.assertIn('id="file-input" multiple accept=', text)
        self.assertIn('id="docs"', text)
        self.assertIn('Upstream Tool Credit', text)
        self.assertIn('href="https://github.com/n2mology/clusterweave"', text)
        self.assertNotIn('id="primary-nav"', text)
        self.assertNotIn('nav-toggle', text)
        self.assertNotIn('launch-deck', text)
        self.assertNotIn('right-column', text)
        self.assertNotIn('weavemap-section', text)
        self.assertNotIn('href="#weavemap" data-nav-target="weavemap"', text)

    def test_web_has_user_modes_and_section_hierarchy(self) -> None:
        text = frontend_text()
        self.assertIn('data-ui-mode="guided"', text)
        self.assertNotIn('id="mode-panel"', text)
        self.assertNotIn('data-mode-option="guided"', text)
        self.assertIn("function setUIMode(mode", text)
        self.assertIn("if (accessMode === 'public' && mode !== 'guided') mode = 'guided'", text)
        self.assertIn('class="runtime-bridge" hidden inert aria-hidden="true"', text)
        self.assertIn('id="run-genome-prep" checked', text)
        self.assertIn('id="run-annotation" checked', text)
        self.assertIn('id="advanced-panel"', text) if 'id="advanced-panel"' in text else self.assertNotIn('id="advanced-panel"', text)
        self.assertIn('id="jobs-card"', text)
        self.assertIn('id="console-card"', text)
        self.assertIn('id="progress-card"', text)

    def test_web_lab_console_scroll_bottom_targets_visible_log_viewport(self) -> None:
        text = frontend_text()
        self.assertIn("function scrollElementToBottom(el)", text)
        self.assertIn("const lastLine = term.lastElementChild;", text)
        self.assertIn("lastLine.scrollIntoView({ block: 'end', inline: 'nearest' });", text)
        self.assertIn("const body = term.closest('.lab-console-body');", text)
        self.assertIn('id="log-terminal"', text)
        self.assertIn('id="system-console"', text)
        self.assertIn(".drawer-body", text)
        self.assertIn(".log-terminal", text)
        self.assertIn("max-height: 44vh", text)

    def test_web_has_neumorphic_surface_system_tokens(self) -> None:
        text = frontend_text()
        for token in [
            "--ink", "--paper", "--panel", "--cyan", "--pink", "--acid",
            "--lavender", "--line", "--shadow", "--shadow-small", "--radius",
        ]:
            self.assertIn(token, text)
        self.assertIn(".module {", text)
        self.assertIn(".state-grid", text)
        self.assertIn(".brutal-button", text)
        self.assertIn(".dropbox", text)
        self.assertIn("box-shadow: var(--shadow)", text)
        self.assertNotIn("--cw-surface-panel", text)
        self.assertNotIn("--cw-raise-panel", text)

    def test_web_has_retrofuturist_weavemap_and_outputs_polish(self) -> None:
        text = frontend_text()
        self.assertIn('aria-label="BGC WORKFLOW STATION"', text)
        self.assertIn('id="workflow-progress-panel"', text)
        self.assertIn('id="bgc-dna-canvas"', text)
        self.assertIn('id="bgc-stage-strip"', text)
        self.assertIn("function bgcWorkflowPayload", text)
        self.assertIn("function updateBgcWorkflowDnaFromJob", text)
        for label in ["Prep", "Annotation / BGC detection", "BiG-SCAPE", "Summary", "clinker", "Figures"]:
            self.assertIn(label, text)
        self.assertIn('id="result-bubble-panel"', text)
        self.assertIn('class="result-output-strip"', text)
        self.assertIn('id="result-reader-surface"', text)
        self.assertIn("function setResultReaderSurface", text)
        self.assertIn('class="brutal-button secondary result-package-download"', text)
        self.assertNotIn('result-focus-toolbar', text)
        self.assertNotIn('result-overview-btn', text)
        self.assertNotIn('result-focus-label', text)
        self.assertNotIn('result-output-tabs', text)
        self.assertNotIn('tab-control-viz', text)
        self.assertNotIn('tab-control-files', text)
        self.assertIn("resultDownloadLink(jobId, item.path, 'Download')", text)
        self.assertIn("resultDownloadLink(jobId, path, 'Download')", text)
        self.assertIn("BiG-SCAPE web view", text)
        self.assertIn("resultDownloadLink(jobId, bigscape.database, 'Download')", text)
        self.assertIn("window.CLUSTERWEAVE_BIGSCAPE_DATABASE_AUTH", text)
        self.assertIn("const dbUrl = resultHref(jobId, databasePath);", text)
        self.assertIn("const dbAuth = authHeadersFor('job', jobId).Authorization || '';", text)
        self.assertIn("fetch(url, options).then", text)
        self.assertIn("window.CLUSTERWEAVE_BIGSCAPE_DATABASE_BYTES = buffer.byteLength || 0;", text)
        self.assertNotIn("dbResp.blob()", text)
        autoload_block = text.split("async function autoloadDatabase()", 1)[1].split("window.CLUSTERWEAVE_BIGSCAPE_AUTOLOAD_DATABASE", 1)[0]
        self.assertNotIn("attachInputFile(buffer);", autoload_block)
        self.assertIn("function renderMarkdownBody(text)", text)
        app_text = (REPO_ROOT / "web" / "app.py").read_text(encoding="utf-8")
        self.assertIn("def _send_file(", app_text)
        self.assertIn("shutil.copyfileobj(handle, self.wfile, length=1024 * 1024)", app_text)
        self.assertIn("self._send_file(HTTPStatus.OK, full, result_file_mime(full), headers)", app_text)
        self.assertNotIn("self._send_text(HTTPStatus.OK, result_file_mime(full), full.read_bytes(), headers)", app_text)
        self.assertIn("function condensedMarkdownBodyText(text)", text)
        self.assertIn("function summaryTopCount(text)", text)
        self.assertIn("summaryCondensedTitle(path, text, count)", text)
        self.assertIn("summary-condensed-title", text)
        self.assertIn("summary-markdown-body", text)
        self.assertIn("source\\s+summary", text)
        self.assertNotIn('id="summary-reader-source"', text)
        self.assertNotIn("source.textContent = summaryArtifactLabel(path)", text)
        self.assertNotIn('id="alt06-result-folder-panel"', text)
        self.assertNotIn('id="alt06-result-folder-title"', text)
        for label in ["ANTISMASH", "FUNBGCEX", "BIG-SCAPE", "CLINKER", "SUMMARY", "FIGURES"]:
            self.assertIn(label, text)
        self.assertNotIn('class="weavemap-section section-anchor hidden" id="weavemap"', text)
        self.assertNotIn('id="weavemap-helix"', text)
        self.assertNotIn("dna-status-strip", text)
        self.assertNotIn("Heartbeat", text)

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
        self.assertIn('id="access-code-input"', text)
        self.assertIn('id="opened-runs-select"', text)
        self.assertIn("sessionStorage.setItem", text)
        self.assertIn("function parseExistingRunInput()", text)
        self.assertIn("function rememberOpenedRun(jobId, token", text)
        self.assertIn("let pendingReadTokens = new Map()", text)
        self.assertIn("const deferResultsShell = !!options.deferResultsShell", text)
        self.assertIn("if (!deferResultsShell) {", text)
        self.assertIn("showResultsShell();", text)
        self.assertIn("function authHeadersFor(kind, jobId = null)", text)
        self.assertIn("function handleResultLinkClick(event, jobId, relPath, download = false)", text)
        self.assertIn('body[data-access="public"] .admin-only', text)
        self.assertIn('id="ops-side-panel"', text)
        self.assertNotIn('id="ops-panel-toggle"', (REPO_ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8"))
        self.assertIn('id="input-checker"', text)
        self.assertIn('id="input-checker-list"', text)
        self.assertIn("function renderInputChecker()", text)
        self.assertIn("function cacheGenomeFileCheck(file)", text)
        self.assertIn("sequenceChars += clean.length", text)
        self.assertNotIn("sequenceChars.push(...clean)", text)
        self.assertIn("let brutalAccessionCommitted = new Set()", text)
        self.assertIn("function commitBrutalAccessionRow(row)", text)
        self.assertIn("function handleBrutalAccessionFocusout(event)", text)
        self.assertIn("brutalAccessionDraftIssues({ committedOnly = true } = {})", text)
        self.assertIn("rows.addEventListener('focusout', handleBrutalAccessionFocusout)", text)
        self.assertIn("CLIENT_GENOME_PRECHECK_BYTES", text)
        self.assertIn("function readClientGenomePreview(file)", text)
        self.assertIn("browserGenomePrecheckUnavailableReason", text)
        self.assertIn("still syncing", text)
        self.assertIn("not plain-text FASTA/GenBank", text)
        self.assertIn("client_preflight_unconfirmed", text)
        self.assertNotIn("Could not read this genome file in the browser.", text)
        self.assertIn("const PUBLIC_FILE_EXTENSIONS = new Set(['gbk','gb','gbff','fasta','fa','fna','fsa','txt']);", text)
        self.assertNotIn("submit_token=", text)
        self.assertNotIn("admin_token=", text)

    def test_web_human_language_contract_keeps_public_and_admin_purpose_clear(self) -> None:
        text = frontend_text()
        for copy in [
            "Discover", "the", "hidden", "potential", "of", "fungi", "INPUT STATION", "New run", "Existing results",
            "TARGET GENOME", "ADD ECOLOGY", "Submit run", "Result blocks", "BGC WORKFLOW STATION",
        ]:
            self.assertIn(copy, text)
        for admin_copy in ["Jobs", "Worker", "QA Console", "Rerun", "Open diagnostics drawer"]:
            self.assertIn(admin_copy, text)
        self.assertIn('class="ops-panel-nav drawer-tabs" role="tablist" aria-label="Diagnostics navigation"', text)
        self.assertIn('id="ops-tab-jobs" type="button" role="tab" data-ops-tab="jobs"', text)
        self.assertIn('id="ops-tab-qa" type="button" role="tab" data-ops-tab="qa"', text)
        self.assertNotIn('class="nav-link admin-only" href="#jobs-card"', text)
        self.assertNotIn('class="nav-link admin-only" href="#console-card"', text)
        self.assertNotIn("shell-first controller", text)
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
        self.assertIn('id="project-name" rows="1" autocomplete="off"', ui_text)
        self.assertIn('autocapitalize="none" autocorrect="off" spellcheck="false" placeholder="fungal_survey"', ui_text)
        self.assertLess(ui_text.index('id="project-name"'), ui_text.index('id="email-notification-panel"'))
        self.assertLess(ui_text.index('id="email-notification-panel"'), ui_text.index('id="target-genome-toggle"'))
        self.assertLess(ui_text.index('id="target-genome-toggle"'), ui_text.index('id="target-genome"'))
        self.assertIn("let smtpEnabled = false", ui_text)
        self.assertIn("smtpEnabled = !!payload.smtp_enabled", ui_text)
        self.assertIn("fd.append('notify_email', notifyEmail)", ui_text)
        self.assertIn('SMTP_ENABLED = env_bool("CLUSTERWEAVE_SMTP_ENABLED"', app_text)
        self.assertIn('"smtp_enabled": SMTP_ENABLED', app_text)
        self.assertIn('"notify_email"', app_text)
        self.assertIn("maybe_send_terminal_notification(job_id)", worker_text)
        self.assertIn("CLUSTERWEAVE_SMTP_SSL", notifications_text)
        self.assertIn("def build_job_email", notifications_text)
        self.assertIn("Suggested fixes:", notifications_text)
        self.assertIn("def sweep_expired_jobs", job_store_text)
        self.assertIn("sweep_expired_jobs()", maintenance_text)
        self.assertIn('CLUSTERWEAVE_SMTP_SSL: "${CLUSTERWEAVE_SMTP_SSL:-0}"', compose_text)
        self.assertIn("CLUSTERWEAVE_PUBLIC_MODE", compose_text)
        self.assertIn("CLUSTERWEAVE_ADMIN_TOKEN", compose_text)
        self.assertIn('CLUSTERWEAVE_JOB_TOKEN_SECRET: "${CLUSTERWEAVE_JOB_TOKEN_SECRET:-}"', compose_text)

    def test_web_ecology_label_table_uses_controlled_public_inputs(self) -> None:
        text = frontend_text()
        html_text = (REPO_ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="ecology-label-panel"', text)
        self.assertIn('id="brutal-ecology-toggle"', text)
        self.assertIn('id="run-ecology"', text)
        self.assertIn('id="metadata-table-body"', text)
        self.assertLess(html_text.index('id="brutal-ecology-toggle"'), html_text.index('id="data-use-ack-panel"'))
        self.assertIn('<th>Input</th><th>Primary ecology</th><th>Secondary ecology</th>', text)
        self.assertIn("const ECOLOGY_LABELS = [", text)
        for label in [
            "soil", "plant_associated", "endophyte", "mycorrhiza", "plant_pathogen",
            "saprotroph", "marine", "freshwater", "lichen_associated", "insect_associated",
            "animal_associated", "human_associated", "food_fermentation", "unknown", "other",
        ]:
            self.assertIn(f"'{label}'", text)
        self.assertIn("function ecologyInputRows()", text)
        self.assertIn("function syncEcologyMetadataPanel()", text)
        self.assertIn("function metadataProfileText()", text)
        self.assertIn("accession\\tgenome_id_current\\ttaxonomy_id\\tgenome_size_mb\\tgenome_id_original_if_different\\tecofun_primary\\tecofun_secondary", text)
        self.assertIn("normalizeShortToken", text)
        self.assertNotIn("Editable Ecology Metadata", text)
        self.assertNotIn("addMetadataRow()", text)

    def test_web_serves_result_assets_inline_unless_download_requested(self) -> None:
        text = (REPO_ROOT / "web" / "app.py").read_text(encoding="utf-8")
        self.assertIn('"image/svg+xml; charset=utf-8"', text)
        self.assertIn('"Cache-Control": "no-store"', text)
        self.assertIn('STATIC_ASSET_DIR = STATIC_DIR / "assets"', text)
        self.assertIn('STATIC_VENDOR_DIR = STATIC_DIR / "vendor"', text)
        self.assertIn('if route.startswith("/assets/"):', text)
        self.assertIn('if route.startswith("/vendor/"):', text)
        self.assertIn("full.relative_to(asset_root)", text)
        self.assertIn("full.relative_to(vendor_root)", text)
        self.assertIn('"Cache-Control": "public, max-age=86400"', text)
        self.assertIn('"X-Content-Type-Options": "nosniff"', text)
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
