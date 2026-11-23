from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SUMMARY_SCRIPT = REPO_ROOT / "summarize_clusterweave.sh"
OUTPUT_PATHS = (
    "summary/all_tools_scaffold_comparison.csv",
    "summary/all_tools_bgc_comparison.csv",
    "summary/all_tools_shared_unshared_summary.csv",
    "summary_tables/antismash_product_types_exact.tsv",
)
EXPECTED_DIGESTS: dict[str, dict[str, str]] = {'zero': {'summary/all_tools_scaffold_comparison.csv': 'e2ab11e43eb206935a1cf2d44d8a6fb112e85860bfb8aeabc76af5bdd3652e39', 'summary/all_tools_bgc_comparison.csv': '060d9795a06573c9e2ae9daf85c7859b93ae3fbcd257a98f50b2a6afc181f71f', 'summary/all_tools_shared_unshared_summary.csv': 'dd9891c0c837db92a743c0c4379201b948ebda23e9181887ece7cf623fb2f058', 'summary_tables/antismash_product_types_exact.tsv': '2845c02fa04001889d673f5e004a15fec511227b8f241e79083e4d775011cd05'}, 'fungal': {'summary/all_tools_scaffold_comparison.csv': 'e4021fd8d78cb35afc700542434e325e3eac1101c4bfa771818ee551c6493b21', 'summary/all_tools_bgc_comparison.csv': '3ddd0d19d96cd5714472abd3c62b49dabaaaf14343c8ddecf78ca997677cfc98', 'summary/all_tools_shared_unshared_summary.csv': '34da21090c20af9d8812f334b1b01c8ddc09ca47f7c24eb06badaab88e288465', 'summary_tables/antismash_product_types_exact.tsv': 'fbeb82144364a87abcbc7573488ac54af31e5e21958be6e7980ae2b14556c60d'}, 'bacterial': {'summary/all_tools_scaffold_comparison.csv': 'aab5f938b9dbf3afbbd9df55d45217d3bcf95a91deea8364bafe0465fa7c3ce9', 'summary/all_tools_bgc_comparison.csv': 'd57f9e41d3d0c5f77b202ed58a2086e66f2ae93eb04f5d0ef691329c4b02ff26', 'summary/all_tools_shared_unshared_summary.csv': 'dd1999cf69055b41a4466f8e0b08128ee6b447e38340546478c6ff4881b90e47', 'summary_tables/antismash_product_types_exact.tsv': '1edbf0414fc58ed94632ed2c731ee18986dbc1ec72f2d1ba01d60dfa9d596285'}, 'mixed': {'summary/all_tools_scaffold_comparison.csv': '7518f3c7aab1f63a8d955b9e570b4679bed9fbab2cc972a9fe5c36977448df3a', 'summary/all_tools_bgc_comparison.csv': '1a7fc27f8f5a0d421e5b43cccc000cea01828367a0845148842db8aec7af8139', 'summary/all_tools_shared_unshared_summary.csv': '258e354175c71b363af585868ca7381f73b5df62bb3e970959fa0e3a91833a08', 'summary_tables/antismash_product_types_exact.tsv': 'e595635997a8c32b7399ada003c3c396a083e93bb038d8cc887eec7372d345e2'}}


def write_recorder(path: Path) -> None:
    path.write_text(
        "import json, os, pathlib, sys\n"
        "with pathlib.Path(os.environ['SUMMARY_CALL_LOG']).open('a', encoding='utf-8') as fh:\n"
        "    fh.write(json.dumps(sys.argv) + '\\n')\n",
        encoding="utf-8",
    )


def write_antismash(
    root: Path,
    genome: str,
    products: list[str],
    *,
    bacterial_name: bool = False,
    record_id: str | None = None,
) -> None:
    genome_dir = root / "antismash" / genome
    genome_dir.mkdir(parents=True, exist_ok=True)
    suffix = ".bacteria.antismash.json" if bacterial_name else ".antismash.json"
    (genome_dir / f"{genome}{suffix}").write_text(
        json.dumps(
            {
                "records": [
                    {
                        "id": record_id or f"{genome}_scaffold.1",
                        "modules": {},
                        "areas": [
                            {
                                "start": 99,
                                "end": 200,
                                "products": products,
                                "protoclusters": {},
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def write_funbgcex(root: Path, genome: str, core: str) -> None:
    genome_dir = root / "funbgcex" / genome
    genome_dir.mkdir(parents=True, exist_ok=True)
    (genome_dir / "allBGCs.csv").write_text(
        "BGC no.,Scaffold,Start position,End position,Core enzymes,"
        "Metabolite from similar BGC,Similar BGC,Similarity score\n"
        f"BGC1,{genome}_scaffold,120,180,{core},-,-,-\n",
        encoding="utf-8",
    )


def write_manifest(root: Path, rows: list[tuple[str, str]]) -> None:
    manifest = root / "summary_tables" / "genome_taxon_manifest.tsv"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        "genome_id\ttaxon_group\tprediction_method\tdetector_profile\n"
        + "".join(
            f"{genome}\t{taxon}\t{'prodigal' if taxon == 'bacteria' else 'funannotate'}\t"
            f"{'antismash' if taxon == 'bacteria' else 'antismash+funbgcex'}\n"
            for genome, taxon in rows
        ),
        encoding="utf-8",
    )


def write_bigscape(root: Path, genomes: list[str]) -> None:
    run_dir = root / "big_scape" / "output_files" / "run_c0.3"
    cluster_dir = run_dir / "mix"
    cluster_dir.mkdir(parents=True, exist_ok=True)
    records = [f"{genome}__region001" for genome in genomes]
    (run_dir / "record_annotations.tsv").write_text(
        "Record\tOrganism\tCategory\n"
        + "".join(f"{record}\tignored\tNRPS\n" for record in records),
        encoding="utf-8",
    )
    (cluster_dir / "mix_clustering_0.3.tsv").write_text(
        "Record\tFamily\n" + "".join(f"{record}\tFAM_1\n" for record in records),
        encoding="utf-8",
    )


class SummarizerExtractionContractTests(unittest.TestCase):
    maxDiff = None

    def run_case(
        self,
        case: str,
        *,
        ecology: bool = False,
        extra_args: tuple[str, ...] = (),
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, bytes], list[list[str]], Path]:
        temporary = tempfile.TemporaryDirectory(prefix=f"clusterweave-r10a-{case}-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        projects_root = root / "projects root"
        results_root = root / "data" / "results" / "project with spaces"
        results_root.mkdir(parents=True)

        if case == "fungal":
            write_manifest(results_root, [("Fungus_one", "fungi")])
            write_antismash(results_root, "Fungus_one", ["NRPS", "T1PKS"])
            write_funbgcex(results_root, "Fungus_one", "NRPS;PKS")
        elif case == "bacterial":
            write_manifest(results_root, [("Bacterium_one", "bacteria")])
            write_antismash(
                results_root,
                "Bacterium_one",
                ["NRPS"],
                bacterial_name=True,
            )
            write_antismash(results_root, "Bacterium_one", ["terpene"])
        elif case == "mixed":
            write_manifest(
                results_root,
                [("Fungus_one", "fungi"), ("Bacterium_one", "bacteria")],
            )
            write_antismash(results_root, "Fungus_one", ["NRPS"])
            write_funbgcex(results_root, "Fungus_one", "NRPS")
            write_antismash(
                results_root,
                "Bacterium_one",
                ["NRPS"],
                bacterial_name=True,
            )
            write_bigscape(results_root, ["Fungus_one", "Bacterium_one"])
        elif case != "zero":
            raise AssertionError(f"unknown case: {case}")

        crosswalk = root / "crosswalk recorder.py"
        candidate = root / "candidate recorder.py"
        write_recorder(crosswalk)
        write_recorder(candidate)
        call_log = root / "calls.jsonl"
        metadata = results_root / "summary_tables" / "ecology.tsv"
        if ecology:
            metadata.parent.mkdir(parents=True, exist_ok=True)
            metadata.write_text("genome_id\tecofun_primary\nFungus_one\tsoil\n", encoding="utf-8")

        env = dict(os.environ)
        env.update(
            {
                "PROJECT_NAME": "project with spaces",
                "PROJECTS_ROOT": str(projects_root),
                "DATA_ROOT": str(root / "data"),
                "RESULTS_ROOT": str(results_root),
                "BGC_GCF_CROSSWALK_PY": str(crosswalk),
                "TARGETED_ANALYSIS_PY": str(candidate),
                "PYTHON_BIN": sys.executable,
                "SUMMARY_CALL_LOG": str(call_log),
                "RUN_ECOLOGY_ANALYSIS": "1" if ecology else "0",
                "METADATA_TSV": str(metadata),
                "BIGSCAPE_GCF_CATEGORY": "mix",
                "BIGSCAPE_GCF_THRESHOLD": "0.3",
            }
        )
        if ecology:
            env.update(
                {
                    "TARGET_GENOME": "Fungus_one",
                    "FOCUS_ECOLOGY_LABEL": "soil habitat",
                    "ECOLOGY_FIELD": "ecofun_primary",
                }
            )

        result = subprocess.run(
            ["bash", str(SUMMARY_SCRIPT), *extra_args],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        outputs = {
            relative: (results_root / relative).read_bytes()
            for relative in OUTPUT_PATHS
            if (results_root / relative).is_file()
        }
        calls = [json.loads(line) for line in call_log.read_text(encoding="utf-8").splitlines()] if call_log.exists() else []
        return result, outputs, calls, projects_root

    def test_fungal_bacterial_mixed_and_zero_output_goldens(self) -> None:
        for case in ("zero", "fungal", "bacterial", "mixed"):
            with self.subTest(case=case):
                result, outputs, calls, projects_root = self.run_case(case)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(set(outputs), set(OUTPUT_PATHS))
                digests = {
                    name: hashlib.sha256(payload).hexdigest()
                    for name, payload in outputs.items()
                }
                self.assertEqual(digests, EXPECTED_DIGESTS[case])
                normalized_stdout = result.stdout.replace(
                    str(projects_root.parent), "<ROOT>"
                )
                self.assertEqual(
                    normalized_stdout,
                    "Wrote scaffold comparison table: <ROOT>/data/results/project with spaces/summary/all_tools_scaffold_comparison.csv\n"
                    "Wrote BGC comparison table:      <ROOT>/data/results/project with spaces/summary/all_tools_bgc_comparison.csv\n"
                    "Wrote summary table:             <ROOT>/data/results/project with spaces/summary/all_tools_shared_unshared_summary.csv\n"
                    "Wrote exact product types:       <ROOT>/data/results/project with spaces/summary_tables/antismash_product_types_exact.tsv\n"
                    "Skipped ecology-aware ranking: set RUN_ECOLOGY_ANALYSIS=1 to enable metadata-driven candidate tables.\n"
                    "Done.\n",
                )
                self.assertEqual(len(calls), 1)
                self.assertEqual(
                    calls[0][1:],
                    [
                        "--project-root",
                        str(projects_root),
                        "--project-name",
                        "project with spaces",
                        "--selected-gcf-category",
                        "mix",
                        "--selected-gcf-threshold",
                        "0.3",
                    ],
                )
                self.assertTrue(calls[0][0].endswith("crosswalk recorder.py"))
                self.assertIn("Skipped ecology-aware ranking", result.stdout)
                self.assertEqual(result.stderr, "")

    def test_shell_uses_one_tracked_summary_implementation(self) -> None:
        shell_text = SUMMARY_SCRIPT.read_text(encoding="utf-8")
        helper = REPO_ROOT / "bin" / "summarize_clusterweave.py"
        helper_text = helper.read_text(encoding="utf-8")
        self.assertNotIn("<<'PY'", shell_text)
        self.assertIn(
            'SUMMARY_BUILDER_PY="${SCRIPT_DIR}/bin/summarize_clusterweave.py"',
            shell_text,
        )
        self.assertIn('"${PYTHON_BIN}" "${SUMMARY_BUILDER_PY}"', shell_text)
        self.assertEqual(shell_text.count("SUMMARY_BUILDER_PY"), 4)
        self.assertIn("def parse_antismash():", helper_text)

    def test_shell_ignores_positional_arguments_as_before(self) -> None:
        plain = self.run_case("mixed")
        with_args = self.run_case("mixed", extra_args=("--not-an-option", "value"))
        self.assertEqual(plain[0].returncode, with_args[0].returncode)
        plain_stdout = plain[0].stdout.replace(str(plain[3].parent), "<ROOT>")
        args_stdout = with_args[0].stdout.replace(
            str(with_args[3].parent), "<ROOT>"
        )
        self.assertEqual(plain_stdout, args_stdout)
        self.assertEqual(plain[0].stderr, with_args[0].stderr)
        self.assertEqual(plain[1], with_args[1])

    def test_ecology_downstream_argv_is_unchanged(self) -> None:
        result, _, calls, projects_root = self.run_case("fungal", ecology=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[0][0].endswith("crosswalk recorder.py"))
        self.assertTrue(calls[1][0].endswith("candidate recorder.py"))
        self.assertEqual(
            calls[1][1:],
            [
                "--project-root",
                str(projects_root),
                "--project-name",
                "project with spaces",
                "--metadata",
                str(
                    projects_root.parent / "data/results/project with spaces/summary_tables/ecology.tsv"
                ),
                "--ecology-field",
                "ecofun_primary",
                "--target-genome",
                "Fungus_one",
                "--focus-ecology-label",
                "soil habitat",
            ],
        )
        self.assertTrue(calls[1][6].endswith("summary_tables/ecology.tsv"))
        self.assertTrue(result.stdout.endswith("Done.\n"))
        self.assertEqual(result.stderr, "")

    def test_malformed_antismash_json_stops_before_downstream_calls(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="clusterweave-r10a-failure-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        results_root = root / "results"
        genome_dir = results_root / "antismash" / "Broken"
        genome_dir.mkdir(parents=True)
        (genome_dir / "Broken.antismash.json").write_text("{not json", encoding="utf-8")
        recorder = root / "recorder.py"
        write_recorder(recorder)
        call_log = root / "calls.jsonl"
        env = dict(os.environ)
        env.update(
            {
                "PROJECT_NAME": "broken",
                "PROJECTS_ROOT": str(root),
                "DATA_ROOT": str(root),
                "RESULTS_ROOT": str(results_root),
                "BGC_GCF_CROSSWALK_PY": str(recorder),
                "TARGETED_ANALYSIS_PY": str(recorder),
                "PYTHON_BIN": sys.executable,
                "SUMMARY_CALL_LOG": str(call_log),
            }
        )
        result = subprocess.run(
            ["bash", str(SUMMARY_SCRIPT)],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("JSONDecodeError", result.stderr)
        self.assertFalse(call_log.exists())


if __name__ == "__main__":
    unittest.main()
