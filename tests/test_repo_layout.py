import csv
import json
import os
from pathlib import Path
import re
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
            "bin/compact_antismash_shard.py",
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

    def test_annotation_detailed_logs_use_canonical_private_results_directory(self) -> None:
        annotation = (REPO_ROOT / "run_annotation_and_detection.sh").read_text(encoding="utf-8")
        wrapper = (REPO_ROOT / "run_clusterweave.sh").read_text(encoding="utf-8")

        self.assertIn('mkdir -p "${RESULTS_ROOT}/logs"', annotation)
        self.assertIn(
            'rsync -a "${WORK_ROOT}/logs/" "${RESULTS_ROOT}/logs/"',
            annotation,
        )
        self.assertIn('See ${manifest} and ${RESULTS_ROOT}/logs.', wrapper)
        self.assertNotIn("${RESULTS_ROOT}/summary_tables/logs", annotation + wrapper)

    def test_annotation_stage_supports_bounded_genome_fanout(self) -> None:
        text = (REPO_ROOT / "run_annotation_and_detection.sh").read_text(encoding="utf-8")
        self.assertIn('GENOME_PARALLELISM="${GENOME_PARALLELISM:-${ANNOTATION_GENOME_PARALLELISM:-1}}"', text)
        self.assertIn('[-p GENOME_PARALLELISM]', text)
        self.assertIn('p) GENOME_PARALLELISM="${OPTARG}" ;;', text)
        self.assertIn('GENOME_PARALLELISM="$(positive_int_or_default "${GENOME_PARALLELISM}" 1)"', text)
        self.assertIn('running_genome_job_count()', text)
        self.assertIn('wait -n', text)
        self.assertIn('process_genome() {', text)
        self.assertIn('MANIFEST_ROW_DIR="${WORK_ROOT}/tmp/manifest_rows"', text)
        self.assertIn('write_genome_manifest_row "${row_file}"', text)
        self.assertIn('process_genome "${genome_id}" "${idx}" "${row_file}" "${#GEN_ARR[@]}" &', text)
        self.assertIn('cat "${row_file}" >> "${MANIFEST}"', text)
        self.assertIn('GENOME_PROGRESS genome=', text)
        process_body = text.split('process_genome() {', 1)[1].split('\n}\n\nidx=0', 1)[0]
        self.assertIn('annotate_genome_with_fallbacks "${genome_id}" "${fasta}" "${staged_gbk}"', process_body)
        self.assertNotIn('>> "${MANIFEST}"', process_body)
        self.assertNotIn('continue', process_body)

    def test_annotation_resource_plan_is_frozen_and_cpu_bounded(self) -> None:
        text = (REPO_ROOT / "run_annotation_and_detection.sh").read_text(encoding="utf-8")
        planner = text.split("freeze_resource_plan() {", 1)[1].split(
            "running_genome_job_count() {", 1
        )[0]
        docker_args = text.split("docker_run_args() {", 1)[1].split(
            "docker_exec() {", 1
        )[0]
        funannotate = text.split("run_funannotate_predict_to_gbk() {", 1)[1].split(
            "annotate_genome_with_fallbacks() {", 1
        )[0]

        self.assertIn('PIPELINE_RESOURCE_MODE="${PIPELINE_RESOURCE_MODE:-conservative}"', text)
        self.assertIn("detect_effective_cpus()", text)
        self.assertIn('local cgroup_root="${1:-/sys/fs/cgroup}"', text)
        self.assertIn('"${cgroup_root}/cpu.max"', text)
        self.assertIn("detect_effective_memory_mb()", text)
        self.assertIn("/sys/fs/cgroup/memory.max", text)
        self.assertIn('PIPELINE_AUTO_MEMORY_PER_GENOME_MB="${PIPELINE_AUTO_MEMORY_PER_GENOME_MB:-8192}"', text)
        self.assertIn('freeze_resource_plan "${#GEN_ARR[@]}"', text)
        self.assertGreater(
            text.index('freeze_resource_plan "${#GEN_ARR[@]}"'),
            text.index('log "Genomes to process'),
        )
        self.assertIn('PER_GENOME_CPU_BUDGET=$((CPUS / GENOME_PARALLELISM))', planner)
        self.assertIn('annotation_slots=$((GENOME_PARALLELISM * ANNO_CPUS))', planner)
        self.assertIn('funbgcex_slots=$((GENOME_PARALLELISM * WORKERS))', planner)
        self.assertIn(
            'antismash_shard_slots=$((GENOME_PARALLELISM * ANTISMASH_RECORD_PARALLELISM * ANTISMASH_SHARD_CPUS))',
            planner,
        )
        self.assertIn('antismash_legacy_slots=$((GENOME_PARALLELISM * ANTISMASH_LEGACY_CPUS))', planner)
        self.assertIn("Resource plan invariant failed", planner)
        self.assertIn("RESOURCE_PLAN_FROZEN", planner)
        self.assertIn("RESOURCE_PLAN_BOUNDS", planner)
        self.assertIn('--cpus "${child_cpus}"', docker_args)
        self.assertIn('--memory "${child_memory}"', docker_args)
        self.assertIn('--pids-limit "${child_pids}"', docker_args)
        for variable in [
            "OMP_NUM_THREADS",
            "OPENBLAS_NUM_THREADS",
            "MKL_NUM_THREADS",
            "NUMEXPR_NUM_THREADS",
            "VECLIB_MAXIMUM_THREADS",
            "BLIS_NUM_THREADS",
        ]:
            self.assertIn(variable, docker_args)
        self.assertIn('--cpus "${ANNO_CPUS}"', funannotate)
        self.assertNotIn("--limit-to-record", funannotate)
        self.assertIn("Funannotate is never split by GenBank record", text)

    def test_annotation_resource_plan_arithmetic_respects_job_budget(self) -> None:
        text = (REPO_ROOT / "run_annotation_and_detection.sh").read_text(encoding="utf-8")
        helper_block = "positive_int_or_default() {" + text.split(
            "positive_int_or_default() {", 1
        )[1].split("\nrunning_genome_job_count() {", 1)[0]
        base = (
            "set -euo pipefail\n"
            + helper_block
            + "\n"
            + "detect_effective_cpus(){ printf '12\\n'; }\n"
            + "detect_effective_memory_mb(){ printf '24576\\n'; }\n"
            + "log(){ :; }\n"
            + "die(){ printf '%s\\n' \"$*\" >&2; exit 99; }\n"
            + "PIPELINE_AUTO_MAX_CPUS=32\n"
            + "PIPELINE_AUTO_MAX_GENOME_PARALLELISM=4\n"
            + "PIPELINE_AUTO_MIN_CPUS_PER_GENOME=2\n"
            + "PIPELINE_AUTO_MEMORY_PERCENT=70\n"
            + "PIPELINE_AUTO_MEMORY_PER_GENOME_MB=8192\n"
            + "PIPELINE_AUTO_MAX_ANNO_CPUS=8\n"
            + "PIPELINE_AUTO_MAX_FUNBGCEX_WORKERS=2\n"
            + "PIPELINE_AUTO_MAX_ANTISMASH_RECORD_PARALLELISM=3\n"
            + "PIPELINE_MEMORY_BUDGET_MB=\n"
        )
        scenarios = [
            (
                "auto",
                (
                    "PIPELINE_RESOURCE_MODE=auto\nCPUS_REQUEST_EXPLICIT=0\n"
                    "CPUS=6\nGENOME_PARALLELISM=1\nANNO_CPUS=6\nWORKERS=2\n"
                    "ANTISMASH_RECORD_PARALLELISM=1\n"
                    "ANTISMASH_SHARD_CPUS_REQUESTED=\nANTISMASH_LEGACY_CPUS_REQUESTED=\n"
                ),
                {
                    "cpus": 12,
                    "genomes": 2,
                    "lane": 6,
                    "anno": 6,
                    "workers": 2,
                    "records": 3,
                    "shard": 2,
                    "legacy": 6,
                },
            ),
            (
                "manual",
                (
                    "PIPELINE_RESOURCE_MODE=manual\nCPUS_REQUEST_EXPLICIT=1\n"
                    "CPUS=12\nGENOME_PARALLELISM=5\nANNO_CPUS=8\nWORKERS=10\n"
                    "ANTISMASH_RECORD_PARALLELISM=4\n"
                    "ANTISMASH_SHARD_CPUS_REQUESTED=9\nANTISMASH_LEGACY_CPUS_REQUESTED=9\n"
                ),
                {
                    "cpus": 12,
                    "genomes": 5,
                    "lane": 2,
                    "anno": 2,
                    "workers": 2,
                    "records": 2,
                    "shard": 1,
                    "legacy": 2,
                },
            ),
        ]
        for name, settings, expected in scenarios:
            with self.subTest(mode=name):
                command = (
                    base
                    + settings
                    + "freeze_resource_plan 25\n"
                    + "printf 'cpus=%s genomes=%s lane=%s anno=%s workers=%s records=%s shard=%s legacy=%s\\n' "
                    + '"$CPUS" "$GENOME_PARALLELISM" "$PER_GENOME_CPU_BUDGET" "$ANNO_CPUS" '
                    + '"$WORKERS" "$ANTISMASH_RECORD_PARALLELISM" "$ANTISMASH_SHARD_CPUS" "$ANTISMASH_LEGACY_CPUS"\n'
                )
                result = subprocess.run(
                    ["bash", "-c", command],
                    cwd=str(REPO_ROOT),
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                observed = {
                    key: int(value)
                    for key, value in (
                        field.split("=", 1) for field in result.stdout.strip().split()
                    )
                }
                self.assertEqual(observed, expected)
                self.assertLessEqual(observed["genomes"] * observed["anno"], observed["cpus"])
                self.assertLessEqual(observed["genomes"] * observed["workers"], observed["cpus"])
                self.assertLessEqual(
                    observed["genomes"] * observed["records"] * observed["shard"],
                    observed["cpus"],
                )
                self.assertLessEqual(observed["genomes"] * observed["legacy"], observed["cpus"])

    def test_effective_cpu_detection_ignores_library_caps_and_honors_cgroup(self) -> None:
        text = (REPO_ROOT / "run_annotation_and_detection.sh").read_text(
            encoding="utf-8"
        )
        helper_block = "count_cpuset_cpus() {" + text.split(
            "count_cpuset_cpus() {", 1
        )[1].split("\ndetect_effective_memory_mb() {", 1)[0]

        with tempfile.TemporaryDirectory() as tmp:
            cgroup_root = Path(tmp)
            (cgroup_root / "cpuset.cpus.effective").write_text(
                "0-7\n", encoding="utf-8"
            )
            (cgroup_root / "cpu.max").write_text(
                "400000 100000\n", encoding="utf-8"
            )
            command = (
                "set -euo pipefail\n"
                "have(){ command -v \"$1\" >/dev/null 2>&1; }\n"
                "nproc(){\n"
                "  if [[ \"${OMP_NUM_THREADS:-}\" == 1 || \"${OMP_THREAD_LIMIT:-}\" == 1 ]]; then\n"
                "    printf '1\\n'\n"
                "  else\n"
                "    printf '12\\n'\n"
                "  fi\n"
                "}\n"
                + helper_block
                + "\nexport OMP_NUM_THREADS=1 OMP_THREAD_LIMIT=1\n"
                + "detect_effective_cpus \"$1\"\n"
            )
            result = subprocess.run(
                ["bash", "-c", command, "bash", str(cgroup_root)],
                cwd=str(REPO_ROOT),
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

        # The fake nproc reports one while either OpenMP cap remains set.  The
        # detector must see 12, then apply cpuset=8 and quota=4 bounds.
        self.assertEqual(result.stdout.strip(), "4")

    def test_annotation_supports_bounded_antismash_record_sharding(self) -> None:
        text = (REPO_ROOT / "run_annotation_and_detection.sh").read_text(encoding="utf-8")
        record_ids = text.split("list_genbank_record_ids() {", 1)[1].split("\n}", 1)[0]
        shard_call = text.split("run_antismash_record_shard() {", 1)[1].split(
            "write_antismash_shard_index() {", 1
        )[0]
        sharded = text.split("run_antismash_sharded() {", 1)[1].split(
            "# Per-genome logging sync + manifest", 1
        )[0]
        process_body = text.split("process_genome() {", 1)[1].split("\n}\n\nidx=0", 1)[0]
        merge_json = text.split("merge_antismash_shard_jsons() {", 1)[1].split("\n}", 1)[0]
        stable_ids = text.split("antismash_record_ids_are_stable() {", 1)[1].split("\n}", 1)[0]
        shard_index = text.split("write_antismash_shard_index() {", 1)[1].split(
            "cleanup_antismash_assembled_outputs() {", 1
        )[0]
        cleanup = text.split("cleanup_antismash_assembled_outputs() {", 1)[1].split("\n}", 1)[0]
        summary = (REPO_ROOT / "summarize_clusterweave.sh").read_text(encoding="utf-8")
        clinker_stage = (REPO_ROOT / "bin" / "stage_clinker_panels.py").read_text(encoding="utf-8")

        self.assertIn('ANTISMASH_RECORD_PARALLELISM="${ANTISMASH_RECORD_PARALLELISM:-1}"', text)
        self.assertIn('ANTISMASH_SHARD_CPUS="${ANTISMASH_SHARD_CPUS:-}"', text)
        self.assertIn('ANTISMASH_LEGACY_CPUS="${ANTISMASH_LEGACY_CPUS:-}"', text)
        self.assertIn('ANTISMASH_RETAIN_SHARD_WORK="${ANTISMASH_RETAIN_SHARD_WORK:-0}"', text)
        self.assertIn('ANTISMASH_SHARD_COMPACTOR="${ANTISMASH_SHARD_COMPACTOR:-${SCRIPT_DIR}/bin/compact_antismash_shard.py}"', text)
        self.assertIn('ANTISMASH_SHARD_CPUS_DEFAULT=$((PER_GENOME_CPU_BUDGET / ANTISMASH_RECORD_PARALLELISM))', text)
        self.assertIn('ANTISMASH_SHARD_CPUS="$(minimum_int', text)
        self.assertIn('ANTISMASH_LEGACY_CPUS="$(minimum_int', text)
        self.assertIn('for record in SeqIO.parse(path, "genbank"):', record_ids)
        self.assertIn('min_record_bp = int(sys.argv[2])', record_ids)
        self.assertIn('if len(record.seq) < min_record_bp:', record_ids)
        self.assertNotIn("--limit-to-record", shard_call)
        self.assertIn('--minlength "${ANTISMASH_MIN_RECORD_BP}"', shard_call)
        self.assertIn('--output-dir "${shard_dir}"', shard_call)
        self.assertIn('--output-basename "${safe_record_id}"', shard_call)
        self.assertIn('--cpus "${ANTISMASH_SHARD_CPUS}"', shard_call)
        self.assertIn('"${ANTISMASH_SHARD_COMPACTOR}"', shard_call)
        self.assertIn('--shard-dir "${shard_dir}"', shard_call)
        self.assertIn('--record-id "${record_id}"', shard_call)
        self.assertIn('--json-name "${safe_record_id}.json"', shard_call)
        self.assertIn('--retain "${ANTISMASH_RETAIN_SHARD_WORK}"', shard_call)
        self.assertIn('antiSMASH record shard compaction failed', shard_call)
        self.assertIn("--allow-long-headers", text)
        self.assertNotIn("--start", shard_call)
        self.assertNotIn("--end", shard_call)
        self.assertIn('while [[ "${active_jobs}" -ge "${ANTISMASH_RECORD_PARALLELISM}" ]]', sharded)
        self.assertIn('while [[ "${active_jobs}" -gt 0 ]]', sharded)
        helper_runtime = text.split("antismash_input_python_exec() {", 1)[1].split("\n}", 1)[0]
        self.assertIn('if [[ "${ENGINE}" == "docker" ]]', helper_runtime)
        self.assertIn('"$(resolve_python_cmd)" "$@"', helper_runtime)
        self.assertIn('antismash_input_python_exec "${ANTISMASH_INPUT_PREPARER}" sanitize', text)
        self.assertIn('antismash_input_python_exec "${ANTISMASH_INPUT_PREPARER}" split-records', sharded)
        self.assertIn('"${ANTISMASH_INPUT_PREPARER}" split-records', sharded)
        self.assertIn('"${shard_inputs[${index}]}"', sharded)
        self.assertGreaterEqual(sharded.count("wait_for_antismash_shard_job"), 2)
        wait_helper = text.split("wait_for_antismash_shard_job() {", 1)[1].split("\n}", 1)[0]
        self.assertIn("wait -n", wait_helper)
        self.assertIn("record_id\\tshard_dir\\tstatus\\telapsed_seconds\\tregion_count", sharded)
        self.assertIn('"${ant_out}/shard_manifest.tsv"', sharded)
        self.assertIn('destination="${ant_out}/${destination_name}"', sharded)
        self.assertIn('cp -f "${region_file}" "${destination}"', sharded)
        self.assertIn('"${safe_record_ids[${index}]}".*) ;;', sharded)
        self.assertIn('canonical_json="${ant_out}/${genome_id}.antismash.json"', sharded)
        self.assertIn('shard_json_args+=("${record_ids[${index}]}" "${expected_json}")', sharded)
        self.assertIn('merge_antismash_shard_jsons "${canonical_json}" "${shard_json_args[@]}"', sharded)
        self.assertIn("merged_records.append(matching_records[0])", merge_json)
        self.assertIn('merged["records"] = merged_records', merge_json)
        self.assertIn("merged_timings.update(timings)", merge_json)
        self.assertIn('merged["timings"] = merged_timings', merge_json)
        self.assertIn("os.replace(temporary_path, output_path)", merge_json)
        self.assertIn('json_path=os.path.join(genome_dir,f"{genome}.antismash.json")', summary)
        self.assertIn('return antismash_root / genome / f"{antismash_region}.gbk"', clinker_stage)
        self.assertIn("tr -c 'A-Za-z0-9._-' '_'", text)
        self.assertIn('find "${shard_dirs[${index}]}" -type f -name \'*region*.gbk\'', sharded)
        self.assertIn('render_antismash_shard_web_bundle', sharded)
        self.assertIn('write_antismash_shard_index "${genome_id}" "${ant_out}"', sharded)
        self.assertIn('"${assembled_count}" -gt 0', sharded)
        self.assertIn('touch "${ant_out}/.done"', sharded)
        self.assertIn('safe_record_id="$(safe_antismash_record_id "${record_id}")"', stable_ids)
        self.assertIn('[[ "${safe_record_id}" != "${record_id}" ]]', stable_ids)
        self.assertIn('ANTISMASH_UNSTABLE_RECORD_ID="${record_id}"', stable_ids)
        self.assertIn('antismash_record_ids_are_stable "${antismash_record_ids_file}"', process_body)
        self.assertIn('"${antismash_record_ids_stable}" -eq 1', process_body)
        self.assertIn(
            'list_genbank_record_ids "${ant_input}" "${ANTISMASH_MIN_RECORD_BP}"',
            process_body,
        )
        self.assertIn('--minlength "${ANTISMASH_MIN_RECORD_BP}"', process_body)
        self.assertEqual(text.count('--minlength "${ANTISMASH_MIN_RECORD_BP}"'), 2)
        self.assertIn('ANTISMASH_RECORD_SHARD_FALLBACK genome=', process_body)
        self.assertIn('reason=record_id_not_output_basename_stable', process_body)
        self.assertIn("html_escape", shard_index)
        self.assertNotIn("href=", shard_index)
        self.assertIn('-maxdepth 1 -type f -name \'*region*.gbk\' -delete', cleanup)
        self.assertIn('"${canonical_json}.tmp"', cleanup)
        self.assertIn('"${ant_out}/index.html"', cleanup)
        self.assertIn('"${ant_out}/.done"', cleanup)
        self.assertGreaterEqual(
            sharded.count('cleanup_antismash_assembled_outputs "${ant_out}" "${canonical_json}"'),
            5,
        )
        self.assertIn("ANTISMASH_RECORD_PROGRESS genome=", text)
        self.assertIn('antismash_shard_root="${per_tmp}/antismash_shards"', process_body)
        self.assertIn('"${ANTISMASH_RECORD_PARALLELISM}" -gt 1', process_body)
        self.assertIn('"${antismash_record_count}" -gt 1', process_body)
        self.assertIn('antiSMASH legacy single-run mode', process_body)
        self.assertIn('--cpus "${ANTISMASH_LEGACY_CPUS}"', process_body)
        self.assertIn('cp -f "${ant_filtered_input}" "${fbx_input}"', process_body)

    def test_antismash_record_id_stability_gate_executes_safe_transform_exactly(self) -> None:
        text = (REPO_ROOT / "run_annotation_and_detection.sh").read_text(encoding="utf-8")
        helper_block = text.split("safe_antismash_record_id() {", 1)[1].split(
            "sanitize_antismash_duplicate_cds_locations() {", 1
        )[0]
        helper_block = "safe_antismash_record_id() {" + helper_block

        cases = [
            ("JASJFT010000001.1", "JASJFT010000001.1", True),
            ("record~tilde", "record_tilde", False),
            (".leading", "record_.leading", False),
            ("-leading", "record_-leading", False),
            ("x" * 121, "x" * 120, False),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            record_ids_file = Path(tmp) / "record_ids.txt"
            for record_id, expected_safe, expected_stable in cases:
                with self.subTest(record_id=record_id):
                    record_ids_file.write_text(record_id + "\n", encoding="utf-8")
                    result = subprocess.run(
                        [
                            "bash",
                            "-c",
                            helper_block
                            + "\nprintf 'safe=%s\\n' \"$(safe_antismash_record_id \"$2\")\"\n"
                            + "if antismash_record_ids_are_stable \"$1\"; then exit 0; else exit 3; fi\n",
                            "antismash-record-id-test",
                            str(record_ids_file),
                            record_id,
                        ],
                        cwd=str(REPO_ROOT),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                    )
                    self.assertEqual(result.stdout, f"safe={expected_safe}\n")
                    self.assertEqual(result.returncode, 0 if expected_stable else 3, result.stderr)

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
        self.assertIn('[[ -f "${outdir}/.done" ]] || return 1', block)
        self.assertIn("[[ -s \"${outdir}/index.html\" ]] || return 1", block)
        self.assertIn("-name \"regions.js\"", block)
        self.assertIn("-name \"*.antismash.json\"", block)
        self.assertNotIn("*region*.gbk", block)
        self.assertNotIn("##antiSMASH-Data-START##", block)

    def test_annotation_completion_markers_require_valid_outputs(self) -> None:
        text = (REPO_ROOT / "run_annotation_and_detection.sh").read_text(encoding="utf-8")
        funbgcex = text.split("funbgcex_outputs_valid() {", 1)[1].split(
            "# GBK diagnostics/filtering", 1
        )[0]
        self.assertIn('[[ -f "${outdir}/.done" ]] || return 1', funbgcex)
        self.assertIn('-name "allBGCs.csv"', funbgcex)
        self.assertNotIn('funbgcex_in.log', funbgcex)
        self.assertIn('&& funbgcex_outputs_valid "${fbx_out}"', text)
        self.assertIn('&& touch "${fbx_out}/.done"', text)
        gbk_check = text.split("gbk_has_cds_and_translation() {", 1)[1].split(
            "backfill_gbk_translations_from_existing_cds() {", 1
        )[0]
        self.assertIn("GENBANK_TRANSLATION_CHECKER", gbk_check)
        self.assertIn('"${VENV_PY}" "${GENBANK_TRANSLATION_CHECKER}"', gbk_check)
        self.assertTrue((REPO_ROOT / "bin" / "check_genbank_translations.py").exists())
        self.assertTrue((REPO_ROOT / "web" / "genbank_readiness.py").exists())
        checker = (REPO_ROOT / "bin" / "check_genbank_translations.py").read_text(encoding="utf-8")
        self.assertIn('Path("/app")', checker)

    def test_annotation_completion_helpers_reject_partial_artifacts(self) -> None:
        text = (REPO_ROOT / "run_annotation_and_detection.sh").read_text(encoding="utf-8")
        completion_helpers = "antismash_done() {" + text.split(
            "antismash_done() {", 1
        )[1].split("# GBK diagnostics/filtering", 1)[0]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            good_gbk = root / "good.gbk"
            good_gbk.write_text(
                "LOCUS       complete 9 bp DNA\n"
                "FEATURES             Location/Qualifiers\n"
                "     CDS             1..9\n"
                "                     /translation=\"MKT\"\n"
                "ORIGIN\n        1 atgaaaact\n//\n",
                encoding="utf-8",
            )
            truncated_gbk = root / "truncated.gbk"
            truncated_gbk.write_text(good_gbk.read_text(encoding="utf-8").removesuffix("//\n"), encoding="utf-8")
            partial_gbk = root / "partial.gbk"
            partial_gbk.write_text(
                good_gbk.read_text(encoding="utf-8").replace(
                    "ORIGIN\n",
                    "     CDS             1..3\n"
                    '                     /product="untranslated"\n'
                    "ORIGIN\n",
                ),
                encoding="utf-8",
            )
            checker = REPO_ROOT / "bin" / "check_genbank_translations.py"
            for path, expected in [(good_gbk, 0), (truncated_gbk, 1), (partial_gbk, 1)]:
                result = subprocess.run(
                    [sys.executable, str(checker), str(path)],
                    cwd=str(REPO_ROOT),
                    check=False,
                )
                self.assertEqual(result.returncode, expected, path.name)

            antismash = root / "antismash"
            antismash.mkdir()
            (antismash / "index.html").write_text("index", encoding="utf-8")
            (antismash / "demo.antismash.json").write_text("{}", encoding="utf-8")
            funbgcex = root / "funbgcex"
            funbgcex.mkdir()
            (funbgcex / "allBGCs.csv").write_text("BGC\n", encoding="utf-8")
            for function_name, outdir in [("antismash_done", antismash), ("funbgcex_done", funbgcex)]:
                command = completion_helpers + f'\n{function_name} "$1"'
                without_marker = subprocess.run(
                    ["bash", "-c", command, "completion-test", str(outdir)],
                    cwd=str(REPO_ROOT),
                    check=False,
                )
                self.assertNotEqual(without_marker.returncode, 0, function_name)
                (outdir / ".done").touch()
                with_marker = subprocess.run(
                    ["bash", "-c", command, "completion-test", str(outdir)],
                    cwd=str(REPO_ROOT),
                    check=False,
                )
                self.assertEqual(with_marker.returncode, 0, function_name)

    def test_bigscape_stages_only_assembled_per_genome_region_roots(self) -> None:
        text = (REPO_ROOT / "run_bigscape.sh").read_text(encoding="utf-8")
        finder = text.split("find_antismash_genome_regions() {", 1)[1].split("\n}", 1)[0]
        stage = text.split("# Stage antiSMASH region GBKs to a flat directory", 1)[1].split(
            "# Run BiG-SCAPE", 1
        )[0]

        self.assertIn('-mindepth 2 -maxdepth 2 -type f -name "*region*.gbk"', finder)
        self.assertIn('relative="${f#"${ANTISMASH_ROOT%/}/"}"', stage)
        self.assertIn('genome="${relative%%/*}"', stage)
        self.assertIn('label="${genome}"', stage)
        self.assertIn('taxon_source="$(manifest_taxon_source "${genome}")"', stage)
        self.assertIn('"${taxon_source,,}" =~ ^(ncbi|ncbi_taxonomy)$', stage)
        self.assertIn('label="${genome#bacteria_}"', stage)
        self.assertIn('label="${label//_/ }"', stage)
        self.assertIn('out="${STAGE_DIR}/${genome}__${base}"', stage)
        self.assertIn('awk -v LABEL="${label}"', stage)
        self.assertIn("done < <(find_antismash_genome_regions -print0)", stage)
        self.assertIn('die "Region staging name collision', stage)
        self.assertNotIn('basename "$(dirname "$f")"', stage)
        self.assertNotIn('find "${ANTISMASH_ROOT}" -type f', stage)

    def test_bacterial_ids_are_taxon_neutral_and_legacy_joins_are_exact_first(self) -> None:
        app_text = (REPO_ROOT / "web" / "app.py").read_text(encoding="utf-8")
        rename_text = (REPO_ROOT / "scripts" / "ncbi" / "rename_ncbi_genomes.sh").read_text(encoding="utf-8")
        crosswalk_text = (REPO_ROOT / "bin" / "build_bgc_gcf_crosswalk.py").read_text(encoding="utf-8")
        summary_text = (REPO_ROOT / "summarize_clusterweave.sh").read_text(encoding="utf-8")

        self.assertNotIn('safe_ncbi_genome_id(f"bacteria_{identifier}")', app_text)
        self.assertNotIn('fid = sanitize(f"bacteria_{fid}")', rename_text)
        self.assertIn("pairs = [(genome, antismash_region)]", crosswalk_text)
        self.assertIn("pre-v1.0 bacterial prefix convention", crosswalk_text)
        self.assertNotIn("def canonical_join_id", crosswalk_text)
        self.assertNotIn("re.sub(r'^bacteria_'", summary_text)

    def test_nplinker_seeding_discovers_assembled_root_level_regions(self) -> None:
        text = (REPO_ROOT / "run_nplinker.sh").read_text(encoding="utf-8")
        root_level_find = (
            'find "${LOCAL_ANTISMASH_ROOT}" -maxdepth 1 -type f '
            '-name "*region*.gbk" -print0'
        )

        self.assertGreaterEqual(text.count(root_level_find), 2)
        self.assertIn('"${RUN_DIR}/antismash/${TARGET_STRAIN}/"', text)

    def test_release_metadata_exists(self) -> None:
        for rel in [
            "README.md",
            "docs/BEGINNER_SETUP.md",
            "CHANGELOG.md",
            "SECURITY.md",
            "LICENSE",
            "CITATION.cff",
            "THIRD_PARTY.md",
            "docs/DATA_SOURCES.md",
            "config/local.env.template",
            "profiles/release_v1.0.0.env",
            "package.json",
            "package-lock.json",
            "visuals/ClusterWeave_workflow.svg",
            "visuals/logo_black.svg",
            "web/OPERATOR_AGREEMENT.md",
            "docs/INSTALL.md",
            "docs/RELEASE_CHECKLIST.md",
            "docs/REPRODUCIBILITY.md",
            "docs/WEB_RUNTIME.md",
            "examples/README.md",
            "pyproject.toml",
        ]:
            self.assertTrue((REPO_ROOT / rel).exists(), rel)

    def test_public_release_copy_excludes_private_gate_status(self) -> None:
        release_docs = [
            "README.md",
            "docs/BEGINNER_SETUP.md",
            "CHANGELOG.md",
            "SECURITY.md",
            "docs/INSTALL.md",
            "docs/RELEASE_CHECKLIST.md",
            "docs/WEB_RUNTIME.md",
            "examples/README.md",
            "examples/fungi_only/README.md",
            "examples/mixed/README.md",
            "web/OPERATOR_AGREEMENT.md",
        ]
        texts = {
            rel: (REPO_ROOT / rel).read_text(encoding="utf-8").casefold()
            for rel in release_docs
        }
        combined = "\n".join(texts.values())
        normalized_readme = " ".join(texts["README.md"].split())
        self.assertIn(
            "clusterweave organizes genome-mining analyses into integrated evidence profiles",
            normalized_readme,
        )
        for private_status in [
            "(pending)",
            "release candidate",
            "source candidate",
            "maintainer approval",
            "cybersecurity review",
            "private release map",
            "pending tag",
            "tag remains pending",
            "tag is still pending",
        ]:
            with self.subTest(private_status=private_status):
                self.assertNotIn(private_status, combined)

        for rel in [
            "README.md",
            "docs/BEGINNER_SETUP.md",
            "SECURITY.md",
            "docs/INSTALL.md",
            "docs/WEB_RUNTIME.md",
            "web/OPERATOR_AGREEMENT.md",
        ]:
            with self.subTest(hosted_status=rel):
                self.assertIn("coming soon", texts[rel])

    def test_generated_and_private_categories_are_ignored(self) -> None:
        gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        dockerignore = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8")
        for category in [
            "node_modules/",
            "test-results/",
            "playwright-report/",
            "credentials/",
            "*.orig",
        ]:
            with self.subTest(category=category):
                self.assertIn(category, gitignore)
                self.assertIn(category, dockerignore)

        for rel in [
            ".env.local",
            "config/local.env",
            "node_modules/example/index.js",
            "test-results/failure.png",
            "playwright-report/index.html",
            "data/jobs/synthetic-job/job.json",
            "scratch.orig",
        ]:
            with self.subTest(ignored=rel):
                result = subprocess.run(
                    ["git", "check-ignore", "--no-index", "--quiet", rel],
                    cwd=REPO_ROOT,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, rel)

        for rel in [
            "config/local.env.template",
            "config/defaults.env",
            "profiles/release_v1.0.0.env",
            "software/phylogeny/Dockerfile",
        ]:
            with self.subTest(public=rel):
                result = subprocess.run(
                    ["git", "check-ignore", "--no-index", "--quiet", rel],
                    cwd=REPO_ROOT,
                    check=False,
                )
                self.assertEqual(result.returncode, 1, rel)

    def test_generic_example_paths_exist(self) -> None:
        self.assertTrue((REPO_ROOT / "profiles" / "example_project.env").exists())
        for rel in [
            "examples/README.md",
            "examples/fungi_only/README.md",
            "examples/fungi_only/accessions.txt",
            "examples/fungi_only/accessions_fungusID_taxonomyID.txt",
            "examples/fungi_only/summary/README.md",
            "examples/fungi_only/summary/family_atlas_shortlist.md",
            "examples/fungi_only/figures/fungi_big_scape_multipanel.svg",
            "examples/fungi_only/figures/bgc_overlap.svg",
            "examples/mixed/README.md",
            "examples/mixed/accessions.txt",
            "examples/mixed/accessions_fungusID_taxonomyID.txt",
            "examples/mixed/accessions_bacteriaID_taxonomyID.txt",
            "examples/mixed/figures/fungi_big_scape_multipanel.svg",
            "examples/mixed/figures/bacteria_big_scape_multipanel.svg",
            "examples/mixed/figures/bgc_overlap.svg",
            "examples/mixed/figures/clusterweave_taxon_tree.svg",
            "examples/mixed/summary/README.md",
            "examples/mixed/summary/all_tools_bgc_comparison.csv",
            "examples/mixed/summary/all_tools_shared_unshared_summary.csv",
            "examples/mixed/summary/family_atlas_shortlist.md",
            "examples/mixed/summary/family_atlas_shortlist.tsv",
        ]:
            self.assertTrue((REPO_ROOT / rel).exists(), rel)

        self.assertFalse((REPO_ROOT / "examples/mixed/accession_validation.tsv").exists())
        self.assertFalse((REPO_ROOT / "examples/mixed/figures/README.md").exists())

        mixed_accessions = (
            REPO_ROOT / "examples/mixed/accessions.txt"
        ).read_text(encoding="utf-8").splitlines()
        fungal_accessions = {
            row.split("\t", 1)[0]
            for row in (
                REPO_ROOT
                / "examples/mixed/accessions_fungusID_taxonomyID.txt"
            ).read_text(encoding="utf-8").splitlines()
            if row
        }
        bacterial_accessions = {
            row.split("\t", 1)[0]
            for row in (
                REPO_ROOT
                / "examples/mixed/accessions_bacteriaID_taxonomyID.txt"
            ).read_text(encoding="utf-8").splitlines()
            if row
        }
        self.assertEqual(40, len(mixed_accessions))
        self.assertEqual(40, len(set(mixed_accessions)))
        self.assertEqual(20, len(bacterial_accessions))
        self.assertEqual(20, len(fungal_accessions))
        self.assertEqual(set(mixed_accessions[:20]), bacterial_accessions)
        self.assertEqual(set(mixed_accessions[20:]), fungal_accessions)

        bacterial_mapping_rows = [
            row.split("\t")
            for row in (
                REPO_ROOT
                / "examples/mixed/accessions_bacteriaID_taxonomyID.txt"
            ).read_text(encoding="utf-8").splitlines()
            if row
        ]
        self.assertTrue(all(len(row) >= 3 for row in bacterial_mapping_rows))
        self.assertTrue(
            all(not row[1].casefold().startswith("bacteria_") for row in bacterial_mapping_rows)
        )
        for relative in (
            "figures/clusterweave_taxon_tree.svg",
            "summary/all_tools_shared_unshared_summary.csv",
            "summary/family_atlas_shortlist.md",
            "summary/family_atlas_shortlist.tsv",
        ):
            text = (REPO_ROOT / "examples/mixed" / relative).read_text(encoding="utf-8")
            self.assertNotRegex(text, r"bacteria_[A-Z][A-Za-z0-9._-]*")

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
        self.assertIn('antismash_status == "ran_ok"', text)
        self.assertIn('antismash_status == "ran_ok_sanitized"', text)
        self.assertIn('antismash_status == "skipped_done"', text)
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
        self.assertIn('ANALYSIS_SCOPE="${ANALYSIS_SCOPE:-fungi}"', text)
        self.assertIn('DEFAULT_METADATA_NAME="ecobac_metadata_normalized.tsv"', text)
        self.assertIn('DEFAULT_METADATA_NAME="ecofun_metadata_normalized.tsv"', text)
        self.assertIn('RUN_ECOLOGY_ANALYSIS="${RUN_ECOLOGY_ANALYSIS:-0}"', text)
        self.assertIn('DEFAULT_METADATA_ROOT="${RESULTS_ROOT}/summary_tables"', text)
        self.assertIn('DEFAULT_METADATA_ROOT="${WORK_ROOT}/routing"', text)
        self.assertIn('METADATA_TEMPLATE_TSV="${METADATA_TEMPLATE_TSV:-${DEFAULT_METADATA_ROOT}/${DEFAULT_METADATA_TEMPLATE_NAME}}"', text)
        self.assertIn('reviewer_args+=(--skip-ecology-tables)', text)
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
        self.assertIn('local -a args=(', text)
        self.assertIn('--cpus "${BIGSCAPE_DOCKER_CPUS}"', text)
        self.assertIn('-e OMP_NUM_THREADS=1', text)

    def test_web_lab_runtime_is_docker_gated(self) -> None:
        compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        public_compose = (REPO_ROOT / "clusterweave.yml").read_text(encoding="utf-8")
        self.assertIn("CLUSTERWEAVE_RUNTIME_MODE: lab-docker", compose)
        self.assertIn("CLUSTERWEAVE_ENABLE_DOCKER_SOCKET: \"1\"", compose)
        self.assertIn("ENGINE: docker", compose)
        self.assertIn('WORKER_CONCURRENCY: "${WORKER_CONCURRENCY:-1}"', compose)
        self.assertIn('WORKER_CPU_BUDGET: "${WORKER_CPU_BUDGET:-auto}"', compose)
        self.assertIn('cpus: "${CLUSTERWEAVE_WORKER_CPU_LIMIT:-4}"', compose)
        self.assertIn('mem_limit: "${CLUSTERWEAVE_WORKER_MEM_LIMIT:-16g}"', compose)
        self.assertEqual(compose.count("mem_limit: 2g"), 1)
        self.assertIn("/var/run/docker.sock:/var/run/docker.sock", compose)
        self.assertNotIn("/usr/bin/docker:/usr/bin/docker", compose)
        self.assertIn('platform: "${CLUSTERWEAVE_DOCKER_PLATFORM:-linux/amd64}"', compose)
        self.assertIn('${CLUSTERWEAVE_BIND_ADDRESS:-127.0.0.1}:${HOST_PORT:-8080}:8080', compose)
        worker_image = (REPO_ROOT / "Dockerfile.worker").read_text(encoding="utf-8")
        self.assertIn("FROM docker:29.6.1-cli AS docker-cli", worker_image)
        self.assertIn("COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker", worker_image)
        self.assertIn("CLUSTERWEAVE_RUNTIME_MODE: public-queue", public_compose)
        self.assertIn("CLUSTERWEAVE_ENABLE_DOCKER_SOCKET: \"0\"", public_compose)
        self.assertIn('CLUSTERWEAVE_PUBLIC_MODE: "${CLUSTERWEAVE_PUBLIC_MODE:-1}"', public_compose)
        self.assertIn('CLUSTERWEAVE_JOB_TOKEN_SECRET: "${CLUSTERWEAVE_JOB_TOKEN_SECRET:-}"', public_compose)
        self.assertIn('WORKER_CONCURRENCY: "${WORKER_CONCURRENCY:-1}"', public_compose)
        self.assertNotIn("/var/run/docker.sock:/var/run/docker.sock", public_compose)

    def test_public_release_files_do_not_contain_private_handoff_markers(self) -> None:
        release_files = [
            "README.md",
            "docs/DATA_SOURCES.md",
            "THIRD_PARTY.md",
            "docs/RELEASE_CHECKLIST.md",
            "docs/WEB_RUNTIME.md",
            "visuals/ClusterWeave_workflow.svg",
            "visuals/logo_black.svg",
            "examples/README.md",
            "examples/fungi_only/accessions.txt",
            "examples/fungi_only/accessions_fungusID_taxonomyID.txt",
            "examples/fungi_only/summary/README.md",
            "examples/fungi_only/summary/family_atlas_shortlist.md",
            "examples/mixed/accessions.txt",
            "examples/mixed/accessions_fungusID_taxonomyID.txt",
            "examples/mixed/accessions_bacteriaID_taxonomyID.txt",
            "examples/mixed/README.md",
            "examples/mixed/summary/README.md",
            "examples/mixed/summary/family_atlas_shortlist.md",
            "docker-compose.yml",
            "clusterweave.yml",
            "web/OPERATOR_AGREEMENT.md",
        ]
        forbidden = [
            "OneDrive",
            ".".join(("192", "168", "50", "25")),
            "dev-admin",
            "dev-change-me",
            "/".join(("", "home", "cloud")),
            "/mnt/c/Users",
        ]
        for rel in release_files:
            text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")
            for marker in forbidden:
                with self.subTest(file=rel, marker=marker):
                    self.assertNotIn(marker, text)

    def test_public_examples_exclude_runtime_artifacts(self) -> None:
        examples_root = REPO_ROOT / "examples"
        forbidden_suffixes = {".db", ".gbk", ".log", ".sqlite", ".zip"}
        private_job_path = re.compile(
            r"(?:^|[/`])data/jobs/[0-9a-f]{8}(?:/|$)"
        )
        for path in examples_root.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            with self.subTest(path=rel):
                self.assertNotIn(path.suffix.lower(), forbidden_suffixes)
                text = path.read_text(encoding="utf-8", errors="replace")
                self.assertIsNone(private_job_path.search(text))
                self.assertNotIn("/".join(("", "home", "cloud")), text)
                self.assertNotIn("/data/jobs/", text)

    def test_frontend_static_assets_are_extracted_without_new_dependencies(self) -> None:
        static_dir = REPO_ROOT / "web" / "static"
        index_text = (static_dir / "index.html").read_text(encoding="utf-8")
        css_text = (static_dir / "assets" / "clusterweave.css").read_text(encoding="utf-8")
        js_text = (static_dir / "assets" / "clusterweave.js").read_text(encoding="utf-8")

        self.assertLess(len(index_text.splitlines()), 1000)
        self.assertIn('href="/favicon.ico', index_text)
        self.assertTrue((static_dir / "favicon.ico").exists())
        self.assertIn('href="assets/clusterweave.css?v=20260723-timer-utc1"', index_text)
        self.assertIn('src="assets/clusterweave.js?v=20260723-timer-utc1"', index_text)
        self.assertNotIn("<style>", index_text)
        self.assertNotIn("<script>\n", index_text)
        self.assertIn("function apiUrl(path)", js_text)
        self.assertIn("function handleResultLinkClick(event, jobId, relPath, download = false)", js_text)
        self.assertIn("const WORKFLOW_DNA_MODULE_PATH", js_text)
        self.assertIn("function bootBgcWorkflowDna()", js_text)
        self.assertNotIn('id="input-station-limit"', index_text)
        self.assertIn('id="upload-limit-note"', index_text)
        self.assertIn('50 genome files or 50 NCBI accessions', index_text)
        self.assertNotIn('input-method-tag standard', index_text)
        self.assertNotIn('input-method-tag secondary', index_text)
        self.assertNotIn('Local file input', index_text)
        self.assertIn('.setup-panel { grid-area: setup; overflow: hidden; align-self: start; }', css_text)
        self.assertIn('.brutal-accession-card {', css_text)
        self.assertIn('align-items: stretch;\n    margin-bottom: .7rem;', css_text)
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

    def test_frontend_taxon_scope_and_mixed_upload_contract(self) -> None:
        static_dir = REPO_ROOT / "web" / "static"
        index_text = (static_dir / "index.html").read_text(encoding="utf-8")
        css_text = (static_dir / "assets" / "clusterweave.css").read_text(encoding="utf-8")
        js_text = (static_dir / "assets" / "clusterweave.js").read_text(encoding="utf-8")

        selector = index_text.split('id="analysis-scope-selector"', 1)[1].split("</fieldset>", 1)[0]
        self.assertIn("<legend>Analysis scope</legend>", selector)
        self.assertIn('name="analysis-scope" value="fungi" checked', selector)
        self.assertIn('name="analysis-scope" value="both"', selector)
        self.assertIn('name="analysis-scope" value="bacteria"', selector)
        self.assertLess(selector.index('value="fungi"'), selector.index('value="both"'))
        self.assertLess(selector.index('value="both"'), selector.index('value="bacteria"'))
        self.assertIn('id="taxon-assignment-panel"', index_text)
        self.assertIn('class="taxon-assignment-columns" role="row"', index_text)
        self.assertIn("markAllTaxonAssignments('fungi')", index_text)
        self.assertIn("markAllTaxonAssignments('bacteria')", index_text)
        self.assertNotIn("Both mode needs one Fungi or Bacteria declaration per ambiguous logical genome.", index_text)
        self.assertNotIn("a same-stem FASTA inherits that route", index_text)
        self.assertIn('id="taxon-assignment-list" role="rowgroup"', index_text)
        self.assertIn('id="run-setup-analysis-scope"', index_text)

        self.assertIn("let stagedAnalysisScope = 'fungi';", js_text)
        self.assertIn("let activeSavedAnalysisContext = null;", js_text)
        self.assertIn("function normalizeAnalysisScope(value, fallback = 'fungi')", js_text)
        self.assertIn("function analysisContextFromJob(job)", js_text)
        self.assertIn("function analysisCapabilities(context = activeAnalysisContext())", js_text)
        self.assertIn("function logicalGenomeInputs(files = selectedFiles)", js_text)
        self.assertIn("return publicGenomeStem(value).toLowerCase();", js_text)
        self.assertIn("let genbankTaxonomyAuthorityCache = new Map();", js_text)
        self.assertIn("function parseClientGenbankTaxonomy(text)", js_text)
        self.assertIn("function logicalGenomeAuthority(item)", js_text)
        self.assertIn("function clientTaxonAssignmentDecision(authority", js_text)
        self.assertIn("function renderTaxonAssignmentPanel()", js_text)
        self.assertIn("function markAllTaxonAssignments(taxonGroup)", js_text)
        self.assertIn("function parseTaxonAssignmentSidecarText(text)", js_text)
        self.assertIn("const TAXON_ASSIGNMENTS_FILENAME = 'taxon_assignments.tsv';", js_text)
        self.assertIn("isTaxonAssignmentsSidecarName(f.name)", js_text)
        self.assertIn("Contradictory duplicate assignment", js_text)
        self.assertIn("Unknown taxon assignment key", js_text)
        self.assertIn("Both mode requires a Fungi or Bacteria declaration", js_text)
        self.assertIn("Feature-free bacterial GenBank accepted", js_text)
        self.assertIn("supplied features will be removed", js_text)
        self.assertIn("Authoritative bacterial GenBank taxonomy accepted", js_text)
        self.assertIn("const assignable = decisions.filter(decision => decision.requiresAssignment);", js_text)
        self.assertIn("if (decision.requiresAssignment && decision.assigned)", js_text)
        self.assertIn("fd.append('analysis_scope', normalizeAnalysisScope(stagedAnalysisScope))", js_text)
        self.assertIn("if (Object.keys(taxonAssignments).length)", js_text)
        self.assertIn("fd.append('taxon_assignments', JSON.stringify(taxonAssignments))", js_text)
        self.assertIn("setActiveSavedAnalysisContext(job);", js_text)
        self.assertIn("resultCategoryApplicable('funbgcex')", js_text)
        self.assertIn("figureApplicableToAnalysis(path, capabilities)", js_text)

        self.assertIn(".analysis-scope-options input:checked + span", css_text)
        self.assertIn(".analysis-scope-options input:focus-visible + span", css_text)
        self.assertIn(".taxon-assignment-panel", css_text)
        self.assertIn(".taxon-assignment-row.is-unresolved", css_text)
        self.assertIn(".taxon-assignment-cell input", css_text)
        self.assertIn("fungal, bacterial, or mixed biosynthetic gene cluster discovery", index_text)

    def test_frontend_phylogeny_figure_discovery_and_accessibility_contract(self) -> None:
        static_dir = REPO_ROOT / "web" / "static"
        css_text = (static_dir / "assets" / "clusterweave.css").read_text(encoding="utf-8")
        js_text = (static_dir / "assets" / "clusterweave.js").read_text(encoding="utf-8")

        approved = js_text.split("const APPROVED_PHYLOGENY_ARTIFACT_NAMES", 1)[1].split("]);", 1)[0]
        for filename in [
            "clusterweave_taxon_tree.svg",
            "clusterweave_taxon_tree.png",
            "clusterweave_taxon_tree.nwk",
            "clusterweave_taxon_tree_leaf_profiles.tsv",
            "clusterweave_gcf_network_edges.tsv",
            "clusterweave_taxon_tree.graphml",
            "clusterweave_tree_manifest.json",
            "clusterweave_tree_methods.json",
            "clusterweave_tree_bundle.zip",
        ]:
            with self.subTest(approved_phylogeny_artifact=filename):
                self.assertIn(f"'{filename}'", approved)

        discovery = js_text.split("function approvedPhylogenyArtifact(path)", 1)[1].split(
            "function isApprovedPhylogenyArtifact", 1
        )[0]
        figure_predicate = js_text.split("function isFigureAsset(path)", 1)[1].split(
            "function isSvgFigureAsset", 1
        )[0]
        self.assertIn(
            "normalized.match(/^data\\/results\\/[^/]+\\/figures\\/phylogeny\\/([^/]+)$/i)",
            discovery,
        )
        self.assertIn("APPROVED_PHYLOGENY_ARTIFACT_NAMES.has(name)", discovery)
        self.assertIn("/^data\\/results\\/[^/]+\\/figures\\/[^/]+\\.(svg|png|jpe?g|webp)$/i", figure_predicate)
        self.assertIn("|| isTaxonTreeVisualAsset(normalized)", figure_predicate)

        tree_bundle = js_text.split("function treeDataBundleForFigure(path, files)", 1)[1].split(
            "function isFigureAsset", 1
        )[0]
        self.assertIn("if (!isTaxonTreeSvgAsset(path)) return '';", tree_bundle)
        self.assertIn("`${directory}/clusterweave_tree_bundle.zip`.toLowerCase()", tree_bundle)
        self.assertIn("candidate.toLowerCase() === expected && isTaxonTreeBundleAsset(candidate)", tree_bundle)
        self.assertIn("resultDownloadLink(jobId, treeBundle, 'Tree data')", js_text)
        self.assertIn("/^data\\/results\\/[^/]+\\/figures\\/phylogeny$/i.test(normalized)", js_text)

        applicability = js_text.split("function figureApplicableToAnalysis", 1)[1].split("return true;", 1)[0]
        self.assertIn("isLegacyFungalFigure(path)", applicability)
        self.assertIn("capabilities.fungalFigures", applicability)
        self.assertIn("isBacterialMultipanelFigure(path)", applicability)
        self.assertIn("capabilities.bacterialFigures", applicability)
        self.assertIn("isTaxonTreeVisualAsset(path)", applicability)
        self.assertIn("capabilities.taxonomyTree", applicability)
        self.assertIn(
            "if (key === 'figures') return isFigureAsset(path) && figureApplicableToAnalysis(path);",
            js_text,
        )

        figure_sort = js_text.split("function figureSortKey(path)", 1)[1].split(
            "function figureCaption", 1
        )[0]
        ordered_names = [
            "fungi_big_scape_multipanel.svg",
            "fungi_big_scape_multipanel.png",
            "bacteria_big_scape_multipanel.svg",
            "bacteria_big_scape_multipanel.png",
            "bgc_overlap.svg",
            "bgc_overlap.png",
            "clusterweave_taxon_tree.svg",
            "clusterweave_taxon_tree.png",
            "big_scape_multipanel.svg",
            "big_scape_multipanel.png",
            "bacterial_multipanel.svg",
            "bacterial_multipanel.png",
        ]
        positions = [figure_sort.index(f"'{name}'") for name in ordered_names]
        self.assertEqual(positions, sorted(positions))
        self.assertIn(
            "Bacterial BiG-SCAPE multipanel combining stacked antiSMASH BGC/GCF counts, cluster context, compound labels, and confidence evidence.",
            js_text,
        )
        self.assertIn(
            "Ranked NCBI taxonomy context with BGC-count-scaled composition markers and class-colored GCF-sharing arcs; branch lengths are not inferred.",
            js_text,
        )

        svg_accessibility = js_text.split("function preserveInlineSvgAccessibility", 1)[1].split(
            "async function hydrateSvgFigures", 1
        )[0]
        self.assertIn("child.localName?.toLowerCase() === 'title'", svg_accessibility)
        self.assertIn("child.localName?.toLowerCase() === 'desc'", svg_accessibility)
        self.assertIn("svg.setAttribute('aria-labelledby', title.id)", svg_accessibility)
        self.assertIn("svg.setAttribute('aria-describedby', desc.id)", svg_accessibility)
        self.assertIn("preserveInlineSvgAccessibility(", js_text)
        self.assertIn('role="group"', js_text)
        self.assertIn('tabindex="0"', js_text)
        self.assertIn('aria-describedby="${escapeHtml(instructionsId)}"', js_text)
        self.assertIn('aria-keyshortcuts="+ - 0 Escape"', js_text)

        self.assertIn(".figure-preview-wrap.is-taxon-tree", css_text)
        self.assertIn("touch-action: pan-x pan-y;", css_text)
        self.assertIn("touch-action: none;", css_text)
        self.assertIn("min-height: clamp(28rem, 70vh, 58rem);", css_text)
        self.assertIn("@media (max-width: 760px)", css_text)
        self.assertIn("@media (pointer: coarse)", css_text)
        self.assertGreaterEqual(css_text.count("min-width: 44px; min-height: 44px;"), 2)

    def test_public_fasta_validation_streams_large_lines(self) -> None:
        app_text = (REPO_ROOT / "web" / "app.py").read_text(encoding="utf-8")
        self.assertIn("classify_public_fasta_stream", app_text)
        self.assertIn("handle.read(UPLOAD_COPY_CHUNK_BYTES)", app_text)
        self.assertIn("sequence_char_count += 1", app_text)
        self.assertNotIn("part.file.read()", app_text)
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

    def test_web_result_focus_and_archive_download_survives_run_changes(self) -> None:
        ui_text = frontend_text()
        self.assertIn("let resultArchiveRequestSeq = 0;", ui_text)
        self.assertIn("let activeArchiveDownload = null;", ui_text)
        self.assertIn("let archiveDownloadStatus = null;", ui_text)
        self.assertIn("async function readArchiveResponseBlob(response, requestId)", ui_text)
        self.assertIn("const requestJobId = activeJobId;", ui_text)
        self.assertIn("const requestId = ++resultArchiveRequestSeq;", ui_text)
        self.assertIn("received: 0", ui_text)
        self.assertIn("total: 0", ui_text)
        self.assertIn("response.body.getReader", ui_text)
        self.assertIn("setArchiveDownloadStatus", ui_text)
        self.assertNotIn("function cancelActiveArchiveDownload()", ui_text)
        self.assertNotIn("cancelActiveArchiveDownload();", ui_text)
        self.assertNotIn("activeJobId !== requestJobId", ui_text)
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
        self.assertIn("function syntenyGcfQualifier(value)", ui_text)
        self.assertIn("parts[i].split('__', 2)", ui_text)
        self.assertIn("GCF ${match[1].toUpperCase()} c${match[2]}.${match[3]}", ui_text)
        self.assertIn("const label = qualifier ? `${compound} · ${qualifier}` : compound;", ui_text)
        self.assertNotIn("titleCaseArtifactLabel(parts[i].split('__', 1)[0]", ui_text)

    def test_web_dna_spine_uses_continuous_ribbons(self) -> None:
        ui_text = frontend_text()
        dna_text = (REPO_ROOT / "web" / "static" / "assets" / "workflow-dna-progress.js").read_text(encoding="utf-8")
        self.assertIn('id="bgc-dna-canvas"', ui_text)
        self.assertIn('id="bgc-dna-progress-region"', ui_text)
        self.assertIn("import * as THREE from '../vendor/three-0.184.0/three.module.min.js';", dna_text)
        self.assertIn("appliedAs: 'color-fade-only'", dna_text)
        self.assertIn("motionPaused: state === 'failed'", ui_text)
        self.assertIn("const nextMotionPaused = Boolean(payload.motionPaused);", dna_text)
        self.assertIn("this.motionPaused = nextMotionPaused;", dna_text)
        self.assertIn("const nextProfile = profileForState(payload.state);", dna_text)
        self.assertIn("const SEGMENTS = 192;", dna_text)
        self.assertIn("const BACKBONE_OVERLAP = 1.08;", dna_text)
        self.assertIn("new THREE.CylinderGeometry(0.055, 0.055, 1, 18, 1, true)", dna_text)
        self.assertIn("length * axialScale", dna_text)
        self.assertIn("workflow-dna-progress.js?v=20260713-fanout-ui1", ui_text)
        self.assertNotIn("tmp/node_geometry_render", ui_text + dna_text)
        self.assertNotIn("data-segment=", ui_text)

    def test_frontend_opens_generated_html_for_private_result_users(self) -> None:
        ui_text = frontend_text()
        self.assertIn("function canOpenRichHtmlArtifacts(jobId = activeJobId)", ui_text)
        self.assertIn(
            "return canUseAdminSurfaces() || !!readTokenForJob(publicRunIdForJob(jobId));",
            ui_text,
        )
        self.assertIn("if (canOpenRichHtmlArtifacts(jobId)) return openHtmlResultWithAssets(event, jobId, relPath);", ui_text)
        self.assertIn("if (isHtmlAsset(path) && !canOpenRichHtmlArtifacts(jobId))", ui_text)

    def test_frontend_generated_html_preview_never_embeds_job_credentials(self) -> None:
        ui_text = frontend_text()
        self.assertIn("const RESULT_PREVIEW_NAVIGATOR_SCRIPT = String.raw", ui_text)
        self.assertIn("data-clusterweave-result-preview", ui_text)
        self.assertIn("data-clusterweave-result-artifact", ui_text)
        self.assertIn("data-clusterweave-result-fragment", ui_text)
        self.assertIn("clusterweave:result-bundle-navigate", ui_text)
        self.assertIn("event.target.closest", ui_text)
        self.assertIn("event.target.closest('a,area')", ui_text)
        self.assertIn("const resolved = await resolveResultArtifact(", ui_text)
        self.assertIn("{ optional: true }", ui_text)
        self.assertNotIn("data-authorization", ui_text)
        self.assertNotIn("scriptEl.dataset.authorization", ui_text)
        rewrite_block = ui_text.split("async function rewriteHtmlResultAssets", 1)[1].split(
            "async function buildHtmlResultObjectUrl", 1
        )[0]
        self.assertIn("script,iframe,object,embed,base", rewrite_block)
        self.assertIn("Content-Security-Policy", rewrite_block)
        self.assertIn("BIGSCAPE_RESULT_PREVIEW_CSP", rewrite_block)
        self.assertIn("CLINKER_RESULT_PREVIEW_CSP", rewrite_block)
        self.assertIn("STATIC_RESULT_PREVIEW_CSP", rewrite_block)
        self.assertIn("connect-src 'none'", ui_text)
        self.assertNotIn("injectResultPreviewNavigator(doc, jobId, htmlPath)", rewrite_block)

    def test_frontend_tool_bundles_use_authenticated_parent_relay_and_opaque_sandbox(self) -> None:
        js_text = (REPO_ROOT / "web" / "static" / "assets" / "clusterweave.js").read_text(encoding="utf-8")
        rewrite_block = js_text.split("async function rewriteHtmlResultAssets", 1)[1].split(
            "async function buildHtmlResultObjectUrl", 1
        )[0]
        sandbox_block = js_text.split("function renderSandboxedToolResultPreview", 1)[1].split(
            "async function openHtmlResultWithAssets", 1
        )[0]
        navigator_block = js_text.split("const RESULT_PREVIEW_NAVIGATOR_SCRIPT", 1)[1].split(
            "function resultUrlShouldStayExternal", 1
        )[0]

        self.assertIn("resultArtifactFamilyAssetPath", js_text)
        self.assertIn("allowToolBundleScripts", rewrite_block)
        self.assertIn("inlineToolResultScripts", rewrite_block)
        self.assertIn("rewriteToolResultScriptForSandbox", js_text)
        self.assertIn("TOOL_RESULT_PREVIEW_CSP", rewrite_block)
        self.assertIn("allowToolBundleScripts && value.startsWith('#')", rewrite_block)
        self.assertIn("querySelectorAll('[autofocus]')", rewrite_block)
        self.assertIn("? 'iframe,object,embed,base'", rewrite_block)
        self.assertNotIn("script:not([src]),iframe,object,embed,base", rewrite_block)
        self.assertIn("clusterweave:result-bundle-navigate", navigator_block)
        self.assertIn("window.parent.postMessage", navigator_block)
        self.assertIn("if (!artifact && fragment.startsWith('#'))", navigator_block)
        self.assertIn("window.viewer.switchToRegion(anchor);", navigator_block)
        self.assertIn("event.stopImmediatePropagation();", navigator_block)
        self.assertIn("clusterweaveAnchor", js_text)
        self.assertIn("sandbox compatibility profile", js_text)
        self.assertNotIn("fetch(", navigator_block)
        self.assertIn("event.source !== frame.contentWindow", sandbox_block)
        self.assertIn(
            "const targetDescriptor = resultArtifactDescriptor(event.data.artifact || '', resultContext);",
            sandbox_block,
        )
        self.assertIn("const targetPath = artifactPresentationKey(targetDescriptor);", sandbox_block)
        self.assertIn("currentDescriptor.bundle_id !== targetDescriptor.bundle_id", sandbox_block)
        self.assertIn("resultFetch(jobId, targetPath, { resultContext })", sandbox_block)
        self.assertIn("frame.setAttribute('sandbox', TOOL_RESULT_PREVIEW_SANDBOX)", sandbox_block)
        self.assertIn("targetWindow.URL.createObjectURL", sandbox_block)
        self.assertIn("targetWindow.URL.revokeObjectURL", sandbox_block)
        self.assertIn(
            "setFrameHtml(nestedHtml, event.data.fragment || '', targetPath, nextChannel);",
            sandbox_block,
        )
        self.assertNotIn("frame.srcdoc", sandbox_block)
        self.assertIn("const TOOL_RESULT_PREVIEW_SANDBOX = 'allow-scripts';", js_text)
        self.assertNotIn("allow-same-origin", sandbox_block)
        self.assertNotIn("Authorization", navigator_block + sandbox_block)
        self.assertNotIn("readToken", navigator_block + sandbox_block)

    def test_frontend_clinker_panel_scripts_are_confined_to_exact_sandboxed_preview(self) -> None:
        js_text = (REPO_ROOT / "web" / "static" / "assets" / "clusterweave.js").read_text(encoding="utf-8")
        rewrite_block = js_text.split("async function rewriteHtmlResultAssets", 1)[1].split(
            "async function buildHtmlResultObjectUrl", 1
        )[0]
        sandbox_block = js_text.split("function renderSandboxedClinkerPreview", 1)[1].split(
            "function renderSandboxedBigscapePreview", 1
        )[0]
        open_block = js_text.split("async function openHtmlResultWithAssets", 1)[1].split(
            "function resultFetch", 1
        )[0]

        self.assertIn(
            "options.allowClinkerInlineScripts === true && isExactPublicClinkerPanelHtml(htmlPath)",
            rewrite_block,
        )
        self.assertIn("'script[src],iframe,object,embed,base'", rewrite_block)
        self.assertIn("'script,iframe,object,embed,base'", rewrite_block)
        self.assertIn("meta[http-equiv=\"refresh\" i]", rewrite_block)
        self.assertIn("default-src 'none'; script-src 'unsafe-inline'; style-src", sandbox_block)
        self.assertIn("script-src 'unsafe-inline'", js_text)
        self.assertIn("connect-src 'none'", js_text)
        self.assertIn("object-src 'none'", js_text)
        self.assertIn("form-action 'none'", js_text)
        self.assertIn("base-uri 'none'", js_text)
        self.assertIn("const CLINKER_PREVIEW_SANDBOX = 'allow-scripts';", js_text)
        self.assertIn("frame.setAttribute('sandbox', CLINKER_PREVIEW_SANDBOX);", sandbox_block)
        self.assertIn("frame.setAttribute('referrerpolicy', 'no-referrer');", sandbox_block)
        self.assertIn("frame.srcdoc = htmlText;", sandbox_block)
        self.assertNotIn("allow-same-origin", sandbox_block)
        self.assertNotIn("allow-popups", sandbox_block)
        self.assertNotIn("allow-forms", sandbox_block)
        self.assertNotIn("allow-top-navigation", sandbox_block)
        self.assertIn("if (isExactPublicClinkerPanelHtml(relPath))", open_block)
        self.assertIn("renderSandboxedClinkerPreview(targetWindow, relPath, rewrittenHtml);", open_block)

    def test_frontend_clinker_panel_script_allowlist_rejects_nearby_paths(self) -> None:
        js_text = (REPO_ROOT / "web" / "static" / "assets" / "clusterweave.js").read_text(encoding="utf-8")
        matcher_start = js_text.index("function isExactPublicClinkerPanelHtml")
        matcher_end = js_text.index("\n}\n", matcher_start) + 3
        matcher = js_text[matcher_start:matcher_end]
        node_script = f"""
function normalizedResultPath(path) {{
  return String(path || '').replaceAll(String.fromCharCode(92), '/');
}}
const descriptors = new Map([
  ['AAAAAAAAAAAAAAAAAAAAAA', {{ category: 'synteny', filename: 'panel.html' }}],
  ['BBBBBBBBBBBBBBBBBBBBBB', {{ category: 'synteny', filename: 'PANEL.HTML' }}],
  ['CCCCCCCCCCCCCCCCCCCCCC', {{ category: 'antismash', filename: 'panel.html' }}],
  ['DDDDDDDDDDDDDDDDDDDDDD', {{ category: 'synteny', filename: 'index.html' }}],
  ['EEEEEEEEEEEEEEEEEEEEEE', {{ category: 'synteny', filename: 'panel.htm' }}],
  ['FFFFFFFFFFFFFFFFFFFFFF', {{ category: 'synteny', filename: 'panel.html.js' }}],
  ['GGGGGGGGGGGGGGGGGGGGGG', {{ category: 'bigscape', filename: 'panel.html' }}],
]);
function resultArtifactDescriptor(value) {{
  return descriptors.get(String(value || '')) || null;
}}
function resultArtifactName(value) {{
  return resultArtifactDescriptor(value)?.filename || '';
}}
{matcher}
const accepted = ['AAAAAAAAAAAAAAAAAAAAAA', 'BBBBBBBBBBBBBBBBBBBBBB'];
const rejected = [
  'CCCCCCCCCCCCCCCCCCCCCC',
  'DDDDDDDDDDDDDDDDDDDDDD',
  'EEEEEEEEEEEEEEEEEEEEEE',
  'FFFFFFFFFFFFFFFFFFFFFF',
  'GGGGGGGGGGGGGGGGGGGGGG',
  'ZZZZZZZZZZZZZZZZZZZZZZ',
];
process.stdout.write(JSON.stringify({{
  accepted: accepted.map(isExactPublicClinkerPanelHtml),
  rejected: rejected.map(isExactPublicClinkerPanelHtml),
}}));
"""
        result = subprocess.run(
            ["node", "-e", node_script],
            cwd=str(REPO_ROOT),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        verdicts = json.loads(result.stdout)
        self.assertEqual(verdicts["accepted"], [True, True])
        self.assertEqual(verdicts["rejected"], [False] * 6)
        self.assertIn("descriptor?.category === 'synteny'", matcher)
        self.assertNotIn("data/results", matcher)

    def test_frontend_bigscape_database_allowlist_accepts_only_sanitized_paths(self) -> None:
        js_text = (REPO_ROOT / "web" / "static" / "assets" / "clusterweave.js").read_text(encoding="utf-8")
        matcher_start = js_text.index("function isBigscapeDatabaseArtifact")
        matcher_end = js_text.index("\n}\n", matcher_start) + 3
        matcher = js_text[matcher_start:matcher_end]
        node_script = f"""
function normalizedResultPath(path) {{
  return String(path || '').replaceAll(String.fromCharCode(92), '/');
}}
const descriptors = new Map([
  ['AAAAAAAAAAAAAAAAAAAAAA', {{ category: 'bigscape', role: 'public-database', filename: 'clusterweave_public.sqlite' }}],
  ['BBBBBBBBBBBBBBBBBBBBBB', {{ category: 'bigscape', role: 'public-database', filename: 'portable.sqlite' }}],
  ['CCCCCCCCCCCCCCCCCCCCCC', {{ category: 'bigscape', role: 'viewer-database', filename: 'clusterweave_viewer.sqlite' }}],
  ['DDDDDDDDDDDDDDDDDDDDDD', {{ category: 'bigscape', role: 'raw-database', filename: 'data_sqlite.db' }}],
  ['EEEEEEEEEEEEEEEEEEEEEE', {{ category: 'bigscape', role: 'public-database-wal', filename: 'clusterweave_public.sqlite-wal' }}],
  ['FFFFFFFFFFFFFFFFFFFFFF', {{ category: 'other', role: 'public-database', filename: 'clusterweave_public.sqlite' }}],
]);
function resultArtifactDescriptor(value) {{
  return descriptors.get(String(value || '')) || null;
}}
{matcher}
const accepted = ['AAAAAAAAAAAAAAAAAAAAAA', 'BBBBBBBBBBBBBBBBBBBBBB'];
const rejected = [
  'CCCCCCCCCCCCCCCCCCCCCC',
  'DDDDDDDDDDDDDDDDDDDDDD',
  'EEEEEEEEEEEEEEEEEEEEEE',
  'FFFFFFFFFFFFFFFFFFFFFF',
  'ZZZZZZZZZZZZZZZZZZZZZZ',
];
process.stdout.write(JSON.stringify({{
  accepted: accepted.map(isBigscapeDatabaseArtifact),
  rejected: rejected.map(isBigscapeDatabaseArtifact),
}}));
"""
        result = subprocess.run(
            ["node", "-e", node_script],
            cwd=str(REPO_ROOT),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        verdicts = json.loads(result.stdout)
        self.assertEqual(verdicts["accepted"], [True, True])
        self.assertEqual(verdicts["rejected"], [False] * 5)
        self.assertIn("descriptor.role === 'public-database'", matcher)

    def test_frontend_bigscape_database_validation_checks_size_and_sqlite_magic(self) -> None:
        js_text = (REPO_ROOT / "web" / "static" / "assets" / "clusterweave.js").read_text(encoding="utf-8")
        max_line = next(line for line in js_text.splitlines() if line.startswith("const BIGSCAPE_BROWSER_DATABASE_MAX_BYTES"))
        header_line = next(line for line in js_text.splitlines() if line.startswith("const SQLITE_FORMAT_HEADER"))
        validator_start = js_text.index("async function validatedBigscapeDatabaseBuffer")
        validator_end = js_text.index("\n}\n", validator_start) + 3
        validator = js_text[validator_start:validator_end]
        node_script = f"""
{max_line}
{header_line}
{validator}
function responseFor(bytes, declaredSize) {{
  return {{
    headers: {{ get: () => String(declaredSize ?? bytes.byteLength) }},
    arrayBuffer: async () => bytes.buffer,
  }};
}}
(async () => {{
  const good = new Uint8Array(64);
  good.set(SQLITE_FORMAT_HEADER);
  const bad = good.slice();
  bad[0] = 0;
  const verdict = {{ good: 0, badMagic: false, oversized: false, empty: false }};
  verdict.good = (await validatedBigscapeDatabaseBuffer(responseFor(good))).byteLength;
  try {{ await validatedBigscapeDatabaseBuffer(responseFor(bad)); }} catch (error) {{ verdict.badMagic = true; }}
  try {{ await validatedBigscapeDatabaseBuffer(responseFor(good, BIGSCAPE_BROWSER_DATABASE_MAX_BYTES + 1)); }} catch (error) {{ verdict.oversized = true; }}
  try {{ await validatedBigscapeDatabaseBuffer(responseFor(new Uint8Array(0))); }} catch (error) {{ verdict.empty = true; }}
  process.stdout.write(JSON.stringify(verdict));
}})().catch(error => {{ console.error(error); process.exit(1); }});
"""
        result = subprocess.run(
            ["node", "-e", node_script],
            cwd=str(REPO_ROOT),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(
            json.loads(result.stdout),
            {"good": 64, "badMagic": True, "oversized": True, "empty": True},
        )

    def test_frontend_bigscape_viewer_path_is_exact_and_distinct_from_download(self) -> None:
        js_text = (REPO_ROOT / "web" / "static" / "assets" / "clusterweave.js").read_text(
            encoding="utf-8"
        )
        matcher_start = js_text.index("function isBigscapeViewerDatabaseArtifact")
        matcher_end = js_text.index("\n}\n", matcher_start) + 3
        matcher = js_text[matcher_start:matcher_end]
        full_start = js_text.index("function isBigscapeDatabaseArtifact")
        full_end = js_text.index("\n}\n", full_start) + 3
        full_matcher = js_text[full_start:full_end]
        node_script = f"""
function normalizedResultPath(path) {{
  return String(path || '').replaceAll(String.fromCharCode(92), '/');
}}
const BIGSCAPE_VIEWER_DATABASE_NAME = 'clusterweave_viewer.sqlite';
let activeJobMeta = {{ bigscape_viewer_available: true }};
const descriptors = new Map([
  ['AAAAAAAAAAAAAAAAAAAAAA', {{ category: 'bigscape', role: 'viewer-database', filename: 'clusterweave_viewer.sqlite' }}],
  ['BBBBBBBBBBBBBBBBBBBBBB', {{ category: 'bigscape', role: 'public-database', filename: 'clusterweave_public.sqlite' }}],
  ['CCCCCCCCCCCCCCCCCCCCCC', {{ category: 'bigscape', role: 'raw-database', filename: 'data_sqlite.db' }}],
  ['DDDDDDDDDDDDDDDDDDDDDD', {{ category: 'other', role: 'viewer-database', filename: 'clusterweave_viewer.sqlite' }}],
]);
function resultArtifactDescriptor(value) {{
  return descriptors.get(String(value || '')) || null;
}}
{full_matcher}
{matcher}
const viewer = 'AAAAAAAAAAAAAAAAAAAAAA';
const publicDownload = 'BBBBBBBBBBBBBBBBBBBBBB';
const rawDatabase = 'CCCCCCCCCCCCCCCCCCCCCC';
const wrongCategory = 'DDDDDDDDDDDDDDDDDDDDDD';
const shapeViewerAvailable = isBigscapeViewerDatabaseArtifact(BIGSCAPE_VIEWER_DATABASE_NAME);
activeJobMeta = {{ bigscape_viewer_available: false }};
process.stdout.write(JSON.stringify({{
  viewerAccepted: isBigscapeViewerDatabaseArtifact(viewer),
  publicRejectedAsViewer: !isBigscapeViewerDatabaseArtifact(publicDownload),
  rawRejectedAsViewer: !isBigscapeViewerDatabaseArtifact(rawDatabase),
  wrongCategoryRejected: !isBigscapeViewerDatabaseArtifact(wrongCategory),
  viewerIsDownload: isBigscapeDatabaseArtifact(viewer),
  publicIsDownload: isBigscapeDatabaseArtifact(publicDownload),
  rawIsDownload: isBigscapeDatabaseArtifact(rawDatabase),
  shapeViewerAvailable,
  shapeViewerUnavailable: !isBigscapeViewerDatabaseArtifact(BIGSCAPE_VIEWER_DATABASE_NAME),
}}));
"""
        result = subprocess.run(
            ["node", "-e", node_script],
            cwd=str(REPO_ROOT),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(
            json.loads(result.stdout),
            {
                "viewerAccepted": True,
                "publicRejectedAsViewer": True,
                "rawRejectedAsViewer": True,
                "wrongCategoryRejected": True,
                "viewerIsDownload": False,
                "publicIsDownload": True,
                "rawIsDownload": False,
                "shapeViewerAvailable": True,
                "shapeViewerUnavailable": True,
            },
        )
        self.assertIn("descriptor.role === 'viewer-database'", matcher)

    def test_frontend_bigscape_database_pairing_stays_with_html_result_scope(self) -> None:
        js_text = (REPO_ROOT / "web" / "static" / "assets" / "clusterweave.js").read_text(encoding="utf-8")
        helpers_start = js_text.index("function chooseBigscapeDatabase")
        helpers_end = js_text.index("function summarySortKey", helpers_start)
        helpers = js_text[helpers_start:helpers_end]
        matcher_start = js_text.index("function isBigscapeDatabaseArtifact")
        matcher_end = js_text.index("\n}\n", matcher_start) + 3
        matcher = js_text[matcher_start:matcher_end]
        node_script = f"""
function normalizedResultPath(path) {{
  return String(path || '').replaceAll(String.fromCharCode(92), '/');
}}
const descriptors = new Map([
  ['AAAAAAAAAAAAAAAAAAAAAA', {{ category: 'bigscape', role: 'html', pair_id: 'pair-a' }}],
  ['BBBBBBBBBBBBBBBBBBBBBB', {{ category: 'bigscape', role: 'html', pair_id: 'pair-b' }}],
  ['CCCCCCCCCCCCCCCCCCCCCC', {{ category: 'bigscape', role: 'html' }}],
  ['DDDDDDDDDDDDDDDDDDDDDD', {{ category: 'bigscape', role: 'public-database', pair_id: 'pair-a' }}],
  ['EEEEEEEEEEEEEEEEEEEEEE', {{ category: 'bigscape', role: 'public-database', pair_id: 'pair-b' }}],
  ['FFFFFFFFFFFFFFFFFFFFFF', {{ category: 'bigscape', role: 'public-database', pair_id: 'pair-x' }}],
  ['GGGGGGGGGGGGGGGGGGGGGG', {{ category: 'bigscape', role: 'viewer-database', pair_id: 'pair-a' }}],
  ['HHHHHHHHHHHHHHHHHHHHHH', {{ category: 'bigscape', role: 'raw-database', pair_id: 'pair-a' }}],
]);
function resultArtifactDescriptor(value) {{
  return descriptors.get(String(value || '')) || null;
}}
{matcher}
{helpers}
const html = 'AAAAAAAAAAAAAAAAAAAAAA';
const canonicalHtml = 'BBBBBBBBBBBBBBBBBBBBBB';
const unauditedHtml = 'CCCCCCCCCCCCCCCCCCCCCC';
const paired = 'DDDDDDDDDDDDDDDDDDDDDD';
const canonical = 'EEEEEEEEEEEEEEEEEEEEEE';
const crossPair = 'FFFFFFFFFFFFFFFFFFFFFF';
const viewer = 'GGGGGGGGGGGGGGGGGGGGGG';
const raw = 'HHHHHHHHHHHHHHHHHHHHHH';
const publicCandidates = [crossPair, viewer, raw, canonical, paired]
  .filter(isBigscapeDatabaseArtifact);
process.stdout.write(JSON.stringify({{
  sameScope: chooseBigscapeDatabase(html, publicCandidates),
  canonical: chooseBigscapeDatabase(canonicalHtml, [paired, canonical]),
  unaudited: chooseBigscapeDatabase(unauditedHtml, [paired, canonical]),
  crossPair: chooseBigscapeDatabase(html, [crossPair]),
  viewerRejected: chooseBigscapeDatabase(html, [viewer].filter(isBigscapeDatabaseArtifact)),
  rawRejected: chooseBigscapeDatabase(html, [raw].filter(isBigscapeDatabaseArtifact)),
}}));
"""
        result = subprocess.run(
            ["node", "-e", node_script],
            cwd=str(REPO_ROOT),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(
            json.loads(result.stdout),
            {
                "sameScope": "DDDDDDDDDDDDDDDDDDDDDD",
                "canonical": "EEEEEEEEEEEEEEEEEEEEEE",
                "unaudited": "",
                "crossPair": "",
                "viewerRejected": "",
                "rawRejected": "",
            },
        )
        self.assertIn("htmlDescriptor?.pair_id", helpers)
        self.assertIn("descriptor.role === 'public-database'", matcher)

    def test_frontend_bigscape_preview_uses_parent_transfer_and_strict_sandbox(self) -> None:
        js_text = (REPO_ROOT / "web" / "static" / "assets" / "clusterweave.js").read_text(encoding="utf-8")
        rewrite_block = js_text.split("async function rewriteHtmlResultAssets", 1)[1].split(
            "async function buildHtmlResultObjectUrl", 1
        )[0]
        sandbox_block = js_text.split("function renderSandboxedBigscapePreview", 1)[1].split(
            "function renderSandboxedToolResultPreview", 1
        )[0]
        contract_block = js_text.split("function injectBigscapeDatabaseContract", 1)[1].split(
            "async function openBigscapeResult", 1
        )[0]
        open_block = js_text.split("async function openBigscapeResult", 1)[1].split(
            "function renderBigscapeReader", 1
        )[0]
        viewer_fetch_block = js_text.split("function bigscapeViewerFetch", 1)[1].split(
            "async function handleResultLinkClick", 1
        )[0]

        self.assertIn("options.allowBigscapeScripts === true && isBigscapeHtmlArtifact(htmlPath)", rewrite_block)
        self.assertIn("inlineBigscapeResultScripts(doc, jobId, htmlPath, assetOptions)", rewrite_block)
        self.assertNotIn("...(allowBigscapeScripts ? [['script[src]', 'src']] : [])", rewrite_block)
        self.assertIn("? BIGSCAPE_RESULT_PREVIEW_CSP", rewrite_block)
        self.assertIn("const BIGSCAPE_PREVIEW_SANDBOX = 'allow-scripts';", js_text)
        self.assertIn(
            "const BIGSCAPE_RESULT_PREVIEW_CSP = \"default-src 'none'; "
            "script-src 'unsafe-inline'; img-src data: blob:; "
            "style-src 'unsafe-inline' data: blob:; font-src data: blob:; "
            "media-src data: blob:; connect-src 'none'; object-src 'none'; "
            "frame-src 'none'; worker-src 'none'; form-action 'none'; base-uri 'none'\";",
            js_text,
        )
        self.assertNotIn("'unsafe-eval'", js_text)
        self.assertNotIn("'wasm-unsafe-eval'", js_text)
        self.assertIn("frame.setAttribute('sandbox', BIGSCAPE_PREVIEW_SANDBOX);", sandbox_block)
        self.assertIn("event.source !== frame.contentWindow", sandbox_block)
        self.assertIn("payload.type !== 'clusterweave:bigscape-database-ready'", sandbox_block)
        self.assertIn("window.CLUSTERWEAVE_BIGSCAPE_INSTALL_TRANSFER = function", sandbox_block)
        self.assertIn("window.addEventListener('message', transferDatabase);", sandbox_block)
        self.assertIn("window.addEventListener('pagehide', cleanupTransfer", sandbox_block)
        self.assertIn("window.addEventListener('beforeunload', cleanupTransfer", sandbox_block)
        self.assertIn("if (transferTimeout) window.clearTimeout(transferTimeout);", sandbox_block)
        self.assertIn("transferTimeout = window.setTimeout(cleanupTransfer, 120000);", sandbox_block)
        self.assertIn("const installTransfer = targetWindow.CLUSTERWEAVE_BIGSCAPE_INSTALL_TRANSFER;", sandbox_block)
        self.assertIn("installTransfer(databaseBuffer, channel, frame.id);", sandbox_block)
        self.assertNotIn("targetWindow.addEventListener", sandbox_block)
        self.assertIn("databaseBuffer = null;", sandbox_block)
        self.assertIn(
            "Object.prototype.toString.call(buffer) === '[object ArrayBuffer]'",
            sandbox_block,
        )
        self.assertIn("Number.isFinite(buffer.byteLength)", sandbox_block)
        self.assertNotIn("buffer instanceof ArrayBuffer", sandbox_block)
        self.assertIn("frame.contentWindow.postMessage", sandbox_block)
        self.assertNotIn("BIGSCAPE_DATABASE_TRANSFER_CHUNK_BYTES", js_text)
        self.assertNotIn("clusterweave:bigscape-database-start", js_text)
        self.assertNotIn("clusterweave:bigscape-database-chunk", js_text)
        self.assertNotIn("clusterweave:bigscape-database-complete", js_text)
        self.assertIn("type: 'clusterweave:bigscape-database'", sandbox_block)
        self.assertIn("type: 'clusterweave:bigscape-database-error'", sandbox_block)
        self.assertIn("}, '*', [buffer]);", sandbox_block)
        self.assertIn("frame.srcdoc = htmlText;", sandbox_block)
        self.assertIn("connect-src 'none'", sandbox_block)
        for permission in ["allow-same-origin", "allow-popups", "allow-forms", "allow-top-navigation", "allow-downloads"]:
            self.assertNotIn(permission, sandbox_block)
        self.assertIn("function receiveBuffer()", contract_block)
        self.assertIn("event.source !== window.parent", contract_block)
        self.assertIn("window.parent.postMessage({ type: 'clusterweave:bigscape-database-ready'", contract_block)
        self.assertIn("payload.type !== 'clusterweave:bigscape-database'", contract_block)
        self.assertIn("payload.buffer.byteLength > maxBytes", contract_block)
        self.assertIn("sqliteHeader.every", contract_block)
        self.assertIn(
            "Object.prototype.toString.call(payload.buffer) !== '[object ArrayBuffer]'",
            contract_block,
        )
        self.assertNotIn("payload.buffer instanceof ArrayBuffer", contract_block)
        self.assertIn("readyInterval = window.setInterval(announceReady, 250);", contract_block)
        self.assertIn("if (readyInterval) window.clearInterval(readyInterval);", contract_block)
        self.assertIn("}, 120000);", contract_block)
        self.assertNotIn("fetch(", contract_block)
        self.assertIn("bigscapeViewerFetch(jobId)", open_block)
        self.assertNotIn("resultFetch(jobId, databasePath)", open_block)
        self.assertIn("isBigscapeViewerDatabaseArtifact(databasePath)", open_block)
        self.assertIn("validatedBigscapeDatabaseBuffer(dbResp)", open_block)
        self.assertIn("allowBigscapeScripts: true", open_block)
        self.assertIn("renderSandboxedBigscapePreview", open_block)
        self.assertNotIn("Authorization", contract_block + open_block + sandbox_block)
        self.assertNotIn("CLUSTERWEAVE_BIGSCAPE_DATABASE_AUTH", js_text)
        self.assertNotIn("dbAuth", contract_block + open_block)
        self.assertNotIn("dbUrl", contract_block + open_block)
        self.assertIn(
            "`api/results/${encodeURIComponent(runId)}/bigscape-viewer-database`",
            viewer_fetch_block,
        )
        self.assertNotIn("/artifacts/", viewer_fetch_block)
        self.assertNotIn("public-database", viewer_fetch_block)
        self.assertNotIn("raw-database", viewer_fetch_block)
        self.assertEqual(open_block.count("bigscapeViewerFetch(jobId)"), 1)
        self.assertEqual(open_block.count("resultFetch(jobId, htmlPath)"), 1)
        self.assertNotIn("resultFetch(jobId, databasePath)", open_block)

    def test_frontend_bigscape_parent_transfer_accepts_cross_realm_buffer_and_cleans_up(self) -> None:
        js_text = (REPO_ROOT / "web" / "static" / "assets" / "clusterweave.js").read_text(
            encoding="utf-8"
        )
        start = js_text.index("function renderSandboxedBigscapePreview")
        end = js_text.index("\nfunction renderSandboxedToolResultPreview", start)
        render_source = js_text[start:end]
        node_script = """
const vm = require('node:vm');
function fileNameFromPath() { return 'index.html'; }
function escapeHtml(value) { return String(value); }
const BIGSCAPE_PREVIEW_SANDBOX = 'allow-scripts';
const renderSandboxedBigscapePreview = eval('(' + %s + ')');

function harness(databaseBuffer) {
  const listeners = new Map();
  const timers = [];
  const posts = [];
  let nextTimer = 1;
  let popupContext = null;
  let registeredMessageHandler = null;
  const frameWindow = {
    postMessage(payload, target, transfer = []) {
      posts.push({ payload, target, transfer });
    },
  };
  const frame = {
    contentWindow: frameWindow,
    setAttribute() {},
    id: '',
    srcdoc: '',
  };
  const document = {
    open() {},
    write(html) {
      const match = String(html).match(/<script>([\\s\\S]*?)<\\/script>/i);
      if (!match) throw new Error('popup relay script missing');
      vm.runInContext(match[1], popupContext);
    },
    close() {},
    createElement(name) {
      if (name !== 'iframe') throw new Error('unexpected element');
      return frame;
    },
    getElementById(id) {
      return frame.id === id ? frame : null;
    },
    body: { appendChild() {} },
  };
  const popupGlobal = {
    document,
    addEventListener(type, handler) {
      if (!listeners.has(type)) listeners.set(type, new Set());
      listeners.get(type).add(handler);
      if (type === 'message') registeredMessageHandler = handler;
    },
    removeEventListener(type, handler) {
      listeners.get(type)?.delete(handler);
    },
    setTimeout(handler, ms) {
      const timer = { id: nextTimer++, handler, ms, cleared: false };
      timers.push(timer);
      return timer.id;
    },
    clearTimeout(id) {
      const timer = timers.find(candidate => candidate.id === id);
      if (timer) timer.cleared = true;
    },
  };
  popupGlobal.window = popupGlobal;
  popupContext = vm.createContext(popupGlobal);
  function emit(type, event = {}) {
    for (const handler of Array.from(listeners.get(type) || [])) handler(event);
  }
  renderSandboxedBigscapePreview(
    popupContext,
    'data/results/demo/big_scape/output_files/index.html',
    '<!doctype html><html><body></body></html>',
    databaseBuffer,
    'expected-channel',
  );
  popupContext.__registeredMessageHandler = registeredMessageHandler;
  const handlerInPopupRealm = vm.runInContext(
    '__registeredMessageHandler instanceof Function',
    popupContext,
  );
  delete popupContext.__registeredMessageHandler;
  return {
    listeners,
    timers,
    posts,
    frameWindow,
    emit,
    registeredMessageHandler,
    handlerInPopupRealm,
    handlerInOpenerRealm: registeredMessageHandler instanceof Function,
    popupContext,
  };
}

const foreignBuffer = vm.runInNewContext('new ArrayBuffer(64)');
new Uint8Array(foreignBuffer)[0] = 83;
const success = harness(foreignBuffer);
success.emit('message', {
  source: success.frameWindow,
  data: { type: 'clusterweave:bigscape-database-ready', channel: 'wrong-channel' },
});
const beforeMatch = success.posts.length;
success.emit('message', {
  source: success.frameWindow,
  data: { type: 'clusterweave:bigscape-database-ready', channel: 'expected-channel' },
});

const expiredBuffer = vm.runInNewContext('new ArrayBuffer(32)');
const expired = harness(expiredBuffer);
const expiredReady = expired.registeredMessageHandler;
expired.timers[0].handler();
expiredReady({
  source: expired.frameWindow,
  data: { type: 'clusterweave:bigscape-database-ready', channel: 'expected-channel' },
});

const unloading = harness(vm.runInNewContext('new ArrayBuffer(32)'));
const unloadingReady = unloading.registeredMessageHandler;
unloading.emit('beforeunload');
unloadingReady({
  source: unloading.frameWindow,
  data: { type: 'clusterweave:bigscape-database-ready', channel: 'expected-channel' },
});

const delivered = success.posts[0] || {};
process.stdout.write(JSON.stringify({
  crossRealmInstanceof: foreignBuffer instanceof ArrayBuffer,
  crossRealmTag: Object.prototype.toString.call(foreignBuffer),
  handlerInPopupRealm: success.handlerInPopupRealm,
  handlerInOpenerRealm: success.handlerInOpenerRealm,
  beforeMatch,
  deliveredType: delivered.payload?.type || '',
  deliveredSameBuffer: delivered.payload?.buffer === foreignBuffer,
  transferredSameBuffer: delivered.transfer?.[0] === foreignBuffer,
  successTimeoutMs: success.timers[0]?.ms || 0,
  successTimeoutCleared: success.timers[0]?.cleared || false,
  successListenersRemaining: Array.from(success.listeners.values()).reduce((n, set) => n + set.size, 0),
  successRelayCleared: success.popupContext.CLUSTERWEAVE_BIGSCAPE_INSTALL_TRANSFER === null,
  expiredTimeoutMs: expired.timers[0]?.ms || 0,
  expiredPosts: expired.posts.length,
  expiredListenersRemaining: Array.from(expired.listeners.values()).reduce((n, set) => n + set.size, 0),
  unloadingPosts: unloading.posts.length,
  unloadingTimeoutCleared: unloading.timers[0]?.cleared || false,
  unloadingListenersRemaining: Array.from(unloading.listeners.values()).reduce((n, set) => n + set.size, 0),
}));
""" % json.dumps(render_source)
        result = subprocess.run(
            ["node", "-e", node_script],
            cwd=str(REPO_ROOT),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(
            json.loads(result.stdout),
            {
                "crossRealmInstanceof": False,
                "crossRealmTag": "[object ArrayBuffer]",
                "handlerInPopupRealm": True,
                "handlerInOpenerRealm": False,
                "beforeMatch": 0,
                "deliveredType": "clusterweave:bigscape-database",
                "deliveredSameBuffer": True,
                "transferredSameBuffer": True,
                "successTimeoutMs": 120000,
                "successTimeoutCleared": True,
                "successListenersRemaining": 0,
                "successRelayCleared": True,
                "expiredTimeoutMs": 120000,
                "expiredPosts": 0,
                "expiredListenersRemaining": 0,
                "unloadingPosts": 0,
                "unloadingTimeoutCleared": True,
                "unloadingListenersRemaining": 0,
            },
        )

    def test_frontend_bigscape_child_readiness_retries_and_transfer_lifecycle_is_bounded(self) -> None:
        js_text = (REPO_ROOT / "web" / "static" / "assets" / "clusterweave.js").read_text(
            encoding="utf-8"
        )
        contract_start = js_text.index("function injectBigscapeDatabaseContract")
        receive_start = js_text.index("  function receiveBuffer()", contract_start)
        receive_end = js_text.index("\n  function emitReady()", receive_start)
        receive_source = js_text[receive_start:receive_end].replace(
            "${BIGSCAPE_BROWSER_DATABASE_MAX_BYTES}", str(64 * 1024 * 1024)
        )
        node_script = """
const vm = require('node:vm');
const makeReceiver = eval(`(function(window, channel) {
  let bufferPromise = null;
  %s
  return receiveBuffer;
})`);

function harness() {
  const listeners = new Map();
  const timers = [];
  const intervals = [];
  const posts = [];
  let nextId = 1;
  const parent = {};
  const window = {
    parent,
    addEventListener(type, handler) {
      if (!listeners.has(type)) listeners.set(type, new Set());
      listeners.get(type).add(handler);
    },
    removeEventListener(type, handler) {
      listeners.get(type)?.delete(handler);
    },
    setTimeout(handler, ms) {
      const timer = { id: nextId++, handler, ms, cleared: false };
      timers.push(timer);
      return timer.id;
    },
    clearTimeout(id) {
      const timer = timers.find(candidate => candidate.id === id);
      if (timer) timer.cleared = true;
    },
    setInterval(handler, ms) {
      const interval = { id: nextId++, handler, ms, cleared: false };
      intervals.push(interval);
      return interval.id;
    },
    clearInterval(id) {
      const interval = intervals.find(candidate => candidate.id === id);
      if (interval) interval.cleared = true;
    },
  };
  parent.postMessage = payload => posts.push(payload);
  function emit(type, event) {
    for (const handler of Array.from(listeners.get(type) || [])) handler(event);
  }
  return {
    window,
    parent,
    listeners,
    timers,
    intervals,
    posts,
    emit,
    receiveBuffer: makeReceiver(window, 'expected-channel'),
  };
}

(async () => {
  const success = harness();
  const promise = success.receiveBuffer();
  const repeatedPromise = success.receiveBuffer();
  const initialAnnouncements = success.posts.length;
  success.intervals[0].handler();
  success.intervals[0].handler();
  success.emit('message', {
    source: {},
    data: { type: 'clusterweave:bigscape-database', channel: 'expected-channel', buffer: new ArrayBuffer(8) },
  });
  success.emit('message', {
    source: success.parent,
    data: { type: 'clusterweave:bigscape-database', channel: 'wrong-channel', buffer: new ArrayBuffer(8) },
  });

  const foreignBuffer = vm.runInNewContext('new ArrayBuffer(64)');
  new Uint8Array(foreignBuffer).set([83, 81, 76, 105, 116, 101, 32, 102, 111, 114, 109, 97, 116, 32, 51, 0]);
  success.emit('message', {
    source: success.parent,
    data: { type: 'clusterweave:bigscape-database', channel: 'expected-channel', buffer: foreignBuffer },
  });
  const resolved = await promise;

  const expired = harness();
  const expiredPromise = expired.receiveBuffer();
  const lateHandler = Array.from(expired.listeners.get('message'))[0];
  expired.timers[0].handler();
  const timeoutMessage = await expiredPromise.then(() => '', error => error.message);
  lateHandler({
    source: expired.parent,
    data: { type: 'clusterweave:bigscape-database', channel: 'expected-channel', buffer: foreignBuffer },
  });

  process.stdout.write(JSON.stringify({
    samePromise: promise === repeatedPromise,
    crossRealmInstanceof: foreignBuffer instanceof ArrayBuffer,
    crossRealmTag: Object.prototype.toString.call(foreignBuffer),
    initialAnnouncements,
    retriedAnnouncements: success.posts.length,
    announcementsValid: success.posts.every(payload =>
      payload.type === 'clusterweave:bigscape-database-ready'
      && payload.channel === 'expected-channel'),
    resolvedSameBuffer: resolved === foreignBuffer,
    retryIntervalMs: success.intervals[0]?.ms || 0,
    transferTimeoutMs: success.timers[0]?.ms || 0,
    intervalCleared: success.intervals[0]?.cleared || false,
    timeoutCleared: success.timers[0]?.cleared || false,
    successListenersRemaining: Array.from(success.listeners.values()).reduce((n, set) => n + set.size, 0),
    timeoutMessage,
    expiredIntervalCleared: expired.intervals[0]?.cleared || false,
    expiredTimeoutCleared: expired.timers[0]?.cleared || false,
    expiredListenersRemaining: Array.from(expired.listeners.values()).reduce((n, set) => n + set.size, 0),
  }));
})().catch(error => {
  console.error(error);
  process.exit(1);
});
""" % receive_source
        result = subprocess.run(
            ["node", "-e", node_script],
            cwd=str(REPO_ROOT),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(
            json.loads(result.stdout),
            {
                "samePromise": True,
                "crossRealmInstanceof": False,
                "crossRealmTag": "[object ArrayBuffer]",
                "initialAnnouncements": 1,
                "retriedAnnouncements": 3,
                "announcementsValid": True,
                "resolvedSameBuffer": True,
                "retryIntervalMs": 250,
                "transferTimeoutMs": 120000,
                "intervalCleared": True,
                "timeoutCleared": True,
                "successListenersRemaining": 0,
                "timeoutMessage": "Compact BiG-SCAPE viewer database transfer timed out.",
                "expiredIntervalCleared": True,
                "expiredTimeoutCleared": True,
                "expiredListenersRemaining": 0,
            },
        )

    def test_frontend_bigscape_opaque_sandbox_assets_are_not_parent_blob_urls(self) -> None:
        js_text = (REPO_ROOT / "web" / "static" / "assets" / "clusterweave.js").read_text(
            encoding="utf-8"
        )
        helpers = js_text.split("function resultUrlShouldStayExternal", 1)[1].split(
            "const STATIC_RESULT_PREVIEW_CSP", 1
        )[0]
        asset_loader = js_text.split("function resultBlobDataUrl", 1)[1].split(
            "async function rewriteHtmlResultAssets", 1
        )[0]
        csp_line = next(
            line
            for line in js_text.splitlines()
            if line.startswith("const BIGSCAPE_RESULT_PREVIEW_CSP")
        )
        node_script = f"""
function normalizedResultPath(path) {{
  return String(path || '').replaceAll(String.fromCharCode(92), '/');
}}
function fileNameFromPath(path) {{
  const parts = normalizedResultPath(path).split('/');
  return parts[parts.length - 1] || normalizedResultPath(path);
}}
function resultPathExt(path) {{
  const name = fileNameFromPath(path).toLowerCase();
  return name.includes('.') ? name.split('.').pop() : '';
}}
function inlineResultMime(path, fallback = '') {{
  const mime = {{ js: 'text/javascript;charset=utf-8', css: 'text/css;charset=utf-8', png: 'image/png' }};
  return mime[resultPathExt(path)] || fallback || 'application/octet-stream';
}}
const resultHelperObjectUrls = [];
const BIGSCAPE_KINETIC_GLOBAL_EVAL_SHIM = '(1,eval)("this")';
const BIGSCAPE_KINETIC_GLOBAL_EVAL_SHIM_COUNT = 2;
let parentBlobCalls = 0;
URL.createObjectURL = function () {{
  parentBlobCalls += 1;
  return 'blob:parent-created';
}};
globalThis.FileReader = class {{
  readAsDataURL(blob) {{
    blob.arrayBuffer().then(buffer => {{
      this.result = 'data:' + (blob.type || 'application/octet-stream') + ';base64,'
        + Buffer.from(buffer).toString('base64');
      if (this.onload) this.onload();
    }}).catch(error => {{
      this.error = error;
      if (this.onerror) this.onerror();
    }});
  }}
}};
const ownerKey = 'artifact/bigscape/AAAAAAAAAAAAAAAAAAAAAA/index.html';
const descriptorRows = [
  [ownerKey, {{
    id: 'AAAAAAAAAAAAAAAAAAAAAA', filename: 'index.html', category: 'bigscape',
    bundle_id: 'bigscape-a',
  }}],
  ['artifact/bigscape/BBBBBBBBBBBBBBBBBBBBBB/app.js', {{
    id: 'BBBBBBBBBBBBBBBBBBBBBB', filename: 'app.js', category: 'bigscape',
    bundle_id: 'bigscape-a',
  }}],
  ['artifact/bigscape/CCCCCCCCCCCCCCCCCCCCCC/vendor.js', {{
    id: 'CCCCCCCCCCCCCCCCCCCCCC', filename: 'vendor.js', category: 'bigscape',
    bundle_id: 'bigscape-a',
  }}],
  ['artifact/bigscape/DDDDDDDDDDDDDDDDDDDDDD/kinetic-v5.1.0.min.js', {{
    id: 'DDDDDDDDDDDDDDDDDDDDDD', filename: 'kinetic-v5.1.0.min.js', category: 'bigscape',
    bundle_id: 'bigscape-a',
  }}],
  ['artifact/bigscape/EEEEEEEEEEEEEEEEEEEEEE/kinetic-v5.1.0-copy.min.js', {{
    id: 'EEEEEEEEEEEEEEEEEEEEEE', filename: 'kinetic-v5.1.0-copy.min.js', category: 'bigscape',
    bundle_id: 'bigscape-a',
  }}],
  ['artifact/bigscape/FFFFFFFFFFFFFFFFFFFFFF/app.css', {{
    id: 'FFFFFFFFFFFFFFFFFFFFFF', filename: 'app.css', category: 'bigscape',
    bundle_id: 'bigscape-a',
  }}],
  ['artifact/bigscape/GGGGGGGGGGGGGGGGGGGGGG/pixel.png', {{
    id: 'GGGGGGGGGGGGGGGGGGGGGG', filename: 'pixel.png', category: 'bigscape',
    bundle_id: 'bigscape-a',
  }}],
  ['artifact/bigscape/HHHHHHHHHHHHHHHHHHHHHH/declared-huge.png', {{
    id: 'HHHHHHHHHHHHHHHHHHHHHH', filename: 'declared-huge.png', category: 'bigscape',
    bundle_id: 'bigscape-a',
  }}],
  ['artifact/bigscape/IIIIIIIIIIIIIIIIIIIIII/actual-huge.png', {{
    id: 'IIIIIIIIIIIIIIIIIIIIII', filename: 'actual-huge.png', category: 'bigscape',
    bundle_id: 'bigscape-a',
  }}],
];
const artifactDescriptors = new Map(descriptorRows);
const artifactKeyById = new Map(
  descriptorRows.map(([key, descriptor]) => [descriptor.id, key]),
);
function resultArtifactDescriptor(value) {{
  const candidate = String(value || '');
  if (artifactDescriptors.has(candidate)) return artifactDescriptors.get(candidate);
  for (const descriptor of artifactDescriptors.values()) {{
    if (descriptor.id === candidate) return descriptor;
  }}
  return null;
}}
function resultArtifactId(value) {{
  return String(resultArtifactDescriptor(value)?.id || '');
}}
function resultArtifactName(value) {{
  return resultArtifactDescriptor(value)?.filename || fileNameFromPath(value);
}}
const payloads = {{
  'BBBBBBBBBBBBBBBBBBBBBB': {{
    type: 'text/javascript;charset=utf-8',
    body: 'window.ORDER.push("app");</script><script>window.INJECTED = true;',
  }},
  'CCCCCCCCCCCCCCCCCCCCCC': {{
    type: 'text/javascript;charset=utf-8',
    body: 'window.ORDER.push("vendor");',
  }},
  'DDDDDDDDDDDDDDDDDDDDDD': {{
    type: 'text/javascript;charset=utf-8',
    body: '(1,eval)("this");window.KINETIC = true;(1,eval)("this");',
  }},
  'EEEEEEEEEEEEEEEEEEEEEE': {{
    type: 'text/javascript;charset=utf-8',
    body: '(1,eval)("this");window.UNRELATED = true;(1,eval)("this");',
  }},
  'FFFFFFFFFFFFFFFFFFFFFF': {{
    type: 'text/css;charset=utf-8',
    body: 'body{{background-image:url(../img/pixel.png)}}',
  }},
  'GGGGGGGGGGGGGGGGGGGGGG': {{
    type: 'image/png',
    body: String.fromCharCode(137, 80, 78, 71),
  }},
  'HHHHHHHHHHHHHHHHHHHHHH': {{
    type: 'image/png', body: 'x', declaredSize: 16 * 1024 * 1024 + 1,
  }},
  'IIIIIIIIIIIIIIIIIIIIII': {{
    type: 'image/png', body: 'x', declaredSize: 1, actualSize: 16 * 1024 * 1024 + 1,
  }},
}};
const resolvedArtifactIds = new Map([
  ['AAAAAAAAAAAAAAAAAAAAAA:html_content/js/app.js', 'BBBBBBBBBBBBBBBBBBBBBB'],
  ['AAAAAAAAAAAAAAAAAAAAAA:html_content/js/vendor.js', 'CCCCCCCCCCCCCCCCCCCCCC'],
  ['AAAAAAAAAAAAAAAAAAAAAA:html_content/js/kinetic-v5.1.0.min.js', 'DDDDDDDDDDDDDDDDDDDDDD'],
  ['AAAAAAAAAAAAAAAAAAAAAA:html_content/js/kinetic-v5.1.0-copy.min.js', 'EEEEEEEEEEEEEEEEEEEEEE'],
  ['AAAAAAAAAAAAAAAAAAAAAA:html_content/css/app.css', 'FFFFFFFFFFFFFFFFFFFFFF'],
  ['AAAAAAAAAAAAAAAAAAAAAA:html_content/img/pixel.png', 'GGGGGGGGGGGGGGGGGGGGGG'],
  ['AAAAAAAAAAAAAAAAAAAAAA:html_content/img/declared-huge.png', 'HHHHHHHHHHHHHHHHHHHHHH'],
  ['AAAAAAAAAAAAAAAAAAAAAA:html_content/img/actual-huge.png', 'IIIIIIIIIIIIIIIIIIIIII'],
  ['FFFFFFFFFFFFFFFFFFFFFF:../img/pixel.png', 'GGGGGGGGGGGGGGGGGGGGGG'],
]);
const fetchedPaths = [];
const bodyReadPaths = [];
async function resultFetch(jobId, path) {{
  void jobId;
  fetchedPaths.push(path);
  const item = payloads[resultArtifactId(path)];
  if (!item) return {{ ok: false, headers: {{ get: () => '' }} }};
  const bytes = item.actualSize
    ? Buffer.alloc(item.actualSize)
    : Buffer.from(item.body, 'binary');
  return {{
    ok: true,
    headers: {{ get: name => {{
      const key = String(name).toLowerCase();
      if (key === 'content-type') return item.type;
      if (key === 'content-length') return String(item.declaredSize ?? bytes.byteLength);
      return '';
    }} }},
    text: async () => {{ bodyReadPaths.push(path); return item.body; }},
    blob: async () => {{ bodyReadPaths.push(path); return new Blob([bytes], {{ type: item.type }}); }},
    arrayBuffer: async () => bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength),
  }};
}}
function resultUrlShouldStayExternal{helpers}
function resultBlobDataUrl{asset_loader}
async function resolveResultArtifact(jobId, ownerArtifact, reference) {{
  void jobId;
  const ownerId = resultArtifactId(ownerArtifact);
  if (!ownerId) return null;
  const referencePath = String(reference || '').split(/[?#]/, 1)[0];
  const childId = resolvedArtifactIds.get(`${{ownerId}}:${{referencePath}}`) || '';
  const key = artifactKeyById.get(childId) || '';
  if (!key) return null;
  return {{ key, descriptor: resultArtifactDescriptor(key), fragment: '' }};
}}
(async () => {{
  const owner = ownerKey;
  const cssOwner = 'artifact/bigscape/FFFFFFFFFFFFFFFFFFFFFF/app.css';
  const regularUrl = await resultAssetObjectUrl('job', owner, 'html_content/js/app.js', new Map());
  const regularBlobCalls = parentBlobCalls;
  const portable = {{
    portableDataUrls: true,
    bigscapeMode: true,
    bigscapeMode: true,
    bigscapeHtmlPath: owner,
    bigscapeAssetBudget: {{ declaredBytes: 0, actualBytes: 0 }},
  }};
  const cssUrl = await resultAssetObjectUrl(
    'job', owner, 'html_content/css/app.css', new Map(), portable,
  );
  const imageUrl = await resultAssetObjectUrl(
    'job', owner, 'html_content/img/pixel.png', new Map(), portable,
  );
  const sqliteTraversal = await resultAssetObjectUrl(
    'job', owner, '../public/clusterweave_public.sqlite', new Map(), portable,
  );
  const crossRoot = await resultAssetObjectUrl(
    'job', owner, '../../bigscape/html_content/img/pixel.png', new Map(), portable,
  );
  const unresolvedCss = await rewriteCssResultUrls(
    'body{{background:url(../../public/clusterweave_public.sqlite)}}',
    'job',
    cssOwner,
    new Map(),
    portable,
  );
  let cssImportRejected = false;
  try {{
    await rewriteCssResultUrls('@import "../css/other.css";', 'job', owner, new Map(), portable);
  }} catch (error) {{ cssImportRejected = /@import/.test(String(error.message)); }}
  let declaredOversizeRejected = false;
  try {{
    await resultAssetObjectUrl(
      'job', owner, 'html_content/img/declared-huge.png', new Map(), portable,
    );
  }} catch (error) {{ declaredOversizeRejected = /16 MiB/.test(String(error.message)); }}
  const declaredHugeBodyWasRead = bodyReadPaths.some(path => path.endsWith('declared-huge.png'));
  let actualOversizeRejected = false;
  try {{
    await resultAssetObjectUrl(
      'job', owner, 'html_content/img/actual-huge.png', new Map(), portable,
    );
  }} catch (error) {{ actualOversizeRejected = /16 MiB/.test(String(error.message)); }}
  const declaredBudget = {{ declaredBytes: 0, actualBytes: 0 }};
  const actualBudget = {{ declaredBytes: 0, actualBytes: 0 }};
  const exactAssetLimit = 16 * 1024 * 1024;
  const declaredResponse = {{ headers: {{ get: () => String(exactAssetLimit) }} }};
  for (let index = 0; index < 4; index += 1) {{
    assertBigscapeAssetDeclaredSize(declaredResponse, declaredBudget);
    assertBigscapeAssetActualSize(exactAssetLimit, actualBudget);
  }}
  let aggregateDeclaredRejected = false;
  let aggregateActualRejected = false;
  try {{ assertBigscapeAssetDeclaredSize({{ headers: {{ get: () => '1' }} }}, declaredBudget); }}
  catch (error) {{ aggregateDeclaredRejected = /64 MiB/.test(String(error.message)); }}
  try {{ assertBigscapeAssetActualSize(1, actualBudget); }}
  catch (error) {{ aggregateActualRejected = /64 MiB/.test(String(error.message)); }}
  class FakeScript {{
    constructor(attrs) {{ this.attrs = {{ ...attrs }}; this.textContent = ''; this.removed = false; }}
    getAttribute(name) {{ return this.attrs[name] || ''; }}
    hasAttribute(name) {{ return Object.prototype.hasOwnProperty.call(this.attrs, name); }}
    removeAttribute(name) {{ delete this.attrs[name]; }}
    remove() {{ this.removed = true; }}
  }}
  const first = new FakeScript({{
    src: 'html_content/js/app.js',
    integrity: 'sha256-private',
    crossorigin: 'anonymous',
    referrerpolicy: 'origin',
    nonce: 'private-nonce',
  }});
  const second = new FakeScript({{ src: 'html_content/js/vendor.js', type: 'text/javascript' }});
  const kinetic = new FakeScript({{ src: 'html_content/js/kinetic-v5.1.0.min.js' }});
  const kineticCopy = new FakeScript({{ src: 'html_content/js/kinetic-v5.1.0-copy.min.js' }});
  const external = new FakeScript({{ src: 'https://example.invalid/remote.js' }});
  const scripts = [first, second, kinetic, kineticCopy, external];
  const doc = {{ querySelectorAll: selector => selector === 'script[src]' ? scripts : [] }};
  await inlineBigscapeResultScripts(doc, 'job', owner, portable);
  async function rejectedLocalScript(attrs) {{
    const script = new FakeScript(attrs);
    const singleDoc = {{ querySelectorAll: () => [script] }};
    try {{
      await inlineBigscapeResultScripts(singleDoc, 'job', owner, portable);
      return false;
    }} catch (error) {{
      return script.removed && !!String(error.message || '');
    }}
  }}
  const invalidModesRejected = (await Promise.all([
    rejectedLocalScript({{ src: 'html_content/js/app.js', async: '' }}),
    rejectedLocalScript({{ src: 'html_content/js/app.js', defer: '' }}),
    rejectedLocalScript({{ src: 'html_content/js/app.js', type: 'module' }}),
  ])).every(Boolean);
  const traversalScriptRejected = await rejectedLocalScript({{
    src: '../public/clusterweave_public.sqlite',
  }});
  const missingScriptRejected = await rejectedLocalScript({{
    src: 'html_content/js/missing.js',
  }});
  const kineticId = 'DDDDDDDDDDDDDDDDDDDDDD';
  const originalKinetic = payloads[kineticId].body;
  payloads[kineticId].body = '(1,eval)("this");window.KINETIC = true;';
  const kineticDriftRejected = await rejectedLocalScript({{
    src: 'html_content/js/kinetic-v5.1.0.min.js',
  }});
  payloads[kineticId].body = originalKinetic;
  const inlineText = first.textContent + second.textContent;
  process.stdout.write(JSON.stringify({{
    regularPreviewUsesObjectUrl: regularUrl === 'blob:parent-created',
    cssIsPortable: cssUrl.startsWith('data:text/css'),
    imageIsPortable: imageUrl.startsWith('data:image/png'),
    noBigscapeParentBlobUrls: parentBlobCalls === regularBlobCalls,
    noBlobReferenceCrossesSandbox: ![cssUrl, imageUrl].some(url => url.startsWith('blob:')),
    localScriptsInlinedInDomOrder: scripts[0] === first && scripts[1] === second
      && first.textContent.includes('ORDER.push("app")')
      && second.textContent.includes('ORDER.push("vendor")'),
    closingScriptEscaped: !/<\\/script/i.test(inlineText)
      && inlineText.includes('<' + String.fromCharCode(92) + '/script'),
    dangerousScriptAttrsRemoved: ['src', 'integrity', 'crossorigin', 'referrerpolicy', 'nonce']
      .every(name => !(name in first.attrs)) && !('src' in second.attrs),
    externalScriptRemoved: external.removed,
    sqliteTraversalRejected: sqliteTraversal === '' && crossRoot === ''
      && !fetchedPaths.some(path => path.includes('clusterweave_public.sqlite')),
    unresolvedCssStripped: unresolvedCss === 'body{{background:none}}'
      && !unresolvedCss.includes('..') && !unresolvedCss.includes('sqlite'),
    descriptorFetchesOnly: fetchedPaths.every(path => path.startsWith('artifact/bigscape/')),
    cssImportRejected,
    declaredOversizeRejectedBeforeRead: declaredOversizeRejected && !declaredHugeBodyWasRead,
    actualOversizeRejected,
    aggregateBudgetRejected: aggregateDeclaredRejected && aggregateActualRejected,
    invalidModesRejected,
    traversalScriptRejected,
    missingScriptRejected,
    kineticEvalShimRemoved: !kinetic.textContent.includes('eval')
      && (kinetic.textContent.match(/globalThis/g) || []).length === 2,
    unrelatedKineticNamePreserved: kineticCopy.textContent.split('(1,eval)').length - 1 === 2
      && !kineticCopy.textContent.includes('globalThis'),
    kineticDriftRejected,
  }}));
}})().catch(error => {{ console.error(error); process.exit(1); }});
"""
        result = subprocess.run(
            ["node", "-e", node_script],
            cwd=str(REPO_ROOT),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(
            json.loads(result.stdout),
            {
                "regularPreviewUsesObjectUrl": True,
                "cssIsPortable": True,
                "imageIsPortable": True,
                "noBigscapeParentBlobUrls": True,
                "noBlobReferenceCrossesSandbox": True,
                "localScriptsInlinedInDomOrder": True,
                "closingScriptEscaped": True,
                "dangerousScriptAttrsRemoved": True,
                "externalScriptRemoved": True,
                "sqliteTraversalRejected": True,
                "unresolvedCssStripped": True,
                "cssImportRejected": True,
                "descriptorFetchesOnly": True,
                "declaredOversizeRejectedBeforeRead": True,
                "actualOversizeRejected": True,
                "aggregateBudgetRejected": True,
                "invalidModesRejected": True,
                "traversalScriptRejected": True,
                "missingScriptRejected": True,
                "kineticEvalShimRemoved": True,
                "unrelatedKineticNamePreserved": True,
                "kineticDriftRejected": True,
            },
        )
        rewrite_block = js_text.split("async function rewriteHtmlResultAssets", 1)[1].split(
            "async function buildHtmlResultObjectUrl", 1
        )[0]
        self.assertIn("querySelectorAll('[srcset]')", rewrite_block)
        self.assertIn("querySelectorAll('form[action], [formaction]')", rewrite_block)
        self.assertIn("if (resultUrlShouldStayExternal(value)) {\n          el.removeAttribute(attr);", rewrite_block)
        self.assertIn("inlineBigscapeResultScripts(doc, jobId, htmlPath, assetOptions)", rewrite_block)
        self.assertIn("script-src 'unsafe-inline';", csp_line)
        self.assertNotIn("'unsafe-eval'", csp_line)
        self.assertNotIn("'wasm-unsafe-eval'", csp_line)
        compatibility_block = js_text.split("function rewriteBigscapeScriptForSandbox", 1)[1].split(
            "async function inlineBigscapeResultScripts", 1
        )[0]
        self.assertIn("kinetic-v5\\.1\\.0\\.min\\.js$", compatibility_block)
        self.assertIn("occurrences !== BIGSCAPE_KINETIC_GLOBAL_EVAL_SHIM_COUNT", compatibility_block)
        self.assertIn("replaceAll(BIGSCAPE_KINETIC_GLOBAL_EVAL_SHIM, 'globalThis')", compatibility_block)
        self.assertIn("connect-src 'none'", csp_line)
        self.assertIn("const BIGSCAPE_PREVIEW_SANDBOX = 'allow-scripts';", js_text)

    def test_frontend_job_fetches_prefer_job_read_token_over_stale_admin_token(self) -> None:
        ui_text = frontend_text()
        self.assertIn("function authHeadersFor(kind, jobId = null)", ui_text)
        self.assertIn("if (kind === 'admin')", ui_text)
        self.assertIn("activeOpsTab !== 'qa'", ui_text)
        self.assertIn("`tail=${QA_LOG_PAGE_SIZE}`", ui_text)
        self.assertIn("logs?since=${encodeURIComponent(logCursor)}", ui_text)
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
        self.assertIn('"GENOME_PARALLELISM": str(_cfg_int(settings, "genome_parallelism", 1))', text)

        self.assertIn('"ANTISMASH_RECORD_PARALLELISM": str(antismash_record_parallelism)', text)
        self.assertIn('if configured_antismash_shard_cpus > 0:', text)
        self.assertIn('env["ANTISMASH_SHARD_CPUS"] = str(configured_antismash_shard_cpus)', text)
        self.assertIn('if configured_antismash_legacy_cpus > 0:', text)
        self.assertIn('env["ANTISMASH_LEGACY_CPUS"] = str(configured_antismash_legacy_cpus)', text)

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

    def test_web_bgc_station_supports_all_accepted_accessible_genome_progress(self) -> None:
        static_dir = REPO_ROOT / "web" / "static"
        index_text = (static_dir / "index.html").read_text(encoding="utf-8")
        css_text = (static_dir / "assets" / "clusterweave.css").read_text(encoding="utf-8")
        js_text = (static_dir / "assets" / "clusterweave.js").read_text(encoding="utf-8")
        dna_text = (static_dir / "assets" / "workflow-dna-progress.js").read_text(encoding="utf-8")

        self.assertIn('id="bgc-genome-progress-layer"', index_text)
        self.assertIn('id="bgc-genome-progress-summary" role="status" aria-live="polite"', index_text)
        self.assertIn('id="bgc-genome-progress-grid" role="list"', index_text)
        self.assertNotIn("MAX_GENOME_PROGRESS_ITEMS", js_text)
        self.assertIn("function normalizeGenomeProgressItems(job)", js_text)
        self.assertIn("source.forEach((item, index) => {", js_text)
        self.assertIn("const items = Array.from(reconciled.values());", js_text)
        self.assertIn("function safeGenomeProgressText", js_text)
        self.assertIn("function genomeProgressStages", js_text)
        self.assertIn('class="genome-progress-meter-row"', js_text)
        self.assertIn('class="genome-progress-track" role="progressbar"', js_text)
        self.assertIn("function genomeProgressSnapshotPrefersPrevious", js_text)
        self.assertIn("function setBgcWorkflowAggregatePresentationSuspended", js_text)
        self.assertNotIn("function genomeMiniDnaSvg", js_text)
        self.assertNotIn("genome-mini-dna", js_text)
        self.assertIn('role="listitem"', js_text)
        self.assertIn("genomeProgressAllTerminal", js_text)
        self.assertIn("genomeProgressHandoff", js_text)
        self.assertIn("const GENOME_PROGRESS_ACTIVE_STATES", js_text)
        self.assertIn("${completeCount} complete · ${activeCount} active · ${queuedCount} queued", js_text)
        self.assertIn("errors: ${errorCount}", js_text)
        self.assertIn("setBgcWorkflowGenomeLayerSuspended(genomeLayerActive);", js_text)
        self.assertIn("if (bgcWorkflowDna) bgcWorkflowDna.setProgress(payload.progress, payload);", js_text)
        self.assertIn("grid.dataset.renderKey", js_text)
        self.assertIn("strip.dataset.renderKey", js_text)
        self.assertIn("renderGenomeProgressLayer(payload);", js_text)
        self.assertEqual(js_text.count("createWorkflowDnaProgress({"), 1)
        hidden_dna = css_text.split(
            ".bgc-workflow-station.has-genome-progress:not(.is-genome-progress-handoff) .dna-progress-region {",
            1,
        )[1].split("}", 1)[0]
        self.assertIn("opacity: 0", hidden_dna)
        self.assertIn("visibility: hidden", hidden_dna)
        self.assertIn("pointer-events: none", hidden_dna)
        self.assertIn(".genome-progress-layer.is-aggregate-handoff", css_text)
        self.assertIn(".genome-progress-row", css_text)
        self.assertIn(".is-aggregate-handoff.has-terminal-warning", css_text)
        self.assertIn(".genome-progress-row:not(.is-warning)", css_text)
        self.assertIn("> .workflow-tool-status", css_text)
        self.assertNotIn(".genome-mini-card", css_text)
        self.assertIn("@media (prefers-reduced-motion: reduce)", css_text)
        self.assertIn("transition-delay: 0s !important;", css_text)
        self.assertIn("this.geometryDirty = true;", dna_text)
        self.assertIn("if (this.disposed || this.suspended) return;", dna_text)
        self.assertIn("!this.reducedMotion.matches", dna_text)
        self.assertIn("this.renderFrame(this.lastFrameTime, true);", dna_text)
        self.assertIn("helixPoint(index, offset, target)", dna_text)
        self.assertNotIn("new THREE.Vector3().subVectors", dna_text)

    def test_web_result_tabs_do_not_collide_with_package_download(self) -> None:
        static_dir = REPO_ROOT / "web" / "static"
        css_text = (static_dir / "assets" / "clusterweave.css").read_text(encoding="utf-8")
        js_text = (static_dir / "assets" / "clusterweave.js").read_text(encoding="utf-8")

        complete_strip = css_text.split(
            'body[data-job-state="complete"] .result-output-strip {', 1
        )[1].split("}", 1)[0]
        complete_grid = css_text.split(
            'body[data-job-state="complete"] .result-grid {', 1
        )[1].split("}", 1)[0]
        self.assertIn("display: grid;", complete_strip)
        self.assertIn("grid-template-columns: minmax(0, 1fr) auto;", complete_strip)
        self.assertIn("overflow: hidden;", complete_strip)
        self.assertIn("display: grid;", complete_grid)
        self.assertIn(
            "grid-template-columns: repeat(auto-fit, minmax(4.65rem, 1fr));",
            complete_grid,
        )
        self.assertIn("overflow: visible;", complete_grid)
        self.assertNotIn("overflow-x: auto;", complete_grid)
        self.assertIn('@media (max-width: 760px)', css_text)
        mobile_css = css_text.split('@media (max-width: 760px)', 1)[1]
        self.assertIn(
            "grid-template-columns: repeat(auto-fit, minmax(4.35rem, 1fr));",
            mobile_css,
        )
        self.assertIn('body[data-job-state="complete"] .output b { white-space: normal; }', mobile_css)
        self.assertIn("width: 100%;", css_text)
        self.assertNotIn("FUNBGCEX · FUNGI ONLY", js_text)
        self.assertIn(
            "Per-genome FunBGCeX HTML views for fungal genomes only; bacterial genomes are not applicable.",
            js_text,
        )

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
        self.assertIn("async function validateAccessCode(value)", js_text)
        self.assertIn("openOpsPanel({ tab: 'jobs', focusPanel: true", js_text)
        self.assertIn('role="tablist" aria-label="Diagnostics navigation"', index_text)
        for tab in ["ops-tab-jobs", "ops-tab-worker", "ops-tab-qa", "ops-tab-rerun"]:
            self.assertIn(f'id="{tab}"', index_text)
        self.assertIn('body[data-access="public"] .admin-only', css_text)
        self.assertIn('body[data-ops-panel="collapsed"] .ops-side-panel', css_text)
        self.assertIn('.ops-panel-toggle', css_text)
        self.assertNotIn('favicon-cw.svg', index_text)
        self.assertFalse((static_dir / "assets" / "favicon-cw.svg").exists())
        self.assertIn('.ops-side-panel.admin-drawer', css_text)
        self.assertNotIn('body[data-results-dashboard="open"][data-management-view="closed"] .ops-side-panel { display: none !important; }', css_text)

    def test_worker_bootstrap_tracks_ncbi_cli_asset(self) -> None:
        entrypoint = (REPO_ROOT / "web" / "entrypoint-worker.sh").read_text(encoding="utf-8")
        ui_text = (REPO_ROOT / "web" / "static" / "assets" / "clusterweave.js").read_text(encoding="utf-8")
        runtime = (REPO_ROOT / "web" / "runtime_capabilities.py").read_text(encoding="utf-8")
        compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn('AUTO_INSTALL_NCBI_CLI="${AUTO_INSTALL_NCBI_CLI:-1}"', entrypoint)
        self.assertIn('run_with_progress "ncbi_cli" "Installing NCBI Datasets CLI"', entrypoint)
        self.assertIn('NCBI_CLI_ROOT: "${NCBI_CLI_ROOT:-/data/software/ncbi_cli}"', compose)
        self.assertIn("{ key: 'ncbi_cli', label: 'NCBI Datasets CLI' }", ui_text)
        self.assertIn("ncbi_datasets", runtime)
        self.assertIn("NCBI Datasets CLI unavailable for accession retrieval", runtime)

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
        self.assertIn("fungi_big_scape_multipanel.svg", text)
        self.assertIn("bacteria_big_scape_multipanel.svg", text)
        self.assertIn("big_scape_multipanel.svg", text)
        self.assertNotIn("gcf_calls_by_tool_category.svg", text)
        self.assertNotIn("bgc_calls_by_tool_category.svg", text)
        self.assertNotIn("bigscape_network.svg", text)
        self.assertIn("const downloadHref = resultHref(jobId, f, { download: true })", text)
        self.assertIn("<th>File / Result</th>", text)
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
        self.assertIn('<span class="file-path-link">${escapeHtml(detail)}</span>', text)
        self.assertIn(
            "const detail = descriptor ? resultCategoryLabel(descriptor.category) : normalizedResultPath(f);",
            text,
        )
        self.assertNotIn('<span class="file-path-link">${escapeHtml(path)}</span>', text)
        self.assertNotIn('<a class="file-path-link"', text)
        self.assertIn("resultHref(jobId, f, { download: true })", text)

    def test_web_upload_supports_manual_accession_entry(self) -> None:
        html_text = (REPO_ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
        js_text = (REPO_ROOT / "web" / "static" / "assets" / "clusterweave.js").read_text(encoding="utf-8")
        self.assertIn('id="manual-accessions"', html_text)
        self.assertIn("function manualAccessionLines()", js_text)
        self.assertIn("const MANUAL_ACCESSIONS_FILENAME = 'manual_accessions.txt'", js_text)
        self.assertIn("manualLines.join('\\n') + '\\n'", js_text)
        self.assertIn("new File([manualAccessionText], MANUAL_ACCESSIONS_FILENAME", js_text)
        self.assertIn("input source(s) ready", js_text)
        self.assertIn("setBrutalInputNotice('submission', '')", js_text)
        self.assertIn("setBrutalInputNotice('submission', message)", js_text)

        # The normalized staging filename is an implementation detail: direct
        # accession entry remains an accession card in every public-facing view.
        self.assertNotIn("manual_accessions.txt", html_text)
        self.assertNotIn("Manual entry &rarr;", js_text)
        self.assertNotIn("const manualItem =", js_text)
        self.assertNotIn("MANUAL_ACCESSIONS_FILENAME} generated", js_text)
        self.assertNotIn("accessionSources.push({ name: MANUAL_ACCESSIONS_FILENAME", js_text)

    def test_web_both_scope_uses_microbe_copy_and_project_placeholder(self) -> None:
        js_text = (REPO_ROOT / "web" / "static" / "assets" / "clusterweave.js").read_text(encoding="utf-8")
        self.assertIn("hero.setAttribute('aria-label', 'Discover the hidden potential of microbes')", js_text)
        self.assertIn("<span>of</span><span>microbes</span>", js_text)
        self.assertIn("scope === 'both' ? 'microbial_survey'", js_text)
        self.assertNotIn("scope === 'both' ? 'genome_survey'", js_text)
        self.assertNotIn("Discover the hidden potential of fungi and bacteria", js_text)

    def test_atlas_and_clinker_default_to_twenty_without_expanding_other_sets(self) -> None:
        html_text = (REPO_ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
        js_text = (REPO_ROOT / "web" / "static" / "assets" / "clusterweave.js").read_text(encoding="utf-8")
        app_text = (REPO_ROOT / "web" / "app.py").read_text(encoding="utf-8")
        canonical_text = (REPO_ROOT / "web" / "canonical_pipeline.py").read_text(encoding="utf-8")
        clinker_text = (REPO_ROOT / "run_clinker.sh").read_text(encoding="utf-8")

        self.assertIn('id="clinker-max-regions" value="20"', html_text)
        self.assertIn('id="shortlist-limit" value="12"', html_text)
        self.assertIn('id="shared-family-stage-limit" value="12"', html_text)
        self.assertIn("ATLAS_STAGE_LIMIT=${document.getElementById('clinker-max-regions').value || '20'}", js_text)
        self.assertIn("fd.append('atlas_stage_limit', document.getElementById('clinker-max-regions').value || '20')", js_text)
        self.assertIn("set('clinker-max-regions', 20)", js_text)
        self.assertIn('fields.get("clinker_max_regions", ["20"])', app_text)
        self.assertIn('fields.get("atlas_stage_limit", ["20"])', app_text)
        self.assertIn('"ATLAS_STAGE_LIMIT": str(_cfg_int(settings, "atlas_stage_limit", 20))', canonical_text)
        self.assertIn('ATLAS_STAGE_LIMIT="${ATLAS_STAGE_LIMIT:-20}"', clinker_text)

        self.assertIn("SHORTLIST_LIMIT=${document.getElementById('shortlist-limit').value || '12'}", js_text)
        self.assertIn("SHARED_FAMILY_STAGE_LIMIT=${document.getElementById('shared-family-stage-limit').value || '12'}", js_text)
        self.assertIn('SHORTLIST_LIMIT="${SHORTLIST_LIMIT:-12}"', clinker_text)
        self.assertIn('SHARED_FAMILY_STAGE_LIMIT="${SHARED_FAMILY_STAGE_LIMIT:-12}"', clinker_text)
        self.assertIn('"SHORTLIST_LIMIT": str(_cfg_int(settings, "shortlist_limit", 12))', canonical_text)
        self.assertRegex(
            canonical_text,
            r'"SHARED_FAMILY_STAGE_LIMIT": str\(_cfg_int\(settings, "shared_family_stage_limit", (?:12|_cfg_int\(settings, "shortlist_limit", 12\))\)\)',
        )

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

    def test_web_tree_tool_credits_use_the_existing_credit_card_layout(self) -> None:
        html_text = (REPO_ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('class="tool-credit-tabs" role="tablist"', html_text)
        self.assertIn('id="tool-credit-web-tab"', html_text)
        self.assertIn('onclick="switchToolCreditTab(\'web\')"', html_text)
        self.assertIn('id="tool-credit-local-tab"', html_text)
        self.assertIn('onclick="switchToolCreditTab(\'local\')"', html_text)
        self.assertIn('id="tool-credit-local-panel" role="tabpanel"', html_text)
        for tool in [
            "NCBI Datasets + Dataformat", "NCBI GenBank + RefSeq", "NCBI Taxonomy",
            "antiSMASH", "Prodigal", "FunBGCeX", "funannotate", "BUSCO", "AUGUSTUS",
            "DIAMOND", "HMMER", "Biopython", "BiG-SCAPE", "FastTree", "clinker",
            "MIBiG", "Pfam", "BRAKER3", "GeneMark", "NPLinker", "GNPS", "MassIVE",
            "PODP", "MAFFT", "IQ-TREE 2", "ETE 4", "trimAl", "CairoSVG",
        ]:
            self.assertRegex(
                html_text,
                rf'<a class="tool-credit-link"[^>]+href="https?://[^"]+"[^>]*>{re.escape(tool)}<sup>[^<]+</sup></a>',
                tool,
            )
        for tool in ["MAFFT", "IQ-TREE 2", "ETE 4", "trimAl"]:
            self.assertNotRegex(html_text, rf'{re.escape(tool)}[^<]*<small')

    def test_web_public_impact_audit_uses_redacted_aggregate_status(self) -> None:
        text = frontend_text()
        for element_id in ["public-impact-server", "public-impact-running", "public-impact-queued", "public-impact-completed"]:
            self.assertIn(f'id="{element_id}"', text)
        self.assertIn("startPublicImpactPolling()", text)
        self.assertIn("fetchSystemStatus({ renderWorker: false })", text)

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
        self.assertIn('role="log" aria-live="polite" aria-relevant="additions text" aria-atomic="false"', text)
        self.assertIn("function publicQaEventLine(event)", text)
        self.assertIn("function renderPublicQaLog(job)", text)
        self.assertIn(".log-line.stage", text)

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
        self.assertIn("resultDownloadLink(jobId, bigscape.database, 'Download sanitized SQLite')", text)
        self.assertIn("The raw SQLite database is excluded from public results", text)
        bigscape_fallback = text.split("if (!bigscape.database) {", 1)[1].split(
            "const jsJobId", 1
        )[0]
        self.assertIn('class="artifact-row result-tool-row"', bigscape_fallback)
        self.assertNotIn('class="artifact-row is-compact result-tool-row"', bigscape_fallback)
        self.assertNotIn("window.CLUSTERWEAVE_BIGSCAPE_DATABASE_AUTH", text)
        self.assertNotIn("const dbUrl = resultHref(jobId, databasePath);", text)
        self.assertNotIn("const dbAuth = authHeadersFor('job', jobId).Authorization || '';", text)
        self.assertIn("bigscapeViewerFetch(jobId)", text)
        self.assertNotIn("resultFetch(jobId, databasePath)", text)
        self.assertIn("bigscape.viewerDatabase", text)
        self.assertIn("isBigscapeViewerDatabaseArtifact(databasePath)", text)
        self.assertIn("const BIGSCAPE_BROWSER_DATABASE_MAX_BYTES = 64 * 1024 * 1024;", text)
        self.assertIn("validatedBigscapeDatabaseBuffer(dbResp)", text)
        self.assertIn("function receiveBuffer()", text)
        self.assertIn("frame.contentWindow.postMessage", text)
        self.assertIn("window.CLUSTERWEAVE_BIGSCAPE_DATABASE_BYTES = buffer.byteLength || 0;", text)
        self.assertNotIn("dbResp.blob()", text)
        autoload_block = text.split("async function autoloadDatabase()", 1)[1].split("window.CLUSTERWEAVE_BIGSCAPE_AUTOLOAD_DATABASE", 1)[0]
        self.assertNotIn("attachInputFile(buffer);", autoload_block)
        self.assertIn("function renderMarkdownBody(text)", text)
        app_text = (REPO_ROOT / "web" / "app.py").read_text(encoding="utf-8")
        self.assertIn("def _send_file(", app_text)
        self.assertIn("shutil.copyfileobj(handle, self.wfile, length=1024 * 1024)", app_text)
        self.assertIn(
            "except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):",
            app_text,
        )
        self.assertIn("authorized_file = authorize_direct_result_file(job, base_dir, rel_path)", app_text)
        self.assertIn("expected_identity=expected_identity", app_text)
        self.assertNotIn("self._send_text(HTTPStatus.OK, result_file_mime(full), full.read_bytes(), headers)", app_text)
        self.assertIn("function condensedMarkdownBodyText(text)", text)
        self.assertIn("function summaryTopCount(text)", text)
        self.assertIn("summaryCondensedTitle(path, text, count)", text)
        self.assertIn("summary-condensed-title", text)
        self.assertIn("summary-markdown-body", text)
        self.assertIn("source\\s+summary", text)
        self.assertNotIn('id="summary-reader-source"', text)
        self.assertIn("summary-subtabs", text)
        self.assertIn("ALL BGCs", text)
        self.assertIn("all_tools_bgc_comparison.csv", text)
        self.assertIn("function updateAllBgcFilter", text)
        self.assertIn("function sortAllBgcTable", text)
        self.assertIn("function refreshAllBgcRows", text)
        self.assertIn("genome: ''", text)
        self.assertIn("const extensionOrder = kind === 'atlas'", text)
        self.assertIn("function renderAtlasSummary", text)
        self.assertIn("DATASET-WIDE FAMILY ATLAS", text)
        self.assertNotIn("changeAllBgcPage", text)
        self.assertNotIn("summary-pagination", text)
        self.assertLess(text.index("const ALL_BGC_COLUMNS"), text.index("function preferredSummaryColumnIndexes"))
        self.assertLess(text.index("async function loadAllBgcReaderFile"), text.index("function preferredSummaryColumnIndexes"))
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
        self.assertIn("const base = apiUrl(`api/results/${encodeURIComponent(runId)}/artifacts/", text)
        self.assertIn("api/results/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(ownerId)}/resolve", text)
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

    def test_web_language_contract_keeps_public_and_admin_purpose_clear(self) -> None:
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
        self.assertLess(ui_text.index('id="target-genome-toggle"'), ui_text.index('id="brutal-ecology-toggle"'))
        self.assertLess(ui_text.index('id="brutal-ecology-toggle"'), ui_text.index('id="project-name"'))
        self.assertLess(ui_text.index('id="project-name"'), ui_text.index('id="email-notification-panel"'))
        self.assertLess(ui_text.index('id="email-notification-panel"'), ui_text.index('id="target-genome"'))
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
        self.assertIn('EMAIL OFF - server mail not configured', ui_text)

    def test_web_submission_gates_are_visible_before_post(self) -> None:
        html_text = (REPO_ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
        css_text = (REPO_ROOT / "web" / "static" / "assets" / "clusterweave.css").read_text(encoding="utf-8")
        js_text = (REPO_ROOT / "web" / "static" / "assets" / "clusterweave.js").read_text(encoding="utf-8")

        self.assertIn("function submissionsPausedForPublic()", js_text)
        self.assertIn("SUBMISSIONS PAUSED - QUEUE LOCKED BY OPERATOR", js_text)
        self.assertIn("Queue gate: paused before upload.", js_text)
        self.assertIn("FORMAT OK - NCBI CHECK PENDING", js_text)
        self.assertIn("input.setAttribute('aria-invalid', showInvalid ? 'true' : 'false')", js_text)
        self.assertIn(':where(a, button, input, textarea, select, summary, [role="button"], [tabindex]):focus-visible', css_text)
        self.assertIn("--blue:", css_text)
        self.assertIn("--muted:", css_text)
        self.assertIn(".input-log-note", css_text)

        self.assertNotIn("PUBLIC DATA ONLY - confirm these inputs are public or releasable.", js_text)
        self.assertNotIn("NAME THE RUN BEFORE LAUNCH", js_text)
        self.assertNotIn("Name the run before launch", js_text)
        self.assertIn('class="project-label-stack" for="project-name"', html_text)
        self.assertIn('<span class="required-flag" id="project-name-required">REQUIRED</span>', html_text)
        self.assertRegex(css_text, r"\.project-name-card\s*\{[^}]*background:\s*var\(--yellow-soft\)")
        self.assertRegex(css_text, r"\.required-flag\s*\{[^}]*display:\s*(?:block|inline-flex)[^}]*background:\s*var\(--acid\)")

        self.assertIn('class="submit-button-shell is-project-locked" id="submit-button-shell"', html_text)
        self.assertIn('id="run-btn" type="button" onclick="startAnalysis()" disabled>Validate</button>', html_text)
        self.assertIn("function submissionValidationSignature()", js_text)
        self.assertIn("function syncRunButtonPresentation", js_text)
        self.assertIn("button.textContent = submitReady ? 'Submit run' : 'Validate'", js_text)
        self.assertIn("Validation passed. Review the inputs, then select Submit run.", js_text)
        self.assertIn("#run-btn.is-validation-pending", css_text)
        self.assertIn("#run-btn.is-submit-ready", css_text)
        self.assertIn(".submit-button-shell.is-project-locked .submit-lock-overlay", css_text)
        self.assertRegex(
            css_text,
            r"\.submit-lock-overlay\s*\{[^}]*background:\s*(?:white|#fff(?:fff)?|var\(--panel\))",
        )
        project_handler_start = js_text.index("document.getElementById('project-name')?.addEventListener('input'")
        project_handler_end = js_text.index("document.getElementById('target-genome')?.addEventListener", project_handler_start)
        self.assertIn("renderFileList()", js_text[project_handler_start:project_handler_end])

        self.assertIn("function uploadedInputRequiresAcknowledgment()", js_text)
        self.assertIn("function syncDataUseAcknowledgment()", js_text)
        self.assertIn("panel.hidden = !required", js_text)
        self.assertIn('id="data-use-ack-panel" hidden inert aria-hidden="true"', html_text)
        self.assertIn('<span><b>PUBLIC DATA ONLY</b></span>', html_text)
        self.assertNotIn('confirm uploaded inputs are public or releasable', html_text)
        self.assertLess(html_text.index('id="upload-limit-note"'), html_text.index('id="data-use-ack-panel"'))
        self.assertLess(html_text.index('id="data-use-ack-panel"'), html_text.index('id="file-list"'))

        self.assertIn('<div class="input-log-drawer" id="input-log-drawer" hidden>', html_text)
        self.assertIn('class="submit-feedback-rail"', html_text)
        self.assertLess(html_text.index('id="data-use-ack-panel"'), html_text.index('class="submit-feedback-rail"'))
        self.assertLess(html_text.index('class="submit-feedback-rail"'), html_text.index('id="input-log-drawer"'))
        self.assertLess(html_text.index('id="run-btn"'), html_text.index('id="input-log-drawer"'))
        self.assertLess(html_text.index('id="input-log-drawer"'), html_text.index('id="upload-status"'))
        self.assertIn("const BRUTAL_ACCESSION_PREVIEW_ROWS = 6", js_text)
        self.assertIn("row.classList.toggle('is-concealed', !presented)", js_text)

    def test_web_target_and_ecology_controls_are_balanced_and_uploads_are_selectable(self) -> None:
        html_text = (REPO_ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
        css_text = (REPO_ROOT / "web" / "static" / "assets" / "clusterweave.css").read_text(encoding="utf-8")
        js_text = (REPO_ROOT / "web" / "static" / "assets" / "clusterweave.js").read_text(encoding="utf-8")

        self.assertIn('class="button-pair target-ecology-controls input-config-rail"', html_text)
        self.assertIn('id="target-genome-toggle"', html_text)
        self.assertIn('id="brutal-ecology-toggle"', html_text)
        self.assertRegex(
            css_text,
            r"\.button-pair\.target-ecology-controls\s*\{[^}]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)",
        )
        self.assertRegex(
            css_text,
            r"\.target-ecology-controls \.config-button\s*\{[^}]*min-height:\s*54px",
        )
        self.assertRegex(
            css_text,
            r"\.target-ecology-controls \.config-button\s*\{[^}]*white-space:\s*nowrap",
        )

        self.assertIn('data-target-genome="', js_text)
        self.assertNotIn('data-target-select', js_text)
        self.assertNotIn('file-target-select', js_text)
        self.assertIn('class="eco-button file-eco-button" type="button"', js_text)
        self.assertIn("function openUploadedGenomeEcoPicker(button)", js_text)
        self.assertIn("uploadCard.classList.toggle('show-ecology', enabled)", js_text)
        self.assertIn(".file-item[data-target-genome]", js_text)
        self.assertRegex(js_text, r"\bfileList\??\.addEventListener\('click'")

    def test_web_ecology_label_table_uses_controlled_public_inputs(self) -> None:
        text = frontend_text()
        html_text = (REPO_ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="ecology-label-panel"', text)
        self.assertIn('id="brutal-ecology-toggle"', text)
        self.assertIn('id="run-ecology"', text)
        self.assertIn('id="metadata-table-body"', text)
        self.assertLess(html_text.index('id="upload-limit-note"'), html_text.index('id="data-use-ack-panel"'))
        self.assertLess(html_text.index('id="data-use-ack-panel"'), html_text.index('id="file-list"'))
        self.assertLess(html_text.index('id="data-use-ack-panel"'), html_text.index('id="brutal-ecology-toggle"'))
        self.assertIn('PUBLIC DATA ONLY', html_text)
        self.assertIn('id="data-use-ack" onchange="renderFileList()"', html_text)
        self.assertIn('id="data-use-ack-panel" hidden inert aria-hidden="true"', html_text)
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

    def test_container_images_include_shared_genbank_readiness_module(self) -> None:
        web_dockerfile = (REPO_ROOT / "Dockerfile.web").read_text(encoding="utf-8")
        worker_dockerfile = (REPO_ROOT / "Dockerfile.worker").read_text(encoding="utf-8")
        expected = "COPY web/genbank_readiness.py /app/genbank_readiness.py"
        self.assertIn(expected, web_dockerfile)
        self.assertIn(expected, worker_dockerfile)
        attestation_expected = "COPY web/result_attestation.py /app/result_attestation.py"
        self.assertIn(attestation_expected, web_dockerfile)
        self.assertIn(attestation_expected, worker_dockerfile)
        self.assertIn("COPY bin/backfill_result_attestations.py /app/backfill_result_attestations.py", web_dockerfile)
        viewer_expected = "COPY web/bigscape_public_db.py /app/bigscape_public_db.py"
        self.assertIn(viewer_expected, web_dockerfile)
        self.assertIn(viewer_expected, worker_dockerfile)

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
        profile = REPO_ROOT / "profiles" / "release_v1.0.0.env"
        self.assertTrue(profile.exists())
        text = profile.read_text(encoding="utf-8")
        self.assertIn("PROJECT_NAME=clusterweave_v1_0_0", text)
        self.assertIn("ANALYSIS_SCOPE=both", text)
        self.assertIn("CAPTURE_EXTERNAL_ARTIFACTS=1", text)
        self.assertIn("AUTO_DOWNLOAD_PFAM=0", text)
        self.assertIn("AUTO_DOWNLOAD_FASTTREE=0", text)
        self.assertIn("INSTALL_CLINKER_SIF=0", text)

    def test_release_metadata_and_runtime_acquisition_are_immutable(self) -> None:
        pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('version = "1.0.1"', pyproject)

        braker_pin = (
            "teambraker/braker3:v3.0.7.6@sha256:"
            "5f8b3c508a9fe1bbc2e9a74dcc013eeed82f91dd5945adca7823514d9c8aecf8"
        )
        fasttree_commit = "29c5e62fbcd93230ee325f9c6a17b81f00e3c72a"
        fasttree_sha256 = (
            "55a9d997813aae2208bd4c2081bfa690e0ecdba2d6c491805d8689415c43e38e"
        )
        annotation = (
            REPO_ROOT / "run_annotation_and_detection.sh"
        ).read_text(encoding="utf-8")
        bigscape = (REPO_ROOT / "run_bigscape.sh").read_text(encoding="utf-8")
        profile = (
            REPO_ROOT / "profiles" / "release_v1.0.0.env"
        ).read_text(encoding="utf-8")
        capture = (
            REPO_ROOT / "bin" / "capture_external_artifacts.py"
        ).read_text(encoding="utf-8")

        for text in (annotation, profile, capture):
            self.assertIn(braker_pin, text)
            self.assertNotIn("teambraker/braker3:latest", text)
        for text in (bigscape, profile, capture):
            self.assertIn(fasttree_commit, text)
            self.assertNotIn("fasttree/raw/main/FastTree", text.lower())
        self.assertIn(fasttree_sha256, bigscape)
        self.assertIn(fasttree_sha256, profile)
        self.assertIn("verify_fasttree_checksum", bigscape)


if __name__ == "__main__":
    unittest.main()
