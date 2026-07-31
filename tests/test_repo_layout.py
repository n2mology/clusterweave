import base64
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
        static_dir / "assets" / "result-reader-boundary.js",
        static_dir / "assets" / "job-lifecycle-boundary.js",
        static_dir / "assets" / "clusterweave.js",
        static_dir / "assets" / "intake-taxon-boundary.js",
        static_dir / "assets" / "diagnostics-access-boundary.js",
        static_dir / "assets" / "motion-boundary.js",
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
            "scripts/ncbi/rename_ncbi_genomes.py",
            "scripts/ncbi/flatten_ncbi_genomes.sh",
            "bin/capture_external_artifacts.py",
            "bin/compact_antismash_shard.py",
            "bin/annotation_input.py",
            "bin/annotation_genbank.py",
            "bin/annotation_runtime.py",
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
        genbank_helper = (REPO_ROOT / "bin" / "annotation_genbank.py").read_text(
            encoding="utf-8"
        )
        compactor = (REPO_ROOT / "bin" / "compact_antismash_shard.py").read_text(
            encoding="utf-8"
        )
        clinker_stage = (REPO_ROOT / "bin" / "stage_clinker_panels.py").read_text(encoding="utf-8")

        self.assertIn('ANTISMASH_RECORD_PARALLELISM="${ANTISMASH_RECORD_PARALLELISM:-1}"', text)
        self.assertIn('ANTISMASH_SHARD_CPUS="${ANTISMASH_SHARD_CPUS:-}"', text)
        self.assertIn('ANTISMASH_LEGACY_CPUS="${ANTISMASH_LEGACY_CPUS:-}"', text)
        self.assertIn('ANTISMASH_RETAIN_SHARD_WORK="${ANTISMASH_RETAIN_SHARD_WORK:-0}"', text)
        self.assertIn('ANTISMASH_SHARD_COMPACTOR="${ANTISMASH_SHARD_COMPACTOR:-${SCRIPT_DIR}/bin/compact_antismash_shard.py}"', text)
        self.assertIn('"${ANNOTATION_GENBANK_HELPER}"', record_ids)
        self.assertIn("list-record-ids", record_ids)
        self.assertIn("def list_record_ids(", genbank_helper)
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
        helper_runtime = text.split("repository_helper_python_exec() {", 1)[1].split("\n}", 1)[0]
        self.assertIn('if [[ "${ENGINE}" == "docker" ]]', helper_runtime)
        self.assertIn('"$(resolve_python_cmd)" "$@"', helper_runtime)
        antismash_adapter = text.split("antismash_input_python_exec() {", 1)[1].split("\n}", 1)[0]
        self.assertEqual(
            antismash_adapter.strip(), 'repository_helper_python_exec "$@"'
        )
        self.assertNotIn('funbgcex_python_exec "${ANNOTATION_GENBANK_HELPER}"', text)
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
        self.assertIn('"${ANTISMASH_SHARD_COMPACTOR}"', merge_json)
        self.assertIn("--merge-output", merge_json)
        self.assertIn("def merge_shards(", compactor)
        self.assertEqual(compactor.count("def _target_record("), 1)
        self.assertIn('return antismash_root / genome / f"{antismash_region}.gbk"', clinker_stage)
        self.assertIn("tr -c 'A-Za-z0-9._-' '_'", text)
        self.assertIn('find "${shard_dirs[${index}]}" -type f -name \'*region*.gbk\'', sharded)
        self.assertIn('render_antismash_shard_web_bundle', sharded)
        self.assertIn('write_antismash_shard_index "${genome_id}" "${ant_out}"', sharded)
        self.assertIn('"${assembled_count}" -gt 0', sharded)
        self.assertNotIn('touch "${ant_out}/.done"', sharded)
        self.assertIn('mark_antismash_done "${ant_out}"', process_body)
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

    def test_antismash_done_requires_complete_browseable_output(self) -> None:
        text = (REPO_ROOT / "run_annotation_and_detection.sh").read_text(encoding="utf-8")
        validators = text.split("antismash_outputs_valid() {", 1)[1].split(
            "funbgcex_outputs_valid()", 1
        )[0]
        done = text.split("antismash_done() {", 1)[1].split(
            "mark_antismash_done()", 1
        )[0]
        self.assertIn('[[ -f "${outdir}/.done" ]] || return 1', done)
        self.assertIn('antismash_outputs_valid "${outdir}"', done)
        self.assertIn("[[ -s \"${outdir}/index.html\" ]] || return 1", validators)
        self.assertIn("-name \"regions.js\"", validators)
        self.assertIn("-name \"*.antismash.json\"", validators)
        self.assertNotIn("*region*.gbk", validators)
        self.assertNotIn("##antiSMASH-Data-START##", validators)

    def test_annotation_completion_markers_require_valid_outputs(self) -> None:
        text = (REPO_ROOT / "run_annotation_and_detection.sh").read_text(encoding="utf-8")
        funbgcex = text.split("funbgcex_outputs_valid() {", 1)[1].split(
            "# GBK diagnostics/filtering", 1
        )[0]
        self.assertIn('[[ -f "${outdir}/.done" ]] || return 1', funbgcex)
        self.assertIn('-name "allBGCs.csv"', funbgcex)
        self.assertNotIn('funbgcex_in.log', funbgcex)
        self.assertIn('&& mark_funbgcex_done "${fbx_out}"', text)
        self.assertIn('&& mark_antismash_done "${ant_out}"', text)
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
        completion_helpers = "antismash_outputs_valid() {" + text.split(
            "antismash_outputs_valid() {", 1
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

            partial_cases = [
                ("mark_antismash_done", antismash, antismash / "index.html"),
                ("mark_funbgcex_done", funbgcex, funbgcex / "allBGCs.csv"),
            ]
            for function_name, outdir, required_output in partial_cases:
                required_output.write_text("", encoding="utf-8")
                (outdir / ".done").touch()
                command = completion_helpers + f'\n{function_name} "$1"'
                marked = subprocess.run(
                    ["bash", "-c", command, "completion-test", str(outdir)],
                    cwd=str(REPO_ROOT),
                    check=False,
                )
                self.assertNotEqual(marked.returncode, 0, function_name)
                self.assertFalse((outdir / ".done").exists(), function_name)

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
            "visuals/ClusterWeave_workflow.svg",
            "visuals/logo_black.svg",
            "docs/INSTALL.md",
            "docs/REPRODUCIBILITY.md",
            "docs/WEB_RUNTIME.md",
            "examples/README.md",
        ]:
            self.assertTrue((REPO_ROOT / rel).exists(), rel)
        for rel in ["package.json", "package-lock.json", "tests/browser/README.md"]:
            self.assertFalse((REPO_ROOT / rel).exists(), rel)

    def test_public_release_copy_excludes_private_gate_status(self) -> None:
        release_docs = [
            "README.md",
            "docs/BEGINNER_SETUP.md",
            "CHANGELOG.md",
            "SECURITY.md",
            "docs/INSTALL.md",
            "docs/WEB_RUNTIME.md",
            "examples/README.md",
            "examples/fungi_only/README.md",
            "examples/mixed/README.md",
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
        ]:
            with self.subTest(hosted_status=rel):
                self.assertIn("coming soon", texts[rel])

        self.assertIn("web-hosted access", texts["README.md"])
        for rel in [
            "docs/BEGINNER_SETUP.md",
            "SECURITY.md",
            "docs/INSTALL.md",
            "docs/WEB_RUNTIME.md",
        ]:
            with self.subTest(project_hosted_status=rel):
                self.assertIn("project-hosted access", texts[rel])

        for unavailable_claim in [
            "web-hosted access: **available",
            "project-hosted access is available",
            "project-hosted portal address",
            "project-hosted portal and local interface",
            "provided by the clusterweave team",
        ]:
            with self.subTest(unavailable_claim=unavailable_claim):
                self.assertNotIn(unavailable_claim, combined)

    def test_owner_only_operator_agreement_is_not_public(self) -> None:
        self.assertFalse((REPO_ROOT / "web/OPERATOR_AGREEMENT.md").exists())

    def test_private_browser_qa_categories_are_not_ignored(self) -> None:
        gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        dockerignore = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8")
        for category in [
            "node_modules/",
            "test-results/",
            "playwright-report/",
            "blob-report/",
        ]:
            with self.subTest(category=category):
                self.assertNotIn(category, gitignore)
                self.assertNotIn(category, dockerignore)
        for category in ["credentials/", "*.orig"]:
            with self.subTest(category=category):
                self.assertIn(category, gitignore)
                self.assertIn(category, dockerignore)

        with tempfile.TemporaryDirectory() as tmp:
            check_root = REPO_ROOT
            if not (REPO_ROOT / ".git").exists():
                check_root = Path(tmp)
                (check_root / ".gitignore").write_text(gitignore, encoding="utf-8")
                subprocess.run(
                    ["git", "init", "--quiet"],
                    cwd=check_root,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )

            for rel in [
                ".env.local",
                "config/local.env",
                "data/jobs/synthetic-job/job.json",
                "scratch.orig",
            ]:
                with self.subTest(ignored=rel):
                    result = subprocess.run(
                        ["git", "check-ignore", "--no-index", "--quiet", rel],
                        cwd=check_root,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0, rel)

            for rel in [
                "config/local.env.template",
                "config/defaults.env",
                "profiles/release_v1.0.0.env",
                "software/phylogeny/Dockerfile",
                "node_modules/example/index.js",
                "test-results/failure.png",
                "playwright-report/index.html",
                "blob-report/report.zip",
            ]:
                with self.subTest(public=rel):
                    result = subprocess.run(
                        ["git", "check-ignore", "--no-index", "--quiet", rel],
                        cwd=check_root,
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

        fungi_only_accessions = (
            REPO_ROOT / "examples/fungi_only/accessions.txt"
        ).read_text(encoding="utf-8").splitlines()
        fungi_only_mapping = {
            row.split("\t", 1)[0]
            for row in (
                REPO_ROOT / "examples/fungi_only/accessions_fungusID_taxonomyID.txt"
            ).read_text(encoding="utf-8").splitlines()
            if row
        }
        self.assertEqual(len(fungi_only_accessions), 50)
        self.assertEqual(len(set(fungi_only_accessions)), 50)
        self.assertEqual(set(fungi_only_accessions), fungi_only_mapping)
        example_index = " ".join(
            (REPO_ROOT / "examples/README.md").read_text(encoding="utf-8").split()
        )
        self.assertIn(
            "The canonical Both run completed on 2026-07-22 without substitutions.",
            example_index,
        )

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

    def test_summary_maps_truncated_and_trailing_dot_scaffolds_to_versioned_accession(self) -> None:
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
                "VERSION     tig00000001_RagTag.1\n"
                "//\n",
                encoding="utf-8",
            )
            (antismash_dir / f"{genome}.antismash.json").write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "id": "tig00000001_RagTag.1",
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
                "BGC1,tig00000001_RagT.,120,180,NRPS,-,-,-\n",
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
            self.assertEqual(bgc_rows[0]["antismash_bgc_id"], "tig00000001_RagTag.1.region001")
            self.assertEqual(bgc_rows[0]["funbgcex_bgc_id"], "BGC1")

            with (results_root / "summary" / "all_tools_shared_unshared_summary.csv").open(encoding="utf-8") as fh:
                summary_rows = list(csv.DictReader(fh))
            counts = {(row["tool"], row["entity_type"], row["class_norm"]): row for row in summary_rows}
            for key in [("antismash", "BGC", "NRPS"), ("funbgcex", "BGC", "NRPS")]:
                self.assertEqual(counts[key]["shared_count"], "1")
                self.assertEqual(counts[key]["unshared_count"], "0")

    def test_wrapper_supports_clinker_stage(self) -> None:
        text = (REPO_ROOT / "run_clusterweave.sh").read_text(encoding="utf-8")
        self.assertIn('RUN_STAGE_CLINKER="${RUN_STAGE_CLINKER:-auto}"', text)
        self.assertIn('CLINKER_MODE="${CLINKER_MODE:-auto}"', text)
        self.assertIn('RUN_CLINKER_STAGE="${PROJECT_DIR}/run_clinker.sh"', text)
        self.assertIn('RUN_STAGE_ANNOTATION="${RUN_STAGE_ANNOTATION:-${RUN_STAGE_NEW:-1}}"', text)
        self.assertIn("Stage 4/4: running run_clinker.sh", text)
        for ordinal in range(1, 5):
            self.assertIn(f"Stage {ordinal}/4: complete", text)
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

    def test_public_release_files_do_not_contain_private_handoff_markers(self) -> None:
        release_files = [
            "README.md",
            "docs/DATA_SOURCES.md",
            "THIRD_PARTY.md",
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
        boundary_text = (static_dir / "assets" / "api-result-boundary.js").read_text(encoding="utf-8")
        reader_text = (static_dir / "assets" / "result-reader-boundary.js").read_text(encoding="utf-8")
        intake_text = (static_dir / "assets" / "intake-taxon-boundary.js").read_text(encoding="utf-8")
        lifecycle_text = (static_dir / "assets" / "job-lifecycle-boundary.js").read_text(encoding="utf-8")
        diagnostics_text = (static_dir / "assets" / "diagnostics-access-boundary.js").read_text(encoding="utf-8")
        motion_text = (static_dir / "assets" / "motion-boundary.js").read_text(encoding="utf-8")

        self.assertLess(len(index_text.splitlines()), 1000)
        self.assertIn('href="/favicon.ico', index_text)
        self.assertTrue((static_dir / "favicon.ico").exists())
        self.assertIn('href="assets/clusterweave.css?v=20260723-timer-utc1-citation-align1"', index_text)
        self.assertIn('src="assets/clusterweave.js?v=20260723-timer-utc1-r13a1-r12h1-stage-tree2-ui-copy1"', index_text)
        self.assertEqual(index_text.count('name="clusterweave-game-asset"'), 4)
        self.assertNotIn('<link rel="stylesheet" href="assets/clusterweave-game.css', index_text)
        self.assertNotIn('<script src="assets/clusterweave-game', index_text)
        self.assertIn("function loadClusterweaveGameAssets()", js_text)
        self.assertIn("url.origin !== window.location.origin", js_text)
        self.assertIn("if (clusterweaveGameAssetsPromise) return clusterweaveGameAssetsPromise;", js_text)
        self.assertNotIn("<style>", index_text)
        self.assertNotIn("<script>\n", index_text)
        self.assertIn("function apiUrl(path)", js_text)
        self.assertIn("const API_RESULT_MODULE_PATH", js_text)
        boundary_start = js_text.index("const apiResultBoundaryReady = bootApiResultBoundary();")
        synchronous_setup = js_text.index("const initialHashRun = captureInitialResultHash();", boundary_start)
        boundary_await = js_text.index(
            "await intakeTaxonBoundaryReady;",
            synchronous_setup,
        )
        self.assertLess(boundary_start, synchronous_setup)
        self.assertLess(synchronous_setup, boundary_await)
        self.assertIn("export function createApiResultBoundary", boundary_text)
        self.assertIn("const RESULT_READER_MODULE_PATH", js_text)
        self.assertIn("export function createResultReaderBoundary", reader_text)
        self.assertIn("state: resultReaderState", js_text)
        self.assertIn("export function createIntakeControllerBoundary", intake_text)
        self.assertIn("state: intakeControllerState", js_text)
        self.assertIn(
            "async function startAnalysis() { return intakeControllerBoundary.startAnalysis(...arguments); }",
            js_text,
        )
        self.assertIn("await Promise.all([jobLifecycleBoundaryReady, resultReaderBoundaryReady]);", js_text)
        for delegate in [
            "function resultArtifactDescriptor(value, resultContext = null) { return resultReaderBoundary.resultArtifactDescriptor(value, resultContext); }",
            "async function handleResultLinkClick(event, jobId, relPath, download = false) { return resultReaderBoundary.handleResultLinkClick(event, jobId, relPath, download); }",
            "async function downloadResultArchive(event) { return resultReaderBoundary.downloadResultArchive(event); }",
            "function renderResultFileSurface(jobId, files) { return resultReaderBoundary.renderResultFileSurface(jobId, files); }",
            "function buildFileTree(files) { return resultReaderBoundary.buildFileTree(files); }",
            "async function hydrateSvgFigures(jobId) { return resultReaderBoundary.hydrateSvgFigures(jobId); }",
        ]:
            self.assertIn(delegate, js_text)
        self.assertIn("const JOB_LIFECYCLE_MODULE_PATH", js_text)
        self.assertIn("export function createJobLifecycleBoundary", lifecycle_text)
        for delegate in [
            "function apiUrl(path) { return apiResultBoundary.apiUrl(path); }",
            "function authHeadersFor(kind, jobId = null) { return apiResultBoundary.authHeadersFor(kind, jobId); }",
            "function resultFetch(jobId, artifactKey, options = {}) { return apiResultBoundary.resultFetch(jobId, artifactKey, options); }",
            "function resolveResultArtifact(jobId, ownerKey, reference, options = {}) { return apiResultBoundary.resolveResultArtifact(jobId, ownerKey, reference, options); }",
        ]:
            self.assertIn(delegate, js_text)
        self.assertNotIn("if (kind === 'job' && jobId)", js_text)
        self.assertIn("function handleResultLinkClick(event, jobId, relPath, download = false)", js_text)
        self.assertIn("const WORKFLOW_DNA_MODULE_PATH", js_text)
        self.assertIn("function bootBgcWorkflowDna()", js_text)
        self.assertNotIn('id="input-station-limit"', index_text)
        self.assertIn('id="upload-limit-note"', index_text)
        self.assertIn("Loading this service's input limits", index_text)
        self.assertNotIn('50 genome files or 50 NCBI accessions', index_text)
        self.assertNotIn('data-max-accessions="50"', index_text)
        self.assertIn('applyPublicQuotaLimits', js_text)
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
        self.assertIn("PUBLIC_WEB_FAQ_URL", intake_text)
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

        self.assertIn("export function createJobLifecycleControllerBoundary", lifecycle_text)
        self.assertIn("const jobLifecycleBoundaryInstalled = new Promise", js_text)
        self.assertIn("script.src = JOB_LIFECYCLE_MODULE_PATH;", js_text)
        self.assertIn("globalThis.__clusterweaveInstallJobLifecycleBoundary?.(", lifecycle_text)
        self.assertNotIn("await import(JOB_LIFECYCLE_MODULE_PATH)", js_text)
        self.assertIn("const jobLifecycleControllerState = {", js_text)
        self.assertIn("state: jobLifecycleControllerState", js_text)
        lifecycle_ready = js_text.index("await Promise.all([jobLifecycleBoundaryReady, motionBoundaryReady]);")
        first_ticker = js_text.index("startStageTicker();", lifecycle_ready)
        self.assertLess(lifecycle_ready, first_ticker)
        self.assertIn("export function createDiagnosticsControllerBoundary", diagnostics_text)
        self.assertIn("const diagnosticsControllerState = {", js_text)
        self.assertIn("state: diagnosticsControllerState", js_text)
        self.assertIn("const MOTION_MODULE_PATH", js_text)
        self.assertIn("export function createMotionBoundary", motion_text)
        self.assertIn("const motionBoundaryState = {", js_text)
        self.assertIn("state: motionBoundaryState", js_text)
        self.assertIn(
            "function animateDiagnosticsReveal() { return motionBoundary.animateDiagnosticsReveal(...arguments); }",
            js_text,
        )
        self.assertIn(
            "async function pollSystemStatus() { return diagnosticsControllerBoundary.pollSystemStatus(...arguments); }",
            js_text,
        )
        for delegate in [
            "function renderRunStack(runs = loadOpenedRuns()) { return jobLifecycleControllerBoundary.renderRunStack(...arguments); }",
            "function renderJobHistory(jobs) { return jobLifecycleControllerBoundary.renderJobHistory(...arguments); }",
            "async function loadJob(jobId, autoScroll = false, options = {}) { return jobLifecycleControllerBoundary.loadJob(...arguments); }",
            "async function hydrateQaLogs({ tail = true, before = null, autoScroll = false } = {}) { return jobLifecycleControllerBoundary.hydrateQaLogs(...arguments); }",
            "function renderGenomeProgressLayer(payload) { return jobLifecycleControllerBoundary.renderGenomeProgressLayer(...arguments); }",
            "function bgcWorkflowPayload(job = activeJobMeta) { return jobLifecycleControllerBoundary.bgcWorkflowPayload(...arguments); }",
            "function renderStageState() { return jobLifecycleControllerBoundary.renderStageState(...arguments); }",
            "function updateProgressBadge(status) { return jobLifecycleControllerBoundary.updateProgressBadge(...arguments); }",
        ]:
            with self.subTest(delegate=delegate):
                self.assertEqual(js_text.count(delegate), 1)
        self.assertNotIn("const ALT06_WORKFLOW_STEPS", js_text)
        self.assertIn("const ALT06_WORKFLOW_STEPS", lifecycle_text)

    def test_frontend_terminal_function_ownership_is_complete(self) -> None:
        assets = REPO_ROOT / "web" / "static" / "assets"
        classic = (assets / "clusterweave.js").read_text(encoding="utf-8")
        module_paths = {
            "apiResultBoundary": "api-result-boundary.js",
            "resultReaderBoundary": "result-reader-boundary.js",
            "intakeTaxonBoundary": "intake-taxon-boundary.js",
            "intakeControllerBoundary": "intake-taxon-boundary.js",
            "jobLifecycleBoundary": "job-lifecycle-boundary.js",
            "jobLifecycleControllerBoundary": "job-lifecycle-boundary.js",
            "diagnosticsAccessBoundary": "diagnostics-access-boundary.js",
            "diagnosticsControllerBoundary": "diagnostics-access-boundary.js",
            "motionBoundary": "motion-boundary.js",
        }
        module_sources = {
            name: (assets / rel).read_text(encoding="utf-8")
            for name, rel in module_paths.items()
        }
        unique_module_sources = {
            rel: (assets / rel).read_text(encoding="utf-8")
            for rel in set(module_paths.values())
        }
        function_re = re.compile(r"^(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(")
        delegate_re = re.compile(
            r"\{\s*return\s+([A-Za-z_$][\w$]*)\.([A-Za-z_$][\w$]*)\([^;]*\);\s*\}$"
        )
        declarations = []
        for line_number, line in enumerate(classic.splitlines(), start=1):
            match = function_re.match(line)
            if match:
                declarations.append((match.group(1), line_number, line))

        self.assertEqual(len(declarations), 852)
        self.assertEqual(len({name for name, _, _ in declarations}), 852)
        expected_delegate_counts = {
            "apiResultBoundary": 12,
            "resultReaderBoundary": 214,
            "intakeTaxonBoundary": 5,
            "intakeControllerBoundary": 138,
            "jobLifecycleBoundary": 32,
            "jobLifecycleControllerBoundary": 135,
            "diagnosticsAccessBoundary": 16,
            "diagnosticsControllerBoundary": 29,
            "motionBoundary": 32,
        }
        delegate_counts = {name: 0 for name in expected_delegate_counts}
        retained = []
        for name, line_number, line in declarations:
            delegate = delegate_re.search(line)
            if not delegate or delegate.group(1) not in module_sources:
                retained.append((name, line_number))
                continue
            target, method = delegate.groups()
            self.assertIn(target, module_sources, line)
            delegate_counts[target] += 1
            canonical_re = re.compile(
                rf"^\s*(?:async\s+)?function\s+{re.escape(method)}\s*\(",
                re.MULTILINE,
            )
            owners = [
                rel for rel, source in unique_module_sources.items()
                if canonical_re.search(source)
            ]
            self.assertEqual(owners, [module_paths[target]], f"{name} -> {target}.{method}")

        self.assertEqual(delegate_counts, expected_delegate_counts)
        self.assertEqual(len(retained), 239)
        declaration_order = {name: index for index, (name, _, _) in enumerate(declarations)}
        retained_regions = [
            ("layout-shell", "setCardCollapsed", "scheduleDnaOverlaySync"),
            ("access-policy-shell", "setAccessMode", "applyPublicCanonicalDefaults"),
            ("navigation-shell", "setActiveNav", "captureInitialResultHash"),
            ("workbench-shell", "resetToIdleWorkbench", "escapeJsString"),
            ("identity-access-shell", "updateAccessTokenStatus", "syncResultAccessCollapse"),
            ("submission-receipt-shell", "setResultAccessCollapsed", "openSubmittedRun"),
            ("run-configuration-shell", "envToBool", "figureApplicableToAnalysis"),
            ("lifecycle-result-shell", "moveWorkflowProgressIntoResults", "currentJobSelection"),
            ("pixel-runner-integration", "clusterweaveGamePhase", "wireClusterweaveGameAdapter"),
            ("workflow-dna-renderer", "dnaLabelLines", "renderWeaveHelix"),
            ("result-navigation-shell", "setResultFocusMode", "loadResults"),
            ("public-bootstrap", "startPublicImpactPolling", "initializeApp"),
        ]
        classifications = {}
        for category, first, last in retained_regions:
            start = declaration_order[first]
            end = declaration_order[last]
            for name, _ in retained:
                if start <= declaration_order[name] <= end:
                    self.assertNotIn(name, classifications)
                    classifications[name] = category
        self.assertEqual(set(classifications), {name for name, _ in retained})
        for name, _ in retained:
            canonical_re = re.compile(
                rf"^\s*(?:async\s+)?function\s+{re.escape(name)}\s*\(",
                re.MULTILINE,
            )
            self.assertFalse(
                any(canonical_re.search(source) for source in unique_module_sources.values()),
                f"retained classic owner duplicated in a module: {name}",
            )

    def test_frontend_taxon_scope_and_mixed_upload_contract(self) -> None:
        static_dir = REPO_ROOT / "web" / "static"
        index_text = (static_dir / "index.html").read_text(encoding="utf-8")
        css_text = (static_dir / "assets" / "clusterweave.css").read_text(encoding="utf-8")
        classic_text = (static_dir / "assets" / "clusterweave.js").read_text(encoding="utf-8")
        reader_text = (static_dir / "assets" / "result-reader-boundary.js").read_text(encoding="utf-8")
        lifecycle_text = (static_dir / "assets" / "job-lifecycle-boundary.js").read_text(encoding="utf-8")
        boundary_text = (static_dir / "assets" / "intake-taxon-boundary.js").read_text(encoding="utf-8")
        js_text = reader_text + "\n" + lifecycle_text + "\n" + classic_text + "\n" + boundary_text

        selector = index_text.split('id="analysis-scope-selector"', 1)[1].split("</fieldset>", 1)[0]
        self.assertIn("<legend>Analysis scope</legend>", selector)
        self.assertIn('name="analysis-scope" value="fungi" checked', selector)
        self.assertIn('name="analysis-scope" value="both"', selector)
        self.assertIn('name="analysis-scope" value="bacteria"', selector)
        self.assertLess(selector.index('value="fungi"'), selector.index('value="both"'))
        self.assertLess(selector.index('value="both"'), selector.index('value="bacteria"'))
        self.assertNotIn("Both mode needs one Fungi or Bacteria declaration per ambiguous logical genome.", index_text)
        self.assertNotIn("a same-stem FASTA inherits that route", index_text)
        self.assertIn('id="run-setup-analysis-scope"', index_text)

        self.assertIn("let stagedAnalysisScope = 'fungi';", js_text)
        self.assertIn("let activeSavedAnalysisContext = null;", js_text)
        self.assertIn("function normalizeAnalysisScope(value, fallback = 'fungi')", js_text)
        self.assertIn("function analysisContextFromJob(job)", js_text)
        self.assertIn("function analysisCapabilities(context = activeAnalysisContext())", js_text)
        self.assertIn("function logicalGenomeInputs(files = state.selectedFiles)", js_text)
        self.assertIn("return publicGenomeStem(value).toLowerCase();", js_text)
        self.assertIn("let genbankTaxonomyAuthorityCache = new Map();", js_text)
        self.assertIn("function parseClientGenbankTaxonomy(text)", js_text)
        self.assertIn("const INTAKE_TAXON_MODULE_PATH", classic_text)
        self.assertIn("export function createIntakeTaxonBoundary", boundary_text)
        self.assertIn(
            "return intakeTaxonBoundary.parseClientGenbankTaxonomy(...arguments)",
            classic_text,
        )
        self.assertNotIn("const organisms = [];", classic_text)
        self.assertIn("const organisms = [];", boundary_text)
        self.assertIn("function logicalGenomeAuthority(item)", js_text)
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
        self.assertIn("fd.append('analysis_scope', normalizeAnalysisScope(state.stagedAnalysisScope))", js_text)
        self.assertIn("if (Object.keys(taxonAssignments).length)", js_text)
        self.assertIn("fd.append('taxon_assignments', JSON.stringify(taxonAssignments))", js_text)
        self.assertIn("setActiveSavedAnalysisContext(job);", js_text)
        self.assertIn("resultCategoryApplicable('funbgcex')", js_text)
        self.assertIn("figureApplicableToAnalysis(path, capabilities)", js_text)

        self.assertIn(".analysis-scope-options input:checked + span", css_text)
        self.assertIn(".analysis-scope-options input:focus-visible + span", css_text)
        self.assertIn("fungal, bacterial, or mixed biosynthetic gene cluster discovery", index_text)

    def test_frontend_phylogeny_figure_discovery_and_accessibility_contract(self) -> None:
        static_dir = REPO_ROOT / "web" / "static"
        css_text = (static_dir / "assets" / "clusterweave.css").read_text(encoding="utf-8")
        reader_text = (static_dir / "assets" / "result-reader-boundary.js").read_text(encoding="utf-8")
        classic_text = (static_dir / "assets" / "clusterweave.js").read_text(encoding="utf-8")
        js_text = reader_text + "\n" + classic_text

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
        self.assertIn(".figure-preview-wrap.is-taxon-tree {\n  min-height: 0;\n  max-height: 78vh;", css_text)
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
        self.assertIn("const requestJobId = state.activeJobId;", ui_text)
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
        self.assertIn("if (state.resultFocusMode === 'focused')", ui_text)
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
        js_text = (REPO_ROOT / "web" / "static" / "assets" / "result-reader-boundary.js").read_text(encoding="utf-8")
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
        js_text = (REPO_ROOT / "web" / "static" / "assets" / "result-reader-boundary.js").read_text(encoding="utf-8")
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
        js_text = (REPO_ROOT / "web" / "static" / "assets" / "result-reader-boundary.js").read_text(encoding="utf-8")
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
        js_text = (REPO_ROOT / "web" / "static" / "assets" / "result-reader-boundary.js").read_text(encoding="utf-8")
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
        js_text = (REPO_ROOT / "web" / "static" / "assets" / "result-reader-boundary.js").read_text(encoding="utf-8")
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
        js_text = (REPO_ROOT / "web" / "static" / "assets" / "result-reader-boundary.js").read_text(
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
const state = {{ get activeJobMeta() {{ return activeJobMeta; }} }};
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
        js_text = (REPO_ROOT / "web" / "static" / "assets" / "result-reader-boundary.js").read_text(encoding="utf-8")
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
        js_text = (REPO_ROOT / "web" / "static" / "assets" / "result-reader-boundary.js").read_text(encoding="utf-8")
        boundary_text = (REPO_ROOT / "web" / "static" / "assets" / "api-result-boundary.js").read_text(encoding="utf-8")
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
        viewer_fetch_block = boundary_text.split("function bigscapeViewerFetch", 1)[1].split(
            "return Object.freeze", 1
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
        js_text = (REPO_ROOT / "web" / "static" / "assets" / "result-reader-boundary.js").read_text(
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
        js_text = (REPO_ROOT / "web" / "static" / "assets" / "result-reader-boundary.js").read_text(
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
        js_text = (REPO_ROOT / "web" / "static" / "assets" / "result-reader-boundary.js").read_text(
            encoding="utf-8"
        )
        helpers = js_text.split("function resultUrlShouldStayExternal", 1)[1].split(
            "function resultBlobDataUrl", 1
        )[0]
        limits_start = js_text.index("const TOOL_RESULT_PREVIEW_ASSET_MAX_BYTES")
        limits_end = js_text.index("const STATIC_RESULT_PREVIEW_CSP", limits_start)
        asset_limits = js_text[limits_start:limits_end]
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
{asset_limits}
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
  const observedToolAssetSize = 17271595;
  const observedToolBudget = {{ declaredBytes: 0, actualBytes: 0 }};
  assertToolResultAssetSize(
    {{ headers: {{ get: () => String(observedToolAssetSize) }} }},
    observedToolAssetSize,
    observedToolBudget,
  );
  let toolDeclaredOversizeRejected = false;
  try {{
    assertToolResultAssetSize(
      {{ headers: {{ get: () => String(32 * 1024 * 1024 + 1) }} }}, 1,
      {{ declaredBytes: 0, actualBytes: 0 }},
    );
  }} catch (error) {{ toolDeclaredOversizeRejected = /32 MiB/.test(String(error.message)); }}
  let toolActualOversizeRejected = false;
  try {{
    assertToolResultAssetSize(
      {{ headers: {{ get: () => '1' }} }}, 32 * 1024 * 1024 + 1,
      {{ declaredBytes: 0, actualBytes: 0 }},
    );
  }} catch (error) {{ toolActualOversizeRejected = /32 MiB/.test(String(error.message)); }}
  const toolAggregateBudget = {{ declaredBytes: 0, actualBytes: 0 }};
  const toolLimitResponse = {{ headers: {{ get: () => String(32 * 1024 * 1024) }} }};
  assertToolResultAssetSize(toolLimitResponse, 32 * 1024 * 1024, toolAggregateBudget);
  assertToolResultAssetSize(toolLimitResponse, 32 * 1024 * 1024, toolAggregateBudget);
  let toolAggregateRejected = false;
  try {{ assertToolResultAssetSize({{ headers: {{ get: () => '1' }} }}, 1, toolAggregateBudget); }}
  catch (error) {{ toolAggregateRejected = /64 MiB/.test(String(error.message)); }}
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
    observedToolAssetAccepted: observedToolBudget.actualBytes === observedToolAssetSize
      && observedToolBudget.declaredBytes === observedToolAssetSize,
    toolOversizeRejected: toolDeclaredOversizeRejected && toolActualOversizeRejected,
    toolAggregateRejected,
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
                "observedToolAssetAccepted": True,
                "toolOversizeRejected": True,
                "toolAggregateRejected": True,
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
        self.assertNotIn("function workflowStageOverviewNodes", text)
        self.assertNotIn("dna-popover-connector-layer", text)

    def test_web_bgc_station_supports_all_accepted_accessible_genome_progress(self) -> None:
        static_dir = REPO_ROOT / "web" / "static"
        index_text = (static_dir / "index.html").read_text(encoding="utf-8")
        css_text = (static_dir / "assets" / "clusterweave.css").read_text(encoding="utf-8")
        classic_text = (static_dir / "assets" / "clusterweave.js").read_text(encoding="utf-8")
        lifecycle_text = (static_dir / "assets" / "job-lifecycle-boundary.js").read_text(encoding="utf-8")
        js_text = classic_text + "\n" + lifecycle_text
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
        self.assertIn("if (state.bgcWorkflowDna) state.bgcWorkflowDna.setProgress(payload.progress, payload);", js_text)
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
        js_text = (static_dir / "assets" / "result-reader-boundary.js").read_text(encoding="utf-8")

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
        classic_text = (static_dir / "assets" / "clusterweave.js").read_text(encoding="utf-8")
        boundary_text = (static_dir / "assets" / "diagnostics-access-boundary.js").read_text(encoding="utf-8")
        js_text = classic_text + "\n" + boundary_text
        self.assertIn('data-ops-panel="collapsed"', index_text)
        self.assertIn('data-ops-tab="jobs"', index_text)
        self.assertNotIn('id="ops-panel-toggle"', index_text)
        self.assertIn("toggle.id = 'ops-panel-toggle';", js_text)
        self.assertIn("documentImpl.body.insertBefore(toggle, panel);", js_text)
        self.assertIn("function ensureOpsPanelToggle()", js_text)
        self.assertIn("function removeOpsPanelToggle()", js_text)
        self.assertIn("function setOpsPanelCollapsed(collapsed)", js_text)
        self.assertIn("export function createDiagnosticsAccessBoundary", boundary_text)
        self.assertIn(
            "function openOpsPanel(options = {}) { return diagnosticsAccessBoundary.openOpsPanel(options); }",
            classic_text,
        )
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

    def test_ui_stage_states_use_semantic_classes(self) -> None:
        text = frontend_text()
        self.assertIn(".stage-card", text)
        self.assertIn(".bgc-stage-card.complete", text)
        self.assertIn(".bgc-stage-card.running", text)
        self.assertIn(".bgc-stage-card.error", text)
        self.assertIn("function initializeStageState(job)", text)
        self.assertIn("function finalizeStageState(status)", text)
        self.assertIn("function renderBgcWorkflowStageStrip(payload)", text)

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
        self.assertIn("const eventId = `log:${state.activeJobId || ''}:${state.logCursor}:${key}`;", text)

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
        self.assertIn("if (eventId && state.activeStageState.appliedEvents.has(eventId)) return;", transition_block)
        self.assertIn("if (isRestart) clearStageTimingFrom(key);", transition_block)
        self.assertIn("setStageStartTime(key, eventMs, source, { force: isRestart });", transition_block)
        self.assertIn("setStageEndTime(state.activeStageState.current, eventMs, source);", transition_block)

        final_block = text.split("function finalizeStageState(status)", 1)[1].split("function renderStageState", 1)[0]
        self.assertIn("if (state.activeStageState.current) setStageEndTime(state.activeStageState.current, terminalMs, 'terminal');", final_block)
        self.assertIn("setStageEndTime(failedKey, terminalMs, 'terminal');", final_block)

        public_block = text.split("function publicStageTimingEvent(event)", 1)[1].split("async function deleteJob", 1)[0]
        self.assertIn("const markerMeta = /^canonical workflow stage$/i.test(marker.meta || '');", public_block)
        self.assertIn("const eventTimeMs = stageTimestampFromClock(marker.time || marker.meta, job, state.activeStageState.lastEventMs);", public_block)

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
        assets_dir = REPO_ROOT / "web" / "static" / "assets"
        js_text = "\n".join(
            (assets_dir / name).read_text(encoding="utf-8")
            for name in ["clusterweave.js", "intake-taxon-boundary.js"]
        )
        self.assertIn('id="manual-accessions"', html_text)
        self.assertIn("function manualAccessionLines()", js_text)
        self.assertIn("const MANUAL_ACCESSIONS_FILENAME = 'manual_accessions.txt'", js_text)
        self.assertIn("manualLines.join('\\n') + '\\n'", js_text)
        self.assertIn("new File([manualAccessionText], MANUAL_ACCESSIONS_FILENAME", js_text)
        self.assertNotIn("input source(s) ready", js_text)
        self.assertIn("api/inputs/validate", js_text)
        self.assertIn("validateAcceptedAccessions()", js_text)
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
        assets_dir = REPO_ROOT / "web" / "static" / "assets"
        js_text = "\n".join(
            (assets_dir / name).read_text(encoding="utf-8")
            for name in ["clusterweave.js", "intake-taxon-boundary.js"]
        )
        self.assertIn("hero.setAttribute('aria-label', 'Discover the hidden potential of microbes')", js_text)
        self.assertIn("<span>of</span><span>microbes</span>", js_text)
        self.assertIn("scope === 'both' ? 'microbial_survey'", js_text)
        self.assertNotIn("scope === 'both' ? 'genome_survey'", js_text)
        self.assertNotIn("Discover the hidden potential of fungi and bacteria", js_text)

    def test_atlas_and_clinker_default_to_twenty_without_expanding_other_sets(self) -> None:
        html_text = (REPO_ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
        assets_dir = REPO_ROOT / "web" / "static" / "assets"
        js_text = "\n".join(
            (assets_dir / name).read_text(encoding="utf-8")
            for name in ["clusterweave.js", "intake-taxon-boundary.js"]
        )
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
        self.assertIn('IF YOU HAVE FOUND CLUSTERWEAVE USEFUL,', text)
        self.assertIn('data-citation-link>CITE US</a>', text)
        self.assertIn('id="tool-credit-open" type="button" aria-haspopup="dialog" aria-controls="tool-credit-overlay">Credit</button>', text)
        self.assertIn('background: #57534e', text)
        self.assertIn('class="citation-card-row"', text)
        self.assertIn("width: min(31rem, 100%)", text)
        self.assertIn("font-size: clamp(.5rem, 1.4vw, .72rem)", text)
        self.assertIn("white-space: nowrap", text)
        self.assertIn("min-width: 5.25rem", text)
        self.assertIn("padding: .5rem .38rem", text)
        self.assertIn('id="tool-credit-support-tab" data-tool-credit-tab="support"', text)
        self.assertIn('aria-controls="tool-credit-support-panel" aria-selected="true"', text)
        self.assertIn('id="tool-credit-web-tab" data-tool-credit-tab="web"', text)
        self.assertIn('id="tool-credit-support-panel" role="tabpanel"', text)
        self.assertIn('src="assets/pmi-logo.png" alt="Plant Microbe Interfaces (PMI)"', text)
        self.assertIn('class="pmi-support-link" href="https://pmiweb.ornl.gov/" target="_blank" rel="noopener"', text)
        self.assertIn("const names = ['support', 'web', 'local'];", text)
        self.assertIn("switchToolCreditTab('support');", text)
        self.assertIn('href="https://github.com/n2mology/clusterweave"', text)
        self.assertNotIn('id="primary-nav"', text)
        self.assertNotIn('nav-toggle', text)
        self.assertNotIn('launch-deck', text)
        self.assertNotIn('right-column', text)
        self.assertNotIn('weavemap-section', text)
        self.assertNotIn('href="#weavemap" data-nav-target="weavemap"', text)

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
        self.assertIn("normalizeAccessMode(options.accessMode) === 'public'", text)
        self.assertIn('class="runtime-bridge" hidden inert aria-hidden="true"', text)
        self.assertIn('id="run-genome-prep" checked', text)
        self.assertIn('id="run-annotation" checked', text)
        self.assertIn('id="advanced-panel"', text) if 'id="advanced-panel"' in text else self.assertNotIn('id="advanced-panel"', text)
        self.assertIn('id="jobs-card"', text)
        self.assertIn('id="console-card"', text)
        self.assertIn('id="progress-card"', text)

    def test_diagnostics_access_boundary_direct_behavior(self) -> None:
        boundary_path = (
            REPO_ROOT / "web" / "static" / "assets" / "diagnostics-access-boundary.js"
        )
        boundary_uri = "data:text/javascript;base64," + base64.b64encode(
            boundary_path.read_bytes()
        ).decode("ascii")
        script = f"""
import {{ createDiagnosticsAccessBoundary }} from {json.dumps(boundary_uri)};
let admin = false;
const body = {{ dataset: {{ opsPanel: 'collapsed' }} }};
const documentImpl = {{
  body,
  activeElement: null,
  querySelectorAll: () => [],
  querySelector: () => null,
  getElementById: () => null,
  addEventListener: () => {{}},
}};
const boundary = createDiagnosticsAccessBoundary({{
  documentImpl,
  windowImpl: {{ requestAnimationFrame: fn => fn() }},
  canUseAdminSurfaces: () => admin,
  setCardCollapsed: () => {{}},
  hydrateQaLogs: () => {{}},
  shouldTailQaLogs: () => true,
  refreshJobHistory: () => {{}},
  pollSystemStatus: () => {{}},
  renderRerunPanel: () => {{}},
  activeJob: () => ({{ jobId: '', job: null }}),
  cssAttributeValue: value => value,
  animateOpsPanelToggle: () => {{}},
}});
const publicMode = boundary.setUIMode('advanced', {{ accessMode: 'public' }});
admin = true;
const adminMode = boundary.setUIMode('lab', {{ accessMode: 'admin' }});
const scroll = {{ scrollTop: 0, scrollHeight: 91, clientHeight: 24 }};
boundary.scrollElementToBottom(scroll);
console.log(JSON.stringify({{
  publicMode,
  adminMode,
  accessFallback: boundary.normalizeAccessMode('unexpected'),
  payload: boundary.rerunPayloadFromStages(['annotation', 'summary'], true),
  hasStages: boundary.rerunPayloadHasStages({{ run_summary: true }}),
  prepAllowed: boundary.rerunStageAllowed('prep', {{ stages: {{ prepare: {{ available: false }} }} }}),
  scrollTop: scroll.scrollTop,
}}));
"""
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            text=True,
            capture_output=True,
            check=True,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["publicMode"], "guided")
        self.assertEqual(payload["adminMode"], "lab")
        self.assertEqual(payload["accessFallback"], "public")
        self.assertTrue(payload["hasStages"])
        self.assertFalse(payload["prepAllowed"])
        self.assertEqual(payload["scrollTop"], 67)
        self.assertEqual(payload["payload"]["run_annotation"], True)
        self.assertEqual(payload["payload"]["run_summary"], True)
        self.assertEqual(payload["payload"]["run_crosswalk"], True)
        self.assertEqual(payload["payload"]["force"], True)

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
        assets_dir = REPO_ROOT / "web" / "static" / "assets"
        js_text = "\n".join(
            (assets_dir / name).read_text(encoding="utf-8")
            for name in ["clusterweave.js", "intake-taxon-boundary.js"]
        )

        self.assertIn("function submissionsPausedForPublic()", js_text)
        self.assertIn("SUBMISSIONS PAUSED - QUEUE LOCKED BY OPERATOR", js_text)
        self.assertIn("Queue gate: paused before upload.", js_text)
        self.assertIn("SELECT VALIDATE FOR AUTHORITATIVE NCBI TAXONOMY", js_text)
        self.assertIn("input.setAttribute('aria-invalid', showError ? 'true' : 'false')", js_text)
        self.assertIn("has-accession-verification-error", js_text)
        self.assertIn(".accession-line.has-accession-verification-error", css_text)
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
        assets_dir = REPO_ROOT / "web" / "static" / "assets"
        js_text = "\n".join(
            (assets_dir / name).read_text(encoding="utf-8")
            for name in ["clusterweave.js", "intake-taxon-boundary.js"]
        )

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



if __name__ == "__main__":
    unittest.main()
