from __future__ import annotations

import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
ENRICHER = REPO_ROOT / "bin" / "enrich_cross_kingdom_context.py"
BUILDER = REPO_ROOT / "bin" / "build_cross_kingdom_evidence.py"


class CrossKingdomContextTests(unittest.TestCase):
    def workspace(self) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return Path(temporary.name)

    @staticmethod
    def write_tsv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    @staticmethod
    def write_region(path: Path, sequence: str, *, edge: bool, mobile: bool = False) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        feature = ""
        if mobile:
            feature = (
                "     CDS             100..900\n"
                "                     /gene=\"mobA\"\n"
                "                     /product=\"IS-family transposase\"\n"
            )
        path.write_text(
            "LOCUS       region 6000 bp DNA linear\n"
            "FEATURES             Location/Qualifiers\n"
            "     region          1..6000\n"
            f"                     /contig_edge=\"{'True' if edge else 'False'}\"\n"
            f"{feature}"
            "ORIGIN\n"
            f"        1 {sequence}\n"
            "//\n",
            encoding="utf-8",
        )

    @staticmethod
    def cluster(prefix: str, count: int = 6) -> dict[str, object]:
        return {
            "loci": [
                {
                    "genes": [
                        {"uid": f"{prefix}{index}", "start": index * 100, "end": index * 100 + 90}
                        for index in range(count)
                    ]
                }
            ]
        }

    @staticmethod
    def write_panel_payload(panel: Path, clusters: list[dict[str, object]], links: list[dict[str, object]]) -> None:
        payload = {"clusters": clusters, "groups": [], "links": links}
        panel.write_text(
            "<script>const data="
            + json.dumps(payload, separators=(",", ":"))
            + ";function serialise(){}</script>",
            encoding="utf-8",
        )

    def make_fixture(self, root: Path) -> dict[str, Path]:
        candidates = root / "candidates.tsv"
        crosswalk = root / "results" / "summary" / "candidate_bgc_gcf_crosswalk.tsv"
        ranking = root / "results" / "summary" / "missing_ranking.tsv"
        manifest = root / "results" / "summary_tables" / "genome_taxon_manifest.tsv"
        antismash = root / "results" / "antismash"
        clinker = root / "results" / "clinker"
        genomes = root / "data" / "genomes"
        output = root / "enriched.tsv"

        self.write_tsv(
            candidates,
            ["candidate_id", "gcf_id", "cross_domain_gcf", "taxon_groups"],
            [
                {
                    "candidate_id": "GCF_X",
                    "gcf_id": "GCF_X",
                    "cross_domain_gcf": "yes",
                    "taxon_groups": "fungi;bacteria",
                }
            ],
        )
        self.write_tsv(
            crosswalk,
            ["genome", "taxon_group", "antismash_region", "gcf_id"],
            [
                {
                    "genome": "fungus_A",
                    "taxon_group": "fungi",
                    "antismash_region": "fungus_region001",
                    "gcf_id": "GCF_X",
                },
                {
                    "genome": "bacterium_B",
                    "taxon_group": "bacteria",
                    "antismash_region": "bacterium_region001",
                    "gcf_id": "GCF_X",
                },
            ],
        )
        self.write_tsv(
            manifest,
            ["genome_id", "taxon_group"],
            [
                {"genome_id": "fungus_A", "taxon_group": "fungi"},
                {"genome_id": "bacterium_B", "taxon_group": "bacteria"},
            ],
        )

        self.write_region(
            antismash / "fungus_A" / "fungus_region001.gbk",
            "G" * 6000,
            edge=False,
        )
        self.write_region(
            antismash / "bacterium_B" / "bacterium_region001.gbk",
            "ACGT" * 1500,
            edge=True,
            mobile=True,
        )
        for taxon, genome in (("fungi", "fungus_A"), ("bacteria", "bacterium_B")):
            genome_path = genomes / taxon / "demo" / f"{genome}.fna"
            genome_path.parent.mkdir(parents=True, exist_ok=True)
            genome_path.write_text(f">{genome}\n" + "ACGT" * 30_000 + "\n", encoding="utf-8")

        panel = clinker / "panels" / "cross_domain"
        self.write_tsv(
            panel / "panel_manifest.tsv",
            ["order", "role", "genome", "antismash_region", "gcf_id"],
            [
                {
                    "order": "1",
                    "role": "target",
                    "genome": "fungus_A",
                    "antismash_region": "fungus_region001",
                    "gcf_id": "GCF_X",
                },
                {
                    "order": "2",
                    "role": "comparator",
                    "genome": "bacterium_B",
                    "antismash_region": "bacterium_region001",
                    "gcf_id": "GCF_X",
                },
                {
                    "order": "3",
                    "role": "mibig_reference",
                    "genome": "BGC0000123.4",
                    "antismash_region": "BGC0000123.4",
                    "gcf_id": "GCF_X",
                },
            ],
        )

        def cluster(prefix: str) -> dict[str, object]:
            return {
                "loci": [
                    {
                        "genes": [
                            {"uid": f"{prefix}{index}", "start": index * 100, "end": index * 100 + 90}
                            for index in range(6)
                        ]
                    }
                ]
            }

        links: list[dict[str, object]] = []
        for index in range(6):
            links.append(
                {
                    "query": {"uid": f"F{index}"},
                    "target": {"uid": f"B{5 - index}"},
                    "identity": 0.75,
                    "similarity": 0.82,
                }
            )
            links.append(
                {
                    "query": {"uid": f"F{index}"},
                    "target": {"uid": f"R{index}"},
                    "identity": 0.80,
                    "similarity": 0.85,
                }
            )
        payload = {"clusters": [cluster("F"), cluster("B"), cluster("R")], "groups": [], "links": links}
        (panel / "panel.html").write_text(
            "<script>const data=" + json.dumps(payload, separators=(",", ":")) + ";function serialise(){}</script>",
            encoding="utf-8",
        )
        return {
            "candidates": candidates,
            "crosswalk": crosswalk,
            "ranking": ranking,
            "manifest": manifest,
            "antismash": antismash,
            "clinker": clinker,
            "genomes": genomes,
            "output": output,
            "panel": panel / "panel.html",
        }

    def run_enricher(
        self,
        paths: dict[str, Path],
        output: Path,
        *,
        explicit: bool = True,
        project_name: str = "demo",
    ) -> subprocess.CompletedProcess[str]:
        command = [sys.executable, str(ENRICHER)]
        if explicit:
            command.append("--explicit-request")
        command.extend(
            [
                "--candidates",
                str(paths["candidates"]),
                "--crosswalk",
                str(paths["crosswalk"]),
                "--ranking",
                str(paths["ranking"]),
                "--taxon-manifest",
                str(paths["manifest"]),
                "--antismash-root",
                str(paths["antismash"]),
                "--clinker-root",
                str(paths["clinker"]),
                "--genomes-root",
                str(paths["genomes"]),
                "--project-name",
                project_name,
                "--output",
                str(output),
                "--max-candidates",
                "25",
            ]
        )
        return subprocess.run(
            command,
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def test_derives_bounded_context_without_manufacturing_contamination_pass(self) -> None:
        root = self.workspace()
        paths = self.make_fixture(root)
        first = root / "first.tsv"
        second = root / "second.tsv"
        completed = self.run_enricher(paths, first)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        repeated = self.run_enricher(paths, second)
        self.assertEqual(repeated.returncode, 0, repeated.stdout + repeated.stderr)
        self.assertEqual(first.read_bytes(), second.read_bytes())

        with first.open("r", newline="", encoding="utf-8") as handle:
            row = next(csv.DictReader(handle, delimiter="\t"))
        self.assertEqual(row["synteny_support"], "yes")
        self.assertEqual(row["synteny_gene_order_matches"], "6")
        self.assertEqual(row["synteny_gene_count"], "6")
        self.assertEqual(row["synteny_basis"], "cross_domain_dataset_clinker")
        self.assertEqual(row["characterized_reference_support"], "yes")
        self.assertEqual(row["characterized_reference_id"], "BGC0000123.4")
        self.assertEqual(row["characterized_reference_similarity_percent"], "85")
        self.assertEqual(row["mobile_element_context"], "present")
        self.assertEqual(row["mobile_element_count"], "1")
        self.assertEqual(row["composition_outlier"], "")
        self.assertEqual(row["composition_deviation"], "yes")
        self.assertEqual(row["composition_region_gc_percent"], "100")
        self.assertEqual(row["composition_genome_gc_percent"], "50")
        self.assertEqual(row["composition_deviation_scope"], "maximum_across_evaluated_candidate_regions")
        self.assertEqual(row["composition_evaluated_region_count"], "2")
        self.assertEqual(row["composition_method"], "BGC_vs_whole_assembly_GC_abs_delta_ge_10pp_heuristic")
        self.assertEqual(row["assembly_region_edge_context"], "concern")
        self.assertEqual(row["assembly_check"], "concern")
        self.assertEqual(row["contamination_check"], "not_tested")
        self.assertEqual(row["paralogy_check"], "not_tested")
        self.assertEqual(row["sampling_check"], "not_tested")

        text = first.read_text(encoding="utf-8")
        self.assertNotIn(str(root), text)
        self.assertNotIn("ACGTACGTACGT", text)

        evidence_dir = root / "evidence"
        built = subprocess.run(
            [
                sys.executable,
                str(BUILDER),
                "--explicit-request",
                "--candidates",
                str(first),
                "--output-dir",
                str(evidence_dir),
            ],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(built.returncode, 0, built.stderr)
        payload = json.loads(
            (evidence_dir / "cross_kingdom_evidence.json").read_text(encoding="utf-8")
        )
        record = payload["records"][0]
        self.assertEqual(record["confidence"], "supportive")
        self.assertNotEqual(record["confidence"], "strong")
        self.assertEqual(record["quality_context"]["contamination"], "unknown")
        self.assertIn(
            "Computational context does not establish an evolutionary event, mechanism, or direction.",
            record["evidence_card"],
        )

    def test_synteny_uses_true_minimum_cluster_coverage(self) -> None:
        root = self.workspace()
        paths = self.make_fixture(root)
        links = [
            {
                "query": {"uid": f"F{index}"},
                "target": {"uid": f"B{index}"},
                "identity": 0.8,
                "similarity": 0.82,
            }
            for index in range(5)
        ]
        links.extend(
            {
                "query": {"uid": f"F{index}"},
                "target": {"uid": f"R{index}"},
                "identity": 0.8,
                "similarity": 0.85,
            }
            for index in range(5)
        )
        self.write_panel_payload(
            paths["panel"],
            [self.cluster("F", 5), self.cluster("B", 100), self.cluster("R", 6)],
            links,
        )
        output = root / "coverage.tsv"
        completed = self.run_enricher(paths, output)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        with output.open(newline="", encoding="utf-8") as handle:
            row = next(csv.DictReader(handle, delimiter="	"))
        self.assertEqual(row["synteny_support"], "no")
        self.assertEqual(row["synteny_gene_order_matches"], "5")
        self.assertEqual(row["synteny_homolog_pair_count"], "5")
        self.assertEqual(row["synteny_min_cluster_coverage"], "0.05")

    def test_zero_similarity_or_low_identity_links_are_not_synteny(self) -> None:
        root = self.workspace()
        paths = self.make_fixture(root)
        links = [
            {
                "query": {"uid": f"F{index}"},
                "target": {"uid": f"B{index}"},
                "identity": 0.0,
                "similarity": 0.0,
            }
            for index in range(6)
        ]
        links.extend(
            {
                "query": {"uid": f"F{index}"},
                "target": {"uid": f"R{index}"},
                "identity": 0.8,
                "similarity": 0.85,
            }
            for index in range(6)
        )
        self.write_panel_payload(
            paths["panel"],
            [self.cluster("F"), self.cluster("B"), self.cluster("R")],
            links,
        )
        output = root / "invalid-links.tsv"
        completed = self.run_enricher(paths, output)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        with output.open(newline="", encoding="utf-8") as handle:
            row = next(csv.DictReader(handle, delimiter="	"))
        self.assertEqual(row["synteny_support"], "")
        self.assertEqual(row["synteny_homolog_pair_count"], "")
        self.assertEqual(row["characterized_reference_support"], "yes")

    def test_reference_method_precedence_and_strict_antismash_percent(self) -> None:
        root = self.workspace()
        paths = self.make_fixture(root)
        self.write_tsv(
            paths["ranking"],
            ["gcf_id", "antismash_knowncluster_accession", "antismash_knowncluster_similarity_score"],
            [{
                "gcf_id": "GCF_X",
                "antismash_knowncluster_accession": "BGC0000999",
                "antismash_knowncluster_similarity_score": "99",
            }],
        )
        output = root / "method.tsv"
        completed = self.run_enricher(paths, output)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        with output.open(newline="", encoding="utf-8") as handle:
            row = next(csv.DictReader(handle, delimiter="	"))
        self.assertEqual(row["characterized_reference_id"], "BGC0000123.4")
        self.assertEqual(row["characterized_reference_similarity_percent"], "85")
        self.assertEqual(row["characterized_reference_method"], "clinker_MIBiG_median_protein_similarity")

        strict_root = self.workspace()
        strict_paths = self.make_fixture(strict_root)
        empty_clinker = strict_root / "empty-clinker"
        empty_clinker.mkdir()
        strict_paths["clinker"] = empty_clinker
        self.write_tsv(
            strict_paths["ranking"],
            ["gcf_id", "antismash_knowncluster_accession", "antismash_knowncluster_similarity_score"],
            [{
                "gcf_id": "GCF_X",
                "antismash_knowncluster_accession": "BGC0000999",
                "antismash_knowncluster_similarity_score": "1",
            }],
        )
        strict_output = strict_root / "one-percent.tsv"
        strict = self.run_enricher(strict_paths, strict_output)
        self.assertEqual(strict.returncode, 0, strict.stdout + strict.stderr)
        with strict_output.open(newline="", encoding="utf-8") as handle:
            strict_row = next(csv.DictReader(handle, delimiter="	"))
        self.assertEqual(strict_row["characterized_reference_support"], "no")
        self.assertEqual(strict_row["characterized_reference_similarity_percent"], "1")
        self.assertEqual(
            strict_row["characterized_reference_method"],
            "antiSMASH_KnownClusterBlast_reference_gene_match_coverage",
        )

    def test_declared_taxon_and_non_symlink_path_are_immutable(self) -> None:
        root = self.workspace()
        paths = self.make_fixture(root)
        self.write_tsv(
            paths["crosswalk"],
            ["genome", "taxon_group", "antismash_region", "gcf_id"],
            [{
                "genome": "fungus_A",
                "taxon_group": "fungi",
                "antismash_region": "fungus_region001",
                "gcf_id": "GCF_X",
            }],
        )
        correct = paths["genomes"] / "fungi" / "demo" / "fungus_A.fna"
        correct.unlink()
        wrong_taxon = paths["genomes"] / "bacteria" / "demo" / "fungus_A.fna"
        wrong_taxon.write_text(">wrong\n" + "G" * 120_000 + "\n", encoding="utf-8")
        output = root / "wrong-taxon.tsv"
        completed = self.run_enricher(paths, output)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        with output.open(newline="", encoding="utf-8") as handle:
            row = next(csv.DictReader(handle, delimiter="	"))
        self.assertEqual(row["composition_deviation"], "")

        symlink_root = self.workspace()
        symlink_paths = self.make_fixture(symlink_root)
        self.write_tsv(
            symlink_paths["crosswalk"],
            ["genome", "taxon_group", "antismash_region", "gcf_id"],
            [{
                "genome": "fungus_A",
                "taxon_group": "fungi",
                "antismash_region": "fungus_region001",
                "gcf_id": "GCF_X",
            }],
        )
        symlink_genome = symlink_paths["genomes"] / "fungi" / "demo" / "fungus_A.fna"
        outside = symlink_root / "outside.fna"
        outside.write_text(">outside\n" + "G" * 120_000 + "\n", encoding="utf-8")
        symlink_genome.unlink()
        symlink_genome.symlink_to(outside)
        symlink_output = symlink_root / "symlink.tsv"
        symlinked = self.run_enricher(symlink_paths, symlink_output)
        self.assertEqual(symlinked.returncode, 0, symlinked.stdout + symlinked.stderr)
        with symlink_output.open(newline="", encoding="utf-8") as handle:
            symlink_row = next(csv.DictReader(handle, delimiter="	"))
        self.assertEqual(symlink_row["composition_deviation"], "")

    def test_project_traversal_and_symlinked_panel_are_rejected(self) -> None:
        root = self.workspace()
        paths = self.make_fixture(root)
        invalid = self.run_enricher(paths, root / "invalid.tsv", project_name="../demo")
        self.assertNotEqual(invalid.returncode, 0)
        self.assertIn("project-name", invalid.stdout)

        external_panel = root / "outside-panel.html"
        external_panel.write_bytes(paths["panel"].read_bytes())
        paths["panel"].unlink()
        paths["panel"].symlink_to(external_panel)
        output = root / "panel-symlink.tsv"
        completed = self.run_enricher(paths, output)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        with output.open(newline="", encoding="utf-8") as handle:
            row = next(csv.DictReader(handle, delimiter="	"))
        self.assertEqual(row["synteny_support"], "")
        self.assertEqual(row["characterized_reference_support"], "")

    def test_clear_region_edges_do_not_manufacture_assembly_pass(self) -> None:
        root = self.workspace()
        paths = self.make_fixture(root)
        self.write_region(
            paths["antismash"] / "bacterium_B" / "bacterium_region001.gbk",
            "ACGT" * 1500,
            edge=False,
            mobile=True,
        )
        output = root / "clear-edge.tsv"
        completed = self.run_enricher(paths, output)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        with output.open(newline="", encoding="utf-8") as handle:
            row = next(csv.DictReader(handle, delimiter="	"))
        self.assertEqual(row["assembly_region_edge_context"], "clear")
        self.assertEqual(row["assembly_check"], "not_tested")

    def test_member_and_streaming_resource_bounds_are_enforced(self) -> None:
        root = self.workspace()
        paths = self.make_fixture(root)
        long_genome = paths["genomes"] / "fungi" / "demo" / "fungus_A.fna"
        long_genome.write_text(">fungus_A\n" + "ACGT" * 300_000 + "\n", encoding="utf-8")
        streamed_output = root / "streamed.tsv"
        streamed = self.run_enricher(paths, streamed_output)
        self.assertEqual(streamed.returncode, 0, streamed.stdout + streamed.stderr)
        with streamed_output.open(newline="", encoding="utf-8") as handle:
            streamed_row = next(csv.DictReader(handle, delimiter="	"))
        self.assertEqual(streamed_row["composition_evaluated_region_count"], "2")

        bounded_root = self.workspace()
        bounded_paths = self.make_fixture(bounded_root)
        self.write_tsv(
            bounded_paths["crosswalk"],
            ["genome", "taxon_group", "antismash_region", "gcf_id"],
            [
                {
                    "genome": f"fungus_{index}",
                    "taxon_group": "fungi",
                    "antismash_region": f"region_{index}",
                    "gcf_id": "GCF_X",
                }
                for index in range(2001)
            ],
        )
        bounded_output = bounded_root / "too-many-members.tsv"
        bounded = self.run_enricher(bounded_paths, bounded_output)
        self.assertNotEqual(bounded.returncode, 0)
        self.assertIn("member bound", bounded.stdout)
        self.assertFalse(bounded_output.exists())

    def test_rejected_panels_and_manifests_consume_the_cumulative_budget(self) -> None:
        import importlib

        bin_dir = str(REPO_ROOT / "bin")
        if bin_dir not in sys.path:
            sys.path.insert(0, bin_dir)
        context_module = importlib.import_module("enrich_putative_transfer_context")

        root = self.workspace()
        clinker = root / "clinker"
        panel_paths: list[Path] = []
        manifest_paths: list[Path] = []
        for name in ("a", "b"):
            panel_dir = clinker / name
            manifest = panel_dir / "panel_manifest.tsv"
            self.write_tsv(
                manifest,
                ["order", "role", "genome", "gcf_id"],
                [
                    {
                        "order": "1",
                        "role": "candidate",
                        "genome": f"genome_{name}",
                        "gcf_id": "GCF_X",
                    }
                ],
            )
            panel = panel_dir / "panel.html"
            panel.write_bytes(b"malformed-panel" + b"x" * 96)
            manifest_paths.append(manifest)
            panel_paths.append(panel)

        cumulative_limit = (
            manifest_paths[0].stat().st_size
            + panel_paths[0].stat().st_size
            + manifest_paths[1].stat().st_size
            + panel_paths[1].stat().st_size
            - 1
        )
        rejected = context_module.ContextInputError("malformed panel")
        with (
            mock.patch.object(
                context_module, "MAX_PANEL_TOTAL_BYTES", cumulative_limit
            ),
            mock.patch.object(context_module, "MAX_PANEL_BYTES", 1024),
            mock.patch.object(
                context_module,
                "bounded_panel_payload",
                side_effect=rejected,
            ) as payload_reader,
        ):
            synteny, references = context_module.panel_observations(
                clinker.resolve(), {}, {"GCF_X"}
            )
        self.assertEqual(synteny, {})
        self.assertEqual(references, {})
        self.assertEqual(payload_reader.call_count, 1)

        with mock.patch.object(context_module, "MAX_PANEL_SCAN_DIRS", 1):
            with self.assertRaisesRegex(
                context_module.ContextInputError, "directory bound"
            ):
                context_module.bounded_panel_manifests(clinker.resolve())

        with mock.patch.object(context_module, "MAX_PANEL_SCAN_ENTRIES", 1):
            with self.assertRaisesRegex(
                context_module.ContextInputError, "entry bound"
            ):
                context_module.bounded_panel_manifests(clinker.resolve())

    def test_explicit_request_is_required(self) -> None:
        root = self.workspace()
        paths = self.make_fixture(root)
        output = root / "implicit.tsv"
        completed = self.run_enricher(paths, output, explicit=False)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("explicit-request", completed.stdout)
        self.assertFalse(output.exists())

    def test_helper_has_no_download_install_or_core_ranking_surface(self) -> None:
        text = ENRICHER.read_text(encoding="utf-8")
        for forbidden in (
            "import requests",
            "import urllib",
            "import subprocess",
            "pip install",
            "docker pull",
            "curl ",
            "wget ",
            "priority_score",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
